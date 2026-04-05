from __future__ import annotations

import numpy as np
import pandas as pd

from stages.factors import m2_structural_phase as m2


def _bars(n: int = 120, start: float = 20.0) -> pd.DataFrame:
    rows = []
    price = start
    for i in range(n):
        price += (0.15 if i % 7 else -0.05)
        rows.append(
            {
                "date": f"2025-02-{(i % 28) + 1:02d}",
                "open": price - 0.2,
                "high": price + 0.4,
                "low": price - 0.3,
                "close": price,
                "volume": 100_000 + i * 100,
            }
        )
    return pd.DataFrame(rows)


def test_m2_returns_5_factors() -> None:
    out = m2.compute_factors(_bars(), pd.DataFrame(), 20.0, None, {})
    assert set(out.keys()) == set(m2.FACTOR_NAMES)


def test_m2_bounds() -> None:
    out = m2.compute_factors(_bars(), pd.DataFrame(), 20.0, None, {})
    assert -1 <= out["wyckoff_phase"] <= 1
    assert 0 <= out["phase_confidence"] <= 1
    assert 0 <= out["phase_age_days"] <= 60
    assert -1 <= out["vol_bias"] <= 1
    assert 0 <= out["structure_quality"] <= 1


def test_m2_short_history_returns_nan() -> None:
    out = m2.compute_factors(_bars(20), pd.DataFrame(), 20.0, None, {})
    assert all(np.isnan(v) for v in out.values())


def test_m2_constant_price_returns_unknown_phase_zero() -> None:
    df = _bars()
    df["open"] = 10.0
    df["high"] = 10.1
    df["low"] = 9.9
    df["close"] = 10.0
    out = m2.compute_factors(df, pd.DataFrame(), 20.0, None, {})
    assert out["wyckoff_phase"] == 0.0
