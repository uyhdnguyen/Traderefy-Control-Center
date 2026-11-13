"""Live, instrument-scoped NinjaTrader telemetry for the TCC Dashboard (R10).

Read-only. Every value returned here comes from a file an engine actually wrote;
nothing is inferred from another engine's heartbeat:

  TUS (M5)   Traderefy/TUS_FTR_Levels_<ROOT>.status   ticks|instrument + AUTO/MANUAL levels
             Traderefy/TUS_FTR_Trend_<ROOT>.status    ticks|instrument|overall|PP|M15|M60
             Traderefy/TUS_Real_Signal_Journal_<ROOT>.csv   signals and their routing status
  TEE (699)  Traderefy/FTR_699_<ROOT>.status          ticks|instrument|EVENT|payload
             Traderefy/FTR_699_Candidates_<ROOT>.csv  FTR candidates
  TEM        tus_sim_bridge/account_heartbeat_<ACCT>_<INST>.txt, auto_heartbeat_<KEY>.txt,
             auto_diagnostic_<KEY>.txt, auto_events_<KEY>.log, order_status[_<ACCT>_<INST>].txt
  Journal    Traderefy/Journal/TUS_Execution_Master.csv  (open positions = fills since last flat)
  Mode       Traderefy/TUS_Playback_Mode.txt          SIM | PLAYBACK(ON) | OFF

The bridge folder can contain hundreds of thousands of abandoned .tmp files, so it
is never listed on a request: known names are probed directly and a bounded
discovery scan runs at most every DISCOVERY_TTL seconds.
"""
from __future__ import annotations

import csv
import io
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import nt_paths

FAMILIES = {           # dashboard family -> roots in preference order (micros first)
    'ES': ['MES', 'ES'],
    'NQ': ['MNQ', 'NQ'],
    'YM': ['MYM', 'YM'],
}
POINT_VALUES = {'MES': 5.0, 'ES': 50.0, 'MNQ': 2.0, 'NQ': 20.0, 'MYM': 0.5, 'YM': 5.0}
KNOWN_TEM_ACCOUNTS = ['SimIBS', 'SimFTR', 'Playback101', 'Sim101']
TEM_FRESH_SECONDS = 15          # TEM writes every 2 s
CHART_FRESH_SECONDS = 90        # TUS/TEE publish on market data; quiet markets publish less
DISCOVERY_TTL = 300
DISCOVERY_MAX_ENTRIES = 600_000
SMALL = 256 * 1024

_discovery_lock = threading.Lock()
_discovery: dict = {'at': 0.0, 'dir': None, 'names': [], 'tmp_count': 0, 'scanned': 0,
                    'truncated': False, 'error': None, 'seconds': None}


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def _num(text):
    try:
        value = float(text)
        return value if value == value and value not in (float('inf'), float('-inf')) else None
    except (TypeError, ValueError):
        return None


def _safe_key(instrument: str) -> str:
    return instrument.replace(' ', '_').replace('/', '_')


def _read_status(path: Path, now: float):
    """Header-ticked status file -> (lines, age_from_ticks, mtime_age) or None."""
    try:
        if not path.is_file():
            return None
        text = nt_paths.read_text(path, max_bytes=SMALL)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            return {'lines': [], 'age': None, 'mtime_age': nt_paths.file_age_seconds(path, now)}
        head = lines[0].split('|')
        age = None
        try:
            age = round(now - nt_paths.dotnet_ticks_to_unix(int(head[0])), 1)
        except (ValueError, IndexError, OverflowError):
            pass
        return {'lines': lines, 'head': head, 'age': age, 'mtime_age': nt_paths.file_age_seconds(path, now)}
    except OSError as exc:
        return {'error': str(exc), 'lines': [], 'age': None}


def _state(age, fresh_seconds):
    if age is None:
        return 'missing'
    if age < -5:
        return 'clock_skew'
    return 'live' if age <= fresh_seconds else 'stale'


