# Meridian UI Integration Plan

## 1. Files reviewed
- `/Users/sjani008/SS/Meridian/AGENTS.md`
- `/Users/sjani008/SS/Meridian/README.md`
- `/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_STATE.md`
- `/Users/sjani008/SS/Meridian/docs/STAGE_5_COMPLETE_SPEC.md`
- `/Users/sjani008/SS/Meridian/docs/meridian_architecture_system_doc.md`
- `/Users/sjani008/SS/Meridian/docs/codebase_reference.md`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/README.md`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/layout.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/candidates/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/model/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/settings/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/trades/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/dashboard-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidates-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/model-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/settings-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/trades-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidate-detail-panel.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/ticker-info-card.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/tradingview-chart.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/mock-data.ts`
- `/Users/sjani008/SS/Advance/mobile_v2.html`
- `/Users/sjani008/SS/Advance/SS1mobile.html`
- `/Users/sjani008/SS/Advance/s1_intelligence_v2.html`
- `/Users/sjani008/SS/Advance/s1_intel_panel.html`
- `/Users/sjani008/SS/Advance/s1_ops_console.html`
- `/Users/sjani008/SS/Advance/ml_workbench.html`
- `/Users/sjani008/SS/Advance/ai_lab.html`
- `/Users/sjani008/SS/Advance/s1_strategy_lab.html`

Note:
- `/Users/sjani008/SS/Advance/signalstack_mobile_v2.html` was not present.
- `/Users/sjani008/SS/Advance/mobile_v2.html` is the practical mobile smart-view source that matches the requested concept.

## 2. Current Meridian React app state
### Strengths
- The app is already a real multi-page operator shell, not a one-page prototype.
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx` provides a reusable frame with sidebar, mobile tab bar, header, API status banner, and live NY clock.
- Current route split is clean enough to expand:
  - `/` dashboard
  - `/candidates`
  - `/trades`
  - `/model`
  - `/settings`
- Data access is centralized in `/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts`, which is the best current seam for shell-level integration.
- The current app already has the right class of operator surfaces:
  - dashboard summary
  - candidate table
  - model / tracking page
  - trade log
  - settings / diagnostics
- Existing components like `candidate-detail-panel`, `ticker-info-card`, and `tradingview-chart` are reusable primitives for a richer shell.

### Weaknesses
- The app is Meridian-specific in naming, route semantics, and data contracts.
- `lib/api.ts` assumes one backend and one candidate shape. It is not lane-aware.
- The current nav labels are narrow:
  - `Dash`
  - `Cands`
  - `Trades`
  - `Model`
  - `Set`
- `/candidates` is a single Meridian shortlist view, not a multi-source smart-views workspace.
- `/model` mixes model health, factor display, and tracking summary in one page but does not yet behave like a product-level Model Lab.
- `adaptPortfolioState()` still exposes challenge-style language and FTMO-shaped assumptions, which is too Meridian/TTP-specific for a unified shell.
- Several API adapters still degrade to demo mode or placeholder behavior rather than lane-specific unavailable states.

### Constraints
- The current API layer is built around Meridian endpoints on port `8080` and a single `API_BASE`.
- The current frontend types in `/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/mock-data.ts` encode Meridian-specific concepts such as `factorRank`, `tcnScore`, `predictedReturn`, `residualAlpha`, and challenge portfolio metrics.
- The shell is client-fetch heavy. There is not yet a normalized server-side aggregation layer for cross-repo views.
- The current app assumes one source of truth for candidates. The target shell needs at least three product lanes:
  - Meridian daily lane
  - S1 daily smart-view lane
  - Vanguard intraday lane

## 3. S1 mobile / smart-view audit
### Views worth preserving
- From `/Users/sjani008/SS/Advance/mobile_v2.html`:
  - `Smart Views`
  - `Market Context`
  - `Strategy Distribution`
  - `Sector Heat`
  - `Volume Anomalies`
  - `Convergence Picks`
  - `Intelligence Brief`
  - `Historical Performance`
  - `Regime × Strategy`
  - the overall idea of one operator shell spanning results, intelligence, status, and trading
- From `/Users/sjani008/SS/Advance/SS1mobile.html`:
  - `Today's Gate`
  - `PASS Rows`
  - `Gate Breakdown`
  - `Forward Tracking`
