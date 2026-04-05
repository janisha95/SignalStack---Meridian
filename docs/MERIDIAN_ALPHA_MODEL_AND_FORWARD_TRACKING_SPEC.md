# MERIDIAN: Alpha Model + Forward Tracking Spec

**Date:** 2026-03-27
**Status:** PLANNING — for implementation after backfill completes
**Priority:** P0 (both needed before prop firm eval)

---

## Part A: Forward Tracking

### Why This Comes First
Before changing the scoring formula (Alpha Model), we need a way 
to measure whether ANY formula produces profitable picks. Forward 
tracking records today's picks and then checks 5 days later whether 
they hit their TBM targets (+2% profit or -1% stop). Without this, 
we're flying blind.

### What Forward Tracking Does
1. Every time the orchestrator runs, snapshot today's top picks 
   with their entry price
2. After 5 trading days, check the OHLCV data to see if each pick:
   - Hit +2% from entry (WIN)
   - Hit -1% from entry (LOSE)  
   - Neither within 5 days (TIMEOUT)
3. Compute running win rate, compare to 33.3% breakeven
4. Display results on the dashboard

### New DB Table: pick_tracking

```sql
CREATE TABLE IF NOT EXISTS pick_tracking (
    pick_date TEXT NOT NULL,          -- date the pick was generated
    eval_date TEXT,                   -- date the outcome was evaluated (pick_date + 5 trading days)
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,          -- LONG or SHORT
    entry_price REAL NOT NULL,        -- close price on pick_date
    tcn_score REAL,                   -- TCN probability at time of pick
    factor_rank REAL,                 -- factor rank at time of pick
    final_score REAL,                 -- blend score at time of pick
    residual_alpha REAL,              -- residual alpha at time of pick
    rank INTEGER,                     -- rank within direction pool
    -- Outcome fields (filled after 5 days)
    outcome TEXT,                     -- WIN / LOSE / TIMEOUT / PENDING
    exit_price REAL,                  -- price when outcome was determined
    exit_date TEXT,                   -- date when +2% or -1% was hit
    return_pct REAL,                  -- actual return from entry to exit
    days_held INTEGER,                -- trading days from entry to outcome
    hit_tp_first INTEGER,             -- 1 if +2% hit before -1%, 0 otherwise
    -- Metadata
    regime TEXT,
    sector TEXT,
    beta REAL,
    PRIMARY KEY (pick_date, ticker)
);

CREATE INDEX IF NOT EXISTS idx_pt_outcome ON pick_tracking(outcome);
CREATE INDEX IF NOT EXISTS idx_pt_direction ON pick_tracking(direction);
```

### Evaluation Logic

