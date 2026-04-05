# STAGE 4B: ML Model Training — v2_model_trainer.py

**Status:** SPEC COMPLETE — ready for build
**Depends on:** Stage 4A training_data (1,083,306 rows, 386 dates, 34 factors)
**Output:** Trained LightGBM + TemporalCNN ensemble model files

---

## What Stage 4B Does

Trains a LightGBM model and a TemporalCNN model on the backfilled training 
data, validates via walk-forward backtesting, generates diagnostic plots, 
and saves model artifacts that Stage 5 can load for live scoring.

**Ensemble:** 0.6 × LightGBM + 0.4 × TemporalCNN = final predicted_return

---

## 1. Data Loading

### From training_data table (1.08M rows)

```python
import sqlite3
import pandas as pd

con = sqlite3.connect('data/v2_universe.db')
df = pd.read_sql('SELECT * FROM training_data WHERE forward_return_5d IS NOT NULL', con)

# Columns:
# - date, ticker (index)
# - 34 factor columns (features)
# - forward_return_5d (target)
# - regime, sector, price (metadata)
```

### Feature columns (from factor_registry.json, active=true)

```python
FEATURES = [
    'adx', 'directional_conviction', 'momentum_acceleration', 'momentum_impulse',
    'volume_participation', 'volume_flow_direction', 'effort_vs_result',
    'volatility_rank', 'volatility_acceleration', 'wick_rejection',
    'bb_position', 'ma_alignment', 'dist_from_ma20_atr',
    'wyckoff_phase', 'phase_confidence', 'phase_age_days',
    'vol_bias', 'structure_quality',
    'damage_depth', 'rollover_strength', 'downside_volume_dominance',
    'ma_death_cross_proximity',
    'leadership_score', 'pullback_score', 'shock_magnitude', 'setup_score',
    'rs_vs_spy_10d', 'rs_vs_spy_20d', 'rs_momentum',
    'options_pcr', 'options_unusual_vol',  # 100% NaN in training — LightGBM handles this
    'volume_climax', 'market_breadth', 'vix_regime',
]

TARGET = 'forward_return_5d'
```

### Drop columns with 100% NaN in training

```python
# options_pcr and options_unusual_vol are 100% NaN in training data.
# LightGBM CAN handle NaN natively, but a column that's ALWAYS NaN
# provides zero signal — it just adds noise to the tree splits.
# Remove them from training features.
TRAIN_FEATURES = [f for f in FEATURES if df[f].notna().any()]
# This will remove options_pcr and options_unusual_vol
```

---

## 2. Walk-Forward Validation

### Design

```
Total: 386 trading days (2024-09-03 to 2026-03-18)

Walk-forward windows (expanding train, fixed 20-day test):
  Window 1: Train [day 1 ... day 200]  Test [day 201 ... day 220]
  Window 2: Train [day 1 ... day 220]  Test [day 221 ... day 240]
  Window 3: Train [day 1 ... day 240]  Test [day 241 ... day 260]
  ...
  Window N: Train [day 1 ... day 366]  Test [day 367 ... day 386]

Each window:
  1. Train LightGBM on training dates
  2. Predict on test dates
  3. Compute IC (Spearman rank correlation between predicted and actual)
  4. Compute top-decile vs bottom-decile spread
  5. Store predictions for equity curve
```

### Implementation

```python
def walk_forward_validation(df, features, target, train_start_days=200, test_days=20):
    dates = sorted(df['date'].unique())
    results = []
    
    for i in range(train_start_days, len(dates) - test_days, test_days):
        train_dates = dates[:i]
        test_dates = dates[i:i + test_days]
        
        train_df = df[df['date'].isin(train_dates)]
        test_df = df[df['date'].isin(test_dates)]
        
        X_train = train_df[features]
        y_train = train_df[target]
        X_test = test_df[features]
        y_test = test_df[target]
        
        # Train LightGBM
        model = lgb.LGBMRegressor(
            n_estimators=500,
            max_depth=6,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=50,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=0.1,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
        )
        
        # Predict
        preds = model.predict(X_test)
        
        # IC per test day
        for date in test_dates:
            day_mask = test_df['date'] == date
            if day_mask.sum() < 50:
                continue
            day_preds = preds[day_mask.values]
            day_actual = y_test[day_mask].values
            ic = scipy.stats.spearmanr(day_preds, day_actual).correlation
            
            # Top/bottom decile spread
            n = len(day_preds)
            decile = n // 10
            sorted_idx = day_preds.argsort()
            top_decile_return = day_actual[sorted_idx[-decile:]].mean()
            bottom_decile_return = day_actual[sorted_idx[:decile]].mean()
            spread = top_decile_return - bottom_decile_return
            
            results.append({
                'window': i,
                'date': date,
                'ic': ic,
                'spread': spread,
                'top_decile': top_decile_return,
                'bottom_decile': bottom_decile_return,
                'n_tickers': day_mask.sum(),
            })
    
    return pd.DataFrame(results)
```

