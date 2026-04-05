# CODEX — Train LGBM LONG Model for Meridian (Local, No GPU)

## Context
Diagnostic confirmed: Meridian LONG TCN (IC 0.105) has inherent bias toward
stable/low-volatility instruments (ETFs). The SHORT TCN (IC 0.392) is excellent
and stays. We need a better LONG model.

Plan: Train a LGBM regressor on Meridian's factor_history data for LONG selection.
If it beats the TCN LONG IC of 0.105 on individual stocks, deploy it.

## Step 1: Understand the training data

```bash
# What tables have historical factor data?
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name
"

# Check factor_history structure and size
sqlite3 ~/SS/Meridian/data/v2_universe.db "
PRAGMA table_info(factor_history)
"

sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT COUNT(*) as total_rows,
    COUNT(DISTINCT date) as dates,
    COUNT(DISTINCT ticker) as tickers,
    MIN(date) as first_date,
    MAX(date) as last_date
FROM factor_history
"

# What columns are available as features?
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT * FROM factor_history LIMIT 1
"

# Check if forward returns exist (needed as training labels)
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%return%'
"

# Check if there's price data we can compute forward returns from
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%price%' OR name LIKE '%cache%' OR name LIKE '%bar%')
"
```

## Step 2: Build training dataset

Create: `~/SS/Meridian/train_lgbm_long.py`

This script:
1. Loads factor_history (all historical factor data)
2. Computes forward 5-day returns as the training label (from price data or cache)
3. Filters to individual stocks only (exclude ETFs by a known list)
4. Trains LGBM regressor with walk-forward validation
5. Reports IC per fold and overall

