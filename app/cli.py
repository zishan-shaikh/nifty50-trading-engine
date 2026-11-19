
import argparse

from app.db import engine, SessionLocal, Base
from app.models import Instrument
from app.universe import load_universe
from app.repository import (
    upsert_instruments,
    get_stats,
    get_indicator_stats,
    get_latest_signals,
)
from app.ingestion import download_symbols
from app.indicator_pipeline import calculate_and_store_indicators
from app.config import DEFAULT_PERIODS
from app.signal_pipeline import generate_signals


def main():
    parser = argparse.ArgumentParser(
        description="Nifty 50 trading engine"
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # Initialize database
    sub.add_parser("init-db")

    # Synchronize Nifty 50 universe
    sub.add_parser("sync-universe")

    # Download historical market data
    dl = sub.add_parser("download")
    dl.add_argument(
        "--interval",
        choices=["5m", "1d"],
        required=True,
    )
    dl.add_argument("--period")
    dl.add_argument(
        "--symbols",
        help="Comma-separated symbols, e.g. RELIANCE,TCS",
    )

    # Calculate technical indicators
    calc = sub.add_parser("calculate-indicators")
    calc.add_argument(
        "--interval",
        choices=["5m", "1d"],
        required=True,
    )
    calc.add_argument(
        "--symbols",
        help="Optional comma-separated symbols",
    )

    # Display candle and indicator statistics
    sub.add_parser("stats")
    sub.add_parser("indicator-stats")

    # Generate trading signals
    sig = sub.add_parser("generate-signals")
    sig.add_argument(
        "--strategy",
        choices=["intraday", "swing"],
        required=True,
    )
    sig.add_argument(
        "--symbols",
        help="Optional comma-separated symbols",
    )

    # View stored trading signals
    view_sig = sub.add_parser("signal-stats")
    view_sig.add_argument(
        "--strategy",
        choices=["intraday", "swing"],
    )
    view_sig.add_argument(
        "--limit",
        type=int,
        default=50,
    )

    args = parser.parse_args()

    # --------------------------------------------------
    # Initialize database
    # --------------------------------------------------
    if args.command == "init-db":
        Base.metadata.create_all(engine)
        print("Database schema initialized.")

    # --------------------------------------------------
    # Synchronize Nifty 50 universe
    # --------------------------------------------------
    elif args.command == "sync-universe":
        Base.metadata.create_all(engine)

        df, source = load_universe()

        with SessionLocal() as session:
            upsert_instruments(session, df, source)

        print(f"Synced {len(df)} symbols from {source}.")

    # --------------------------------------------------
    # Download historical market data
    # --------------------------------------------------
    elif args.command == "download":
        Base.metadata.create_all(engine)

        period = args.period or DEFAULT_PERIODS[args.interval]

        with SessionLocal() as session:
            if args.symbols:
                symbols = [
                    s.strip().upper()
                    for s in args.symbols.split(",")
                    if s.strip()
                ]
            else:
                symbols = [
                    row[0]
                    for row in session.query(Instrument.symbol)
                    .filter(Instrument.active.is_(True))
                    .all()
                ]

            if not symbols:
                parser.error(
                    "No active symbols. Run sync-universe first "
                    "or pass --symbols."
                )

            results = download_symbols(
                session,
                symbols,
                args.interval,
                period,
            )

        for symbol, downloaded, saved, status in results:
            print(
                f"{symbol:15} downloaded={downloaded:5} "
                f"upserted={saved:5} {status}"
            )

    # --------------------------------------------------
    # Calculate and store technical indicators
    # --------------------------------------------------
    elif args.command == "calculate-indicators":
        Base.metadata.create_all(engine)

        with SessionLocal() as session:
            if args.symbols:
                symbols = [
                    s.strip().upper()
                    for s in args.symbols.split(",")
                    if s.strip()
                ]
            else:
                symbols = [
                    row[0]
                    for row in session.query(Instrument.symbol)
                    .filter(Instrument.active.is_(True))
                    .all()
                ]

            if not symbols:
                parser.error(
                    "No active symbols. Run sync-universe first "
                    "or pass --symbols."
                )

            results = calculate_and_store_indicators(
                session,
                symbols,
                args.interval,
            )

        success_count = 0
        error_count = 0

        for symbol, processed, status in results:
            print(
                f"{symbol:15} processed={processed:5} {status}"
            )

            if status.startswith("ERROR"):
                error_count += 1
            elif processed > 0:
                success_count += 1

        print(
            f"\nCompleted: {success_count} successful, "
            f"{error_count} errors."
        )

    # --------------------------------------------------
    # Display candle statistics
    # --------------------------------------------------
    elif args.command == "stats":
        with SessionLocal() as session:
            rows = get_stats(session)

        if not rows:
            print("No candle data found.")

        for symbol, interval, count in rows:
            print(
                f"{symbol:15} {interval:4} {count:8} candles"
            )

    # --------------------------------------------------
    # Display indicator statistics
    # --------------------------------------------------
    elif args.command == "indicator-stats":
        with SessionLocal() as session:
            rows = get_indicator_stats(session)

        if not rows:
            print("No indicator data found.")

        for symbol, interval, count in rows:
            print(
                f"{symbol:15} {interval:4} "
                f"{count:8} indicator rows"
            )

    # --------------------------------------------------
    # Generate intraday or swing trading signals
    # --------------------------------------------------
    elif args.command == "generate-signals":
        with SessionLocal() as session:
            if args.symbols:
                symbols = [
                    s.strip().upper()
                    for s in args.symbols.split(",")
                    if s.strip()
                ]
            else:
                symbols = [
                    row[0]
                    for row in session.query(Instrument.symbol)
                    .filter(Instrument.active.is_(True))
                    .all()
                ]

            if not symbols:
                parser.error("No active symbols found.")

            results = generate_signals(
                session,
                symbols,
                args.strategy,
            )

        for symbol, signal, score, details in results:
            print(
                f"{symbol:15} {signal:22} "
                f"score={score:3} {details}"
            )

        print(
            f"\nProcessed {len(results)} symbols."
        )

    # --------------------------------------------------
    # View stored trading signals
    # --------------------------------------------------
    elif args.command == "signal-stats":
        with SessionLocal() as session:
            rows = get_latest_signals(
                session,
                strategy=args.strategy,
                limit=args.limit,
            )

        if not rows:
            print("No trading signals found.")

        for row in rows:
            print(
                f"{row.symbol:15} "
                f"{row.strategy:10} "
                f"{row.signal:15} "
                f"score={row.score:3} "
                f"price={row.close_price:.2f} "
                f"time={row.timestamp}"
            )


if __name__ == "__main__":
    main()
