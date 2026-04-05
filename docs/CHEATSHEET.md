# Meridian v2 — Quick Reference Cheat Sheet

## Start Everything
```bash
# API server
cd ~/SS/Meridian && python3 stages/v2_api_server.py &

# React dashboard  
cd ~/SS/Meridian/ui/signalstack-app && npm run dev &

# View dashboard: http://localhost:3000
# View API: http://localhost:8080/api/candidates
```

## Run Pipeline (Daily)
```bash
cd ~/SS/Meridian
python3 stages/v2_orchestrator.py 2>&1 | tee data/orchestrator_run.log
```

## Debug: SPY Stale Data
```bash
cd ~/SS/Meridian
python3 -c "
import sqlite3, yfinance as yf
con = sqlite3.connect('data/v2_universe.db')
spy = yf.download('SPY', period='5d', progress=False)
for idx, row in spy.iterrows():
    d = str(idx)[:10]
    if not con.execute('SELECT 1 FROM daily_bars WHERE ticker=\"SPY\" AND date=?',(d,)).fetchone():
        con.execute('INSERT INTO daily_bars (ticker,date,open,high,low,close,volume,source) VALUES (?,?,?,?,?,?,?,?)',
            ('SPY',d,float(row['Open']),float(row['High']),float(row['Low']),float(row['Close']),int(row['Volume']),'yfinance_fix'))
        print(f'Inserted SPY {d}')
con.commit(); con.close()
"
```

## Debug: Check DB State
```bash
cd ~/SS/Meridian
python3 -c "
import sqlite3
con = sqlite3.connect('data/v2_universe.db')
print('daily_bars:', con.execute('SELECT COUNT(*) FROM daily_bars').fetchone()[0])
print('training_data:', con.execute('SELECT COUNT(*) FROM training_data').fetchone()[0])
print('factor_history:', con.execute('SELECT COUNT(*), COUNT(DISTINCT date) FROM factor_history').fetchone())
print('SPY latest:', con.execute('SELECT MAX(date) FROM daily_bars WHERE ticker=\"SPY\"').fetchone()[0])
con.close()
"
```

## Debug: Test TCN Scorer
```bash
cd ~/SS/Meridian
python3 -c "
from stages.tcn_scorer import TCNScorer
s = TCNScorer()
scores = s.score('2026-03-18')
print(f'Scored {len(scores)} tickers')
print(scores.head(10))
"
```

## Debug: Test Each Stage
```bash
# Stage 1
python3 -c "import sqlite3; c=sqlite3.connect('data/v2_universe.db'); print('Bars:', c.execute('SELECT COUNT(*) FROM daily_bars').fetchone()[0])"

# Stage 3
python3 stages/v2_factor_engine.py --dry-run --debug AAPL

# Stage 4B
python3 -c "from stages.tcn_scorer import TCNScorer; s=TCNScorer(); print('OK')"

# Stage 5
python3 stages/v2_selection.py --dry-run --mock

# Stage 6
python3 -c "from stages.v2_risk_filters import build_tradeable_portfolio; from pathlib import Path; f,s=build_tradeable_portfolio(db_path=Path('data/v2_universe.db').resolve(),dry_run=True,mock=True,prop_firm='ftmo'); print(f'{len(f)} candidates')"

# Stage 7
curl -s http://localhost:8080/health | python3 -m json.tool
curl -s http://localhost:8080/api/candidates | python3 -m json.tool | head -20
```

## Backfill
```bash
# Local (resume from where stopped)
cd ~/SS/Meridian
nohup python3 stages/v2_training_backfill.py --start-date 2021-09-08 > data/backfill_extended2.log 2>&1 &
tail -f data/backfill_extended2.log

# Check progress
tail -3 ~/SS/Meridian/data/backfill_extended2.log
```

## Colab Training
```
1. Go to colab.research.google.com
2. Mount Drive: from google.colab import drive; drive.mount('/content/drive')
3. CSV is at: /content/drive/MyDrive/meridian_ALL_features.csv
4. Use L4 or A100 GPU for TCN training
```

## Key Files
```
~/SS/Meridian/
├── stages/v2_orchestrator.py      ← runs full pipeline
├── stages/v2_cache_warm.py        ← Stage 1: download bars
├── stages/v2_prefilter.py         ← Stage 2: filter universe
├── stages/v2_factor_engine.py     ← Stage 3: compute factors
├── stages/tcn_scorer.py           ← Stage 4B: ML scoring
├── stages/v2_selection.py         ← Stage 5: rank + select
├── stages/v2_risk_filters.py      ← Stage 6: position sizing
├── stages/v2_api_server.py        ← Stage 7: API server
├── config/factor_registry.json    ← factor definitions
├── models/tcn_pass_v1/            ← TCN model files
│   ├── model.pt
│   └── config.json
├── data/v2_universe.db            ← main database
└── ui/signalstack-app/            ← React dashboard
```

## Winning Model Config
- TCN Classifier, 19 features, TBM labels (+2%/-1%)
- 64-bar lookback, 4-layer CNN (64→64→64→32)
- BCEWithLogitsLoss, Adam lr=1e-3
- IC=+0.031 [PASS], hit=68%, spread=+0.56%

## Notion Pages
- Handoff: 330b2399fcac81b98b90e5a8229ea0cd
- System State: 32fb2399fcac81ea9b88cf769bec33ed
- ML Training: 32fb2399fcac81b4a48ccfd94f6b3d3b
