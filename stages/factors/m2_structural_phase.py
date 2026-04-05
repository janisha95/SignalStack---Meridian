from __future__ import annotations

import pandas as pd

from . import clamp, nan_dict


FACTOR_NAMES = [
    "wyckoff_phase",
    "phase_confidence",
    "phase_age_days",
    "vol_bias",
    "structure_quality",
]


def _phase_age(closes: pd.Series) -> int:
    ma20 = closes.rolling(20).mean()
    signal = (closes > ma20).astype(float).fillna(0.0)
    flips = signal.diff().fillna(0.0) != 0
    if not flips.any():
        return min(len(closes), 60)
    last_flip = flips[flips].index[-1]
    return int(min(len(closes.loc[last_flip:]), 60))


def compute_factors(
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
    vix: float,
    sector: str | None,
    universe_stats: dict,
) -> dict[str, float]:
    if df is None or len(df) < 50:
        return nan_dict(FACTOR_NAMES)

    data = df
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].fillna(0.0).astype(float)

    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    latest_close = float(close.iloc[-1])
    above_ma20 = not pd.isna(ma20.iloc[-1]) and latest_close > ma20.iloc[-1]
    above_ma50 = not pd.isna(ma50.iloc[-1]) and latest_close > ma50.iloc[-1]
    recent = data.tail(20)

    up_vol = recent.loc[recent["close"] > recent["open"], "volume"].sum()
    down_vol = recent.loc[recent["close"] <= recent["open"], "volume"].sum()
    total_vol = up_vol + down_vol
    vol_bias = 0.0 if total_vol == 0 else float((up_vol - down_vol) / total_vol)

    higher_lows = bool((low.tail(5).diff().dropna() > 0).all())
    lower_highs = bool((high.tail(5).diff().dropna() < 0).all())
    recent_high = float(high.tail(20).max())
    recent_low = float(low.tail(20).min())
    price_span = float(close.tail(20).max() - close.tail(20).min())
    if price_span <= max(abs(latest_close) * 0.005, 0.05):
        return {
            "wyckoff_phase": 0.0,
            "phase_confidence": 0.0,
            "phase_age_days": float(_phase_age(close)),
            "vol_bias": float(clamp(vol_bias, -1.0, 1.0)),
            "structure_quality": 0.0,
        }

    phase_code = 0.0
    if (not above_ma20) and (not above_ma50) and vol_bias > 0.1 and higher_lows:
        phase_code = 1.0
    elif above_ma20 and above_ma50 and latest_close >= recent_high * 0.98:
        phase_code = 0.5
    elif above_ma20 and above_ma50 and vol_bias < -0.1 and lower_highs:
        phase_code = -1.0
    elif (not above_ma20) and (not above_ma50) and latest_close <= recent_low * 1.02:
        phase_code = -0.5

    confidence = 0.25
    confidence += min(abs(vol_bias), 0.35)
    confidence += 0.2 if higher_lows or lower_highs else 0.0
    confidence += 0.2 if phase_code != 0.0 else 0.0
    confidence = clamp(confidence, 0.0, 1.0)

    structure_quality = 0.0
    structure_quality += 0.4 if higher_lows else 0.0
    structure_quality += 0.4 if lower_highs else 0.0
    structure_quality += min(abs(vol_bias), 0.2)
    structure_quality = clamp(structure_quality, 0.0, 1.0)

    return {
        "wyckoff_phase": float(phase_code),
        "phase_confidence": float(confidence),
        "phase_age_days": float(_phase_age(close)),
        "vol_bias": float(clamp(vol_bias, -1.0, 1.0)),
        "structure_quality": float(structure_quality),
    }
