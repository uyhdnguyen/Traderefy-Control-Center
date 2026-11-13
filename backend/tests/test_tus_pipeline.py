"""R10: TUS journal -> Trading-Journal-AI database, and live NinjaTrader telemetry.

    cd backend && python -m pytest tests/test_tus_pipeline.py -q

Fixtures use the exact headers and value formats TUS/TEE/TEM write
(TraderefyUltimateSystem.cs, TraderefyEntryEngine.cs, TraderefyExecutionManager.cs).
"""
import base64
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ['TCC_NT_TIMEZONE'] = 'America/New_York'

import nt_paths  # noqa: E402
import nt_telemetry  # noqa: E402
import tus_bridge  # noqa: E402
import tus_import  # noqa: E402
import tus_journal  # noqa: E402

TRADE_HEAD = 'TradeId,Account,Instrument,Side,Quantity,OpenTime,CloseTime,EntryPrice,ExitPrice,GrossPnl,Commission,NetPnl,FeeKnown,ExecutionIds,Status'
FILL_HEAD = 'ExecutionId,Account,Instrument,Time,Action,Quantity,Price,PointValue,Commission,FeeKnown'


def q(s):
    return '"' + s.replace('"', '""') + '"'


def two_leg(account, ids, open_t, close_t, side='LONG', entry=7552.25, exits=(7556.0, 7560.0), qty_each=1,
            commission=0.0):
    """A TEM two-leg trade: two 1-lot limit entries, TP1 and TP2 exits. Returns (trade row, fill rows)."""
    inst = 'MES 12-26'
    keys = [f'{account}|{inst}|{i}' for i in ids]
    entry_action, exit_action = ('Buy', 'Sell') if side == 'LONG' else ('SellShort', 'BuyToCover')
    fills = [
        f'{q(keys[0])},{q(account)},{q(inst)},{open_t},{entry_action},{qty_each},{entry},5,{commission},1',
        f'{q(keys[1])},{q(account)},{q(inst)},{open_t},{entry_action},{qty_each},{entry},5,{commission},1',
        f'{q(keys[2])},{q(account)},{q(inst)},{close_t},{exit_action},{qty_each},{exits[0]},5,{commission},1',
        f'{q(keys[3])},{q(account)},{q(inst)},{close_t},{exit_action},{qty_each},{exits[1]},5,{commission},1',
    ]
    sign = 1 if side == 'LONG' else -1
    gross = sum((x - entry) * sign * 5 * qty_each for x in exits)
    net = gross - 4 * commission
    trade_id = keys[0] + '_' + keys[3]
    row = (f'{q(trade_id)},{q(account)},{q(inst)},{q(side)},2,{open_t},{close_t},{entry},{sum(exits) / 2},'
           f'{gross},{4 * commission},{net},1,{q(";".join(keys))},PENDING')
    return trade_id, row, fills


@pytest.fixture
def nt(tmp_path):
    root = tmp_path / 'NinjaTrader 8'
    journal = root / 'Traderefy' / 'Journal'
    journal.mkdir(parents=True)
    (root / 'tus_sim_bridge').mkdir()
    return root


def write_journal(nt, trades, fills, tags=(), resets=(), groups=(), forward=()):
    j = nt / 'Traderefy' / 'Journal'
    (j / 'TUS_Trade_Master.csv').write_text('\n'.join([TRADE_HEAD, *trades]) + '\n', encoding='utf-8')
    (j / 'TUS_Execution_Master.csv').write_text('\n'.join([FILL_HEAD, *fills]) + '\n', encoding='utf-8')
    (j / 'TUS_Trade_Setup_Tags.csv').write_text('\n'.join(['TradeId,Setup', *[f'{q(a)},{q(b)}' for a, b in tags]]) + '\n')
    (j / 'TUS_Account_Reset.csv').write_text('\n'.join(['Account,ResetUtc', *[f'{q(a)},{q(b)}' for a, b in resets]]) + '\n')
    (j / 'TUS_Approved_Trades.csv').write_text('TradeId,Account,CloseTime,NetPnl,Instrument,Side,Quantity,FeeKnown\n')
    (j / 'TUS_Manual_Trade_Groups.tsv').write_text(
        ''.join(f'{g}\t{base64.b64encode(t.encode()).decode()}\n' for g, t in groups))
    (nt / 'Traderefy' / 'TUS_SIM_Forward_Fills.tsv').write_text(''.join('\t'.join(r) + '\n' for r in forward))


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / 'journal.db'
    monkeypatch.setenv('DATABASE_PATH', str(path))
    sys.modules.pop('database', None)
    import database
    database.DB_PATH = str(path)
    database.init_db()
    conn = database.get_db()
    yield conn
    conn.close()