def market_session(now: float) -> dict:
    """CME equity-index futures schedule in ET (no holiday calendar: holidays show as open)."""
    try:
        from zoneinfo import ZoneInfo
        et = datetime.fromtimestamp(now, ZoneInfo('America/New_York'))
    except Exception:  # tzdata missing
        et = datetime.fromtimestamp(now, timezone(timedelta(hours=-5)))
    wd, hm = et.weekday(), et.hour * 60 + et.minute
    closed = (wd == 5) or (wd == 4 and hm >= 17 * 60) or (wd == 6 and hm < 18 * 60) or (17 * 60 <= hm < 18 * 60)
    rth = (wd < 5) and (9 * 60 + 30 <= hm < 16 * 60)
    return {'open': not closed, 'rth': rth, 'et_time': et.strftime('%Y-%m-%d %H:%M:%S'),
            'note': 'Simplified CME schedule; exchange holidays are not modelled.'}


# ── bridge discovery (bounded, cached) ────────────────────────────────────────

_DISCOVER = re.compile(r'^(account_heartbeat_|auto_heartbeat_|auto_diagnostic_|auto_events_|order_status)', re.I)


def discover_bridge(bridge: Path | None, force: bool = False) -> dict:
    """Names of TEM files in the bridge folder; cached, bounded, .tmp files only counted."""
    if bridge is None:
        return {'names': [], 'tmp_count': 0, 'at': None, 'error': 'bridge folder not found'}
    with _discovery_lock:
        fresh = (time.time() - _discovery['at'] < DISCOVERY_TTL and _discovery['dir'] == str(bridge))
        if fresh and not force:
            return dict(_discovery)
        started = time.time()
        names, tmp, scanned, truncated, error = [], 0, 0, False, None
        try:
            with os.scandir(bridge) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > DISCOVERY_MAX_ENTRIES:
                        truncated = True
                        break
                    name = entry.name
                    if name.lower().endswith('.tmp'):
                        tmp += 1
                    elif _DISCOVER.match(name):
                        names.append(name)
        except OSError as exc:
            error = str(exc)
        _discovery.update({'at': time.time(), 'dir': str(bridge), 'names': sorted(names), 'tmp_count': tmp,
                           'scanned': scanned, 'truncated': truncated, 'error': error,
                           'seconds': round(time.time() - started, 2)})
        return dict(_discovery)


# ── per-engine readers ────────────────────────────────────────────────────────

def read_levels(traderefy: Path, root: str, now: float) -> dict:
    path = traderefy / f'TUS_FTR_Levels_{root}.status'
    status = _read_status(path, now)
    if not status or not status.get('lines'):
        return {'state': 'missing', 'file': str(path), 'items': []}
    head = status.get('head') or []
    items = []
    for line in status['lines'][1:]:
        parts = line.split('|')
        if len(parts) < 3:
            continue
        price = _num(parts[2])
        if price is None:
            continue
        color = parts[3].strip() if len(parts) > 3 else ''
        if color and not color.startswith('#'):
            color = '#' + color
        items.append({'source': parts[0], 'name': parts[1], 'price': price, 'color': color or None})
    by_name = {i['name'].upper(): i['price'] for i in items if i['source'] == 'AUTO'}
    return {'state': _state(status['age'], CHART_FRESH_SECONDS), 'age_seconds': status['age'],
            'file': str(path), 'instrument': head[1] if len(head) > 1 else None, 'items': items,
            'orb': {'high': by_name.get('ORB HIGH'), 'low': by_name.get('ORB LOW')},
            'previous_day': {k: by_name.get(k) for k in ('PDO', 'PDH', 'PDL', 'PDC')},
            'manual': [i['price'] for i in items if i['source'] == 'MANUAL']}


def read_trend(traderefy: Path, root: str, now: float) -> dict:
    path = traderefy / f'TUS_FTR_Trend_{root}.status'
    status = _read_status(path, now)
    if not status or not status.get('lines'):
        return {'state': 'missing', 'file': str(path)}
    parts = status['lines'][0].split('|')

    def vote(i):
        try:
            return int(parts[i])
        except (ValueError, IndexError):
            return None
    return {'state': _state(status['age'], CHART_FRESH_SECONDS), 'age_seconds': status['age'], 'file': str(path),
            'instrument': parts[1] if len(parts) > 1 else None,
            'overall': vote(2), 'pp': vote(3), 'm15': vote(4), 'm60': vote(5)}


