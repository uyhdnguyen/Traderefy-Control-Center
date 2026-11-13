"""Import TUS journal trades into the Trading-Journal-AI database (R10).

After an import, the existing Overview, Trade Log, Calendar, Reports, R multiples,
Leaks, Exit Lab, Diary and Day Review all see TUS trades, because they become
ordinary rows of the `trades` table.

Rules:
  * One TUS master row (flat-to-flat cycle) = one journal trade. A two-leg TP1/TP2
    trade stays one trade; its four fills are its executions. Fills are never trades.
  * Idempotent: tus_import_map remembers (TUS account, TUS TradeId) -> journal trade,
    plus a content hash. Unchanged trades are skipped; changed ones are updated.
  * Annotations are never overwritten: trade_analysis notes/ratings/etc. are untouched;
    stop/risk/R are only filled when empty or still equal to the value TCC wrote;
    the setup tag is only set when empty or previously set by TCC; trades edited in
    the journal (source='edited') are not overwritten.
  * A trade deleted in the journal is not re-created. A trade that disappears from
    TUS (account reset / Playback clear) is kept and flagged; purge is explicit.
  * Playback accounts import into separate journal accounts flagged as Playback; the
    "All Accounts" analytics exclude them (see playback_account_ids / main.account_ids).
  * Each TUS account maps to its own journal account "TUS · <Account>".
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import tus_journal

BROKER_LIVE = 'NinjaTrader · TUS'
BROKER_PLAYBACK = 'NinjaTrader · TUS Playback'
SOURCE = 'tus'
MONTH_CODES = 'FGHJKMNQUVXZ'
POINT_VALUES = {'MES': 5.0, 'ES': 50.0, 'MNQ': 2.0, 'NQ': 20.0, 'MYM': 0.5, 'YM': 5.0, 'M2K': 5.0, 'RTY': 50.0,
                'MGC': 10.0, 'GC': 100.0, 'MCL': 100.0, 'CL': 1000.0}
ACTION = {'Buy': 'BOT', 'BuyToCover': 'BOT', 'Sell': 'SOLD', 'SellShort': 'SOLD'}
_run_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS tus_accounts (
    tus_account TEXT PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    playback    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tus_import_map (
    tus_account   TEXT NOT NULL,
    tus_trade_id  TEXT NOT NULL,
    account_id    INTEGER NOT NULL,
    trade_group   TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    tus_status    TEXT,
    manual_group_id TEXT,
    tcc_values    TEXT,            -- JSON of setup/stop/risk/R values TCC wrote
    first_imported_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    removed_from_tus_at TEXT,
    deleted_in_journal_at TEXT,
    conflict      TEXT,
    PRIMARY KEY (tus_account, tus_trade_id)
);
CREATE INDEX IF NOT EXISTS idx_tus_map_group ON tus_import_map(account_id, trade_group);
CREATE TABLE IF NOT EXISTS tus_import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source_directory TEXT,
    source_signature TEXT,
    trigger TEXT,
    seen INTEGER DEFAULT 0, inserted INTEGER DEFAULT 0, updated INTEGER DEFAULT 0,
    unchanged INTEGER DEFAULT 0, removed_from_tus INTEGER DEFAULT 0,
    skipped_deleted INTEGER DEFAULT 0, skipped_edited INTEGER DEFAULT 0,
    warnings TEXT, error TEXT
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def futures_ticker(instrument: str) -> tuple[str, str]:
    """'MES 12-26' -> ('/MESZ26', 'MES'). Unknown formats keep the NinjaTrader name."""
    m = re.match(r'^\s*([A-Z0-9]+)\s+(\d{1,2})-(\d{2})\s*$', (instrument or '').upper())
    if not m or not 1 <= int(m.group(2)) <= 12:
        root = (instrument or '').split(' ')[0].upper()
        return (instrument or '').upper(), root
    root = m.group(1)
    return f"/{root}{MONTH_CODES[int(m.group(2)) - 1]}{m.group(3)}", root


def _eastern(dt_utc: datetime) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt_utc.astimezone(ZoneInfo('America/New_York'))
    except Exception:
        return dt_utc


def playback_account_ids(conn) -> set[int]:
    try:
        return {r[0] for r in conn.execute("SELECT account_id FROM tus_accounts WHERE playback=1")}
    except Exception:
        return set()


def _account_id(conn, tus_account: str) -> int:
    row = conn.execute("SELECT account_id FROM tus_accounts WHERE tus_account=?", (tus_account,)).fetchone()
    if row and conn.execute("SELECT 1 FROM accounts WHERE id=?", (row[0],)).fetchone():
        return row[0]
    playback = tus_journal.is_playback_account(tus_account)
    broker = BROKER_PLAYBACK if playback else BROKER_LIVE
    name = f"TUS · {tus_account}" + (' (Playback)' if playback else '')
    existing = conn.execute("SELECT id FROM accounts WHERE name=? AND broker=?", (name, broker)).fetchone()
    # R4 "Set up Traderefy SIM journal accounts" created empty placeholders named exactly
    # like the NinjaTrader account (Sim101, SimIBS, SimFTR). Reuse one only while it holds
    # no trades from another source, so TUS fills can never double-count a CSV import.
    placeholder = conn.execute(
        "SELECT a.id FROM accounts a WHERE a.name=? COLLATE NOCASE AND a.broker=? AND NOT EXISTS "
        "(SELECT 1 FROM trades t WHERE t.account_id=a.id AND t.source<>?)",
        (tus_account, 'NinjaTrader (journal only)', SOURCE)).fetchone() if not playback else None
    if existing:
        account_id = existing[0]
    elif placeholder:
        account_id = placeholder[0]
        conn.execute("UPDATE accounts SET broker=? WHERE id=?", (broker, account_id))
    else:
        cur = conn.execute("INSERT INTO accounts (name, type, color, broker) VALUES (?,?,?,?)",
                           (name, 'day_trading', '#8a96a5' if playback else '#1479f5', broker))
        account_id = cur.lastrowid
    conn.execute("INSERT OR REPLACE INTO tus_accounts (tus_account, account_id, playback) VALUES (?,?,?)",
                 (tus_account, account_id, 1 if playback else 0))
    return account_id


def _free_group(conn, account_id: int, date: str, ticker: str, taken: set) -> str:
    n = 1
    while True:
        name = f"{date}_{ticker}_FUTURE_{n}"
        if name not in taken and not conn.execute(
                "SELECT 1 FROM trades WHERE trade_group=? AND account_id=?", (name, account_id)).fetchone() \
                and not conn.execute("SELECT 1 FROM tus_import_map WHERE trade_group=? AND account_id=?",
                                     (name, account_id)).fetchone():
            taken.add(name)
            return name
        n += 1


def build_trade(t: dict) -> dict:
    """TUS master row (+ fills) -> journal trade fields, executions in the native shape."""
    ticker, root = futures_ticker(t.get('Instrument', ''))
    warnings = []
    execs = []
    for f in sorted(t.get('executions', []), key=lambda f: (f.get('Time', ''), f.get('ExecutionId', ''))):
        when = tus_journal.parse_nt_time(f.get('Time'))
        action = ACTION.get(f.get('Action', ''))
        try:
            qty = int(float(f.get('Quantity') or 0))
            price = float(f.get('Price') or 0)
            commission = float(f.get('Commission') or 0)
        except ValueError:
            qty, price, commission = 0, 0.0, 0.0
        if not when or not action or qty <= 0:
            warnings.append(f"unreadable fill {f.get('ExecutionId')}")
            continue
        et = _eastern(when)
        execs.append({'date': et.strftime('%Y-%m-%d'), 'time': et.strftime('%H:%M:%S'), 'action': action,
                      'qty': qty, 'price': price, 'commission': round(commission, 2),
                      'tus_execution_id': f.get('ExecutionId')})
    synthetic = False
    if not execs or t.get('missing_execution_ids'):
        # Keep the trade in analytics from the master's own aggregate values; flag it.
        synthetic = True
        warnings.append('fills missing from TUS_Execution_Master; entry/exit synthesised from the trade master')
        qty = int(float(t.get('Quantity') or 0))
        opened = tus_journal.parse_nt_time(t.get('OpenTime'))
        closed = tus_journal.parse_nt_time(t.get('CloseTime'))
        side_long = (t.get('Side') or '').upper() == 'LONG'
        execs = []
        for when, price, act in ((opened, t.get('EntryPrice'), 'BOT' if side_long else 'SOLD'),
                                 (closed, t.get('ExitPrice'), 'SOLD' if side_long else 'BOT')):
            if when is None:
                continue
            et = _eastern(when)
            execs.append({'date': et.strftime('%Y-%m-%d'), 'time': et.strftime('%H:%M:%S'), 'action': act,
                          'qty': qty, 'price': float(price or 0), 'commission': 0.0, 'synthetic': True})
    closed = tus_journal.parse_nt_time(t.get('CloseTime'))
    date = _eastern(closed).strftime('%Y-%m-%d') if closed else (execs[-1]['date'] if execs else '')
    pv = None
    for f in t.get('executions', []):
        try:
            pv = float(f.get('PointValue') or 0) or None
        except ValueError:
            pv = None
        if pv:
            break
    pv = pv or POINT_VALUES.get(root)
    gross, net, comm = t.get('gross_pnl'), t.get('net_pnl'), t.get('commission')
    if pv and not synthetic:
        computed = sum(e['price'] * e['qty'] * pv * (1 if e['action'] == 'SOLD' else -1) for e in execs)
        if gross is not None and abs(computed - gross) > 0.011:
            warnings.append(f'gross P&L {gross} differs from fills ({round(computed, 2)}); TUS value kept')
    side = (t.get('Side') or '').upper()
    if side not in ('LONG', 'SHORT'):
        side = 'LONG' if execs and execs[0]['action'] == 'BOT' else 'SHORT'
    # Setup: TUS journal classification first, then the TEM forward-fill setup.
    forward = t.get('forward') or []
    setup = t.get('setup_tag') or (forward[0]['setup'] if forward and forward[0].get('setup') else None)
    # Initial risk from TEM's protective stop at entry (SIM/Playback automation only).
    risk = stop = r_multiple = None
    entry = t.get('EntryPrice')
    try:
        entry = float(entry) if entry not in (None, '') else None
    except ValueError:
        entry = None
    stops = {round(x['stop'], 6) for x in forward if x.get('stop')}
    if len(stops) == 1 and entry is not None and pv:
        stop = stops.pop()
        qty_total = int(float(t.get('Quantity') or 0))
        risk = round(abs(entry - stop) * pv * qty_total, 2)
        if risk > 0 and net is not None:
            r_multiple = round(net / risk, 2)
        else:
            risk = None
    return {'ticker': ticker, 'root': root, 'date': date, 'side': side, 'executions': execs,
            'gross_pnl': round(gross, 2) if gross is not None else None,
            'net_pnl': round(net, 2) if net is not None else None,
            'commissions': round(abs(comm), 2) if comm is not None else 0.0,
            'setup': setup, 'stop': stop, 'risk': risk, 'r_multiple': r_multiple,
            'point_value': pv, 'synthetic': synthetic, 'warnings': warnings}


def _hash(t: dict, built: dict) -> str:
    payload = {k: built[k] for k in ('date', 'side', 'executions', 'gross_pnl', 'net_pnl', 'commissions',
                                     'setup', 'stop', 'risk', 'r_multiple')}
    payload.update({'status': t.get('Status'), 'group': t.get('manual_group_id')})
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _ensure_setup(conn, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO custom_setups (name, notes) VALUES (?, ?)",
                 (name, 'Added by the TUS journal import'))
    conn.execute("UPDATE custom_setups SET active=1 WHERE name=? AND active=0", (name,))


def _apply_review(conn, account_id: int, group: str, built: dict, previous: dict) -> dict:
    """Fill stop/risk/R and the setup tag without overwriting the trader's own values."""
    written = {}
    if built.get('setup'):
        row = conn.execute("SELECT setup, setup_source FROM trades WHERE trade_group=? AND account_id=?",
                           (group, account_id)).fetchone()
        if row is not None and (row[0] in (None, '') or row[1] == SOURCE):
            _ensure_setup(conn, built['setup'])
            conn.execute("UPDATE trades SET setup=?, setup_source=? WHERE trade_group=? AND account_id=?",
                         (built['setup'], SOURCE, group, account_id))
            written['setup'] = built['setup']
        elif row is not None and row[0] == previous.get('setup'):
            written['setup'] = previous.get('setup')
    fields = {'stop_loss': built.get('stop'), 'risk_per_trade': built.get('risk'), 'r_multiple': built.get('r_multiple')}
    if any(v is not None for v in fields.values()):
        ta = conn.execute("SELECT id, stop_loss, risk_per_trade, r_multiple FROM trade_analysis "
                          "WHERE trade_group=? AND account_id=?", (group, account_id)).fetchone()
        if ta is None:
            conn.execute("INSERT INTO trade_analysis (account_id, trade_group, ticker, date, stop_loss, "
                         "risk_per_trade, r_multiple) VALUES (?,?,?,?,?,?,?)",
                         (account_id, group, built['ticker'], built['date'], *fields.values()))
            written.update({k: v for k, v in fields.items() if v is not None})
        else:
            updates = {}
            for col, value in fields.items():
                current = ta[col]
                if value is None:
                    continue
                if current is None or current == previous.get(col):
                    updates[col] = value
                    written[col] = value
            if updates:
                conn.execute(f"UPDATE trade_analysis SET {', '.join(c + '=?' for c in updates)} WHERE id=?",
                             (*updates.values(), ta[0]))
    return written


