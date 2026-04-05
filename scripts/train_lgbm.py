#!/usr/bin/env python3
"""Train Meridian v2 dual LGBM models from training_data.

Builds two binary classifiers from the full 5-year training_data table:
- lgbm_long_v2: P(+2% before -1%) proxy from forward_return_5d
- lgbm_short_v2: P(-2% before +1%) proxy from forward_return_5d

Artifacts:
- models/lgbm_long_v2/model.pkl
- models/lgbm_long_v2/config.json
- models/lgbm_short_v2/model.pkl
- models/lgbm_short_v2/config.json
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "v2_universe.db"
LONG_MODEL_DIR = ROOT / "models" / "lgbm_long_v2"
SHORT_MODEL_DIR = ROOT / "models" / "lgbm_short_v2"

FACTOR_FEATURES = [
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
    "bb_position",
    "ma_alignment",
    "dist_from_ma20_atr",
    "wyckoff_phase",
    "phase_confidence",
    "phase_age_days",
    "vol_bias",
    "structure_quality",
    "damage_depth",
    "rollover_strength",
    "downside_volume_dominance",
    "ma_death_cross_proximity",
    "leadership_score",
    "pullback_score",
    "shock_magnitude",
    "setup_score",
    "rs_vs_spy_10d",
    "rs_vs_spy_20d",
    "rs_momentum",
    "options_pcr",
    "options_unusual_vol",
    "volume_climax",
    "market_breadth",
    "vix_regime",
]

MODEL_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 63,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
    "n_estimators": 1000,
}


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _load_training_frame() -> pd.DataFrame:
    cols = ["date", "ticker", "forward_return_5d", *FACTOR_FEATURES]
    query = f"""
        SELECT {",".join(cols)}
        FROM training_data
        WHERE forward_return_5d IS NOT NULL
        ORDER BY date ASC, ticker ASC
    """
    con = _connect()
    try:
        df = pd.read_sql_query(query, con)
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    for col in ["forward_return_5d", *FACTOR_FEATURES]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float32)
    return df


def _split_dates(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, list[str], list[str]]:
    unique_dates = sorted(df["date"].dt.strftime("%Y-%m-%d").unique().tolist())
    split_idx = int(len(unique_dates) * 0.8)
    split_idx = min(max(split_idx, 1), len(unique_dates) - 1)
    train_dates = unique_dates[:split_idx]
    test_dates = unique_dates[split_idx:]
    train_mask = df["date"].dt.strftime("%Y-%m-%d").isin(train_dates)
    test_mask = df["date"].dt.strftime("%Y-%m-%d").isin(test_dates)
    return train_mask, test_mask, train_dates, test_dates


def _top20_hit_rate(labels: np.ndarray, probs: np.ndarray) -> float:
    if len(labels) == 0:
        return float("nan")
    threshold = np.quantile(probs, 0.8)
    sel = probs >= threshold
    if not np.any(sel):
        return float("nan")
    return float(labels[sel].mean())


def _feature_importance_map(model: lgb.LGBMClassifier, features: list[str], top_n: int = 15) -> list[dict[str, float]]:
    booster = model.booster_
    if booster is None:
        return []
    gains = booster.feature_importance(importance_type="gain")
    pairs = sorted(zip(features, gains), key=lambda x: float(x[1]), reverse=True)
    out: list[dict[str, float]] = []
    for name, gain in pairs[:top_n]:
        out.append({"feature": str(name), "gain": float(gain)})
    return out


def _train_binary_model(
    df: pd.DataFrame,
    *,
    label_name: str,
    positive_rule,
    negative_rule,
    model_dir: Path,
    ic_alignment: str,
) -> dict[str, object]:
    work = df.copy()
    work[label_name] = np.nan
    work.loc[positive_rule(work["forward_return_5d"]), label_name] = 1.0
    work.loc[negative_rule(work["forward_return_5d"]), label_name] = 0.0
    work = work.dropna(subset=[label_name]).copy()
    work[label_name] = work[label_name].astype(np.int8)

    train_mask, test_mask, train_dates, test_dates = _split_dates(work)
    train_df = work.loc[train_mask].copy()
    test_df = work.loc[test_mask].copy()

    X_train = train_df[FACTOR_FEATURES].fillna(0).astype(np.float32)
    y_train = train_df[label_name].astype(np.int8)
    X_test = test_df[FACTOR_FEATURES].fillna(0).astype(np.float32)
    y_test = test_df[label_name].astype(np.int8)

    pos = int(y_train.sum())
    neg = int(len(y_train) - pos)
    scale_pos_weight = float(neg / max(pos, 1))

    model = lgb.LGBMClassifier(
        **MODEL_PARAMS,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        eval_metric="binary_logloss",
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )

    probs = model.predict_proba(X_test)[:, 1].astype(np.float32)
    auc = float(roc_auc_score(y_test, probs))
    if ic_alignment == "negative":
        ic_target = (-test_df["forward_return_5d"]).astype(np.float32)
    else:
        ic_target = test_df["forward_return_5d"].astype(np.float32)
    ic = float(spearmanr(probs, ic_target, nan_policy="omit").statistic)
    hit_rate = _top20_hit_rate(y_test.to_numpy(dtype=np.float32), probs)
    feature_importance = _feature_importance_map(model, FACTOR_FEATURES, top_n=15)

    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_dir / "model.pkl")
    config = {
        "features": FACTOR_FEATURES,
        "label_name": label_name,
        "labeling": {
            "positive": "+2% before -1%" if label_name == "label_long" else "-2% before +1%",
            "negative": "-1% before +2%" if label_name == "label_long" else "+1% before -2%",
            "source_column": "forward_return_5d",
        },
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "train_dates": [train_dates[0], train_dates[-1]] if train_dates else [],
        "test_dates": [test_dates[0], test_dates[-1]] if test_dates else [],
        "n_features": len(FACTOR_FEATURES),
        "metrics": {
            "auc_roc": auc,
            "ic_spearman": ic,
            "top20_hit_rate": hit_rate,
            "best_iteration": int(getattr(model, "best_iteration_", 0) or 0),
            "scale_pos_weight": scale_pos_weight,
        },
        "feature_importance_top15": feature_importance,
        "params": {
            **MODEL_PARAMS,
            "scale_pos_weight": scale_pos_weight,
            "early_stopping_rounds": 50,
        },
    }
    (model_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return {
        "label_name": label_name,
        "rows": int(len(work)),
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "auc_roc": auc,
        "ic_spearman": ic,
        "top20_hit_rate": hit_rate,
        "scale_pos_weight": scale_pos_weight,
        "feature_importance_top15": feature_importance,
        "model_dir": str(model_dir),
    }


def main() -> None:
    print(f"[train_lgbm] Loading training_data from {DB_PATH}...")
    df = _load_training_frame()
    rows = len(df)
    dates = int(df["date"].nunique())
    tickers = int(df["ticker"].nunique())
    print(f"[train_lgbm] rows={rows:,} dates={dates} tickers={tickers}")
    print(f"[train_lgbm] Using {len(FACTOR_FEATURES)} factor features")
    print(f"[train_lgbm] Features: {FACTOR_FEATURES}")

    long_metrics = _train_binary_model(
        df,
        label_name="label_long",
        positive_rule=lambda s: s >= 0.02,
        negative_rule=lambda s: s <= -0.01,
        model_dir=LONG_MODEL_DIR,
        ic_alignment="positive",
    )
    short_metrics = _train_binary_model(
        df,
        label_name="label_short",
        positive_rule=lambda s: s <= -0.02,
        negative_rule=lambda s: s >= 0.01,
        model_dir=SHORT_MODEL_DIR,
        ic_alignment="negative",
    )

    summary = {
        "training_data": {"rows": rows, "dates": dates, "tickers": tickers},
        "features": FACTOR_FEATURES,
        "lgbm_long": long_metrics,
        "lgbm_short": short_metrics,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
