from __future__ import annotations

import numpy as np
import pandas as pd

from stages.factors import m1_technical_core as m1


def _bars(n: int = 260, start: float = 50.0, drift: float = 0.2, volume: float = 100_000.0) -> pd.DataFrame:
    rows = []
    price = start
    for i in range(n):
        price += drift + ((i % 5) - 2) * 0.05
        rows.append(
            {
                "date": f"2025-01-{(i % 28) + 1:02d}",
                "open": price - 0.3,
                "high": price + 0.6,
                "low": price - 0.6,
                "close": price,
                "volume": volume + (i % 20) * 1000,
            }
        )
    return pd.DataFrame(rows)


def test_m1_returns_all_18_factors() -> None:
    df = _bars()
    out = m1.compute_factors(df, df.copy(), 20.0, "Technology", {})
    assert set(out.keys()) == set(m1.FACTOR_NAMES)


def test_m1_bounded_outputs() -> None:
    df = _bars()
    out = m1.compute_factors(df, df.copy(), 20.0, "Technology", {})
    assert 0 <= out["rsi14"] <= 100
    assert 0 <= out["rsi2"] <= 100
    assert 0 <= out["bb_position"] <= 1
    assert 0 <= out["adx"] <= 100
    assert -3 <= out["ma_alignment"] <= 3
    assert isinstance(out["trend_persistence"], float)
    assert isinstance(out["price_acceleration"], float)


def test_m1_short_history_returns_nan_dict() -> None:
    df = _bars(10)
    out = m1.compute_factors(df, df.copy(), 20.0, "Technology", {})
    assert all(np.isnan(v) for v in out.values())


def test_m1_zero_volume_and_constant_price_do_not_crash() -> None:
    df = _bars(260, start=10.0, drift=0.0, volume=0.0)
    out = m1.compute_factors(df, df.copy(), 20.0, "Technology", {})
    assert set(out.keys()) == set(m1.FACTOR_NAMES)