def import_journal(conn, journal: dict, trigger: str = 'manual') -> dict:
    """Import a tus_journal.load_journal() result. Caller supplies an open connection."""
    ensure_schema(conn)
    now = _utcnow()
    stats = {'seen': 0, 'inserted': 0, 'updated': 0, 'unchanged': 0, 'removed_from_tus': 0,
             'skipped_deleted': 0, 'skipped_edited': 0}
    warnings: list[str] = []
    run_id = conn.execute("INSERT INTO tus_import_runs (started_at, source_directory, trigger) VALUES (?,?,?)",
                          (now, journal.get('source_directory'), trigger)).lastrowid
    taken: set = set()
    seen_keys = set()
    for t in journal.get('trades', []):
        tus_account, trade_id = t.get('Account'), t.get('TradeId')
        if not tus_account or not trade_id:
            continue
        stats['seen'] += 1
        seen_keys.add((tus_account, trade_id))
        account_id = _account_id(conn, tus_account)
        built = build_trade(t)
        for w in built['warnings']:
            warnings.append(f"{tus_account} {t.get('CloseTime')}: {w}")
        digest = _hash(t, built)
        mapping = conn.execute("SELECT * FROM tus_import_map WHERE tus_account=? AND tus_trade_id=?",
                               (tus_account, trade_id)).fetchone()
        previous = json.loads(mapping['tcc_values'] or '{}') if mapping else {}
        if mapping:
            group = mapping['trade_group']
            account_id = mapping['account_id'] if conn.execute(
                "SELECT 1 FROM accounts WHERE id=?", (mapping['account_id'],)).fetchone() else account_id
            row = conn.execute("SELECT id, source FROM trades WHERE trade_group=? AND account_id=?",
                               (group, account_id)).fetchone()
            if row is None:
                stats['skipped_deleted'] += 1
                conn.execute("UPDATE tus_import_map SET last_seen_at=?, removed_from_tus_at=NULL, "
                             "deleted_in_journal_at=COALESCE(deleted_in_journal_at, ?) "
                             "WHERE tus_account=? AND tus_trade_id=?", (now, now, tus_account, trade_id))
                continue
            if mapping['content_hash'] == digest:
                stats['unchanged'] += 1
                conn.execute("UPDATE tus_import_map SET last_seen_at=?, removed_from_tus_at=NULL "
                             "WHERE tus_account=? AND tus_trade_id=?", (now, tus_account, trade_id))
                continue
            if row['source'] == 'edited':
                stats['skipped_edited'] += 1
                conn.execute("UPDATE tus_import_map SET last_seen_at=?, conflict=? WHERE tus_account=? AND tus_trade_id=?",
                             (now, 'TUS changed this trade but it was edited in the journal; journal values kept',
                              tus_account, trade_id))
                continue
            conn.execute("UPDATE trades SET date=?, side=?, gross_pnl=?, net_pnl=?, commissions=?, executions=?, "
                         "imported_at=datetime('now') WHERE id=?",
                         (built['date'], built['side'], built['gross_pnl'], built['net_pnl'], built['commissions'],
                          json.dumps(built['executions']), row['id']))
            written = _apply_review(conn, account_id, group, built, previous)
            conn.execute("UPDATE tus_import_map SET content_hash=?, tus_status=?, manual_group_id=?, tcc_values=?, "
                         "last_seen_at=?, removed_from_tus_at=NULL, conflict=NULL WHERE tus_account=? AND tus_trade_id=?",
                         (digest, t.get('Status'), t.get('manual_group_id'), json.dumps(written), now,
                          tus_account, trade_id))
            stats['updated'] += 1
            continue
        group = _free_group(conn, account_id, built['date'], built['ticker'], taken)
        conn.execute("INSERT INTO trades (account_id, trade_group, date, ticker, instrument_type, side, gross_pnl, "
                     "net_pnl, commissions, executions, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (account_id, group, built['date'], built['ticker'], 'FUTURE', built['side'], built['gross_pnl'],
                      built['net_pnl'], built['commissions'], json.dumps(built['executions']), SOURCE))
        written = _apply_review(conn, account_id, group, built, {})
        conn.execute("INSERT INTO tus_import_map (tus_account, tus_trade_id, account_id, trade_group, content_hash, "
                     "tus_status, manual_group_id, tcc_values, first_imported_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (tus_account, trade_id, account_id, group, digest, t.get('Status'), t.get('manual_group_id'),
                      json.dumps(written), now, now))
        stats['inserted'] += 1
    # Trades no longer present in TUS (reset / Playback clear): keep, flag once.
    for m in conn.execute("SELECT tus_account, tus_trade_id FROM tus_import_map WHERE removed_from_tus_at IS NULL "
                          "AND deleted_in_journal_at IS NULL").fetchall():
        if (m[0], m[1]) not in seen_keys:
            conn.execute("UPDATE tus_import_map SET removed_from_tus_at=? WHERE tus_account=? AND tus_trade_id=?",
                         (now, m[0], m[1]))
            stats['removed_from_tus'] += 1
    conn.execute("UPDATE tus_import_runs SET finished_at=?, seen=?, inserted=?, updated=?, unchanged=?, "
                 "removed_from_tus=?, skipped_deleted=?, skipped_edited=?, warnings=? WHERE id=?",
                 (_utcnow(), stats['seen'], stats['inserted'], stats['updated'], stats['unchanged'],
                  stats['removed_from_tus'], stats['skipped_deleted'], stats['skipped_edited'],
                  json.dumps(warnings[:200]), run_id))
    conn.commit()
    return {**stats, 'warnings': warnings[:200], 'run_id': run_id}


