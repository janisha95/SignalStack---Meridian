#!/usr/bin/env python3
"""
Meridian SHORT TCN Training — Vast.ai A100

Same architecture as tcn_pass_v1 (LONG), but trained on INVERTED TBM labels:
  label=1 if price drops 2% before rising 1% (bearish setup)
  label=0 otherwise

Upload to Vast.ai:
  scp meridian_tcn_short_train.py root@<VAST_IP>:/workspace/
  scp ~/SS/Meridian/data/v2_universe.db root@<VAST_IP>:/workspace/  (or use factor_history parquet)

Run:
  cd /workspace && python3 meridian_tcn_short_train.py

Output:
  /workspace/output/tcn_short_v1/model.pt
  /workspace/output/tcn_short_v1/config.json
"""

import json
import os
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.stats import spearmanr
from torch.utils.data import DataLoader, Dataset

# ── Config ────────────────────────────────────────────────────────────────────

FEATURES = [
    "adx", "bb_position", "dist_from_ma20_atr", "rs_vs_spy_10d",
    "volume_participation", "momentum_acceleration", "volatility_rank",
    "wyckoff_phase", "ma_alignment", "leadership_score", "setup_score",
    "damage_depth", "volume_climax", "rs_vs_spy_20d",
    "ma_death_cross_proximity", "downside_volume_dominance",
    "phase_confidence", "directional_conviction", "vix_regime",
]

LOOKBACK = 64  # days of history per sample
TP_PCT = 0.02  # SHORT take profit: price drops 2%
SL_PCT = 0.01  # SHORT stop loss: price rises 1%
HORIZON_DAYS = 11  # same as LONG TCN

# Architecture — IDENTICAL to tcn_pass_v1
TCN_CHANNELS = [64, 64, 64, 32]
TCN_KERNEL = 3
TCN_DILATIONS = [1, 2, 4, 8]
TCN_DROPOUT = 0.3

EPOCHS = 30
BATCH_SIZE = 256
LR = 1e-3
WEIGHT_DECAY = 1e-5
PATIENCE = 5

DB_PATH = "/workspace/v2_universe.db"
OUTPUT_DIR = Path("/workspace/output/tcn_short_v1")

# ── Data Loading ──────────────────────────────────────────────────────────────

def load_data():
    """Load factor_history + daily_bars, compute SHORT TBM labels."""
    print("Loading factor_history...")
    con = sqlite3.connect(DB_PATH)
    
    fh = pd.read_sql(f"""
        SELECT ticker, date, {', '.join(FEATURES)}
        FROM factor_history
        WHERE date >= '2021-01-01'
        ORDER BY ticker, date
    """, con)
    print(f"  factor_history: {len(fh):,} rows, {fh['ticker'].nunique()} tickers")
    
    print("Loading daily_bars for label computation...")
    bars = pd.read_sql("""
        SELECT ticker, date, close, high, low
        FROM daily_bars
        WHERE date >= '2021-01-01'
        ORDER BY ticker, date
    """, con)
    con.close()
    print(f"  daily_bars: {len(bars):,} rows")
    
    # Compute SHORT TBM labels
    print("Computing SHORT TBM labels...")
    labels = compute_short_tbm_labels(bars)
    print(f"  Labels: {len(labels):,} rows, label=1 rate: {labels['label'].mean():.3f}")
    
    # Merge
    fh['date'] = pd.to_datetime(fh['date']).dt.strftime('%Y-%m-%d')
    labels['date'] = pd.to_datetime(labels['date']).dt.strftime('%Y-%m-%d')
    merged = fh.merge(labels[['ticker', 'date', 'label']], on=['ticker', 'date'], how='inner')
    merged = merged.dropna(subset=['label'])
    print(f"  Merged: {len(merged):,} rows")
    
    return merged


