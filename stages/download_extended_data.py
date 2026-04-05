import os, sys, json, time, sqlite3, urllib.request, urllib.error
from pathlib import Path

ALPACA_KEY = os.environ.get('ALPACA_KEY', '')
ALPACA_SECRET = os.environ.get('ALPACA_SECRET', '')
BASE_URL = "https://data.alpaca.markets"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "v2_universe.db"
START_DATE = "2020-01-01"
END_DATE = "2024-08-31"

def alpaca_get(url, params=None):
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
        return None

def main():
    if not ALPACA_KEY or not ALPACA_SECRET:
        print("ERROR: Set ALPACA_KEY and ALPACA_SECRET", flush=True)
        sys.exit(1)
    print(f"[download] Starting: {START_DATE} to {END_DATE}", flush=True)
    print(f"[download] DB: {DB_PATH}", flush=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    tickers = [r[0] for r in con.execute("SELECT DISTINCT ticker FROM daily_bars ORDER BY ticker").fetchall()]
    print(f"[download] {len(tickers)} tickers", flush=True)
    total_bars = 0
    errors = 0
    for i, ticker in enumerate(tickers, 1):
        try:
            all_bars = []
            page_token = None
            while True:
                params = {"start": START_DATE, "end": END_DATE, "timeframe": "1Day", "feed": "iex", "adjustment": "split", "limit": "10000"}
                if page_token: params["page_token"] = page_token
                data = alpaca_get(f"{BASE_URL}/v2/stocks/{ticker}/bars", params)
                if not data: break
                bars = data.get("bars", [])
                all_bars.extend(bars)
                page_token = data.get("next_page_token")
                if not page_token: break
            if all_bars:
                rows = [(ticker, b.get("t","")[:10], float(b.get("o",0)), float(b.get("h",0)), float(b.get("l",0)), float(b.get("c",0)), int(b.get("v",0))) for b in all_bars]
                con.executemany("INSERT OR IGNORE INTO daily_bars (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)", rows)
                total_bars += len(rows)
            if i % 50 == 0:
                con.commit()
            if i % 100 == 0:
                print(f"[download] {i}/{len(tickers)} ({i*100//len(tickers)}%) — {total_bars:,} bars", flush=True)
            time.sleep(0.35)
        except Exception as e:
            errors += 1
            if errors % 10 == 0: print(f"[download] Error {ticker}: {e}", flush=True)
    con.commit()
    count = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
    print(f"\n[download] DONE: {total_bars:,} new bars, {errors} errors, {count:,} total in DB", flush=True)
    con.close()

if __name__ == "__main__":
    main()