def run_import(conn, trigger: str = 'manual', roots=None, signature_check: bool = False) -> dict:
    """Locate the TUS journal, load it and import it. Serialised with CSV imports."""
    from trade_store import IMPORT_LOCK
    root, checked = tus_journal.find_journal_root([Path(r) for r in roots] if roots is not None else None)
    if root is None:
        return {'ok': False, 'reason': 'TUS journal not found', 'paths_checked': checked}
    signature = tus_journal.source_signature(root)
    with _run_lock, IMPORT_LOCK:
        ensure_schema(conn)
        if signature_check:
            last = conn.execute("SELECT source_signature FROM tus_import_runs WHERE finished_at IS NOT NULL "
                                "AND error IS NULL ORDER BY id DESC LIMIT 1").fetchone()
            if last and last[0] == signature:
                return {'ok': True, 'skipped': 'source unchanged', 'source_directory': str(root)}
        try:
            journal = tus_journal.load_journal(root)
            result = import_journal(conn, journal, trigger)
            conn.execute("UPDATE tus_import_runs SET source_signature=? WHERE id=?", (signature, result['run_id']))
            conn.commit()
            return {'ok': True, 'source_directory': str(root), **result}
        except Exception as exc:  # recorded, never silently swallowed
            conn.rollback()
            conn.execute("INSERT INTO tus_import_runs (started_at, finished_at, source_directory, trigger, error) "
                         "VALUES (?,?,?,?,?)", (_utcnow(), _utcnow(), str(root), trigger, repr(exc)))
            conn.commit()
            return {'ok': False, 'source_directory': str(root), 'error': repr(exc)}


