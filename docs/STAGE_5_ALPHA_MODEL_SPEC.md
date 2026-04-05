# STAGE 5: Alpha Model — Probability-Weighted E[r] Spec

**Status:** SPEC COMPLETE — ready for build  
**Target file:** `~/SS/Meridian/stages/v2_selection.py`  
**Also touches:** `~/SS/Meridian/stages/v2_api_server.py`  
**Does NOT touch:** Stages 1-4B, Stage 6-7, TCN model, factor engine  
**Notion ref:** https://www.notion.so/330b2399fcac81c6aeabd491cc7f1dd0

---

## Problem

Current Stage 5 has a hand-written blend formula:
```python
final_score = 0.60 × factor_rank + 0.40 × tcn_score
```

Three structural flaws:
1. **Direction is decoupled from scoring** — direction comes from side-aware factor percentiles, but TCN probability may disagree. A ticker can have TCN=0.95 (model says "go up") but be assigned SHORT.
2. **Arbitrary weights** — 60/40 is not learned from data. Same anti-pattern as S1 convergence formula.
3. **Multiple competing columns** — UI shows TCN Score, Factor Rank, Final Score, Exp Return, Residual Alpha. No clear source of truth.

---

## Solution: Probability-Weighted Expected Return

The TCN was trained with TBM labels: +2% = WIN (label=1), -1% = LOSE (label=0). Its output is P(WIN). Convert this back to expected return using the SAME thresholds:

```python
E[r] = tcn_prob * 0.02 + (1 - tcn_prob) * (-0.01)
```

This is NOT a hand-written formula. It is the mathematically exact calibration of the model's own training objective. Zero arbitrary weights.

**Direction from sign of E[r]:**
- E[r] > 0 → LONG (TCN prob > 0.333)
- E[r] < 0 → SHORT (TCN prob < 0.333)
- E[r] ≈ 0 → filtered out (near breakeven)

**Breakeven:** `p × 0.02 + (1-p) × (-0.01) = 0` → `p = 1/3 = 0.333`

---

## Full Alpha Computation Pipeline

```
Step 1: E[r] = tcn_prob × 0.02 + (1 - tcn_prob) × (-0.01)
           ↓
Step 2: conviction = 0.5 + 0.5 × factor_rank
           ↓
Step 3: alpha = E[r] × conviction
           ↓
Step 4: spy_alpha = (spy_tcn_prob × 0.02 + (1 - spy_tcn_prob) × (-0.01)) × spy_conviction
           ↓
Step 5: residual_alpha = alpha - (beta × spy_alpha)
           ↓
Step 6: direction = "LONG" if residual_alpha > 0 else "SHORT"
           ↓
Step 7: Rank LONGs by residual_alpha descending (highest positive = best)
         Rank SHORTs by residual_alpha ascending (most negative = best)
```

### Step explanations:

**Step 1 — E[r]:** Converts TCN classification probability to expected return.
- TCN=0.82 → E[r] = 0.82 × 0.02 + 0.18 × (-0.01) = +1.46%
- TCN=0.15 → E[r] = 0.15 × 0.02 + 0.85 × (-0.01) = -0.55%

**Step 2 — Conviction multiplier:** Factor rank (0-1 cross-sectional percentile) scales magnitude without changing sign. rank=0.99 → conviction=0.995 (keeps ~100% of E[r]). rank=0.10 → conviction=0.55 (dampens to ~55%). Floor of 0.5 prevents total zeroing.

**Step 3 — Alpha:** Conviction-scaled expected return. Primary scoring signal.

**Step 4 — SPY alpha:** Same formula applied to SPY for beta stripping.

**Step 5 — Residual alpha:** Strips market component. Isolates idiosyncratic edge.

**Step 6 — Direction:** From SIGN of residual_alpha. No separate direction assignment. No contradictions possible.

**Step 7 — Ranking:** LONGs highest-first, SHORTs lowest-first (most negative = strongest short).

---

## How Shorts Work

Shorts are tickers where:
1. TCN probability < 0.333 → negative E[r]
2. Factor rank may also be low → amplifies negative E[r]
3. After beta stripping, residual is still negative

Worked examples:

| Ticker | TCN | Factor Rank | E[r] | Conviction | Alpha | Beta | SPY Alpha | Residual | Dir |
|--------|-----|-------------|------|------------|-------|------|-----------|----------|-----|
| AVIG   | 0.82| 0.99        |+1.46%| 0.995      |+1.45% | 0.17 | +0.10%    | +1.43%   | LONG|
| CAH    | 0.89| 0.89        |+1.69%| 0.945      |+1.60% | 0.25 | +0.10%    | +1.57%   | LONG|
| XYZZ   | 0.15| 0.20        |-0.55%| 0.60       |-0.33% | 1.10 | +0.10%    | -0.44%   |SHORT|
| BADCO  | 0.08| 0.05        |-0.77%| 0.525      |-0.40% | 0.80 | +0.10%    | -0.48%   |SHORT|