def fwd(account, setup, exec_id, entry, stop, t='2026-11-11T10:00:00.0000000'):
    return [t, account, 'MES 12-26', setup, 'NORMAL', 'sig', 'cmd', exec_id, '1', str(entry), str(stop)]


# ── journal reader ────────────────────────────────────────────────────────────

def test_parse_nt_time_handles_seven_digit_fractions_and_local_time():
    utc = tus_journal.parse_nt_time('2026-11-13T10:25:35.7530000')
    assert utc == datetime(2026, 11, 13, 15, 25, 35, 753000, tzinfo=timezone.utc)
    assert tus_journal.parse_nt_time('2026-11-03T19:28:48.6642789Z').hour == 19
    assert tus_journal.parse_nt_time('garbage') is None


def test_two_leg_trade_is_one_trade_with_four_fills(nt):
    tid, row, fills = two_leg('SimIBS', 'abcd', '2026-11-11T10:00:00.0000000', '2026-11-11T10:20:00.0000000')
    write_journal(nt, [row], fills)
    data = tus_journal.load_journal(nt / 'Traderefy' / 'Journal')
    assert data['trade_count'] == 1
    assert data['trades'][0]['execution_count'] == 4
    assert data['trades'][0]['missing_execution_ids'] == []


def test_reset_watermark_excludes_older_trades_in_utc(nt):
    old_id, old, f1 = two_leg('Sim101', 'abcd', '2026-11-03T13:00:00.0000000', '2026-11-03T14:20:00.0000000')
    new_id, new, f2 = two_leg('Sim101', 'efgh', '2026-11-03T15:00:00.0000000', '2026-11-03T15:20:00.0000000')
    # 14:20 ET = 19:20Z (before reset); 15:20 ET = 20:20Z (after reset at 19:28Z)
    write_journal(nt, [old, new], f1 + f2, resets=[('Sim101', '2026-11-03T19:28:48.6642789Z')])
    data = tus_journal.load_journal(nt / 'Traderefy' / 'Journal')
    assert [t['TradeId'] for t in data['trades']] == [new_id]
    assert data['excluded_before_reset'] == 1


def test_playback_tags_and_groups(nt):
    tid, row, fills = two_leg('Playback101', 'abcd', '2026-11-02T10:57:04.0000000', '2026-11-02T12:10:08.0000000')
    write_journal(nt, [row], fills, tags=[(tid, 'IBS')], groups=[('G1', tid)])
    t = tus_journal.load_journal(nt / 'Traderefy' / 'Journal')['trades'][0]
    assert t['playback'] and t['setup_tag'] == 'IBS' and t['manual_group_id'] == 'G1'


# ── import into the journal database ─────────────────────────────────────────

