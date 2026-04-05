from __future__ import annotations

import numpy as np
import pandas as pd

from . import compute_atr, nan_dict


FACTOR_NAMES = [
    "damage_depth",
    "days_below_ma50",
    "rollover_strength",
    "downside_volume_dominance",
    "lower_highs_streak",
    "ma_death_cross_proximity",
]


def _count_true_from_end(series: pd.Series, cap: int) -> int:
    count = 0
    for value in reversed(series.fillna(False).tolist()):
        if value:
            count += 1
        else:
            break
    return min(count, cap)


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
    open_ = data["open"].astype(float)
    volume = data["volume"].fillna(0.0).astype(float)

    ma50 = close.rolling(50).mean()
    atr = compute_atr(data, 14)
    latest_close = float(close.iloc[-1])

    damage_depth = float("nan")
    if not pd.isna(ma50.iloc[-1]) and latest_close > 0:
        damage_depth = float((ma50.iloc[-1] - latest_close) / latest_close)

    below_ma50 = close < ma50
    days_below_ma50 = float(_count_true_from_end(below_ma50, 60))

    rollover_strength = float("nan")
    if not pd.isna(atr.iloc[-1]) and atr.iloc[-1] not in (0, None):
        rollover_strength = float((open_.iloc[-1] - latest_close) / atr.iloc[-1])

    recent = data.tail(20).copy()
    prev_close = recent["close"].shift(1)
    down_vol = recent.loc[recent["close"] < prev_close, "volume"].sum()
    up_vol = recent.loc[recent["close"] >= prev_close, "volume"].sum()
    downside_volume_dominance = 5.0 if up_vol == 0 and down_vol > 0 else float(down_vol / up_vol) if up_vol > 0 else 0.0

    rolling_highs = high.rolling(5).max().dropna()
    lower_highs = 0
    for i in range(len(rolling_highs) - 1, 0, -1):
        if rolling_highs.iloc[i] < rolling_highs.iloc[i - 1]:
            lower_highs += 1
        else:
            break
    lower_highs_streak = float(min(lower_highs, 20))

    ma_death_cross_proximity = float("nan")
    if len(close) >= 200:
        ma200 = close.rolling(200).mean()
        if not pd.isna(ma200.iloc[-1]) and latest_close > 0:
            ma_death_cross_proximity = float((ma50.iloc[-1] - ma200.iloc[-1]) / latest_close)

    return {
        "damage_depth": damage_depth,
        "days_below_ma50": days_below_ma50,
        "rollover_strength": rollover_strength,
        "downside_volume_dominance": float(downside_volume_dominance),
        "lower_highs_streak": lower_highs_streak,
        "ma_death_cross_proximity": ma_death_cross_proximity,
    }
