# CODEX — Meridian Downstream Adapter Fixes (Run AFTER Stage 3/4/5 Rebuild)

## Context
The Stage 3/4/5 rebuild changes `shortlist_daily` columns:
- NEW columns: `tcn_long_score`, `tcn_short_score`
- LEGACY columns written as 0: `factor_rank`, `residual_alpha`, `beta`, `market_component`
- `tcn_score` = tcn_long_score for LONG, tcn_short_score for SHORT
- `final_score` = tcn_long_score for LONG, tcn_short_score for SHORT
- `direction` determined by which TCN scored higher
- `predicted_return` = 0 (LGBM killed)
- Shortlist now 5 LONG + 5 SHORT (was 30+30)

## Git backup
```bash
cd ~/SS/Vanguard && git add -A && git commit -m "backup: pre-adapter-fix"
cd ~/SS/Meridian && git add -A && git commit -m "backup: pre-adapter-fix"
```

## CHANGE 1: Meridian Adapter
### File: `~/SS/Vanguard/vanguard/api/adapters/meridian_adapter.py`

Read the file first:
```bash
cat ~/SS/Vanguard/vanguard/api/adapters/meridian_adapter.py
```

Update the SQL query to read new columns. The adapter reads `shortlist_daily` and returns normalized rows. Change it to:
- Read `tcn_long_score` and `tcn_short_score` from shortlist_daily (these are new columns)
- If those columns don't exist yet (rebuild hasn't run), fall back to reading `tcn_score` and `final_score`
- Map into native fields: `tcn_long_score`, `tcn_short_score`, `tcn_score`, `final_score`, `rank`
- Remove references to `residual_alpha`, `beta`, `factor_rank` as primary display fields

Use try/except for the new column names in case the old schema is still active:
```python
try:
    # New schema after rebuild
    rows = pd.read_sql("""
        SELECT ticker, direction, tcn_long_score, tcn_short_score, 
               final_score, rank, regime, sector, price, date
        FROM shortlist_daily WHERE date = ?
    """, con, params=(date,))
except:
    # Old schema fallback
    rows = pd.read_sql("""
        SELECT ticker, direction, tcn_score, factor_rank, final_score,
               predicted_return, rank, regime, sector, price, date
        FROM shortlist_daily WHERE date = ?
    """, con, params=(date,))
```

## CHANGE 2: Trade Desk tier logic
### File: `~/SS/Vanguard/vanguard/api/trade_desk.py`

Read the file first:
```bash
cat ~/SS/Vanguard/vanguard/api/trade_desk.py
```

Find where Meridian tiers are defined. Currently uses thresholds like `tcn_score >= 0.53` and `factor_rank >= 0.60`.

Replace with simple tier logic:
- `tier_meridian_long`: direction == LONG, sorted by tcn_long_score DESC, top 5
- `tier_meridian_short`: direction == SHORT, sorted by tcn_short_score DESC, top 5
- No threshold filtering needed — the shortlist already contains only top 5 per direction

## CHANGE 3: Field Registry
### File: `~/SS/Vanguard/vanguard/api/field_registry.py`

Read the file:
```bash
cat ~/SS/Vanguard/vanguard/api/field_registry.py
```

Add new fields:
```python
{"key": "tcn_long_score", "label": "TCN Long", "type": "number", "sources": ["meridian"], ...}
{"key": "tcn_short_score", "label": "TCN Short", "type": "number", "sources": ["meridian"], ...}
```

Mark as deprecated (don't remove, just deprioritize):
- `factor_rank` — still in schema but always 0
- `residual_alpha` — always 0
- `beta` — always 0
- `lgbm_long_prob` — removed from pipeline
- `lgbm_short_prob` — removed from pipeline

## CHANGE 4: Userviews default columns
### File: `~/SS/Vanguard/vanguard/api/userviews.py`

Read the file:
```bash
cat ~/SS/Vanguard/vanguard/api/userviews.py
```

Update default visible columns for Meridian views:
- Replace `factor_rank` with `tcn_long_score` or `tcn_short_score`
- Keep `final_score`, `rank`, `price`, `sector`

## CHANGE 5: Meridian API server
### File: `~/SS/Meridian/stages/v2_api_server.py`

Read the file:
```bash
grep -n "shortlist_daily\|factor_rank\|tcn_score\|final_score\|candidates" ~/SS/Meridian/stages/v2_api_server.py | head -20
```

Update the `/api/candidates` query to include `tcn_long_score`, `tcn_short_score`.

## CHANGE 6: Evening report Meridian thresholds
### File: `~/SS/Advance/s1_evening_report_v2.py`

Read the file:
```bash
grep -n "meridian\|MERIDIAN\|tcn_score\|factor_rank\|TCN_LONG\|FRANK" ~/SS/Advance/s1_evening_report_v2.py | head -20
```

Current thresholds: `tcn_score >= 0.53` and `factor_rank >= 0.60` for longs, `tcn_score < 0.40` and `factor_rank > 0.68` for shorts.

Update to: 
- Meridian Longs: top 5 from shortlist_daily where direction = 'LONG', sorted by final_score DESC
- Meridian Shorts: top 5 from shortlist_daily where direction = 'SHORT', sorted by final_score DESC
- No threshold needed — shortlist already filtered to top 5 each

## Verification
```bash
# Compile check all changed files
python3 -m py_compile ~/SS/Vanguard/vanguard/api/adapters/meridian_adapter.py
python3 -m py_compile ~/SS/Vanguard/vanguard/api/trade_desk.py
python3 -m py_compile ~/SS/Vanguard/vanguard/api/field_registry.py
python3 -m py_compile ~/SS/Vanguard/vanguard/api/userviews.py
python3 -m py_compile ~/SS/Meridian/stages/v2_api_server.py
python3 -m py_compile ~/SS/Advance/s1_evening_report_v2.py
```

## Commit
```bash
cd ~/SS/Vanguard && git add -A && git commit -m "fix: downstream adapters for Meridian Stage 3/4/5 rebuild — tcn_long/short_score columns"
cd ~/SS/Meridian && git add -A && git commit -m "fix: API server updated for tcn_long/short_score columns"
cd ~/SS/Advance && git add -A && git commit -m "fix: evening report Meridian thresholds simplified for 5+5 shortlist"
```
