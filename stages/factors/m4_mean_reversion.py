from __future__ import annotations

import numpy as np
import pandas as pd

from . import bollinger, compute_atr, compute_rsi, nan_dict


FACTOR_NAMES = [
    "leadership_score",
    "pullback_score",
    "shock_magnitude",
    "setup_score",
]


def compute_factors(
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
    vix: float,
    sector: str | None,
    universe_stats: dict,
) -> dict[str, float]:
    if df is None or len(df) < 200:
        return nan_dict(FACTOR_NAMES)

    data = df
    close = data["close"].astype(float)
    volume = data["volume"].fillna(0.0).astype(float)
    latest_close = float(close.iloc[-1])

    sma200 = close.rolling(200).mean()
    sma50 = close.rolling(50).mean()
    leadership = 0.0
    if not pd.isna(sma200.iloc[-1]) and latest_close > sma200.iloc[-1]:
        leadership += 0.25
    if not pd.isna(sma50.iloc[-1]) and not pd.isna(sma50.iloc[-6]) and sma50.iloc[-1] > sma50.iloc[-6]:
        leadership += 0.25
    if len(spy_df) >= 21 and close.iloc[-21] not in (0, None) and spy_df["close"].iloc[-21] not in (0, None):
        ticker_ret = (latest_close / close.iloc[-21]) - 1.0
        spy_ret = (spy_df["close"].iloc[-1] / spy_df["close"].iloc[-21]) - 1.0
        if ticker_ret > spy_ret:
            leadership += 0.25
    dollar_vol = float((close * volume).tail(20).mean())
    if dollar_vol > 1_000_000:
        leadership += 0.25

    rsi2 = compute_rsi(close, 2)
    pullback = 0.0
    latest_rsi2 = float(rsi2.iloc[-1]) if not pd.isna(rsi2.iloc[-1]) else float("nan")
    if not pd.isna(latest_rsi2):
        if latest_rsi2 <= 5:
            pullback += 0.4
        elif latest_rsi2 <= 10:
            pullback += 0.3
        elif latest_rsi2 <= 20:
            pullback += 0.15

    atr = compute_atr(data, 14)
    atr_pct = float(atr.iloc[-1] / latest_close) if not pd.isna(atr.iloc[-1]) and latest_close > 0 else float("nan")
    shock_magnitude = float("nan")
    if len(close) >= 3 and not pd.isna(atr_pct) and atr_pct > 0 and close.iloc[-3] not in (0, None):
        shock = abs((latest_close / close.iloc[-3]) - 1.0)
        shock_magnitude = float(shock / atr_pct)
        pullback += min(0.3, shock_magnitude * 0.1)

    bb = bollinger(close, 20)
    if not pd.isna(bb["lower"].iloc[-1]):
        if latest_close < bb["lower"].iloc[-1]:
            pullback += 0.3
        elif latest_close < bb["lower"].iloc[-1] * 1.01:
            pullback += 0.15
    pullback = min(1.0, pullback)

    trigger_quality = 0.0
    if len(rsi2.dropna()) >= 2 and float(rsi2.iloc[-1]) > float(rsi2.iloc[-2]):
        trigger_quality = 1.0 if latest_close > close.iloc[-2] else 0.5

    setup_score = min(1.0, (0.4 * leadership) + (0.4 * pullback) + (0.2 * trigger_quality))

    return {
        "leadership_score": float(leadership),
        "pullback_score": float(pullback),
        "shock_magnitude": shock_magnitude,
        "setup_score": float(setup_score),
    }