def test_import_is_idempotent_and_feeds_native_tables(nt, db):
    tid, row, fills = two_leg('SimIBS', 'abcd', '2026-11-11T10:00:00.0000000', '2026-11-11T10:20:00.0000000',
                              entry=7552.25, exits=(7556.0, 7560.0))
    write_journal(nt, [row], fills,
                  forward=[fwd('SimIBS', 'IBS', 'abcd'[0], 7552.25, 7548.25), fwd('SimIBS', 'IBS', 'abcd'[1], 7552.25, 7548.25)])
    root = nt / 'Traderefy' / 'Journal'
    first = tus_import.run_import(db, roots=[root])
    assert first['ok'] and first['inserted'] == 1
    second = tus_import.run_import(db, roots=[root])
    assert second['inserted'] == 0 and second['unchanged'] == 1
    trade = db.execute('SELECT * FROM trades').fetchone()
    assert trade['ticker'] == '/MESZ26' and trade['instrument_type'] == 'FUTURE' and trade['source'] == 'tus'
    assert trade['date'] == '2026-11-11' and trade['side'] == 'LONG'
    assert trade['gross_pnl'] == pytest.approx((3.75 + 7.75) * 5)
    execs = json.loads(trade['executions'])
    assert len(execs) == 4 and [e['action'] for e in execs] == ['BOT', 'BOT', 'SOLD', 'SOLD']
    assert trade['setup'] == 'IBS' and trade['setup_source'] == 'tus'
    review = db.execute('SELECT * FROM trade_analysis').fetchone()
    assert review['stop_loss'] == 7548.25
    assert review['risk_per_trade'] == pytest.approx(4 * 5 * 2)
    assert review['r_multiple'] == pytest.approx(round(57.5 / 40, 2))
    assert db.execute("SELECT 1 FROM custom_setups WHERE name='IBS' AND active=1").fetchone()


def test_user_annotations_survive_tus_changes(nt, db):
    tid, row, fills = two_leg('SimFTR', 'abcd', '2026-11-12T11:26:50.0000000', '2026-11-12T11:28:14.0000000',
                              entry=7659.0, exits=(7660.75, 7663.25))
    write_journal(nt, [row], fills, forward=[fwd('SimFTR', 'FTR-1', 'a', 7659.0, 7656.5),
                                             fwd('SimFTR', 'FTR-1', 'b', 7659.0, 7656.5)])
    root = nt / 'Traderefy' / 'Journal'
    tus_import.run_import(db, roots=[root])
    group = db.execute('SELECT trade_group FROM trades').fetchone()[0]
    # The trader writes notes, overrides R and re-tags the setup in the journal.
    db.execute("UPDATE trade_analysis SET notes='late entry', r_multiple=9.9 WHERE trade_group=?", (group,))
    db.execute("UPDATE trades SET setup='ORB + Retest', setup_source='manual' WHERE trade_group=?", (group,))
    db.commit()
    # TUS later rewrites the trade with commissions (content changes).
    tid2, row2, fills2 = two_leg('SimFTR', 'abcd', '2026-11-12T11:26:50.0000000', '2026-11-12T11:28:14.0000000',
                                 entry=7659.0, exits=(7660.75, 7663.25), commission=0.35)
    write_journal(nt, [row2], fills2, forward=[fwd('SimFTR', 'FTR-1', 'a', 7659.0, 7656.5),
                                               fwd('SimFTR', 'FTR-1', 'b', 7659.0, 7656.5)])
    result = tus_import.run_import(db, roots=[root])
    assert result['updated'] == 1 and result['inserted'] == 0
    trade = db.execute('SELECT * FROM trades').fetchone()
    assert trade['commissions'] == pytest.approx(1.4)
    assert trade['setup'] == 'ORB + Retest'               # manual tag kept
    review = db.execute('SELECT * FROM trade_analysis').fetchone()
    assert review['notes'] == 'late entry' and review['r_multiple'] == 9.9   # trader's values kept
    assert db.execute('SELECT COUNT(*) FROM trades').fetchone()[0] == 1


