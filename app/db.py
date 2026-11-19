from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import DATABASE_URL

class Base(DeclarativeBase):
    pass

def make_engine(url: str = DATABASE_URL):
    return create_engine(url, pool_pre_ping=True, future=True)

engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
