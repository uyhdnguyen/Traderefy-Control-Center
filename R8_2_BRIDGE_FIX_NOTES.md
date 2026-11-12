# R8.2 — TCC read-only heartbeat discovery fix

- Resolves the Windows Documents directory using the Windows Shell API (supports redirected Documents).
- Checks fallback Documents/OneDrive locations.
- Ignores abandoned `.tmp` files and prioritizes recent heartbeat files rather than the first 80 alphabetically.
- Accepts `heartbeat.txt`, `account_heartbeat_*`, and `auto_heartbeat_*` only when both embedded .NET UTC ticks and file modification time are fresh.
- Returns `bridge_paths_checked` and ignored temporary file counts for troubleshooting.
- Keeps engine connection verification separate: an account heartbeat does not verify TUS/TEE/TEM independently.
- Read-only; no order controls, account routing, or NinjaTrader strategy changes.

**Limitations:** The scan still traverses the directory once, so 200k abandoned temp files should be cleaned up after NinjaTrader is shut down and the writer is confirmed stable. NinjaTrader and Windows installer runtime tests are not available here.
