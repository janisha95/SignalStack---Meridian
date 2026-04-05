# Timezone Audit Report
Date: 2026-03-30

## Summary
- Files audited: 24 active runtime/UI/schema files
- Violations found: 18 grouped findings
- Critical (trade execution): 4
- Display-only: 8

Notes:
- This audit is limited to active runtime paths and operator UI. It intentionally excludes archived/superseded copies under legacy folders such as `Advance/docs`, `Advance/files1`, and `Advance/Villian Arc`.
- Standard applied: store timestamps in DB as UTC, render operator-facing times in `America/New_York`, and avoid hardcoded DST offsets.

## Violations

### CRITICAL — Trade Execution Timestamps
| File | Line | Code | Violation Type | Fix |
|---|---:|---|---|---|
| [/Users/sjani008/SS/Vanguard/vanguard/api/trade_desk.py](/Users/sjani008/SS/Vanguard/vanguard/api/trade_desk.py) | 27, 49 | `executed_at TEXT NOT NULL DEFAULT (datetime('now'))` / `created_at TEXT DEFAULT (datetime('now'))` | SQLITE_NOW | Store explicit UTC ISO strings, e.g. `strftime('%Y-%m-%dT%H:%M:%SZ','now')` in schema defaults or write timestamps in Python with `datetime.now(timezone.utc).isoformat()`. |
| [/Users/sjani008/SS/Vanguard/vanguard/execution/bridge.py](/Users/sjani008/SS/Vanguard/vanguard/execution/bridge.py) | 84 | `created_at_utc TEXT DEFAULT (datetime('now'))` | SQLITE_NOW | Keep UTC, but make it explicit with a `Z`/offset suffix instead of a naive SQLite datetime string. |
| [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/trades-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/trades-client.tsx) | 773 | `{entry.executed_at}` | FRONTEND_RAW | Render `executed_at` through the existing ET formatter (`fmtTimeEt`) instead of printing the raw backend value. |
| [/Users/sjani008/SS/Vanguard/vanguard/execution/telegram_alerts.py](/Users/sjani008/SS/Vanguard/vanguard/execution/telegram_alerts.py) | 69, 86, 95, 113, 138, 163, 206, 214 | `datetime.now().strftime(... 'ET')` | NAIVE_STRFTIME | Replace all operator-facing alert stamps with `datetime.now(ZoneInfo("America/New_York"))` so the displayed `ET` label is DST-safe and host-timezone-independent. |

### HIGH — Operator-Facing Display
| File | Line | Code | Violation Type | Fix |
|---|---:|---|---|---|
| [/Users/sjani008/SS/Vanguard/vanguard/api/adapters/meridian_adapter.py](/Users/sjani008/SS/Vanguard/vanguard/api/adapters/meridian_adapter.py) | 41 | `return f"{date_str}T17:00:00-04:00"` | HARDCODED_OFFSET | Build `as_of` with `ZoneInfo("America/New_York")` and let DST determine the correct offset. |
| [/Users/sjani008/SS/Vanguard/vanguard/api/adapters/s1_adapter.py](/Users/sjani008/SS/Vanguard/vanguard/api/adapters/s1_adapter.py) | 77 | `return f"{run_date}T17:16:00-04:00"` | HARDCODED_OFFSET | Same fix: generate ET timestamps with `ZoneInfo("America/New_York")`, not a fixed `-04:00` string. |
| [/Users/sjani008/SS/Meridian/stages/v2_api_server.py](/Users/sjani008/SS/Meridian/stages/v2_api_server.py) | 253 | `datetime.now().isoformat()` | NAIVE_NOW | Return UTC explicitly for API timestamps, e.g. `datetime.now(timezone.utc).isoformat()`. |
| [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidate-detail-panel.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidate-detail-panel.tsx) | 139 | `· {unifiedRow.as_of}` | FRONTEND_RAW | Parse `as_of` and render it to ET with `Intl.DateTimeFormat`/`toLocaleString` before display. |
| [/Users/sjani008/SS/Advance/s1_evening_report_v2.py](/Users/sjani008/SS/Advance/s1_evening_report_v2.py) | 949, 989 | `datetime.now().strftime("%Y%m%d_%H%M")` / `datetime.now().strftime("%Y-%m-%d")` | NAIVE_STRFTIME | Use ET-aware clocks for operator report stamps and report-date defaults. |
| [/Users/sjani008/SS/Advance/s1_morning_report_v2.py](/Users/sjani008/SS/Advance/s1_morning_report_v2.py) | 1033, 1074 | `datetime.now().strftime("%Y%m%d_%H%M")` / `datetime.now().strftime("%Y-%m-%d")` | NAIVE_STRFTIME | Same as evening report: explicit `America/New_York` for operator-facing report generation. |
| [/Users/sjani008/SS/Advance/s1_convergence_pipeline.py](/Users/sjani008/SS/Advance/s1_convergence_pipeline.py) | 135, 139, 958-959 | `datetime.now().strftime(...)` / `now = datetime.now()` | NAIVE_NOW / NAIVE_STRFTIME | Use UTC for stored/generated metadata and ET-aware formatting for Telegram/report display strings. |
| [/Users/sjani008/SS/Advance/s1_evening_orchestrator.py](/Users/sjani008/SS/Advance/s1_evening_orchestrator.py) | 92, 96 | `datetime.now().strftime(...)` | NAIVE_STRFTIME | Use ET for run-date/stamp logic that operators or daily-session routing rely on. |
| [/Users/sjani008/SS/Advance/s1_morning_agent.py](/Users/sjani008/SS/Advance/s1_morning_agent.py) | 396-397, 483, 489, 495 | `now = datetime.now()` / `now.strftime(...)` | NAIVE_NOW / NAIVE_STRFTIME | Make morning narrative/report timestamps explicitly ET-aware. |

