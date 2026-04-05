# CLAUDE CODE TASK: Aggregate Historical 1m→5m Bars for Non-Equity + Re-run V4A

## Problem

Twelve Data historical backfill wrote 9.6M 1m bars for forex/crypto/metals:
- crypto: 3,423,788 bars (14 symbols)
- forex: 5,949,738 bars (35 symbols)  
- metal: 223,103 bars (4 symbols)

But only ~1,100 5m bars exist for these asset classes (from recent live polling).

V4A training backfill reads `vanguard_bars_5m`. It found 0 5m bars for non-equity, so it produced 0 training rows. V4B then skipped forex/crypto/commodity models ("0 rows < 5000 minimum").

## Fix: Two steps

### Step 1: Aggregate historical 1m bars → 5m bars

Read the existing bar aggregation logic:
```bash
# How does V1 aggregate 1m → 5m currently?
grep -n "aggregate\|1m.*5m\|derive\|resample\|5m\|5Min" \
  ~/SS/Vanguard/stages/vanguard_cache.py \
  ~/SS/Vanguard/vanguard/helpers/bars.py 2>/dev/null | head -30

# Check if --rebuild-5m flag exists
python3 ~/SS/Vanguard/stages/vanguard_cache.py --help 2>/dev/null | head -20

# Check bars.py helper
cat ~/SS/Vanguard/vanguard/helpers/bars.py 2>/dev/null | head -80
```

If `--rebuild-5m` exists, use it:
```bash
cd ~/SS/Vanguard && python3 stages/vanguard_cache.py --rebuild-5m
```

If it doesn't exist, write a standalone aggregation script. The logic is simple:
- Group 1m bars by (symbol, floor(timestamp to 5-min boundary))
- For each 5-min bucket: first open, max high, min low, last close, sum volume
- Bar end time = ceiling of the 5-min boundary (e.g., 09:30-09:34 → bar_ts = 09:35)
- Write to `vanguard_bars_5m` with same schema

```python
"""Aggregate historical 1m → 5m bars for non-equity asset classes."""
import sqlite3
import pandas as pd
from datetime import datetime

DB = "/Users/sjani008/SS/Vanguard/data/vanguard_universe.db"

con = sqlite3.connect(DB)
con.execute("PRAGMA journal_mode=WAL")
con.execute("PRAGMA busy_timeout=30000")

# Get schema of vanguard_bars_5m
schema = con.execute("PRAGMA table_info(vanguard_bars_5m)").fetchall()
print(f"5m schema: {[col[1] for col in schema]}")

# Count existing 5m bars by asset class
existing = con.execute("""
    SELECT asset_class, COUNT(*) FROM vanguard_bars_5m 
    WHERE asset_class IN ('forex','crypto','metal','commodity')
    GROUP BY asset_class
""").fetchall()
print(f"Existing 5m non-equity: {existing}")

# Process each non-equity asset class
for asset_class in ['forex', 'crypto', 'metal']:
    print(f"\n--- Processing {asset_class} ---")
    
    # Load 1m bars
    df = pd.read_sql(f"""
        SELECT * FROM vanguard_bars_1m 
        WHERE asset_class = '{asset_class}'
        ORDER BY symbol, timestamp
    """, con)
    
    if df.empty:
        print(f"  No 1m bars for {asset_class}")
        continue
    
    print(f"  Loaded {len(df):,} 1m bars for {df['symbol'].nunique()} symbols")
    
    # Parse timestamps
    df['ts'] = pd.to_datetime(df['timestamp'])
    
    # Floor to 5-minute boundaries
    df['bar_5m'] = df['ts'].dt.floor('5min')
    
    # Aggregate
    agg = df.groupby(['symbol', 'bar_5m', 'asset_class']).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).reset_index()
    
    # Bar end time = bar_5m + 5 minutes
    agg['timestamp'] = (agg['bar_5m'] + pd.Timedelta(minutes=5)).dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    agg['bar_count'] = df.groupby(['symbol', 'bar_5m']).size().reset_index(name='cnt')['cnt'].values
    
    # Add missing columns with defaults (check actual schema)
    if 'path' not in agg.columns:
        agg['path'] = 'twelvedata'
    if 'source' not in agg.columns:
        agg['source'] = 'twelvedata'
    if 'tick_volume' not in agg.columns:
        agg['tick_volume'] = agg['volume']
    if 'spread_avg' not in agg.columns:
        agg['spread_avg'] = 0
    
    print(f"  Aggregated to {len(agg):,} 5m bars")
    
    # Write to DB (INSERT OR IGNORE to avoid duplicates with live bars)
    # IMPORTANT: match exact column names from the 5m table schema
    # Adjust column mapping based on actual schema from PRAGMA above
    
    # ... write logic here based on actual schema ...
    
    print(f"  Written to vanguard_bars_5m")

con.close()
```

