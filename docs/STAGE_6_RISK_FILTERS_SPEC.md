# STAGE 6: Risk Filters — v2_risk_filters.py

**Status:** SPEC COMPLETE — ready for build
**Depends on:** Stage 5 shortlist output
**Critical for:** Prop firm evaluation (FTMO, MyFundsTrader, etc.)

---

## What Stage 6 Does

Takes the ranked shortlist from Stage 5 and applies hard risk constraints to
produce a tradeable portfolio. This is the safety net that keeps you within
prop firm rules. It also computes position sizes and stop/take-profit levels.

**This stage is designed to be usable INDEPENDENTLY of the ML pipeline.**
It works with any shortlist — from Meridian's ML, from S1's convergence,
or from manual ticker selection. The risk math is the same regardless of
signal source.

---

## Prop Firm Rules (FTMO Default — configurable)

```python
RISK_CONFIG = {
    # Account parameters
    "account_balance": 100000,          # Starting balance (configurable)
    "currency": "USD",
    
    # FTMO rules
    "max_daily_loss_pct": 0.05,         # 5% max daily loss (hard limit)
    "max_total_drawdown_pct": 0.10,     # 10% max total drawdown (static from initial)
    "profit_target_pct": 0.10,          # 10% profit target (challenge phase)
    "best_day_max_pct": 0.50,           # No single day > 50% of total profit
    "min_trading_days": 4,              # Minimum 4 trading days
    
    # Position sizing
    "risk_per_trade_pct": 0.005,        # 0.5% risk per trade (conservative)
    "max_risk_per_trade_pct": 0.008,    # 0.8% maximum risk per trade
    "max_positions": 10,                # Maximum concurrent positions
    "max_portfolio_heat_pct": 0.08,     # 8% total portfolio heat (sum of all position risks)
    
    # Diversification
    "max_per_sector": 3,                # Max 3 positions in same GICS sector
    "max_correlation": 0.85,            # >0.85 rolling 60d correlation = demote one
    "max_direction_imbalance": 0.80,    # Max 80% of positions in one direction
    
    # Stop/Take-profit
    "stop_atr_multiple": 2.0,           # Initial stop = 2 × ATR(14) from entry
    "tp_atr_multiple": 4.0,             # Take profit = 4 × ATR(14) from entry (2:1 R/R)
    "trail_trigger_atr": 1.0,           # Start trailing when 1 × ATR in profit
    "trail_atr_multiple": 1.5,          # Trail at 1.5 × ATR once triggered
}
```

---

## Pipeline

```
Input: shortlist_daily (15 LONG + 15 SHORT from Stage 5)
  ↓
Step 1: Load current portfolio state (open positions, daily P&L, total P&L)
  ↓
Step 2: Check daily loss budget remaining
         daily_budget = (max_daily_loss_pct × account_balance) - abs(today_realized_loss)
  ↓
Step 3: Check total drawdown budget remaining
         drawdown_budget = (max_total_drawdown_pct × account_balance) - abs(max_drawdown_to_date)
  ↓
Step 4: Position sizing per candidate
         For each shortlist ticker:
           stop_distance = ATR(14) × stop_atr_multiple
           risk_dollars = min(risk_per_trade_pct × account_balance, daily_budget / max_new_positions)
           shares = floor(risk_dollars / stop_distance)
           position_value = shares × price
  ↓
Step 5: Apply filters (any filter can remove a candidate):
         a. Sector cap: max 3 per GICS sector (count existing positions)
         b. Correlation filter: skip if >0.85 correlation with existing position
         c. Portfolio heat: skip if adding this trade exceeds 8% total heat
         d. Daily loss budget: skip if not enough budget for this trade's risk
         e. Direction balance: skip if >80% in one direction
         f. Best day guard: ALERT if today's P&L > 40% of running total profit
  ↓
Step 6: Output tradeable portfolio (up to max_positions)
```

---

## 1. Input Contract

| Input | Source | Format |
|-------|--------|--------|
| Shortlist | Stage 5 (or manual) | DataFrame: ticker, direction, price, residual_alpha, regime, sector |
| Portfolio state | portfolio_state table in DB | Open positions, unrealized P&L, daily P&L |
| OHLCV | v2_universe.db | For ATR computation and correlation |
| Risk config | config/risk_config.json | Overridable parameters |

### CLI Arguments

| Flag | Default | Notes |
|------|---------|-------|
| `--account-balance` | from config | Override starting balance |
| `--risk-per-trade` | from config | Override risk % per trade |
| `--max-positions` | from config | Override max positions |
| `--dry-run` | False | Print portfolio plan without writing |
| `--prop-firm` | ftmo | Preset: ftmo, myfundedtrader, custom |
| `--debug` | None | Ticker to print full sizing math |

