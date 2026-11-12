"""The Thinkorswim and IBKR importers against the sample statements shipped in scripts/.

    cd backend && python -m pytest tests -q

Expected figures are worked out by hand from the sample rows (shown in each comment), not
copied from the parser's output.
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from csv_parser import detect_broker, parse_broker_csv  # noqa: E402

SCRIPTS = BACKEND.parent / "scripts"


def read(name):
    return (SCRIPTS / name).read_text(encoding="utf-8-sig")


def by_group(trades):
    return {t["trade_group"]: t for t in trades}


@pytest.fixture(scope="module")
def tos():
    trades, skipped = parse_broker_csv(read("sample_import.csv"), "auto", account_id=1)
    assert skipped == 0
    return by_group(trades)


@pytest.fixture(scope="module")
def ibkr():
    trades, skipped = parse_broker_csv(read("sample_import_ibkr.csv"), "auto", account_id=1)
    assert skipped == 0
    return by_group(trades)


def test_each_sample_is_detected_as_its_broker():
    assert detect_broker(read("sample_import.csv")) == "thinkorswim"
    assert detect_broker(read("sample_import_ibkr.csv")) == "ibkr"


def test_thinkorswim_scale_in_long(tos):
    # BOT 200 @176.40 + BOT 100 @176.15 = 52,895.00 paid; SOLD 300 @177.35 = 53,205.00
    # gross 310.00, fees 0.70 + 0.35 + 1.05 = 2.10, net 307.90
    t = tos["8/24/26_NVDA_STOCK_1"]
    assert (t["side"], t["gross_pnl"], t["commissions"], t["net_pnl"]) == ("LONG", 310.0, 2.1, 307.9)
    assert len(json.loads(t["executions"])) == 3


def test_thinkorswim_partial_exits(tos):
    # BOT 150 @334.20 = 50,130.00; SOLD 75 @336.10 + 75 @335.40 = 50,362.50
    # gross 232.50, fees 0.55 + 0.30 + 0.30 = 1.15, net 231.35
    t = tos["8/24/26_TSLA_STOCK_1"]
    assert (t["side"], t["gross_pnl"], t["commissions"], t["net_pnl"]) == ("LONG", 232.5, 1.15, 231.35)


def test_thinkorswim_short(tos):
    # SOLD 400 @167.80 = 67,120.00; BOT 400 @167.15 = 66,860.00
    # gross 260.00, fees 1.40 + 1.40, net 257.20
    t = tos["8/24/26_AMD_STOCK_1"]
    assert (t["side"], t["gross_pnl"], t["net_pnl"]) == ("SHORT", 260.0, 257.2)


def test_thinkorswim_loser(tos):
    # BOT 100 @644.90, SOLD 100 @644.15: gross -75.00, fees 0.70, net -75.70
    assert tos["8/24/26_SPY_STOCK_1"]["net_pnl"] == -75.7


def test_thinkorswim_day_total(tos):
    assert len(tos) == 4
    assert round(sum(t["net_pnl"] for t in tos.values()), 2) == 720.75


def test_ibkr_round_trip_across_days(ibkr):
    # BOT 5 @1215.86 (6,079.32) and 6 @1227.67 (7,366.01), SOLD 5 @1239.47 (6,197.36)
    # and 6 @1251.28 (7,507.66): gross 13,705.02 - 13,445.33 = 259.69, fees 4 x 0.35, net 258.29
    t = ibkr["2026-04-27_NFLX_STOCK_1"]
    assert (t["side"], t["gross_pnl"], t["commissions"], t["net_pnl"]) == ("LONG", 259.69, 1.4, 258.29)
    assert t["date"] == "2026-04-27"  # a trade is dated by its closing fill


def test_ibkr_open_positions_report_no_realized_pnl(ibkr):
    # a new buy after the round trip is an open position: no realized P&L until it closes
    t = ibkr["2026-04-30_NFLX_STOCK_2"]
    assert (t["net_pnl"], t["gross_pnl"]) == (0.0, 0.0)
    assert len(json.loads(t["executions"])) == 1