### Success Criteria

| Metric | Target | What it means |
|--------|--------|---------------|
| Mean IC | > 0.03 | Predictions have weak but positive rank correlation with actual returns |
| IC hit rate | > 55% | More than half of days have positive IC |
| Mean spread | > 0.5% | Top decile beats bottom decile by 0.5% per 5-day period |
| Spread hit rate | > 55% | Spread is positive more than half the time |

If mean IC < 0.02, the model is not adding value over random — investigate 
features, target, or data quality before proceeding.

---

## 3. LightGBM Model

### Hyperparameters

```python
LGBM_PARAMS = {
    'objective': 'regression',
    'metric': 'mae',
    'n_estimators': 800,
    'max_depth': 6,
    'learning_rate': 0.03,
    'num_leaves': 31,
    'min_child_samples': 50,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'reg_alpha': 0.1,
    'reg_lambda': 0.1,
    'random_state': 42,
    'n_jobs': -1,
    'verbose': -1,
}
```

### Training (final model)

After walk-forward validation confirms IC > 0.03, train the final model on ALL data:

```python
final_model = lgb.LGBMRegressor(**LGBM_PARAMS)
final_model.fit(df[TRAIN_FEATURES], df[TARGET])
final_model.booster_.save_model('models/lgbm_v1.txt')
```

### SHAP for explainability

```python
import shap
explainer = shap.TreeExplainer(final_model)
shap_values = explainer.shap_values(X_test.head(100))
# Save top SHAP factors per ticker for Stage 5 display
```

---

## 4. TemporalCNN Model

### Architecture

```python
import torch
import torch.nn as nn

class TemporalCNN(nn.Module):
    """1D CNN that processes the last 20 days of factor history per ticker."""
    def __init__(self, n_features=32, seq_len=20, hidden=64):
        super().__init__()
        self.conv1 = nn.Conv1d(n_features, hidden, kernel_size=3, padding=1)
        self.conv2 = nn.Conv1d(hidden, hidden, kernel_size=3, padding=1)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.fc = nn.Sequential(
            nn.Linear(hidden, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, 1),
        )
    
    def forward(self, x):
        # x shape: (batch, n_features, seq_len)
        x = torch.relu(self.conv1(x))
        x = torch.relu(self.conv2(x))
        x = self.pool(x).squeeze(-1)  # (batch, hidden)
        return self.fc(x).squeeze(-1)  # (batch,)
```

### Data preparation for TemporalCNN

Unlike LightGBM which sees one row per ticker-date, the TemporalCNN sees 
the LAST 20 DAYS of factor values for each ticker. This captures temporal 
patterns (is momentum accelerating? is damage getting worse?).

```python
def build_sequences(df, features, target, seq_len=20):
    """Build (ticker, date) → 20-day sequence arrays for TemporalCNN."""
    sequences = []
    targets = []
    
    for ticker, group in df.groupby('ticker'):
        group = group.sort_values('date')
        values = group[features].values  # shape: (n_days, n_features)
        returns = group[target].values
        
        for i in range(seq_len, len(group)):
            seq = values[i - seq_len:i]  # (20, n_features)
            if np.isnan(seq).sum() / seq.size > 0.5:
                continue  # skip if >50% NaN in sequence
            # Fill remaining NaN with 0 for CNN
            seq = np.nan_to_num(seq, nan=0.0)
            sequences.append(seq.T)  # (n_features, 20) for Conv1d
            targets.append(returns[i])
    
    return np.array(sequences), np.array(targets)
```

### Training

