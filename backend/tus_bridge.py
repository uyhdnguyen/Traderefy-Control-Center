"""TEM bridge heartbeat diagnostics (read-only). R10.

Kept for the /api/tus/snapshot contract used since R8. Changes from R8.2/R9:
  * The bridge folder is no longer listed on every request (it can hold 200k+
    abandoned .tmp files). Known files are read directly; other TEM files come
    from nt_telemetry's bounded, cached discovery scan.
  * Files are opened with delete-sharing on Windows so a TCC read can never make
    TEM's File.Replace fail.
  * Paths come from nt_paths, the same resolver as the journal and telemetry.
An account heartbeat proves a TEM instance is running; it does not prove that
TUS or TEE are running. Use /api/tcc/live for per-engine status.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import nt_paths
import nt_telemetry

FRESH_SECONDS = 15
MAX_BYTES = 128 * 1024
HEARTBEAT = re.compile(r'^(?:auto_heartbeat_|account_heartbeat_|heartbeat\.txt$)', re.I)


def bridge_roots() -> list[Path]:
    return [nt / 'tus_sim_bridge' for nt in nt_paths.ninjatrader_candidates()]


def inspect_file(path: Path, now: float | None = None) -> dict | None:
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
        if stat.st_size > MAX_BYTES:
            return {'file': path.name, 'status': 'oversized', 'bytes': stat.st_size, 'fresh': False}
        raw = nt_paths.read_text(path, MAX_BYTES).strip()
        fields = raw.split('|')
        age = now - stat.st_mtime
        heartbeat_age = None
        if HEARTBEAT.match(path.name) and fields:
            try:
                heartbeat_age = now - nt_paths.dotnet_ticks_to_unix(int(fields[0]))
            except (ValueError, OverflowError):
                pass
        fresh = (heartbeat_age is not None and -5 <= heartbeat_age <= FRESH_SECONDS and -5 <= age <= FRESH_SECONDS)
        return {'file': path.name, 'status': 'read', 'modified_age_seconds': round(age, 1),
                'heartbeat_age_seconds': round(heartbeat_age, 1) if heartbeat_age is not None else None,
                'fresh': fresh,
                'content': raw[:4000] if path.name.startswith(('auto_heartbeat_', 'auto_diagnostic_', 'account_heartbeat_')) else None}
    except (OSError, UnicodeError):
        return {'file': path.name, 'status': 'unreadable', 'fresh': False}


def snapshot_data(roots=None) -> dict:
    now = datetime.now(timezone.utc).timestamp()
    roots = [Path(r) for r in roots] if roots is not None else bridge_roots()
    inspected, files, seen = [], [], set()
    for root in roots:
        if not root.is_dir():
            inspected.append({'path': str(root), 'exists': False})
            continue
        discovery = nt_telemetry.discover_bridge(root)
        inspected.append({'path': str(root), 'exists': True, 'ignored_temporary_files': discovery.get('tmp_count'),
                          'discovery_scanned_entries': discovery.get('scanned'),
                          'discovery_age_seconds': round(now - discovery['at'], 1) if discovery.get('at') else None})
        for name in ['heartbeat.txt', 'order_status.txt'] + list(discovery.get('names', [])):
            path = root / name
            canonical = str(path.resolve())
            if canonical in seen:
                continue
            seen.add(canonical)
            result = inspect_file(path, now)
            if result is not None:
                files.append(result)
    files.sort(key=lambda f: (not HEARTBEAT.match(f['file']), f.get('heartbeat_age_seconds') or 1e12))
    fresh = [f for f in files if HEARTBEAT.match(f['file']) and f.get('fresh')]
    existing = any(r.get('exists') for r in inspected)
    reason = ('Fresh TEM heartbeat detected' if fresh else
              'No fresh completed TEM heartbeat detected' if existing else
              'NinjaTrader bridge directory not found')
    return {'connected': bool(fresh), 'reason': reason, 'files': files[:120],
            'heartbeat_count': sum(bool(HEARTBEAT.match(f['file'])) for f in files),
            'fresh_heartbeat_count': len(fresh), 'read_only': True,
            'positions_available': False, 'orders_available': False,
            'engine_connections_verified': False, 'bridge_paths_checked': inspected,
            'note': 'TEM heartbeat only. Per-engine, per-instrument status: /api/tcc/live',
            'checked_at': datetime.now(timezone.utc).isoformat()}
