"""TUS journal reader (pure logic, read-only). R10.

Source of truth: <NinjaTrader 8>/Traderefy/Journal, written by TUS (TraderefyUltimateSystem.cs):

  TUS_Trade_Master.csv      one row per completed flat-to-flat position cycle per account+instrument.
                            A two-leg IBS/FTR trade (TP1 + TP2) is ONE row with Quantity 2 and all
                            entry/exit execution ids in ExecutionIds. Never count its fills as trades.
  TUS_Execution_Master.csv  every execution TUS observed (ExecutionId = "Account|Instrument|NT id").
  TUS_Trade_Setup_Tags.csv  TradeId -> setup chosen in the TUS journal UI.
  TUS_Manual_Trade_Groups.tsv  "<group id>\t<base64(TradeId)>" calendar grouping.
  TUS_Account_Reset.csv     Account -> ResetUtc watermark (UTC, ISO 8601 with Z).
  TUS_Approved_Trades.csv   TUS journal approvals (Status APPROVED in the master).
  ../TUS_SIM_Forward_Fills.tsv  TEM entry fills: setup, risk mode, signal id, stop at entry.

Times in the trade/execution files are NinjaTrader local wall-clock times without an
offset (DateTime.Kind Unspecified). TUS compares them with ToUniversalTime(), i.e. as the
PC's local time zone; this module does the same (override with TCC_NT_TIMEZONE).
"""
from __future__ import annotations

import base64
import csv
import io
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import nt_paths

FILES = {
    'trades': 'TUS_Trade_Master.csv',
    'executions': 'TUS_Execution_Master.csv',
    'approved': 'TUS_Approved_Trades.csv',
    'tags': 'TUS_Trade_Setup_Tags.csv',
    'resets': 'TUS_Account_Reset.csv',
    'groups': 'TUS_Manual_Trade_Groups.tsv',
}
FORWARD_FILLS = 'TUS_SIM_Forward_Fills.tsv'
MAX_SIZE = 40 * 1024 * 1024
MAX_ROWS = 150000


def local_zone():
    name = os.environ.get('TCC_NT_TIMEZONE', '').strip()
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            pass
    return None  # system local time zone


def parse_nt_time(value: str | None) -> datetime | None:
    """NinjaTrader 'o' timestamp -> aware UTC datetime. Naive values are NT local time."""
    if not value:
        return None
    text = value.strip().replace('Z', '+00:00')
    # .NET writes 7 fractional digits; Python < 3.11 accepts at most 6.
    if '.' in text:
        head, _, frac = text.partition('.')
        n = 0
        while n < len(frac) and frac[n].isdigit():
            n += 1
        digits, rest = frac[:n], frac[n:]
        text = f"{head}.{digits[:6].ljust(6, '0')}{rest}"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        zone = local_zone()
        dt = dt.replace(tzinfo=zone) if zone else dt.astimezone()
    return dt.astimezone(timezone.utc)


def is_playback_account(name: str | None) -> bool:
    return bool(name) and name.strip().lower().startswith('playback')


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    if path.stat().st_size > MAX_SIZE:
        raise ValueError(f'{path.name} exceeds {MAX_SIZE} bytes')
    text = nt_paths.read_text(path, max_bytes=MAX_SIZE)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    out = []
    for i, row in enumerate(reader):
        if i >= MAX_ROWS:
            raise ValueError(f'{path.name} exceeds {MAX_ROWS} rows')
        if row.get(None):
            continue  # malformed row: never misattribute fills
        out.append({str(k).strip(): (v or '').strip() for k, v in row.items()})
    return out


def _read_groups(path: Path) -> dict:
    if not path.is_file():
        return {}
    result = {}
    for line in nt_paths.read_text(path, max_bytes=MAX_SIZE).splitlines():
        parts = line.rstrip('\r\n').split('\t')
        if len(parts) != 2 or not parts[0]:
            continue
        try:
            trade_id = base64.b64decode(parts[1], validate=True).decode('utf-8')
        except (ValueError, UnicodeError):
            continue
        if trade_id:
            result[trade_id] = parts[0]
    return result


