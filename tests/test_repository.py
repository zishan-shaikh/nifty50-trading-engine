import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.db import Base
from app.models import Candle
from app.repository import upsert_candles
import pandas as pd

def test_candle_upsert_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    frame = pd.DataFrame([{
        "timestamp": pd.Timestamp("2025-01-02T09:15:00Z"),
        "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000
    }])
    with Session(engine) as session:
        assert upsert_candles(session, "TEST", "5m", frame) == 1
        assert upsert_candles(session, "TEST", "5m", frame) == 1
        rows = session.scalars(select(Candle)).all()
        assert len(rows) == 1
