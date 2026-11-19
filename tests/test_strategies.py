
import pandas as pd
import pytest

from app.strategies import (
    completed_candles,
    evaluate_exit,
    evaluate_signal,
)


def make_candles(strategy="intraday", rows=60):
    if strategy == "intraday":
        timestamps = pd.date_range(
            "2026-11-18 03:45:00",
            periods=rows,
            freq="5min",
            tz="UTC",
        )
    else:
        timestamps = pd.date_range(
            end="2026-11-18",
            periods=rows,
            freq="D",
            tz="UTC",
        )

    data = {
        "timestamp": timestamps,
        "open": [104.0] * rows,
        "high": [106.0] * rows,
        "low": [103.0] * rows,
        "close": [105.0] * rows,
        "volume": [1500.0] * rows,
        "ema_20": [103.0] * rows,
        "ema_50": [101.0] * rows,
        "ema_200": [98.0] * rows,
        "rsi_14": [60.0] * rows,
        "macd": [2.0] * rows,
        "macd_signal": [1.0] * rows,
        "macd_histogram": [1.0] * rows,
        "atr_14": [2.0] * rows,
        "volume_sma_20": [1000.0] * rows,
        "vwap": [102.0] * rows,
    }

    return pd.DataFrame(data)


def test_intraday_generates_strong_buy():
    candles = make_candles("intraday")

    result = evaluate_signal(
        candles,
        "intraday",
        now=pd.Timestamp("2026-11-18 10:00:00", tz="UTC"),
        symbol="RELIANCE",
    )

    assert result.strategy == "intraday"
    assert result.symbol == "RELIANCE"
    assert result.signal == "STRONG_BUY"
    assert result.score >= 75


def test_swing_generates_strong_buy():
    candles = make_candles("swing", rows=220)

    result = evaluate_signal(
        candles,
        "swing",
        now=pd.Timestamp("2026-11-19 10:00:00", tz="UTC"),
        symbol="RELIANCE",
    )

    assert result.strategy == "swing"
    assert result.signal == "STRONG_BUY"
    assert result.score >= 75


def test_intraday_ignores_incomplete_candle():
    candles = make_candles("intraday")

    now = candles.iloc[-1]["timestamp"] + pd.Timedelta(minutes=4)

    completed = completed_candles(
        candles,
        "intraday",
        now=now,
    )

    assert len(completed) == len(candles) - 1


def test_daily_ignores_today_before_market_close():
    candles = make_candles("swing", rows=220)

    today = pd.DataFrame([{
        **candles.iloc[-1].to_dict(),
        "timestamp": pd.Timestamp("2026-11-19 00:00:00", tz="UTC"),
    }])

    candles = pd.concat([candles.iloc[:-1], today], ignore_index=True)

    completed = completed_candles(
        candles,
        "swing",
        now=pd.Timestamp("2026-11-19 09:00:00", tz="UTC"),
    )

    assert completed.iloc[-1]["timestamp"].date().isoformat() == "2026-11-17"

def test_insufficient_data_does_not_generate_buy():
    candles = make_candles("intraday", rows=30)

    result = evaluate_signal(
        candles,
        "intraday",
        now=pd.Timestamp("2026-11-18 10:00:00", tz="UTC"),
    )

    assert result.signal == "INSUFFICIENT_DATA"
    assert result.score == 0


def test_stop_loss_has_priority_if_stop_and_target_both_hit():
    candles = make_candles("intraday")

    candles.loc[candles.index[-1], "low"] = 94.0
    candles.loc[candles.index[-1], "high"] = 111.0

    result = evaluate_exit(
        candles,
        "intraday",
        stop_loss=95.0,
        target_price=110.0,
        now=pd.Timestamp("2026-11-18 10:00:00", tz="UTC"),
    )

    assert result.should_exit is True
    assert result.reason == "STOP_LOSS"
    assert result.exit_price == 95.0


def test_target_triggers_exit():
    candles = make_candles("intraday")
    candles.loc[candles.index[-1], "high"] = 111.0

    result = evaluate_exit(
        candles,
        "intraday",
        stop_loss=95.0,
        target_price=110.0,
        now=pd.Timestamp("2026-11-18 10:00:00", tz="UTC"),
    )

    assert result.should_exit is True
    assert result.reason == "TARGET"
    assert result.exit_price == 110.0


def test_invalid_strategy_is_rejected():
    with pytest.raises(ValueError):
        evaluate_signal(make_candles(), "scalping")
