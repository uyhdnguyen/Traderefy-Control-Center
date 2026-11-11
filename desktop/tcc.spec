# PyInstaller spec — run from repository root on Windows after frontend build.
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
hidden = ['main', 'database', 'csv_parser', 'trade_store', 'broker_formats', 'ai_analysis', 'leaks', 'daily_summary', 'library', 'edge_sync', 'update_check', 'exitlab.api']
for mod in ['uvicorn', 'webview', 'pandas_market_calendars', 'exchange_calendars', 'anthropic', 'httpx', 'tzdata', 'zoneinfo']:
    hidden += collect_submodules(mod)
extra = []
for mod in ['pandas_market_calendars', 'exchange_calendars', 'tzdata']:
    extra += collect_data_files(mod)
a = Analysis(['desktop/tcc_launcher.py'], pathex=['backend'], binaries=[],
             datas=[('backend','backend'), ('frontend/build','frontend_build'), ('VERSION','.')]+extra,
             hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TraderefyControlCenter', console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='TraderefyControlCenter')
