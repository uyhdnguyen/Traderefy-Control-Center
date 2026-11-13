"""TCC routes for NinjaTrader telemetry and the TUS journal pipeline (R10).

  GET  /api/tus/snapshot            TEM heartbeat diagnostics (R8 contract)
  GET  /api/tus/journal/snapshot    TUS journal, read-only view + import mapping
  GET  /api/tcc/live                per-instrument TUS / TEE / TEM telemetry, setups, positions
  GET  /api/tcc/diagnostics         resolved paths, versions, importer state, file inventory
  GET  /api/tus/import/status       last import, per-account results, conflicts
  POST /api/tus/import/run          import now
  POST /api/tus/import/purge-removed  delete journal trades that TUS removed (explicit only)

No route here submits, modifies or cancels orders.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query

import nt_paths
import nt_telemetry
import tus_bridge
import tus_import
import tus_journal
from database import get_db

router = APIRouter(tags=['TCC NinjaTrader integration'])
_auto_importer: tus_import.AutoImporter | None = None


def _version() -> str:
    for base in (Path(getattr(sys, '_MEIPASS', '')), Path(__file__).resolve().parents[1]):
        try:
            return (base / 'VERSION').read_text().strip()
        except OSError:
            continue
    return 'unknown'


def start_auto_import() -> None:
    """Started from main.py on application startup (disable with TCC_TUS_AUTO_IMPORT=0)."""
    global _auto_importer
    if os.environ.get('TCC_TUS_AUTO_IMPORT', '1') == '0' or _auto_importer is not None:
        return
    _auto_importer = tus_import.AutoImporter(get_db, interval=float(os.environ.get('TCC_TUS_IMPORT_INTERVAL', '10')))
    _auto_importer.start()


def stop_auto_import() -> None:
    if _auto_importer is not None:
        _auto_importer.stop()


@router.get('/api/tus/snapshot')
def bridge_snapshot():
    return tus_bridge.snapshot_data()


@router.get('/api/tus/journal/snapshot')
def journal_snapshot():
    data = tus_journal.journal_snapshot()
    conn = get_db()
    try:
        tus_import.ensure_schema(conn)
        mapping = {(r['tus_account'], r['tus_trade_id']): dict(r) for r in conn.execute(
            "SELECT m.tus_account, m.tus_trade_id, m.account_id, m.trade_group, m.removed_from_tus_at, "
            "m.deleted_in_journal_at, m.conflict, t.id AS journal_trade_id, ta.r_multiple "
            "FROM tus_import_map m LEFT JOIN trades t ON t.account_id=m.account_id AND t.trade_group=m.trade_group "
            "LEFT JOIN trade_analysis ta ON ta.account_id=m.account_id AND ta.trade_group=m.trade_group")}
        for t in data.get('trades', []):
            m = mapping.get((t.get('Account'), t.get('TradeId')))
            t['journal'] = m
        data['database_imported'] = bool(mapping)
        data['native_journal_analytics_synced'] = bool(mapping)
        data['import_status'] = tus_import.import_status(conn)
    finally:
        conn.close()
    return data


@router.get('/api/tcc/live')
def live(refresh_discovery: bool = Query(False)):
    return nt_telemetry.live_snapshot(force_discovery=refresh_discovery)


@router.get('/api/tus/import/status')
def import_status():
    conn = get_db()
    try:
        status = tus_import.import_status(conn)
    finally:
        conn.close()
    status['auto_import'] = {
        'enabled': _auto_importer is not None,
        'interval_seconds': _auto_importer.interval if _auto_importer else None,
        'last_error': _auto_importer.last_error if _auto_importer else None,
    }
    return status


@router.post('/api/tus/import/run')
def import_run():
    conn = get_db()
    try:
        return tus_import.run_import(conn, trigger='manual')
    finally:
        conn.close()


@router.post('/api/tus/import/purge-removed')
def import_purge_removed():
    conn = get_db()
    try:
        return tus_import.purge_removed(conn)
    finally:
        conn.close()


@router.get('/api/tcc/diagnostics')
def diagnostics():
    """Everything needed to troubleshoot the pipeline from one URL."""
    now = datetime.now(timezone.utc).timestamp()
    nt = nt_paths.ninjatrader_dir()
    inventory = []
    for folder in (nt_paths.traderefy_dir(nt), nt_paths.journal_dir(nt)):
        if folder is None or not folder.is_dir():
            continue
        try:
            for entry in sorted(folder.iterdir())[:400]:
                if entry.is_file() and not entry.name.lower().endswith('.tmp'):
                    inventory.append({'file': str(entry), 'bytes': entry.stat().st_size,
                                      'age_seconds': nt_paths.file_age_seconds(entry, now)})
        except OSError as exc:
            inventory.append({'folder': str(folder), 'error': str(exc)})
    root, checked = tus_journal.find_journal_root()
    conn = get_db()
    try:
        importer = tus_import.import_status(conn)
    finally:
        conn.close()
    return {
        'tcc_version': _version(), 'python': sys.version.split()[0], 'platform': sys.platform,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'database_path': os.environ.get('DATABASE_PATH', 'trading_journal.db'),
        'ninjatrader_dir': str(nt) if nt else None,
        'ninjatrader_candidates': [str(p) for p in nt_paths.ninjatrader_candidates()],
        'journal_root': str(root) if root else None, 'journal_paths_checked': checked,
        'bridge_discovery': nt_telemetry.live_snapshot(nt, now)['bridge_discovery'],
        'auto_import_enabled': _auto_importer is not None,
        'auto_import_last_error': _auto_importer.last_error if _auto_importer else None,
        'importer': importer, 'files': inventory,
    }
