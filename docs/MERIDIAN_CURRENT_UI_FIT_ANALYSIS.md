# Meridian Current UI Fit Analysis

## 1. Files reviewed
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/layout.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/candidates/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/model/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/trades/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/app/settings/page.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/dashboard-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidates-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidate-detail-panel.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/model-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/trades-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/settings-client.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/ticker-info-card.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/components/tradingview-chart.tsx`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts`
- `/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/mock-data.ts`
- `/Users/sjani008/SS/Meridian/AGENTS.md`
- `/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_STATE.md`
- `/Users/sjani008/SS/Advance/mobile_v2.html`
- `/Users/sjani008/SS/Advance/SS1mobile.html`
- `/Users/sjani008/SS/Advance/s1_intelligence_v2.html`
- `/Users/sjani008/SS/Advance/s1_intel_panel.html`
- `/Users/sjani008/SS/Advance/s1_ops_console.html`

Note:
- `/Users/sjani008/SS/Advance/signalstack_mobile_v2.html` was not present.
- `/Users/sjani008/SS/Advance/mobile_v2.html` is the actual mobile smart-view file that matches the requested concept.

## 2. Current React app structure

Current routes/pages:
- `/`
  - `DashboardClient`
- `/candidates`
  - `CandidatesClient`
- `/trades`
  - `TradesClient`
- `/model`
  - `ModelClient`
- `/settings`
  - `SettingsClient`

Current major component model:
- `AppShell`
  - shared layout frame
  - desktop sidebar
  - mobile bottom nav
  - top bar
  - API status banner
- `DashboardClient`
  - overview page
  - top-long / top-short candidate cards
  - selected-pick sizing block
  - portfolio summary
  - trade-log summary
- `CandidatesClient`
  - full shortlist table
  - LONG / SHORT toggle
  - sortable columns
  - opens detail panel
- `CandidateDetailPanel`
  - right-side slide-over drawer
  - diagnostics + TradingView + ticker info + top factors
- `ModelClient`
  - model health cards
  - forward-tracking widgets
  - P&L curve
  - factor sample list
- `TradesClient`
  - plain trade log table
- `SettingsClient`
  - read-only settings / toggles / environment info

Current data-fetching pattern:
- all page clients fetch on mount with `useEffect`
- no shared query cache layer
- no server components doing data aggregation
- no Redux / Zustand / context store for page data
- only cross-page shared state mechanism is API runtime status subscription from `lib/api.ts`

Current state management:
- local `useState` + `useMemo` in each page component
- `AppShell` keeps:
  - current time
  - challenge label from `getPortfolioState()`
  - API banner state via `subscribeApiStatus`
- page-level state is isolated

Current page purposes:
- dashboard = operator overview for current Meridian lane
- candidates = canonical candidate inspection page
- trades = basic trade-history page
- model = model/forward-tracking page
- settings = environment/settings diagnostics page

## 3. Current layout and navigation model

The current UI is a classic operator shell with one global frame and five top-level destinations.

Navigation:
- desktop:
  - fixed narrow left sidebar
  - icon + short label nav items
- mobile:
  - fixed 5-item bottom nav

Current nav items in code:
- `Dash`
- `Cands`
- `Trades`
- `Model`
- `Set`

Top bar:
- product title `SignalStack`
- active challenge label
- current page title
- NY time clock
- avatar/brand block

Banner model:
- top-of-shell connectivity banner
- can show:
  - API offline
  - demo mode

Layout behavior:
- shell is stable and reusable
- pages are full-page surfaces inside one content column
- there is no secondary tab bar inside the shell today
- the only overlay pattern is the candidate detail slide-over

This matters for S1 fit:
- the app is already designed around top-level pages, not dense nested workspaces
- adding S1 should prefer page reuse and intra-page sections before inventing a second shell model

## 4. Current major UI surfaces

### Dashboard
What exists:
- top metrics strip:
  - balance
  - today P&L
  - open positions
  - distance to target
  - win rate
- top long candidates card
- top short candidates card
- selection/sizing workflow
- trade activity / recent performance summaries

Why it matters:
- this page already behaves like a compact operator overview
- it is the most natural place for S1 overview summaries without disrupting route structure

### Candidates
What exists:
- two-state LONG / SHORT switch
- one large sortable table
- columns:
  - rank
  - ticker
  - direction
  - price
  - exp return
  - residual alpha
  - TCN
  - final
  - factor rank
  - beta
  - regime
  - sector
- footer status strip
- clicking a row opens the detail panel

Why it matters:
- this is the strongest existing fit point for S1 smart views
- it already supports dense ranked-table inspection
- it is currently single-source Meridian only

### Candidate detail panel
What exists:
- right-side slide-over panel
- diagnostic grid
- TradingView chart
- ticker info card
- top factors block
- quick external links

Why it matters:
- this is the existing pattern for “tell me more about one ticker”
- if S1 gets integrated, this is the least disruptive place to add S1 lane metadata

### Model page
What exists:
- model health cards
- forward-tracking summary
- cumulative P&L curve
- by-direction breakdown
- by-TCN-bucket breakdown
- factor sample list

Why it matters:
- this page already contains tracking/reporting semantics, not just raw model data
- it can absorb S1-related tracking/report concepts with less layout disruption than the candidates page

### Trades page
What exists:
- one trade log table
- no richer execution workflow
- no positions / orders / alerts panels

Why it matters:
- it fits as a simple history page today
- it does not yet naturally represent the old S1 mobile “trading” tab or a future richer lane

### Settings page
What exists:
- read-only settings rows
- read-only execution toggles block
- mostly operational metadata

