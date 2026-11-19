
import yfinance as yf
from app.validation import normalize_ohlcv


class YahooFinanceProvider:

    name = "yfinance"

    def fetch(
        self,
        symbol: str,
        interval: str,
        period: str
    ):

        ticker = f"{symbol}.NS"

        data = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False
        )

        return normalize_ohlcv(
            data,
            interval=interval
        )
