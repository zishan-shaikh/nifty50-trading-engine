from app.providers.yahoo import YahooFinanceProvider
from app.repository import upsert_candles

def download_symbols(session, symbols, interval, period, provider=None):
    provider = provider or YahooFinanceProvider()
    summary = []
    for symbol in symbols:
        try:
            candles = provider.fetch(symbol, interval, period)
            saved = upsert_candles(session, symbol, interval, candles, provider.name)
            summary.append((symbol, len(candles), saved, "ok" if len(candles) else "empty"))
        except Exception as exc:
            summary.append((symbol, 0, 0, f"error: {exc}"))
    return summary