def read_tee(traderefy: Path, root: str, now: float) -> dict:
    path = traderefy / f'FTR_699_{root}.status'
    status = _read_status(path, now)
    if not status or not status.get('lines'):
        return {'state': 'missing', 'file': str(path)}
    parts = status['lines'][0].split('|', 3)
    payload = parts[3] if len(parts) > 3 else ''
    bar = None
    match = re.search(r'bar=(\d+)', payload)
    if match:
        bar = int(match.group(1))
    return {'state': _state(status['age'], CHART_FRESH_SECONDS), 'age_seconds': status['age'], 'file': str(path),
            'instrument': parts[1] if len(parts) > 1 else None,
            'event': parts[2] if len(parts) > 2 else None, 'payload': payload[:300], 'bar': bar}


def read_candidates(traderefy: Path, root: str, limit: int = 8) -> list[dict]:
    """TEE FTR candidates. Older files keep an 8-column header with 13-column rows."""
    path = traderefy / f'FTR_699_Candidates_{root}.csv'
    if not path.is_file():
        return []
    cols = ['time', 'instrument', 'direction', 'entry', 'tp1', 'range_low', 'range_high', 'status',
            'tp2', 'touch', 'swing', 'atr', 'swing_time']
    rows = []
    for line in nt_paths.tail_lines(path, limit + 1):
        cells = next(csv.reader([line]), [])
        if not cells or cells[0] == 'Timestamp':
            continue
        row = dict(zip(cols, cells))
        for k in ('entry', 'tp1', 'tp2', 'range_low', 'range_high', 'swing', 'atr'):
            if k in row:
                row[k] = _num(row[k])
        row['family'] = 'FTR'
        row['source'] = 'TEE 699 candidate'
        rows.append(row)
    return rows[-limit:]


SIGNAL_STAGE = [
    (re.compile(r'^PHASE10_SIM_QUEUED|QUEUED', re.I), 'sent_to_tem'),
    (re.compile(r'^REJECT', re.I), 'rejected'),
    (re.compile(r'APPROV', re.I), 'approval_pending'),
    (re.compile(r'EXPIRE', re.I), 'expired'),
    (re.compile(r'CANCEL', re.I), 'cancelled'),
]


def read_signals(traderefy: Path, root: str, limit: int = 10) -> list[dict]:
    path = traderefy / f'TUS_Real_Signal_Journal_{root}.csv'
    if not path.is_file():
        return []
    header = ['RecordedUtc', 'Family', 'SignalId', 'Instrument', 'Direction', 'Entry50', 'SwingStop',
              'TP1', 'TP2', 'RiskUsd', 'Status']
    out = []
    for line in nt_paths.tail_lines(path, limit + 1):
        cells = next(csv.reader([line]), [])
        if not cells or cells[0] == 'RecordedUtc':
            continue
        r = dict(zip(header, cells))
        stage = 'detected'
        for pattern, label in SIGNAL_STAGE:
            if pattern.search(r.get('Status', '')):
                stage = label
                break
        out.append({'time': r.get('RecordedUtc'), 'family': r.get('Family'), 'signal_id': r.get('SignalId'),
                    'instrument': r.get('Instrument'), 'direction': r.get('Direction'),
                    'entry': _num(r.get('Entry50')), 'stop': _num(r.get('SwingStop')),
                    'tp1': _num(r.get('TP1')), 'tp2': _num(r.get('TP2')), 'risk_usd': _num(r.get('RiskUsd')),
                    'status': r.get('Status'), 'stage': stage, 'source': 'TUS signal journal'})
    return out[-limit:]


def _tem_key_candidates(account: str, instrument: str) -> list[str]:
    base = f'{account}_{_safe_key(instrument)}'
    return [base, base + '_IBS', base + '_FTR'] if account.lower().startswith('playback') else [base]


