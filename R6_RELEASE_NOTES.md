# TCC R6: TUS Control Center

Adds a new **TUS Control** navigation tab to the existing Trading-Journal-AI interface. Existing journal pages and backend are preserved.

## Working locally
- Overview: strategy catalog and explicit disconnected engine state.
- Strategy Manager: persistent local tracking preferences for IBS, FTR, FTR-2, ORB15 Retest and IRL→ERL. These are not NinjaTrader execution toggles.
- Risk Calculator: equity, percent risk, entry, stop, contract point value, estimated fees, recommended contract count and budget warnings.
- Diagnostics: paste or load a TUS text report; inspect most recent FTR order, rejection and execution evidence; copy report.
- Uses existing theme CSS variables and TUS green/red.

## Not implemented / safety
- No live NinjaTrader bridge, order submission, strategy toggling, account polling or real-time positions. All are labeled Not connected rather than displaying invented data.
- Risk calculations are planning-only, do not include slippage, and do not submit trades.
- No existing journal data or NinjaTrader scripts modified.

## Validation
- Source/static checks only; full Windows installer and NinjaTrader integration not tested.
