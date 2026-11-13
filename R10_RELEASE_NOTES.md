# TCC R10: Working TUS → TCC → Journal pipeline and live engine telemetry

R10 replaces R9. It is built from the full R9 source tree, so every existing journal page, the Exit Lab and the Settings are unchanged. TUS, TEE and the trading rules are untouched. TEM has one small change, to how it writes order status (see section 4).

---

## 1. Audit: why TCC showed no NinjaTrader data

The findings below come from reading the source and the user's own NinjaTrader folder on 2026-11-13.

| # | Finding | Effect |
|---|---|---|
| 1 | The installed source in `Downloads\Traderefy-Control-Center-main` is **R8.2 with two R9 files dropped in**. `main.py`, `App.js`, `ControlWorkspace.js` and `AppHeader.js` are byte-identical to R8.2. `tus_journal.py` and `TusJournal.js` were never imported or mounted. | `/api/tus/journal/snapshot` did not exist, and the R9 dashboard never appeared. |
| 2 | The R9 notes said to test `http://127.0.0.1:8000`, but `desktop/tcc_launcher.py` serves on **8010**. | Every manual API test failed regardless of code. |
| 3 | The R9 dashboard was a static shell. The ES/NQ/YM panels were hard-coded to "No data", and setups, orders, levels and forward tests were placeholders. Nothing read the files TUS and TEE publish (`Traderefy\TUS_FTR_Levels_<ROOT>.status`, `TUS_FTR_Trend_<ROOT>.status`, `FTR_699_<ROOT>.status`, the candidates and the signal journal). | Nothing could show even with NinjaTrader running. |
| 4 | Engine status searched for `auto_heartbeat_*` files whose names contain "tus" or "tee". TEM names these files `auto_heartbeat_<Account>_<Instrument>`. | TUS, TEE and TEM always showed "Disconnected". |
| 5 | No code wrote TUS trades into the Trading-Journal-AI database. | Calendar, Reports, R and the KPIs never saw TUS trades. |
| 6 | The R9 reset filter compared offset-less NinjaTrader times with an aware UTC watermark and skipped every comparison. Python 3.10 cannot parse 7-digit .NET fractions. | Account resets were ignored, and parsing was fragile. |
| 7 | The bridge reader listed all ~206,000 entries of `tus_sim_bridge` every 5 s. Python's `open()` does not grant delete-sharing on Windows, so a TCC read could make TEM's `File.Replace` fail. | CPU and disk load, plus a plausible source of more abandoned `.tmp` files. |
| 8 | TEM `order_status.txt` is shared by every TEM instance, but each instance had only its own lock and no `.tmp` cleanup. The per-account `order_status_<acct>_<inst>.txt` path was computed but **never written**. | Order state was last-writer-wins, `.tmp` files leaked, and there was no per-instance order state. |
| 9 | Only **MES** charts are live: TUS M5, TEE 699, and TEM on SimIBS and SimFTR. The MNQ files are stale since 2026-10-22, and no MYM/YM files exist. | NQ and YM cannot show live data until those chart pairs are opened. |

## 2. What R10 changes

### Backend (new modules, pure Python, unit-tested)
- **`nt_paths.py`** is the single resolver for the NinjaTrader folder: Documents (including redirected and OneDrive folders), `tus_sim_bridge`, `Traderefy` and `Traderefy\Journal`. It can be overridden with `TCC_NINJATRADER_DIR` or `TCC_NINJATRADER_JOURNAL_DIR`. On Windows all reads use `FILE_SHARE_READ|WRITE|DELETE`, so TCC can never block a NinjaTrader writer.
- **`nt_telemetry.py`** reads each engine from its own file, per market. ES maps to MES or ES, NQ to MNQ or NQ, YM to MYM or YM, choosing the freshest root.
  - **TUS M5:** level and trend publication age, trend votes (overall/PP/M15/M60), ORB high/low, previous-day levels, pivots, and manually drawn key levels.
  - **TEE 699:** status age, event and bar number, plus FTR candidates.
  - **TEM:** each instance's account heartbeat and auto-route heartbeat, last diagnostic code, scoped order status (after the TEM fix) and recent events.
  - **Open positions:** net fills since flat, taken from `TUS_Execution_Master.csv`.
  - **Signal routing:** from `TUS_Real_Signal_Journal_<ROOT>.csv`, showing detected, sent to TEM or rejected.
  - **Automation mode:** from `TUS_Playback_Mode.txt` (SIM, PLAYBACK or OFF). This is labelled as TUS routing mode, not the data feed.
  - **Market session:** a simplified CME schedule, so stale data on a closed market is not reported as a failure.
  - **Bridge folder:** never listed per request. Known names are read directly, and a bounded discovery scan runs at most every 5 minutes.
