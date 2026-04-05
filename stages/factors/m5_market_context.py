from __future__ import annotations

import numpy as np
import pandas as pd

from . import safe_log10, nan_dict


FACTOR_NAMES = [
    "rs_vs_spy_10d",
    "rs_vs_spy_20d",
    "rs_momentum",
    "rs_vs_sector",
    "sector_weakness",
    "options_pcr",
    "options_unusual_vol",
    "dollar_volume_log",
    "price_quality",
    "volume_climax",
    "market_breadth",
    "advance_decline_ratio",
    "spy_momentum_5d",
    "vix_regime",
]


def _rs_vs_spy(close: pd.Series, spy_close: pd.Series, period: int) -> float:
    if len(close) < period + 1 or len(spy_close) < period + 1:
        return float("nan")
    if close.iloc[-period - 1] in (0, None) or spy_close.iloc[-period - 1] in (0, None):
        return float("nan")
    ticker_ret = (close.iloc[-1] / close.iloc[-period - 1]) - 1.0
    spy_ret = (spy_close.iloc[-1] / spy_close.iloc[-period - 1]) - 1.0
    return float(ticker_ret - spy_ret)


def compute_factors(
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
    vix: float,
    sector: str | None,
    universe_stats: dict,
) -> dict[str, float]:
    if df is None or len(df) < 20:
        return nan_dict(FACTOR_NAMES)

    data = df
    close = data["close"].astype(float)
    volume = data["volume"].fillna(0.0).astype(float)
    spy_close = spy_df["close"].astype(float)
    ticker = str(df.attrs.get("ticker") or df.get("ticker", pd.Series([""])).iloc[0]).upper()

    rs_10 = _rs_vs_spy(close, spy_close, 10)
    rs_20 = _rs_vs_spy(close, spy_close, 20)
    rs_momentum = float(rs_10 - rs_20) if not pd.isna(rs_10) and not pd.isna(rs_20) else float("nan")

    rs_vs_sector = float("nan")
    sector_returns = universe_stats.get("sector_returns", {})
    ticker_10d_return = float("nan")
    if len(close) >= 11 and close.iloc[-11] not in (0, None):
        ticker_10d_return = float((close.iloc[-1] / close.iloc[-11]) - 1.0)
    if sector and sector in sector_returns and not pd.isna(ticker_10d_return):
        rs_vs_sector = float(ticker_10d_return - sector_returns[sector])
    sector_weakness = float(
        1.0 if sector and sector in sector_returns and sector_returns[sector] < 0 and not pd.isna(rs_vs_sector) and rs_vs_sector < 0 else 0.0
    )

    options_map = universe_stats.get("options_map", {})
    option_row = options_map.get(ticker, {})
    options_pcr = option_row.get("options_pcr", float("nan"))
    options_unusual = option_row.get("options_unusual_vol", float("nan"))

    avg_dollar_volume = float((close * volume).tail(20).mean()) if len(close) >= 1 else float("nan")
    dollar_volume_log = safe_log10(avg_dollar_volume)
    price_quality = safe_log10(float(close.iloc[-1])) if len(close) else float("nan")

    volume_climax = float("nan")
    if len(volume) >= 60:
        max_vol = float(volume.tail(60).max())
        volume_climax = 0.0 if max_vol == 0 else float(volume.iloc[-1] / max_vol)

    return {
        "rs_vs_spy_10d": rs_10,
        "rs_vs_spy_20d": rs_20,
        "rs_momentum": rs_momentum,
        "rs_vs_sector": rs_vs_sector,
        "sector_weakness": sector_weakness,
        "options_pcr": float(options_pcr) if options_pcr is not None else float("nan"),
        "options_unusual_vol": float(options_unusual) if options_unusual is not None else float("nan"),
        "dollar_volume_log": dollar_volume_log,
        "price_quality": price_quality,
        "volume_climax": volume_climax,
        "market_breadth": float(universe_stats.get("market_breadth", float("nan"))),
        "advance_decline_ratio": float(universe_stats.get("advance_decline_ratio", float("nan"))),
        "spy_momentum_5d": float(universe_stats.get("spy_5d_return", float("nan"))),
        "vix_regime": float(universe_stats.get("vix_252d_percentile", float("nan"))),
    }
