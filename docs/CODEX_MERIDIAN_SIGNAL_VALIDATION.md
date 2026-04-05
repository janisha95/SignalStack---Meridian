# CODEX — Meridian Signal Validation + Model Deep Dive

## Goal
1. Fetch LIVE prices for all 60 Meridian shortlist tickers (30 LONG + 30 SHORT) from Mar 31
2. Compare with their TCN score, LGBM predicted_return, and factor_rank
3. Determine which signal component (TCN, LGBM, factor_rank) was most predictive
4. Deep dive into TCN and LGBM model characteristics

## DO NOT change any code. Read only + analysis.

## Part 1: Live Price Validation

```python
import sqlite3, yfinance as yf, pandas as pd, numpy as np
from scipy.stats import spearmanr

# Load Mar 31 shortlist
MERIDIAN_DB = '/Users/sjani008/SS/Meridian/data/v2_universe.db'
con = sqlite3.connect(MERIDIAN_DB)
df = pd.read_sql("""
    SELECT ticker, direction, tcn_score, factor_rank, final_score, 
           predicted_return, lgbm_long_prob, lgbm_short_prob, rank
    FROM shortlist_daily 
    WHERE date = '2026-03-31'
    ORDER BY direction, final_score DESC
""", con)
con.close()

print(f'Shortlist: {len(df)} tickers')
print(f'LONG: {len(df[df.direction=="LONG"])}, SHORT: {len(df[df.direction=="SHORT"])}')

# Fetch Mar 31 close and Apr 1 current price
tickers = df['ticker'].tolist()
print(f'Downloading prices for {len(tickers)} tickers...')
prices = yf.download(tickers, start='2026-03-28', end='2026-04-02', progress=False)

# Compute 1-day return (Mar 31 close → Apr 1 latest)
results = []
for _, row in df.iterrows():
    ticker = row['ticker']
    try:
        if len(tickers) > 1:
            close_mar31 = prices['Close'][ticker].loc['2026-03-31']
            close_apr1 = prices['Close'][ticker].iloc[-1]
        else:
            close_mar31 = prices['Close'].loc['2026-03-31']
            close_apr1 = prices['Close'].iloc[-1]
        ret = (close_apr1 - close_mar31) / close_mar31
    except:
        ret = None
    
    results.append({
        **row.to_dict(),
        'close_mar31': close_mar31 if ret is not None else None,
        'close_apr1': close_apr1 if ret is not None else None,
        'return_1d': ret,
    })

rdf = pd.DataFrame(results)
rdf = rdf.dropna(subset=['return_1d'])
print(f'Got prices for {len(rdf)} / {len(df)} tickers')

# For SHORTS, the "correct" outcome is negative return
rdf['signal_correct'] = False
rdf.loc[(rdf['direction'] == 'LONG') & (rdf['return_1d'] > 0), 'signal_correct'] = True
rdf.loc[(rdf['direction'] == 'SHORT') & (rdf['return_1d'] < 0), 'signal_correct'] = True

# === RESULTS TABLE ===
print('\n' + '='*100)
print('  MERIDIAN LONGS — Mar 31 picks vs Apr 1 prices')
print('='*100)
print(f'{"#":>3} {"Ticker":8} {"TCN":>7} {"LGBM_pred":>10} {"FR":>7} {"Final":>7} {"Close 3/31":>11} {"Close 4/1":>11} {"Return":>8} {"Correct?":>10}')
print('-'*100)
longs = rdf[rdf['direction'] == 'LONG'].sort_values('final_score', ascending=False)
for i, (_, r) in enumerate(longs.iterrows(), 1):
    sign = '✅' if r['signal_correct'] else '❌'
    print(f'{i:3d} {r["ticker"]:8s} {r["tcn_score"]:7.3f} {r["predicted_return"]:+10.4f} {r["factor_rank"]:7.3f} {r["final_score"]:7.3f} {r["close_mar31"]:11.2f} {r["close_apr1"]:11.2f} {r["return_1d"]:+8.2%} {sign:>10}')

print('\n' + '='*100)
print('  MERIDIAN SHORTS — Mar 31 picks vs Apr 1 prices')
print('='*100)
print(f'{"#":>3} {"Ticker":8} {"TCN":>7} {"LGBM_pred":>10} {"FR":>7} {"Final":>7} {"Close 3/31":>11} {"Close 4/1":>11} {"Return":>8} {"Correct?":>10}')
print('-'*100)
shorts = rdf[rdf['direction'] == 'SHORT'].sort_values('final_score', ascending=False)
for i, (_, r) in enumerate(shorts.iterrows(), 1):
    sign = '✅' if r['signal_correct'] else '❌'
    print(f'{i:3d} {r["ticker"]:8s} {r["tcn_score"]:7.3f} {r["predicted_return"]:+10.4f} {r["factor_rank"]:7.3f} {r["final_score"]:7.3f} {r["close_mar31"]:11.2f} {r["close_apr1"]:11.2f} {r["return_1d"]:+8.2%} {sign:>10}')

# === SIGNAL QUALITY COMPARISON ===
print('\n' + '='*80)
print('  SIGNAL QUALITY — Who predicted correctly?')
print('='*80)

# Overall accuracy
long_acc = longs['signal_correct'].mean() * 100
short_acc = shorts['signal_correct'].mean() * 100
print(f'\nDirection accuracy:')
print(f'  LONG:  {long_acc:.1f}% ({longs["signal_correct"].sum()}/{len(longs)} correct)')
print(f'  SHORT: {short_acc:.1f}% ({shorts["signal_correct"].sum()}/{len(shorts)} correct)')

# IC for each signal component vs actual return
print(f'\nIC (Spearman correlation with actual 1-day return):')
for col, label in [('tcn_score', 'TCN Score'), ('predicted_return', 'LGBM Predicted Return'),
                    ('factor_rank', 'Factor Rank'), ('final_score', 'Final Score (current blend)')]:
    if col in rdf.columns:
        # For longs: higher score should predict higher return
        l_ic, _ = spearmanr(longs[col], longs['return_1d'])
        # For shorts: lower tcn/higher FR should predict more negative return
        s_ic, _ = spearmanr(shorts[col], shorts['return_1d'])
        # Overall
        all_ic, _ = spearmanr(rdf[col], rdf['return_1d'])
        print(f'  {label:30s}  LONG IC={l_ic:+.4f}  SHORT IC={s_ic:+.4f}  ALL IC={all_ic:+.4f}')

# Simulated Option A: 0.60 * tcn + 0.40 * lgbm_long_prob
if 'lgbm_long_prob' in rdf.columns and rdf['lgbm_long_prob'].notna().any():
    rdf['option_a_score'] = 0.60 * rdf['tcn_score'] + 0.40 * rdf['lgbm_long_prob']
    oa_ic, _ = spearmanr(rdf['option_a_score'], rdf['return_1d'])
    print(f'  {"Option A (0.6 TCN + 0.4 LGBM)":30s}  ALL IC={oa_ic:+.4f}')

# Top 5 vs Bottom 5 spread
print(f'\nTop 5 LONG avg return: {longs.head(5)["return_1d"].mean():+.2%}')
print(f'Bottom 5 LONG avg return: {longs.tail(5)["return_1d"].mean():+.2%}')
print(f'Top 5 SHORT avg return: {shorts.head(5)["return_1d"].mean():+.2%}')
print(f'Bottom 5 SHORT avg return: {shorts.tail(5)["return_1d"].mean():+.2%}')
```