```python
from torch.utils.data import DataLoader, TensorDataset

X_seq, y_seq = build_sequences(train_df, TRAIN_FEATURES, TARGET)
dataset = TensorDataset(
    torch.FloatTensor(X_seq),
    torch.FloatTensor(y_seq),
)
loader = DataLoader(dataset, batch_size=512, shuffle=True)

model = TemporalCNN(n_features=len(TRAIN_FEATURES))
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
criterion = nn.MSELoss()

for epoch in range(30):
    model.train()
    total_loss = 0
    for X_batch, y_batch in loader:
        optimizer.zero_grad()
        pred = model(X_batch)
        loss = criterion(pred, y_batch)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    print(f'[tcnn] Epoch {epoch+1}/30 loss={total_loss/len(loader):.6f}')

torch.save(model.state_dict(), 'models/tcnn_v1.pt')
```

---

## 5. Ensemble

```python
def ensemble_predict(lgbm_model, tcnn_model, X_flat, X_seq, weights=(0.6, 0.4)):
    """Combine LightGBM (flat features) and TemporalCNN (sequences)."""
    lgbm_pred = lgbm_model.predict(X_flat)
    
    tcnn_model.eval()
    with torch.no_grad():
        tcnn_pred = tcnn_model(torch.FloatTensor(X_seq)).numpy()
    
    return weights[0] * lgbm_pred + weights[1] * tcnn_pred
```

---

## 6. Diagnostic Plots

Generate these as PNG files in data/plots/:

### 6a. Walk-forward IC time series
```python
plt.figure(figsize=(12, 4))
plt.bar(results['date'], results['ic'], color=['green' if ic > 0 else 'red' for ic in results['ic']])
plt.axhline(y=0, color='gray', linestyle='--')
plt.title('Daily IC (Spearman Rank Correlation)')
plt.ylabel('IC')
plt.savefig('data/plots/ic_timeseries.png', dpi=150, bbox_inches='tight')
```

### 6b. Feature importance (top 20)
```python
importance = final_model.feature_importances_
idx = importance.argsort()[-20:]
plt.figure(figsize=(8, 6))
plt.barh(np.array(TRAIN_FEATURES)[idx], importance[idx])
plt.title('LightGBM Feature Importance (Top 20)')
plt.savefig('data/plots/feature_importance.png', dpi=150, bbox_inches='tight')
```

### 6c. Calibration plot
```python
# Bucket predictions into deciles, plot avg predicted vs avg actual
pred_buckets = pd.qcut(all_preds, 10, labels=False)
cal_df = pd.DataFrame({'pred': all_preds, 'actual': all_actual, 'bucket': pred_buckets})
cal_agg = cal_df.groupby('bucket').agg({'pred': 'mean', 'actual': 'mean'})
plt.figure(figsize=(6, 6))
plt.scatter(cal_agg['pred'], cal_agg['actual'])
plt.plot([-0.05, 0.05], [-0.05, 0.05], 'k--')
plt.xlabel('Predicted Return')
plt.ylabel('Actual Return')
plt.title('Calibration: Predicted vs Actual')
plt.savefig('data/plots/calibration.png', dpi=150, bbox_inches='tight')
```

### 6d. Walk-forward equity curve
```python
# Cumulative return of top-decile picks
cum_return = (1 + results['top_decile']).cumprod() - 1
plt.figure(figsize=(12, 4))
plt.plot(results['date'], cum_return * 100, label='Top Decile')
plt.plot(results['date'], spy_cum * 100, label='SPY', alpha=0.5)
plt.title('Walk-Forward Equity Curve')
plt.ylabel('Cumulative Return (%)')
plt.legend()
plt.savefig('data/plots/equity_curve.png', dpi=150, bbox_inches='tight')
```

### 6e. Long IC vs Short IC
```python
# Split IC by direction
long_ic = [ic for pred, actual, ic in zip(preds, actuals, ics) if pred > 0]
short_ic = [ic for pred, actual, ic in zip(preds, actuals, ics) if pred < 0]
```

### 6f. SHAP waterfall for top prediction
```python
shap.plots.waterfall(shap_values[top_prediction_idx], max_display=15)
plt.savefig('data/plots/shap_waterfall.png', dpi=150, bbox_inches='tight')
```

---

## 7. Model Artifacts