def test_edited_deleted_and_removed_trades(nt, db):
    a_id, a, fa = two_leg('SimIBS', 'abcd', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    b_id, b, fb = two_leg('SimIBS', 'efgh', '2026-11-10T11:00:00.0000000', '2026-11-10T11:20:00.0000000')
    root = nt / 'Traderefy' / 'Journal'
    write_journal(nt, [a, b], fa + fb)
    tus_import.run_import(db, roots=[root])
    groups = [r[0] for r in db.execute('SELECT trade_group FROM trades ORDER BY trade_group')]
    assert groups == ['2026-11-10_/MESZ26_FUTURE_1', '2026-11-10_/MESZ26_FUTURE_2']
    # Trader deletes A in the journal: it must not come back.
    db.execute("DELETE FROM trades WHERE trade_group=?", (groups[0],))
    db.commit()
    r = tus_import.run_import(db, roots=[root])
    assert r['skipped_deleted'] == 1 and db.execute('SELECT COUNT(*) FROM trades').fetchone()[0] == 1
    # TUS resets the account: B disappears from TUS; the journal keeps it until an explicit purge.
    write_journal(nt, [], [])
    r = tus_import.run_import(db, roots=[root])
    assert r['removed_from_tus'] == 1 and db.execute('SELECT COUNT(*) FROM trades').fetchone()[0] == 1
    assert tus_import.purge_removed(db)['purged'] == 1
    assert db.execute('SELECT COUNT(*) FROM trades').fetchone()[0] == 0


def test_edited_trade_is_not_overwritten(nt, db):
    tid, row, fills = two_leg('SimIBS', 'abcd', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    root = nt / 'Traderefy' / 'Journal'
    write_journal(nt, [row], fills)
    tus_import.run_import(db, roots=[root])
    db.execute("UPDATE trades SET net_pnl=1.0, source='edited'")
    db.commit()
    tid, row, fills = two_leg('SimIBS', 'abcd', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000',
                              commission=0.5)
    write_journal(nt, [row], fills)
    r = tus_import.run_import(db, roots=[root])
    assert r['skipped_edited'] == 1
    assert db.execute('SELECT net_pnl FROM trades').fetchone()[0] == 1.0
    assert tus_import.import_status(db)['conflicts']


def test_playback_imports_into_flagged_separate_account(nt, db):
    s_id, s, fs = two_leg('SimIBS', 'abcd', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    p_id, p, fp = two_leg('Playback101', 'efgh', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    write_journal(nt, [s, p], fs + fp)
    tus_import.run_import(db, roots=[nt / 'Traderefy' / 'Journal'])
    rows = {r['tus_account']: r for r in db.execute('SELECT * FROM tus_accounts')}
    assert rows['Playback101']['playback'] == 1 and rows['SimIBS']['playback'] == 0
    assert rows['Playback101']['account_id'] != rows['SimIBS']['account_id']
    assert tus_import.playback_account_ids(db) == {rows['Playback101']['account_id']}
    broker = db.execute('SELECT broker FROM accounts WHERE id=?', (rows['Playback101']['account_id'],)).fetchone()[0]
    assert broker == tus_import.BROKER_PLAYBACK


def test_missing_fills_still_import_with_flag(nt, db):
    tid, row, fills = two_leg('SimIBS', 'abcd', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    write_journal(nt, [row], fills[:2])
    r = tus_import.run_import(db, roots=[nt / 'Traderefy' / 'Journal'])
    assert r['inserted'] == 1 and any('synthesised' in w for w in r['warnings'])
    execs = json.loads(db.execute('SELECT executions FROM trades').fetchone()[0])
    assert all(e.get('synthetic') for e in execs)


def test_all_accounts_excludes_playback_in_main(nt, db, monkeypatch):
    pytest.importorskip('fastapi')
    s_id, s, fs = two_leg('SimIBS', 'abcd', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    p_id, p, fp = two_leg('Playback101', 'efgh', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    write_journal(nt, [s, p], fs + fp)
    tus_import.run_import(db, roots=[nt / 'Traderefy' / 'Journal'])
    sys.modules.pop('main', None)
    import main
    ids = main.account_ids(None)
    playback = tus_import.playback_account_ids(db)
    assert ids and not (set(ids) & playback)
    assert main.account_ids(str(next(iter(playback)))) == [next(iter(playback))]


# ── live telemetry ────────────────────────────────────────────────────────────

def ticks(ts):
    return int(ts * 10_000_000) + nt_paths.TICKS_AT_UNIX_EPOCH


def write_engines(nt, now, tus_age=3, tee_age=4, tem_age=1, root='MES'):
    t = nt / 'Traderefy'
    inst = f'{root} 12-26'
    (t / f'TUS_FTR_Levels_{root}.status').write_text(
        f'{ticks(now - tus_age)}|{inst}\nAUTO|PDH|7674.5|#FF228B22\nAUTO|ORB HIGH|7648|FFD17312\n'
        f'AUTO|ORB LOW|7603|FFD17312\nMANUAL|KEY|7600|FF6D4C9C\n')
    (t / f'TUS_FTR_Trend_{root}.status').write_text(f'{ticks(now - tus_age)}|{inst}|-1|-1|0|1')
    (t / f'FTR_699_{root}.status').write_text(f'{ticks(now - tee_age)}|{inst}|HEARTBEAT|bar=10572')
    (t / f'FTR_699_Candidates_{root}.csv').write_text(
        'Timestamp,Instrument,Direction,Entry50,IllustrativeTP1,RangeLow,RangeHigh,Status\n'
        f'2026-11-13T10:29:01.6330000,{inst},SHORT,7540.5,7538.5,7539,7541.75,CANDIDATE_NOT_TUS_AUTHORIZED,7535,2,7543,3.33,2026-11-13T10:16:26.5400000\n')
    (t / f'TUS_Real_Signal_Journal_{root}.csv').write_text(
        'RecordedUtc,Family,SignalId,Instrument,Direction,Entry50,SwingStop,TP1,TP2,RiskUsd,Status\n'
        f'2026-11-13T15:25:36Z,FTR,x|FTR-1,{inst},SHORT,7533.25,7537.5,7531.25,7527.75,42.5,PHASE10_SIM_QUEUED_SimFTR\n'
        f'2026-11-13T16:25:02Z,FTR,y|FTR-1,{inst},SHORT,7536.75,7539,7535,7531.75,22.5,REJECT_PRICE_GEOMETRY\n')
    b = nt / 'tus_sim_bridge'
    key = f'SimFTR_{root}_12-26'
    (b / f'account_heartbeat_{key}.txt').write_text(f'{ticks(now - tem_age)}|SimFTR|{inst}')
    (b / f'auto_heartbeat_{key}.txt').write_text(f'{ticks(now - tem_age)}|SimFTR|{inst}')
    (b / f'auto_diagnostic_{key}.txt').write_text(f'{ticks(now - 100)}|REJECT_PRICE_GEOMETRY|signal=y')
    (b / f'auto_events_{key}.log').write_text('2026-11-13T15:25:36Z | COMMAND_DETECTED | auto_command\n')
    (b / 'heartbeat.txt').write_text(f'{ticks(now - tem_age)}|SimFTR|{inst}')
    for i in range(50):
        (b / f'heartbeat.txt.{i:032x}.tmp').write_text('x')


def test_live_snapshot_reads_each_engine_independently(nt):
    now = time.time()
    write_engines(nt, now)
    nt_telemetry._discovery['at'] = 0
    snap = nt_telemetry.live_snapshot(nt, now)
    es = snap['markets'][0]
    assert es['root'] == 'MES' and es['instrument'] == 'MES 12-26' and es['state'] == 'live'
    assert es['engines']['tus_m5']['state'] == 'live'
    assert es['engines']['tee_699']['state'] == 'live' and es['engines']['tee_699']['bar'] == 10572
    assert es['engines']['tem']['state'] == 'live' and es['engines']['tem']['live_instances'] == 1
    assert es['trend']['overall'] == -1 and es['trend']['m60'] == 1
    assert es['levels']['orb'] == {'high': 7648.0, 'low': 7603.0} and es['levels']['manual'] == [7600.0]
    assert es['setups']['candidates'][0]['tp2'] == 7535.0
    assert [s['stage'] for s in es['setups']['signals']] == ['sent_to_tem', 'rejected']
    assert snap['markets'][2]['state'] == 'no_charts'          # no YM/MYM charts
    assert snap['bridge_discovery']['tmp_count'] == 50


def test_engine_staleness_is_per_engine(nt):
    now = time.time()
    write_engines(nt, now, tus_age=3, tee_age=600, tem_age=60)
    nt_telemetry._discovery['at'] = 0
    es = nt_telemetry.live_snapshot(nt, now)['markets'][0]
    assert es['engines']['tus_m5']['state'] == 'live'
    assert es['engines']['tee_699']['state'] == 'stale'
    assert es['engines']['tem']['state'] == 'stale'
    assert es['state'] == 'partial'


def test_open_positions_from_execution_ledger(nt):
    j = nt / 'Traderefy' / 'Journal'
    (j / 'TUS_Execution_Master.csv').write_text('\n'.join([
        FILL_HEAD,
        '"SimIBS|MES 12-26|1","SimIBS","MES 12-26",2026-11-13T10:00:00.0000000,Buy,1,7550,5,0,1',
        '"SimIBS|MES 12-26|2","SimIBS","MES 12-26",2026-11-13T10:00:01.0000000,Buy,1,7551,5,0,1',
        '"SimIBS|MES 12-26|3","SimIBS","MES 12-26",2026-11-13T10:05:00.0000000,Sell,1,7555,5,0,1',
        '"SimFTR|MES 12-26|4","SimFTR","MES 12-26",2026-11-13T10:00:00.0000000,SellShort,1,7550,5,0,1',
        '"SimFTR|MES 12-26|5","SimFTR","MES 12-26",2026-11-13T10:01:00.0000000,BuyToCover,1,7549,5,0,1',
    ]) + '\n')
    pos = nt_telemetry.open_positions(j)['MES 12-26']
    assert len(pos) == 1 and pos[0]['account'] == 'SimIBS' and pos[0]['quantity'] == 1
    assert pos[0]['side'] == 'LONG'


def test_bridge_snapshot_counts_tmp_without_reading_them(nt):
    now = time.time()
    write_engines(nt, now)
    nt_telemetry._discovery['at'] = 0
    data = tus_bridge.snapshot_data([nt / 'tus_sim_bridge'])
    assert data['connected'] is True
    assert data['bridge_paths_checked'][0]['ignored_temporary_files'] == 50
    assert all(not f['file'].endswith('.tmp') for f in data['files'])


def test_read_text_tail(tmp_path):
    p = tmp_path / 'log.txt'
    p.write_text(''.join(f'line {i}\n' for i in range(10000)))
    assert nt_paths.tail_lines(p, 3, max_bytes=200) == ['line 9997', 'line 9998', 'line 9999']


def test_reuses_empty_r4_placeholder_account_only(nt, db):
    db.execute("INSERT INTO accounts (name, type, broker) VALUES ('SimIBS','day_trading','NinjaTrader (journal only)')")
    db.execute("INSERT INTO accounts (name, type, broker) VALUES ('SimFTR','day_trading','NinjaTrader (journal only)')")
    ftr = db.execute("SELECT id FROM accounts WHERE name='SimFTR'").fetchone()[0]
    db.execute("INSERT INTO trades (account_id, trade_group, date, ticker, instrument_type, side, executions, source) "
               "VALUES (?, 'x', '2026-11-01', '/MESZ26', 'FUTURE', 'LONG', '[]', 'imported')", (ftr,))
    db.commit()
    a_id, a, fa = two_leg('SimIBS', 'abcd', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    b_id, b, fb = two_leg('SimFTR', 'efgh', '2026-11-10T10:00:00.0000000', '2026-11-10T10:20:00.0000000')
    write_journal(nt, [a, b], fa + fb)
    tus_import.run_import(db, roots=[nt / 'Traderefy' / 'Journal'])
    rows = {r['tus_account']: r['account_id'] for r in db.execute('SELECT * FROM tus_accounts')}
    ibs = db.execute("SELECT id FROM accounts WHERE name='SimIBS'").fetchone()[0]
    assert rows['SimIBS'] == ibs                     # empty placeholder reused
    assert rows['SimFTR'] != ftr                     # has CSV trades: separate TUS account
