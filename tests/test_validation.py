
import pandas as pd

from app.validation import normalize_ohlcv


def test_normalize_sorts_and_deduplicates():
    idx = pd.to_datetime([
        "2025-01-02 09:20",
        "2025-01-02 09:15",
        "2025-01-02 09:15"
    ])

    raw = pd.DataFrame({
        "Open": [10, 9, 9],
        "High": [11, 10, 10],
        "Low": [9, 8, 8],
        "Close": [10.5, 9.5, 9.6],
        "Volume": [100, 90, 95]
    }, index=idx)

    out = normalize_ohlcv(raw)

    assert len(out) == 2
    assert out.iloc[0]["close"] == 9.6
    assert out["timestamp"].is_monotonic_increasing


def test_invalid_ohlc_removed():
    idx = pd.to_datetime(["2025-01-02 09:15"])

    raw = pd.DataFrame({
        "Open": [10],
        "High": [9],
        "Low": [8],
        "Close": [10],
        "Volume": [10]
    }, index=idx)

    assert normalize_ohlcv(raw).empty


def test_empty_input():
    assert normalize_ohlcv(pd.DataFrame()).empty


def test_daily_timestamp_preserves_exchange_date():
    idx = pd.DatetimeIndex(
        ["2026-11-19 00:00:00"],
        tz="Asia/Kolkata"
    )

    raw = pd.DataFrame({
        "Open": [100],
        "High": [105],
        "Low": [98],
        "Close": [103],
        "Volume": [1000]
    }, index=idx)

    result = normalize_ohlcv(raw, interval="1d")

    assert (
        result.iloc[0]["timestamp"]
        == pd.Timestamp("2026-11-19 00:00:00", tz="UTC")
    )
