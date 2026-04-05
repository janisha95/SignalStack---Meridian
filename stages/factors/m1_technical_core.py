from __future__ import annotations

import numpy as np
import pandas as pd

from . import bollinger, clamp, compute_adx, compute_macd_histogram, compute_rsi, nan_dict, rolling_percentile, z_score


FACTOR_NAMES = [
    "adx",
    "directional_conviction",
    "momentum_acceleration",
    "momentum_impulse",
    "volume_participation",
    "volume_flow_direction",
    "effort_vs_result",
    "volatility_rank",
    "volatility_acceleration",
    "wick_rejection",
    "rsi14",
    "rsi2",
    "bb_position",
    "bb_width",
    "ma_alignment",
    "dist_from_ma20_atr",
    "trend_persistence",
    "price_acceleration",
]


def _trend_persistence(closes: pd.Series) -> int:
    diffs = pd.to_numeric(closes, errors="coerce").diff().dropna()
    if diffs.empty:
        return 0
    direction = 1 if diffs.iloc[-1] > 0 else -1
    count = 0
    for value in reversed(diffs.tolist()):
        if (value > 0 and direction > 0) or (value < 0 and direction < 0):
            count += 1
        else:
            break
    return int(count * direction)


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
    closes = data["close"].astype(float)
    highs = data["high"].astype(float)
    lows = data["low"].astype(float)
    opens = data["open"].astype(float)
    volume = data["volume"].fillna(0.0).astype(float)

    adx_pack = compute_adx(data, 14)
    adx_series = adx_pack["adx"]
    plus_di = adx_pack["plus_di"]
    minus_di = adx_pack["minus_di"]
    atr = adx_pack["atr"]
    atr_pct = atr / closes.replace(0, np.nan)

    rsi14 = compute_rsi(closes, 14)
    rsi2 = compute_rsi(closes, 2)
    macd_hist = compute_macd_histogram(closes)
    vol_ma20 = volume.rolling(20).mean()

    obv = (np.sign(closes.diff().fillna(0.0)) * volume).cumsum()
    evr_raw = (highs - lows) / volume.replace(0, np.nan)
    wick_range = (highs - lows).replace(0, np.nan)
    wick_raw = ((highs - closes) - (closes - lows)) / wick_range
    bb = bollinger(closes, 20)

    latest_close = float(closes.iloc[-1])
    latest_atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else float("nan")
    ma20 = closes.rolling(20).mean()
    ma50 = closes.rolling(50).mean()
    ma200 = closes.rolling(200).mean()

    bb_pos = float("nan")
    if not pd.isna(bb["upper"].iloc[-1]) and not pd.isna(bb["lower"].iloc[-1]):
        denom = bb["upper"].iloc[-1] - bb["lower"].iloc[-1]
        if denom and denom > 0:
            bb_pos = clamp((latest_close - bb["lower"].iloc[-1]) / denom, 0.0, 1.0)

    bb_width = float("nan")
    if not pd.isna(bb["mid"].iloc[-1]) and bb["mid"].iloc[-1] not in (0, None):
        bb_width = float((bb["upper"].iloc[-1] - bb["lower"].iloc[-1]) / bb["mid"].iloc[-1])

    ma_alignment = 0
    for ma in (ma20.iloc[-1], ma50.iloc[-1], ma200.iloc[-1]):
        if pd.isna(ma):
            continue
        if latest_close > ma:
            ma_alignment += 1
        elif latest_close < ma:
            ma_alignment -= 1

    dist_from_ma20_atr = float("nan")
    if not pd.isna(ma20.iloc[-1]) and latest_atr and not pd.isna(latest_atr) and latest_atr != 0:
        dist_from_ma20_atr = float((latest_close - ma20.iloc[-1]) / latest_atr)

    price_acc = float("nan")
    if len(closes) >= 21 and closes.iloc[-21] not in (0, None) and closes.iloc[-6] not in (0, None):
        ret_5 = (latest_close / closes.iloc[-6]) - 1.0
        ret_20 = (latest_close / closes.iloc[-21]) - 1.0
        price_acc = float(ret_5 - ret_20)

    result = {
        "adx": float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else float("nan"),
        "directional_conviction": z_score((plus_di - minus_di), 20),
        "momentum_acceleration": z_score(rsi14.diff(3), 20),
        "momentum_impulse": z_score(macd_hist / atr.replace(0, np.nan), 20),
        "volume_participation": z_score(volume / vol_ma20.replace(0, np.nan), 20),
        "volume_flow_direction": z_score(obv.diff(5) / (vol_ma20 * 5).replace(0, np.nan), 20),
        "effort_vs_result": z_score(evr_raw, 20),
        "volatility_rank": rolling_percentile(atr_pct, 126),
        "volatility_acceleration": z_score(atr_pct.pct_change(5), 20),
        "wick_rejection": z_score(wick_raw, 20),
        "rsi14": float(rsi14.iloc[-1]) if not pd.isna(rsi14.iloc[-1]) else float("nan"),
        "rsi2": float(rsi2.iloc[-1]) if not pd.isna(rsi2.iloc[-1]) else float("nan"),
        "bb_position": bb_pos,
        "bb_width": bb_width,
        "ma_alignment": float(ma_alignment),
        "dist_from_ma20_atr": dist_from_ma20_atr,
        "trend_persistence": float(_trend_persistence(closes)),
        "price_acceleration": price_acc,
    }
    return result
