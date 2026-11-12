# Traderefy Control Center R4 — SIM Journal account setup

## What changed
- Settings > General: Set up Traderefy SIM accounts button.
- Creates local Journal account records for Sim101, SimIBS, SimFTR and SimIBSHook.
- Idempotent case-insensitive account matching, preserving existing accounts/trades.
- No NinjaTrader connection, automatic discovery, trade import or order execution.

## Update procedure
1. Upload the contents of this ZIP into your existing private GitHub repository, preserving folder structure.
2. Commit changes and run Actions > Build Traderefy Windows Installer.
3. Install the new build; open Settings > General > Set up Traderefy SIM accounts.
4. Restart TCC and open All Accounts.
5. Verify accounts appear and no duplicate accounts after clicking setup twice.

## Verification
Python syntax and ZIP integrity checked in the development environment. Windows React build, installer, and runtime not verified here.