def compute_short_tbm_labels(bars):
    """
    SHORT Triple Barrier Method:
      label=1 if LOW reaches entry × (1 - TP_PCT) before HIGH reaches entry × (1 + SL_PCT)
      within HORIZON_DAYS forward bars.
      label=0 otherwise (stop loss hit or timeout).
    """
    results = []
    bars = bars.sort_values(['ticker', 'date']).reset_index(drop=True)
    
    tickers = bars['ticker'].unique()
    print(f"  Computing labels for {len(tickers)} tickers...")
    
    for i, ticker in enumerate(tickers):
        if i % 500 == 0:
            print(f"    {i}/{len(tickers)} tickers processed...")
        
        tb = bars[bars['ticker'] == ticker].reset_index(drop=True)
        closes = tb['close'].values
        highs = tb['high'].values
        lows = tb['low'].values
        dates = tb['date'].values
        
        for j in range(len(tb) - HORIZON_DAYS):
            entry = closes[j]
            tp_level = entry * (1 - TP_PCT)   # price must DROP to this
            sl_level = entry * (1 + SL_PCT)   # price must NOT RISE to this
            
            label = 0  # default: timeout / stop loss
            for k in range(j + 1, min(j + 1 + HORIZON_DAYS, len(tb))):
                if lows[k] <= tp_level:
                    label = 1  # SHORT TP hit — price dropped enough
                    break
                if highs[k] >= sl_level:
                    label = 0  # SHORT SL hit — price rose
                    break
            
            results.append({
                'ticker': ticker,
                'date': dates[j],
                'label': label,
            })
    
    return pd.DataFrame(results)


# ── Dataset ───────────────────────────────────────────────────────────────────

class TCNDataset(Dataset):
    def __init__(self, sequences, labels):
        self.sequences = torch.tensor(sequences, dtype=torch.float32)
        self.labels = torch.tensor(labels, dtype=torch.float32)
    
    def __len__(self):
        return len(self.labels)
    
    def __getitem__(self, idx):
        return self.sequences[idx], self.labels[idx]


def build_sequences(df):
    """Build (N, LOOKBACK, n_features) sequences with cross-sectional rank normalization."""
    print("Building sequences...")
    feature_cols = FEATURES
    
    # Cross-sectional rank normalize per date
    print("  Cross-sectional rank normalization...")
    dates = sorted(df['date'].unique())
    normalized = []
    for date in dates:
        day_df = df[df['date'] == date].copy()
        for col in feature_cols:
            vals = day_df[col]
            day_df[col] = vals.rank(pct=True)
        normalized.append(day_df)
    df_norm = pd.concat(normalized, ignore_index=True)
    
    # Build sequences per ticker
    sequences = []
    labels = []
    tickers = df_norm['ticker'].unique()
    
    for ticker in tickers:
        tdf = df_norm[df_norm['ticker'] == ticker].sort_values('date')
        if len(tdf) < LOOKBACK:
            continue
        
        feats = tdf[feature_cols].values
        lbls = tdf['label'].values
        
        for i in range(LOOKBACK, len(tdf)):
            seq = feats[i - LOOKBACK:i]
            if np.isnan(seq).any():
                continue
            sequences.append(seq)
            labels.append(lbls[i])
    
    sequences = np.array(sequences)
    labels = np.array(labels)
    print(f"  Built {len(sequences):,} sequences, shape={sequences.shape}")
    print(f"  Label distribution: 1={labels.mean():.3f}, 0={1-labels.mean():.3f}")
    
    return sequences, labels


# ── TCN Architecture ──────────────────────────────────────────────────────────

