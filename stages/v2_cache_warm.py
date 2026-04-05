#!/usr/bin/env python3
"""
Meridian Stage 1 — cache pipeline.

Builds Meridian's own v2 cache database from Alpaca, yfinance, and options data,
then runs a fail-closed validation gate.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import pandas as pd
except ImportError:  # pragma: no cover - runtime dependency for live downloads
    pd = None

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - runtime dependency for live downloads
    yf = None

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Vanguard"))

from stages.factors import now_et, now_et_iso, today_et, today_et_date

try:
    from vanguard.data_adapters.ibkr_adapter import IBKRAdapter
except Exception:  # pragma: no cover - optional integration path
    IBKRAdapter = None


log = logging.getLogger("meridian.stage1.cache")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "v2_universe.db"
IBKR_DAILY_DB_PATH = DATA_DIR / "ibkr_daily.db"
DEFAULT_REPORT_PATH = DATA_DIR / "cache_warm_report.json"
DEFAULT_DIFF_FILE = ROOT / "yf_universe_diff.txt"
SECTOR_MAP_PATH = ROOT / "config" / "ticker_sector_map.json"

ALPACA_BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
ALPACA_DATA_BASE = "https://data.alpaca.markets"
ALPACA_BATCH_SIZE = 500
YF_BATCH_SIZE = 50
OPTIONS_WORKERS = 8
OPTIONS_TOP_N = 200

SOURCE_ALPACA = "alpaca_bars_nightly"
SOURCE_IBKR = "ibkr"
SOURCE_YF = "yfinance_v2"
SOURCE_OPTIONS = "yahoo_options"
IBKR_DAILY_FETCH_LIMIT = int(os.environ.get("MERIDIAN_IBKR_DAILY_FETCH_LIMIT", "500"))
IBKR_PRIORITY_TICKERS = [
    "SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "TSLA", "GOOGL", "JPM", "V", "UNH", "JNJ", "PG", "HD", "MA", "BAC",
    "ABBV", "PFE", "KO", "PEP", "MRK", "COST", "WMT", "NFLX", "ORCL",
    "CRM", "AMD", "INTC", "BA", "CAT", "GS", "AXP", "NKE", "DIS",
]

class CacheWarmError(RuntimeError):
    """Fatal pipeline error."""


class ValidationAbort(CacheWarmError):
    """Validation gate failure."""


@dataclass
class StepResult:
    name: str
    ok: bool
    started_at: str
    finished_at: str
    elapsed_s: float
    metrics: dict[str, Any]


def _generated_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_now_iso() -> str:
    return now_et_iso()


def _resolve_db_path(db_arg: Optional[str] = None) -> Path:
    raw = db_arg or os.environ.get("V2_DB_PATH", str(DEFAULT_DB_PATH))
    return Path(raw).expanduser().resolve()


def _guard_db_path(db_path: Path) -> None:
    resolved = db_path.expanduser().resolve()
    if resolved.parent != DATA_DIR.resolve():
        raise CacheWarmError(
            f"Refusing to use non-Meridian DB path: {resolved}. "
            "Stage 1 may only write to ~/SS/Meridian/data/v2_universe.db."
        )


def _connect_db(db_path: Path) -> sqlite3.Connection:
    _guard_db_path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        con = sqlite3.connect(str(db_path), timeout=30)
    except sqlite3.OperationalError as exc:
        raise CacheWarmError(f"Cannot open DB at {db_path}: {exc}") from exc
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _ensure_v2_db(db_path: Path) -> None:
    con = _connect_db(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_bars (
                ticker  TEXT NOT NULL,
                date    TEXT NOT NULL,
                open    REAL,
                high    REAL,
                low     REAL,
                close   REAL,
                volume  REAL,
                source  TEXT,
                PRIMARY KEY (ticker, date)
            );

            CREATE INDEX IF NOT EXISTS idx_v2_ticker_date
                ON daily_bars(ticker, date);
            CREATE INDEX IF NOT EXISTS idx_v2_source
                ON daily_bars(source);
            CREATE INDEX IF NOT EXISTS idx_v2_date
                ON daily_bars(date);

            CREATE TABLE IF NOT EXISTS options_daily (
                ticker             TEXT NOT NULL,
                date               TEXT NOT NULL,
                pcr                REAL,
                unusual_vol_ratio  REAL,
                net_delta          REAL,
                source             TEXT,
                PRIMARY KEY (ticker, date)
            );

            CREATE INDEX IF NOT EXISTS idx_options_date
                ON options_daily(date);

            CREATE TABLE IF NOT EXISTS cache_meta (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT
            );
            """
        )
        con.commit()
    finally:
        con.close()


