# STAGE 3B: Modules 2 + 3 — Structural Phase + Damage/Short-Side (11 factors)

**Files:**
- `stages/factors/m2_structural_phase.py` (5 factors)
- `stages/factors/m3_damage_shortside.py` (6 factors)

**Copy from S1:**
- `wyckoff.py` detect_wyckoff_phase → Module 2
- `brf.py` damage/rollover factors → Module 3

**Depends on:** OHLCV DataFrame per ticker (200+ bars)

---

## Module 2: Structural Phase (Wyckoff Logic) — 5 factors

Detects smart money positioning through Wyckoff phase analysis.
In S1, this was a strategy that only fired on ACCUMULATION/DISTRIBUTION.
In Meridian, it computes continuous phase values for EVERY ticker.

| # | Factor | Computation | Range | S1 Source |
|---|--------|-------------|-------|-----------|
| 1 | `wyckoff_phase` | Phase encoded: ACCUMULATION=1, MARKUP=0.5, DISTRIBUTION=-1, MARKDOWN=-0.5, UNKNOWN=0 | -1 to 1 | wyckoff.py detect_wyckoff_phase |
| 2 | `phase_confidence` | Confidence of current phase detection | 0.0 to 1.0 | wyckoff.py |
| 3 | `phase_age_days` | Days in current phase (capped at 60) | 0 to 60 | wyckoff.py |
| 4 | `vol_bias` | Volume pattern: accumulation (+) vs distribution (-) | -1 to 1 | wyckoff.py |
| 5 | `structure_quality` | Higher lows + vol bias confirmation composite | 0 to 1 | wyckoff.py |

### Wyckoff Phase Detection (from S1)

The core logic from `wyckoff.py` uses these signals:
- **Accumulation:** Price in range, volume declining, support holding, spring patterns
- **Markup:** Price breaking above range with volume confirmation
- **Distribution:** Price in range after uptrend, volume expanding on down bars
- **Markdown:** Price breaking below range with volume

**Key change from S1:** Don't filter for only ACCUMULATION/DISTRIBUTION. Compute
the phase for every ticker regardless. A ticker in MARKUP phase still gets a
`wyckoff_phase` value of 0.5 — the ML model decides if that's useful.

### vol_bias Computation

```python
def vol_bias(df: pd.DataFrame, window: int = 20) -> float:
    """Volume bias: accumulation vs distribution pattern.
    
    Compares volume on up days vs down days.
    +1 = all volume on up days (accumulation)
    -1 = all volume on down days (distribution)
     0 = balanced
    """
    recent = df.tail(window)
    up_vol = recent.loc[recent['close'] > recent['open'], 'volume'].sum()
    down_vol = recent.loc[recent['close'] <= recent['open'], 'volume'].sum()
    total = up_vol + down_vol
    if total == 0:
        return 0.0
    return (up_vol - down_vol) / total
```

---

## Module 3: Damage / Short-Side — 6 factors

Detects structural weakness and distribution patterns. In S1, BRF only computed
these for tickers that passed all 5 BRF conditions. In Meridian, compute for
EVERY ticker as continuous values. A healthy stock will have `damage_depth` near 0
and `days_below_ma50` at 0 — that's information too.

| # | Factor | Computation | Range | S1 Source |
|---|--------|-------------|-------|-----------|
| 1 | `damage_depth` | (MA50 - close) / close | ratio (0 = at MA50, positive = below) | brf.py — extend to all tickers |
| 2 | `days_below_ma50` | Consecutive bars where close < MA50 | 0 to 60 (capped) | NEW — build |
| 3 | `rollover_strength` | (open - close) / ATR on latest bar | ratio | brf.py — extend |
| 4 | `downside_volume_dominance` | Down-day volume sum / up-day volume sum (20 bars) | ratio (>1 = distribution) | NEW — build |
| 5 | `lower_highs_streak` | Consecutive lower 5-bar rolling highs | 0 to 20 (capped) | NEW — build |
| 6 | `ma_death_cross_proximity` | (MA50 - MA200) / price | ratio (negative = death cross territory) | NEW — build |

### Factor Computation Details

**damage_depth:**
```python
ma50 = closes.rolling(50).mean().iloc[-1]
damage = (ma50 - close) / close  # positive when below MA50
# No clamp — let the ML model see the full range
```

**days_below_ma50:**
```python
ma50 = closes.rolling(50).mean()
below = closes < ma50
# Count consecutive True from the end
count = 0
for val in reversed(below.values):
    if val:
        count += 1
    else:
        break
return min(count, 60)  # cap at 60
```

**downside_volume_dominance:**
```python
recent = df.tail(20)
down_vol = recent.loc[recent['close'] < recent['close'].shift(1), 'volume'].sum()
up_vol = recent.loc[recent['close'] >= recent['close'].shift(1), 'volume'].sum()
if up_vol == 0:
    return 5.0  # extreme distribution, capped
return down_vol / up_vol  # >1 = more volume on down days
```

**lower_highs_streak:**
```python
rolling_highs = df['high'].rolling(5).max()
# Count consecutive lower values from the end
count = 0
for i in range(len(rolling_highs) - 1, 0, -1):
    if rolling_highs.iloc[i] < rolling_highs.iloc[i-1]:
        count += 1
    else:
        break
return min(count, 20)
```

**ma_death_cross_proximity:**
```python
ma50 = closes.rolling(50).mean().iloc[-1]
ma200 = closes.rolling(200).mean().iloc[-1]
return (ma50 - ma200) / close  # negative = MA50 below MA200 (bearish)
```

---

## Tests

### test_m2_structural_phase.py
1. Returns 5 factors in output dict
2. wyckoff_phase bounded -1 to 1
3. phase_confidence bounded 0 to 1
4. phase_age_days bounded 0 to 60
5. vol_bias bounded -1 to 1
6. structure_quality bounded 0 to 1
7. Returns NaN dict on insufficient data (< 50 bars)
8. Handles constant price (no phase detected → UNKNOWN → 0)

### test_m3_damage_shortside.py
1. Returns 6 factors in output dict
2. damage_depth = 0 when price equals MA50
3. damage_depth > 0 when price below MA50
4. days_below_ma50 = 0 when price above MA50
5. downside_volume_dominance > 1 when down-volume exceeds up-volume
6. lower_highs_streak = 0 on consistently rising highs
7. ma_death_cross_proximity negative when MA50 < MA200
8. Returns NaN dict on insufficient data (< 50 bars for MA50, < 200 for MA200)
9. Handles zero volume gracefully

---

## Acceptance Criteria

- [ ] `stages/factors/m2_structural_phase.py` exists with `compute_factors()` returning 5 keys
- [ ] `stages/factors/m3_damage_shortside.py` exists with `compute_factors()` returning 6 keys
- [ ] Wyckoff phase computed for ALL tickers (not just ACCUMULATION/DISTRIBUTION)
- [ ] Damage factors computed for ALL tickers (not just BRF SELL signals)
- [ ] Edge cases: < 50 bars → NaN, < 200 bars → NaN for MA200-dependent factors only
- [ ] No imports from S1
- [ ] All unit tests pass
- [ ] QA report generated at `qa_report_stage3b.md`