---

## 2. Output Contract

### Primary Output: tradeable_portfolio DataFrame

| Column | Type | Notes |
|--------|------|-------|
| ticker | str | |
| direction | str | LONG or SHORT |
| shares | int | Position size in shares |
| entry_price | float | Current price (or limit) |
| stop_price | float | Initial stop loss |
| tp_price | float | Take profit target |
| risk_dollars | float | $ at risk for this position |
| risk_pct | float | % of account at risk |
| position_value | float | shares × entry_price |
| atr | float | ATR(14) used for sizing |
| sector | str | For sector cap tracking |
| rank | int | From Stage 5 |
| residual_alpha | float | From Stage 5 |
| filter_status | str | APPROVED / SECTOR_CAP / CORRELATION / HEAT_LIMIT / etc. |

### DB Tables

```sql
-- Tradeable portfolio (written by Stage 6)
CREATE TABLE IF NOT EXISTS tradeable_portfolio (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT,
    shares INTEGER,
    entry_price REAL,
    stop_price REAL,
    tp_price REAL,
    risk_dollars REAL,
    risk_pct REAL,
    position_value REAL,
    atr REAL,
    sector TEXT,
    rank INTEGER,
    residual_alpha REAL,
    filter_status TEXT,
    PRIMARY KEY (date, ticker)
);

-- Portfolio state (tracks open positions + P&L over time)
CREATE TABLE IF NOT EXISTS portfolio_state (
    date TEXT NOT NULL,
    account_balance REAL,
    daily_pnl REAL,
    total_pnl REAL,
    total_pnl_pct REAL,
    max_drawdown REAL,
    max_drawdown_pct REAL,
    open_positions INTEGER,
    portfolio_heat_pct REAL,
    daily_loss_remaining REAL,
    drawdown_remaining REAL,
    distance_to_target REAL,
    best_day_pnl REAL,
    best_day_pct_of_total REAL,
    trading_days INTEGER,
    PRIMARY KEY (date)
);

-- Trade log (every entry/exit)
CREATE TABLE IF NOT EXISTS trade_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    direction TEXT,
    entry_date TEXT,
    entry_price REAL,
    shares INTEGER,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,          -- STOP_HIT, TP_HIT, TRAIL_STOP, MANUAL, TIME_EXIT
    pnl_dollars REAL,
    pnl_pct REAL,
    hold_days INTEGER,
    risk_dollars REAL
);
```

### Risk Dashboard Data (for UI)

The portfolio_state table provides everything the prop firm eval UI needs:

```json
{
    "account_balance": 103500,
    "daily_pnl": -450,
    "total_pnl": 3500,
    "total_pnl_pct": 3.5,
    
    "daily_loss_limit": 5000,
    "daily_loss_used": 450,
    "daily_loss_remaining": 4550,
    "daily_loss_pct_used": 9.0,
    
    "max_drawdown_limit": 10000,
    "max_drawdown_current": 1200,
    "drawdown_remaining": 8800,
    "drawdown_pct_used": 12.0,
    
    "profit_target": 10000,
    "profit_current": 3500,
    "distance_to_target": 6500,
    "target_pct_complete": 35.0,
    
    "open_positions": 7,
    "max_positions": 10,
    "portfolio_heat_pct": 4.2,
    
    "best_day_pnl": 1800,
    "best_day_pct_of_total": 51.4,
    "best_day_warning": true,
    
    "trading_days": 8,
    "min_trading_days": 4,
    "trading_days_met": true
}
```

---

## 3. Position Sizing Math

```python
def compute_position(ticker, direction, price, atr, config, portfolio_state):
    """Compute position size respecting all risk constraints."""
    
    account = config['account_balance'] + portfolio_state['total_pnl']
    
    # Risk budget per trade
    risk_per_trade = config['risk_per_trade_pct'] * config['account_balance']  # % of INITIAL balance
    
    # Daily loss budget remaining
    daily_remaining = (config['max_daily_loss_pct'] * config['account_balance']) - abs(portfolio_state['daily_loss_used'])
    
    # Can't risk more than remaining daily budget
    risk_dollars = min(risk_per_trade, daily_remaining * 0.5)  # don't use more than 50% of remaining daily
    
    if risk_dollars <= 0:
        return None  # daily budget exhausted
    
    # Stop distance
    stop_distance = atr * config['stop_atr_multiple']
    
    # Position size
    shares = int(risk_dollars / stop_distance)
    if shares <= 0:
        return None  # can't afford even 1 share at this risk level
    
    # Stop and TP prices
    if direction == 'LONG':
        stop_price = price - stop_distance
        tp_price = price + (atr * config['tp_atr_multiple'])
    else:  # SHORT
        stop_price = price + stop_distance
        tp_price = price - (atr * config['tp_atr_multiple'])
    
    return {
        'shares': shares,
        'entry_price': price,
        'stop_price': round(stop_price, 2),
        'tp_price': round(tp_price, 2),
        'risk_dollars': round(risk_dollars, 2),
        'risk_pct': round(risk_dollars / config['account_balance'] * 100, 3),
        'position_value': round(shares * price, 2),
        'atr': round(atr, 4),
    }
```