def _set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO cache_meta (key, value, updated_at)
        VALUES (?, ?, ?)
        """,
        (key, value, _run_now_iso()),
    )


def _write_daily_rows(con: sqlite3.Connection, rows: Iterable[tuple[Any, ...]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO daily_bars
            (ticker, date, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def _write_options_rows(con: sqlite3.Connection, rows: Iterable[tuple[Any, ...]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO options_daily
            (ticker, date, pcr, unusual_vol_ratio, net_delta, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def _get_last_trading_day(ref: Optional[datetime | date] = None) -> date:
    current = ref or now_et()
    if isinstance(current, date) and not isinstance(current, datetime):
        current_dt = datetime.combine(current, dt_time(23, 59, 59))
    else:
        current_dt = current
    ref_date = current_dt.date()
    before_close = current_dt.time() < dt_time(16, 0)
    if ref_date.weekday() >= 5:
        candidate = ref_date
    elif before_close:
        candidate = ref_date - timedelta(days=1)
    else:
        candidate = ref_date
    try:  # pragma: no cover - optional dependency path
        import exchange_calendars as ec
        import pandas as pd  # type: ignore

        nyse = ec.get_calendar("XNYS")
        session = pd.Timestamp(candidate)
        if nyse.is_session(session):
            return session.date()
        return nyse.previous_session(session).date()
    except Exception:
        pass
    if candidate.weekday() == 5:
        return candidate - timedelta(days=1)
    if candidate.weekday() == 6:
        return candidate - timedelta(days=2)
    return candidate


def _retry_json_request(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout: int = 30,
    retries: int = 3,
) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as exc:  # pragma: no cover - live network path
            last_exc = exc
            if attempt == retries:
                raise
            time.sleep(min(2 * attempt, 5))
    if last_exc:
        raise last_exc
    raise RuntimeError("unreachable")


def _load_sector_map() -> dict[str, str]:
    if SECTOR_MAP_PATH.exists():
        with open(SECTOR_MAP_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k).upper(): str(v) for k, v in data.items()}
    log.warning("ticker sector map not found in Meridian config path")
    return {}


def _load_alpaca_tickers(api_key: str, api_secret: str) -> list[str]:
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
        "Accept": "application/json",
    }
    url = f"{ALPACA_BASE}/v2/assets?status=active&asset_class=us_equity"
    assets = _retry_json_request(url, headers=headers, timeout=20, retries=3)
    if not isinstance(assets, list):
        raise CacheWarmError("Unexpected Alpaca assets response format")

    tickers = {
        str(asset.get("symbol", "")).upper()
        for asset in assets
        if asset.get("tradable")
        and "." not in str(asset.get("symbol", ""))
        and "/" not in str(asset.get("symbol", ""))
        and len(str(asset.get("symbol", ""))) <= 5
        and not str(asset.get("symbol", "")).endswith("W")
    }
    if len(tickers) < 5000:
        raise CacheWarmError(f"Alpaca ticker universe too small: {len(tickers)}")
    return sorted(tickers)


def _alpaca_bars_batch(
    tickers: list[str],
    start_date: str,
    end_date: str,
    api_key: str,
    api_secret: str,
) -> dict[str, list[dict[str, Any]]]:
    if not tickers:
        return {}
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
        "Accept": "application/json",
    }
    results: dict[str, list[dict[str, Any]]] = {t: [] for t in tickers}
    symbols = ",".join(tickers[:ALPACA_BATCH_SIZE])
    params = urllib.parse.urlencode(
        {
            "symbols": symbols,
            "timeframe": "1Day",
            "start": start_date,
            "end": end_date,
            "limit": 10000,
            "feed": "iex",
            "adjustment": "split",
            "sort": "asc",
        }
    )
    url = f"{ALPACA_DATA_BASE}/v2/stocks/bars?{params}"
    pages = 0
    while url and pages < 100:  # pragma: no cover - live pagination path
        data = _retry_json_request(url, headers=headers, timeout=30, retries=3)
        bars_map = data.get("bars") or {}
        for ticker, bar_list in bars_map.items():
            upper = str(ticker).upper()
            target = results.setdefault(upper, [])
            for bar in bar_list:
                target.append(
                    {
                        "date": str(bar.get("t", ""))[:10],
                        "open": bar.get("o"),
                        "high": bar.get("h"),
                        "low": bar.get("l"),
                        "close": bar.get("c"),
                        "volume": bar.get("v"),
                    }
                )
        token = data.get("next_page_token")
        if token:
            url = f"{ALPACA_DATA_BASE}/v2/stocks/bars?{params}&page_token={urllib.parse.quote(str(token))}"
        else:
            url = ""
        pages += 1
    return {ticker: bars for ticker, bars in results.items() if bars}


def _get_stale_tickers(
    db_path: Path,
    tickers: list[str],
    *,
    source: str,
    days: int,
) -> list[str]:
    if not db_path.exists() or not tickers:
        return list(tickers)
    # A ticker is stale if it's missing the most recent completed trading day's
    # bar. Using _get_last_trading_day() (not today_et_date()) is critical:
    # after midnight but before market close, "today" has no bars yet, so
    # we'd try to fetch data that doesn't exist. _get_last_trading_day()
    # returns yesterday before 4pm ET and today after 4pm ET.
    today_str = _get_last_trading_day().isoformat()
    con = _connect_db(db_path)
    try:
        placeholders = ",".join("?" * len(tickers))
        query = f"""
            SELECT ticker, MAX(date) AS newest
            FROM daily_bars
            WHERE source = ?
              AND ticker IN ({placeholders})
            GROUP BY ticker
        """
        try:
            rows = con.execute(query, [source, *tickers]).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return list(tickers)
            raise
        newest = {str(row["ticker"]).upper(): str(row["newest"]) for row in rows if row["newest"]}
    finally:
        con.close()
    return [ticker for ticker in tickers if newest.get(ticker, "") < today_str]


def _resolve_yf_diff_file() -> Path:
    if DEFAULT_DIFF_FILE.exists():
        return DEFAULT_DIFF_FILE
    raise CacheWarmError("yf_universe_diff.txt not found in Meridian repo root")


def _load_yf_diff_tickers(alpaca_tickers: set[str]) -> list[str]:
    path = _resolve_yf_diff_file()
    raw = {
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    diff = sorted(raw - alpaca_tickers)
    if not diff:
        log.warning("YF diff universe resolved to 0 tickers after subtracting Alpaca set")
    return diff


def _parse_yf_df(df: Any, ticker: str, source: str = SOURCE_YF) -> list[tuple[Any, ...]]:
    if pd is None:
        raise CacheWarmError("pandas is required for yfinance parsing")
    if df is None or getattr(df, "empty", True):
        return []
    frame = df.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    needed = {"open", "high", "low", "close", "volume"}
    if not needed.issubset(set(frame.columns)):
        return []
    rows: list[tuple[Any, ...]] = []
    for idx, row in frame.iterrows():
        try:
            d = pd.Timestamp(idx).date().isoformat()
            rows.append(
                (
                    ticker.upper(),
                    d,
                    float(row["open"]) if row.get("open") is not None else None,
                    float(row["high"]) if row.get("high") is not None else None,
                    float(row["low"]) if row.get("low") is not None else None,
                    float(row["close"]) if row.get("close") is not None else None,
                    float(row["volume"]) if row.get("volume") is not None else None,
                    source,
                )
            )
        except Exception as exc:
            raise CacheWarmError(f"Failed parsing yfinance row for {ticker}: {exc}") from exc
    return rows


def _download_yf_batch(tickers: list[str], start_date: str, end_date: str) -> dict[str, list[tuple[Any, ...]]]:
    if yf is None:
        raise CacheWarmError("yfinance is not installed")
    if pd is None:
        raise CacheWarmError("pandas is not installed")
    if not tickers:
        return {}
    try:
        raw = yf.download(
            tickers=tickers,
            start=start_date,
            end=end_date,
            interval="1d",
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception as exc:  # pragma: no cover - live network path
        raise CacheWarmError(f"yfinance batch download failed: {exc}") from exc
    if raw is None or len(raw) == 0:
        return {}

    results: dict[str, list[tuple[Any, ...]]] = {}
    multi = isinstance(getattr(raw, "columns", None), pd.MultiIndex)
    for ticker in tickers:
        if multi:
            if ticker not in raw.columns.get_level_values(0):
                continue
            frame = raw[ticker]
        else:
            frame = raw
        rows = _parse_yf_df(frame, ticker, SOURCE_YF)
        if rows:
            results[ticker] = rows
    return results


def _top_tickers_by_dollar_volume(db_path: Path, limit: int = OPTIONS_TOP_N) -> list[str]:
    con = _connect_db(db_path)
    try:
        latest = con.execute("SELECT MAX(date) AS d FROM daily_bars").fetchone()["d"]
        if not latest:
            return []
        rows = con.execute(
            """
            SELECT ticker
            FROM daily_bars
            WHERE date = ?
            ORDER BY (COALESCE(close, 0) * COALESCE(volume, 0)) DESC
            LIMIT ?
            """,
            (latest, limit),
        ).fetchall()
        return [str(row["ticker"]).upper() for row in rows]
    finally:
        con.close()


def _pull_option_metrics(ticker: str, as_of: str) -> Optional[tuple[Any, ...]]:
    if yf is None:
        raise CacheWarmError("yfinance is not installed")
    inst = yf.Ticker(ticker)
    expiries = list(inst.options or [])
    if not expiries:
        return None
    chain = inst.option_chain(expiries[0])
    calls = chain.calls
    puts = chain.puts

    call_oi = float(calls["openInterest"].fillna(0).sum()) if "openInterest" in calls else 0.0
    put_oi = float(puts["openInterest"].fillna(0).sum()) if "openInterest" in puts else 0.0
    call_vol = float(calls["volume"].fillna(0).sum()) if "volume" in calls else 0.0
    put_vol = float(puts["volume"].fillna(0).sum()) if "volume" in puts else 0.0

    if call_vol > 0:
        pcr = put_vol / call_vol
    elif call_oi > 0:
        pcr = put_oi / call_oi
    else:
        pcr = None

    total_vol = call_vol + put_vol
    total_oi = call_oi + put_oi
    unusual = (total_vol / total_oi) if total_oi > 0 else None
    net_delta = ((call_oi - put_oi) / total_oi) if total_oi > 0 else None

    return (
        ticker.upper(),
        as_of,
        float(pcr) if pcr is not None else None,
        float(unusual) if unusual is not None else None,
        float(net_delta) if net_delta is not None else None,
        SOURCE_OPTIONS,
    )


def _count_price_jump_tickers(con: sqlite3.Connection, since_date: str) -> int:
    row = con.execute(
        """
        SELECT COUNT(DISTINCT ticker) AS tickers
        FROM (
            SELECT
                ticker,
                date,
                close,
                LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS prev_close
            FROM daily_bars
            WHERE date >= ?
        )
        WHERE prev_close IS NOT NULL
          AND prev_close > 0
          AND ABS(close / prev_close - 1.0) > 0.5
        """,
        (since_date,),
    ).fetchone()
    return int(row["tickers"] or 0)


def _top_price_jump_tickers(
    con: sqlite3.Connection,
    since_date: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT ticker, date, close, prev_close, jump_pct
        FROM (
            SELECT
                ticker,
                date,
                close,
                LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS prev_close,
                ABS(close / LAG(close) OVER (PARTITION BY ticker ORDER BY date) - 1.0) AS jump_pct
            FROM daily_bars
            WHERE date >= ?
        )
        WHERE prev_close IS NOT NULL
          AND prev_close > 0
          AND jump_pct > 0.5
        ORDER BY jump_pct DESC, ticker ASC, date ASC
        LIMIT ?
        """,
        (since_date, limit),
    ).fetchall()
    return [
        {
            "ticker": str(row["ticker"]),
            "date": str(row["date"]),
            "close": float(row["close"]) if row["close"] is not None else None,
            "prev_close": float(row["prev_close"]) if row["prev_close"] is not None else None,
            "jump_pct": round(float(row["jump_pct"]), 4) if row["jump_pct"] is not None else None,
        }
        for row in rows
    ]


