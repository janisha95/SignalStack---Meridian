from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from stages import v2_cache_warm as mod


def _use_tmp_meridian(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)


def _table_names(db_path: Path) -> list[str]:
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def _insert_daily_rows(db_path: Path, rows: list[tuple]) -> None:
    con = mod._connect_db(db_path)
    try:
        mod._write_daily_rows(con, rows)
        con.commit()
    finally:
        con.close()


def test_ensure_v2_db_creates_required_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    mod._ensure_v2_db(db_path)

    tables = _table_names(db_path)
    assert "daily_bars" in tables
    assert "options_daily" in tables
    assert "cache_meta" in tables


def test_guard_db_path_rejects_s1_and_s8_paths() -> None:
    with pytest.raises(mod.CacheWarmError):
        mod._guard_db_path(Path("/Users/sjani008/SS/Advance/data_cache/universe_ohlcv.db"))
    with pytest.raises(mod.CacheWarmError):
        mod._guard_db_path(Path("/Users/sjani008/SS/SignalStack8/data_cache/universe_ohlcv.db"))


def test_write_daily_rows_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    mod._ensure_v2_db(db_path)
    rows = [
        ("SPY", "2026-03-24", 500.0, 505.0, 498.0, 503.0, 1_000_000.0, mod.SOURCE_ALPACA),
        ("SPY", "2026-03-24", 500.0, 505.0, 498.0, 503.0, 1_000_000.0, mod.SOURCE_ALPACA),
    ]

    _insert_daily_rows(db_path, rows)
    _insert_daily_rows(db_path, rows)

    con = sqlite3.connect(str(db_path))
    try:
        count = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
    finally:
        con.close()
    assert count == 1


def test_load_yf_diff_tickers_subtracts_alpaca_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    diff_file = tmp_path / "yf_universe_diff.txt"
    diff_file.write_text("AAPL\nMSFT\nXYZ\nABC\n", encoding="utf-8")

    monkeypatch.setattr(mod, "DEFAULT_DIFF_FILE", diff_file)

    tickers = mod._load_yf_diff_tickers({"AAPL", "MSFT"})
    assert tickers == ["ABC", "XYZ"]


def test_load_sector_map_reads_meridian_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sector_json = tmp_path / "ticker_sector_map.json"
    sector_json.write_text('{"AAPL":"Technology","XOM":"Energy"}\n', encoding="utf-8")

    monkeypatch.setattr(mod, "SECTOR_MAP_PATH", sector_json)

    sector_map = mod._load_sector_map()
    assert sector_map == {"AAPL": "Technology", "XOM": "Energy"}


def test_run_pipeline_dry_run_does_not_require_alpaca_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    diff_file = tmp_path / "yf_universe_diff.txt"
    sector_json = tmp_path / "ticker_sector_map.json"
    diff_file.write_text("XYZ\nABC\n", encoding="utf-8")
    sector_json.write_text('{"AAPL":"Technology"}\n', encoding="utf-8")

    monkeypatch.setattr(mod, "DEFAULT_DIFF_FILE", diff_file)
    monkeypatch.setattr(mod, "SECTOR_MAP_PATH", sector_json)
    monkeypatch.delenv("ALPACA_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET", raising=False)
    monkeypatch.setattr(mod, "step_alpaca_warm", lambda *a, **k: {"ok": True, "alpaca_tickers": 0, "to_fetch": 0})
    monkeypatch.setattr(mod, "step_yf_warm", lambda *a, **k: {"ok": True, "diff_universe": 2, "to_fetch": 2})
    monkeypatch.setattr(mod, "step_options_pull", lambda *a, **k: {"ok": True, "candidate_tickers": 0})

    args = mod.parse_args(["--dry-run", "--db", str(db_path)])
    result = mod.run_pipeline(args)

    assert result["ok"] is True
    assert result["dry_run"] is True


def test_validation_gate_aborts_if_spy_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    mod._ensure_v2_db(db_path)

    with pytest.raises(mod.ValidationAbort, match="SPY missing"):
        mod.step_validation_gate(db_path)


def test_validation_gate_aborts_if_spy_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    mod._ensure_v2_db(db_path)
    _insert_daily_rows(
        db_path,
        [("SPY", "2026-03-21", 500.0, 501.0, 499.0, 500.5, 1_000_000.0, mod.SOURCE_ALPACA)],
    )
    monkeypatch.setattr(mod, "_get_last_trading_day", lambda ref=None: date(2026, 3, 24))

    with pytest.raises(mod.ValidationAbort, match="SPY stale"):
        mod.step_validation_gate(db_path)


def test_validation_gate_aborts_on_excess_price_jumps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    mod._ensure_v2_db(db_path)
    rows = [("SPY", "2026-03-23", 500.0, 501.0, 499.0, 500.0, 1_000_000.0, mod.SOURCE_ALPACA)]
    for i in range(101):
        ticker = f"T{i:03d}"
        rows.append((ticker, "2026-03-23", 10.0, 10.0, 10.0, 10.0, 1000.0, mod.SOURCE_ALPACA))
        rows.append((ticker, "2026-03-24", 20.0, 20.0, 20.0, 20.0, 1000.0, mod.SOURCE_ALPACA))
    _insert_daily_rows(db_path, rows)
    monkeypatch.setattr(mod, "_get_last_trading_day", lambda ref=None: date(2026, 3, 23))

    with pytest.raises(mod.ValidationAbort, match="Price jump failure"):
        mod.step_validation_gate(db_path)


def test_validation_gate_passes_when_spy_fresh_and_alignment_good(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    mod._ensure_v2_db(db_path)
    monkeypatch.setattr(mod, "_get_last_trading_day", lambda ref=None: date(2026, 3, 24))

    rows = []
    for ticker in ("SPY", "AAPL", "MSFT", "NVDA", "JPM", "XOM", "LLY", "META", "BAC", "GS"):
        rows.append((ticker, "2026-03-24", 100.0, 101.0, 99.0, 100.5, 1_000_000.0, mod.SOURCE_ALPACA))
        rows.append((ticker, "2026-03-23", 99.0, 100.0, 98.0, 99.5, 1_000_000.0, mod.SOURCE_ALPACA))
    rows.append(("XYZ", "2026-03-24", 10.0, 10.5, 9.5, 10.1, 500_000.0, mod.SOURCE_YF))
    _insert_daily_rows(db_path, rows)

    result = mod.step_validation_gate(db_path)
    assert result["ok"] is True
    assert result["spy_latest"] == "2026-03-24"
    assert result["alpaca_total"] == 10
    assert result["alpaca_on_spy_date"] == 10
    assert result["price_jump_tickers"] == 0
