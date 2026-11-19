from pathlib import Path
import pandas as pd
import requests
from app.config import OFFICIAL_UNIVERSE_URL, FALLBACK_UNIVERSE

def load_universe(use_network: bool = True) -> tuple[pd.DataFrame, str]:
    if use_network:
        try:
            response = requests.get(
                OFFICIAL_UNIVERSE_URL,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            response.raise_for_status()
            from io import StringIO
            raw = pd.read_csv(StringIO(response.text))
            cols = {c.lower().strip(): c for c in raw.columns}
            symbol_col = next((cols[k] for k in ("symbol",) if k in cols), None)
            name_col = next((cols[k] for k in ("company name", "company_name") if k in cols), None)
            sector_col = next((cols[k] for k in ("industry", "sector") if k in cols), None)
            if not symbol_col or not name_col or len(raw) != 50:
                raise ValueError("Official constituent CSV did not contain the expected 50 rows/columns")
            result = pd.DataFrame({
                "symbol": raw[symbol_col].astype(str).str.strip(),
                "company_name": raw[name_col].astype(str).str.strip(),
                "sector": raw[sector_col].astype(str).str.strip() if sector_col else None,
            })
            return result.drop_duplicates("symbol"), "official_niftyindices_csv"
        except Exception:
            pass
    fallback = pd.read_csv(Path(FALLBACK_UNIVERSE))
    fallback = fallback.rename(columns={"company_name": "company_name"})
    return fallback[["symbol", "company_name", "sector"]], "local_fallback_snapshot"
