"""Windows desktop entry point. No NinjaTrader order execution is performed."""
import os
import sys
import time
import threading
from pathlib import Path
import socket


def main():
    import webview
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    backend = base / 'backend'
    frontend = base / 'frontend_build'
    if not (frontend / 'index.html').exists():
        raise RuntimeError('Bundled React frontend is missing')
    sys.path.insert(0, str(backend))
    data = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Traderefy' / 'ControlCenter'
    data.mkdir(parents=True, exist_ok=True)
    os.environ['DATABASE_PATH'] = str(data / 'trading_journal.db')
    os.environ['UPLOAD_DIR'] = str(data / 'uploads')
    os.environ['UPDATE_CHECK_CACHE'] = str(data / 'update_check.json')
    os.chdir(data)
    from main import app
    app.mount('/static', StaticFiles(directory=str(frontend / 'static')), name='frontend-static')
    @app.get('/', include_in_schema=False)
    async def home():
        return FileResponse(str(frontend / 'index.html'))
    # React client-side routing uses state navigation; no arbitrary filesystem paths exposed.
    host, port = '127.0.0.1', 8010
    with socket.socket() as sock:
        if sock.connect_ex((host, port)) == 0:
            raise RuntimeError('Port 8010 is in use. Close the other journal instance before launching TCC.')
    config = uvicorn.Config(app, host=host, port=port, log_level='warning', access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(120):
        if server.started:
            break
        if not thread.is_alive():
            raise RuntimeError('The local TCC service failed to start')
        time.sleep(.1)
    if not server.started:
        raise RuntimeError('The local TCC service timed out')
    try:
        webview.create_window('Traderefy Control Center', f'http://{host}:{port}', width=1500, height=960, min_size=(1050, 700))
        webview.start(gui='edgechromium', debug=False)
    finally:
        server.should_exit = True
        thread.join(timeout=10)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(exc), 'Traderefy Control Center — Startup Error', 0x10)
        raise