class TemporalBlock(nn.Module):
    def __init__(self, in_ch, out_ch, kernel_size, dilation, dropout):
        super().__init__()
        padding = (kernel_size - 1) * dilation
        self.conv1 = nn.Conv1d(in_ch, out_ch, kernel_size, dilation=dilation, padding=padding)
        self.bn1 = nn.BatchNorm1d(out_ch)
        self.conv2 = nn.Conv1d(out_ch, out_ch, kernel_size, dilation=dilation, padding=padding)
        self.bn2 = nn.BatchNorm1d(out_ch)
        self.dropout = nn.Dropout(dropout)
        self.downsample = nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else None
        self.relu = nn.ReLU()
        self.padding = padding
    
    def forward(self, x):
        res = x
        out = self.conv1(x)[:, :, :x.size(2)]
        out = self.bn1(out)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.conv2(out)[:, :, :x.size(2)]
        out = self.bn2(out)
        out = self.relu(out)
        out = self.dropout(out)
        if self.downsample is not None:
            res = self.downsample(res)
        return self.relu(out + res)


class TCNClassifier(nn.Module):
    def __init__(self, n_features, channels, kernel_size, dilations, dropout):
        super().__init__()
        layers = []
        in_ch = n_features
        for i, out_ch in enumerate(channels):
            dilation = dilations[i] if i < len(dilations) else 1
            layers.append(TemporalBlock(in_ch, out_ch, kernel_size, dilation, dropout))
            in_ch = out_ch
        self.network = nn.Sequential(*layers)
        self.head = nn.Sequential(
            nn.Linear(channels[-1], 16),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(16, 1),
        )
    
    def forward(self, x):
        # x: (batch, seq_len, features) → (batch, features, seq_len)
        x = x.transpose(1, 2)
        x = self.network(x)
        x = x[:, :, -1]  # last timestep
        return self.head(x).squeeze(-1)


# ── Training ──────────────────────────────────────────────────────────────────

