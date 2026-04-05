#!/usr/bin/env python3
"""
Train LGBM regressor for Meridian LONG selection.
Uses factor_history for features, forward 5-day return as label.
Filters out ETFs from training to avoid the TCN's ETF bias.
"""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DB = str(Path.home() / "SS/Meridian/data/v2_universe.db")

# Known ETFs to exclude from training (expand this list)
KNOWN_ETFS = {
    "SCHD", "GFLW", "DFAU", "NOBL", "SPYD", "FNDE", "AVLV", "SDY", "IDV",
    "COWZ", "HDV", "OIH", "BBJP", "VLUE", "GCOW", "VIG", "DVY", "DGRO",
    "VYM", "DGRW", "SCHG", "SCHA", "SCHB", "SCHX", "SCHF", "SCHE",
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "IVV", "VEA", "VWO",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB",
    "ARKK", "SARK", "TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY", "SVXY",
    "MSTZ", "QTEC", "QLD", "QID", "SSO", "SDS", "VXX", "VIXY",
    # Bond/money-market
    "FLOT", "VUSB", "GSY", "FLRN", "USFR", "ICSH", "JPST", "FTSM", "PULS",
    "BND", "AGG", "TLT", "SHY", "IEF", "LQD", "HYG", "JNK",
}


def load_data():
    con = sqlite3.connect(DB, timeout=30)

    print("Loading factor_history...")
    fh = pd.read_sql("SELECT * FROM factor_history", con)
    print(
        f"  Loaded {len(fh)} rows, {fh['date'].nunique()} dates, "
        f"{fh['ticker'].nunique()} tickers"
    )

    tcn_features = [
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
        "damage_depth",
        "rollover_strength",
        "rs_vs_spy_10d",
        "rs_vs_spy_20d",
        "rs_momentum",
    ]

    available = [f for f in tcn_features if f in fh.columns]
    missing = [f for f in tcn_features if f not in fh.columns]
    print(f"  Available TCN features: {len(available)}/{len(tcn_features)}")
    if missing:
        print(f"  Missing: {missing}")

    extra_cols = [
        c
        for c in fh.columns
        if c not in tcn_features + ["ticker", "date", "symbol"]
        and pd.api.types.is_numeric_dtype(fh[c])
    ]
    print(f"  Extra numeric columns available: {extra_cols[:10]}...")

    prices = pd.read_sql(
        """
        SELECT ticker, date, close
        FROM daily_bars
        WHERE close IS NOT NULL
        ORDER BY ticker, date
        """,
        con,
    )
    print(f"  Loaded {len(prices)} price rows from daily_bars")
    con.close()

    prices = prices.sort_values(["ticker", "date"])
    prices["fwd_5d_return"] = prices.groupby("ticker")["close"].transform(
        lambda x: x.shift(-5) / x - 1
    )

    merged = fh.merge(
        prices[["ticker", "date", "fwd_5d_return"]],
        on=["ticker", "date"],
        how="inner",
    )
    merged = merged.dropna(subset=["fwd_5d_return"])
    merged = merged[~merged["ticker"].isin(KNOWN_ETFS)]
    print(
        f"\n  After ETF exclusion: {len(merged)} rows, "
        f"{merged['ticker'].nunique()} tickers"
    )

    return merged, available, extra_cols


def train_lgbm(df, feature_cols, label_col="fwd_5d_return"):
    import lightgbm as lgb

    dates = sorted(df["date"].unique())
    n_dates = len(dates)
    train_cutoff = int(n_dates * 0.6)
    step = max(1, int(n_dates * 0.1))
    results = []

    for start in range(train_cutoff, n_dates - step, step):
        train_dates = dates[:start]
        test_dates = dates[start:start + step]

        train = df[df["date"].isin(train_dates)]
        test = df[df["date"].isin(test_dates)]

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
            X_train,
            y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )

        preds = model.predict(X_test)
        mask = ~np.isnan(preds) & ~np.isnan(y_test)
        ic_clean = spearmanr(preds[mask], y_test[mask])[0] if mask.sum() > 50 else np.nan

        results.append(
            {
                "train_end": train_dates[-1],
                "test_start": test_dates[0],
                "test_end": test_dates[-1],
                "train_rows": len(train),
                "test_rows": len(test),
                "ic": ic_clean,
            }
        )
        print(
            f"  Window {len(results)}: train={len(train):,} "
            f"test={len(test):,} IC={ic_clean:+.4f}"
        )

    if not results:
        print("ERROR: No valid walk-forward windows")
        return None, None

    ics = [r["ic"] for r in results if not np.isnan(r["ic"])]
    mean_ic = np.mean(ics) if ics else 0.0
    hit_rate = sum(1 for ic in ics if ic > 0) / len(ics) if ics else 0.0

    print("\n=== LGBM LONG RESULTS ===")
    print(f"  Windows: {len(results)}")
    print(f"  Mean IC: {mean_ic:+.4f} (TCN LONG: +0.105)")
    print(f"  Hit rate: {hit_rate:.1%}")
    print(f"  {'PASS' if mean_ic > 0.03 else 'FAIL'} — threshold: IC > 0.03")

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

    importances = sorted(
        zip(feature_cols, final_model.feature_importances_),
        key=lambda x: x[1],
        reverse=True,
    )
    print("\n  Top 10 features:")
    for name, imp in importances[:10]:
        print(f"    {name:30s} {imp:.0f}")

    return final_model, results


def main():
    print("=== Meridian LGBM LONG Training ===\n")

    data, features, extra = load_data()
    if data is None:
        return

    print(f"\n--- Training with TCN features ({len(features)}) ---")
    model_tcn, results_tcn = train_lgbm(data, features)

    all_features = features + [c for c in extra if c in data.columns]
    all_features = list(dict.fromkeys(all_features))
    all_features = [f for f in all_features if data[f].notna().sum() > len(data) * 0.5]

    if len(all_features) > len(features):
        print(f"\n--- Training with ALL features ({len(all_features)}) ---")
        train_lgbm(data, all_features)

    if model_tcn is not None:
        import joblib

        out_dir = Path.home() / "SS/Meridian/models/lgbm_long_v1"
        out_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(model_tcn, out_dir / "lgbm_long_v1.pkl")

        meta = {
            "model": "lgbm_long_v1",
            "features": features,
            "target": "fwd_5d_return",
            "training_rows": len(data),
            "training_tickers": data["ticker"].nunique(),
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
