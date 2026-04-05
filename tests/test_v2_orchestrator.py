from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from stages import v2_orchestrator as mod
from stages.v2_prefilter import PrefilterError
from stages.v2_selection import SelectionError


def _prefilter_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "SPY",
                "regime": "TRENDING",
                "price": 500.0,
                "dollar_volume": 5_000_000.0,
                "bars_available": 120,
                "atr_pct": 0.01,
                "adx": 20.0,
                "sector": "ETF",
            },
            {
                "ticker": "AAPL",
                "regime": "CHOPPY",
                "price": 252.61,
                "dollar_volume": 281_000_000.0,
                "bars_available": 120,
                "atr_pct": 0.021,
                "adx": 22.9,
                "sector": "Technology",
            },
        ]
    )


def _factor_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "AAPL", "date": "2026-03-26", "regime": "CHOPPY", "f1": 1.0, "f2": 2.0},
            {"ticker": "SPY", "date": "2026-03-26", "regime": "TRENDING", "f1": 0.5, "f2": 1.0},
        ]
    )


def _prediction_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "AAPL", "predicted_return": 0.012, "regime": "CHOPPY", "sector": "Technology", "price": 252.61},
            {"ticker": "SPY", "predicted_return": 0.004, "regime": "TRENDING", "sector": "ETF", "price": 500.0},
        ]
    )


def _shortlist_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "direction": "LONG",
                "predicted_return": 0.012,
                "beta": 1.1,
                "market_component": 0.0044,
                "residual_alpha": 0.0076,
                "rank": 12,
                "regime": "CHOPPY",
                "sector": "Technology",
                "price": 252.61,
                "top_shap_factors": None,
                "top_shap_list": [],
            }
        ]
    )


def _risk_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "direction": "LONG",
                "shares": 47,
                "entry_price": 252.61,
                "stop_price": 241.99,
                "tp_price": 273.85,
                "risk_dollars": 500.0,
                "risk_pct": 0.5,
                "position_value": 11872.67,
                "atr": 5.3112,
                "sector": "Technology",
                "regime": "CHOPPY",
                "rank": 12,
                "predicted_return": 0.012,
                "beta": 1.1,
                "residual_alpha": 0.0076,
                "filter_status": "APPROVED",
                "filter_reason": "APPROVED",
            }
        ]
    )


def _risk_state() -> dict[str, float]:
    return {
        "date": "2026-03-26",
        "account_balance": 100000.0,
        "daily_pnl": 0.0,
        "total_pnl": 0.0,
        "total_pnl_pct": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "open_positions": 0,
        "portfolio_heat_pct": 0.0,
        "daily_loss_remaining": 5000.0,
        "drawdown_remaining": 10000.0,
        "distance_to_target": 10000.0,
        "best_day_pnl": 0.0,
        "best_day_pct_of_total": 0.0,
        "trading_days": 0,
        "best_day_warning": False,
    }


