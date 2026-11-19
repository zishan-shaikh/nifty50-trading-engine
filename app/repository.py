
import math
import pandas as pd

from sqlalchemy import select, func, and_
from app.models import (
    Instrument,
    Candle,
    TechnicalIndicator,
    TradingSignal,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import Instrument, Candle, TechnicalIndicator


def upsert_instruments(session, df, source):
    for row in df.to_dict("records"):
        obj = session.get(Instrument, row["symbol"])

        if obj:
            obj.company_name = row["company_name"]
            obj.sector = row.get("sector")
            obj.active = True
            obj.source = source
        else:
            session.add(
                Instrument(
                    symbol=row["symbol"],
                    company_name=row["company_name"],
                    sector=row.get("sector"),
                    active=True,
                    source=source,
                )
            )

    session.commit()


def upsert_candles(session, symbol, interval, frame, provider="yfinance"):
    if frame.empty:
        return 0

    rows = []

    for r in frame.to_dict("records"):
        ts = (
            r["timestamp"].to_pydatetime()
            if hasattr(r["timestamp"], "to_pydatetime")
            else r["timestamp"]
        )

        rows.append({
            "symbol": symbol,
            "interval": interval,
            "timestamp": ts,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
            "provider": provider,
        })

    dialect = session.get_bind().dialect.name

    if dialect == "postgresql":
        stmt = pg_insert(Candle).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "interval", "timestamp"],
            set_={
                k: getattr(stmt.excluded, k)
                for k in ["open", "high", "low", "close", "volume", "provider"]
            },
        )
    elif dialect == "sqlite":
        stmt = sqlite_insert(Candle).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "interval", "timestamp"],
            set_={
                k: getattr(stmt.excluded, k)
                for k in ["open", "high", "low", "close", "volume", "provider"]
            },
        )
    else:
        raise NotImplementedError(f"Upsert not implemented for {dialect}")

    session.execute(stmt)
    session.commit()

    return len(rows)


def upsert_technical_indicators(session, symbol, interval, frame):
    if frame.empty:
        return 0

    indicator_columns = [
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

    rows = []

    for record in frame.to_dict("records"):
        timestamp = record["timestamp"]

        if hasattr(timestamp, "to_pydatetime"):
            timestamp = timestamp.to_pydatetime()

        row = {
            "symbol": symbol,
            "interval": interval,
            "timestamp": timestamp,
        }

        for column in indicator_columns:
            value = record.get(column)

            if value is None:
                row[column] = None
            else:
                numeric_value = float(value)
                row[column] = (
                    numeric_value if math.isfinite(numeric_value) else None
                )

        rows.append(row)

    dialect = session.get_bind().dialect.name

    update_columns = indicator_columns + ["calculated_at"]

    if dialect == "postgresql":
        stmt = pg_insert(TechnicalIndicator).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "interval", "timestamp"],
            set_={
                column: getattr(stmt.excluded, column)
                for column in update_columns
            },
        )
    elif dialect == "sqlite":
        stmt = sqlite_insert(TechnicalIndicator).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "interval", "timestamp"],
            set_={
                column: getattr(stmt.excluded, column)
                for column in update_columns
            },
        )
    else:
        raise NotImplementedError(f"Upsert not implemented for {dialect}")

    session.execute(stmt)
    session.commit()

    return len(rows)


def get_stats(session):
    return session.execute(
        select(
            Candle.symbol,
            Candle.interval,
            func.count(Candle.id),
        )
        .group_by(Candle.symbol, Candle.interval)
        .order_by(Candle.symbol, Candle.interval)
    ).all()


def get_indicator_stats(session):
    return session.execute(
        select(
            TechnicalIndicator.symbol,
            TechnicalIndicator.interval,
            func.count(TechnicalIndicator.id),
        )
        .group_by(
            TechnicalIndicator.symbol,
            TechnicalIndicator.interval,
        )
        .order_by(
            TechnicalIndicator.symbol,
            TechnicalIndicator.interval,
        )
    ).all()


def get_strategy_frame(session, symbol, interval):
    """
    Load OHLCV candles and their stored indicators together.
    """
    rows = session.execute(
        select(Candle, TechnicalIndicator)
        .join(
            TechnicalIndicator,
            and_(
                Candle.symbol == TechnicalIndicator.symbol,
                Candle.interval == TechnicalIndicator.interval,
                Candle.timestamp == TechnicalIndicator.timestamp,
            ),
        )
        .where(
            Candle.symbol == symbol,
            Candle.interval == interval,
        )
        .order_by(Candle.timestamp)
    ).all()

    if not rows:
        return pd.DataFrame()

    records = []

    indicator_columns = [
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

    for candle, indicator in rows:
        record = {
            "timestamp": candle.timestamp,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }

        for column in indicator_columns:
            record[column] = getattr(indicator, column)

        records.append(record)

    return pd.DataFrame(records)


def upsert_trading_signal(session, signal_data):
    """
    Insert a signal or update the existing signal for the same candle.
    """
    dialect = session.get_bind().dialect.name

    if dialect == "postgresql":
        insert_function = pg_insert
    elif dialect == "sqlite":
        insert_function = sqlite_insert
    else:
        raise NotImplementedError(
            f"Upsert not implemented for {dialect}"
        )

    stmt = insert_function(TradingSignal).values(**signal_data)

    update_columns = [
        "signal",
        "score",
        "close_price",
        "reasons",
        "generated_at",
    ]

    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "symbol",
            "strategy",
            "interval",
            "timestamp",
        ],
        set_={
            column: getattr(stmt.excluded, column)
            for column in update_columns
        },
    )

    session.execute(stmt)
    session.commit()


def get_latest_signals(session, strategy=None, limit=50):
    query = select(TradingSignal)

    if strategy:
        query = query.where(
            TradingSignal.strategy == strategy
        )

    query = query.order_by(
        TradingSignal.timestamp.desc(),
        TradingSignal.score.desc(),
    ).limit(limit)

    return session.scalars(query).all()
