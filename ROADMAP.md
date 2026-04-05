# Meridian — Build Roadmap

## Timeline

| Week | Stage | Est. Days | Status |
|------|-------|-----------|--------|
| Week 1 (Mar 25-28) | Stage 1: Cache Pipeline | 2 | 🔨 Building |
| Week 1 (Mar 28-29) | Stage 2: Prefilter | 1 | ⬜ |
| Week 2 (Mar 31 - Apr 3) | Stage 3: Factor Engine (5 modules, 34 factors) | 3-4 | ⬜ |
| Week 2-3 (Apr 3-7) | Stage 4: ML Scoring (LightGBM + LSTM) | 3-4 | ⬜ |
| Week 3 (Apr 7) | Stage 5: Selection (residual alpha) | 0.5 | ⬜ |
| Week 3 (Apr 7-8) | Stage 6: Risk Filters (FTMO) | 1 | ⬜ |
| Week 3-4 (Apr 8-11) | Stage 7: Orchestrator + Output | 2 | ⬜ |
| Week 4+ | Shadow run alongside S1 | ongoing | ⬜ |

**Total estimated: ~13-15 days**

## Dependencies

```
Stage 1 (Cache) → standalone
Stage 2 (Prefilter) → Stage 1 DB output
Stage 3 (Factor Engine) → Stage 2 filtered universe
Stage 4 (ML Scoring) → Stage 3 factor matrix
Stage 5 (Selection) → Stage 4 ML predictions
Stage 6 (Risk Filters) → Stage 5 ranked picks
Stage 7 (Orchestrator) → wraps all stages
```

## Parallel Work

While Codex/Claude Code builds pipeline stages:
- S1 continues running production trades
- Forward tracker collects outcome data
- Scorer refines daily
- When Meridian is ready, shadow run alongside S1 for 1-2 weeks before cutover

## Key Decisions (Locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Factor count | 34 (trimmed from 52) | Redundancy removed. Each factor orthogonal. |
| ML models | LightGBM (0.6) + LSTM (0.4) ensemble | LightGBM for cross-sectional, LSTM for temporal |
| Prediction horizon | 5 trading days | Sweet spot for swing trading |
| Selection method | Residual alpha (beta-stripped) | Prevents mega-cap dominance |
| Risk framework | FTMO-constrained | 0.5-0.8% risk/trade, 8-10 max positions |
| Database | SQLite WAL (own DB) | No cross-stack sharing |
| Architecture | In-process, no HTTP | Single Python process + ThreadPoolExecutor |
| Project name | Meridian | Reference point for navigation |

## Spec Approval Process

1. Opus writes STAGE_X_SPEC.md with 4 blocks (Input/Output/Test/Fail)
2. Shan reviews
3. GPT peer-reviews for blind spots
4. Edits applied
5. Spec approved → build begins
6. Build validated against acceptance criteria
7. Stage marked complete → next spec written