```python
#!/usr/bin/env python3
"""
Train LGBM regressor for Meridian LONG selection.
Uses factor_history for features, forward 5-day return as label.
Filters out ETFs from training to avoid the TCN's ETF bias.
"""
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

DB = str(Path.home() / "SS/Meridian/data/v2_universe.db")

# Known ETFs to exclude from training (expand this list)
KNOWN_ETFS = {
    'SCHD', 'GFLW', 'DFAU', 'NOBL', 'SPYD', 'FNDE', 'AVLV', 'SDY', 'IDV',
    'COWZ', 'HDV', 'OIH', 'BBJP', 'VLUE', 'GCOW', 'VIG', 'DVY', 'DGRO',
    'VYM', 'DGRW', 'SCHG', 'SCHA', 'SCHB', 'SCHX', 'SCHF', 'SCHE',
    'SPY', 'QQQ', 'IWM', 'DIA', 'VOO', 'VTI', 'IVV', 'VEA', 'VWO',
    'XLK', 'XLF', 'XLE', 'XLV', 'XLI', 'XLY', 'XLP', 'XLU', 'XLB',
    'ARKK', 'SARK', 'TQQQ', 'SQQQ', 'SPXL', 'SPXS', 'UVXY', 'SVXY',
    'MSTZ', 'QTEC', 'QLD', 'QID', 'SSO', 'SDS', 'VXX', 'VIXY',
    # Bond/money-market
    'FLOT', 'VUSB', 'GSY', 'FLRN', 'USFR', 'ICSH', 'JPST', 'FTSM', 'PULS',
    'BND', 'AGG', 'TLT', 'SHY', 'IEF', 'LQD', 'HYG', 'JNK',
}

def load_data():
    con = sqlite3.connect(DB, timeout=30)
    
    # Load factor history
    print("Loading factor_history...")
    fh = pd.read_sql("SELECT * FROM factor_history", con)
    print(f"  Loaded {len(fh)} rows, {fh['date'].nunique()} dates, {fh['ticker'].nunique()} tickers")
    
    # Check available columns for features
    # The TCN uses these 19 features — use the same ones for LGBM:
    TCN_FEATURES = [
        'directional_conviction', 'momentum_acceleration', 'momentum_impulse',
        'volume_participation', 'volume_flow_direction', 'effort_vs_result',
        'volatility_rank', 'volatility_acceleration', 'wick_rejection',
        'bb_position', 'ma_alignment', 'dist_from_ma20_atr',
        'wyckoff_phase', 'phase_confidence', 'damage_depth',
        'rollover_strength', 'rs_vs_spy_10d', 'rs_vs_spy_20d', 'rs_momentum'
    ]
    
    # Check which features exist
    available = [f for f in TCN_FEATURES if f in fh.columns]
    missing = [f for f in TCN_FEATURES if f not in fh.columns]
    print(f"  Available TCN features: {len(available)}/{len(TCN_FEATURES)}")
    if missing:
        print(f"  Missing: {missing}")
    
    # Also check for extra useful features not in TCN
    extra_cols = [c for c in fh.columns 
                  if c not in TCN_FEATURES + ['ticker', 'date', 'symbol']
                  and fh[c].dtype in ['float64', 'int64', 'float32']]
    print(f"  Extra numeric columns available: {extra_cols[:10]}...")
    
    # Try to compute forward returns
    # We need close prices — check if cache table has them
    try:
        prices = pd.read_sql("""
            SELECT ticker, date, close 
            FROM cache_daily
            ORDER BY ticker, date
        """, con)
        print(f"  Loaded {len(prices)} price rows from cache_daily")
    except:
        try:
            # Try alternate price table
            tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", con)
            print(f"  Available tables: {tables['name'].tolist()}")
            prices = None
        except:
            prices = None
    
    con.close()
    
    if prices is None:
        print("ERROR: Cannot find price data to compute forward returns")
        print("Check available tables and find where close prices are stored")
        return None, None, None
    
    # Compute forward 5-day return
    prices = prices.sort_values(['ticker', 'date'])
    prices['fwd_5d_return'] = prices.groupby('ticker')['close'].transform(
        lambda x: x.shift(-5) / x - 1
    )
    
    # Merge features with labels
    merged = fh.merge(prices[['ticker', 'date', 'fwd_5d_return']], on=['ticker', 'date'], how='inner')
    merged = merged.dropna(subset=['fwd_5d_return'])
    
    # Exclude ETFs
    merged = merged[~merged['ticker'].isin(KNOWN_ETFS)]
    print(f"\n  After ETF exclusion: {len(merged)} rows, {merged['ticker'].nunique()} tickers")
    
    return merged, available, extra_cols


def train_lgbm(df, feature_cols, label_col='fwd_5d_return'):
    """Walk-forward train and evaluate LGBM regressor."""
    import lightgbm as lgb
    
    dates = sorted(df['date'].unique())
    n_dates = len(dates)
    
    # Walk-forward: train on 80% of dates, test on next 20%
    train_cutoff = int(n_dates * 0.6)
    step = max(1, int(n_dates * 0.1))
    
    results = []
    
    for start in range(train_cutoff, n_dates - step, step):
        train_dates = dates[:start]
        test_dates = dates[start:start+step]
        
        train = df[df['date'].isin(train_dates)]
        test = df[df['date'].isin(test_dates)]
        
        if len(train) < 1000 or len(test) < 100:
            continue
        
        X_train = train[feature_cols].fillna(0).values
        y_train = train[label_col].values
        X_test = test[feature_cols].fillna(0).values
        y_test = test[label_col].values
        
        model = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=31,
            feature_fraction=0.8,
            bagging_fraction=0.8,
            bagging_freq=5,
            min_child_samples=50,
            verbose=-1,
            random_state=42,
        )
        
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )
        
        preds = model.predict(X_test)
        ic, _ = spearmanr(preds, y_test)
        
        # Also check IC on non-NaN subset
        mask = ~np.isnan(preds) & ~np.isnan(y_test)
        if mask.sum() > 50:
            ic_clean, _ = spearmanr(preds[mask], y_test[mask])
        else:
            ic_clean = ic
        
        results.append({
            'train_end': train_dates[-1],
            'test_start': test_dates[0],
            'test_end': test_dates[-1],
            'train_rows': len(train),
            'test_rows': len(test),
            'ic': ic_clean,
        })
        
        print(f"  Window {len(results)}: train={len(train):,} test={len(test):,} IC={ic_clean:+.4f}")
    
    if not results:
        print("ERROR: No valid walk-forward windows")
        return None, None
    
    ics = [r['ic'] for r in results if not np.isnan(r['ic'])]
    mean_ic = np.mean(ics) if ics else 0
    hit_rate = sum(1 for ic in ics if ic > 0) / len(ics) if ics else 0
    
    print(f"\n=== LGBM LONG RESULTS ===")
    print(f"  Windows: {len(results)}")
    print(f"  Mean IC: {mean_ic:+.4f} (TCN LONG: +0.105)")
    print(f"  Hit rate: {hit_rate:.1%}")
    print(f"  {'PASS' if mean_ic > 0.03 else 'FAIL'} — threshold: IC > 0.03")
    
    # Train final model on all data
    X_all = df[feature_cols].fillna(0).values
    y_all = df[label_col].values
    
    final_model = lgb.LGBMRegressor(
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=5,
        min_child_samples=50,
        verbose=-1,
        random_state=42,
    )
    final_model.fit(X_all, y_all)
    
    # Feature importance
    importances = sorted(zip(feature_cols, final_model.feature_importances_),
                        key=lambda x: x[1], reverse=True)
    print(f"\n  Top 10 features:")
    for name, imp in importances[:10]:
        print(f"    {name:30s} {imp:.0f}")
    
    return final_model, results


def main():
    print("=== Meridian LGBM LONG Training ===\n")
    
    data, features, extra = load_data()
    if data is None:
        return
    
    # Try with TCN features first
    print(f"\n--- Training with TCN features ({len(features)}) ---")
    model_tcn, results_tcn = train_lgbm(data, features)
    
    # Try with ALL available numeric features
    all_features = features + [c for c in extra if c in data.columns]
    all_features = [f for f in all_features if data[f].notna().sum() > len(data) * 0.5]
    
    if len(all_features) > len(features):
        print(f"\n--- Training with ALL features ({len(all_features)}) ---")
        model_all, results_all = train_lgbm(data, all_features)
    
    # Save best model
    if model_tcn is not None:
        import joblib
        out_dir = Path.home() / "SS/Meridian/models/lgbm_long_v1"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        joblib.dump(model_tcn, out_dir / "lgbm_long_v1.pkl")
        
        import json
        meta = {
            "model": "lgbm_long_v1",
            "features": features,
            "target": "fwd_5d_return",
            "training_rows": len(data),
            "training_tickers": data['ticker'].nunique(),
            "etfs_excluded": True,
            "results": [r for r in (results_tcn or [])],
        }
        (out_dir / "config.json").write_text(json.dumps(meta, indent=2, default=str))
        
        print(f"\n  Saved to {out_dir}")
    
    print("\nDone. Check IC results above.")
    print("If Mean IC > 0.03, the LGBM LONG is usable.")
    print("If Mean IC > 0.105, it beats the TCN LONG.")


if __name__ == "__main__":
    main()
```

## Step 3: Run the training

```bash
cd ~/SS/Meridian && python3 train_lgbm_long.py
```

## Step 4: Report back

DO NOT deploy the model yet. Report:
1. How many training rows after ETF exclusion
2. How many walk-forward windows
3. Mean IC and hit rate
4. Top 10 feature importances
5. Whether it beats TCN LONG IC of +0.105

We decide deployment after seeing the numbers.

## Commit
```bash
cd ~/SS/Meridian && git add train_lgbm_long.py && git commit -m "feat: LGBM LONG training script (ETF-excluded)"
```