def step_validation_gate(db_path: Path) -> dict[str, Any]:
    con = _connect_db(db_path)
    try:
        spy_latest = con.execute(
            "SELECT MAX(date) AS d FROM daily_bars WHERE ticker='SPY'"
        ).fetchone()["d"]
        if not spy_latest:
            raise ValidationAbort("SPY missing from daily_bars")

        expected = _get_last_trading_day()
        if spy_latest < expected.isoformat():
            raise ValidationAbort(
                f"SPY stale: latest={spy_latest}, expected_at_least={expected.isoformat()}"
            )

        total_tickers = int(
            con.execute("SELECT COUNT(DISTINCT ticker) AS n FROM daily_bars").fetchone()["n"] or 0
        )
        alpaca_total = int(
            con.execute(
                "SELECT COUNT(DISTINCT ticker) AS n FROM daily_bars WHERE source=?",
                (SOURCE_ALPACA,),
            ).fetchone()["n"]
            or 0
        )
        alpaca_on_spy_date = int(
            con.execute(
                """
                SELECT COUNT(DISTINCT ticker) AS n
                FROM daily_bars
                WHERE source = ? AND date = ?
                """,
                (SOURCE_ALPACA, spy_latest),
            ).fetchone()["n"]
            or 0
        )
        alpaca_alignment = (
            alpaca_on_spy_date / alpaca_total if alpaca_total else 0.0
        )
        alignment_warning = None
        if alpaca_total and alpaca_alignment < 0.70:
            raise ValidationAbort(
                f"Alignment failure: only {alpaca_on_spy_date}/{alpaca_total} "
                f"alpaca tickers on SPY date {spy_latest}"
            )
        if alpaca_total and alpaca_alignment < 0.90:
            alignment_warning = (
                f"Alignment warning: only {alpaca_on_spy_date}/{alpaca_total} "
                f"alpaca tickers on SPY date {spy_latest}"
            )
            log.warning(alignment_warning)

        jump_scan_start = (expected - timedelta(days=30)).isoformat()
        jump_tickers = _count_price_jump_tickers(con, jump_scan_start)
        top_jump_tickers = _top_price_jump_tickers(con, jump_scan_start, limit=10)
        if jump_tickers > 2000:
            raise ValidationAbort(
                f"Price jump failure: {jump_tickers} tickers moved >50% day/day in last 30d"
            )
        if jump_tickers > 0:
            log.warning(
                "Price jump warning: %d tickers moved >50%% day/day in last 30d; top examples=%s",
                jump_tickers,
                json.dumps(top_jump_tickers),
            )

        yfinance_total = int(
            con.execute(
                "SELECT COUNT(DISTINCT ticker) AS n FROM daily_bars WHERE source=?",
                (SOURCE_YF,),
            ).fetchone()["n"]
            or 0
        )
        yfinance_on_spy_date = int(
            con.execute(
                """
                SELECT COUNT(DISTINCT ticker) AS n
                FROM daily_bars
                WHERE source = ? AND date = ?
                """,
                (SOURCE_YF, spy_latest),
            ).fetchone()["n"]
            or 0
        )

        return {
            "ok": True,
            "spy_latest": spy_latest,
            "expected_trading_day": expected.isoformat(),
            "total_tickers": total_tickers,
            "alpaca_total": alpaca_total,
            "alpaca_on_spy_date": alpaca_on_spy_date,
            "alpaca_alignment_pct": round(alpaca_alignment, 4),
            "alignment_warning": alignment_warning,
            "yfinance_total": yfinance_total,
            "yfinance_on_spy_date": yfinance_on_spy_date,
            "price_jump_tickers": jump_tickers,
            "top_price_jump_tickers": top_jump_tickers,
        }
    finally:
        con.close()