- From `/Users/sjani008/SS/Advance/s1_intel_panel.html`:
  - compact regime / status summary strip
  - ML gate status and alerts as small high-signal cards
- From `/Users/sjani008/SS/Advance/s1_ops_console.html`:
  - `Services`
  - `Trading Connections`
  - `Databases`
  - `Pipeline Jobs`
- From `/Users/sjani008/SS/Advance/ml_workbench.html`, `/Users/sjani008/SS/Advance/ai_lab.html`, and `/Users/sjani008/SS/Advance/s1_strategy_lab.html`:
  - `Replay / Backtest`
  - `Regime / Intelligence`
  - `League Cycles`
  - `League Scorecard`

### Views to retire
- The literal mobile tab shell in `mobile_v2.html` should be retired as a layout model. The React app already has a better shell.
- The old pipeline-run controls from the mobile HTML should not be copied as first-class product UX.
- Gate configurator and threshold tuning widgets from old status pages should not be carried into the main operator shell as default surfaces.
- The duplicated lab surfaces in `ml_workbench.html`, `ai_lab.html`, and `s1_strategy_lab.html` should not survive as separate concepts.
- Old S1 gate-specific wording should not dominate the top-level product structure.

### Views to redesign in React
- Smart views should become filterable React tables/cards, not imperative chip buttons tied to bespoke HTML rendering.
- `PASS Rows`, `Gate Breakdown`, and `Forward Tracking` should become reusable widgets inside `Daily Candidates` and `Forward Tracking`, not one isolated mobile page.
- `Market Context`, `Sector Heat`, `Volume Anomalies`, and `Intelligence Brief` should become shared widgets used on both `Home` and `Daily Candidates`.
- `Services`, `Databases`, and `Pipeline Jobs` should become a canonical `System Health` page built from shared health cards and job tables.
- `Replay / Backtest`, `League Cycles`, and `League Scorecard` should become the backbone of `Model Lab`, not raw HTML clones.

## 4. Proposed unified app structure
### Home
- Purpose:
  - one operator-facing overview page
  - answer “what matters now?” across all lanes
- Content:
  - global header strip with market regime, API status, data freshness, and open alerts
  - lane summary cards:
    - Daily Candidates summary
    - Intraday Candidates summary
    - Forward Tracking snapshot
    - System Health snapshot
  - “Today’s attention” smart list:
    - top merged daily ideas
    - top Vanguard intraday alerts
    - unresolved forward-tracker anomalies
  - compact intelligence brief
- This page should borrow the spirit of `s1_intel_panel.html` plus the stat-card utility of the current Meridian dashboard.

### Daily Candidates
- Purpose:
  - unified daily decision surface
  - merged S1 + Meridian smart views driven by validated thresholds
- This should be the heaviest and most important page in the shell.
- It should replace the current single Meridian `/candidates` view.

### Intraday Candidates
- Purpose:
  - Vanguard-native execution and review surface
  - clearly distinct from daily-signal ranking
- Daily signals should appear here only as enrichment and context, never as direct auto-promotion.

### Forward Tracking
- Purpose:
  - canonical cross-lane outcome/tracking page
  - one place for sleeve stats, validation buckets, pending resolution counts, and resolved performance
- This page should absorb concepts now split across Meridian model tracking and old S1 forward-tracking surfaces.

### Reports
- Purpose:
  - human-readable outputs
  - evening reports, morning reports, intelligence summaries, convergence summaries, and generated briefs
- This should centralize what is currently scattered across Telegram-oriented artifacts and HTML intel views.

### System Health
- Purpose:
  - operational diagnostics for all lanes
- Should take strong cues from `s1_ops_console.html`.

### Model Lab
- Purpose:
  - research, backtest, scorecards, league views, model comparisons
- This should evolve from the current Meridian `/model` route plus the old S1 workbench/lab concepts.

## 5. Daily Candidates page design
### Proposed smart tables/cards
- `Merged Daily Smart Views`
  - top-level smart-view switcher replacing old `Smart Views` chips
  - views such as:
    - Best Daily
    - Cross-Confirmed
    - Short Advisory
    - High Conviction
    - Watchlist / Borderline