def test_orchestrator_runs_stages_in_order(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    order: list[str] = []

    monkeypatch.setattr(mod, "_send_telegram_summary", lambda message, no_telegram: "SKIP")
    monkeypatch.setattr(mod, "_run_stage2", lambda db_path, args: order.append("2") or _prefilter_df())
    monkeypatch.setattr(mod, "_run_stage3", lambda db_path, args: order.append("3") or _factor_df())
    monkeypatch.setattr(mod, "_run_stage4_mock", lambda db_path, prefilter_df, dry_run: order.append("4") or _prediction_df())
    monkeypatch.setattr(mod, "_run_stage5", lambda db_path, args, use_mock: order.append("5") or _shortlist_df())
    monkeypatch.setattr(mod, "_run_stage6", lambda db_path, args, use_mock: order.append("6") or (_risk_df(), _risk_state()))

    args = mod.parse_args(["--db", str(db_path), "--skip-cache", "--dry-run", "--no-telegram"])
    result = mod.run_orchestrator(args)

    assert result["ok"] is True
    assert order == ["2", "3", "4", "5", "6"]
    stages = {row["stage"]: row["status"] for row in result["stages"]}
    assert stages["1"] == "SKIP"
    assert stages["4"] == "MOCK"
    assert stages["5"] == "OK"
    assert stages["6"] == "OK"


def test_orchestrator_aborts_on_stage2_failure(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    calls: list[str] = []

    monkeypatch.setattr(mod, "_send_telegram_summary", lambda message, no_telegram: "SKIP")

    def fail_stage2(db_path: Path, args) -> pd.DataFrame:
        calls.append("2")
        raise PrefilterError("prefilter failed")

    monkeypatch.setattr(mod, "_run_stage2", fail_stage2)
    monkeypatch.setattr(mod, "_run_stage3", lambda db_path, args: calls.append("3") or _factor_df())

    args = mod.parse_args(["--db", str(db_path), "--skip-cache", "--dry-run", "--no-telegram"])
    result = mod.run_orchestrator(args)

    assert result["ok"] is False
    assert "prefilter failed" in result["error"]
    assert calls == ["2"]


def test_orchestrator_degrades_on_stage5_failure(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"

    monkeypatch.setattr(mod, "_send_telegram_summary", lambda message, no_telegram: "SKIP")
    monkeypatch.setattr(mod, "_run_stage2", lambda db_path, args: _prefilter_df())
    monkeypatch.setattr(mod, "_run_stage3", lambda db_path, args: _factor_df())
    monkeypatch.setattr(mod, "_run_stage4_mock", lambda db_path, prefilter_df, dry_run: _prediction_df())
    monkeypatch.setattr(mod, "_run_stage5", lambda db_path, args, use_mock: (_ for _ in ()).throw(SelectionError("selection bad")))

    args = mod.parse_args(["--db", str(db_path), "--skip-cache", "--dry-run", "--no-telegram"])
    result = mod.run_orchestrator(args)

    assert result["ok"] is True
    stages = {row["stage"]: row for row in result["stages"]}
    assert stages["5"]["status"] == "FAIL"
    assert stages["6"]["status"] == "FAIL"
    assert "Selection unavailable" in stages["6"]["detail"]["error"]


def test_orchestrator_stage_specific_run(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    calls: list[str] = []

    monkeypatch.setattr(mod, "_send_telegram_summary", lambda message, no_telegram: "SKIP")
    monkeypatch.setattr(mod, "_run_stage3", lambda db_path, args: calls.append("3") or _factor_df())
    monkeypatch.setattr(mod, "_run_stage2", lambda db_path, args: calls.append("2") or _prefilter_df())

    args = mod.parse_args(["--db", str(db_path), "--stage", "3", "--dry-run", "--no-telegram"])
    result = mod.run_orchestrator(args)

    assert result["ok"] is True
    assert calls == ["3"]
    assert [row["stage"] for row in result["stages"]] == ["3"]


def test_orchestrator_writes_log_table(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"

    monkeypatch.setattr(mod, "_send_telegram_summary", lambda message, no_telegram: "SKIP")
    monkeypatch.setattr(mod, "_run_stage1", lambda args, db_path: {"ok": True, "summary": {}})
    monkeypatch.setattr(mod, "_run_stage2", lambda db_path, args: _prefilter_df())
    monkeypatch.setattr(mod, "_run_stage3", lambda db_path, args: _factor_df())
    monkeypatch.setattr(mod, "_run_stage4_mock", lambda db_path, prefilter_df, dry_run: _prediction_df())
    monkeypatch.setattr(mod, "_run_stage5", lambda db_path, args, use_mock: _shortlist_df())
    monkeypatch.setattr(mod, "_run_stage6", lambda db_path, args, use_mock: (_risk_df(), _risk_state()))

    args = mod.parse_args(["--db", str(db_path), "--no-telegram"])
    result = mod.run_orchestrator(args)

    assert result["ok"] is True
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute("SELECT stage, status FROM orchestrator_log ORDER BY stage ASC").fetchall()
        meta = dict(con.execute("SELECT key, value FROM cache_meta").fetchall())
    finally:
        con.close()
    assert len(rows) == 6
    assert meta["orchestrator_status"] == "OK"
    assert "orchestrator_run_at" in meta
