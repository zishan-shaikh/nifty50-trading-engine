from __future__ import annotations

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
}


def calculate_indicators(
    candles: pd.DataFrame,
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Calculate technical indicators from OHLCV candles.

    Supported intervals:
      - 1d: daily indicators; VWAP is left empty.
      - Intraday intervals such as 5m: indicators plus session VWAP.

    The input DataFrame must contain:
      timestamp, open, high, low, close, volume

    Returns the original OHLCV data plus indicator columns.
    Raw input data is not modified.
    """
    if candles.empty:
        return candles.copy()

    missing = REQUIRED_COLUMNS - set(candles.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = candles.copy()

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df.sort_values("timestamp")
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    df = df.reset_index(drop=True)

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    df = df[
        (df["high"] >= df["low"])
        & (df["volume"] >= 0)
    ].reset_index(drop=True)

    if df.empty:
        return df

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Exponential moving averages
    df["ema_20"] = close.ewm(
        span=20, adjust=False, min_periods=20
    ).mean()

    df["ema_50"] = close.ewm(
        span=50, adjust=False, min_periods=50
    ).mean()

    df["ema_200"] = close.ewm(
        span=200, adjust=False, min_periods=200
    ).mean()

    # RSI 14 using Wilder-style exponential smoothing
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    average_gain = gain.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    average_loss = loss.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    relative_strength = average_gain / average_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + relative_strength))

    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100)
    rsi = rsi.mask((average_loss == 0) & (average_gain == 0), 50)

    df["rsi_14"] = rsi

    # MACD 12 / 26 / 9
    ema_12 = close.ewm(
        span=12, adjust=False, min_periods=12
    ).mean()

    ema_26 = close.ewm(
        span=26, adjust=False, min_periods=26
    ).mean()

    df["macd"] = ema_12 - ema_26

    df["macd_signal"] = df["macd"].ewm(
        span=9, adjust=False, min_periods=9
    ).mean()

    df["macd_histogram"] = df["macd"] - df["macd_signal"]

    # Average True Range 14
    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["atr_14"] = true_range.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    # Average volume over 20 candles
    df["volume_sma_20"] = df["volume"].rolling(
        window=20, min_periods=20
    ).mean()

    # VWAP is meaningful here for intraday candles only.
    df["vwap"] = np.nan

    if interval != "1d":
        local_timestamps = df["timestamp"].dt.tz_convert("Asia/Kolkata")
        session_dates = local_timestamps.dt.date

        typical_price = (high + low + close) / 3
        price_volume = typical_price * df["volume"]

        cumulative_price_volume = price_volume.groupby(
            session_dates, sort=False
        ).cumsum()

        cumulative_volume = df["volume"].groupby(
            session_dates, sort=False
        ).cumsum()

        df["vwap"] = (
            cumulative_price_volume
            / cumulative_volume.replace(0, np.nan)
        )

    return df