### Correlation Filter

```python
def check_correlation(ticker, existing_positions, ohlcv_dict, threshold=0.85):
    """Check if ticker is too correlated with any existing position."""
    ticker_returns = ohlcv_dict[ticker]['close'].pct_change().tail(60)
    for pos_ticker in existing_positions:
        if pos_ticker not in ohlcv_dict:
            continue
        pos_returns = ohlcv_dict[pos_ticker]['close'].pct_change().tail(60)
        corr = ticker_returns.corr(pos_returns)
        if abs(corr) > threshold:
            return False, pos_ticker, corr
    return True, None, None
```

---

## 4. Prop Firm Presets

```python
PROP_FIRM_PRESETS = {
    "ftmo": {
        "max_daily_loss_pct": 0.05,
        "max_total_drawdown_pct": 0.10,
        "profit_target_pct": 0.10,
        "best_day_max_pct": 0.50,
        "min_trading_days": 4,
    },
    "myfundedtrader": {
        "max_daily_loss_pct": 0.05,
        "max_total_drawdown_pct": 0.08,
        "profit_target_pct": 0.08,
        "best_day_max_pct": None,  # no best day rule
        "min_trading_days": 5,
    },
    "custom": {}  # user provides all values
}
```

---

## 5. What the Frontend Needs from Stage 6

For a prop firm eval UI, the frontend needs these API endpoints (Stage 7 serves them):

```
GET /api/portfolio/state          → portfolio_state for today
GET /api/portfolio/positions      → open positions with P&L
GET /api/portfolio/risk-gauges    → daily loss %, drawdown %, heat %
GET /api/portfolio/tradeable      → today's approved trades with sizing
GET /api/portfolio/trade-log      → historical trades with outcomes
GET /api/portfolio/equity-curve   → daily balance over time (from portfolio_state)
GET /api/portfolio/rules-status   → prop firm rules compliance check
```

All data comes from the 3 DB tables (tradeable_portfolio, portfolio_state, trade_log).
The frontend just reads and displays. No computation needed client-side.

---

## 6. Success Test

```bash
# Dry run with mock shortlist
python3 stages/v2_risk_filters.py --dry-run --prop-firm ftmo

# Debug one ticker
python3 stages/v2_risk_filters.py --debug AAPL --dry-run

# Expected output:
# [risk] Account: $100,000 (FTMO challenge)
# [risk] Daily loss budget: $5,000 remaining
# [risk] Drawdown budget: $10,000 remaining
# [risk] Shortlist: 15 LONG + 15 SHORT
# [risk] Applying filters...
# [risk]   AAPL LONG: APPROVED — 45 shares @ $252.61, stop $245.80, TP $266.22, risk $306.45 (0.31%)
# [risk]   MSFT LONG: SECTOR_CAP — Technology already has 3 positions
# [risk]   GOOGL LONG: CORRELATION — 0.91 corr with MSFT (existing)
# [risk] Portfolio: 8 positions, heat 4.2%, daily used 0%
# [risk] DONE: 8 tradeable, 22 filtered
```

---

## 7. Acceptance Criteria

- [ ] `stages/v2_risk_filters.py` exists
- [ ] `config/risk_config.json` with all parameters
- [ ] Position sizing uses ATR-based stops
- [ ] Daily loss budget tracked and enforced
- [ ] Total drawdown tracked and enforced
- [ ] Sector cap (max 3 per sector) enforced
- [ ] Correlation filter (>0.85 = skip) implemented
- [ ] Portfolio heat cap enforced
- [ ] Best day warning at 40% threshold
- [ ] Direction balance check
- [ ] portfolio_state, tradeable_portfolio, trade_log tables created
- [ ] --prop-firm preset flag works (ftmo, myfundedtrader)
- [ ] --debug shows full sizing math
- [ ] Works with mock shortlist (no dependency on ML)
- [ ] Progress logging per OPERATIONAL_STANDARDS.md
- [ ] No S1 imports
- [ ] QA report at qa_report_stage6.md