```python
def evaluate_pick(ticker, direction, entry_price, ohlcv_5d):
    """Check if pick hit TBM targets within 5 trading days.
    
    Args:
        ticker: stock ticker
        direction: LONG or SHORT
        entry_price: close price on pick date
        ohlcv_5d: DataFrame of 5 trading days of OHLCV after pick date
    
    Returns:
        dict with outcome, exit_price, exit_date, return_pct, days_held
    """
    TP_PCT = 0.02   # +2% take profit
    SL_PCT = 0.01   # -1% stop loss
    
    for i, (date, row) in enumerate(ohlcv_5d.iterrows()):
        if direction == "LONG":
            # Check if high hit TP
            if row["high"] >= entry_price * (1 + TP_PCT):
                return {
                    "outcome": "WIN",
                    "exit_price": round(entry_price * (1 + TP_PCT), 2),
                    "exit_date": str(date),
                    "return_pct": TP_PCT,
                    "days_held": i + 1,
                    "hit_tp_first": 1,
                }
            # Check if low hit SL
            if row["low"] <= entry_price * (1 - SL_PCT):
                return {
                    "outcome": "LOSE",
                    "exit_price": round(entry_price * (1 - SL_PCT), 2),
                    "exit_date": str(date),
                    "return_pct": -SL_PCT,
                    "days_held": i + 1,
                    "hit_tp_first": 0,
                }
        else:  # SHORT
            # Check if low hit TP (price dropped 2%)
            if row["low"] <= entry_price * (1 - TP_PCT):
                return {
                    "outcome": "WIN",
                    "exit_price": round(entry_price * (1 - TP_PCT), 2),
                    "exit_date": str(date),
                    "return_pct": TP_PCT,
                    "days_held": i + 1,
                    "hit_tp_first": 1,
                }
            # Check if high hit SL (price rose 1%)
            if row["high"] >= entry_price * (1 + SL_PCT):
                return {
                    "outcome": "LOSE",
                    "exit_price": round(entry_price * (1 + SL_PCT), 2),
                    "exit_date": str(date),
                    "return_pct": -SL_PCT,
                    "days_held": i + 1,
                    "hit_tp_first": 0,
                }
    
    # Neither hit within 5 days — TIMEOUT
    last_close = ohlcv_5d.iloc[-1]["close"]
    if direction == "LONG":
        actual_return = (last_close - entry_price) / entry_price
    else:
        actual_return = (entry_price - last_close) / entry_price
    
    return {
        "outcome": "TIMEOUT",
        "exit_price": round(last_close, 2),
        "exit_date": str(ohlcv_5d.index[-1]),
        "return_pct": round(actual_return, 6),
        "days_held": len(ohlcv_5d),
        "hit_tp_first": 0,
    }
```

### Integration Points

1. **After Stage 5 runs (orchestrator):** Insert today's picks into 
   pick_tracking with outcome=PENDING

2. **Daily evaluation job:** Check all PENDING picks where 
   pick_date + 5 trading days <= today. Load OHLCV, evaluate, 
   update outcome.

3. **API endpoint:** /api/tracking/summary returns:
   - Total picks, wins, losses, timeouts
   - Win rate (overall, by direction, by TCN bucket)
   - Average return per pick
   - Running P&L curve

4. **Dashboard:** Model page shows forward tracking results as 
   a validation chart (win rate over time, P&L curve)

### CLI for Manual Evaluation

```bash
# Evaluate all pending picks
python3 stages/v2_forward_tracker.py --evaluate

# Backfill evaluations for past picks
python3 stages/v2_forward_tracker.py --backfill --start-date 2026-03-20

# Show summary
python3 stages/v2_forward_tracker.py --summary
```

---

## Part B: Alpha Model (Stage 5 Replacement)

### Prerequisites
- Forward tracking MUST be running first
- Backfill must be complete (need training data)
- Current 60/40 blend system must have 2+ weeks of tracked picks

### Design Principles (Lessons from Today's Disaster)
1. PLAN BEFORE BUILDING — no code changes until spec is fully reviewed
2. BACKUP BEFORE CHANGING — git commit before any modification
3. ONE SPEC, ONE IMPLEMENTATION — no fragments, no patches
4. TEST ON HISTORICAL DATA FIRST — backtest before production
5. A/B COMPARISON — run alpha model alongside blend, compare forward 
   tracking results before switching

### The Alpha Model Formula

The TCN was trained with TBM labels: +2% = WIN (1), -1% = LOSE (0).
Convert probability to expected return:

```
E[r] = tcn_prob × 0.02 + (1 - tcn_prob) × (-0.01)
```

Breakeven: tcn_prob = 0.333 (E[r] = 0)

Full pipeline:
```
Step 1: E[r] = tcn_prob × 0.02 + (1 - tcn_prob) × (-0.01)
Step 2: conviction = 0.5 + 0.5 × factor_rank
Step 3: alpha = E[r] × conviction
Step 4: direction = LONG if alpha > 0, SHORT if alpha < 0
Step 5: Rank LONGs by alpha DESC, SHORTs by alpha ASC
```

