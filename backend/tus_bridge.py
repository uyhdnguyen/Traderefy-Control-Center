"""Read-only local NinjaTrader bridge. Never creates, modifies, or removes bridge files."""
from pathlib import Path
from datetime import datetime, timezone
import os
import re
from fastapi import APIRouter

router = APIRouter(prefix='/api/tus', tags=['TUS read-only'])
ROOT = Path.home() / 'Documents' / 'NinjaTrader 8' / 'tus_sim_bridge'
ALLOWED = re.compile(r'^(auto_heartbeat_|auto_diagnostic_|account_heartbeat_|heartbeat\.txt$|auto_events_|auto_command_)')
MAX_BYTES = 128 * 1024


def bridge_root():
    # Only allow the standard local NinjaTrader bridge path; no user-controlled URL or path.
    return ROOT


def inspect_file(path):
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
        if stat.st_size > MAX_BYTES:
            return {'file': path.name, 'status': 'oversized', 'bytes': stat.st_size}
        raw = path.read_text(encoding='utf-8-sig', errors='replace').strip()
        age = max(0, (datetime.now(timezone.utc).timestamp() - stat.st_mtime))
        fields = raw.split('|')
        # NT timestamps are .NET ticks since year 0001, not Unix timestamps.
        heartbeat_age = None
        if path.name.startswith(('auto_heartbeat_', 'account_heartbeat_')) and fields:
            try:
                timestamp = (int(fields[0]) - 621355968000000000) / 10000000
                heartbeat_age = round(datetime.now(timezone.utc).timestamp() - timestamp, 1)
            except (ValueError, OverflowError):
                pass
        return {'file': path.name, 'status': 'read', 'modified_age_seconds': round(age, 1),
                'heartbeat_age_seconds': heartbeat_age,
                'fresh': heartbeat_age is not None and -5 <= heartbeat_age <= 15,
                'content': raw[:4000] if path.name.startswith(('auto_heartbeat_', 'auto_diagnostic_', 'account_heartbeat_')) else None}
    except (OSError, UnicodeError):
        return {'file': path.name, 'status': 'unreadable'}


@router.get('/snapshot')
def snapshot():
    root = bridge_root()
    if not root.is_dir():
        return {'connected': False, 'reason': 'NinjaTrader bridge directory not found', 'files': [], 'read_only': True}
    try:
        candidates = sorted((p for p in root.iterdir() if ALLOWED.match(p.name) and p.is_file() and not p.is_symlink()), key=lambda p: p.name)[:80]
        files = [v for p in candidates if (v := inspect_file(p)) is not None]
    except OSError:
        return {'connected': False, 'reason': 'Cannot read NinjaTrader bridge directory', 'files': [], 'read_only': True}
    heartbeat = [f for f in files if f['file'].startswith(('auto_heartbeat_', 'account_heartbeat_'))]
    fresh = [f for f in heartbeat if f.get('fresh')]
    return {'connected': bool(fresh), 'reason': 'Fresh heartbeat detected' if fresh else 'No fresh heartbeat detected',
            'files': files, 'heartbeat_count': len(heartbeat), 'fresh_heartbeat_count': len(fresh),
            'read_only': True, 'positions_available': False, 'orders_available': False,
            'checked_at': datetime.now(timezone.utc).isoformat()}