- **`tus_journal.py`** is the read-only TUS journal parser. It handles timezones correctly (NT local time to UTC, override with `TCC_NT_TIMEZONE`), enforces reset watermarks, attaches each trade's own fills, reads tags, manual groups and approvals, and reads TEM forward fills for setup and stop.
- **`tus_import.py`** is an idempotent importer into the existing `trades` and `trade_analysis` tables:
  - **One trade per TUS master row.** A two-leg TP1/TP2 trade is one trade with 4 executions, and fills are never counted as trades.
  - **One journal account per NinjaTrader account**, named `TUS · <Account>`. An empty R4 placeholder (`SimIBS`, `SimFTR`, `Sim101`) is reused only if it holds no other trades.
  - **Playback** goes to separate accounts, flagged so that **"All Accounts" excludes Playback** everywhere in the Journal. Select a Playback account to see it.
  - **Setup** comes from the TUS journal tag, or failing that from TEM's forward-fill setup (IBS, FTR-1/2/3). It is added to the playbook if missing.
  - **Stop, risk and R** come from TEM's protective stop at entry: risk = |entry − stop| × point value × quantity.
  - **Annotations are never overwritten:**
    - Notes and ratings are untouched.
    - Stop, risk and R are only filled when empty or when they still hold the value TCC wrote.
    - A setup changed by hand is kept.
    - A trade edited in the journal (`source='edited'`) is not overwritten and is reported as a conflict.
    - A trade deleted in the journal is not re-created.
    - A trade removed from TUS (reset or Playback clear) is kept and flagged. Purging it is explicit (`POST /api/tus/import/purge-removed`).
  - **Imports run automatically** every 10 s when the journal files change (`TCC_TUS_AUTO_IMPORT=0` disables this), and on demand.
- **`tcc_api.py`** provides the routes: `/api/tcc/live`, `/api/tcc/diagnostics`, `/api/tus/import/status|run|purge-removed`, plus the existing `/api/tus/snapshot` and `/api/tus/journal/snapshot`.
- **`main.py`** registers the router, creates the import tables on startup and starts auto-import. The "All Accounts" filter now excludes Playback. A journal edit of a TUS trade marks it `edited`.

### Frontend
- **Dashboard** (`TccDashboard.js`, the single Dashboard page with no sub-tabs). It shows three market panels, each with:
  - TUS, TEE and TEM status with ages
  - trend meter
  - ORB, previous-day levels, pivots and drawn key levels
  - open position

  Below them:
  - **Setups / signal routing**
  - **Active trades / orders / TEM**, with per-instance heartbeat, last event, order status and recent events
  - **Forward tests**, per imported account: trades, net, win %, average R, and an Import now button
  - **Risk**, the existing calculator link
  - **System diagnostics**, with a "Copy diagnostics" button
  - **TUS Trades**

  Only R9's existing `cw-*` styles and palette are used. The only addition is an amber "stale" chip that reuses the existing warning colours.
- **Journal → TUS Trades** shows each TUS trade's journal status (Imported, Edited (kept), Deleted in journal, or Pending), its R, and an Import now button.

### NinjaScript
- **TEM** `PublishOrderState` now writes through the existing process-wide atomic writer (static lock, guaranteed `.tmp` cleanup) and also writes the scoped `order_status_<Account>_<Instrument>.txt`. **No order, risk, account or validation logic changed.**
- **TUS and TEE are unchanged.**

### Build
- `desktop/tcc.spec` adds the new modules as hidden imports.
- The GitHub workflow runs `tests/test_tus_pipeline.py`, which must pass, and then the full backend suite (reported, non-blocking) before PyInstaller.
- `VERSION` is set to `R10`. R9 never updated it and still reported R8.

## 3. Verification status

