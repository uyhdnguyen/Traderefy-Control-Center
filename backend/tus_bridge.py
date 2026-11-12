"""Read-only NinjaTrader bridge discovery and heartbeat diagnostics.

No order submission or file mutations. An account heartbeat is not proof that
TUS, TEE, or TEM is connected independently.
"""
from pathlib import Path
from datetime import datetime, timezone
import os
import re
from fastapi import APIRouter

router = APIRouter(prefix='/api/tus', tags=['TUS read-only'])
MAX_BYTES = 128 * 1024
MAX_FILES = 80
FRESH_SECONDS = 15
TICKS_AT_UNIX_EPOCH = 621355968000000000
ALLOWED = re.compile(r'^(?:auto_heartbeat_|auto_diagnostic_|account_heartbeat_|heartbeat\.txt$|auto_events_|auto_command_)', re.I)
HEARTBEAT = re.compile(r'^(?:auto_heartbeat_|account_heartbeat_|heartbeat\.txt$)', re.I)


def bridge_roots():
    """Use the same Windows Documents location as TEM, including redirected folders."""
    documents = []
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(32768)
            # CSIDL_PERSONAL = 5; resolves redirected Documents folder.
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                documents.append(Path(buf.value))
        except (OSError, AttributeError, ValueError):
            pass
    documents.append(Path.home() / 'Documents')
    if os.environ.get('OneDrive'):
        documents.append(Path(os.environ['OneDrive']) / 'Documents')
    if os.environ.get('OneDriveCommercial'):
        documents.append(Path(os.environ['OneDriveCommercial']) / 'Documents')
    result = []
    for doc in documents:
        path = doc / 'NinjaTrader 8' / 'tus_sim_bridge'
        if path not in result:
            result.append(path)
    return result


def inspect_file(path, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
        if stat.st_size > MAX_BYTES:
            return {'file': path.name, 'status': 'oversized', 'bytes': stat.st_size, 'fresh': False}
        raw = path.read_text(encoding='utf-8-sig', errors='replace').strip()
        fields = raw.split('|')
        age = now - stat.st_mtime
        heartbeat_age = None
        if HEARTBEAT.match(path.name) and fields:
            try:
                heartbeat_age = now - (int(fields[0]) - TICKS_AT_UNIX_EPOCH) / 10000000
            except (ValueError, OverflowError):
                pass
        # Both the timestamp inside the file and its filesystem modification time
        # must be recent. Do not accept future-dated or stale heartbeats.
        fresh = (heartbeat_age is not None and -5 <= heartbeat_age <= FRESH_SECONDS
                 and -5 <= age <= FRESH_SECONDS)
        return {'file': path.name, 'status': 'read', 'modified_age_seconds': round(age, 1),
                'heartbeat_age_seconds': round(heartbeat_age, 1) if heartbeat_age is not None else None,
                'fresh': fresh,
                'content': raw[:4000] if path.name.startswith(('auto_heartbeat_', 'auto_diagnostic_', 'account_heartbeat_')) else None}
    except (OSError, UnicodeError):
        return {'file': path.name, 'status': 'unreadable', 'fresh': False}


def snapshot_data(roots=None):
    roots = bridge_roots() if roots is None else roots
    now = datetime.now(timezone.utc).timestamp()
    inspected_roots = []
    selected = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            inspected_roots.append({'path': str(root), 'exists': False})
            continue
        candidates = []
        ignored_tmp = 0
        try:
            # Bounded memory, no alphabetic sorting of 200k+ files. Keep the
            # newest matching files, with heartbeats preferred over logs.
            import heapq
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.name.lower().endswith('.tmp'):
                        ignored_tmp += 1
                        continue
                    if not ALLOWED.match(entry.name) or not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        mtime = entry.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    priority = 1 if HEARTBEAT.match(entry.name) else 0
                    key = (priority, mtime, entry.name)
                    item = (key, entry.path)
                    if len(candidates) < MAX_FILES:
                        heapq.heappush(candidates, item)
                    elif key > candidates[0][0]:
                        heapq.heapreplace(candidates, item)
            inspected_roots.append({'path': str(root), 'exists': True,
                                    'ignored_temporary_files': ignored_tmp})
            selected.extend((key, Path(path)) for key, path in candidates)
        except OSError as exc:
            inspected_roots.append({'path': str(root), 'exists': True, 'error': str(exc)})
    # Avoid duplicate entries if two paths resolve to the same location.
    seen = set()
    files = []
    for _, path in sorted(selected, key=lambda x: x[0], reverse=True):
        canonical = str(path.resolve())
        if canonical in seen:
            continue
        seen.add(canonical)
        result = inspect_file(path, now)
        if result is not None:
            files.append(result)
        if len(files) >= MAX_FILES:
            break
    fresh = [f for f in files if HEARTBEAT.match(f['file']) and f.get('fresh')]
    existing = any(r.get('exists') for r in inspected_roots)
    reason = ('Fresh account/bridge heartbeat detected' if fresh else
              'No fresh completed heartbeat detected' if existing else
              'NinjaTrader bridge directory not found')
    return {'connected': bool(fresh), 'reason': reason, 'files': files,
            'heartbeat_count': sum(bool(HEARTBEAT.match(f['file'])) for f in files),
            'fresh_heartbeat_count': len(fresh), 'read_only': True,
            'positions_available': False, 'orders_available': False,
            'engine_connections_verified': False, 'bridge_paths_checked': inspected_roots,
            'checked_at': datetime.now(timezone.utc).isoformat()}


@router.get('/snapshot')
def snapshot():
    return snapshot_data()
