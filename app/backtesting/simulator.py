
from dataclasses import dataclass, field

import pandas as pd

from app.backtesting.config import BacktestConfig
from app.backtesting.execution import Trade, open_trade, close_trade
from app.strategies import evaluate_signal, evaluate_exit


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    buy_threshold: int
    initial_capital: float
    ending_capital: float
    trades: list[Trade] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def net_pnl(self) -> float:
        return sum(t.net_pnl for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0

        winners = sum(t.net_pnl > 0 for t in self.trades)
        return winners / len(self.trades) * 100


def _candle_close_time(
    timestamp: pd.Timestamp,
    strategy: str,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(timestamp)

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")

    if strategy == "intraday":
        return timestamp + pd.Timedelta(minutes=5)

    local_date = timestamp.tz_convert("Asia/Kolkata").date()

    return pd.Timestamp(
        f"{local_date} 15:30:00",
        tz="Asia/Kolkata",
    ).tz_convert("UTC")


def _candle_open_time(
    timestamp: pd.Timestamp,
    strategy: str,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(timestamp)

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")

    if strategy == "intraday":
        return timestamp

    # Daily candle execution starts at 09:15 IST.
    local_date = timestamp.tz_convert(
        "Asia/Kolkata"
    ).date()

    return pd.Timestamp(
        f"{local_date} 09:15:00",
        tz="Asia/Kolkata",
    ).tz_convert("UTC")


def _is_last_intraday_candle(
    candles: pd.DataFrame,
    index: int,
) -> bool:
    current_timestamp = candles.iloc[index]["timestamp"]

    current_time = current_timestamp.tz_convert(
        "Asia/Kolkata"
    )

    # Do not square off if another candle exists later
    # in the same trading session.
    local_timestamps = candles["timestamp"].dt.tz_convert(
        "Asia/Kolkata"
    )

    later_same_day = (
        (local_timestamps.dt.date == current_time.date())
        & (candles["timestamp"] > current_timestamp)
    ).any()

    if later_same_day:
        return False

    # NSE final candle normally starts at 15:25.
    # Use 15:20 only if the 15:25 candle is unavailable.
    return (
        current_time.hour == 15
        and current_time.minute >= 20
    )



def simulate_symbol(
    candles: pd.DataFrame,
    symbol: str,
    strategy: str,
    buy_threshold: int,
    config: BacktestConfig,
) -> BacktestResult:

    config.validate()

    if strategy not in ("intraday", "swing"):
        raise ValueError(f"Invalid strategy: {strategy}")

    if buy_threshold not in config.buy_thresholds:
        raise ValueError(
            f"Threshold {buy_threshold} is not configured"
        )

    required = {
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "atr_14",
    }

    missing = required - set(candles.columns)

    if missing:
        raise ValueError(
            f"Missing candle columns: {sorted(missing)}"
        )

    if candles.empty:
        return BacktestResult(
            symbol=symbol,
            strategy=strategy,
            buy_threshold=buy_threshold,
            initial_capital=config.initial_capital,
            ending_capital=config.initial_capital,
        )

    df = candles.copy()

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        utc=True,
        errors="coerce",
    )

    df = (
        df.dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )

    if df.empty:
        raise ValueError("No valid candle timestamps")

    numeric_columns = [
        "open", "high", "low", "close", "volume", "atr_14"
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    if df[numeric_columns[:5]].isna().any().any():
        raise ValueError("OHLCV contains invalid values")

    if (
        (df["open"] <= 0).any()
        or (df["high"] <= 0).any()
        or (df["low"] <= 0).any()
        or (df["close"] <= 0).any()
    ):
        raise ValueError("OHLC prices must be positive")

    if (
        (df["high"] < df["low"]).any()
        or (df["high"] < df["open"]).any()
        or (df["high"] < df["close"]).any()
        or (df["low"] > df["open"]).any()
        or (df["low"] > df["close"]).any()
    ):
        raise ValueError("Invalid OHLC candle")

    cash = config.initial_capital
    trades: list[Trade] = []

    open_position: Trade | None = None
    pending_signal = None

    for index in range(len(df)):
        row = df.iloc[index]
        timestamp = row["timestamp"]

        close_time = _candle_close_time(
            timestamp,
            strategy,
        )

        # 1. Execute the signal generated by the previous candle.
        # Entry happens at this candle's open, never its close.
        if pending_signal is not None and open_position is None:

            atr = pending_signal["atr"]

            trade = open_trade(
                symbol=symbol,
                strategy=strategy,
                entry_time=_candle_open_time(timestamp, strategy),
                raw_entry_price=float(row["open"]),
                atr=atr,
                signal_score=pending_signal["score"],
                available_capital=cash,
                config=config,
            )

            if trade is not None:
                required_cash = (
                    trade.entry_price * trade.quantity
                    + trade.entry_cost
                )

                if required_cash <= cash:
                    cash -= required_cash
                    open_position = trade

            pending_signal = None

        # 2. Check the currently open position against this candle.
        if open_position is not None:

            current_history = df.iloc[:index + 1].copy()

            exit_signal = evaluate_exit(
                candles=current_history,
                strategy=strategy,
                stop_loss=open_position.stop_loss,
                target_price=open_position.target_price,
                now=close_time,
            )

            if exit_signal.should_exit:
                closed_trade = close_trade(
                    trade=open_position,
                    exit_time=close_time,
                    raw_exit_price=exit_signal.exit_price,
                    exit_reason=exit_signal.reason,
                    config=config,
                )

                cash += (
                    closed_trade.exit_price
                    * closed_trade.quantity
                    - closed_trade.exit_cost
                )

                trades.append(closed_trade)
                open_position = None

        # 3. Intraday positions must not remain overnight.
        if (
            strategy == "intraday"
            and open_position is not None
            and _is_last_intraday_candle(df, index)
        ):
            closed_trade = close_trade(
                trade=open_position,
                exit_time=close_time,
                raw_exit_price=float(row["close"]),
                exit_reason="END_OF_SESSION",
                config=config,
            )

            cash += (
                closed_trade.exit_price
                * closed_trade.quantity
                - closed_trade.exit_cost
            )

            trades.append(closed_trade)
            open_position = None

        # 4. Generate a signal after the current candle closes.
        # It can only be executed at the next candle's open.
        if index < len(df) - 1 and open_position is None:

            history = df.iloc[:index + 1].copy()

            signal = evaluate_signal(
                candles=history,
                strategy=strategy,
                now=close_time,
                symbol=symbol,
                buy_threshold=buy_threshold,
            )

            if (
                signal.signal in ("BUY", "STRONG_BUY")
                and signal.score >= buy_threshold
                and pd.notna(row["atr_14"])
                and float(row["atr_14"]) > 0
            ):
                pending_signal = {
                    "score": signal.score,
                    "atr": float(row["atr_14"]),
                }

    # 5. Close any remaining position at the end of available data.
    if open_position is not None:
        last_row = df.iloc[-1]

        final_time = _candle_close_time(
            last_row["timestamp"],
            strategy,
        )

        closed_trade = close_trade(
            trade=open_position,
            exit_time=final_time,
            raw_exit_price=float(last_row["close"]),
            exit_reason="END_OF_DATA",
            config=config,
        )

        cash += (
            closed_trade.exit_price
            * closed_trade.quantity
            - closed_trade.exit_cost
        )

        trades.append(closed_trade)

    return BacktestResult(
        symbol=symbol,
        strategy=strategy,
        buy_threshold=buy_threshold,
        initial_capital=config.initial_capital,
        ending_capital=cash,
        trades=trades,
    )