def read_tem(bridge: Path | None, instrument: str | None, discovered: list[str], now: float,
             events_limit: int = 8) -> list[dict]:
    """One entry per TEM instance (account x instrument[x family]) seen for this instrument."""
    if bridge is None or not instrument:
        return []
    suffix = _safe_key(instrument)
    accounts = set(KNOWN_TEM_ACCOUNTS)
    for name in discovered:
        m = re.match(r'^(?:account_heartbeat_|auto_heartbeat_|auto_diagnostic_|auto_events_|order_status_)(.+?)_'
                     + re.escape(suffix) + r'(?:_IBS|_FTR)?\.(?:txt|log)$', name)
        if m:
            accounts.add(m.group(1))
    result = []
    for account in sorted(accounts):
        # Account heartbeat and scoped order status are per account x instrument;
        # auto heartbeat / diagnostics / events are per TEM key (Playback adds a family).
        hb = _read_status(bridge / f'account_heartbeat_{account}_{suffix}.txt', now)
        scoped = _read_status(bridge / f'order_status_{account}_{suffix}.txt', now)
        keys = []
        for key in _tem_key_candidates(account, instrument):
            if any((bridge / f'{prefix}{key}.{ext}').is_file() for prefix, ext in
                   (('auto_heartbeat_', 'txt'), ('auto_diagnostic_', 'txt'), ('auto_events_', 'log'))):
                keys.append(key)
        if not keys and (hb or scoped):
            keys = [f'{account}_{suffix}']
        for key in keys:
            auto = _read_status(bridge / f'auto_heartbeat_{key}.txt', now)
            diag = _read_status(bridge / f'auto_diagnostic_{key}.txt', now)
            events_path = bridge / f'auto_events_{key}.log'
            entry = {'account': account, 'key': key, 'instrument': instrument,
                     'family': 'IBS' if key.endswith('_IBS') or account == 'SimIBS' else
                               'FTR' if key.endswith('_FTR') or account == 'SimFTR' else None,
                     'heartbeat': {'state': _state((hb or {}).get('age'), TEM_FRESH_SECONDS),
                                   'age_seconds': (hb or {}).get('age')},
                     'auto_route': {'state': _state((auto or {}).get('age'), TEM_FRESH_SECONDS),
                                    'age_seconds': (auto or {}).get('age')}}
            if diag and diag.get('lines'):
                parts = diag['lines'][0].split('|', 2)
                entry['last_diagnostic'] = {'code': parts[1] if len(parts) > 1 else None,
                                            'detail': (parts[2] if len(parts) > 2 else '')[:300],
                                            'age_seconds': diag.get('age')}
            if scoped and scoped.get('lines'):
                parts = scoped['lines'][0].split('|', 4)
                entry['order_status'] = {'status': parts[3] if len(parts) > 3 else None,
                                         'detail': (parts[4] if len(parts) > 4 else '')[:300],
                                         'age_seconds': scoped.get('age'), 'scoped': True}
            if events_path.is_file():
                events = []
                for line in nt_paths.tail_lines(events_path, events_limit):
                    parts = [p.strip() for p in line.split('|', 2)]
                    events.append({'time': parts[0], 'code': parts[1] if len(parts) > 1 else '',
                                   'detail': (parts[2] if len(parts) > 2 else '')[:240]})
                entry['events'] = events
            entry['live'] = entry['heartbeat']['state'] == 'live' or entry['auto_route']['state'] == 'live'
            result.append(entry)
    return result


def read_shared_order_status(bridge: Path | None, now: float) -> dict | None:
    if bridge is None:
        return None
    status = _read_status(bridge / 'order_status.txt', now)
    if not status or not status.get('lines'):
        return None
    parts = status['lines'][0].split('|', 4)
    return {'account': parts[1] if len(parts) > 1 else None, 'instrument': parts[2] if len(parts) > 2 else None,
            'status': parts[3] if len(parts) > 3 else None, 'detail': (parts[4] if len(parts) > 4 else '')[:300],
            'age_seconds': status.get('age'),
            'note': 'Shared file: last writer among all TEM instances.'}


