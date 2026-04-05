# Stage 6 Update: Trade The Pool Day Trade $50K Rules

## Context
Updating v2_risk_filters.py from FTMO rules to Trade The Pool 
Day Trade FLEX $50K account rules. Meridian will be used for 
day trading (enter at open, exit by 3:30pm ET) on TTP platform.

## TTP Day Trade $50K FLEX Rules

```python
RISK_CONFIG = {
    # Account parameters
    "account_balance": 50000,
    "currency": "USD",
    "prop_firm": "trade_the_pool_day_50k",
    
    # TTP Day Trade rules
    "max_daily_loss_pct": 0.02,          # 2% daily loss ($1,000) — pauses account
    "max_total_drawdown_pct": 0.04,      # 4% max drawdown ($2,000) — terminates
    "profit_target_pct": 0.06,           # 6% profit target ($3,000)
    "max_single_trade_profit_pct": 0.30, # No single trade > 30% of total eval profit
    "min_positions": 20,                 # Min 20 positions during eval
    "min_trade_duration_sec": 30,        # Trades < 30 sec don't count
    "min_tick_profit": 10,               # Min 10 ticks ($0.10/share) profit to count
    
    # Position sizing (conservative for $50K)
    "risk_per_trade_pct": 0.004,         # 0.4% risk per trade ($200)
    "max_risk_per_trade_pct": 0.008,     # 0.8% max risk per trade ($400)
    "max_positions": 5,                  # Max 5 concurrent positions (conservative)
    "max_portfolio_heat_pct": 0.03,      # 3% total heat ($1,500) — stays under 4% DD
    
    # Diversification
    "max_per_sector": 2,                 # Max 2 positions in same sector
    "max_correlation": 0.85,             # Correlation filter
    "max_direction_imbalance": 0.80,     # Max 80% in one direction
    
    # Stop/Take-profit (TBM aligned, tighter for intraday)
    "stop_atr_multiple": 1.0,            # Tighter stop for day trade (1x ATR)
    "tp_atr_multiple": 2.0,              # 2:1 R/R minimum
    "trail_trigger_atr": 0.75,           # Start trailing earlier
    "trail_atr_multiple": 1.0,           # Tighter trail
    
    # TTP-specific filters
    "must_close_eod": True,              # ALL positions closed by 3:30pm ET
    "eod_close_time": "15:30",           # Close positions by this time (ET)
    "no_new_trades_after": "15:00",      # No new entries after 3:00pm ET
    "block_earnings_same_day": True,     # No stocks reporting earnings today
    "block_halted": True,                # No halted stocks
    "block_low_volume": 200000,          # Min 200K shares/day regular hours
    "block_high_volatility_4min": 0.08,  # Block stocks that moved 8%+ in 4 min
    "block_leveraged_inverse": True,     # Block leveraged/inverse ETFs
    
    # Commission
    "commission_per_trade": 0.75,        # $0.75 per trade OR $0.005/share
}
```

## Changes to v2_risk_filters.py

### 1. Replace FTMO preset with TTP preset
Find the PROP_FIRM_PRESETS dict and replace/add:

```python
PROP_FIRM_PRESETS = {
    "trade_the_pool_day_50k": {
        "max_daily_loss_pct": 0.02,
        "max_total_drawdown_pct": 0.04,
        "profit_target_pct": 0.06,
        "max_single_trade_profit_pct": 0.30,
        "min_positions": 20,
        "must_close_eod": True,
    },
    "trade_the_pool_day_100k": {
        "max_daily_loss_pct": 0.02,
        "max_total_drawdown_pct": 0.04,
        "profit_target_pct": 0.06,
        "max_single_trade_profit_pct": 0.30,
        "min_positions": 20,
        "must_close_eod": True,
    },
    "trade_the_pool_swing_10k": {
        "max_daily_loss_pct": 0.03,
        "max_total_drawdown_pct": 0.07,
        "profit_target_pct": 0.15,
        "max_single_trade_profit_pct": 0.30,
        "min_positions": 5,
        "must_close_eod": False,
    },
    # Keep FTMO as legacy option
    "ftmo": {
        "max_daily_loss_pct": 0.05,
        "max_total_drawdown_pct": 0.10,
        "profit_target_pct": 0.10,
        "best_day_max_pct": 0.50,
        "min_trading_days": 4,
        "must_close_eod": False,
    },
}
```

### 2. Add EOD Close Filter
Add a new filter that blocks trades after 3:00pm ET and flags 
existing positions for closure by 3:30pm ET:

```python
def check_eod_close(config, current_time_et):
    """Check if we should block new trades or close positions."""
    if not config.get("must_close_eod", False):
        return {"can_open": True, "must_close": False}
    
    no_new_after = config.get("no_new_trades_after", "15:00")
    close_by = config.get("eod_close_time", "15:30")
    
    # Parse times
    hour_no_new = int(no_new_after.split(":")[0])
    min_no_new = int(no_new_after.split(":")[1])
    hour_close = int(close_by.split(":")[0])
    min_close = int(close_by.split(":")[1])
    
    current_hour = current_time_et.hour
    current_min = current_time_et.minute
    
    can_open = (current_hour < hour_no_new) or \
               (current_hour == hour_no_new and current_min < min_no_new)
    must_close = (current_hour > hour_close) or \
                 (current_hour == hour_close and current_min >= min_close)
    
    return {"can_open": can_open, "must_close": must_close}
```

### 3. Add Earnings Filter
```python
def check_earnings_today(ticker, date):
    """Check if ticker reports earnings today. Block if yes."""
    # For now, use a simple yfinance check
    # TODO: Wire to earnings calendar API
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).calendar
        if info is not None and 'Earnings Date' in info:
            earnings_dates = info['Earnings Date']
            if date in [str(d.date()) for d in earnings_dates]:
                return True
    except:
        pass
    return False
```

### 4. Add Leveraged/Inverse ETF Filter
```python
LEVERAGED_KEYWORDS = [
    "Ultra", "2X", "3X", "-1X", "Inverse", "Short", "Bear",
    "ProShares", "Direxion", "Daily Bull", "Daily Bear"
]

def is_leveraged_inverse(ticker):
    """Check if ticker is a leveraged or inverse ETF."""
    # Quick check by known tickers
    KNOWN_LEVERAGED = {
        "TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY", "SVXY",
        "LABU", "LABD", "NUGT", "DUST", "JNUG", "JDST",
        "FAS", "FAZ", "TNA", "TZA", "TECL", "TECS",
        "SOXL", "SOXS", "UDOW", "SDOW", "UPRO", "SDS",
        "QLD", "QID", "DDM", "DXD", "MVV", "MZZ",
        "TWM", "UWM", "BTCZ", "SBIT", "TSLQ", "MSTZ",
        "AMDD", "TSDD", "UVIX", "GDXU", "GDXD",
    }
    return ticker in KNOWN_LEVERAGED
```

### 5. Update Position Sizing for $50K
With $50K buying power and 2% daily loss ($1,000):
- Risk per trade: 0.4% = $200
- Max 5 concurrent positions = $1,000 max heat (2% of $50K)
- This leaves $1,000 buffer before 4% drawdown ($2,000)
- Typical position: $200 risk / ($2 ATR stop) = 100 shares at $50/share

### 6. Update Default Preset
Change the default from "ftmo" to "trade_the_pool_day_50k":

```python
DEFAULT_PROP_FIRM = "trade_the_pool_day_50k"
```

## Stage 2 Prefilter Updates (v2_prefilter.py)

Add these filters to the prefilter to catch TTP-prohibited stocks:

1. Volume: Exclude stocks with < 200K avg daily volume
2. Leveraged/Inverse: Exclude known leveraged/inverse ETFs
3. Price: Exclude penny stocks < $1.00 (TTP may restrict)

## Verification

```bash
cd ~/SS/Meridian

# Compile check
python3 -c "import ast; ast.parse(open('stages/v2_risk_filters.py').read()); print('OK')"

# Dry run with TTP rules
python3 stages/v2_risk_filters.py --dry-run --prop-firm trade_the_pool_day_50k

# Check position sizing
python3 stages/v2_risk_filters.py --size AAPL LONG --prop-firm trade_the_pool_day_50k

# Verify no leveraged ETFs pass
python3 -c "
from stages.v2_risk_filters import is_leveraged_inverse
for t in ['TQQQ','SQQQ','BTCZ','SBIT','TSLQ','AAPL','MSFT']:
    print(f'{t}: blocked={is_leveraged_inverse(t)}')
"
```

## DO NOT TOUCH
- v2_selection.py (Stage 5 — working, git committed)
- tcn_scorer.py (Stage 4B)
- v2_orchestrator.py (except adding prefilter updates)
- v2_forward_tracker.py (just built, working)

py_compile after all changes.
