
import pandas as pd
from sqlalchemy import select

from app.models import Candle, TechnicalIndicator
from app.repository import get_strategy_frame


STRATEGY_INTERVALS = {
    "intraday": "5m",
    "swing": "1d",
}


def load_backtest_data(
    session,
    strategy: str,
) -> dict[str, pd.DataFrame]:
    """
    Load historical OHLCV and indicators for all symbols
    that have matching candle and indicator records.
    """

    if strategy not in STRATEGY_INTERVALS:
        raise ValueError(f"Invalid strategy: {strategy}")

    interval = STRATEGY_INTERVALS[strategy]

    query = (
        select(Candle.symbol)
        .join(
            TechnicalIndicator,
            (
                (Candle.symbol == TechnicalIndicator.symbol)
                & (Candle.interval == TechnicalIndicator.interval)
                & (Candle.timestamp == TechnicalIndicator.timestamp)
            ),
        )
        .where(Candle.interval == interval)
        .distinct()
        .order_by(Candle.symbol)
    )

    symbols = session.scalars(query).all()

    result = {}

    for symbol in symbols:
        frame = get_strategy_frame(
            session,
            symbol,
            interval,
        )

        if frame.empty:
            continue

        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"],
            utc=True,
            errors="coerce",
        )

        frame = (
            frame.dropna(subset=["timestamp"])
            .sort_values("timestamp")
            .drop_duplicates(
                subset=["timestamp"],
                keep="last",
            )
            .reset_index(drop=True)
        )

        if frame.empty:
            continue

        if "atr_14" not in frame.columns:
            continue

        result[symbol] = frame

    return result


def get_backtest_data_summary(
    data: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Return a summary of loaded historical data."""

    records = []

    for symbol, frame in data.items():
        records.append({
            "symbol": symbol,
            "candles": len(frame),
            "first_timestamp": frame["timestamp"].min(),
            "last_timestamp": frame["timestamp"].max(),
            "valid_atr": int(frame["atr_14"].notna().sum()),
        })

    return pd.DataFrame(records)
