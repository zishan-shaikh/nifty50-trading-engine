
from datetime import datetime, timezone

from sqlalchemy import (
    String, Boolean, DateTime, BigInteger, Integer,
    Float, Index, CheckConstraint, text, JSON
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Instrument(Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(String(100), default="fallback")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="yfinance")

    __table_args__ = (
        Index(
            "uq_candle_symbol_interval_timestamp",
            "symbol", "interval", "timestamp",
            unique=True,
        ),
    )


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    ema_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_200: Mapped[float | None] = mapped_column(Float, nullable=True)

    rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)

    macd: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_histogram: Mapped[float | None] = mapped_column(Float, nullable=True)

    atr_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_sma_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index(
            "uq_indicator_symbol_interval_timestamp",
            "symbol", "interval", "timestamp",
            unique=True,
        ),
        Index(
            "ix_indicator_symbol_interval",
            "symbol", "interval",
        ),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)

    # Separate intraday and swing positions
    strategy: Mapped[str] = mapped_column(String(16), nullable=False)

    interval: Mapped[str] = mapped_column(String(8), nullable=False)

    # Long-only trading
    side: Mapped[str] = mapped_column(
        String(8), nullable=False, default="LONG"
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="OPEN"
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    exit_price: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    realized_pnl: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    exit_reason: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "strategy IN ('intraday', 'swing')",
            name="ck_position_strategy",
        ),
        CheckConstraint(
            "side = 'LONG'",
            name="ck_position_long_only",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_position_quantity",
        ),
        CheckConstraint(
            "entry_price > 0 AND stop_loss > 0 "
            "AND target_price > 0",
            name="ck_position_prices_positive",
        ),
        CheckConstraint(
            "stop_loss < entry_price "
            "AND target_price > entry_price",
            name="ck_position_long_prices",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="ck_position_status",
        ),
        Index(
            "uq_open_position_symbol_strategy",
            "symbol",
            "strategy",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
    )



class TradingSignal(Base):
    __tablename__ = "trading_signals"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    symbol: Mapped[str] = mapped_column(
        String(32), nullable=False
    )

    strategy: Mapped[str] = mapped_column(
        String(16), nullable=False
    )

    interval: Mapped[str] = mapped_column(
        String(8), nullable=False
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    signal: Mapped[str] = mapped_column(
        String(20), nullable=False
    )

    score: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    close_price: Mapped[float] = mapped_column(
        Float, nullable=False
    )

    reasons: Mapped[list] = mapped_column(
        JSON, nullable=False
    )

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint(
            "strategy IN ('intraday', 'swing')",
            name="ck_signal_strategy",
        ),
        CheckConstraint(
            "signal IN ('STRONG_BUY', 'BUY', 'NO_ENTRY')",
            name="ck_signal_type",
        ),
        CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_signal_score",
        ),
        Index(
            "uq_trading_signal_symbol_strategy_interval_timestamp",
            "symbol",
            "strategy",
            "interval",
            "timestamp",
            unique=True,
        ),
        Index(
            "ix_trading_signal_strategy_signal",
            "strategy",
            "signal",
        ),
    )
