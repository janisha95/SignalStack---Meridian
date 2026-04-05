#!/usr/bin/env python3
"""Dual-model LGBM scorer for Meridian v2.

Primary mode:
- models/lgbm_long_v2/model.pkl
- models/lgbm_short_v2/model.pkl

Backward compatibility:
- falls back to legacy models/lgbm_pass_v1/model.pkl if v2 dual models
  are unavailable. In legacy mode, short probability is inferred as
  (1 - long probability).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "v2_universe.db"
LONG_MODEL_DIR = ROOT / "models" / "lgbm_long_v2"
SHORT_MODEL_DIR = ROOT / "models" / "lgbm_short_v2"
LEGACY_MODEL_DIR = ROOT / "models" / "lgbm_pass_v1"


def _connect_db(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


class LGBMScorer:
    """Score factor_matrix_daily rows using v2 dual LGBM models."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._long_model: Any = None
        self._short_model: Any = None
        self._legacy_model: Any = None
        self._long_features: list[str] = []
        self._short_features: list[str] = []
        self._legacy_features: list[str] = []
        self.mode = "unloaded"

        long_cfg = LONG_MODEL_DIR / "config.json"
        long_pkl = LONG_MODEL_DIR / "model.pkl"
        short_cfg = SHORT_MODEL_DIR / "config.json"
        short_pkl = SHORT_MODEL_DIR / "model.pkl"

        if long_cfg.exists() and long_pkl.exists() and short_cfg.exists() and short_pkl.exists():
            self._long_model = joblib.load(long_pkl)
            self._short_model = joblib.load(short_pkl)
            self._long_features = json.loads(long_cfg.read_text(encoding="utf-8"))["features"]
            self._short_features = json.loads(short_cfg.read_text(encoding="utf-8"))["features"]
            self.mode = "dual_v2"
            return

        legacy_cfg = LEGACY_MODEL_DIR / "config.json"
        legacy_pkl = LEGACY_MODEL_DIR / "model.pkl"
        if legacy_cfg.exists() and legacy_pkl.exists():
            self._legacy_model = joblib.load(legacy_pkl)
            self._legacy_features = json.loads(legacy_cfg.read_text(encoding="utf-8"))["features"]
            self.mode = "legacy_v1"
            return

        raise FileNotFoundError(
            "No LGBM model artifacts found. "
            "Expected dual v2 models or legacy models/lgbm_pass_v1/."
        )

    def _load_factor_rows(self, run_date: str) -> pd.DataFrame:
        con = _connect_db(self.db_path)
        try:
            df = pd.read_sql_query(
                "SELECT * FROM factor_matrix_daily WHERE date = ? ORDER BY ticker ASC",
                con,
                params=(run_date,),
            )
        finally:
            con.close()
        if df.empty:
            return pd.DataFrame()
        df["ticker"] = df["ticker"].astype(str).str.upper()
        return df

    @staticmethod
    def _feature_matrix(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
        work = df.copy()
        for col in features:
            if col not in work.columns:
                work[col] = np.nan
        return work[features].fillna(0).astype(float)

    def score(self, run_date: str) -> pd.DataFrame:
        """Return DataFrame[ticker, lgbm_long_prob, lgbm_short_prob, predicted_return]."""
        df = self._load_factor_rows(run_date)
        if df.empty:
            return pd.DataFrame(
                columns=["ticker", "lgbm_long_prob", "lgbm_short_prob", "predicted_return"]
            )

        if self.mode == "dual_v2":
            X_long = self._feature_matrix(df, self._long_features)
            X_short = self._feature_matrix(df, self._short_features)
            long_probs = self._long_model.predict_proba(X_long)[:, 1].astype(float)
            short_probs = self._short_model.predict_proba(X_short)[:, 1].astype(float)
        else:
            X = self._feature_matrix(df, self._legacy_features)
            long_probs = self._legacy_model.predict_proba(X)[:, 1].astype(float)
            short_probs = (1.0 - long_probs).astype(float)

        predicted_return = (long_probs - short_probs).astype(float)
        return pd.DataFrame(
            {
                "ticker": df["ticker"].values,
                "lgbm_long_prob": long_probs,
                "lgbm_short_prob": short_probs,
                "predicted_return": predicted_return,
            }
        )
