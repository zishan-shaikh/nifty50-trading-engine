from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.backtesting.config import BacktestConfig
from app.backtesting.execution import Trade, open_trade, close_trade
from app.strategies import evaluate_signal, evaluate_exit
from app.backtesting.simulator import _candle_close_time, _candle_open_time, _is_last_intraday_candle


REQUIRED_COLUMNS = {
    "timestamp", "open", "high", "low", "close", "volume", "atr_14"
}


@dataclass
class PortfolioBacktestResult:
    buy_threshold: int
    initial_capital: float
    ending_capital: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def net_pnl(self) -> float:
        return sum(trade.net_pnl for trade in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.net_pnl > 0 for t in self.trades) / len(self.trades) * 100

    @property
    def gross_profit(self) -> float:
        return sum(t.net_pnl for t in self.trades if t.net_pnl > 0)

    @property
    def gross_loss(self) -> float:
        return abs(sum(t.net_pnl for t in self.trades if t.net_pnl < 0))

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / self.gross_loss

    @property
    def max_drawdown(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        equity = self.equity_curve["equity"].astype(float)
        peaks = equity.cummax()
        safe_peaks = peaks.where(peaks != 0)
        drawdown = (peaks - equity) / safe_peaks
        return float(drawdown.max() * 100) if not drawdown.empty else 0.0

    def trades_by_strategy(self) -> pd.DataFrame:
        return _group_trade_metrics(self.trades, "strategy")

    def trades_by_symbol(self) -> pd.DataFrame:
        return _group_trade_metrics(self.trades, "symbol")

    def summary(self) -> dict[str, Any]:
        return {
            "buy_threshold": self.buy_threshold,
            "initial_capital": self.initial_capital,
            "ending_capital": self.ending_capital,
            "net_pnl": self.net_pnl,
            "total_trades": self.total_trades,
            "win_rate_pct": self.win_rate,
            "profit_factor": self.profit_factor,
            "max_drawdown_pct": self.max_drawdown,
        }


@dataclass
class _PendingEntry:
    score: int
    atr: float


@dataclass
class _OpenPosition:
    trade: Trade
    last_price: float
    last_time: pd.Timestamp


def _group_trade_metrics(trades: list[Trade], field_name: str) -> pd.DataFrame:
    rows = []
    groups: dict[str, list[Trade]] = {}
    for trade in trades:
        key = str(getattr(trade, field_name))
        groups.setdefault(key, []).append(trade)

    for key, group in sorted(groups.items()):
        winners = [t for t in group if t.net_pnl > 0]
        losers = [t for t in group if t.net_pnl < 0]
        gross_profit = sum(t.net_pnl for t in winners)
        gross_loss = abs(sum(t.net_pnl for t in losers))
        rows.append({
            field_name: key,
            "trades": len(group),
            "net_pnl": sum(t.net_pnl for t in group),
            "win_rate_pct": len(winners) / len(group) * 100 if group else 0.0,
            "profit_factor": (
                gross_profit / gross_loss if gross_loss else
                (float("inf") if gross_profit else 0.0)
            ),
        })
    return pd.DataFrame(rows)


def _prepare_frame(frame: pd.DataFrame, symbol: str, strategy: str) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(
            f"{symbol} ({strategy}) is missing columns: {sorted(missing)}"
        )
    if frame.empty:
        return frame.copy()

    df = frame.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = (
        df.dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )
    numeric = ["open", "high", "low", "close", "volume", "atr_14"]
    for column in numeric:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if df[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise ValueError(f"{symbol} ({strategy}) has invalid OHLCV values")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{symbol} ({strategy}) has non-positive OHLC prices")
    if (
        (df["high"] < df["low"]).any()
        or (df["high"] < df["open"]).any()
        or (df["high"] < df["close"]).any()
        or (df["low"] > df["open"]).any()
        or (df["low"] > df["close"]).any()
    ):
        raise ValueError(f"{symbol} ({strategy}) has invalid OHLC candles")
    return df


def _portfolio_equity(
    cash: float,
    positions: dict[tuple[str, str], _OpenPosition],
) -> float:
    # Cash is reduced by entry notional and entry costs. Add current market
    # value of open positions to obtain marked-to-market portfolio equity.
    return cash + sum(
        position.last_price * position.trade.quantity
        for position in positions.values()
    )


def simulate_portfolio(
    data_by_strategy: dict[str, dict[str, pd.DataFrame]],
    buy_threshold: int,
    config: BacktestConfig,
) -> PortfolioBacktestResult:
    """
    Backtest all supplied symbols using one shared cash balance.

    Input shape:
        {
            "intraday": {"RELIANCE": dataframe, ...},
            "swing": {"RELIANCE": dataframe, ...},
        }

    Signals are evaluated only after each candle completes. Entries execute
    at the next available candle's open. At a shared timestamp, all candle
    closes/exits are processed first, then pending entries are ranked by
    descending score, followed by symbol and strategy for deterministic ties.
    """
    config.validate()
    if buy_threshold not in config.buy_thresholds:
        raise ValueError(f"Threshold {buy_threshold} is not configured")

    unknown = set(data_by_strategy) - {"intraday", "swing"}
    if unknown:
        raise ValueError(f"Unsupported strategies: {sorted(unknown)}")

    frames: dict[tuple[str, str], pd.DataFrame] = {}
    close_events: dict[pd.Timestamp, list[tuple[str, str, int]]] = {}
    open_events: dict[pd.Timestamp, list[tuple[str, str, int]]] = {}

    for strategy in ("intraday", "swing"):
        for symbol, source in sorted(data_by_strategy.get(strategy, {}).items()):
            frame = _prepare_frame(source, symbol, strategy)
            if frame.empty:
                continue
            key = (symbol, strategy)
            frames[key] = frame
            for index, row in frame.iterrows():
                open_time = _candle_open_time(row["timestamp"], strategy)
                close_time = _candle_close_time(row["timestamp"], strategy)
                open_events.setdefault(open_time, []).append((symbol, strategy, index))
                close_events.setdefault(close_time, []).append((symbol, strategy, index))

    cash = float(config.initial_capital)
    positions: dict[tuple[str, str], _OpenPosition] = {}
    pending: dict[tuple[str, str], _PendingEntry] = {}
    trades: list[Trade] = []
    equity_rows: list[dict[str, Any]] = []

    all_times = sorted(set(close_events) | set(open_events))
    for event_time in all_times:
        # Phase 1: process completed candles, exits, square-offs and signals.
        # This releases capital before any entries at the same timestamp.
        for symbol, strategy, index in sorted(
            close_events.get(event_time, []),
            key=lambda item: (item[0], item[1]),
        ):
            key = (symbol, strategy)
            frame = frames[key]
            row = frame.iloc[index]
            history = frame.iloc[: index + 1].copy()
            close_time = _candle_close_time(row["timestamp"], strategy)

            if key in positions:
                position = positions[key]
                position.last_price = float(row["close"])
                position.last_time = close_time

                exit_signal = evaluate_exit(
                    candles=history,
                    strategy=strategy,
                    stop_loss=position.trade.stop_loss,
                    target_price=position.trade.target_price,
                    now=close_time,
                )
                if exit_signal.should_exit:
                    closed = close_trade(
                        trade=position.trade,
                        exit_time=close_time,
                        raw_exit_price=float(exit_signal.exit_price),
                        exit_reason=exit_signal.reason or "STRATEGY_EXIT",
                        config=config,
                    )
                    cash += closed.exit_price * closed.quantity - closed.exit_cost
                    trades.append(closed)
                    del positions[key]

            if (
                strategy == "intraday"
                and key in positions
                and _is_last_intraday_candle(frame, index)
            ):
                position = positions[key]
                closed = close_trade(
                    trade=position.trade,
                    exit_time=close_time,
                    raw_exit_price=float(row["close"]),
                    exit_reason="END_OF_SESSION",
                    config=config,
                )
                cash += closed.exit_price * closed.quantity - closed.exit_cost
                trades.append(closed)
                del positions[key]

            # A new signal is allowed after an exit on this candle, just as
            # in the existing single-symbol simulator.
            if index < len(frame) - 1 and key not in positions:
                signal = evaluate_signal(
                    candles=history,
                    strategy=strategy,
                    now=close_time,
                    symbol=symbol,
                    buy_threshold=buy_threshold,
                )
                atr = row["atr_14"]
                if (
                    signal.signal in ("BUY", "STRONG_BUY")
                    and signal.score >= buy_threshold
                    and pd.notna(atr)
                    and float(atr) > 0
                ):
                    pending[key] = _PendingEntry(
                        score=int(signal.score),
                        atr=float(atr),
                    )
            elif key in positions:
                pending.pop(key, None)

            equity_rows.append({
                "timestamp": event_time,
                "cash": cash,
                "equity": _portfolio_equity(cash, positions),
                "open_positions": len(positions),
            })

        # Phase 2: all entries at this timestamp compete for shared capital.
        # Signals with the highest score get first access to available cash.
        candidates = []
        for symbol, strategy, index in open_events.get(event_time, []):
            key = (symbol, strategy)
            if key in pending and key not in positions:
                candidates.append((
                    -pending[key].score,
                    symbol,
                    strategy,
                    index,
                ))

        for _, symbol, strategy, index in sorted(candidates):
            key = (symbol, strategy)
            signal = pending.pop(key, None)
            if signal is None or key in positions:
                continue

            row = frames[key].iloc[index]
            trade = open_trade(
                symbol=symbol,
                strategy=strategy,
                entry_time=_candle_open_time(row["timestamp"], strategy),
                raw_entry_price=float(row["open"]),
                atr=signal.atr,
                signal_score=signal.score,
                available_capital=cash,
                config=config,
            )
            if trade is None:
                continue

            required_cash = (
                trade.entry_price * trade.quantity + trade.entry_cost
            )
            # Do not permit fees to push the portfolio below zero cash.
            if required_cash > cash + 1e-9:
                continue

            cash -= required_cash
            positions[key] = _OpenPosition(
                trade=trade,
                last_price=float(row["open"]),
                last_time=_candle_open_time(row["timestamp"], strategy),
            )

        # Record equity after entries too, so entry costs are reflected at
        # the execution timestamp rather than waiting for the next candle.
        equity_rows.append({
            "timestamp": event_time,
            "cash": cash,
            "equity": _portfolio_equity(cash, positions),
            "open_positions": len(positions),
        })

    # Liquidate any remaining positions at each symbol/strategy's last
    # available completed candle. No positions are carried beyond the data.
    for key, position in sorted(positions.items()):
        symbol, strategy = key
        closed = close_trade(
            trade=position.trade,
            exit_time=position.last_time,
            raw_exit_price=position.last_price,
            exit_reason="END_OF_DATA",
            config=config,
        )
        cash += closed.exit_price * closed.quantity - closed.exit_cost
        trades.append(closed)

    if all_times:
        equity_rows.append({
            "timestamp": all_times[-1],
            "cash": cash,
            "equity": cash,
            "open_positions": 0,
        })

    equity_curve = pd.DataFrame(equity_rows)
    if not equity_curve.empty:
        equity_curve = (
            equity_curve.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True)
        )

    return PortfolioBacktestResult(
        buy_threshold=buy_threshold,
        initial_capital=float(config.initial_capital),
        ending_capital=cash,
        trades=sorted(trades, key=lambda t: (t.entry_time, t.symbol, t.strategy)),
        equity_curve=equity_curve,
    )


def run_threshold_experiments(
    data_by_strategy: dict[str, dict[str, pd.DataFrame]],
    config: BacktestConfig,
) -> dict[int, PortfolioBacktestResult]:
    """Run each configured threshold with a fresh, independent portfolio."""
    config.validate()
    return {
        threshold: simulate_portfolio(data_by_strategy, threshold, config)
        for threshold in config.buy_thresholds
    }
