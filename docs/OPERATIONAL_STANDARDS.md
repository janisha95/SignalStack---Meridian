# Meridian — Operational Standards for All Scripts

**Every Meridian script MUST follow these operational standards.**
**Codex: Read this file before building ANY stage.**

---

## 1. Progress Logging

Every script must print progress to stdout with `flush=True` so output appears
immediately (not buffered). A user running the script in a terminal must ALWAYS
be able to tell if the script is running, stuck, or failed.

### Required log points:

**At startup:**
```python
print(f"[{STAGE_NAME}] Starting...", flush=True)
print(f"[{STAGE_NAME}] Input: {count} tickers", flush=True)
```

**During long operations (loops over tickers or batches):**
```python
# Every N items (N = 500 for tickers, 5 for batches)
if i % 500 == 0:
    print(f"[{STAGE_NAME}] Progress: {i}/{total} ({i*100//total}%)...", flush=True)
```

**At major milestones:**
```python
print(f"[{STAGE_NAME}] Filter applied: {removed} removed, {remaining} remaining", flush=True)
print(f"[{STAGE_NAME}] Module 1 complete: 18 factors computed", flush=True)
```

**At completion:**
```python
print(f"[{STAGE_NAME}] DONE: {summary_stats}", flush=True)
```

**On errors (don't just silently return NaN):**
```python
print(f"[{STAGE_NAME}] WARNING: {ticker} failed in M1: {error}", flush=True)
```

### Timing:
Every major step must be timed:
```python
import time
t0 = time.time()
# ... do work ...
elapsed = time.time() - t0
print(f"[{STAGE_NAME}] Step completed in {elapsed:.1f}s", flush=True)
```

---

## 2. Error Handling

### Per-ticker errors → NaN, not crash
If a factor computation fails for one ticker, set that factor to NaN and continue.
Do NOT crash the entire pipeline for one bad ticker.

```python
try:
    result = compute_something(df)
except Exception as e:
    print(f"[{STAGE_NAME}] WARNING: {ticker} failed: {e}", flush=True)
    result = float('nan')
```

### Per-module errors → NaN dict, not crash
If an entire module fails for a ticker, return NaN for all that module's factors.

```python
try:
    m1_factors = m1_technical_core.compute_factors(df, spy_df, vix, sector, universe_stats)
except Exception as e:
    print(f"[factor_engine] WARNING: M1 failed for {ticker}: {e}", flush=True)
    m1_factors = {name: float('nan') for name in M1_FACTOR_NAMES}
```

### Pipeline-level errors → abort with clear message
If a precondition fails (DB missing, validation failed), abort immediately with
a clear error message. Don't silently return empty results.

---

## 3. Debuggability

### Factor-level diagnostics
After computing all factors for all tickers, print a summary:
```python
print(f"[factor_engine] Factor NaN rates:", flush=True)
for factor_name in sorted(factor_names):
    nan_count = factor_matrix[factor_name].isna().sum()
    nan_pct = nan_count / len(factor_matrix) * 100
    if nan_pct > 5:  # only print factors with significant NaN
        print(f"  {factor_name}: {nan_pct:.1f}% NaN ({nan_count}/{len(factor_matrix)})", flush=True)
```

### Per-ticker factor dump (--debug flag)
Every script should support a `--debug TICKER` flag that prints all computed
values for a single ticker:
```bash
python3 stages/v2_factor_engine.py --debug AAPL
# Should print all 34 factor values for AAPL
```

### Factor registry validation
At startup, verify that every factor in `factor_registry.json` has a corresponding
computation in a module. Print warnings for orphaned registry entries.

---

## 4. Extensibility (Adding/Removing Factors)

### To add a new factor:
1. Add the computation to the appropriate module (m1-m5)
2. Add an entry to `config/factor_registry.json` with `"active": true`
3. The engine automatically picks it up
4. Next ML retrain includes the new factor

### To remove a factor:
1. Set `"active": false` in `config/factor_registry.json`
2. Engine skips it. No code changes needed.
3. Old models still work (they ignore missing columns)

### To debug a factor:
1. Use `--debug TICKER` to see the value for one ticker
2. Check NaN rate summary at the end of the run
3. If NaN rate > 30% for a factor, there's probably a bug in the computation

---

## 5. Performance

### Target runtimes:
- Stage 1 (Cache): < 15 minutes (full refresh), < 2 minutes (incremental)
- Stage 2 (Prefilter): < 60 seconds on 11k tickers
- Stage 3 (Factor Engine): < 5 minutes on 3k tickers
- Stage 4 (ML Scoring): < 2 minutes on 3k tickers

### Memory:
- Don't load all OHLCV into memory at once if not needed
- Use SQL aggregates for filtering (Stage 2)
- For Stage 3: pre-load all survivor OHLCV into a dict (3k × 500 bars = ~1.5GB, acceptable)

### Parallelism:
- Stage 3 uses ThreadPoolExecutor with configurable worker count (default 8)
- Each worker processes one ticker across all 5 modules

---

## 6. QA Report Generation

Every Codex build task MUST generate a `qa_report_stageX.md` covering:
1. Import audit (flag any S1/S8 references)
2. Test results (all tests with pass/fail)
3. Acceptance criteria checklist (PASS/FAIL/UNTESTED for each)
4. Code snippets for any concerning findings
5. Live validation output (--dry-run or real run)