- `S1 Daily Smart Table`
  - curated S1 smart-view rows
  - includes scorer/gate/convergence style context where applicable
- `Meridian Daily Table`
  - current Meridian shortlist in richer form
  - uses existing candidate-detail patterns
- `Cross-System Confirmation Table`
  - names where S1 and Meridian align on direction / strength
  - this is the highest-value merged table
- `Short Opportunities Table`
  - merged short advisory / short-opportunity surface
  - conceptually inherits from old S1 `short_opps`
- `Market Context / Sector Heat Block`
  - compact context cards and sector distribution visuals
- `Intelligence Brief / Notes Block`
  - daily narrative summary, anomalies, and why the shortlist looks the way it does

### S1 sections
- S1 Smart Views / validated shortlist buckets
- S1 gate/scorer-style confidence or advisory context where still relevant
- S1 forward-tracker-backed bucket labels
- S1 short advisory surface

### Meridian sections
- Meridian shortlist table
- candidate detail drawer with:
  - factor rank
  - TCN score
  - expected return / residual alpha
  - regime / beta / sector
- Meridian-specific diagnostics should live in the detail drawer, not dominate the merged page

### Cross-system / merged sections
- Best Daily
  - merged, operator-ranked table
- Cross-Confirmed
  - S1 and Meridian aligned names
- Divergence / Watchlist
  - where one lane is strong and the other is absent or skeptical
- Short Advisory
  - short ideas worth monitoring, not auto-promoting to Vanguard

## 6. Intraday Candidates page design
### Vanguard-native sections
- `Intraday Candidate Grid`
  - real-time Vanguard engine output
  - primary operator table for entries/exits and execution readiness
- `Execution Readiness Panel`
  - account, buying power, risk caps, lane status
- `Orders / Positions / Alerts`
  - inherited conceptually from old mobile Trading tab and current Meridian trades page
- `Live Health Strip`
  - broker/API/data freshness status relevant to intraday execution

### Daily-signal enrichment sections
- `Daily Context Tags`
  - whether a Vanguard ticker also appears in S1 or Meridian daily views
- `Daily Bias / Conflict Panel`
  - show if daily systems agree, disagree, or are silent
- `Forward Validation Hints`
  - forward-tracker-backed notes like “daily long validated bucket” or “short bucket weak”
- These are enrichment-only. They should never appear visually as direct trade authorization.

### Operator workflow
- Intraday should feel execution-first, not research-first.
- Workflow:
  - review live Vanguard candidates
  - sort/filter by execution readiness and intraday score
  - inspect ticker detail drawer
  - see daily enrichment context
  - decide manual action
- This differs from Daily Candidates, which should feel curation-first and validation-first.

## 7. Shared component plan
### Reusable cards
- `MetricStrip`
  - compact summary chips for counts, win rates, pending/resolved, freshness
- `StatusCard`
  - service/database/job/broker health
- `ContextCard`
  - market regime, breadth, long/short ratio, volatility, sector signal
- `LaneSummaryCard`
  - one card per lane on Home / Health / Reports

### Tables
- `SmartCandidateTable`
  - normalized table used by Daily and Intraday with lane-specific columns toggled on/off
- `ForwardTrackerTable`
  - pending/resolved/outcome table
- `JobStatusTable`
  - pipeline job health and timestamps
- `ModelScorecardTable`
  - for Model Lab and Reports

### Filters
- `SmartViewTabs`
  - React replacement for old smart-view chips
- `LaneFilter`
  - S1 / Meridian / Vanguard / merged
- `DirectionFilter`
  - Long / Short / Both
- `ConfidenceFilter`
  - validated bucket / score range / confirmation status
- `UniverseFilter`
  - daily vs intraday vs tracked-only

### Detail drawers / ticker panels
- `TickerDetailDrawer`
  - canonical expandable drawer for both Daily and Intraday
- reuse ideas from:
  - `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidate-detail-panel.tsx`
  - `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/ticker-info-card.tsx`
  - `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/tradingview-chart.tsx`
- Detail drawer sections:
  - summary header
  - lane scores
  - daily context
  - forward-tracker history
  - health / risk notes

### Report widgets
- `BriefCard`
  - daily intelligence brief
- `ReportList`
  - list of generated reports
