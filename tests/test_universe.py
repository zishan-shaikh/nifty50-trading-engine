from app.universe import load_universe

def test_fallback_universe_has_50_unique_symbols():
    df, source = load_universe(use_network=False)
    assert len(df) == 50
    assert df["symbol"].is_unique
    assert source == "local_fallback_snapshot"