def import_status(conn) -> dict:
    ensure_schema(conn)
    last = conn.execute("SELECT * FROM tus_import_runs ORDER BY id DESC LIMIT 1").fetchone()
    last_ok = conn.execute("SELECT * FROM tus_import_runs WHERE error IS NULL AND finished_at IS NOT NULL "
                           "AND seen > 0 ORDER BY id DESC LIMIT 1").fetchone()
    accounts = []
    for r in conn.execute(
            "SELECT ta.tus_account, ta.account_id, ta.playback, a.name, "
            "(SELECT COUNT(*) FROM tus_import_map m WHERE m.tus_account=ta.tus_account AND m.removed_from_tus_at IS NULL "
            " AND m.deleted_in_journal_at IS NULL) AS trades, "
            "(SELECT COUNT(*) FROM tus_import_map m WHERE m.tus_account=ta.tus_account AND m.removed_from_tus_at IS NOT NULL) AS removed, "
            "(SELECT ROUND(SUM(t.net_pnl),2) FROM trades t WHERE t.account_id=ta.account_id) AS net_pnl, "
            "(SELECT COUNT(*) FROM trades t WHERE t.account_id=ta.account_id) AS journal_trades, "
            "(SELECT SUM(CASE WHEN t.net_pnl>0 THEN 1 ELSE 0 END) FROM trades t WHERE t.account_id=ta.account_id) AS wins, "
            "(SELECT ROUND(AVG(x.r_multiple),2) FROM trade_analysis x WHERE x.account_id=ta.account_id AND x.r_multiple IS NOT NULL) AS avg_r "
            "FROM tus_accounts ta LEFT JOIN accounts a ON a.id=ta.account_id ORDER BY ta.playback, ta.tus_account"):
        accounts.append(dict(r) if hasattr(r, 'keys') else r)
    conflicts = [dict(r) for r in conn.execute(
        "SELECT tus_account, tus_trade_id, trade_group, conflict FROM tus_import_map WHERE conflict IS NOT NULL LIMIT 50")]
    return {'last_run': dict(last) if last else None, 'last_successful_import': dict(last_ok) if last_ok else None,
            'accounts': accounts, 'conflicts': conflicts,
            'playback_account_ids': sorted(playback_account_ids(conn)),
            'note': 'Playback accounts are excluded from "All Accounts" analytics; select them explicitly.'}


