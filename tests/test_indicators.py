import numpy as np
import pandas as pd

from app.indicators import calculate_indicators


def sample_candles(count=250, interval="1d"):
    timestamps = pd.date_range(
        "2026-01-01 09:15",
        periods=count,
        freq="5min" if interval != "1d" else "D",
        tz="Asia/Kolkata",
    )

    close = np.linspace(100, 150, count)

    return pd.DataFrame({
        "timestamp": timestamps,
        "open": close - 0.5,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": np.full(count, 1000),
    })


def test_indicator_columns_are_created():
    result = calculate_indicators(sample_candles(), interval="1d")

    expected = [
        "ema_20",
        "ema_50",
        "ema_200",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_histogram",
        "atr_14",
        "volume_sma_20",
        "vwap",
    ]

    for column in expected:
        assert column in result.columns


def test_ema_warmup_periods():
    result = calculate_indicators(sample_candles(250), interval="1d")

    assert result["ema_20"].iloc[:19].isna().all()
    assert pd.notna(result["ema_20"].iloc[19])

    assert result["ema_50"].iloc[:49].isna().all()
    assert pd.notna(result["ema_50"].iloc[49])

    assert result["ema_200"].iloc[:199].isna().all()
    assert pd.notna(result["ema_200"].iloc[199])


def test_rsi_is_bounded_between_zero_and_100():
    result = calculate_indicators(sample_candles(100), interval="1d")

    valid_rsi = result["rsi_14"].dropna()

    assert not valid_rsi.empty
    assert valid_rsi.between(0, 100).all()


def test_atr_is_positive():
    result = calculate_indicators(sample_candles(100), interval="1d")

    valid_atr = result["atr_14"].dropna()

    assert not valid_atr.empty
    assert (valid_atr > 0).all()


def test_daily_vwap_is_not_calculated():
    result = calculate_indicators(sample_candles(100), interval="1d")

    assert result["vwap"].isna().all()


def test_intraday_vwap_resets_each_session():
    candles = sample_candles(6, interval="5m")

    # Put the final three candles on the next trading day.
    candles.loc[3:, "timestamp"] += pd.Timedelta(days=1)

    result = calculate_indicators(candles, interval="5m")

    # VWAP of the first candle in each session equals its typical price.
    first_day_first = result.iloc[0]
    second_day_first = result.iloc[3]

    expected_first = (
        first_day_first["high"]
        + first_day_first["low"]
        + first_day_first["close"]
    ) / 3

    expected_second = (
        second_day_first["high"]
        + second_day_first["low"]
        + second_day_first["close"]
    ) / 3

    assert np.isclose(first_day_first["vwap"], expected_first)
    assert np.isclose(second_day_first["vwap"], expected_second)


def test_empty_input_returns_empty_dataframe():
    empty = pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )

    result = calculate_indicators(empty)

    assert result.empty