# Meridian SignalStack Integration Master Plan

## 1. Files reviewed
- [/Users/sjani008/SS/Meridian/MERIDIAN_REPO_AUDIT.md](/Users/sjani008/SS/Meridian/MERIDIAN_REPO_AUDIT.md)
- [/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_UI_FIT_ANALYSIS.md](/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_UI_FIT_ANALYSIS.md)
- [/Users/sjani008/SS/Meridian/UNIFIED_CANDIDATE_SOURCE_INVESTIGATION.md](/Users/sjani008/SS/Meridian/UNIFIED_CANDIDATE_SOURCE_INVESTIGATION.md)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/layout.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/layout.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/candidates/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/candidates/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/trades/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/trades/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/model/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/model/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/dashboard-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/dashboard-client.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidates-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidates-client.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidate-detail-panel.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidate-detail-panel.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/trades-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/trades-client.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts](/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts)
- [/Users/sjani008/SS/Advance/mobile_v2.html](/Users/sjani008/SS/Advance/mobile_v2.html)
- [/Users/sjani008/SS/Advance/SS1mobile.html](/Users/sjani008/SS/Advance/SS1mobile.html)
- [/Users/sjani008/SS/Advance/s1_intelligence_v2.html](/Users/sjani008/SS/Advance/s1_intelligence_v2.html)
- [/Users/sjani008/SS/Advance/s1_intel_panel.html](/Users/sjani008/SS/Advance/s1_intel_panel.html)
- [/Users/sjani008/SS/Advance/s1_ops_console.html](/Users/sjani008/SS/Advance/s1_ops_console.html)

## 2. Current UI/layout constraints
- The current Meridian shell is already a coherent product shell. [`AppShell`](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx) provides the desktop sidebar, mobile bottom nav, page title area, NY clock, and API-status banner. That should stay.
- The current top-level route set is compact and usable:
  - `/`
  - `/candidates`
  - `/trades`
  - `/model`
  - `/settings`
- `/candidates` is the strongest integration point because it already functions as a ranked-candidate workspace with:
  - side toggle
  - sortable table
  - candidate detail drawer
  - score-centric columns
- `/trades` already exists, but today it is a simple Meridian trade-log page. It is the least disruptive place to grow a unified trade page.
- `/model` already hosts tracking/validation surfaces and is the natural place for cross-system forward-tracker and threshold-validation visibility later.
- Current React state is page-local. There is no global cross-page store. That makes a `/candidates`-local Userviews MVP feasible without first redesigning the entire app state layer.
- [`lib/api.ts`](/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts) is currently Meridian-specific and assumes one backend plus one candidate shape. That is the main technical constraint for S1 integration.
- The current candidate/detail UI assumes Meridian fields like `finalScore`, `factorRank`, `tcnScore`, `predictedReturn`, and `beta`. S1 can fit, but only if lane-specific score semantics are carried as metadata instead of being forced into Meridian’s numeric slots.
- The current shell does not justify a new top-level `Views` route yet. The best fit remains inside `/candidates`.

## 3. S1-first integration strategy
- Integrate S1 into the existing `/candidates` workspace first, not as a separate top-level page.
- Use the already-established real S1 candidate surfaces:
  - `signalstack_results.db.scorer_predictions`
  - latest convergence JSON
- Treat S1 as a second daily-candidate lane, not as a Meridian subtype.
- The first integration should be source-aware:
  - `Meridian`
  - `S1`
  - `Combined`
- `Combined` should not pretend there is a cross-lane comparable numeric rank. It should be a curated merged table where:
  - source is explicit
  - lane-native scores remain visible
  - sorting defaults are source-aware or operator-selected
- Initial S1 integration should focus on read-layer normalization and display, not on changing Meridian’s shell or navigation.
- The initial UI should preserve Meridian’s current workflow:
  - enter `/candidates`
  - inspect ranked rows
  - open right-side detail drawer
- S1-specific smart-view concepts from the old mobile stack should land as curated candidate views, intelligence slices, and operator table presets inside `/candidates`, not as a literal copied mobile experience.

## 4. Userviews architecture inside /candidates
### Operator workflow
- The operator enters `/candidates`.
- At the top of the page, they choose a source scope:
  - `Meridian`
  - `S1`
  - `Combined`
- They choose or load a saved Userview.
- They adjust:
  - direction scope
  - filters
  - sort
  - grouping
  - visible columns
  - display mode
- The current table region becomes the preview/results area.
- Clicking a row still opens the existing detail drawer.
- A saved view stores configuration only. It does not duplicate the candidate data itself.

### Layout placement
- Keep the current `/candidates` page scaffold and table-first layout.
- Replace or expand the current simple `LONG / SHORT` control row with a richer workspace header containing:
  - source selector
  - view selector
  - direction control
  - optional filter/sort/group controls