| Item | Status |
|---|---|
| Journal parser and importer against the **user's real journal files** (20 trades, 5 accounts, including Playback) | **Verified here.** All 20 imported; a second run left all 20 unchanged. |
| R/setup values traced to TEM forward fills | **Verified here.** Example: the 2026-11-09 SimIBS trade's 96.75-point stop really is what TEM recorded. |
| Telemetry against the user's real status, heartbeat and event files | **Verified here.** MES TUS 2 s, TEE 4 s, TEM 2/2 live; MNQ stale since 22 days; YM no charts. |
| 16 backend unit tests: idempotency, annotations, edits, deletes, resets, purge, Playback isolation, placeholder reuse, telemetry, positions, `.tmp` handling | **Pass here** (Python 3.13). The 17th, the Playback filter through `main.account_ids`, needs FastAPI and runs in CI. |
| API route functions (`tcc_api.py`) on real data | **Verified here** using a FastAPI stand-in, because FastAPI cannot be installed in this sandbox. |
| Dashboard and TUS Trades components | **Rendered here** from the real data through a React-compatible static renderer. Syntax and undefined-name checks were run with TypeScript. **The CRA/webpack build was not run here**; the CI build verifies it. |
| Full app start (FastAPI and uvicorn), Windows installer, pywebview | **Not tested here.** Covered by the GitHub workflow and by the checks in section 5. |
| TEM change compiled in NinjaTrader | **Not compiled.** No C# compiler is available here. The change is 6 lines and calls an existing method. |
| `tools/Verify-TCC.ps1` | **Not run here.** No PowerShell is available. |
| Bidirectional level sync, TCC approvals, TEM command routing, Telegram, Quick Tools rework | **Not in R10.** These are planned for R11, after R10 is confirmed on Windows. |

## 4. Install

1. **Back up:**
   - `%LOCALAPPDATA%\Traderefy\ControlCenter\trading_journal.db`
   - the whole `Downloads\Traderefy-Control-Center-main` folder
   - `Documents\NinjaTrader 8\bin\Custom\Strategies\TraderefyExecutionManager.cs`
2. **Replace the entire repository folder** with this R10 source. Do not merge single files; partial copying is what broke R9.
3. **Push to GitHub**, run "Build Traderefy Windows Installer", download the artifact and install it. The tests step must be green.
4. **TEM:** close the TEM strategies, copy `NinjaTrader/TraderefyExecutionManager.cs` over the existing file, and compile with NinjaScript Editor → F5. Re-enable TEM on the SimIBS (M5) and SimFTR (699) charts, **SIM only**.
5. **Clean up old `.tmp` files** (optional, only after NinjaTrader is completely closed). In PowerShell:
   `Get-ChildItem "$env:USERPROFILE\Documents\NinjaTrader 8\tus_sim_bridge" -Filter *.tmp | Remove-Item`

## 5. Test procedure (Windows)

1. Start NinjaTrader with the MES M5 TUS and MES 699 TEE charts, and TEM on both. Open TCC.
2. Run `powershell -ExecutionPolicy Bypass -File tools\Verify-TCC.ps1 -Import`. Every required check should be `[OK]`.
3. On the **Dashboard**, the ES panel should show `ES (MES) · MES 12-26 · Live`. The ORB and previous-day levels should match the chart, and TEM should show `2/2 live`.
4. Check staleness detection:
   - Remove TEE from the 699 chart. Within 90 s only "TEE · 699" should turn **Stale**, while TUS and TEM stay Live.
   - Disable TEM on SimFTR. Within 15 s TEM should show `1/2 live`.
5. In **Journal → TUS Trades**, every row should be "Imported".
6. Open **Trade Log** and filter the account `TUS · SimIBS`. Check that **Calendar**, **Reports** (by strategy: IBS, FTR-1, FTR-3) and the R distribution include the trades.
7. With "All Accounts" selected, confirm that the Playback101 results (−$466.25) are **not** included. Select `TUS · Playback101 (Playback)` to see them.
8. Check idempotency:
   - Restart TCC and confirm no duplicate trades.
   - Add a note to one imported trade, click **Import now**, and confirm the note is kept.
9. After the next real SIM trade closes, confirm that within about 15 s it appears in TUS Trades and the Trade Log as **one** trade with 4 fills.
10. If anything fails, click **Copy diagnostics** on the Dashboard and send the output.

## 6. Notes on the data

- The importer keeps TUS's own P&L and commission. On the user's data, SimIBS and SimFTR fills carry a commission of 0.
- `PA-APEX-30231-02` trades from the funded account are imported because TUS journals them. They are read-only data. TCC never executes on any account.