def open_positions(journal: Path | None, limit_bytes: int = 8 * 1024 * 1024) -> dict:
    """Net open quantity per (account, instrument) from TUS's execution ledger.

    TUS journals every NinjaTrader account execution it observes. A position is
    open when the signed sum of fills since the last flat point is non-zero.
    """
    result: dict = {}
    if journal is None:
        return result
    path = journal / 'TUS_Execution_Master.csv'
    if not path.is_file():
        return result
    try:
        text = nt_paths.read_text(path, max_bytes=limit_bytes)
    except OSError:
        return result
    rows = list(csv.DictReader(io.StringIO(text)))
    rows.sort(key=lambda r: (r.get('Time') or '', r.get('ExecutionId') or ''))
    book: dict = {}
    for r in rows:
        try:
            qty = int(float(r.get('Quantity') or 0))
            price = float(r.get('Price') or 0)
        except ValueError:
            continue
        sign = 1 if r.get('Action') in ('Buy', 'BuyToCover') else -1
        key = (r.get('Account') or '', r.get('Instrument') or '')
        pos = book.setdefault(key, {'qty': 0, 'cost': 0.0, 'opened': None, 'fills': 0})
        if pos['qty'] == 0:
            pos.update({'cost': 0.0, 'opened': r.get('Time'), 'fills': 0})
        if pos['qty'] == 0 or (pos['qty'] > 0) == (sign > 0):
            pos['cost'] += price * qty
        else:
            close = min(abs(pos['qty']), qty)
            avg = pos['cost'] / abs(pos['qty']) if pos['qty'] else 0
            pos['cost'] -= avg * close
            if qty > close:  # reversal: remainder opens the other side
                pos['cost'] = price * (qty - close)
                pos['opened'] = r.get('Time')
        pos['qty'] += sign * qty
        pos['fills'] += 1
    for (account, instrument), pos in book.items():
        if pos['qty'] != 0:
            result.setdefault(instrument, []).append({
                'account': account, 'instrument': instrument, 'quantity': pos['qty'],
                'side': 'LONG' if pos['qty'] > 0 else 'SHORT',
                'average_price': round(pos['cost'] / abs(pos['qty']), 4),
                'opened': pos['opened'], 'fills_since_flat': pos['fills'],
                'source': 'TUS_Execution_Master.csv (fills observed by TUS)'})
    return result


def read_execution_mode(traderefy: Path | None, now: float) -> dict:
    if traderefy is None:
        return {'value': None, 'state': 'missing'}
    path = traderefy / 'TUS_Playback_Mode.txt'
    if not path.is_file():
        return {'value': 'OFF', 'state': 'default', 'file': str(path),
                'note': 'File absent: TUS treats execution mode as OFF.'}
    raw = nt_paths.read_text(path, 256).strip().upper()
    value = 'PLAYBACK' if raw in ('ON', 'PLAYBACK') else raw or 'OFF'
    return {'value': value, 'raw': raw, 'state': 'read', 'file': str(path),
            'age_seconds': nt_paths.file_age_seconds(path, now),
            'note': 'TUS automation routing mode (SIM -> SimIBS/SimFTR, PLAYBACK -> Playback101). '
                    'It is not the data-feed connection.'}


# ── snapshot ──────────────────────────────────────────────────────────────────

def _pick_root(traderefy: Path, roots: list[str], now: float) -> tuple[str | None, list[dict]]:
    seen = []
    for root in roots:
        ages = []
        for name in (f'TUS_FTR_Levels_{root}.status', f'TUS_FTR_Trend_{root}.status', f'FTR_699_{root}.status'):
            age = nt_paths.file_age_seconds(traderefy / name, now)
            if age is not None:
                ages.append(age)
        if ages:
            seen.append({'root': root, 'freshest_file_age_seconds': min(ages)})
    if not seen:
        return None, seen
    seen.sort(key=lambda s: s['freshest_file_age_seconds'])
    return seen[0]['root'], seen


