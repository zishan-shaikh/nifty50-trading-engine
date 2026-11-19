
import pandas as pd
from sqlalchemy import select

from app.models import Candle
from app.indicators import calculate_indicators
from app.repository import upsert_technical_indicators


def calculate_and_store_indicators(session, symbols, interval):
    results = []

    for symbol in symbols:
        candles = session.execute(
            select(
                Candle.timestamp,
                Candle.open,
                Candle.high,
                Candle.low,
                Candle.close,
                Candle.volume,
            )
            .where(
                Candle.symbol == symbol,
                Candle.interval == interval,
            )
            .order_by(Candle.timestamp)
        ).mappings().all()

        if not candles:
            results.append((symbol, 0, "no candle data"))
            continue

        frame = pd.DataFrame(candles)

        try:
            calculated = calculate_indicators(
                frame,
                interval=interval,
            )

            saved = upsert_technical_indicators(
                session,
                symbol,
                interval,
                calculated,
            )

            results.append((symbol, len(calculated), f"saved={saved}"))

        except Exception as exc:
            session.rollback()
            results.append((symbol, 0, f"ERROR: {exc}"))

    return results
