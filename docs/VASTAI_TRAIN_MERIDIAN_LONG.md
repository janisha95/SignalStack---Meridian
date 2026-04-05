# VAST.AI — Train Meridian LONG TCN + LGBM

## Upload 3 files only
```bash
scp meridian_ALL_features.csv root@<vast_ip>:/workspace/
scp meridian_daily_bars.csv root@<vast_ip>:/workspace/
scp meridian_factor_history.csv root@<vast_ip>:/workspace/
```

NO old model needed — training from scratch.

## Setup
```bash
pip install torch lightgbm pandas numpy scipy scikit-learn joblib
```

## FIRST: Explore the CSV (paste output before training)
```bash
python3 -c "
import pandas as pd
df = pd.read_csv('meridian_ALL_features.csv')
print(f'Rows: {len(df):,}')
print(f'Tickers: {df[\"ticker\"].nunique() if \"ticker\" in df.columns else \"no ticker col\"}')
print(f'Columns ({len(df.columns)}):')
for c in sorted(df.columns):
    nulls = df[c].isna().sum()
    print(f'  {c:40s} {str(df[c].dtype):10s} nulls={nulls}')
"
```

## Create train_long.py and run
```bash
cat > /workspace/train_long.py << 'SCRIPT'
#!/usr/bin/env python3
"""Train Meridian LONG: TCN + LGBM. ETFs excluded. Same data as SHORT TCN (IC 0.392)."""
import json, sys, time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.stats import spearmanr
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

LOOKBACK = 64
CHANNELS = [64, 64, 64, 32]
KERNEL_SIZE = 3
DILATIONS = [1, 2, 4, 8]
DROPOUT = 0.3
EPOCHS = 100
BATCH_SIZE = 256
LR = 0.001
PATIENCE = 15
LABEL_THRESHOLD = 0.02

ETFS = {'SCHD','GFLW','DFAU','NOBL','SPYD','FNDE','AVLV','SDY','IDV','COWZ','HDV','OIH','BBJP','VLUE','GCOW','VIG','DVY','DGRO','VYM','DGRW','SCHG','SCHA','SCHB','SCHX','SCHF','SCHE','SPY','QQQ','IWM','DIA','VOO','VTI','IVV','VEA','VWO','XLK','XLF','XLE','XLV','XLI','XLY','XLP','XLU','XLB','ARKK','SARK','TQQQ','SQQQ','SPXL','SPXS','UVXY','SVXY','MSTZ','QTEC','QLD','QID','SSO','SDS','VXX','VIXY','FLOT','VUSB','GSY','FLRN','USFR','ICSH','JPST','FTSM','PULS','BND','AGG','TLT','SHY','IEF','LQD','HYG','JNK','SPDN','SH','IXC','IEMG','EEM','EFA'}

def load_data():
    print("Loading meridian_ALL_features.csv...")
    df = pd.read_csv('/workspace/meridian_ALL_features.csv')
    print(f"  Raw: {len(df):,} rows, {df['ticker'].nunique()} tickers")
    meta = {'ticker','symbol','date','close','open','high','low','volume','forward_return','fwd_5d_return','label_long','label_short','fwd_return','returns','adj_close'}
    features = [c for c in df.columns if c not in meta and df[c].dtype in ['float64','int64','float32','int32'] and df[c].notna().sum() > len(df)*0.3]
    print(f"  Features: {len(features)}")
    
    label_col = None
    for c in ['forward_return','fwd_5d_return','fwd_return','returns_5d']:
        if c in df.columns:
            label_col = c; break
    if label_col is None and 'close' in df.columns:
        print("  Computing forward 5d returns...")
        df = df.sort_values(['ticker','date'])
        df['forward_return'] = df.groupby('ticker')['close'].transform(lambda x: x.shift(-5)/x - 1)
        label_col = 'forward_return'
    if label_col is None:
        # Try daily bars file
        bars = pd.read_csv('/workspace/meridian_daily_bars.csv')
        bars = bars.sort_values(['ticker','date'])
        bars['forward_return'] = bars.groupby('ticker')['close'].transform(lambda x: x.shift(-5)/x - 1)
        df = df.merge(bars[['ticker','date','forward_return']], on=['ticker','date'], how='left')
        label_col = 'forward_return'
    
    df = df.dropna(subset=[label_col])
    before = df['ticker'].nunique()
    df = df[~df['ticker'].isin(ETFS)]
    after = df['ticker'].nunique()
    print(f"  ETF exclusion: {before} -> {after} ({before-after} removed)")
    df['label_long'] = (df[label_col] > LABEL_THRESHOLD).astype(int)
    print(f"  Label rate: {df['label_long'].mean():.3f}")
    print(f"  Final: {len(df):,} rows")
    return df, features, label_col

class TemporalBlock(nn.Module):
    def __init__(s, ni, no, ks, d, dr):
        super().__init__()
        p = (ks-1)*d
        s.c1 = nn.Conv1d(ni,no,ks,padding=p,dilation=d)
        s.b1 = nn.BatchNorm1d(no)
        s.c2 = nn.Conv1d(no,no,ks,padding=p,dilation=d)
        s.b2 = nn.BatchNorm1d(no)
        s.dr = nn.Dropout(dr)
        s.ds = nn.Conv1d(ni,no,1) if ni!=no else None
    def forward(s, x):
        o = s.dr(torch.relu(s.b1(s.c1(x)[...,:x.size(2)])))
        o = s.dr(torch.relu(s.b2(s.c2(o)[...,:x.size(2)])))
        r = x if s.ds is None else s.ds(x)
        return torch.relu(o+r)

class TCN(nn.Module):
    def __init__(s, nf, chs, ks, ds, dr):
        super().__init__()
        ls, ic = [], nf
        for i,oc in enumerate(chs):
            ls.append(TemporalBlock(ic,oc,ks,ds[i] if i<len(ds) else ds[-1],dr))
            ic = oc
        s.net = nn.Sequential(*ls)
        s.fc = nn.Linear(chs[-1], 1)
    def forward(s, x):
        x = x.permute(0,2,1)
        return torch.sigmoid(s.fc(s.net(x)[:,:,-1]))

def build_seqs(df, feats, lb=LOOKBACK):
    X,y,D = [],[],[]
    for t,g in df.groupby('ticker'):
        g = g.sort_values('date')
        v = g[feats].fillna(0).values.astype(np.float32)
        la, da = g['label_long'].values, g['date'].values
        for i in range(lb, len(g)):
            X.append(v[i-lb:i]); y.append(la[i]); D.append(da[i])
    return np.array(X), np.array(y), np.array(D)

def train_tcn(X, y, D, nf):
    dates = sorted(set(D)); n = len(dates)
    results, best_st, best_ic = [], None, -999
    for fold in range(5):
        te = int(n*(0.6+fold*0.08))
        tt = min(int(n*(0.6+(fold+1)*0.08)),n)
        if te>=n: break
        trm = np.array([d in set(dates[:te]) for d in D])
        tsm = np.array([d in set(dates[te:tt]) for d in D])
        Xtr,ytr,Xts,yts = X[trm],y[trm],X[tsm],y[tsm]
        if len(Xtr)<1000 or len(Xts)<200: continue
        print(f"\n  Fold {fold+1}: tr={len(Xtr):,} ts={len(Xts):,}")
        dev = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        m = TCN(nf,CHANNELS,KERNEL_SIZE,DILATIONS,DROPOUT).to(dev)
        opt = torch.optim.Adam(m.parameters(), lr=LR)
        crit = nn.BCELoss()
        bl,pc,bs = float('inf'),0,None
        for ep in range(EPOCHS):
            m.train(); idx=np.random.permutation(len(Xtr)); el,nb=0,0
            for s in range(0,len(Xtr),BATCH_SIZE):
                bi=idx[s:s+BATCH_SIZE]
                xb=torch.tensor(Xtr[bi]).to(dev)
                yb=torch.tensor(ytr[bi],dtype=torch.float32).to(dev)
                opt.zero_grad(); p=m(xb).squeeze(); l=crit(p,yb); l.backward(); opt.step()
                el+=l.item(); nb+=1
            al=el/max(nb,1)
            if al<bl: bl=al;pc=0;bs={k:v.cpu().clone() for k,v in m.state_dict().items()}
            else: pc+=1
            if pc>=PATIENCE: print(f"    Stop ep {ep+1}"); break
            if (ep+1)%20==0: print(f"    Ep {ep+1} loss={al:.4f}")
        m.load_state_dict(bs); m.eval()
        with torch.no_grad():
            ps=[]
            for s in range(0,len(Xts),BATCH_SIZE):
                xb=torch.tensor(Xts[s:s+BATCH_SIZE]).to(dev)
                p=m(xb).squeeze().cpu().numpy()
                ps.extend(p if p.ndim>0 else [p.item()])
        ic,_=spearmanr(np.array(ps),yts)
        hr=np.mean((np.array(ps)>0.5)==yts)
        results.append({'fold':fold+1,'ic':ic,'hr':hr})
        print(f"    IC={ic:+.4f} HR={hr:.4f}")
        if ic>best_ic: best_ic=ic; best_st=bs
    mic=np.mean([r['ic'] for r in results])
    print(f"\n  TCN LONG Mean IC: {mic:+.4f} (current +0.105)")
    return best_st, results, mic

def train_lgbm(df, feats, lcol):
    import lightgbm as lgb
    dates=sorted(df['date'].unique()); n=len(dates); res=[]
    for fold in range(5):
        te=int(n*(0.6+fold*0.08)); tt=min(int(n*(0.6+(fold+1)*0.08)),n)
        if te>=n: break
        tr=df[df['date'].isin(dates[:te])]; ts=df[df['date'].isin(dates[te:tt])]
        if len(tr)<1000 or len(ts)<200: continue
        m=lgb.LGBMRegressor(n_estimators=500,learning_rate=0.05,num_leaves=31,feature_fraction=0.8,bagging_fraction=0.8,bagging_freq=5,min_child_samples=50,verbose=-1,random_state=42)
        m.fit(tr[feats].fillna(0),tr[lcol],eval_set=[(ts[feats].fillna(0),ts[lcol])],callbacks=[lgb.early_stopping(50,verbose=False)])
        p=m.predict(ts[feats].fillna(0)); ic,_=spearmanr(p,ts[lcol])
        res.append({'fold':fold+1,'ic':ic}); print(f"  LGBM Fold {fold+1}: IC={ic:+.4f}")
    mic=np.mean([r['ic'] for r in res]) if res else 0
    print(f"\n  LGBM LONG Mean IC: {mic:+.4f}")
    fm=lgb.LGBMRegressor(n_estimators=500,learning_rate=0.05,num_leaves=31,feature_fraction=0.8,bagging_fraction=0.8,bagging_freq=5,min_child_samples=50,verbose=-1,random_state=42)
    fm.fit(df[feats].fillna(0),df[lcol])
    imp=sorted(zip(feats,fm.feature_importances_),key=lambda x:x[1],reverse=True)
    print(f"\n  Top 10:"); [print(f"    {n:30s} {v:.0f}") for n,v in imp[:10]]
    return fm, res, mic

def main():
    t0=time.time()
    print("="*60); print("  MERIDIAN LONG — TCN + LGBM"); print("="*60)
    df,feats,lcol=load_data()
    print(f"\n{'='*60}\n  LGBM ({len(feats)} features)\n{'='*60}")
    lm,lr,lic=train_lgbm(df,feats,lcol)
    print(f"\n{'='*60}\n  TCN ({len(feats)} features)\n{'='*60}")
    X,y,D=build_seqs(df,feats)
    ts,tr,tic=train_tcn(X,y,D,len(feats))
    out=Path('/workspace/output'); out.mkdir(exist_ok=True)
    if ts: torch.save(ts,out/'model.pt')
    import joblib; joblib.dump(lm,out/'lgbm_long_v2.pkl')
    cfg={'type':'LONG_TCN_v2','features':feats,'n_features':len(feats),'lookback':LOOKBACK,
         'architecture':{'channels':CHANNELS,'kernel_size':KERNEL_SIZE,'dilations':DILATIONS,'dropout':DROPOUT},
         'labeling':{'method':'forward_return_proxy','threshold':LABEL_THRESHOLD},
         'etf_excluded':True,'rows':len(df),'tickers':int(df['ticker'].nunique()),
         'tcn_ic':tic,'lgbm_ic':lic,'tcn_results':tr,'lgbm_results':lr}
    (out/'config.json').write_text(json.dumps(cfg,indent=2,default=str))
    print(f"\n{'='*60}\n  RESULTS\n{'='*60}")
    print(f"  Current LONG TCN: +0.105 (ETF biased)")
    print(f"  New TCN:          {tic:+.4f}")
    print(f"  New LGBM:         {lic:+.4f}")
    print(f"  SHORT TCN (keep): +0.392")
    print(f"  Winner: {'TCN' if tic>lic else 'LGBM'}")
    print(f"  Time: {time.time()-t0:.0f}s")
    print(f"  Files: /workspace/output/")

if __name__=='__main__': main()
SCRIPT

python3 train_long.py 2>&1 | tee training_log.txt
```

## Download results to Mac
```bash
mkdir -p ~/SS/Meridian/models/tcn_long_v2
mkdir -p ~/SS/Meridian/models/lgbm_long_v2
scp root@<vast_ip>:/workspace/output/model.pt ~/SS/Meridian/models/tcn_long_v2/
scp root@<vast_ip>:/workspace/output/config.json ~/SS/Meridian/models/tcn_long_v2/
scp root@<vast_ip>:/workspace/output/lgbm_long_v2.pkl ~/SS/Meridian/models/lgbm_long_v2/
scp root@<vast_ip>:/workspace/training_log.txt ~/SS/Meridian/models/
```