**IMPORTANT:** Before writing the aggregation, READ the actual `vanguard_bars_5m` schema and match columns exactly:
```bash
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "PRAGMA table_info(vanguard_bars_5m)"
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "SELECT * FROM vanguard_bars_5m LIMIT 3"
```

Also check the 1m schema:
```bash
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "PRAGMA table_info(vanguard_bars_1m)"
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "
SELECT * FROM vanguard_bars_1m WHERE asset_class='forex' LIMIT 3
"
```

### Step 2: Verify aggregation worked

```bash
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "
SELECT asset_class, COUNT(*) as bars_5m, COUNT(DISTINCT symbol) as symbols
FROM vanguard_bars_5m
WHERE asset_class IN ('forex','crypto','metal','commodity')
GROUP BY asset_class
"
```

Expected: hundreds of thousands of 5m bars per asset class (roughly 1m_count / 5).

### Step 3: Also aggregate 1m → 1h bars (V3 needs these for HTF features)

Same logic but floored to 60-minute boundaries:
```bash
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "
SELECT asset_class, COUNT(*) as bars_1h, COUNT(DISTINCT symbol) as symbols
FROM vanguard_bars_1h
WHERE asset_class IN ('forex','crypto','metal','commodity')
GROUP BY asset_class
"
```

If also sparse, aggregate 1m → 1h with the same approach.

### Step 4: Re-run V4A for non-equity asset classes

Check if V4A supports `--asset-class` flag:
```bash
python3 ~/SS/Vanguard/stages/vanguard_training_backfill_fast.py --help
```

If yes:
```bash
nohup python3 ~/SS/Vanguard/stages/vanguard_training_backfill_fast.py \
  --asset-class forex --workers 4 \
  >> ~/SS/Vanguard/logs/v4a_forex.log 2>&1 &

# After forex finishes:
nohup python3 ~/SS/Vanguard/stages/vanguard_training_backfill_fast.py \
  --asset-class crypto --workers 4 \
  >> ~/SS/Vanguard/logs/v4a_crypto.log 2>&1 &
```

If `--asset-class` doesn't exist, V4A should process all asset classes that have 5m bars — just re-run it with `--resume`:
```bash
nohup python3 ~/SS/Vanguard/stages/vanguard_training_backfill_fast.py \
  --resume --workers 4 \
  >> ~/SS/Vanguard/logs/v4a_training.log 2>&1 &
```

### Step 5: Verify training data exists for non-equity

```bash
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "
SELECT asset_class, COUNT(*) as rows, COUNT(DISTINCT symbol) as symbols,
       AVG(label_long) as long_wr, AVG(label_short) as short_wr
FROM vanguard_training_data
GROUP BY asset_class
"
```

Expected: rows for forex, crypto, metal in addition to equity.

### Step 6: Re-train V4B with multi-asset data

```bash
cd ~/SS/Vanguard && python3 stages/vanguard_model_trainer.py 2>&1 | tee ~/SS/Vanguard/logs/v4b_retrain.log
```

This time, forex/crypto/commodity should have >5000 rows and produce real models.

## Reporting

```
## 1m→5m Aggregation Results

### Before
- forex 5m: 752 bars
- crypto 5m: 277 bars  
- metal 5m: 103 bars

### After aggregation
- forex 5m: [X] bars ([Y] symbols)
- crypto 5m: [X] bars ([Y] symbols)
- metal 5m: [X] bars ([Y] symbols)

### V4A re-run
- forex training rows: [X] ([Y] symbols)
- crypto training rows: [X] ([Y] symbols)  
- metal training rows: [X] ([Y] symbols)

### V4B retrain
- lgbm_forex_long_v1: IC=[X], status=[trained/skipped]
- lgbm_forex_short_v1: IC=[X]
- lgbm_crypto_long_v1: IC=[X]
- lgbm_crypto_short_v1: IC=[X]
```

## Rules
- Read actual DB schemas before writing — column names must match exactly
- Use INSERT OR IGNORE to avoid clobbering live 5m bars from recent polling
- Bar end time convention: if 1m bar timestamps are bar-start, the 5m bar timestamp should be bar_start + 5 minutes
- Check the V1 spec: "ts_utc = bar END time (not open)" — make sure the aggregation respects this
- Git backup before any DB writes: the DB is 15GB, don't corrupt it
- Do NOT modify V4A or V4B code — just provide them with the data they expect