def _run_step(name: str, fn, *args, **kwargs) -> StepResult:
    started_at = _run_now_iso()
    t0 = time.time()
    metrics = fn(*args, **kwargs)
    elapsed = round(time.time() - t0, 1)
    return StepResult(
        name=name,
        ok=bool(metrics.get("ok", True)),
        started_at=started_at,
        finished_at=_run_now_iso(),
        elapsed_s=elapsed,
        metrics=metrics,
    )


def _alpaca_bars_batch_with_retry(
    batch: list[str],
    start_date: str,
    end_date: str,
    api_key: str,
    api_secret: str,
    *,
    max_retries: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Retry _alpaca_bars_batch if fewer than 50% of tickers return bars."""
    last_result: dict[str, list[dict[str, Any]]] = {}
    for attempt in range(1, max_retries + 1):
        try:
            result = _alpaca_bars_batch(batch, start_date, end_date, api_key, api_secret)
            filled = sum(1 for bars in result.values() if bars)
            if filled >= len(batch) * 0.5:
                return result
            _progress(
                f"Batch retry {attempt}/{max_retries}: only {filled}/{len(batch)} tickers returned bars"
            )
            last_result = result
        except Exception as exc:
            _progress(f"Batch attempt {attempt}/{max_retries} failed: {exc}")
            last_result = {}
        if attempt < max_retries:
            time.sleep(5 * attempt)
    return last_result


def step_alpaca_warm(
    db_path: Path,
    *,
    api_key: str,
    api_secret: str,
    days: int,
    full_refresh: bool,
    dry_run: bool,
) -> dict[str, Any]:
    start_date = (
        (today_et_date() - timedelta(days=730)).isoformat()
        if full_refresh
        else (today_et_date() - timedelta(days=days + 30)).isoformat()
    )
    end_date = today_et()
    if dry_run and (not api_key or not api_secret):
        return {
            "ok": True,
            "alpaca_tickers": 0,
            "to_fetch": 0,
            "batches": 0,
            "start_date": start_date,
            "end_date": end_date,
            "note": "dry-run without Alpaca credentials; universe size not resolved",
        }

    _progress("Step 1: Loading Alpaca tickers...")
    tickers = _load_alpaca_tickers(api_key, api_secret)
    _progress(f"Step 1: {len(tickers)} tickers loaded")
    _progress(f"Step 1: Date range {start_date} -> {end_date}")
    if full_refresh:
        to_fetch = list(tickers)
    else:
        to_fetch = _get_stale_tickers(
            db_path,
            tickers,
            source=SOURCE_ALPACA,
            days=days,
        )

    if dry_run:
        return {
            "ok": True,
            "alpaca_tickers": len(tickers),
            "to_fetch": len(to_fetch),
            "batches": (len(to_fetch) + ALPACA_BATCH_SIZE - 1) // ALPACA_BATCH_SIZE,
            "start_date": start_date,
            "end_date": end_date,
        }

    _ensure_v2_db(db_path)
    written_rows = 0
    downloaded_tickers = 0
    failed_batches = 0
    total_batches = (len(to_fetch) + ALPACA_BATCH_SIZE - 1) // ALPACA_BATCH_SIZE if to_fetch else 0
    for i in range(0, len(to_fetch), ALPACA_BATCH_SIZE):
        batch_num = (i // ALPACA_BATCH_SIZE) + 1
        if batch_num == 1 or batch_num % 5 == 0 or batch_num == total_batches:
            _progress(f"Step 1: Downloading bars batch {batch_num}/{total_batches}...")
        batch = to_fetch[i : i + ALPACA_BATCH_SIZE]
        try:
            bars_map = _alpaca_bars_batch_with_retry(batch, start_date, end_date, api_key, api_secret)
        except Exception as exc:
            failed_batches += 1
            log.error("Alpaca batch failed: %s", exc)
            continue
        rows = []
        for ticker, bars in bars_map.items():
            if bars:
                downloaded_tickers += 1
            rows.extend(
                (
                    ticker.upper(),
                    bar["date"],
                    bar.get("open"),
                    bar.get("high"),
                    bar.get("low"),
                    bar.get("close"),
                    bar.get("volume"),
                    SOURCE_ALPACA,
                )
                for bar in bars
                if bar.get("date")
            )
        con = _connect_db(db_path)
        try:
            written_rows += _write_daily_rows(con, rows)
            con.commit()
        finally:
            con.close()

    con = _connect_db(db_path)
    try:
        _set_meta(con, "last_alpaca_warm", _run_now_iso())
        con.commit()
    finally:
        con.close()

    _progress(f"Step 1: Alpaca complete: {written_rows} rows written")

    return {
        "ok": True,
        "alpaca_tickers": len(tickers),
        "to_fetch": len(to_fetch),
        "downloaded_tickers": downloaded_tickers,
        "failed_batches": failed_batches,
        "rows_written": written_rows,
        "start_date": start_date,
        "end_date": end_date,
    }


def step_yf_warm(
    db_path: Path,
    *,
    alpaca_tickers: set[str],
    days: int,
    full_refresh: bool,
    dry_run: bool,
) -> dict[str, Any]:
    diff_tickers = _load_yf_diff_tickers(alpaca_tickers)
    start_date = (
        (today_et_date() - timedelta(days=730)).isoformat()
        if full_refresh
        else (today_et_date() - timedelta(days=days + 30)).isoformat()
    )
    end_date = today_et()
    if full_refresh:
        to_fetch = list(diff_tickers)
    else:
        to_fetch = _get_stale_tickers(
            db_path,
            diff_tickers,
            source=SOURCE_YF,
            days=days,
        )
    _progress(f"Step 2: Date range {start_date} -> {end_date}")

    if dry_run:
        return {
            "ok": True,
            "diff_universe": len(diff_tickers),
            "to_fetch": len(to_fetch),
            "batches": (len(to_fetch) + YF_BATCH_SIZE - 1) // YF_BATCH_SIZE,
            "start_date": start_date,
            "end_date": end_date,
        }

    _ensure_v2_db(db_path)
    fetched = 0
    failed = 0
    written_rows = 0
    _progress(f"Step 2: YFinance diff: {len(to_fetch)} tickers to fetch...")
    total_batches = (len(to_fetch) + YF_BATCH_SIZE - 1) // YF_BATCH_SIZE if to_fetch else 0
    for i in range(0, len(to_fetch), YF_BATCH_SIZE):
        batch_num = (i // YF_BATCH_SIZE) + 1
        if batch_num == 1 or batch_num % 10 == 0 or batch_num == total_batches:
            _progress(f"Step 2: Batch {batch_num}/{total_batches}...")
        batch = to_fetch[i : i + YF_BATCH_SIZE]
        try:
            bars_map = _download_yf_batch(batch, start_date, end_date)
        except Exception as exc:
            log.error("YF batch failed: %s", exc)
            failed += len(batch)
            continue
        rows = []
        for ticker in batch:
            ticker_rows = bars_map.get(ticker, [])
            if ticker_rows:
                fetched += 1
                rows.extend(ticker_rows)
            else:
                failed += 1
        con = _connect_db(db_path)
        try:
            written_rows += _write_daily_rows(con, rows)
            con.commit()
        finally:
            con.close()

    con = _connect_db(db_path)
    try:
        _set_meta(con, "last_yf_warm", _run_now_iso())
        con.commit()
    finally:
        con.close()

    _progress(f"Step 2: YFinance complete: {written_rows} rows written")

    return {
        "ok": True,
        "diff_universe": len(diff_tickers),
        "to_fetch": len(to_fetch),
        "fetched": fetched,
        "failed": failed,
        "rows_written": written_rows,
        "start_date": start_date,
        "end_date": end_date,
    }


def step_options_pull(
    db_path: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    as_of = _get_last_trading_day().isoformat()
    if dry_run:
        if not db_path.exists():
            return {
                "ok": True,
                "candidate_tickers": 0,
                "as_of": as_of,
                "note": "dry-run without existing cache; top dollar-volume universe not resolved",
            }
        try:
            top_tickers = _top_tickers_by_dollar_volume(db_path, OPTIONS_TOP_N)
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            return {
                "ok": True,
                "candidate_tickers": 0,
                "as_of": as_of,
                "note": "dry-run without initialized cache tables; top dollar-volume universe not resolved",
            }
        return {
            "ok": True,
            "candidate_tickers": len(top_tickers),
            "as_of": as_of,
        }

    top_tickers = _top_tickers_by_dollar_volume(db_path, OPTIONS_TOP_N)
    _progress(f"Step 3: Options pull: {len(top_tickers)} tickers...")
    written = 0
    failed = 0
    rows: list[tuple[Any, ...]] = []
    for i, ticker in enumerate(top_tickers):  # pragma: no cover - live network path
        errored = False
        try:
            row = _pull_option_metrics(ticker, as_of)
        except Exception as exc:
            failed += 1
            log.warning("Options pull failed for %s: %s", ticker, exc)
            row = None
            errored = True
        if row is None and not errored:
            failed += 1
        else:
            if row is not None:
                rows.append(row)
        if (i + 1) % 50 == 0 or (i + 1) == len(top_tickers):
            _progress(f"Step 3: {i + 1}/{len(top_tickers)} pulled...")
        # Yahoo free tier rate limiting: ~2 requests/sec.
        if i % 2 == 0:
            time.sleep(1.0)

    con = _connect_db(db_path)
    try:
        written = _write_options_rows(con, rows)
        _set_meta(con, "last_options_pull", _run_now_iso())
        con.commit()
    finally:
        con.close()

    return {
        "ok": True,
        "candidate_tickers": len(top_tickers),
        "written": written,
        "failed": failed,
        "as_of": as_of,
    }


def _load_local_tickers(db_path: Path) -> list[str]:
    priority = IBKR_PRIORITY_TICKERS
    bad_dot_suffixes = (".WS", ".WT", ".U", ".R")
    if not db_path.exists():
        return []
    con = _connect_db(db_path)
    try:
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_bars'"
        ).fetchone() is None:
            return []
        rows = con.execute(
            "SELECT DISTINCT ticker FROM daily_bars ORDER BY ticker"
        ).fetchall()
        all_tickers = [str(row[0]).upper() for row in rows if row and row[0]]
        clean_tickers: list[str] = []
        for ticker in all_tickers:
            if ticker.endswith(bad_dot_suffixes):
                continue
            # Skip common warrant-style suffixes like ABCDW, while preserving
            # normal 3-4 char tickers such as GLW.
            if ticker.endswith("W") and len(ticker) >= 5 and ticker not in priority:
                continue
            clean_tickers.append(ticker)

        priority_set = set(priority)
        priority_first = [ticker for ticker in priority if ticker in clean_tickers]
        rest = [ticker for ticker in clean_tickers if ticker not in priority_set]
        return priority_first + rest
    finally:
        con.close()


def _sync_shared_ibkr_daily_to_local(db_path: Path, min_date: str, max_date: str) -> int:
    if not IBKR_DAILY_DB_PATH.exists():
        return 0
    src = sqlite3.connect(str(IBKR_DAILY_DB_PATH), timeout=30)
    src.row_factory = sqlite3.Row
    dst = _connect_db(db_path)
    try:
        src.execute("DELETE FROM ibkr_daily_bars WHERE date > ?", (max_date,))
        src.commit()
        dst.execute("DELETE FROM daily_bars WHERE date > ?", (max_date,))
        rows = src.execute(
            """
            SELECT symbol, date, open, high, low, close, volume, data_source
            FROM ibkr_daily_bars
            WHERE date >= ? AND date <= ?
            ORDER BY symbol, date
            """,
            (min_date, max_date),
        ).fetchall()
        mapped = [
            (
                row["symbol"],
                row["date"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["volume"],
                row["data_source"] or SOURCE_IBKR,
            )
            for row in rows
        ]
        written = _write_daily_rows(dst, mapped)
        if written:
            _set_meta(dst, "last_ibkr_sync", _run_now_iso())
        dst.commit()
        return written
    finally:
        src.close()
        dst.close()


def _count_stale_local_tickers(db_path: Path, fresh_cutoff: str) -> int:
    """Count local tickers still missing a bar on or after ``fresh_cutoff``."""
    if not db_path.exists():
        return 0
    con = _connect_db(db_path)
    try:
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_bars'"
        ).fetchone() is None:
            return 0
        row = con.execute(
            """
            SELECT COUNT(DISTINCT ticker)
            FROM daily_bars
            WHERE ticker NOT IN (
                SELECT DISTINCT ticker
                FROM daily_bars
                WHERE date >= ?
            )
            """,
            (fresh_cutoff,),
        ).fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        con.close()


def step_ibkr_daily_sync(
    db_path: Path,
    *,
    days: int,
    full_refresh: bool,
    dry_run: bool,
) -> dict[str, Any]:
    """
    IBKR fetches only the first priority slice of the universe.
    Alpaca/YF remain the broad-universe daily source in the shared DB.
    """
    lookback_days = 730 if full_refresh else max(int(days), 1) + 10
    max_date = _get_last_trading_day().isoformat()
    min_date = (_get_last_trading_day() - timedelta(days=lookback_days)).isoformat()
    local_tickers = _load_local_tickers(db_path)
    fetch_limit = max(1, min(IBKR_DAILY_FETCH_LIMIT, 500))
    priority_set = set(IBKR_PRIORITY_TICKERS)
    rest = [ticker for ticker in local_tickers if ticker not in priority_set]
    fetch_symbols = [
        *[ticker for ticker in IBKR_PRIORITY_TICKERS if ticker in local_tickers],
        *rest[: max(fetch_limit - len(IBKR_PRIORITY_TICKERS), 0)],
    ][:fetch_limit]
    if dry_run:
        shared_rows = 0
        if IBKR_DAILY_DB_PATH.exists():
            con = sqlite3.connect(str(IBKR_DAILY_DB_PATH), timeout=30)
            try:
                shared_rows = int(
                    con.execute(
                        "SELECT COUNT(*) FROM ibkr_daily_bars WHERE date >= ?",
                        (min_date,),
                    ).fetchone()[0] or 0
                )
            finally:
                con.close()
        return {
            "ok": True,
            "dry_run": True,
            "local_tickers": len(local_tickers),
            "shared_rows": shared_rows,
            "fetch_limit": fetch_limit,
            "fetch_symbols": len(fetch_symbols),
            "min_date": min_date,
            "max_date": max_date,
        }

    fetched_rows = 0
    if IBKRAdapter is not None and fetch_symbols:
        adapter = IBKRAdapter(client_id=11)
        try:
            if adapter.connect():
                bars = adapter.get_daily_bars(fetch_symbols, days=days)
                bars = {
                    symbol: [
                        bar for bar in bar_list
                        if str(bar.get("date", "")) <= max_date
                    ]
                    for symbol, bar_list in (bars or {}).items()
                }
                fetched_rows = adapter.write_daily_bars(bars, IBKR_DAILY_DB_PATH)
                log.info(
                    "IBKR priority fetch: %d rows for %d/%d symbols",
                    fetched_rows,
                    len(fetch_symbols),
                    len(local_tickers),
                )
        except Exception as exc:
            log.warning("IBKR daily fetch failed (non-fatal): %s", exc)
        finally:
            try:
                adapter.disconnect()
            except Exception:
                pass
    synced_rows = _sync_shared_ibkr_daily_to_local(
        db_path,
        min_date=min_date,
        max_date=max_date,
    )
    return {
        "ok": True,
        "local_tickers": len(local_tickers),
        "fetch_symbols": len(fetch_symbols),
        "fetch_limit": fetch_limit,
        "fetched_rows": fetched_rows,
        "synced_rows": synced_rows,
        "shared_db": str(IBKR_DAILY_DB_PATH),
        "min_date": min_date,
        "max_date": max_date,
    }


def _build_report(
    *,
    db_path: Path,
    dry_run: bool,
    steps: list[StepResult],
    sector_map_size: int,
) -> dict[str, Any]:
    totals = {step.name: step.metrics for step in steps}
    ok = all(step.ok for step in steps)
    return {
        "ok": ok,
        "dry_run": dry_run,
        "generated_at": _generated_at_utc(),
        "db_path": str(db_path),
        "sector_map_size": sector_map_size,
        "steps": [
            {
                "name": step.name,
                "ok": step.ok,
                "started_at": step.started_at,
                "finished_at": step.finished_at,
                "elapsed_s": step.elapsed_s,
                "metrics": step.metrics,
            }
            for step in steps
        ],
        "summary": totals,
    }


def _write_report(report: dict[str, Any], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _progress(message: str) -> None:
    print(message, flush=True)


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    db_path = _resolve_db_path(args.db)
    _guard_db_path(db_path)

    sector_map = _load_sector_map()
    api_key = os.environ.get("ALPACA_KEY", "")
    api_secret = os.environ.get("ALPACA_SECRET", "")

    steps: list[StepResult] = []
    alpaca_tickers: set[str] = set()
    ibkr_shared_rows = 0

    if not args.dry_run:
        _ensure_v2_db(db_path)

    if not args.skip_ibkr:
        ibkr_step = _run_step(
            "ibkr_daily_sync",
            step_ibkr_daily_sync,
            db_path,
            days=args.days,
            full_refresh=args.full_refresh,
            dry_run=args.dry_run,
        )
        steps.append(ibkr_step)
        ibkr_shared_rows = int(
            ibkr_step.metrics.get("synced_rows")
            or ibkr_step.metrics.get("shared_rows")
            or 0
        )
    else:
        steps.append(
            StepResult(
                name="ibkr_daily_sync",
                ok=True,
                started_at=_run_now_iso(),
                finished_at=_run_now_iso(),
                elapsed_s=0.0,
                metrics={"ok": True, "skipped": True},
            )
        )

    stale_cutoff = _get_last_trading_day().isoformat()
    stale_tickers_after_ibkr = 0 if args.dry_run else _count_stale_local_tickers(db_path, stale_cutoff)
    # Always run Alpaca/YF broad-universe updates; IBKR is a priority overwrite.
    use_legacy_daily_sources = True
    if stale_tickers_after_ibkr > 0:
        _progress(
            f"Fallback daily sources enabled: {stale_tickers_after_ibkr} tickers still stale after IBKR sync"
        )
    if (
        use_legacy_daily_sources
        and not args.dry_run
        and not args.skip_alpaca
        and (not api_key or not api_secret)
    ):
        raise CacheWarmError("ALPACA_KEY and ALPACA_SECRET are required")

    if not args.skip_alpaca and use_legacy_daily_sources:
        alpaca_step = _run_step(
            "alpaca_warm",
            step_alpaca_warm,
            db_path,
            api_key=api_key,
            api_secret=api_secret,
            days=args.days,
            full_refresh=args.full_refresh,
            dry_run=args.dry_run,
        )
        steps.append(alpaca_step)
        if not args.dry_run:
            alpaca_tickers = set(_load_alpaca_tickers(api_key, api_secret))
        else:
            alpaca_tickers = set()
    else:
        steps.append(
            StepResult(
                name="alpaca_warm",
                ok=True,
                started_at=_run_now_iso(),
                finished_at=_run_now_iso(),
                elapsed_s=0.0,
                metrics={"ok": True, "skipped": True},
            )
        )

    if not args.skip_yf and use_legacy_daily_sources:
        yf_step = _run_step(
            "yf_warm",
            step_yf_warm,
            db_path,
            alpaca_tickers=alpaca_tickers,
            days=args.days,
            full_refresh=args.full_refresh,
            dry_run=args.dry_run,
        )
        steps.append(yf_step)
    else:
        steps.append(
            StepResult(
                name="yf_warm",
                ok=True,
                started_at=_run_now_iso(),
                finished_at=_run_now_iso(),
                elapsed_s=0.0,
                metrics={"ok": True, "skipped": True},
            )
        )

    if not args.skip_options:
        options_step = _run_step(
            "options_pull",
            step_options_pull,
            db_path,
            dry_run=args.dry_run,
        )
        steps.append(options_step)
    else:
        steps.append(
            StepResult(
                name="options_pull",
                ok=True,
                started_at=_run_now_iso(),
                finished_at=_run_now_iso(),
                elapsed_s=0.0,
                metrics={"ok": True, "skipped": True},
            )
        )

    if args.dry_run:
        return _build_report(
            db_path=db_path,
            dry_run=True,
            steps=steps,
            sector_map_size=len(sector_map),
        )

    _progress("Step 4: Validation gate running...")
    validation_step = _run_step("validation_gate", step_validation_gate, db_path)
    steps.append(validation_step)

    con = _connect_db(db_path)
    try:
        _set_meta(con, "stage1_validation_status", "PASS")
        _set_meta(con, "last_validation_gate", _run_now_iso())
        _set_meta(
            con,
            "price_jump_flagged_count",
            str(validation_step.metrics.get("price_jump_tickers", 0)),
        )
        con.commit()
    finally:
        con.close()

    report = _build_report(
        db_path=db_path,
        dry_run=False,
        steps=steps,
        sector_map_size=len(sector_map),
    )
    con = _connect_db(db_path)
    try:
        total_rows = int(con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0] or 0)
        total_tickers = int(con.execute("SELECT COUNT(DISTINCT ticker) FROM daily_bars").fetchone()[0] or 0)
    finally:
        con.close()
    _progress(
        f"DONE: {total_rows} bars, {total_tickers} tickers, validation: "
        f"{'PASS' if validation_step.metrics.get('ok') else 'FAIL'}"
    )
    _write_report(report, DEFAULT_REPORT_PATH)
    return report


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meridian Stage 1 cache pipeline")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without writing data")
    parser.add_argument("--skip-ibkr", action="store_true", help="skip shared IBKR daily sync step")
    parser.add_argument("--skip-alpaca", action="store_true", help="skip Alpaca bars step")
    parser.add_argument("--skip-yf", action="store_true", help="skip YFinance diff step")
    parser.add_argument("--skip-options", action="store_true", help="skip options pull step")
    parser.add_argument("--days", type=int, default=5, help="incremental freshness window")
    parser.add_argument("--full-refresh", action="store_true", help="download 2 years of history")
    parser.add_argument("--db", default=None, help="override DB path")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        report = run_pipeline(args)
    except ValidationAbort as exc:
        report = {
            "ok": False,
            "error": str(exc),
            "generated_at": _generated_at_utc(),
        }
        _write_report(report, DEFAULT_REPORT_PATH)
        print(json.dumps(report, indent=2))
        return 1
    except CacheWarmError as exc:
        report = {
            "ok": False,
            "error": str(exc),
            "generated_at": _run_now_iso(),
        }
        print(json.dumps(report, indent=2))
        return 1

    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
