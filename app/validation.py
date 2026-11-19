
import pandas as pd

REQUIRED = ["Open", "High", "Low", "Close", "Volume"]


def normalize_ohlcv(
    frame: pd.DataFrame,
    interval: str = "5m"
) -> pd.DataFrame:

    columns = [
        "timestamp", "open", "high",
        "low", "close", "volume"
    ]

    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)

    df = frame.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    missing = [c for c in REQUIRED if c not in df.columns]

    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    df = df[REQUIRED].copy()

    idx = pd.DatetimeIndex(df.index)

    if interval == "1d":
        # Preserve the Indian exchange session date.
        if idx.tz is not None:
            idx = idx.tz_localize(None)

        idx = idx.normalize().tz_localize("UTC")

    else:
        # Intraday timestamps represent actual moments.
        if idx.tz is None:
            idx = idx.tz_localize("Asia/Kolkata")

        idx = idx.tz_convert("UTC")

    df.index = idx
    df.index.name = "timestamp"
    df = df.reset_index()

    for col in REQUIRED:
        df[col] = pd.to_numeric(
            df[col], errors="coerce"
        )

    df = df.dropna(
        subset=["timestamp"] + REQUIRED
    )

    valid = (
        (df["Open"] > 0)
        & (df["High"] > 0)
        & (df["Low"] > 0)
        & (df["Close"] > 0)
        & (df["Volume"] >= 0)
        & (
            df["High"]
            >= df[["Open", "Close", "Low"]].max(axis=1)
        )
        & (
            df["Low"]
            <= df[["Open", "Close", "High"]].min(axis=1)
        )
    )

    df = df.loc[valid]

    df = (
        df.drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
    )

    return df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume"
    })[columns]
