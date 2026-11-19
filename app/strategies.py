
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd


STRATEGY_INTERVALS = {
    "intraday": "5m",
    "swing": "1d",
}

BUY_CANDIDATE_SCORE = 60
STRONG_BUY_SCORE = 75

NSE_CLOSE_TIME = time(15, 30)

COMMON_COLUMNS = {
    "timestamp", "open", "high", "low", "close", "volume",
    "ema_20", "ema_50", "rsi_14", "macd",
    "macd_signal", "macd_histogram", "volume_sma_20",
}

SWING_COLUMNS = COMMON_COLUMNS | {"ema_200"}


@dataclass
class StrategySignal:
    strategy: str
    symbol: str | None
    signal: str
    score: int
    reasons: list[str]
    timestamp: pd.Timestamp | None


@dataclass
class ExitSignal:
    should_exit: bool
    reason: str | None = None
    exit_price: float | None = None


def completed_candles(
    candles: pd.DataFrame,
    strategy: str,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Return only candles whose time period has fully completed."""
    if strategy not in STRATEGY_INTERVALS:
        raise ValueError(f"Unsupported strategy: {strategy}")

    if candles.empty:
        return candles.copy()

    df = candles.copy()
    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True, errors="coerce"
    )
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

    current_time = (
        pd.Timestamp.now(tz="UTC")
        if now is None
        else pd.Timestamp(now)
    )

    if current_time.tzinfo is None:
        current_time = current_time.tz_localize("UTC")
    else:
        current_time = current_time.tz_convert("UTC")

    if strategy == "intraday":
        # Yahoo intraday timestamps represent the candle start.
        candle_end = df["timestamp"] + pd.Timedelta(minutes=5)
        return df.loc[candle_end <= current_time].reset_index(drop=True)

    # Daily timestamps are normalized to the exchange date.
    local_now = current_time.tz_convert("Asia/Kolkata")
    local_today = local_now.date()

    candle_dates = df["timestamp"].dt.date
    previous_sessions = candle_dates < local_today
    todays_session_closed = (
        (candle_dates == local_today)
        & (local_now.time() >= NSE_CLOSE_TIME)
    )

    return df.loc[
        previous_sessions | todays_session_closed
    ].reset_index(drop=True)


def _empty_signal(strategy: str, signal: str) -> StrategySignal:
    return StrategySignal(
        strategy=strategy,
        symbol=None,
        signal=signal,
        score=0,
        reasons=[],
        timestamp=None,
    )


def evaluate_signal(
    candles: pd.DataFrame,
    strategy: str,
    now: pd.Timestamp | None = None,
    symbol: str | None = None,
    buy_threshold: int = BUY_CANDIDATE_SCORE,
) -> StrategySignal:
    """
    Evaluate the latest completed candle.

    Scores are candidate-ranking rules, not guarantees of profitability.
    """
    if strategy not in STRATEGY_INTERVALS:
        raise ValueError(f"Unsupported strategy: {strategy}")
    if not 0 <= buy_threshold <= STRONG_BUY_SCORE:
        raise ValueError(
            f"buy_threshold must be between 0 and {STRONG_BUY_SCORE}"
        )

    if candles.empty:
        return _empty_signal(strategy, "NO_DATA")

    required = (
        SWING_COLUMNS if strategy == "swing" else COMMON_COLUMNS
    )
    missing = required - set(candles.columns)

    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df = completed_candles(candles, strategy, now)

    minimum_rows = 200 if strategy == "swing" else 50
    if len(df) < minimum_rows:
        return _empty_signal(strategy, "INSUFFICIENT_DATA")

    row = df.iloc[-1]
    previous = df.iloc[-6] if len(df) >= 6 else None

    if pd.isna(row["ema_20"]) or pd.isna(row["ema_50"]):
        return _empty_signal(strategy, "INDICATORS_NOT_READY")

    score = 0
    reasons: list[str] = []

    close = float(row["close"])
    ema20 = float(row["ema_20"])
    ema50 = float(row["ema_50"])
    rsi = row["rsi_14"]
    macd = row["macd"]
    macd_signal = row["macd_signal"]
    volume = row["volume"]
    volume_average = row["volume_sma_20"]

    if strategy == "intraday":
        # Trend: 25 points
        if close > ema20 > ema50:
            score += 25
            reasons.append("Price above rising trend structure")
        elif close > ema20:
            score += 12
            reasons.append("Price above EMA 20")

        # Momentum: 25 points
        if pd.notna(rsi) and 50 <= rsi <= 70:
            score += 15
            reasons.append("RSI in bullish momentum range")

        if (
            pd.notna(macd)
            and pd.notna(macd_signal)
            and macd > macd_signal
        ):
            score += 10
            reasons.append("MACD bullish")

        # Volume: 20 points
        if (
            pd.notna(volume_average)
            and volume_average > 0
            and volume >= volume_average * 1.2
        ):
            score += 20
            reasons.append("Volume at least 1.2x average")
        elif (
            pd.notna(volume_average)
            and volume_average > 0
            and volume >= volume_average
        ):
            score += 12
            reasons.append("Volume at or above average")

        # VWAP: 20 points
        if pd.notna(row.get("vwap")) and close > float(row["vwap"]):
            score += 20
            reasons.append("Price above session VWAP")

        # Additional confirmation: 10 points
        if previous is not None:
            if (
                pd.notna(previous["ema_20"])
                and ema20 > float(previous["ema_20"])
            ):
                score += 5
                reasons.append("EMA 20 rising")

        if close > float(row["open"]):
            score += 5
            reasons.append("Bullish candle")

    else:
        # Trend: 30 points
        ema200 = row["ema_200"]

        if pd.notna(ema200):
            ema200 = float(ema200)

            if close > ema20 > ema50 > ema200:
                score += 30
                reasons.append("Strong EMA 20/50/200 alignment")
            elif close > ema50 > ema200:
                score += 20
                reasons.append("Price above EMA 50 and EMA 200")
            elif close > ema200:
                score += 12
                reasons.append("Price above EMA 200")

        # Momentum: 25 points
        if pd.notna(rsi) and 50 <= rsi <= 70:
            score += 15
            reasons.append("RSI in bullish momentum range")

        if (
            pd.notna(macd)
            and pd.notna(macd_signal)
            and macd > macd_signal
        ):
            score += 10
            reasons.append("MACD bullish")

        # Volume: 15 points
        if (
            pd.notna(volume_average)
            and volume_average > 0
            and volume >= volume_average
        ):
            score += 15
            reasons.append("Volume at or above average")

        # Price confirmation: 10 points
        if close > ema20:
            score += 10
            reasons.append("Close above EMA 20")

        # Longer-term confirmation: 20 points
        if previous is not None:
            if (
                pd.notna(previous["ema_20"])
                and ema20 > float(previous["ema_20"])
            ):
                score += 10
                reasons.append("EMA 20 rising")

            if (
                pd.notna(previous["ema_50"])
                and ema50 > float(previous["ema_50"])
            ):
                score += 10
                reasons.append("EMA 50 rising")

    if score >= STRONG_BUY_SCORE:
        signal = "STRONG_BUY"
    elif score >= buy_threshold:
        signal = "BUY"
    else:
        signal = "NO_ENTRY"

    return StrategySignal(
        strategy=strategy,
        symbol=symbol,
        signal=signal,
        score=score,
        reasons=reasons,
        timestamp=row["timestamp"],
    )


def evaluate_exit(
    candles: pd.DataFrame,
    strategy: str,
    stop_loss: float,
    target_price: float,
    now: pd.Timestamp | None = None,
) -> ExitSignal:
    """
    Evaluate an existing LONG position only.

    If stop-loss and target are both touched in one candle,
    stop-loss is assumed to execute first (conservative assumption).
    """
    if strategy not in STRATEGY_INTERVALS:
        raise ValueError(f"Unsupported strategy: {strategy}")

    if stop_loss <= 0 or target_price <= 0:
        raise ValueError("Stop-loss and target must be positive")

    if candles.empty:
        return ExitSignal(False)

    df = completed_candles(candles, strategy, now)
    if df.empty:
        return ExitSignal(False)

    row = df.iloc[-1]

    open_price = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])

    # Check stop first if both levels were touched in the same candle.
    if low <= stop_loss:
        return ExitSignal(
            True,
            "STOP_LOSS",
            min(open_price, stop_loss),
        )

    if high >= target_price:
        return ExitSignal(
            True,
            "TARGET",
            target_price,
        )

    if strategy == "intraday":
        technical_exit = (
            pd.notna(row["ema_20"])
            and pd.notna(row["macd_histogram"])
            and close < float(row["ema_20"])
            and float(row["macd_histogram"]) < 0
        )

        if technical_exit:
            return ExitSignal(True, "INTRADAY_TREND_EXIT", close)

    else:
        technical_exit = (
            pd.notna(row["ema_50"])
            and close < float(row["ema_50"])
        )

        momentum_exit = (
            pd.notna(row["rsi_14"])
            and pd.notna(row["macd_histogram"])
            and float(row["rsi_14"]) < 45
            and float(row["macd_histogram"]) < 0
        )

        if technical_exit or momentum_exit:
            return ExitSignal(True, "SWING_TREND_EXIT", close)

    return ExitSignal(False)