- `ReportPreview`
  - compact rendered report summary
- `ScoreBreakdownCard`
  - lane/component contribution view for model/report pages

### Health widgets
- `ServiceGrid`
  - from old S1 ops-console concepts
- `DatabaseFreshnessCard`
  - cache status and freshness
- `JobTimelineCard`
  - recent orchestrator / pipeline activity
- `AlertFeed`
  - warnings, failures, stale feeds, missing models

## 8. Route / page map
- `/`
  - Home
- `/daily`
  - Daily Candidates
- `/intraday`
  - Intraday Candidates
- `/tracking`
  - Forward Tracking
- `/reports`
  - Reports
- `/health`
  - System Health
- `/lab`
  - Model Lab

Recommended secondary route groups:
- `/daily/[ticker]` or drawer-based routing for ticker detail
- `/reports/[id]` for full report view
- `/lab/replay`
- `/lab/scorecards`
- `/lab/compare`

Mapping from current Meridian routes:
- current `/` becomes new `Home`
- current `/candidates` should be replaced by `/daily`
- current `/trades` is the best base for `/intraday`
- current `/model` is the best base for `/lab` and parts of `/tracking`
- current `/settings` should be absorbed into `/health` or a subordinate settings pane later

## 9. Data flow / contract implications
- The current `lib/api.ts` is too Meridian-specific for the target shell.
- Required shift:
  - from one global Meridian API contract
  - to either lane-aware adapters or a normalized shell contract
- Minimum contract split needed:
  - `dailyCandidates`
    - merged + per-lane buckets
  - `intradayCandidates`
    - Vanguard-native rows
  - `forwardTracking`
    - lane-aware but normalized tracking rows
  - `reports`
    - list + content metadata
  - `systemHealth`
    - service/db/job/broker status
  - `modelLab`
    - scorecards, experiments, backtests

Specific Meridian assumptions that need relaxing:
- Candidate rows should not require Meridian-only fields like `factorRank` and `tcnScore` to exist universally.
- Portfolio state should not assume challenge/eval semantics as the top-level shell contract.
- The shell should not assume one backend URL forever.
- The UI should distinguish:
  - lane data unavailable
  - lane disabled
  - demo mode
  - real data
- Daily and intraday routes should own their state separately.
- Shared shell state should be limited to:
  - active lane filters
  - health summary
  - selected ticker context

Recommended state ownership:
- page-local data fetching for each top-level route
- shared shell provider only for:
  - health banner
  - selected global date/session
  - selected ticker drawer state
  - lane availability

## 10. Recommended implementation order
1. Expand the Meridian shell routing and navigation.
   - Add the new top-level route map and rename the current Meridian pages into their future roles.

2. Normalize the API adapter surface.
   - Split `lib/api.ts` into lane-aware or domain-aware adapters without changing backend logic yet.
   - This is the main prerequisite for multi-lane integration.

3. Build `Home` and `System Health`.
   - These are the lowest-risk pages because they mostly aggregate existing summary/status surfaces.
   - Reuse current dashboard and settings ideas plus old S1 intel/status concepts.

4. Build `Daily Candidates`.
   - Start with:
     - Meridian table
     - S1 smart-view table
     - merged cross-confirmed table
   - Then add context cards and intelligence brief widgets.

5. Build `Forward Tracking`.
   - Unify Meridian tracking summary concepts with S1 forward-tracking concepts into one page.

6. Build `Reports`.
   - Centralize daily/evening/morning/intelligence outputs in one route.

7. Build `Intraday Candidates`.
   - Add Vanguard-native execution-first page after the shell and daily lane are stable.
   - Wire daily enrichment as secondary context only.

8. Build `Model Lab`.
   - Merge the current Meridian model page with selected S1 workbench concepts.
   - Keep this last because it is broad and easiest to overbuild early.

Bottom-line recommendation:
- Meridian is the right base shell because it already has the cleanest React app and app-shell structure.
- Do not copy old S1 mobile HTML literally.
- Carry over the S1 smart-view concepts as:
  - reusable cards
  - smart tables
  - context widgets
  - health widgets
- Use the Meridian React app as the canonical shell, but relax its current one-backend, one-lane, Meridian-only assumptions before merging S1 and Vanguard into it.
