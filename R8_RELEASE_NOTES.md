# TCC R8 — Unified Workspaces (source release)

## Included
- Two horizontal workspace tabs: DASHBOARD and JOURNAL.
- DASHBOARD left navigation: Overview, Market, Strategies, Risk, Execution, Diagnostics.
- JOURNAL left navigation: Overview, Trade Log, Calendar, Reports, Exit Lab, Diary, Day Review, Import, Settings. Existing journal pages and backend retained.
- New dark/navy TCC dashboard UI with TUS #58D297 green and #F47D7D red.
- Real journal KPI endpoint used for dashboard metrics; existing account filter passed through.
- Read-only NinjaTrader bridge polled every five seconds; per-engine status remains disconnected unless matching heartbeat file is fresh. This does NOT prove an engine can execute orders.
- Strategy rules and independent SIM account descriptions for IBS, FTR, FTR-2; ORB15 explicitly observation only; IRL→ERL planned.
- Local risk calculator for entry/stop, point value, contracts, estimated fees, and equity risk budget; it sends no orders.
- Diagnostics file inventory, local TXT import, and copy report.
- Explicit empty states for unavailable live prices, signals, positions, order history, and risk limits. No invented live data.

## Not included / blocked on NinjaTrader exporters
- Automatic TUS CSV execution import and signal/forward-test classification: cannot safely infer the actual master CSV schema or source-of-truth path from the bridge snapshot. Existing journal manual import remains.
- Live market data, trend meter values, live positions/orders, stop management, and SIM execution controls: no verified export/command protocol. Controls are intentionally disabled.
- Pixel-perfect matching to illustrative renders is not yet verified; the new screens follow the panel structure but need screenshot comparison in the built Windows app.

## Testing
- Backend Python modules compiled with `python -m compileall`.
- `npm ci --offline` could not complete because a dependency tarball is absent from the local cache. Frontend compilation and Windows installer are **not verified**.
- No NinjaTrader runtime connection was tested.

## Safety
- No live or SIM order submission added. No changes to TUS/TEE/TEM NinjaScript sources.
- Historical journal database is not altered by this release.
