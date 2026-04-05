from __future__ import annotations

import numpy as np
import pandas as pd

from stages.factors import m3_damage_shortside as m3


def _bars(n: int = 260, falling: bool = False) -> pd.DataFrame:
    rows = []
    price = 50.0
    for i in range(n):
        price += -0.15 if falling else 0.1
        rows.append(
            {
                "date": f"2025-03-{(i % 28) + 1:02d}",
                "open": price + (0.4 if falling else 0.1),
                "high": price + 0.6,
                "low": price - 0.6,
                "close": price,
                "volume": 80_000 + (i % 10) * 500,
            }
        )
    return pd.DataFrame(rows)


def test_m3_returns_6_factors() -> None:
    out = m3.compute_factors(_bars(), pd.DataFrame(), 20.0, None, {})
    assert set(out.keys()) == set(m3.FACTOR_NAMES)


def test_m3_damage_depth_signs() -> None:
    healthy = m3.compute_factors(_bars(), pd.DataFrame(), 20.0, None, {})
    damaged = m3.compute_factors(_bars(falling=True), pd.DataFrame(), 20.0, None, {})
    assert healthy["days_below_ma50"] == 0
    assert damaged["damage_depth"] > 0


def test_m3_short_history_returns_nan() -> None:
    out = m3.compute_factors(_bars(40), pd.DataFrame(), 20.0, None, {})
    assert all(np.isnan(v) for v in out.values())


def test_m3_ma200_factor_nan_when_history_under_200() -> None:
    out = m3.compute_factors(_bars(120, falling=True), pd.DataFrame(), 20.0, None, {})
    assert np.isnan(out["ma_death_cross_proximity"])
