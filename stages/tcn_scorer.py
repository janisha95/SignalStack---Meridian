#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "tcn_pass_v1"
DB_PATH = ROOT / "data" / "v2_universe.db"
TCN_FEATURES = [
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
    "directional_conviction",
]
LOOKBACK = 64


BASE_QUERY_COLUMNS = {
    "date",
    "ticker",
    *TCN_FEATURES,
}


class CausalConv1d(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, kernel: int, dilation: int = 1):
        super().__init__()
        self.conv = nn.Conv1d(in_ch, out_ch, kernel, dilation=dilation)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        pad = (self.conv.kernel_size[0] - 1) * self.conv.dilation[0]
        if pad > 0:
            x = F.pad(x, (pad, 0))
        return self.conv(x)


class TCNBlock(nn.Module):
    def __init__(self, ch: int, kernel: int = 3, dilation: int = 1):
        super().__init__()
        self.c1 = CausalConv1d(ch, ch, kernel, dilation)
        self.c2 = CausalConv1d(ch, ch, kernel, dilation)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = torch.relu(self.c1(x))
        out = torch.relu(self.c2(out))
        return out + x


class TCNClassifier(nn.Module):
    def __init__(self, n_features: int, hidden: int = 64):
        super().__init__()
        self.inp = nn.Conv1d(n_features, hidden, 1)
        self.blocks = nn.ModuleList(
            [TCNBlock(hidden, 3, 2**i) for i in range(4)]
        )
        self.head = nn.Sequential(
            nn.Linear(hidden, 32),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.permute(0, 2, 1)
        x = torch.relu(self.inp(x))
        for block in self.blocks:
            x = block(x)
        return torch.sigmoid(self.head(x[:, :, -1])).squeeze(-1)


class _ShortResBlock(nn.Module):
    """ResNet-BN block used by SHORT_TCN models."""

    def __init__(self, in_ch: int, out_ch: int, kernel: int = 3, dilation: int = 1):
        super().__init__()
        self._pad = (kernel - 1) * dilation
        self.conv1 = nn.Conv1d(in_ch, out_ch, kernel, dilation=dilation)
        self.bn1 = nn.BatchNorm1d(out_ch)
        self.conv2 = nn.Conv1d(out_ch, out_ch, kernel, dilation=dilation)
        self.bn2 = nn.BatchNorm1d(out_ch)
        self.downsample: nn.Conv1d | None = (
            nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else None
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        identity = x
        out = F.pad(x, (self._pad, 0))
        out = F.relu(self.bn1(self.conv1(out)))
        out = F.pad(out, (self._pad, 0))
        out = self.bn2(self.conv2(out))
        if self.downsample is not None:
            identity = self.downsample(x)
        return F.relu(out + identity)


class ShortTCNClassifier(nn.Module):
    """ResNet-BN TCN used for SHORT_TCN model files (tcn_short_v1 etc.)."""

    def __init__(
        self,
        n_features: int,
        channels: list[int] | None = None,
        kernel: int = 3,
        dilations: list[int] | None = None,
        dropout: float = 0.3,
    ):
        super().__init__()
        channels = channels or [64, 64, 64, 32]
        dilations = dilations or [1, 2, 4, 8]
        blocks: list[nn.Module] = []
        in_ch = n_features
        for out_ch, dil in zip(channels, dilations):
            blocks.append(_ShortResBlock(in_ch, out_ch, kernel, dil))
            in_ch = out_ch
        self.network = nn.ModuleList(blocks)
        self.head = nn.Sequential(
            nn.Linear(channels[-1], 16),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(16, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.permute(0, 2, 1)
        for block in self.network:
            x = block(x)
        return torch.sigmoid(self.head(x[:, :, -1])).squeeze(-1)


class TCNScorer:
    """Load 64 days of cross-sectionally ranked factor history and score candidates."""

    FEATURES = TCN_FEATURES
    LOOKBACK = LOOKBACK

    def __init__(self, model_dir: str | Path | None = None, db_path: str | Path | None = None):
        model_dir = Path(model_dir) if model_dir else MODEL_DIR
        self.db_path = str(Path(db_path)) if db_path else str(DB_PATH)

        self.config: dict[str, object] = {}
        config_path = model_dir / "config.json"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as fh:
                self.config = json.load(fh)

        self.features = list(self.config.get("features", self.FEATURES))
        self.lookback = int(self.config.get("lookback", self.LOOKBACK))

        model_path = model_dir / "model.pt"
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        model_type = str(self.config.get("type", "TCN"))
        if model_type == "SHORT_TCN":
            arch = self.config.get("architecture", {})
            self.model: nn.Module = ShortTCNClassifier(
                n_features=len(self.features),
                channels=list(arch.get("channels", [64, 64, 64, 32])),
                kernel=int(arch.get("kernel_size", 3)),
                dilations=list(arch.get("dilations", [1, 2, 4, 8])),
                dropout=float(arch.get("dropout", 0.3)),
            )
        else:
            self.model = TCNClassifier(len(self.features))
        try:
            state = torch.load(model_path, map_location="cpu", weights_only=True)
        except TypeError:
            state = torch.load(model_path, map_location="cpu")
        self.model.load_state_dict(state)
        self.model.eval()
        print(
            f"[tcn_scorer] Loaded {model_type}: {len(self.features)} features, lookback={self.lookback}",
            flush=True,
        )

    def _load_factor_history(self, target_date: str) -> pd.DataFrame:
        con = sqlite3.connect(self.db_path, timeout=30)
        try:
            date_sql = f"""
                SELECT DISTINCT date
                FROM factor_history
                WHERE date <= ?
                ORDER BY date DESC
                LIMIT {self.lookback}
            """
            dates_df = pd.read_sql_query(date_sql, con, params=[target_date])
            if len(dates_df) < self.lookback:
                print(
                    f"[tcn_scorer] WARNING: only {len(dates_df)} days of history (need {self.lookback})",
                    flush=True,
                )
                if len(dates_df) < 10:
                    return pd.DataFrame()

            min_date = str(dates_df["date"].min())
            available_cols = {
                str(row[1])
                for row in con.execute("PRAGMA table_info(factor_history)").fetchall()
            }
            requested = list(self.features)
            present = [col for col in requested if col in available_cols]
            missing = [col for col in requested if col not in available_cols]
            if missing:
                print(
                    f"[tcn_scorer] WARNING: factor_history missing {len(missing)} features; "
                    f"using neutral fallback for {missing}",
                    flush=True,
                )
            select_cols = ["date", "ticker", *present]
            query_cols = ",".join(select_cols)
            frame = pd.read_sql_query(
                f"""
                SELECT {query_cols}
                FROM factor_history
                WHERE date >= ? AND date <= ?
                ORDER BY date ASC, ticker ASC
                """,
                con,
                params=[min_date, target_date],
            )
            for col in missing:
                # Missing schema-level features should behave as neutral inputs,
                # not as sequence-level missingness that disqualifies every ticker.
                frame[col] = 0.5
            # Treat columns that are >90% null across the window as structurally absent
            # (newly added features without historical backfill). Fill with 0.5 neutral,
            # same treatment as missing schema columns above.
            for col in present:
                if frame[col].isna().mean() > 0.9:
                    frame[col] = frame[col].fillna(0.5)
            return frame[["date", "ticker", *requested]]
        finally:
            con.close()

    def _rank_normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        ranked = frame.copy()
        for col in self.features:
            if col in ranked.columns:
                ranked[col] = ranked.groupby("date")[col].rank(pct=True, method="average")
        return ranked

    def score(self, target_date: str) -> pd.DataFrame:
        frame = self._load_factor_history(target_date)
        if frame.empty:
            print(f"[tcn_scorer] No factor history for {target_date}", flush=True)
            return pd.DataFrame(columns=["ticker", "tcn_score"])

        ranked = self._rank_normalize(frame)
        sequences: list[np.ndarray] = []
        tickers: list[str] = []

        for ticker, group in ranked.sort_values(["ticker", "date"]).groupby("ticker", sort=False):
            if len(group) < self.lookback:
                continue
            window = group[self.features].tail(self.lookback).to_numpy(dtype=np.float32)
            nan_pct = float(np.isnan(window).sum() / window.size) if window.size else 1.0
            if nan_pct > 0.3:
                continue
            window = np.nan_to_num(window, nan=0.5)
            sequences.append(window)
            tickers.append(str(ticker).upper())

        if not sequences:
            print(f"[tcn_scorer] No valid sequences for {target_date}", flush=True)
            return pd.DataFrame(columns=["ticker", "tcn_score"])

        x = torch.FloatTensor(np.asarray(sequences, dtype=np.float32))
        with torch.no_grad():
            scores = self.model(x).cpu().numpy()

        result = (
            pd.DataFrame({"ticker": tickers, "tcn_score": scores})
            .sort_values("tcn_score", ascending=False)
            .reset_index(drop=True)
        )
        print(
            f"[tcn_scorer] Scored {len(result)} tickers for {target_date}, "
            f"top={result['tcn_score'].max():.3f} bot={result['tcn_score'].min():.3f}",
            flush=True,
        )
        return result


if __name__ == "__main__":
    try:
        scorer = TCNScorer()
        print(f"Features: {scorer.features}")
        print("Model loaded successfully")
    except FileNotFoundError as exc:
        print(f"Model not found: {exc}")
        print("Download from Google Drive:")
        print("  meridian_tcn_pass_model.pt -> ~/SS/Meridian/models/tcn_pass_v1/model.pt")
        print("  meridian_tcn_pass_config.json -> ~/SS/Meridian/models/tcn_pass_v1/config.json")