- Keep the current large results table in the main body.
- Keep the current detail drawer as the right-side inspection surface.
- Do not create a new full-screen views builder page in the MVP.
- Do not move smart-view behavior into `/settings`.

### State/data flow
- MVP state should stay local to [`CandidatesClient`](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidates-client.tsx).
- That page-local state should expand from today’s:
  - `activeTab`
  - `sortKey`
  - `sortDir`
  - `activeCandidate`
- Into:
  - `sourceMode`
  - `selectedViewId`
  - `directionScope`
  - `filterState`
  - `sortState`
  - `groupState`
  - `visibleColumns`
  - `displayMode`
  - `activeCandidate`
- The backend/read layer should provide three raw row loaders:
  - Meridian shortlist loader
  - S1 scorer loader
  - S1 convergence loader
- A client-side or API-side adapter can then build:
  - pure Meridian rows
  - pure S1 rows
  - combined rows with explicit `source` and lane-specific metadata
- The detail drawer should receive a normalized core candidate row plus raw source-specific metadata.

### Saved view model
- Saved views should be source-aware and configuration-driven.
- Minimum saved-view shape:
  - `id`
  - `name`
  - `source_mode` (`meridian`, `s1`, `combined`)
  - `direction_scope`
  - `filters`
  - `sort`
  - `group_by`
  - `visible_columns`
  - `display_mode`
- Early saved views should likely be simple JSON-backed app objects, not a full complex query system.
- The saved view should not store computed candidate ranks or snapshot data in MVP.

### MVP scope
- Source-aware view selection inside `/candidates`
- Load `Meridian`, `S1`, and `Combined`
- Configurable:
  - sort
  - filter
  - grouping
  - visible columns
  - display mode
- Save/load a small set of named views
- Reuse the existing table and detail drawer
- No advanced query DSL
- No top-level Views page
- No fake unified numeric `primary_score`

## 5. Unified trade page plan
### Existing sources
- Meridian today has a true trade-log source:
  - `/api/trades/log`
  - backed by Meridian trade log tables exposed through [`getTradeLog()`](/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts)
- Meridian also has position-style sources:
  - `/api/positions`
  - approved/active trade surfaces downstream of selection/risk/orchestrator
- S1 does not present a clean execution-trade page today in the React shell, but it does have trade-adjacent persisted surfaces:
  - forward-tracker candidate rows
  - tracker outcomes
  - standings / reports
  - scored picks that may have been acted on
- Practically, S1 is closer to a tracked-idea / validated-signal lane than a fully symmetric execution log.

### Common fields
- A realistic shared trade/log core across S1 and Meridian is:
  - `source_system`
  - `asof_date`
  - `ticker`
  - `direction`
  - `status`
  - `entry_reference`
  - `exit_reference`
  - `pnl`
  - `pnl_pct`
  - `signal_label`
  - `notes`
- Meridian can usually fill actual trade-like fields.
- S1 may often only fill signal-tracking or outcome-tracking versions of those fields.
- That means the unified trade page should not promise full execution symmetry.

### UI structure
- Extend the current `/trades` page rather than creating a new top-level route.
- The page should evolve into a unified trade/track workspace with:
  - source filter (`All`, `Meridian`, `S1`)
  - status filter
  - main log table
  - optional source-specific detail row or drawer
- Likely page sections:
  - `Open / Active`
  - `Closed / Resolved`
  - `Tracked Ideas / Signal Outcomes`
- Keep one main table surface, then allow source-specific detail panels beneath or beside it.

### Risks / gaps
- Meridian is actual trade-log oriented; S1 is forward-tracker oriented.
- Some fields will be absent or synthetic on the S1 side.
- If the page pretends all rows are identical “trades,” it will mislead operators.
- The unified trade page should therefore be source-aware, with clear labels like:
  - `Trade`
  - `Tracked Pick`
  - `Resolved Signal`

## 6. Read-layer / backend implications
- The current [`lib/api.ts`](/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts) is too Meridian-specific for the unified shell.
- The least disruptive next step is not a shell redesign. It is a read-layer seam that can fetch and adapt multiple candidate sources.
- Needed read-layer capabilities:
  - Meridian candidates from `shortlist_daily`
  - S1 candidates from `scorer_predictions`
  - S1 convergence from latest convergence artifact or a mirrored API/db surface
  - Meridian trade log and positions
  - S1 forward-tracker / signal-outcome rows for the trades page
- The normalized core contract should stay narrow and honest:
  - source
  - ticker
  - direction
  - date / batch context
  - status
  - price-ish fields
  - regime / sector where available
  - metadata references
- Lane-native score families should remain lane-specific:
  - S1 `scorer_prob`, `convergence_score`, `p_tp`, `nn_p_tp`
  - Meridian `final_score`, `tcn_score`, `factor_rank`, `predicted_return`, `residual_alpha`