Why it matters:
- this is not a strong product surface
- it is a reasonable placeholder diagnostics page, but not where S1 candidate views should go

## 5. S1 smart-view concepts worth carrying over

From `mobile_v2.html`, the concepts worth carrying over are:
- `Smart Views`
- `Market Context`
- `Strategy Distribution`
- `Sector Heat`
- `Volume Anomalies`
- `Convergence Picks`
- `Intelligence Brief`
- `Historical Performance`
- `Regime × Strategy`

From `SS1mobile.html`, the concepts worth carrying over are:
- `Today's Gate`
- `PASS Rows`
- `Gate Breakdown`
- `Forward Tracking`

From `s1_intel_panel.html`, the concepts worth carrying over are:
- compact regime/status strip
- small-card summary of gate / alerts / live state

From `s1_ops_console.html`, the concepts worth carrying over are:
- operational status blocks
- services / DBs / jobs as one diagnostics surface

Operator workflows worth preserving conceptually:
- quick scan of best picks by smart view
- quick scan of system/market context before reading picks
- review of gate/pass quality before trusting a lane
- review of forward-tracker summary before using a smart view

What matters conceptually, not literally:
- S1’s value is not the old HTML shell itself
- it is the curated smart-view layer over raw candidates

## 6. Best fit points in current UI for S1 integration

### Best fit: `/candidates`

Why:
- it is already the ranked-candidate workspace
- it already uses table-based browsing and a detail drawer
- the current LONG / SHORT toggle can host S1-derived views with minimal mental-model change

What S1 can fit into here with minimal disruption:
- additional smart-view sections above the existing table
- a source/view toggle that switches the table source:
  - Meridian shortlist
  - S1 smart views
  - merged curated view
- lane/source badges inside the existing row table
- extra S1 metrics in the existing detail drawer

What this means:
- the candidates page is the least disruptive home for S1 candidate integration
- a dedicated “Views” concept fits best as a section/filter mode within `Candidates`, not necessarily as a wholly separate shell page yet

### Good fit: `/`

Why:
- dashboard already has overview-card behavior
- S1 can fit as summary-level cards without forcing new top-level navigation immediately

What fits here:
- S1 smart-view summary cards
- top daily ideas summary
- market-context strip
- forward-validation summary snippet

### Good fit: `/model`

Why:
- it already mixes model and forward-tracking concerns
- S1 smart-view validation and tracking concepts can fit here without changing the page archetype

What fits here:
- S1 forward-tracker summary
- view-level validation buckets
- cross-lane tracking comparison later

### Weak fit: `/trades`

Why:
- current trades page is just a trade log
- old S1 smart views are candidate/intelligence concepts, not trade-history concepts

What could fit here with minimal change:
- almost nothing from S1 smart views directly
- if anything, only downstream “acted-on trades from S1 views,” but that is not the immediate integration point

### Weak fit: `/settings`

Why:
- current settings page is diagnostic/read-only
- not a natural home for S1 candidate surfaces

## 7. What should NOT be redesigned yet

- The global shell frame in `AppShell` should stay.
- The current sidebar + mobile bottom-nav structure should stay.
- The current top bar should stay.
- The existing page split should stay for the next planning step.
- The candidate detail slide-over pattern should stay.
- The model page should not be reclassified yet until S1 fit is clearer.
- The trades page should not be turned into a broad execution workspace yet.
- The old S1 mobile tab shell should not be copied into React.
- The old pipeline-run/operator-control UI from `mobile_v2.html` should not be imported into the current React shell yet.

In short:
- preserve the Meridian shell and page model
- layer S1 into the existing page structure first

## 8. Least disruptive integration path

1. Treat the current Meridian app as the fixed shell.
   - Do not introduce a second shell or a second nav system.

2. Use the current `Candidates` page as the first S1 landing surface.
   - Add S1 smart-view content as alternate or adjacent candidate views inside the existing candidate workspace.

3. Use the current `Dashboard` for summary-level S1 integration.
   - Add compact smart-view summaries and context cards there, not a whole new operator page.

4. Use the current `Model` page for S1 validation/tracking fit.
   - S1’s strongest non-candidate concepts are forward-tracking and view-quality validation.

5. Do not force a separate top-level `Views` page yet.
   - In the current layout, `Views` is more naturally a mode within `Candidates` than a brand-new shell destination.

6. Do not force a richer `Trades` page yet.
   - The current trades page does not naturally fit S1 smart-view concepts.
   - If the product later needs a richer trade/execution surface, that should be justified by intraday or execution needs, not by S1 smart-view import.

Concrete least-disruptive fit:
- `Dashboard`
  - keep as overview
  - add S1 summary cards
- `Candidates`
  - keep as main table workspace
  - host S1 smart views there first
- `Model`
  - keep as tracking/health
  - add S1 validation/tracker summaries there
- `Trades`
  - leave mostly untouched
- `Settings`
  - leave mostly untouched

## 9. Recommended next planning step

The next planning step should be narrower than a full redesign:

- Map the current `Candidates` page into:
  - current Meridian-only table behavior
  - where a source/view switch could sit
  - what minimal new sections could be added above the existing table
- Map the current `Dashboard` page into:
  - which existing cards can host S1 summaries without layout breakage
- Map the current `Model` page into:
  - which existing tracking blocks can host S1 forward-validation summaries

That next step should answer one focused question:
- how to integrate S1 into the existing Meridian page layout with the fewest route and shell changes

Not yet:
- no new shell
- no big route explosion
- no literal HTML port
- no full unified-product redesign until the current page-fit is locked down
