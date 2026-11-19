from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    # Portfolio
    initial_capital: float = 100_000.0
    risk_per_trade: float = 1_000.0

    # Signal experiments
    buy_thresholds: tuple[int, ...] = (60, 65, 75)

    # ATR-based risk management
    intraday_atr_multiplier: float = 1.5
    swing_atr_multiplier: float = 2.0
    reward_to_risk: float = 2.0

    # Execution
    allow_long_only: bool = True
    intraday_interval: str = "5m"
    swing_interval: str = "1d"

    # Provisional transaction costs.
    # These are configurable assumptions, NOT verified Dhan charges.
    brokerage_rate: float = 0.0003
    slippage_rate: float = 0.0005
    other_charges_rate: float = 0.0002

    # Prevent unrealistic position concentration
    max_position_value: float = 100_000.0

    def validate(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("Initial capital must be positive")

        if self.risk_per_trade <= 0:
            raise ValueError("Risk per trade must be positive")

        if not self.buy_thresholds:
            raise ValueError("At least one BUY threshold is required")

        if any(
            threshold < 0 or threshold > 75
            for threshold in self.buy_thresholds
        ):
            raise ValueError("BUY thresholds must be between 0 and 75")

        if self.intraday_atr_multiplier <= 0:
            raise ValueError("Intraday ATR multiplier must be positive")

        if self.swing_atr_multiplier <= 0:
            raise ValueError("Swing ATR multiplier must be positive")

        if self.reward_to_risk <= 0:
            raise ValueError("Reward-to-risk must be positive")

        if min(
            self.brokerage_rate,
            self.slippage_rate,
            self.other_charges_rate,
        ) < 0:
            raise ValueError("Transaction cost rates cannot be negative")
