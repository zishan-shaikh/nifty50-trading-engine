
from datetime import datetime, timezone

from app.strategies import evaluate_signal
from app.repository import (
    get_strategy_frame,
    upsert_trading_signal,
)

STRATEGY_INTERVALS = {
    "intraday": "5m",
    "swing": "1d",
}


def generate_signals(
    session,
    symbols,
    strategy,
    now=None,
):
    if strategy not in STRATEGY_INTERVALS:
        raise ValueError(
            f"Unsupported strategy: {strategy}"
        )

    interval = STRATEGY_INTERVALS[strategy]

    results = []

    for symbol in symbols:
        try:
            frame = get_strategy_frame(
                session,
                symbol,
                interval,
            )

            if frame.empty:
                results.append(
                    (symbol, "NO_DATA", 0, "No joined data")
                )
                continue

            result = evaluate_signal(
                candles=frame,
                strategy=strategy,
                now=now,
                symbol=symbol,
            )

            # These are data-readiness statuses, not trading signals.
            if result.signal in {
                "NO_DATA",
                "INSUFFICIENT_DATA",
                "INDICATORS_NOT_READY",
            }:
                results.append(
                    (
                        symbol,
                        result.signal,
                        result.score,
                        "Insufficient completed data",
                    )
                )
                continue

            timestamp = result.timestamp

            if hasattr(timestamp, "to_pydatetime"):
                timestamp = timestamp.to_pydatetime()

            signal_data = {
                "symbol": symbol,
                "strategy": strategy,
                "interval": interval,
                "timestamp": timestamp,
                "signal": result.signal,
                "score": result.score,
                "close_price": float(
                    frame.loc[
                        frame["timestamp"] == result.timestamp,
                        "close",
                    ].iloc[-1]
                ),
                "reasons": result.reasons,
                "generated_at": datetime.now(timezone.utc),
            }

            upsert_trading_signal(
                session,
                signal_data,
            )

            results.append(
                (
                    symbol,
                    result.signal,
                    result.score,
                    ", ".join(result.reasons),
                )
            )

        except Exception as exc:
            session.rollback()

            results.append(
                (
                    symbol,
                    "ERROR",
                    0,
                    str(exc),
                )
            )

    return results