- Those should either render as source-aware table columns or live in metadata/detail drawers.
- One single fake cross-lane `primary_score` should not be introduced.
- The backend/read layer must also support saved Userview queries:
  - source-aware filtering
  - lane-aware sorts
  - lane-aware grouping

## 7. Vanguard later-fit plan
- Vanguard should be planned now but not implemented in the shell yet.
- Current audits show Vanguard is not ready for candidate normalization:
  - no native candidate shortlist table
  - no stable intraday candidate contract
  - execution/health artifacts exist, but not a candidate-ready lane surface
- The shell should therefore reserve fit assumptions only:
  - future `Intraday Candidates` section
  - future source mode or route for Vanguard-native rows
  - future enrichment from Daily Candidates as non-promoting context
- The correct product truth remains:
  - daily signals from S1 and Meridian can enrich Vanguard later
  - they are not automatic promotions
- Vanguard should be integrated only after it has:
  - native candidate output
  - stable session/run identifiers
  - stable score semantics
  - a normalized read surface

## 8. Phased implementation plan
### Phase 0
- Scope:
  - preserve the existing Meridian shell
  - define non-breaking read-layer seams
  - lock down candidate/trade source contracts
  - avoid changing top-level navigation
- Touched areas:
  - read adapters
  - type contracts
  - source-aware API abstractions
- Risks:
  - accidental Meridian regression if existing consumers are forced to adopt normalized shapes too early
- Acceptance criteria:
  - current Meridian pages still work unchanged
  - S1 read contracts are documented and accessible
  - no fake cross-lane score introduced

### Phase 1
- Scope:
  - integrate S1 into `/candidates`
  - add source-aware mode:
    - `Meridian`
    - `S1`
    - `Combined`
  - keep current shell and table-first workflow
- Touched areas:
  - `/candidates`
  - candidate adapters
  - detail drawer metadata handling
- Risks:
  - overfitting S1 rows into Meridian-only columns
  - confusion if Combined mode tries to over-normalize ranking
- Acceptance criteria:
  - `/candidates` can display S1 rows, Meridian rows, and combined rows
  - source is explicit
  - lane-native score columns remain honest
  - detail drawer can show S1 metadata without breaking Meridian rows

### Phase 2
- Scope:
  - add Userviews MVP inside `/candidates`
  - configurable:
    - filters
    - sort
    - grouping
    - visible columns
    - display mode
    - saved views
- Touched areas:
  - `CandidatesClient`
  - candidate workspace controls
  - saved-view storage/read layer
- Risks:
  - too much state complexity inside one component
  - saved views becoming tied to unstable backend field names
- Acceptance criteria:
  - operator can create and save source-aware views
  - preview/results remain inside the current table workspace
  - no new top-level Views page

### Phase 3
- Scope:
  - extend `/trades` into a unified trade/track page for S1 + Meridian
  - add source-aware filters and source-specific row handling
- Touched areas:
  - `/trades`
  - trade-log adapters
  - possibly detail drawers or row expanders
- Risks:
  - S1 rows being misrepresented as true execution trades
  - uneven field completeness between sources
- Acceptance criteria:
  - `/trades` can show Meridian trades and S1 tracked/resolved signal rows together
  - source differences are visible
  - shared fields are consistent

### Phase 4
- Scope:
  - spec and fit Vanguard into the shell once it has a real candidate source
- Touched areas:
  - future intraday route or future source mode
  - future backend read adapters
- Risks:
  - integrating Vanguard before it has a native candidate contract
- Acceptance criteria:
  - Vanguard has a real candidate-producing surface
  - its rows can enter the shell without fake normalization

## 9. Acceptance criteria by phase
- Phase 0:
  - no Meridian UI regressions
  - documented, source-aware read contracts for S1 and Meridian
  - clear separation of normalized core fields vs lane-specific metadata
- Phase 1:
  - S1 data is visible inside the existing `/candidates` workspace
  - Combined mode works without inventing fake score comparability
  - existing detail drawer still works for both lanes
- Phase 2:
  - operators can save/load configurable Userviews
  - filters, sorts, grouping, columns, and display mode are configurable
  - Userviews stay inside `/candidates`
- Phase 3:
  - `/trades` shows both systems with explicit source labels
  - common trade/log fields are coherent
  - source-specific gaps are surfaced rather than hidden
- Phase 4:
  - Vanguard enters only after its own candidate surface is real and stable
  - no placeholder intraday lane is exposed prematurely

## 10. Recommended safest implementation order
1. Phase 0: non-breaking read-layer seams and contract hardening
2. Phase 1: S1 inside `/candidates`
3. Phase 2: Userviews MVP inside `/candidates`
4. Phase 3: unified `/trades` extension for S1 + Meridian
5. Phase 4: Vanguard later, only after native candidate readiness

This is the safest order because it preserves the current Meridian shell, adds S1 where the current UI already has the right ranked-table workspace, postpones higher-state UX complexity until candidate sources are stable, and avoids forcing Vanguard into the shell before its own candidate layer is real.
