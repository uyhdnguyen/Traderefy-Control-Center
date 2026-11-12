
# Traderefy Control Center - Windows PyInstaller specification

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "build"
LAUNCHER = ROOT / "desktop" / "tcc_launcher.py"

required = [
    LAUNCHER,
    BACKEND / "main.py",
    FRONTEND / "index.html",
    ROOT / "VERSION",
]

for path in required:
    if not path.exists():
        raise FileNotFoundError(f"Required build file missing: {path}")

hidden = [
    "main",
    "database",
    "csv_parser",
    "trade_store",
    "broker_formats",
    "ai_analysis",
    "leaks",
    "daily_summary",
    "library",
    "edge_sync",
    "update_check",
    "exitlab.api",
]

for mod in [
    "uvicorn",
    "webview",
    "pandas_market_calendars",
    "exchange_calendars",
    "anthropic",
    "httpx",
    "tzdata",
    "zoneinfo",
]:
    hidden += collect_submodules(mod)

extra = []

for mod in [
    "pandas_market_calendars",
    "exchange_calendars",
    "tzdata",
]:
    extra += collect_data_files(mod)

a = Analysis(
    [str(LAUNCHER)],
    pathex=[str(ROOT), str(BACKEND)],
    binaries=[],
    datas=[
        (str(BACKEND), "backend"),
        (str(FRONTEND), "frontend_build"),
        (str(ROOT / "VERSION"), "."),
    ] + extra,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TraderefyControlCenter",
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TraderefyControlCenter",
)
