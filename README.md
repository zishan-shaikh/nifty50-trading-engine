# Nifty 50 Trading Engine — Phase 1

Local historical market-data foundation for a Nifty 50 technical trading research project.

**Configuration**
- Universe: Nifty 50 constituents (official index CSV first; local CSV fallback)
- Intraday: 5-minute candles
- Swing: daily candles
- Paper capital: ₹100,000
- Risk per trade: 1% (₹1,000 planned risk)
- Strategy: technical/rule-based (implemented in a later phase)
- SELL: exit-only (implemented in a later phase)
- Broker integration: intentionally excluded

## 1. Requirements

- macOS (tested design target), Python 3.12+
- Docker Desktop with Docker Compose
- Internet access for Yahoo Finance / official constituent CSV

Yahoo Finance via `yfinance` is a research-data source, not an exchange-grade feed. Its intraday history is limited (commonly about 60 days for 5-minute bars), can be delayed or revised, and may omit candles. This project does not use it for live trading. Daily history is generally much longer.

## 2. Start PostgreSQL

```bash
docker compose up -d db
```

PostgreSQL is exposed only on localhost port 5432. Default local development credentials are in `.env.example`; change them for any non-local deployment.

## 3. Create Python environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

## 4. Initialize schema and sync Nifty 50 universe

```bash
python -m app.cli init-db
python -m app.cli sync-universe
```

The universe sync tries the official Nifty Indices CSV:
`https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv`

If unavailable, it uses `data/nifty50_fallback.csv`. The fallback is a snapshot and must be refreshed when the index rebalances. The database records the source and sync timestamp.

## 5. Download historical candles

Examples:

```bash
# Daily history (default: 5 years)
python -m app.cli download --interval 1d --period 5y

# 5-minute history (provider limits apply; default: 30 days)
python -m app.cli download --interval 5m --period 30d --symbols RELIANCE,TCS
```

To download the current configured universe, omit `--symbols`. Start with a few symbols to validate connectivity and rate limits before requesting all 50.

The downloader:
- stores timestamps in UTC in PostgreSQL;
- retains provider timezone metadata in the source configuration;
- normalizes OHLCV columns;
- rejects invalid OHLC rows;
- de-duplicates candles using `(symbol, interval, timestamp)`;
- uses PostgreSQL upserts so reruns are safe.

Yahoo's 5-minute data availability is restricted. Do not expect five-minute candles for multiple years. For deeper intraday research, acquire a licensed historical feed and implement a provider adapter.

## 6. Run tests

Tests use SQLite in-memory and do not require PostgreSQL or network access:

```bash
pytest -q
```

## 7. Inspect data

```bash
python -m app.cli stats
```

## Data model

- `instruments`: symbol, company name, sector, active flag, source
- `candles`: symbol, interval, UTC timestamp, OHLCV, provider

No indicator or trading signals are generated in Phase 1. Phase 1 establishes trustworthy input data. Phase 2 will add indicator calculations; Phase 3 will add entry/exit, stop-loss and target rules.

## Research and risk notes

- Historical data quality varies by provider. Compare sample candles with a second trusted source before relying on results.
- Account for splits, dividends, symbol changes and constituent changes in serious backtests.
- Avoid survivorship bias: a current Nifty 50 list applied to old history is not a historically correct index universe.
- Never use a candle's final close to simulate an entry earlier within that same candle.
- No profitability is implied by this data pipeline.
