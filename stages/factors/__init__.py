from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def now_et() -> datetime:
    """Current datetime in US Eastern Time."""
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("America/New_York"))
    return datetime.now(timezone(timedelta(hours=-4)))


def today_et() -> str:
    """Today's ET date as YYYY-MM-DD."""
    return now_et().strftime("%Y-%m-%d")


def today_et_date() -> date:
    """Today's ET date as a date object."""
    return now_et().date()


def now_et_iso() -> str:
    """Current ET timestamp as ISO string."""
    return now_et().isoformat()


def now_utc_iso() -> str:
    """Current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nan_dict(names: Iterable[str]) -> dict[str, float]:
    return {name: float("nan") for name in names}


def _as_float_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_float_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    return pd.to_numeric(series, errors="coerce").astype(float)


def z_score(series: pd.Series, window: int = 20) -> float:
    values = _as_float_series(series).dropna()
    if len(values) < window:
        return float("nan")
    recent = values.iloc[-window:]
    arr = recent.to_numpy(dtype=float, copy=False)
    std = float(np.std(arr, ddof=1))
    if pd.isna(std) or std == 0:
        return 0.0
    return float((arr[-1] - float(np.mean(arr))) / std)


def rolling_percentile(series: pd.Series, window: int = 126) -> float:
    values = _as_float_series(series).dropna()
    if len(values) < window:
        return float("nan")
    recent = values.iloc[-window:]
    arr = recent.to_numpy(dtype=float, copy=False)
    latest = arr[-1]
    return float(np.mean(arr <= latest))


def wilder_smooth(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    first = sum(values[:period])
    out = [first]
    for value in values[period:]:
        out.append(out[-1] - out[-1] / period + value)
    return out


def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    values = _as_float_series(closes)
    deltas = values.diff()
    gains = deltas.clip(lower=0.0).fillna(0.0)
    losses = (-deltas.clip(upper=0.0)).fillna(0.0)
    if len(values) <= period:
        return pd.Series(np.nan, index=values.index, dtype=float)
    avg_gain = gains.iloc[1 : period + 1].mean()
    avg_loss = losses.iloc[1 : period + 1].mean()
    rsi = pd.Series(np.nan, index=values.index, dtype=float)
    if avg_loss == 0:
        rsi.iloc[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi.iloc[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period + 1, len(values)):
        avg_gain = ((avg_gain * (period - 1)) + gains.iloc[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses.iloc[i]) / period
        if avg_loss == 0:
            rsi.iloc[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi.iloc[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    highs = _as_float_series(df["high"])
    lows = _as_float_series(df["low"])
    closes = _as_float_series(df["close"])
    prev_close = closes.shift(1)
    tr = pd.concat(
        [
            highs - lows,
            (highs - prev_close).abs(),
            (lows - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    smoothed = wilder_smooth(tr.iloc[1:].fillna(0.0).tolist(), period)
    atr = pd.Series(np.nan, index=df.index, dtype=float)
    if not smoothed:
        return atr
    for offset, value in enumerate(smoothed, start=period):
        atr.iloc[offset] = value / period
    return atr


def compute_adx(df: pd.DataFrame, period: int = 14) -> dict[str, pd.Series]:
    highs = _as_float_series(df["high"])
    lows = _as_float_series(df["low"])
    closes = _as_float_series(df["close"])
    prev_high = highs.shift(1)
    prev_low = lows.shift(1)
    prev_close = closes.shift(1)
    tr = pd.concat(
        [(highs - lows), (highs - prev_close).abs(), (lows - prev_close).abs()],
        axis=1,
    ).max(axis=1).fillna(0.0)
    up_move = (highs - prev_high).fillna(0.0)
    down_move = (prev_low - lows).fillna(0.0)
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    smoothed_tr = wilder_smooth(tr.iloc[1:].tolist(), period)
    smoothed_plus = wilder_smooth(plus_dm.iloc[1:].tolist(), period)
    smoothed_minus = wilder_smooth(minus_dm.iloc[1:].tolist(), period)
    adx = pd.Series(np.nan, index=df.index, dtype=float)
    plus_di = pd.Series(np.nan, index=df.index, dtype=float)
    minus_di = pd.Series(np.nan, index=df.index, dtype=float)
    atr = pd.Series(np.nan, index=df.index, dtype=float)
    dx_series = []
    min_len = min(len(smoothed_tr), len(smoothed_plus), len(smoothed_minus))
    for i in range(min_len):
        idx = i + period
        tr_val = smoothed_tr[i]
        atr.iloc[idx] = tr_val / period
        if tr_val <= 0:
            plus = 0.0
            minus = 0.0
            dx = 0.0
        else:
            plus = 100.0 * smoothed_plus[i] / tr_val
            minus = 100.0 * smoothed_minus[i] / tr_val
            denom = plus + minus
            dx = 0.0 if denom <= 0 else 100.0 * abs(plus - minus) / denom
        plus_di.iloc[idx] = plus
        minus_di.iloc[idx] = minus
        dx_series.append(dx)
    adx_smoothed = wilder_smooth(dx_series, period)
    for i, value in enumerate(adx_smoothed, start=(period * 2) - 1):
        if i < len(adx):
            adx.iloc[i] = value / period
    return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di, "atr": atr}


def compute_macd_histogram(closes: pd.Series) -> pd.Series:
    prices = _as_float_series(closes)
    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def bollinger(closes: pd.Series, window: int = 20) -> dict[str, pd.Series]:
    prices = _as_float_series(closes)
    mid = prices.rolling(window).mean()
    std = prices.rolling(window).std()
    upper = mid + (2.0 * std)
    lower = mid - (2.0 * std)
    return {"mid": mid, "upper": upper, "lower": lower}


def clamp(value: float, low: float, high: float) -> float:
    return float(max(low, min(high, value)))


def safe_log10(value: float) -> float:
    if value is None or value <= 0:
        return float("nan")
    return float(math.log10(value))
