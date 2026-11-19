
import pytest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Position
from app.position_manager import (
    calculate_position_size,
    open_position,
    close_position,
    get_open_positions,
    get_portfolio_summary,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Position.__table__.create(engine)

    with Session(engine) as db:
        yield db

    engine.dispose()


def test_position_size_respects_risk():
    quantity = calculate_position_size(
        entry_price=1000,
        stop_loss=950,
        risk_amount=1000,
        available_capital=100000,
    )

    assert quantity == 20


def test_position_size_respects_available_capital():
    quantity = calculate_position_size(
        entry_price=1000,
        stop_loss=900,
        risk_amount=10000,
        available_capital=5000,
    )

    assert quantity == 5


def test_intraday_and_swing_positions_are_separate(session):
    intraday = open_position(
        session, "RELIANCE", "intraday", 1000, 950, 1100
    )

    swing = open_position(
        session, "RELIANCE", "swing", 1000, 900, 1200
    )

    assert intraday.strategy == "intraday"
    assert swing.strategy == "swing"

    assert intraday.interval == "5m"
    assert swing.interval == "1d"

    assert len(get_open_positions(session)) == 2


def test_closing_intraday_does_not_close_swing(session):
    open_position(
        session, "RELIANCE", "intraday", 1000, 950, 1100
    )

    open_position(
        session, "RELIANCE", "swing", 1000, 900, 1200
    )

    closed = close_position(
        session, "RELIANCE", "intraday", 1050
    )

    assert closed.status == "CLOSED"
    assert closed.realized_pnl == 1000

    remaining = get_open_positions(session)

    assert len(remaining) == 1
    assert remaining[0].symbol == "RELIANCE"
    assert remaining[0].strategy == "swing"


def test_duplicate_open_position_is_rejected(session):
    open_position(
        session, "TCS", "intraday", 1000, 950, 1100
    )

    with pytest.raises(ValueError, match="already exists"):
        open_position(
            session, "TCS", "intraday", 1000, 900, 1200
        )


def test_portfolio_capital_is_shared(session):
    open_position(
        session,
        "RELIANCE",
        "intraday",
        1000,
        950,
        1100,
        risk_amount=1000,
        total_capital=10000,
    )

    summary = get_portfolio_summary(session, total_capital=10000)

    assert summary["deployed_capital"] <= 10000
    assert summary["available_capital"] >= 0
    assert summary["open_intraday_positions"] == 1
    assert summary["open_swing_positions"] == 0


def test_invalid_long_position_is_rejected(session):
    with pytest.raises(ValueError, match="stop-loss"):
        open_position(
            session, "INFY", "swing", 1000, 1050, 1200
        )
