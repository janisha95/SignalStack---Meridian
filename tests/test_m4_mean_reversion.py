from __future__ import annotations

import numpy as np
import pandas as pd

from stages.factors import m4_mean_reversion as m4


def _bars(n: int = 260, oversold: bool = False) -> pd.DataFrame:
    rows = []
    price = 40.0
    for i in range(n):
        drift = 0.12
        if oversold and i > n - 5:
            drift = -1.2
        price += drift
        rows.append(
            {
                "date": f"2025-04-{(i % 28) + 1:02d}",
                "open": price - 0.2,
                "high": price + 0.5,
                "low": price - 0.7,
                "close": price,
                "volume": 150_000 + (i % 15) * 2000,
            }
        )
    return pd.DataFrame(rows)


def test_m4_returns_4_factors() -> None:
    out = m4.compute_factors(_bars(), _bars(), 20.0, None, {})
    assert set(out.keys()) == set(m4.FACTOR_NAMES)


def test_m4_scores_bounded() -> None:
    out = m4.compute_factors(_bars(oversold=True), _bars(), 20.0, None, {})
    assert 0 <= out["leadership_score"] <= 1
    assert 0 <= out["pullback_score"] <= 1
    assert out["shock_magnitude"] >= 0
    assert 0 <= out["setup_score"] <= 1


def test_m4_short_history_returns_nan() -> None:
    out = m4.compute_factors(_bars(100), _bars(), 20.0, None, {})
    assert all(np.isnan(v) for v in out.values())