## Part 2: TCN + LGBM Model Deep Dive

```python
import json

# TCN model config
print('\n' + '='*80)
print('  TCN MODEL DEEP DIVE')
print('='*80)

tcn_config = json.load(open('/Users/sjani008/SS/Meridian/models/tcn_pass_v1/config.json'))
print(f'TCN Config:')
for k, v in tcn_config.items():
    print(f'  {k}: {v}')

# LGBM model config
print('\n' + '='*80)
print('  LGBM MODEL DEEP DIVE')
print('='*80)

for side in ['long', 'short']:
    try:
        lgbm_config = json.load(open(f'/Users/sjani008/SS/Meridian/models/lgbm_v2_{side}/config.json'))
        print(f'\nLGBM {side.upper()} Config:')
        for k, v in lgbm_config.items():
            print(f'  {k}: {v}')
    except Exception as e:
        print(f'\nLGBM {side.upper()}: {e}')

# Check predictions_daily distribution
print('\n' + '='*80)
print('  PREDICTIONS_DAILY DISTRIBUTION (Mar 31)')
print('='*80)

con = sqlite3.connect(MERIDIAN_DB)
preds = pd.read_sql("SELECT * FROM predictions_daily WHERE date = '2026-03-31'", con)
con.close()

print(f'Total tickers scored: {len(preds)}')
for col in ['predicted_return', 'lgbm_long_prob', 'lgbm_short_prob']:
    if col in preds.columns:
        vals = preds[col].dropna()
        print(f'\n{col}:')
        print(f'  count={len(vals)}, mean={vals.mean():.4f}, std={vals.std():.4f}')
        print(f'  min={vals.min():.4f}, 25%={vals.quantile(0.25):.4f}, 50%={vals.median():.4f}, 75%={vals.quantile(0.75):.4f}, max={vals.max():.4f}')
        # Is it all positive? (the calibration issue)
        print(f'  % positive: {(vals > 0).mean()*100:.1f}%')
        print(f'  % > 0.50: {(vals > 0.50).mean()*100:.1f}%')

# TCN score distribution from shortlist
print('\n' + '='*80)
print('  TCN SCORE DISTRIBUTION')
print('='*80)
con = sqlite3.connect(MERIDIAN_DB)
tcn_all = pd.read_sql("""
    SELECT ticker, direction, tcn_score FROM shortlist_daily WHERE date = '2026-03-31'
""", con)
con.close()

for d in ['LONG', 'SHORT']:
    vals = tcn_all[tcn_all['direction'] == d]['tcn_score']
    print(f'\nTCN {d}:')
    print(f'  count={len(vals)}, mean={vals.mean():.3f}, std={vals.std():.3f}')
    print(f'  min={vals.min():.3f}, max={vals.max():.3f}')

# KEY QUESTION: Is TCN calibrated for shorts?
print('\n' + '='*80)
print('  KEY QUESTION: Is TCN a one-sided classifier?')
print('='*80)
print('TCN is trained with TBM labels: P(bullish) = sigmoid output')
print('LONG picks have high TCN (0.73-1.00) = model says bullish = CORRECT USE')
print('SHORT picks have low TCN (0.02-0.37) = model says NOT bullish = INVERTED USE')
print('The model was NEVER trained to predict bearish setups explicitly.')
print('Low TCN could mean "not bullish" OR "no data/confused" OR genuinely bearish.')
print()
print('LGBM predicted_return for SHORT picks:')
short_pred = preds[preds['ticker'].isin(shorts['ticker'].tolist())]['predicted_return']
if len(short_pred) > 0:
    print(f'  mean={short_pred.mean():.4f}, min={short_pred.min():.4f}, max={short_pred.max():.4f}')
    print(f'  % positive: {(short_pred > 0).mean()*100:.1f}%')
    print('  If LGBM predicted_return is positive for shorts, LGBM DISAGREES with the short thesis.')

print('\nDone!')
```

Run both parts and report ALL output.