def instrument_snapshot(family: str, nt: Path | None, now: float, discovered: list[str],
                        positions: dict) -> dict:
    traderefy, bridge = nt_paths.traderefy_dir(nt), nt_paths.bridge_dir(nt)
    out = {'family': family, 'roots_considered': FAMILIES[family], 'root': None, 'instrument': None}
    if traderefy is None or not traderefy.is_dir():
        out['state'] = 'no_ninjatrader_folder'
        return out
    root, seen = _pick_root(traderefy, FAMILIES[family], now)
    out['roots_seen'] = seen
    if root is None:
        out['state'] = 'no_charts'
        out['detail'] = (f'No TUS/TEE publication for {" or ".join(FAMILIES[family])}. '
                         f'Open the M5 TUS and 699-tick TEE charts for this market.')
        return out
    levels, trend, tee = read_levels(traderefy, root, now), read_trend(traderefy, root, now), read_tee(traderefy, root, now)
    instrument = levels.get('instrument') or trend.get('instrument') or tee.get('instrument')
    tem = read_tem(bridge, instrument, discovered, now)
    out.update({
        'root': root, 'instrument': instrument, 'point_value': POINT_VALUES.get(root),
        'engines': {
            'tus_m5': {'state': levels['state'] if levels['state'] != 'missing' else trend['state'],
                       'age_seconds': min([a for a in (levels.get('age_seconds'), trend.get('age_seconds')) if a is not None], default=None),
                       'evidence': 'TUS_FTR_Levels/Trend publication (M5 chart, realtime only)'},
            'tee_699': {'state': tee['state'], 'age_seconds': tee.get('age_seconds'), 'event': tee.get('event'),
                        'bar': tee.get('bar'), 'evidence': 'FTR_699 status publication (699-tick chart, realtime only)'},
            'tem': {'state': 'live' if any(t['live'] for t in tem) else ('stale' if tem else 'missing'),
                    'instances': len(tem), 'live_instances': sum(t['live'] for t in tem),
                    'evidence': 'account/auto heartbeats per TEM instance (every 2 s)'},
        },
        'trend': trend, 'levels': levels, 'tee': tee, 'tem': tem,
        'setups': {'signals': read_signals(traderefy, root), 'candidates': read_candidates(traderefy, root)},
        'positions': positions.get(instrument, []) if instrument else [],
    })
    states = [e['state'] for e in out['engines'].values()]
    out['state'] = ('live' if all(s == 'live' for s in states) else
                    'partial' if any(s == 'live' for s in states) else 'stale')
    return out


def live_snapshot(nt: Path | None = None, now: float | None = None, force_discovery: bool = False) -> dict:
    now = _now() if now is None else now
    nt = nt or nt_paths.ninjatrader_dir()
    bridge, traderefy, journal = nt_paths.bridge_dir(nt), nt_paths.traderefy_dir(nt), nt_paths.journal_dir(nt)
    discovery = discover_bridge(bridge if bridge and bridge.is_dir() else None, force=force_discovery)
    positions = open_positions(journal if journal and journal.is_dir() else None)
    markets = [instrument_snapshot(f, nt, now, discovery.get('names', []), positions) for f in FAMILIES]
    shared_hb = None
    if bridge is not None:
        hb = _read_status(bridge / 'heartbeat.txt', now)
        if hb and hb.get('lines'):
            parts = hb['lines'][0].split('|')
            shared_hb = {'age_seconds': hb['age'], 'state': _state(hb['age'], TEM_FRESH_SECONDS),
                         'account': parts[1] if len(parts) > 1 else None,
                         'instrument': parts[2] if len(parts) > 2 else None,
                         'note': 'Shared heartbeat: proves only that at least one TEM instance is running.'}
    return {
        'checked_at': _iso(now), 'read_only': True,
        'ninjatrader_dir': str(nt) if nt else None,
        'paths': {'bridge': str(bridge) if bridge else None, 'traderefy': str(traderefy) if traderefy else None,
                  'journal': str(journal) if journal else None,
                  'candidates_checked': [str(p) for p in nt_paths.ninjatrader_candidates()]},
        'market_session': market_session(now),
        'execution_mode': read_execution_mode(traderefy if traderefy and traderefy.is_dir() else None, now),
        'markets': markets,
        'tem_shared_heartbeat': shared_hb,
        'tem_shared_order_status': read_shared_order_status(bridge if bridge and bridge.is_dir() else None, now),
        'bridge_discovery': {k: discovery.get(k) for k in ('tmp_count', 'scanned', 'truncated', 'error', 'seconds')}
                            | {'at': _iso(discovery.get('at')), 'tem_files': len(discovery.get('names', []))},
        'thresholds_seconds': {'tem': TEM_FRESH_SECONDS, 'charts': CHART_FRESH_SECONDS},
    }