### MEDIUM — Storage Ambiguity
| File | Line | Code | Violation Type | Fix |
|---|---:|---|---|---|
| [/Users/sjani008/SS/Vanguard/vanguard/api/userviews.py](/Users/sjani008/SS/Vanguard/vanguard/api/userviews.py) | 35, 36, 251 | `created_at TEXT DEFAULT (datetime('now'))` / `updated_at = datetime('now')` | SQLITE_NOW | Store explicit UTC ISO timestamps with `Z` in schema defaults and update statements, or write them in Python. |
| [/Users/sjani008/SS/Vanguard/vanguard/api/reports.py](/Users/sjani008/SS/Vanguard/vanguard/api/reports.py) | 39, 40, 127 | `created_at TEXT DEFAULT (datetime('now'))` / `updated_at = datetime('now')` | SQLITE_NOW | Same fix as `userviews.py`: keep UTC but make it explicit. |
| [/Users/sjani008/SS/Advance/agent_server.py](/Users/sjani008/SS/Advance/agent_server.py) | 597, 707, 720 | `fromtimestamp(...).strftime(...)` / `.isoformat()` from filesystem mtimes | DISPLAY_UTC | If these timestamps are shown to operators, convert them to ET or label them UTC; today they are ambiguous local/host times. |

### LOW — Internal Only
| File | Line | Code | Violation Type | Fix |
|---|---:|---|---|---|
| [/Users/sjani008/SS/Advance/s1_pass_scorer.py](/Users/sjani008/SS/Advance/s1_pass_scorer.py) | 411 | `"trained_at": datetime.now().isoformat()` | NAIVE_NOW | Use explicit UTC for model-training metadata (`datetime.now(timezone.utc).isoformat()`). |
| [/Users/sjani008/SS/Meridian/stages/factors/__init__.py](/Users/sjani008/SS/Meridian/stages/factors/__init__.py) | 20 | `return datetime.now(timezone(timedelta(hours=-4)))` | HARDCODED_OFFSET | Keep the `ZoneInfo("America/New_York")` path; replace the fallback with a DST-safe alternative or fail loudly if zone data is unavailable. |

## Files Clean (no violations)
- [/Users/sjani008/SS/Meridian/stages/v2_cache_warm.py](/Users/sjani008/SS/Meridian/stages/v2_cache_warm.py)
- [/Users/sjani008/SS/Meridian/stages/v2_prefilter.py](/Users/sjani008/SS/Meridian/stages/v2_prefilter.py)
- [/Users/sjani008/SS/Meridian/stages/v2_training_backfill.py](/Users/sjani008/SS/Meridian/stages/v2_training_backfill.py)
- [/Users/sjani008/SS/Advance/s1_orchestrator_v2.py](/Users/sjani008/SS/Advance/s1_orchestrator_v2.py)
- [/Users/sjani008/SS/Vanguard/vanguard/helpers/clock.py](/Users/sjani008/SS/Vanguard/vanguard/helpers/clock.py)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/unified-candidates-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/unified-candidates-client.tsx)
