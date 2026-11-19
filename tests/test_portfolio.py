import pandas as pd
import pytest
from types import SimpleNamespace

from app.backtesting.config import BacktestConfig
from app.backtesting.portfolio import (
    run_threshold_experiments,
    simulate_portfolio,
)


def make_swing_frame(periods=202, price=100.0, atr=0.1):
    timestamps = pd.date_range(
        "2025-01-01",
        periods=periods,
        freq="B",
        tz="UTC",
    )
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": [price] * periods,
        "high": [price + 0.1] * periods,
        "low": [price - 0.1] * periods,
        "close": [price] * periods,
        "volume": [100_000] * periods,
        "atr_14": [atr] * periods,
        "ema_20": [price - 1] * periods,
        "ema_50": [price - 2] * periods,
        "ema_200": [price - 3] * periods,
        "rsi_14": [55.0] * periods,
        "macd": [1.0] * periods,
        "macd_signal": [0.5] * periods,
        "macd_histogram": [0.5] * periods,
        "volume_sma_20": [90_000] * periods,
        "vwap": [price - 1] * periods,
    })


def buy_signal(score):
    return SimpleNamespace(
        signal="STRONG_BUY" if score >= 75 else "BUY",
        score=score,
    )


def test_shared_capital_allows_only_affordable_simultaneous_entries(monkeypatch):
    import app.backtesting.portfolio as portfolio

    monkeypatch.setattr(
        portfolio,
        "evaluate_signal",
        lambda **kwargs: buy_signal(65),
    )
    data = {
        "swing": {
            "AAA": make_swing_frame(),
            "BBB": make_swing_frame(),
        }
    }
    config = BacktestConfig(
        initial_capital=100_000,
        risk_per_trade=1_000,
        buy_thresholds=(60, 65, 75),
        max_position_value=100_000,
    )

    result = simulate_portfolio(data, 60, config)

    # Both candidates arrive together and have equal scores. The deterministic
    # symbol tie-break chooses AAA. BBB cannot reuse the same initial capital.
    entry_symbols = {trade.symbol for trade in result.trades}
    assert entry_symbols == {"AAA"}
    assert result.ending_capital >= 0
    assert result.ending_capital <= config.initial_capital


def test_higher_score_gets_priority_when_capital_is_limited(monkeypatch):
    import app.backtesting.portfolio as portfolio

    def fake_signal(**kwargs):
        return buy_signal(75 if kwargs["symbol"] == "BBB" else 65)

    monkeypatch.setattr(portfolio, "evaluate_signal", fake_signal)
    data = {
        "swing": {
            "AAA": make_swing_frame(),
            "BBB": make_swing_frame(),
        }
    }
    config = BacktestConfig(
        initial_capital=100_000,
        risk_per_trade=1_000,
        buy_thresholds=(60, 65, 75),
        max_position_value=100_000,
    )

    result = simulate_portfolio(data, 60, config)

    assert {trade.symbol for trade in result.trades} == {"BBB"}


def test_intraday_and_swing_are_distinct_position_keys(monkeypatch):
    import app.backtesting.portfolio as portfolio

    monkeypatch.setattr(
        portfolio,
        "evaluate_signal",
        lambda **kwargs: buy_signal(65),
    )

    swing = make_swing_frame(periods=202, price=50, atr=1.0)

    intraday_times = pd.date_range(
        "2026-10-01 03:45:00+00:00",
        periods=60,
        freq="5min",
    )
    intraday = pd.DataFrame({
        "timestamp": intraday_times,
        "open": [50.0] * 60,
        "high": [50.2] * 60,
        "low": [49.8] * 60,
        "close": [50.0] * 60,
        "volume": [10_000] * 60,
        "atr_14": [0.5] * 60,
        "ema_20": [49.0] * 60,
        "ema_50": [48.0] * 60,
        "rsi_14": [55.0] * 60,
        "macd": [1.0] * 60,
        "macd_signal": [0.5] * 60,
        "macd_histogram": [0.5] * 60,
        "volume_sma_20": [9_000] * 60,
        "vwap": [49.0] * 60,
    })

    # The same ticker is supplied under two strategy keys. Both independent
    # strategy streams should be able to generate their own trade.
    config = BacktestConfig(
        initial_capital=100_000,
        risk_per_trade=500,
        buy_thresholds=(60, 65, 75),
        max_position_value=50_000,
    )
    result = simulate_portfolio(
        {"intraday": {"AAA": intraday}, "swing": {"AAA": swing}},
        60,
        config,
    )

    assert result.ending_capital >= 0
    assert {trade.strategy for trade in result.trades} == {"intraday", "swing"}
    assert all(trade.symbol == "AAA" for trade in result.trades)


def test_threshold_experiments_start_with_fresh_capital(monkeypatch):
    import app.backtesting.portfolio as portfolio

    class NoSignal:
        signal = "NO_ENTRY"
        score = 0

    monkeypatch.setattr(
        portfolio,
        "evaluate_signal",
        lambda **kwargs: NoSignal(),
    )
    data = {"swing": {"AAA": make_swing_frame()}}
    config = BacktestConfig(
        initial_capital=100_000,
        buy_thresholds=(60, 65, 75),
    )

    results = run_threshold_experiments(data, config)

    assert set(results) == {60, 65, 75}
    for result in results.values():
        assert result.initial_capital == 100_000
        assert result.ending_capital == 100_000
        assert result.total_trades == 0


def test_portfolio_rejects_missing_required_columns():
    bad_frame = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=2, tz="UTC"),
        "open": [100, 100],
    })
    config = BacktestConfig()

    with pytest.raises(ValueError, match="missing columns"):
        simulate_portfolio(
            {"swing": {"AAA": bad_frame}},
            60,
            config,
        )
