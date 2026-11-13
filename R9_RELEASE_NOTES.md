# TCC R9 — Journal Reader + Unified Dashboard Foundation

## Implemented in this source
- New read-only endpoint: `GET /api/tus/journal/snapshot`.
- Locates `Documents/NinjaTrader 8/Traderefy/Journal` using the same Windows Documents resolver as TEM bridge. Override with `TCC_NINJATRADER_JOURNAL_DIR` if necessary.
- Parses TUS trade master and execution master with Python CSV quoting, links executions by IDs, preserves setup tags and manual grouping metadata, isolates Playback accounts, filters records preceding account reset watermarks, prevents repeated trade IDs from being double-counted in the read-only view.
- New Journal > TUS Trades page with account and Playback filtering.
- Dashboard now combines ES/NQ/YM status, setup, active orders, risk, levels, forward tests, source trades and diagnostics in one screen. Removed the Dashboard's Overview/Market/Strategies/Risk/Execution/Diagnostics navigation sub-tabs.
- No NinjaTrader trading code or SIM safety behavior changed.

## Not implemented or verified
- No persistent Trading-Journal-AI database ingestion; existing Calendar, Reports, R metrics and other analytics still use their existing database. The new TUS Trades page and Dashboard preview are read-only from source files.
- No bidirectional key-level synchronization, engine-specific telemetry, approval queue, TEM command routing, Telegram or Quick Tools UI reduction.
- Frontend Windows/CI build was not verified in this environment. NinjaTrader runtime integration not verified.
- Group IDs are preserved as metadata, not automatically merged into a single analytical trade; grouping requires explicit account/leg policy.
- Existing TUS master trade data must be available for the new endpoint to display it.

## Install
1. Back up existing TCC source and its journal database.
2. Replace the R8.2 source with this full source ZIP, rebuild via your existing Windows/GitHub workflow.
3. Start NinjaTrader/TUS and confirm `Documents/NinjaTrader 8/Traderefy/Journal/TUS_Trade_Master.csv` exists.
4. Open `http://127.0.0.1:8000/api/tus/journal/snapshot` on the same PC and check `available`, `source_directory`, `trade_count`, and `paths_checked`.
5. Open TCC Dashboard and Journal > TUS Trades; verify account and Playback filters against TUS journal.
6. Do not assume Trading-Journal-AI's original Reports/Calendar are synced yet.
