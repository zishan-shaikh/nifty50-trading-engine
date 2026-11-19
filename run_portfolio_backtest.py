from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from app.backtesting.config import BacktestConfig
from app.backtesting.data_loader import (
    get_backtest_data_summary,
    load_backtest_data,
)
from app.backtesting.portfolio import run_threshold_experiments
from app.db import SessionLocal


def main() -> None:
    config = BacktestConfig()
    config.validate()

    print("\nLoading historical data from PostgreSQL...")
    with SessionLocal() as session:
        intraday_data = load_backtest_data(session, "intraday")
        swing_data = load_backtest_data(session, "swing")

    data_by_strategy = {
        "intraday": intraday_data,
        "swing": swing_data,
    }

    intraday_summary = get_backtest_data_summary(intraday_data)
    swing_summary = get_backtest_data_summary(swing_data)

    reports_dir = Path("backtest_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    intraday_summary.to_csv(
        reports_dir / "intraday_data_coverage.csv",
        index=False,
    )
    swing_summary.to_csv(
        reports_dir / "swing_data_coverage.csv",
        index=False,
    )

    print(f"\nIntraday symbols loaded: {len(intraday_data)}")
    if not intraday_summary.empty:
        print(intraday_summary.to_string(index=False))
    print(f"\nSwing symbols loaded: {len(swing_data)}")
    if not swing_summary.empty:
        print(swing_summary.to_string(index=False))

    if not intraday_data and not swing_data:
        raise RuntimeError(
            "No backtest data found. Check candle and technical_indicators tables."
        )

    print("\nRunning independent portfolio experiments...")
    results = run_threshold_experiments(data_by_strategy, config)

    summary_rows = []
    for threshold, result in results.items():
        summary_rows.append(result.summary())

        pd.DataFrame([asdict(trade) for trade in result.trades]).to_csv(
            reports_dir / f"trades_threshold_{threshold}.csv",
            index=False,
        )
        result.equity_curve.to_csv(
            reports_dir / f"equity_threshold_{threshold}.csv",
            index=False,
        )
        result.trades_by_strategy().to_csv(
            reports_dir / f"strategy_summary_threshold_{threshold}.csv",
            index=False,
        )
        result.trades_by_symbol().to_csv(
            reports_dir / f"symbol_summary_threshold_{threshold}.csv",
            index=False,
        )

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(reports_dir / "portfolio_summary.csv", index=False)

    print("\n" + "=" * 88)
    print("PORTFOLIO BACKTEST SUMMARY")
    print("=" * 88)
    print(summary.to_string(index=False))
    print(f"\nReports saved to: {reports_dir.resolve()}")

    print("\nIMPORTANT DATA LIMITATIONS")
    print(f"- Intraday: {len(intraday_data)} symbols loaded.")
    print(f"- Swing: {len(swing_data)} symbols loaded.")
    print("- Results are historical simulations, not predictions or guarantees.")
    print("- Brokerage and other charges are provisional configuration assumptions.")
    print("- Verify Dhan's actual charges and model taxes/levies before judging profitability.")
    print("- Intraday results from a small symbol sample must not be generalized to all Nifty 50.")


if __name__ == "__main__":
    main()
