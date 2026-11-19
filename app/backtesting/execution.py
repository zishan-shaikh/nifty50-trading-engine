
from dataclasses import dataclass
from typing import Literal

from app.backtesting.config import BacktestConfig


@dataclass
class Trade:
    symbol: str
    strategy: Literal["intraday", "swing"]
    entry_time: object
    entry_price: float
    quantity: int
    stop_loss: float
    target_price: float
    atr: float
    signal_score: int

    exit_time: object | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    gross_pnl: float = 0.0
    entry_cost: float = 0.0
    exit_cost: float = 0.0
    net_pnl: float = 0.0

    @property
    def is_closed(self) -> bool:
        return self.exit_time is not None


def get_atr_multiplier(
    strategy: str,
    config: BacktestConfig,
) -> float:
    if strategy == "intraday":
        return config.intraday_atr_multiplier

    if strategy == "swing":
        return config.swing_atr_multiplier

    raise ValueError(f"Invalid strategy: {strategy}")


def calculate_position_quantity(
    entry_price: float,
    stop_loss: float,
    available_capital: float,
    config: BacktestConfig,
) -> int:
    if entry_price <= 0 or stop_loss <= 0:
        return 0

    risk_per_share = entry_price - stop_loss

    if risk_per_share <= 0:
        return 0

    risk_quantity = int(
        config.risk_per_trade / risk_per_share
    )

    capital_limit = min(
        available_capital,
        config.max_position_value,
    )

    capital_quantity = int(capital_limit / entry_price)

    return max(0, min(risk_quantity, capital_quantity))


def calculate_transaction_cost(
    turnover: float,
    config: BacktestConfig,
) -> float:
    if turnover < 0:
        raise ValueError("Turnover cannot be negative")

    return turnover * (
        config.brokerage_rate
        + config.other_charges_rate
    )


def calculate_entry_price(
    raw_price: float,
    config: BacktestConfig,
) -> float:
    if raw_price <= 0:
        raise ValueError("Entry price must be positive")

    # Slippage makes a long entry more expensive.
    return raw_price * (1 + config.slippage_rate)


def calculate_exit_price(
    raw_price: float,
    config: BacktestConfig,
) -> float:
    if raw_price <= 0:
        raise ValueError("Exit price must be positive")

    # Slippage makes a long exit less favourable.
    return raw_price * (1 - config.slippage_rate)


def open_trade(
    symbol: str,
    strategy: str,
    entry_time,
    raw_entry_price: float,
    atr: float,
    signal_score: int,
    available_capital: float,
    config: BacktestConfig,
) -> Trade | None:
    if strategy not in ("intraday", "swing"):
        raise ValueError(f"Invalid strategy: {strategy}")

    if not config.allow_long_only:
        raise ValueError("This simulator currently supports long-only trades")

    if raw_entry_price <= 0 or atr <= 0:
        return None

    entry_price = calculate_entry_price(
        raw_entry_price,
        config,
    )

    multiplier = get_atr_multiplier(strategy, config)

    stop_distance = atr * multiplier

    stop_loss = entry_price - stop_distance

    target_price = (
        entry_price
        + stop_distance * config.reward_to_risk
    )

    quantity = calculate_position_quantity(
        entry_price=entry_price,
        stop_loss=stop_loss,
        available_capital=available_capital,
        config=config,
    )

    if quantity <= 0:
        return None

    entry_cost = calculate_transaction_cost(
        entry_price * quantity,
        config,
    )

    return Trade(
        symbol=symbol,
        strategy=strategy,
        entry_time=entry_time,
        entry_price=entry_price,
        quantity=quantity,
        stop_loss=stop_loss,
        target_price=target_price,
        atr=atr,
        signal_score=signal_score,
        entry_cost=entry_cost,
    )


def close_trade(
    trade: Trade,
    exit_time,
    raw_exit_price: float,
    exit_reason: str,
    config: BacktestConfig,
) -> Trade:
    if trade.is_closed:
        raise ValueError("Trade is already closed")

    executed_exit_price = calculate_exit_price(
        raw_exit_price,
        config,
    )

    exit_turnover = executed_exit_price * trade.quantity

    exit_cost = calculate_transaction_cost(
        exit_turnover,
        config,
    )

    gross_pnl = (
        executed_exit_price - trade.entry_price
    ) * trade.quantity

    trade.exit_time = exit_time
    trade.exit_price = executed_exit_price
    trade.exit_reason = exit_reason

    trade.gross_pnl = gross_pnl
    trade.exit_cost = exit_cost

    trade.net_pnl = (
        gross_pnl
        - trade.entry_cost
        - trade.exit_cost
    )

    return trade
