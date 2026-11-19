
import pandas as pd
import pytest

import app.backtesting.simulator as simulator

from app.backtesting.config import BacktestConfig
from app.backtesting.execution import open_trade, close_trade
from app.strategies import StrategySignal, ExitSignal, evaluate_exit


@pytest.fixture
def config():
    return BacktestConfig()


def test_open_trade_respects_risk_and_atr_levels(config):
    trade = open_trade(
        symbol="RELIANCE",
        strategy="swing",
        entry_time=pd.Timestamp("2026-11-19", tz="UTC"),
        raw_entry_price=100,
        atr=10,
        signal_score=75,
        available_capital=100_000,
        config=config,
    )

    assert trade is not None
    assert trade.quantity > 0
    assert trade.entry_price == pytest.approx(100.05)
    assert trade.stop_loss == pytest.approx(80.05)
    assert trade.target_price == pytest.approx(140.05)

    planned_risk = (
        trade.entry_price - trade.stop_loss
    ) * trade.quantity

    assert planned_risk <= config.risk_per_trade


def test_open_trade_respects_available_capital(config):
    trade = open_trade(
        symbol="TCS",
        strategy="swing",
        entry_time=pd.Timestamp("2026-11-19", tz="UTC"),
        raw_entry_price=1000,
        atr=10,
        signal_score=75,
        available_capital=5000,
        config=config,
    )

    assert trade is not None

    required_cash = (
        trade.entry_price * trade.quantity
        + trade.entry_cost
    )

    assert required_cash <= 5000


def test_close_trade_calculates_net_pnl(config):
    trade = open_trade(
        symbol="RELIANCE",
        strategy="swing",
        entry_time=pd.Timestamp("2026-11-19", tz="UTC"),
        raw_entry_price=100,
        atr=10,
        signal_score=75,
        available_capital=100_000,
        config=config,
    )

    assert trade is not None

    closed = close_trade(
        trade=trade,
        exit_time=pd.Timestamp("2026-11-20", tz="UTC"),
        raw_exit_price=120,
        exit_reason="TARGET",
        config=config,
    )

    assert closed.is_closed
    assert closed.gross_pnl > 0
    assert closed.entry_cost > 0
    assert closed.exit_cost > 0
    assert closed.net_pnl == pytest.approx(
        closed.gross_pnl
        - closed.entry_cost
        - closed.exit_cost
    )


def test_close_trade_rejects_double_close(config):
    trade = open_trade(
        symbol="RELIANCE",
        strategy="swing",
        entry_time=pd.Timestamp("2026-11-19", tz="UTC"),
        raw_entry_price=100,
        atr=10,
        signal_score=75,
        available_capital=100_000,
        config=config,
    )

    assert trade is not None

    close_trade(
        trade,
        pd.Timestamp("2026-11-20", tz="UTC"),
        110,
        "TEST_EXIT",
        config,
    )

    with pytest.raises(ValueError, match="already closed"):
        close_trade(
            trade,
            pd.Timestamp("2026-11-21", tz="UTC"),
            115,
            "SECOND_EXIT",
            config,
        )


def test_simulator_enters_at_next_candle_open(
    monkeypatch,
    config,
):
    timestamps = pd.date_range(
        "2026-11-16",
        periods=3,
        freq="D",
        tz="UTC",
    )

    candles = pd.DataFrame({
        "timestamp": timestamps,
        "open": [90, 100, 105],
        "high": [95, 115, 120],
        "low": [85, 95, 100],
        "close": [92, 105, 110],
        "volume": [1000, 1200, 1500],
        "atr_14": [10, 10, 10],
    })

    def fake_evaluate_signal(
        candles,
        strategy,
        now=None,
        symbol=None,
        buy_threshold=60,
    ):
        if len(candles) == 1:
            return StrategySignal(
                strategy=strategy,
                symbol=symbol,
                signal="BUY",
                score=65,
                reasons=["Test signal"],
                timestamp=now,
            )

        return StrategySignal(
            strategy=strategy,
            symbol=symbol,
            signal="NO_ENTRY",
            score=0,
            reasons=[],
            timestamp=now,
        )

    def fake_evaluate_exit(
        candles,
        strategy,
        stop_loss,
        target_price,
        now=None,
    ):
        return ExitSignal(False)

    monkeypatch.setattr(
        simulator,
        "evaluate_signal",
        fake_evaluate_signal,
    )

    monkeypatch.setattr(
        simulator,
        "evaluate_exit",
        fake_evaluate_exit,
    )

    result = simulator.simulate_symbol(
        candles=candles,
        symbol="RELIANCE",
        strategy="swing",
        buy_threshold=60,
        config=config,
    )

    assert result.total_trades == 1

    trade = result.trades[0]

    # Signal came from candle 0.
    # Entry happens at the next trading session's 09:15 IST open.
    expected_entry_time = pd.Timestamp(
        "2026-11-17 09:15:00",
        tz="Asia/Kolkata",
    ).tz_convert("UTC")

    assert trade.entry_time == expected_entry_time
    assert trade.entry_price == pytest.approx(
        100 * (1 + config.slippage_rate)
    )

    assert trade.exit_reason == "END_OF_DATA"


def test_exit_prefers_stop_when_both_levels_are_hit():
    candles = pd.DataFrame({
        "timestamp": [
            pd.Timestamp("2026-11-19", tz="UTC")
        ],
        "open": [100],
        "high": [120],
        "low": [80],
        "close": [105],
    })

    result = evaluate_exit(
        candles=candles,
        strategy="swing",
        stop_loss=90,
        target_price=110,
        now=pd.Timestamp(
            "2026-11-20 10:00",
            tz="Asia/Kolkata",
        ),
    )

    assert result.should_exit
    assert result.reason == "STOP_LOSS"
    assert result.exit_price == 90


def test_intraday_square_off_uses_actual_last_candle():
    timestamps = pd.to_datetime([
        "2026-11-19 15:20:00+05:30",
        "2026-11-19 15:25:00+05:30",
    ]).tz_convert("UTC")

    candles = pd.DataFrame({
        "timestamp": timestamps,
    })

    # Do not square off at 15:20 if 15:25 exists.
    assert not simulator._is_last_intraday_candle(
        candles, 0
    )

    # Square off on the final 15:25 candle.
    assert simulator._is_last_intraday_candle(
        candles, 1
    )


def test_intraday_square_off_fallback_at_1520():
    candles = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-11-19 15:20:00+05:30",
        ]).tz_convert("UTC"),
    })

    assert simulator._is_last_intraday_candle(
        candles, 0
    )


def test_intraday_does_not_square_off_at_1415():
    candles = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-11-19 14:15:00+05:30",
        ]).tz_convert("UTC"),
    })

    assert not simulator._is_last_intraday_candle(
        candles, 0
    )