def read_forward_fills(path: Path) -> dict:
    """NT execution id -> TEM entry metadata (setup, stop, signal)."""
    result = {}
    if not path.is_file():
        return result
    for line in nt_paths.read_text(path, max_bytes=MAX_SIZE).splitlines():
        f = line.split('\t')
        if len(f) < 11:
            continue
        try:
            stop = float(f[10])
            price = float(f[9])
        except ValueError:
            continue
        result[f[7]] = {'time': f[0], 'account': f[1], 'instrument': f[2], 'setup': f[3],
                        'risk_mode': f[4], 'signal_id': f[5], 'command_id': f[6],
                        'entry_price': price, 'stop': stop}
    return result


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_journal(root: Path) -> dict:
    """Parse one journal folder into completed trades with their own fills attached."""
    raw = {name: _read_csv(root / filename) for name, filename in FILES.items() if name != 'groups'}
    groups = _read_groups(root / FILES['groups'])
    forward = read_forward_fills(root.parent / FORWARD_FILLS)
    tags = {r.get('TradeId'): r.get('Setup') for r in raw['tags'] if r.get('TradeId')}
    resets = {r.get('Account'): parse_nt_time(r.get('ResetUtc')) for r in raw['resets'] if r.get('Account')}
    approved = {r.get('TradeId') for r in raw['approved'] if r.get('TradeId')}
    by_execution = {r.get('ExecutionId'): r for r in raw['executions'] if r.get('ExecutionId')}
    trades, seen, excluded_reset = [], set(), 0
    for r in raw['trades']:
        trade_id, account = r.get('TradeId', ''), r.get('Account', '')
        if not trade_id or not account or (account, trade_id) in seen:
            continue
        seen.add((account, trade_id))
        closed = parse_nt_time(r.get('CloseTime'))
        reset = resets.get(account)
        if reset and closed and closed <= reset:
            excluded_reset += 1
            continue
        ids = [x.strip() for x in r.get('ExecutionIds', '').split(';') if x.strip()]
        fills = [by_execution[x] for x in ids if x in by_execution and by_execution[x].get('Account') == account]
        forward_meta = [forward[x.split('|')[-1]] for x in ids if x.split('|')[-1] in forward]
        setup_tag = tags.get(trade_id)
        opened = parse_nt_time(r.get('OpenTime')) or closed
        trades.append({
            **r,
            'setup': setup_tag or 'Unclassified',
            'setup_tag': setup_tag if setup_tag and setup_tag != 'Unclassified' else None,
            'forward': forward_meta,
            'manual_group_id': groups.get(trade_id),
            'approved': trade_id in approved or r.get('Status') == 'APPROVED',
            'executions': fills, 'execution_count': len(fills),
            'missing_execution_ids': [x for x in ids if x not in by_execution],
            'playback': is_playback_account(account),
            'open_utc': opened.isoformat() if opened else None,
            'close_utc': closed.isoformat() if closed else None,
            'net_pnl': _float(r.get('NetPnl')), 'gross_pnl': _float(r.get('GrossPnl')),
            'commission': _float(r.get('Commission')),
        })
    trades.sort(key=lambda t: t.get('close_utc') or '', reverse=True)
    by_account = defaultdict(lambda: {'trades': 0, 'net_pnl': 0.0, 'playback': False})
    for t in trades:
        a = by_account[t['Account']]
        a['trades'] += 1
        a['net_pnl'] = round(a['net_pnl'] + (t['net_pnl'] or 0.0), 2)
        a['playback'] = t['playback']
    return {
        'source_directory': str(root),
        'files': {k: (root / v).is_file() for k, v in FILES.items()} | {'forward_fills': (root.parent / FORWARD_FILLS).is_file()},
        'trades': trades, 'trade_count': len(trades), 'execution_count': len(raw['executions']),
        'excluded_before_reset': excluded_reset,
        'playback_trade_count': sum(t['playback'] for t in trades),
        'sim_trade_count': sum(not t['playback'] for t in trades),
        'accounts': dict(by_account), 'read_only': True,
    }


def journal_roots() -> list[Path]:
    roots = []
    override = os.environ.get(nt_paths.ENV_JOURNAL_DIR, '').strip()
    if override:
        roots.append(Path(override).expanduser())
    for nt in nt_paths.ninjatrader_candidates():
        roots.append(nt / 'Traderefy' / 'Journal')
    return list(dict.fromkeys(roots))


def find_journal_root(roots: list[Path] | None = None) -> tuple[Path | None, list[dict]]:
    checked = []
    for root in (roots if roots is not None else journal_roots()):
        root = Path(root)
        exists = root.is_dir()
        has_master = exists and (root / FILES['trades']).is_file()
        checked.append({'path': str(root), 'exists': exists, 'trade_master': has_master})
        if has_master:
            return root, checked
    return None, checked


def journal_snapshot(roots=None) -> dict:
    root, checked = find_journal_root([Path(r) for r in roots] if roots is not None else None)
    if root is None:
        return {'available': False, 'paths_checked': checked, 'trades': [],
                'reason': 'TUS_Trade_Master.csv not found in the checked journal directories', 'read_only': True}
    try:
        return {'available': True, 'paths_checked': checked, **load_journal(root)}
    except (OSError, ValueError, csv.Error) as exc:
        return {'available': False, 'paths_checked': checked, 'error': str(exc), 'trades': []}


def source_signature(root: Path | None) -> str:
    """Cheap change detector: size + mtime of every journal input."""
    if root is None:
        return ''
    parts = []
    for path in [root / f for f in FILES.values()] + [root.parent / FORWARD_FILLS]:
        try:
            st = path.stat()
            parts.append(f'{path.name}:{st.st_size}:{st.st_mtime_ns}')
        except OSError:
            parts.append(f'{path.name}:-')
    return '|'.join(parts)