NOTE: NO BETA STRIPPING in this version. Beta stripping caused 
inverse ETFs to dominate rankings (the disaster from today). 
Beta belongs in the Risk Model (Stage 6), not the Alpha Model.
If we add beta stripping later, it must be capped so it cannot 
exceed 50% of the raw alpha magnitude.

### Alpha Model Inputs (confirmed by Shan)
- tcn_score (from Stage 4B TCN scorer)
- factor_rank (cross-sectional percentile)
- predicted_return (from predictions_daily)
- residual_alpha (from beta computation)
- lgbm_score (when wired — future)

### What Changes vs Current 60/40 Blend
| Aspect | Current (60/40) | Alpha Model |
|--------|----------------|-------------|
| Direction | From residual_alpha sign | From alpha sign |
| Ranking | final_score = 0.60×FR + 0.40×TCN | alpha = E[r] × conviction |
| Shorts | Option D: invert TCN | Natural: low TCN → negative E[r] |
| Beta | In ranking formula | In Stage 6 risk only |
| Weights | Hand-written 60/40 | Derived from TBM thresholds |

### Implementation Plan
1. Build v2_forward_tracker.py FIRST
2. Run forward tracking for 2 weeks on current 60/40 blend
3. Build alpha model as a SEPARATE function in v2_selection.py
   (not replacing the blend — alongside it)
4. Run BOTH formulas, track picks from BOTH, compare win rates
5. When alpha model shows better forward tracking results → switch
6. Git commit at every step

### Phase 2: Ridge Calibrator (After Backfill)
Once backfill is complete with 5 years of data:
```python
# Train Ridge on walk-forward out-of-sample data
X = [tcn_score, factor_rank, predicted_return, residual_alpha]
y = actual_5d_forward_return
calibrator = Ridge(alpha=1.0)
calibrator.fit(X, y)
E_r_calibrated = calibrator.predict(X_live)
```
This REPLACES the probability-weighted E[r] with a learned E[r].
Only do this after forward tracking validates the probability approach.

### Phase 3: Portfolio Optimization (Post Prop Firm)
Replace top-N selection with mean-variance optimization.
Only after Phase 2 is validated.

---

## Implementation Order

```
WEEK 1 (This Weekend):
  1. Build v2_forward_tracker.py (Part A)
  2. Wire into orchestrator (record picks after Stage 5)
  3. Wire evaluation into daily job
  4. Add /api/tracking/summary endpoint
  5. Add tracking results to Model page in UI

WEEK 2 (After Prop Firm Eval Starts):
  6. Forward tracking accumulates data on 60/40 blend
  7. Build alpha model function (alongside, not replacing)
  8. Track alpha model picks in parallel
  9. Compare win rates

WEEK 3 (After 2 Weeks of Data):
  10. If alpha model wins → switch
  11. If blend wins → keep blend, investigate why
  12. Either way: data-driven decision, not opinion

AFTER BACKFILL COMPLETE:
  13. Ridge calibrator (Phase 2)
  14. Retrain TCN on full 5-year data
  15. Train LGBM + ensemble
```

---

## Acceptance Criteria

### Forward Tracking:
- [ ] pick_tracking table created
- [ ] Orchestrator inserts picks after Stage 5
- [ ] Evaluation job correctly identifies WIN/LOSE/TIMEOUT
- [ ] Short P&L computed correctly (price drop = win)
- [ ] /api/tracking/summary returns valid data
- [ ] Model page shows tracking chart
- [ ] CLI commands work (--evaluate, --backfill, --summary)

### Alpha Model (when built):
- [ ] compute_alpha() function alongside existing blend
- [ ] NO beta stripping (beta in Stage 6 only)
- [ ] Direction from sign of alpha
- [ ] No inverse ETFs in top candidates  
- [ ] Forward tracking records alpha model picks separately
- [ ] Git committed before and after changes
- [ ] Backtest on historical shortlist data before production
