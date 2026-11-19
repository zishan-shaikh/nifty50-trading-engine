
from sqlalchemy import select, func
from datetime import datetime, timezone

from app.models import Position


PAPER_CAPITAL = 100_000.0
RISK_PER_TRADE = 1_000.0

STRATEGY_INTERVALS = {
    "intraday": "5m",
    "swing": "1d",
}


def calculate_position_size(
    entry_price: float,
    stop_loss: float,
    risk_amount: float = RISK_PER_TRADE,
    available_capital: float = PAPER_CAPITAL,
) -> int:
    """
    Calculate long-only quantity using risk and available capital.

    Quantity is limited by:
      1. Maximum planned loss at stop-loss.
      2. Available paper capital.
    """
    if entry_price <= 0 or stop_loss <= 0:
        raise ValueError("Entry and stop-loss prices must be positive.")

    if stop_loss >= entry_price:
        raise ValueError("For a long position, stop-loss must be below entry.")

    if risk_amount <= 0 or available_capital <= 0:
        raise ValueError("Risk and available capital must be positive.")

    risk_per_share = entry_price - stop_loss

    quantity_by_risk = int(risk_amount // risk_per_share)
    quantity_by_capital = int(available_capital // entry_price)

    return max(0, min(quantity_by_risk, quantity_by_capital))


def get_open_positions(session, strategy=None):
    """Return open positions, optionally filtered by strategy."""
    stmt = select(Position).where(Position.status == "OPEN")

    if strategy is not None:
        if strategy not in STRATEGY_INTERVALS:
            raise ValueError("Strategy must be 'intraday' or 'swing'.")
        stmt = stmt.where(Position.strategy == strategy)

    return session.scalars(
        stmt.order_by(Position.symbol, Position.strategy)
    ).all()


def get_deployed_capital(session) -> float:
    """Calculate capital currently allocated to all open positions."""
    value = session.scalar(
        select(
            func.coalesce(
                func.sum(Position.quantity * Position.entry_price),
                0.0,
            )
        ).where(Position.status == "OPEN")
    )

    return float(value or 0.0)


def open_position(
    session,
    symbol: str,
    strategy: str,
    entry_price: float,
    stop_loss: float,
    target_price: float,
    risk_amount: float = RISK_PER_TRADE,
    total_capital: float = PAPER_CAPITAL,
):
    """
    Open a long position for one strategy.

    Intraday and swing positions in the same stock are independent.
    """
    symbol = symbol.strip().upper()

    if not symbol:
        raise ValueError("Symbol cannot be empty.")

    if strategy not in STRATEGY_INTERVALS:
        raise ValueError("Strategy must be 'intraday' or 'swing'.")

    if target_price <= entry_price:
        raise ValueError("For a long position, target must exceed entry.")

    if entry_price <= 0 or stop_loss <= 0:
        raise ValueError("Entry and stop-loss prices must be positive.")

    existing = session.scalar(
        select(Position).where(
            Position.symbol == symbol,
            Position.strategy == strategy,
            Position.status == "OPEN",
        )
    )

    if existing:
        raise ValueError(
            f"An open {strategy} position already exists for {symbol}."
        )

    deployed = get_deployed_capital(session)
    available = total_capital - deployed

    if available <= 0:
        raise ValueError("No paper capital available.")

    quantity = calculate_position_size(
        entry_price=entry_price,
        stop_loss=stop_loss,
        risk_amount=risk_amount,
        available_capital=available,
    )

    if quantity <= 0:
        raise ValueError(
            "Position quantity is zero. Insufficient capital or risk budget."
        )

    position = Position(
        symbol=symbol,
        strategy=strategy,
        interval=STRATEGY_INTERVALS[strategy],
        side="LONG",
        quantity=quantity,
        entry_price=float(entry_price),
        stop_loss=float(stop_loss),
        target_price=float(target_price),
        status="OPEN",
    )

    try:
        session.add(position)
        session.commit()
        session.refresh(position)
    except Exception:
        session.rollback()
        raise

    return position


def close_position(
    session,
    symbol: str,
    strategy: str,
    exit_price: float,
    reason: str = "SIGNAL_EXIT",
):
    """
    Close only the position belonging to the specified strategy.
    """
    symbol = symbol.strip().upper()

    if strategy not in STRATEGY_INTERVALS:
        raise ValueError("Strategy must be 'intraday' or 'swing'.")

    if exit_price <= 0:
        raise ValueError("Exit price must be positive.")

    position = session.scalar(
        select(Position).where(
            Position.symbol == symbol,
            Position.strategy == strategy,
            Position.status == "OPEN",
        )
    )

    if position is None:
        raise ValueError(
            f"No open {strategy} position found for {symbol}."
        )

    position.status = "CLOSED"
    position.exit_price = float(exit_price)
    position.closed_at = datetime.now(timezone.utc)
    position.exit_reason = reason

    position.realized_pnl = (
        (float(exit_price) - position.entry_price) * position.quantity
    )

    try:
        session.commit()
        session.refresh(position)
    except Exception:
        session.rollback()
        raise

    return position


def get_portfolio_summary(
    session,
    total_capital: float = PAPER_CAPITAL,
):
    """Return capital allocation and realized P&L summary."""
    deployed = get_deployed_capital(session)

    realized = session.scalar(
        select(
            func.coalesce(func.sum(Position.realized_pnl), 0.0)
        ).where(Position.status == "CLOSED")
    )

    open_intraday = session.scalar(
        select(func.count(Position.id)).where(
            Position.status == "OPEN",
            Position.strategy == "intraday",
        )
    )

    open_swing = session.scalar(
        select(func.count(Position.id)).where(
            Position.status == "OPEN",
            Position.strategy == "swing",
        )
    )

    return {
        "total_capital": float(total_capital),
        "deployed_capital": deployed,
        "available_capital": float(total_capital - deployed),
        "realized_pnl": float(realized or 0.0),
        "open_intraday_positions": int(open_intraday or 0),
        "open_swing_positions": int(open_swing or 0),
    }
