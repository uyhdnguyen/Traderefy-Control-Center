"""Read-only, lossless TUS journal adapter. No order control, no DB mutation.

The TUS trade master is authoritative. Executions are children, not extra trades.
Manual group metadata is preserved separately; no cross-account merging.
"""
import base64
import csv
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from tus_bridge import bridge_roots

router = APIRouter(prefix='/api/tus/journal', tags=['TUS journal read-only'])
FILES = {
    'trades': 'TUS_Trade_Master.csv',
    'executions': 'TUS_Execution_Master.csv',
    'approved': 'TUS_Approved_Trades.csv',
    'tags': 'TUS_Trade_Setup_Tags.csv',
    'resets': 'TUS_Account_Reset.csv',
    'groups': 'TUS_Manual_Trade_Groups.tsv',
}
MAX_SIZE = 40 * 1024 * 1024
MAX_ROWS = 150000


def journal_roots():
    roots = []
    env = os.environ.get('TCC_NINJATRADER_JOURNAL_DIR', '').strip()
    if env:
        roots.append(Path(env).expanduser())
    # TEM bridge lives in Documents/NinjaTrader 8/tus_sim_bridge; the TUS journal
    # lives in NinjaTrader's UserDataDir/Traderefy/Journal (usually sibling path).
    for bridge in bridge_roots():
        roots.append(bridge.parent / 'Traderefy' / 'Journal')
    return list(dict.fromkeys(roots))


def _read_csv(path):
    if not path.is_file() or path.is_symlink():
        return []
    if path.stat().st_size > MAX_SIZE:
        raise ValueError(f'{path.name} exceeds {MAX_SIZE} bytes')
    with path.open('r', encoding='utf-8-sig', newline='', errors='replace') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            return []
        result = []
        for i, row in enumerate(reader):
            if i >= MAX_ROWS:
                raise ValueError(f'{path.name} exceeds {MAX_ROWS} rows')
            if row.get(None):
                continue  # reject malformed rows, do not misattribute executions
            result.append({str(k).strip(): (v or '').strip() for k, v in row.items()})
        return result


def _groups(path):
    if not path.is_file() or path.is_symlink():
        return {}
    if path.stat().st_size > MAX_SIZE:
        raise ValueError('Groups file too large')
    result = {}
    with path.open('r', encoding='utf-8-sig', errors='replace') as stream:
        for i, line in enumerate(stream):
            if i >= MAX_ROWS:
                raise ValueError('Groups file too large')
            parts = line.rstrip('\r\n').split('\t')
            if len(parts) != 2:
                continue
            try:
                # TUS stores "group id<TAB>base64(trade id)".
                trade_id = base64.b64decode(parts[1], validate=True).decode('utf-8')
            except (ValueError, UnicodeError):
                continue
            if trade_id and parts[0]:
                result[trade_id] = parts[0]
    return result


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def _load_root(root):
    raw = {name: _read_csv(root / filename) for name, filename in FILES.items() if name != 'groups'}
    groups = _groups(root / FILES['groups'])
    tags = {r.get('TradeId'): r.get('Setup') for r in raw['tags'] if r.get('TradeId')}
    resets = {r.get('Account'): _timestamp(r.get('ResetUtc')) for r in raw['resets'] if r.get('Account')}
    by_execution = {r.get('ExecutionId'): r for r in raw['executions'] if r.get('ExecutionId')}
    trades = []
    seen = set()
    for r in raw['trades']:
        trade_id, account = r.get('TradeId', ''), r.get('Account', '')
        if not trade_id or not account or (account, trade_id) in seen:
            continue
        seen.add((account, trade_id))
        closed = _timestamp(r.get('CloseTime'))
        reset = resets.get(account)
        if reset and closed and closed.tzinfo and reset.tzinfo and closed <= reset:
            continue
        ids = [x.strip() for x in r.get('ExecutionIds', '').split(';') if x.strip()]
        fills = [by_execution[x] for x in ids if x in by_execution and by_execution[x].get('Account') == account]
        is_playback = account.lower().startswith('playback')
        trades.append({**r, 'setup': tags.get(trade_id) or 'Unclassified',
                       'manual_group_id': groups.get(trade_id), 'executions': fills,
                       'execution_count': len(fills), 'missing_execution_ids': [x for x in ids if x not in by_execution],
                       'playback': is_playback, 'net_pnl': _float(r.get('NetPnl')),
                       'gross_pnl': _float(r.get('GrossPnl')),
                       'commission': _float(r.get('Commission'))})
    trades.sort(key=lambda r: r.get('CloseTime', ''), reverse=True)
    by_account = defaultdict(lambda: {'trades': 0, 'net_pnl': 0.0})
    for t in trades:
        by_account[t['Account']]['trades'] += 1
        by_account[t['Account']]['net_pnl'] += t['net_pnl'] or 0.0
    return {
        'source_directory': str(root), 'files': {k: (root / v).is_file() for k, v in FILES.items()},
        'trades': trades, 'trade_count': len(trades), 'execution_count': len(raw['executions']),
        'playback_trade_count': sum(t['playback'] for t in trades),
        'sim_trade_count': sum(not t['playback'] for t in trades),
        'accounts': dict(by_account), 'read_only': True,
        'database_imported': False, 'native_journal_analytics_synced': False,
        'note': 'Native TUS trade records shown read-only. Trading-Journal-AI database analytics are not yet synchronized.',
    }


def journal_snapshot(roots=None):
    roots = journal_roots() if roots is None else [Path(r) for r in roots]
    checked = []
    for root in roots:
        if not root.is_dir():
            checked.append({'path': str(root), 'exists': False})
            continue
        checked.append({'path': str(root), 'exists': True})
        if not (root / FILES['trades']).is_file():
            continue
        try:
            return {'available': True, 'paths_checked': checked, **_load_root(root)}
        except (OSError, ValueError, csv.Error) as exc:
            return {'available': False, 'paths_checked': checked, 'error': str(exc), 'trades': []}
    return {'available': False, 'paths_checked': checked, 'trades': [],
            'reason': 'TUS_Trade_Master.csv not found in the checked journal directories',
            'read_only': True, 'database_imported': False, 'native_journal_analytics_synced': False}


@router.get('/snapshot')
def snapshot():
    return journal_snapshot()