SHORT ranking: BADCO (#1, -0.48%) > XYZZ (#2, -0.44%). Most negative = strongest short.

---

## Backend Changes (v2_selection.py)

### Constants to add:
```python
TBM_WIN_RETURN = 0.02
TBM_LOSE_RETURN = -0.01
TBM_BREAKEVEN_PROB = 1/3  # 0.3333
CONVICTION_FLOOR = 0.5
MIN_ALPHA_THRESHOLD = 0.001  # filter out near-zero alpha (noise)
```

### Replace the blend formula:

**REMOVE this pattern:**
```python
final_score = 0.60 * factor_rank + 0.40 * tcn_score
```

**REPLACE WITH:**
```python
def compute_alpha(tcn_prob, factor_rank, beta, spy_tcn_prob, spy_factor_rank):
    """Convert TCN probability + factor rank into a single alpha score.
    
    Direction comes from the SIGN of the output. No separate direction logic.
    """
    # Step 1: Expected return from TCN probability
    e_r = tcn_prob * TBM_WIN_RETURN + (1 - tcn_prob) * TBM_LOSE_RETURN
    
    # Step 2: Conviction multiplier from factor rank
    conviction = CONVICTION_FLOOR + (1 - CONVICTION_FLOOR) * factor_rank
    
    # Step 3: Alpha = conviction-scaled expected return
    alpha = e_r * conviction
    
    # Step 4: SPY alpha (same formula)
    spy_e_r = spy_tcn_prob * TBM_WIN_RETURN + (1 - spy_tcn_prob) * TBM_LOSE_RETURN
    spy_conviction = CONVICTION_FLOOR + (1 - CONVICTION_FLOOR) * spy_factor_rank
    spy_alpha = spy_e_r * spy_conviction
    
    # Step 5: Strip market component
    residual_alpha = alpha - (beta * spy_alpha)
    
    # Step 6: Direction from sign
    direction = "LONG" if residual_alpha > 0 else "SHORT"
    
    return {
        "expected_return": round(e_r, 6),
        "conviction": round(conviction, 4),
        "alpha": round(alpha, 6),
        "residual_alpha": round(residual_alpha, 6),
        "direction": direction,
    }
```

### Selection logic:
```python
# After computing alpha for all tickers:
longs = [t for t in scored if t["direction"] == "LONG" 
         and abs(t["residual_alpha"]) > MIN_ALPHA_THRESHOLD]
shorts = [t for t in scored if t["direction"] == "SHORT" 
          and abs(t["residual_alpha"]) > MIN_ALPHA_THRESHOLD]

# Rank: LONGs by residual_alpha DESCENDING (highest positive = best)
longs.sort(key=lambda x: x["residual_alpha"], reverse=True)
for i, t in enumerate(longs[:top_n]):
    t["rank"] = i + 1

# Rank: SHORTs by residual_alpha ASCENDING (most negative = best)
shorts.sort(key=lambda x: x["residual_alpha"])
for i, t in enumerate(shorts[:top_n]):
    t["rank"] = i + 1
```

### Fallback mode (no TCN model):
```python
# When TCN model files are missing:
# tcn_prob = 0.5 for all tickers (neutral)
# E[r] = 0.5 * 0.02 + 0.5 * (-0.01) = +0.005 (slightly positive)
# factor_rank alone drives conviction scaling
# All tickers get slightly positive E[r] → all LONG in fallback
# This is acceptable — factor-only mode is a degraded state
```

### DB schema change (shortlist_daily):

**ADD columns:**
- `expected_return REAL` — raw E[r] from TCN probability
- `conviction REAL` — factor_rank scaled multiplier
- `alpha REAL` — conviction-scaled E[r]

**KEEP columns:**
- `residual_alpha REAL` — already exists, now computed from alpha pipeline
- `direction TEXT` — already exists, now derived from sign
- `beta REAL` — already exists
- `tcn_score REAL` — keep for diagnostics
- `factor_rank REAL` — keep for diagnostics
- `rank INTEGER` — already exists
- `regime TEXT` — already exists
- `sector TEXT` — already exists
- `price REAL` — already exists

**REMOVE columns:**
- `final_score REAL` — replaced by alpha
- `predicted_return REAL` — replaced by expected_return

---

## API Changes (v2_api_server.py)

### `/api/candidates` response shape:

**BEFORE:**
```json
{
  "ticker": "AVIG",
  "direction": "LONG",
  "final_score": 0.79,
  "tcn_score": 0.82,
  "factor_rank": 0.99,
  "predicted_return": 0.116,
  "residual_alpha": 0.11,
  "beta": 0.17
}
```

**AFTER:**
```json
{
  "ticker": "AVIG",
  "direction": "LONG",
  "alpha": 0.0143,
  "conviction": 0.995,
  "tcn_prob": 0.82,
  "factor_rank": 0.99,
  "expected_return": 0.0146,
  "residual_alpha": 0.0143,
  "beta": 0.17,
  "regime": "TRENDING",
  "sector": "UNKNOWN",
  "rank": 1,
  "price": 41.22
}
```

**Key changes:**
- `final_score` → replaced by `alpha` (the residual_alpha IS the alpha)
- `predicted_return` → replaced by `expected_return` (from TCN probability)
- Added `conviction` field (factor_rank multiplier)
- `tcn_score` renamed to `tcn_prob` (clearer semantics)
- `direction` now derived from sign of alpha, not separately assigned

### Normalize function `_normalize_candidate_rows()`:
Update this function in v2_api_server.py to map the new column names from shortlist_daily to the API response shape above.

---

## UI Changes (React Dashboard — Candidates Page)

### Main table columns (AFTER):

| # | Ticker | Dir | Price | Alpha | Conviction | Sector |
|---|--------|-----|-------|-------|------------|--------|
| 1 | AVIG   | L   |$41.22 |+1.43% | ████████░░ | UNKN   |
| 2 | CAH    | L   |$207.57|+1.57% | ███████░░░ | HLTH   |
|...|  ...   | ... | ...   | ...   |    ...     |  ...   |
|31 | BADCO  | S   |$15.40 |-0.48% | ████░░░░░░ | TECH   |

- **Alpha** — residual_alpha as percentage. Green for LONG, red for SHORT. Sort by this.
- **Conviction** — horizontal bar, |alpha| relative to day's max. Visual only.
- **Dir** — L (green) or S (red) badge. Derived from sign of alpha.

### REMOVED from main table:
- TCN Score column
- Factor Rank column
- Final Score column
- Expected Return column
- Residual Alpha as separate column (it IS the Alpha column now)

### Detail panel (click to expand):
When user clicks a row, show diagnostic data:

| Label | Value | Source |
|-------|-------|--------|
| TCN Probability | 0.82 | Stage 4B scorer |
| Factor Rank | 0.99 | Stage 3 percentile |
| Expected Return | +1.46% | E[r] from TCN |
| Conviction | 0.995 | Factor rank multiplier |
| Raw Alpha | +1.45% | E[r] × conviction |
| Beta | 0.17 | 60-day regression |
| Residual Alpha | +1.43% | Alpha − beta × SPY |
| Regime | TRENDING | Stage 2 prefilter |
| Position Size | 47 shares | Stage 6 risk |
| Dollar Risk | $500 (0.5%) | ATR-based sizing |

Plus existing TradingView chart, ticker info card (OPEN, PREV CLOSE, VOLUME, etc.), and quick links.

---

## Claude Code Prompt

```
READ FIRST: ~/SS/Meridian/stages/v2_selection.py
READ ALSO: ~/SS/Meridian/stages/v2_api_server.py
READ SPEC:  ~/SS/Meridian/docs/STAGE_5_ALPHA_MODEL_SPEC.md

Task: Replace the hand-written 60/40 blend formula in Stage 5 with 
a probability-weighted expected return (alpha model).

The TCN was trained with TBM labels (+2% WIN, -1% LOSE). Convert its 
output probability to expected return:
  E[r] = tcn_prob * 0.02 + (1 - tcn_prob) * (-0.01)

Direction comes from the SIGN of the final alpha — no separate 
direction assignment. Positive = LONG, negative = SHORT.

Full pipeline per ticker:
1. E[r] = tcn_prob * 0.02 + (1 - tcn_prob) * (-0.01)
2. conviction = 0.5 + 0.5 * factor_rank
3. alpha = E[r] * conviction  
4. SPY alpha = same formula for SPY ticker
5. residual_alpha = alpha - (beta * spy_alpha)
6. direction = "LONG" if residual_alpha > 0 else "SHORT"
7. LONGs ranked by residual_alpha descending
   SHORTs ranked by residual_alpha ascending (most negative = best)

Constants:
  TBM_WIN_RETURN = 0.02
  TBM_LOSE_RETURN = -0.01
  CONVICTION_FLOOR = 0.5
  MIN_ALPHA_THRESHOLD = 0.001

Fallback when TCN model missing:
  tcn_prob = 0.5 for all tickers (neutral)
  Factor rank alone drives conviction scaling
  All tickers slightly positive E[r] → all LONG (degraded but valid)

DB changes to shortlist_daily:
  ADD: expected_return REAL, conviction REAL, alpha REAL
  KEEP: residual_alpha, direction, beta, tcn_score, factor_rank, rank, regime, sector, price
  REMOVE: final_score (replaced by alpha)

API changes to v2_api_server.py:
  /api/candidates response: rename final_score→alpha, 
  predicted_return→expected_return, tcn_score→tcn_prob,
  add conviction field
  Update _normalize_candidate_rows() to map new columns

Do NOT change stages 1-4B or 6-7.
Do NOT change the TCN model or training.
Do NOT change the factor engine or factor registry.

After changes:
  python3 -c "import ast; ast.parse(open('stages/v2_selection.py').read()); print('OK')"
  python3 -c "import ast; ast.parse(open('stages/v2_api_server.py').read()); print('OK')"
  python3 stages/v2_selection.py --dry-run --mock
  Verify output shows alpha, direction derived from sign, LONGs and SHORTs ranked correctly.
```

---

## Acceptance Criteria

### Backend (v2_selection.py):
- [ ] Uses probability-weighted E[r] formula, NOT 60/40 blend
- [ ] `compute_alpha()` function exists with the 7-step pipeline
- [ ] Direction derived from sign of residual_alpha, not separately assigned
- [ ] No hand-written blend weights anywhere in the file
- [ ] LONGs ranked by residual_alpha descending (highest positive = best)
- [ ] SHORTs ranked by residual_alpha ascending (most negative = best)
- [ ] Tickers with TCN < 0.333 produce negative E[r] and become SHORTs
- [ ] Tickers with TCN > 0.333 produce positive E[r] and become LONGs
- [ ] Fallback mode works with tcn_prob=0.5 when model files missing
- [ ] MIN_ALPHA_THRESHOLD filters out near-zero noise tickers
- [ ] shortlist_daily table has new columns: expected_return, conviction, alpha
- [ ] shortlist_daily table no longer writes final_score
- [ ] `py_compile` passes on v2_selection.py
- [ ] `--dry-run --mock` produces valid output with both LONGs and SHORTs

### API (v2_api_server.py):
- [ ] `/api/candidates` returns `alpha` field (not `final_score`)
- [ ] `/api/candidates` returns `expected_return` (not `predicted_return`)
- [ ] `/api/candidates` returns `tcn_prob` (not `tcn_score`)
- [ ] `/api/candidates` returns `conviction` field
- [ ] `_normalize_candidate_rows()` updated for new column mapping
- [ ] `py_compile` passes on v2_api_server.py

### UI (React Candidates page — separate task):
- [ ] Main table shows: #, Ticker, Dir, Price, Alpha, Conviction bar, Sector
- [ ] Alpha column shows percentage (green positive, red negative)
- [ ] Dir badge (L/S) derived from alpha sign
- [ ] Conviction bar scales relative to day's max |alpha|
- [ ] Click row expands detail panel with: TCN prob, factor rank, E[r], conviction, raw alpha, beta, residual alpha, regime, position size, dollar risk
- [ ] Detail panel includes existing TradingView chart + ticker info
- [ ] REMOVED from main table: TCN Score, Factor Rank, Final Score, Expected Return, Residual Alpha as separate columns
- [ ] Default sort: LONGs tab descending by alpha, SHORTs tab descending by |alpha|

---

## Why This Is Not S1 Convergence Formula Redux

S1 convergence formula — 7 hand-written weighted factors:
```python
convergence_score = (
    strategy_strength * 0.30
    + convergence_factor * 0.25
    + rf_bucket * 0.10
    + regime_factor * 0.10
    + source_factor * 0.10
    + purity_factor * 0.08
    + volume_factor * 0.07
)
```

New alpha formula — ZERO arbitrary weights:
- E[r] derived from model's own TBM training thresholds
- Conviction multiplier has ONE parameter (floor=0.5), a risk preference not a signal weight
- Beta stripping is standard quant math

The old formula BLENDED signals. The new formula CHAINS transformations:
probability → expected return → conviction scaling → beta stripping → alpha.
Each step refines the previous. No weighted sum of unrelated components.

---

## Future: Ridge Calibrator (Phase 2)

Once backfill reaches 3+ years with walk-forward test data:
```python
X = [tcn_prob, factor_rank]  # only 2 features
y = actual_5d_forward_return   # from walk-forward test sets
calibrator = Ridge(alpha=1.0)
calibrator.fit(X, y)
```
This REPLACES the probability-weighted E[r] with a learned combination.
Current approach is the correct bridge — works today, validates later.
