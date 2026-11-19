import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://niftyuser:niftypass@localhost:5432/niftydb",
)
OFFICIAL_UNIVERSE_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"
FALLBACK_UNIVERSE = "data/nifty50_fallback.csv"
DEFAULT_PERIODS = {"1d": "5y", "5m": "30d"}
YAHOO_SUFFIX = ".NS"
