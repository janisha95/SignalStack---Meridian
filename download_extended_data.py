#!/usr/bin/env python3
"""Download extended OHLCV data (2020-01-01 to 2024-08-31) from Alpaca.
This supplements the existing v2_universe.db which has 2024-09-01 to 2026-03-18.
Run with: nohup python3 download_extended_data.py > data/extended_download.log 2>&1 &
"""
import os, sys, json, time, sqlite3, urllib.request, urllib.error
from datetime import datetime, date, timedelta
from pathlib import Path

# Alpaca config
ALPACA_KEY = os.environ.get('ALPACA_KEY', os.environ.get('ALPACA_API_KEY', ''))
ALPACA_SECRET = os.environ.get('ALPACA_SECRET', os.environ.get('ALPACA_API_SECRET', ''))
BASE_URL = "https://data.alpaca.markets"

DB_PATH = Path(__file__).resolve().parent / "data" / "v2_universe.db"

START_DATE = "2020-01-01"
END_DATE = "2024-08-31"  # Day before existing data starts

def alpaca_get(url, params=None):
    """Make authenticated GET to Alpaca data API."""
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {url[:100]}", flush=True)
        return None

def get_active_tickers():
    """Get list of active US equities from existing DB."""
    con = sqlite3.connect(DB_PATH)
    tickers = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM daily_bars ORDER BY ticker"
    ).fetchall()]
    con.close()
    return tickers

def download_bars_for_ticker(ticker, start, end):
    """Download daily bars for one ticker from Alpaca."""
    all_bars = []
    page_token = None
    
    while True:
        params = {
            "start": start,
            "end": end,
            "timeframe": "1Day",
            "feed": "iex",
            "limit": "10000",
        }
        if page_token:
            params["page_token"] = page_token
        
        data = alpaca_get(f"{BASE_URL}/v2/stocks/{ticker}/bars", params)
        if not data:
            break
        
        bars = data.get("bars", [])
        all_bars.extend(bars)
        
        page_token = data.get("next_page_token")
        if not page_token:
            break
    
    return all_bars

def main():
    if not ALPACA_KEY or not ALPACA_SECRET:
        print("ERROR: Set ALPACA_KEY and ALPACA_SECRET environment variables", flush=True)
        sys.exit(1)
    
    print(f"[download] Starting extended data download: {START_DATE} to {END_DATE}", flush=True)
    print(f"[download] DB: {DB_PATH}", flush=True)
    
    # Get tickers from existing DB
    tickers = get_active_tickers()
    print(f"[download] {len(tickers)} tickers to download", flush=True)
    
    # Setup DB
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    
    total_bars = 0
    errors = 0
    
    for i, ticker in enumerate(tickers, 1):
        try:
            bars = download_bars_for_ticker(ticker, START_DATE, END_DATE)
            
            if bars:
                rows = []
                for b in bars:
                    d = b.get("t", "")[:10]  # YYYY-MM-DD
                    rows.append((
                        ticker, d,
                        float(b.get("o", 0)), float(b.get("h", 0)),
                        float(b.get("l", 0)), float(b.get("c", 0)),
                        int(b.get("v", 0)),
                    ))
                
                con.executemany(
                    "INSERT OR IGNORE INTO daily_bars (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                    rows
                )
                
                if i % 50 == 0:
                    con.commit()
                
                total_bars += len(rows)
            
            if i % 100 == 0:
                print(f"[download] Progress: {i}/{len(tickers)} ({i*100//len(tickers)}%) — {total_bars:,} bars total", flush=True)
            
            # Rate limiting: Alpaca free tier = 200 req/min
            time.sleep(0.35)
            
        except Exception as e:
            errors += 1
            if errors % 10 == 0:
                print(f"[download] Error on {ticker}: {e}", flush=True)
    
    con.commit()
    
    # Verify
    count = con.execute("SELECT COUNT(*) FROM daily_bars WHERE date < '2024-09-01'").fetchone()[0]
    print(f"\n[download] DONE: {total_bars:,} new bars downloaded, {errors} errors", flush=True)
    print(f"[download] Total pre-2024-09 bars in DB: {count:,}", flush=True)
    print(f"[download] Total bars in DB: {con.execute('SELECT COUNT(*) FROM daily_bars').fetchone()[0]:,}", flush=True)
    
    con.close()

if __name__ == "__main__":
    main()
