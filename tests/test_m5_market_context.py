from __future__ import annotations

import numpy as np
import pandas as pd

from stages.factors import m5_market_context as m5


def _bars(n: int = 120, ticker: str = "AAPL") -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        price += 0.2
        rows.append(
            {
                "ticker": ticker,
                "date": f"2025-05-{(i % 28) + 1:02d}",
                "open": price - 0.2,
                "high": price + 0.4,
                "low": price - 0.5,
                "close": price,
                "volume": 200_000 + (i % 20) * 1000,
            }
        )
    df = pd.DataFrame(rows)
    df.attrs["ticker"] = ticker
    return df


def test_m5_returns_14_factors() -> None:
    df = _bars()
    spy = _bars(ticker="SPY")
    out = m5.compute_factors(df, spy, 20.0, "Technology", {"options_map": {}, "sector_returns": {}, "market_breadth": 0.5, "advance_decline_ratio": 1.0, "spy_5d_return": 0.01, "vix_252d_percentile": 0.6})
    assert set(out.keys()) == set(m5.FACTOR_NAMES)


def test_m5_rs_math_and_bounds() -> None:
    df = _bars()
    spy = _bars(ticker="SPY")
    stats = {
        "options_map": {"AAPL": {"options_pcr": 0.8, "options_unusual_vol": 1.2}},
        "sector_returns": {"Technology": 0.01},
        "market_breadth": 0.62,
        "advance_decline_ratio": 1.35,
        "spy_5d_return": 0.015,
        "vix_252d_percentile": 0.72,
    }
    out = m5.compute_factors(df, spy, 20.0, "Technology", stats)
    assert np.isclose(out["rs_momentum"], out["rs_vs_spy_10d"] - out["rs_vs_spy_20d"], equal_nan=False)
    assert 0 <= out["market_breadth"] <= 1
    assert 0 <= out["vix_regime"] <= 1
    assert 0 <= out["volume_climax"] <= 1
    assert out["options_pcr"] == 0.8
    assert out["options_unusual_vol"] == 1.2


def test_m5_unmapped_sector_and_missing_options() -> None:
    df = _bars(ticker="UNKN")
    spy = _bars(ticker="SPY")
    out = m5.compute_factors(df, spy, 20.0, None, {"options_map": {}, "sector_returns": {}, "market_breadth": 0.5, "advance_decline_ratio": 1.0, "spy_5d_return": 0.01, "vix_252d_percentile": 0.6})
    assert np.isnan(out["rs_vs_sector"])
    assert np.isnan(out["options_pcr"])