def purge_removed(conn) -> dict:
    """Delete journal trades whose TUS source was removed (reset). Review notes are kept."""
    ensure_schema(conn)
    rows = conn.execute("SELECT account_id, trade_group FROM tus_import_map WHERE removed_from_tus_at IS NOT NULL "
                        "AND deleted_in_journal_at IS NULL").fetchall()
    for r in rows:
        conn.execute("DELETE FROM trades WHERE account_id=? AND trade_group=? AND source=?", (r[0], r[1], SOURCE))
    conn.execute("UPDATE tus_import_map SET deleted_in_journal_at=? WHERE removed_from_tus_at IS NOT NULL "
                 "AND deleted_in_journal_at IS NULL", (_utcnow(),))
    conn.commit()
    return {'purged': len(rows)}


# ── background sync ───────────────────────────────────────────────────────────

class AutoImporter:
    """Polls the journal signature and imports when it changes. One instance per process."""

    def __init__(self, connect, interval: float = 10.0):
        self.connect, self.interval = connect, interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_result: dict | None = None
        self.last_error: str | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name='tus-auto-import', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn = self.connect()
                try:
                    result = run_import(conn, trigger='auto', signature_check=True)
                    if not result.get('skipped'):
                        self.last_result = result
                    self.last_error = None if result.get('ok') else result.get('error') or result.get('reason')
                finally:
                    conn.close()
            except Exception as exc:  # keep the service alive; surface the error in status
                self.last_error = repr(exc)
            self._stop.wait(self.interval)