Save to ~/SS/Meridian/models/:

```
models/
├── lgbm_v1.txt              # LightGBM booster
├── tcnn_v1.pt               # TemporalCNN state dict
├── model_meta.json           # Metadata
├── feature_list.json         # Ordered feature list used in training
└── walk_forward_results.csv  # Per-day IC and spread
```

### model_meta.json

```json
{
    "version": "v1",
    "trained_at": "2026-03-26T10:30:00-04:00",
    "training_rows": 1083306,
    "training_dates": 386,
    "feature_count": 32,
    "features_excluded": ["options_pcr", "options_unusual_vol"],
    "lgbm_params": { ... },
    "tcnn_architecture": "Conv1d(32→64)×2, Pool, FC(64→32→1)",
    "ensemble_weights": [0.6, 0.4],
    "walk_forward": {
        "mean_ic": 0.045,
        "ic_hit_rate": 0.62,
        "mean_spread": 0.008,
        "spread_hit_rate": 0.59,
        "windows": 9
    }
}
```

---

## 8. CLI

```bash
cd ~/SS/Meridian

# Full training pipeline
python3 stages/v2_model_trainer.py

# Just LightGBM (skip TemporalCNN)
python3 stages/v2_model_trainer.py --lgbm-only

# Just walk-forward validation (no final model save)
python3 stages/v2_model_trainer.py --validate-only

# Generate plots only (requires existing walk-forward results)
python3 stages/v2_model_trainer.py --plots-only

# Debug: train on 5 dates only
python3 stages/v2_model_trainer.py --debug --max-dates 5
```

---

## 9. Acceptance Criteria

- [ ] `stages/v2_model_trainer.py` exists and runs
- [ ] Loads training_data from v2_universe.db
- [ ] Excludes 100% NaN columns (options_pcr, options_unusual_vol)
- [ ] Walk-forward validation with expanding train window
- [ ] Computes daily IC and top/bottom decile spread
- [ ] LightGBM trains with early stopping
- [ ] TemporalCNN trains on 20-day sequences
- [ ] Ensemble combines 0.6 × LightGBM + 0.4 × TemporalCNN
- [ ] Saves model artifacts to models/
- [ ] Generates 6 diagnostic plots to data/plots/
- [ ] model_meta.json with training stats and walk-forward results
- [ ] feature_list.json saved
- [ ] Progress logging per OPERATIONAL_STANDARDS.md
- [ ] Mean IC printed at end
- [ ] No S1 imports
- [ ] QA report at qa_report_stage4b.md

---

## 10. MANDATORY Progress Logging

```
[trainer] Loading training data...
[trainer] Loaded 1,083,306 rows, 386 dates, 32 features (dropped 2 all-NaN)
[trainer] Walk-forward validation: 200-day initial train, 20-day test windows
[trainer] Window 1/9: train 200 days, test 20 days...
[trainer]   IC: 0.042, spread: 0.8%, top: +1.2%, bottom: +0.4%
[trainer] Window 2/9: train 220 days, test 20 days...
[trainer]   IC: 0.051, spread: 1.1%, top: +1.5%, bottom: +0.4%
...
[trainer] Walk-forward summary:
[trainer]   Mean IC: 0.045 (target: >0.03)
[trainer]   IC hit rate: 62% (target: >55%)
[trainer]   Mean spread: 0.8% (target: >0.5%)
[trainer]   Spread hit rate: 59% (target: >55%)
[trainer] VERDICT: PASS — model adds value over random
[trainer] Training final LightGBM on all 386 dates...
[trainer] Training TemporalCNN (30 epochs)...
[trainer]   Epoch 1/30 loss=0.002341
[trainer]   Epoch 10/30 loss=0.001205
[trainer]   Epoch 20/30 loss=0.000891
[trainer]   Epoch 30/30 loss=0.000782
[trainer] Generating diagnostic plots...
[trainer] Saved: data/plots/ic_timeseries.png
[trainer] Saved: data/plots/feature_importance.png
[trainer] Saved: data/plots/calibration.png
[trainer] Saved: data/plots/equity_curve.png
[trainer] Saved: models/lgbm_v1.txt
[trainer] Saved: models/tcnn_v1.pt
[trainer] Saved: models/model_meta.json
[trainer] DONE in 245.3s
```