def train():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    
    # Load and prepare data
    df = load_data()
    sequences, labels = build_sequences(df)
    
    # Time-series split: last 20% for validation
    split_idx = int(len(sequences) * 0.8)
    train_seqs, val_seqs = sequences[:split_idx], sequences[split_idx:]
    train_lbls, val_lbls = labels[:split_idx], labels[split_idx:]
    
    print(f"\nTrain: {len(train_seqs):,}  Val: {len(val_seqs):,}")
    print(f"Train label=1 rate: {train_lbls.mean():.3f}")
    print(f"Val label=1 rate: {val_lbls.mean():.3f}")
    
    # Pos weight for class imbalance
    n_pos = train_lbls.sum()
    n_neg = len(train_lbls) - n_pos
    pos_weight = torch.tensor([n_neg / max(n_pos, 1)], device=device)
    print(f"pos_weight: {pos_weight.item():.2f}")
    
    train_ds = TCNDataset(train_seqs, train_lbls)
    val_ds = TCNDataset(val_seqs, val_lbls)
    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=4)
    val_dl = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=4)
    
    # Model
    model = TCNClassifier(
        n_features=len(FEATURES),
        channels=TCN_CHANNELS,
        kernel_size=TCN_KERNEL,
        dilations=TCN_DILATIONS,
        dropout=TCN_DROPOUT,
    ).to(device)
    
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    
    print(f"\nModel params: {sum(p.numel() for p in model.parameters()):,}")
    print(f"Training for {EPOCHS} epochs, patience={PATIENCE}...\n")
    
    best_ic = -999
    patience_counter = 0
    
    for epoch in range(EPOCHS):
        # Train
        model.train()
        train_loss = 0
        for X, y in train_dl:
            X, y = X.to(device), y.to(device)
            optimizer.zero_grad()
            logits = model(X)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(X)
        train_loss /= len(train_ds)
        
        # Validate
        model.eval()
        val_preds, val_true = [], []
        val_loss = 0
        with torch.no_grad():
            for X, y in val_dl:
                X, y = X.to(device), y.to(device)
                logits = model(X)
                loss = criterion(logits, y)
                val_loss += loss.item() * len(X)
                probs = torch.sigmoid(logits)
                val_preds.extend(probs.cpu().numpy())
                val_true.extend(y.cpu().numpy())
        val_loss /= len(val_ds)
        
        val_preds = np.array(val_preds)
        val_true = np.array(val_true)
        
        ic, _ = spearmanr(val_preds, val_true)
        hit_rate = ((val_preds > 0.5) == val_true).mean()
        
        # For SHORT model: high prob = likely to drop
        # IC should be positive (high pred → actually drops → label=1)
        print(f"Epoch {epoch+1:2d}/{EPOCHS}  "
              f"train_loss={train_loss:.4f}  val_loss={val_loss:.4f}  "
              f"IC={ic:+.4f}  hit_rate={hit_rate:.3f}  "
              f"pred_mean={val_preds.mean():.3f}  pred_std={val_preds.std():.3f}")
        
        if ic > best_ic:
            best_ic = ic
            patience_counter = 0
            torch.save(model.state_dict(), OUTPUT_DIR / "model.pt")
            print(f"  → New best IC={ic:+.4f}, saved model")
        else:
            patience_counter += 1
            if patience_counter >= PATIENCE:
                print(f"  → Early stopping at epoch {epoch+1}")
                break
    
    # Final evaluation
    model.load_state_dict(torch.load(OUTPUT_DIR / "model.pt", weights_only=True))
    model.eval()
    
    val_preds, val_true = [], []
    with torch.no_grad():
        for X, y in val_dl:
            X, y = X.to(device), y.to(device)
            probs = torch.sigmoid(model(X))
            val_preds.extend(probs.cpu().numpy())
            val_true.extend(y.cpu().numpy())
    
    val_preds = np.array(val_preds)
    val_true = np.array(val_true)
    ic, _ = spearmanr(val_preds, val_true)
    hit_rate = ((val_preds > 0.5) == val_true).mean()
    
    # Bucket analysis
    print(f"\n{'='*60}")
    print(f"  FINAL RESULTS — SHORT TCN v1")
    print(f"{'='*60}")
    print(f"  IC: {ic:+.4f}  (PASS if > +0.03)")
    print(f"  Hit rate: {hit_rate:.3f}")
    print(f"  Verdict: {'PASS' if ic > 0.03 else 'FAIL'}")
    
    bins = [0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.01]
    for i in range(len(bins) - 1):
        mask = (val_preds >= bins[i]) & (val_preds < bins[i+1])
        if mask.sum() > 0:
            bucket_wr = val_true[mask].mean()
            print(f"  [{bins[i]:.1f}-{bins[i+1]:.2f}): n={mask.sum():6d}  "
                  f"label=1 rate={bucket_wr:.3f}")
    
    # Save config
    config = {
        "type": "SHORT_TCN",
        "description": "TCN trained on inverted TBM labels — P(bearish)",
        "features": FEATURES,
        "n_features": len(FEATURES),
        "lookback": LOOKBACK,
        "architecture": {
            "channels": TCN_CHANNELS,
            "kernel_size": TCN_KERNEL,
            "dilations": TCN_DILATIONS,
            "dropout": TCN_DROPOUT,
        },
        "labeling": {
            "method": "TBM_SHORT",
            "tp_pct": TP_PCT,
            "sl_pct": SL_PCT,
            "horizon_days": HORIZON_DAYS,
        },
        "training": {
            "epochs_run": epoch + 1,
            "batch_size": BATCH_SIZE,
            "lr": LR,
            "train_samples": len(train_seqs),
            "val_samples": len(val_seqs),
        },
        "ic": float(ic),
        "hit_rate": float(hit_rate),
        "verdict": "PASS" if ic > 0.03 else "FAIL",
        "timestamp": pd.Timestamp.now().isoformat(),
    }
    
    with open(OUTPUT_DIR / "config.json", "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"\nModel saved to {OUTPUT_DIR}/model.pt")
    print(f"Config saved to {OUTPUT_DIR}/config.json")
    print(f"\nTo deploy:")
    print(f"  scp {OUTPUT_DIR}/model.pt ~/SS/Meridian/models/tcn_short_v1/")
    print(f"  scp {OUTPUT_DIR}/config.json ~/SS/Meridian/models/tcn_short_v1/")


if __name__ == "__main__":
    train()
