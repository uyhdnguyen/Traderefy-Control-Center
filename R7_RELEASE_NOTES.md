# TCC R7: Local read-only NinjaTrader bridge

- Adds `GET /api/tus/snapshot` to read the existing NinjaTrader 8 `tus_sim_bridge` directory on the same Windows machine.
- Reports per-account heartbeat freshness and recent auto diagnostic file contents without modifying NinjaTrader files.
- TUS Control polls every five seconds, distinguishes heartbeat detected from verified execution, and shows source file status.
- Does not create or modify commands, send orders, change strategies, or imply account positions are available.
- Position and order details require a separate documented read-only data exporter from NinjaTrader; not implemented in R7.
- Only files matching fixed known bridge prefixes are considered; file size and count are bounded, and symlinks are ignored.
- No NinjaTrader scripts modified. Existing journal UI retained.

Validation: Python syntax compilation passed. Full Windows build and real NinjaTrader runtime not tested.
