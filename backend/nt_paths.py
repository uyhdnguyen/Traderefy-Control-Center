"""NinjaTrader data locations and non-blocking file reads for TCC (R10).

One resolver for every TCC reader, so the bridge, telemetry and journal can never
look in different folders:

    <Documents>/NinjaTrader 8/                  NinjaTrader UserDataDir
        tus_sim_bridge/                         TEM heartbeats, order status, events
        Traderefy/                              TUS/TEE instrument bridge files
        Traderefy/Journal/                      TUS trade journal

TEM resolves Environment.SpecialFolder.MyDocuments; TUS/TEE use
NinjaTrader.Core.Globals.UserDataDir. Both are normally <Documents>/NinjaTrader 8.

All reads are read-only. On Windows they open files with FILE_SHARE_DELETE so a
TCC read can never make NinjaTrader's File.Replace / File.Move fail (Python's
default open() does not share delete access, which can leave .tmp files behind
in NinjaTrader's writers).
"""
from __future__ import annotations

import os
from pathlib import Path

TICKS_AT_UNIX_EPOCH = 621355968000000000
ENV_NT_DIR = 'TCC_NINJATRADER_DIR'
ENV_JOURNAL_DIR = 'TCC_NINJATRADER_JOURNAL_DIR'


def _windows_documents() -> Path | None:
    if os.name != 'nt':
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        # CSIDL_PERSONAL = 5 resolves a redirected (e.g. OneDrive) Documents folder.
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except (OSError, AttributeError, ValueError):
        pass
    return None


def documents_candidates() -> list[Path]:
    result: list[Path] = []
    for candidate in (_windows_documents(), Path.home() / 'Documents',
                      Path(os.environ['OneDrive']) / 'Documents' if os.environ.get('OneDrive') else None,
                      Path(os.environ['OneDriveCommercial']) / 'Documents' if os.environ.get('OneDriveCommercial') else None):
        if candidate is not None and candidate not in result:
            result.append(candidate)
    return result


def ninjatrader_candidates() -> list[Path]:
    """Candidate NinjaTrader 8 user-data folders, override first."""
    result: list[Path] = []
    override = os.environ.get(ENV_NT_DIR, '').strip()
    if override:
        result.append(Path(override).expanduser())
    for docs in documents_candidates():
        path = docs / 'NinjaTrader 8'
        if path not in result:
            result.append(path)
    return result


def ninjatrader_dir() -> Path | None:
    """The first existing candidate that looks like a NinjaTrader 8 user folder."""
    for path in ninjatrader_candidates():
        if (path / 'Traderefy').is_dir() or (path / 'tus_sim_bridge').is_dir() or (path / 'bin' / 'Custom').is_dir():
            return path
    return None


def bridge_dir(nt: Path | None = None) -> Path | None:
    nt = nt or ninjatrader_dir()
    return nt / 'tus_sim_bridge' if nt else None


def traderefy_dir(nt: Path | None = None) -> Path | None:
    nt = nt or ninjatrader_dir()
    return nt / 'Traderefy' if nt else None


def journal_dir(nt: Path | None = None) -> Path | None:
    override = os.environ.get(ENV_JOURNAL_DIR, '').strip()
    if override:
        return Path(override).expanduser()
    nt = nt or ninjatrader_dir()
    return nt / 'Traderefy' / 'Journal' if nt else None


# ── Non-blocking reads ────────────────────────────────────────────────────────

def _open_shared_windows(path: Path):
    import ctypes
    import msvcrt
    from ctypes import wintypes
    GENERIC_READ = 0x80000000
    SHARE_ALL = 0x1 | 0x2 | 0x4          # read | write | delete
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    create = ctypes.windll.kernel32.CreateFileW
    create.restype = wintypes.HANDLE
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    handle = create(str(path), GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error() or 2, 'Cannot open file', str(path))
    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    return os.fdopen(fd, 'rb')


def open_binary_shared(path: Path):
    """Open for reading without ever blocking a writer's rename/replace/delete."""
    if os.name == 'nt':
        try:
            return _open_shared_windows(path)
        except (ImportError, AttributeError):
            pass
    return open(path, 'rb')


def read_bytes(path: Path, max_bytes: int = 4 * 1024 * 1024, tail: bool = False) -> bytes:
    """Read at most max_bytes; tail=True reads the end of the file."""
    with open_binary_shared(path) as stream:
        if tail:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - max_bytes))
        return stream.read(max_bytes)


def read_text(path: Path, max_bytes: int = 4 * 1024 * 1024, tail: bool = False) -> str:
    data = read_bytes(path, max_bytes, tail)
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    return data.decode('utf-8', errors='replace')


def tail_lines(path: Path, count: int = 50, max_bytes: int = 256 * 1024) -> list[str]:
    """Last `count` complete lines of a (possibly large, append-only) text file."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    text = read_text(path, max_bytes=max_bytes, tail=True)
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]   # first line may be cut in half
    return [line for line in lines if line.strip()][-count:]


def dotnet_ticks_to_unix(ticks: int) -> float:
    """.NET DateTime.UtcNow.Ticks -> Unix seconds (UTC)."""
    return (int(ticks) - TICKS_AT_UNIX_EPOCH) / 10_000_000


def file_age_seconds(path: Path, now: float) -> float | None:
    try:
        return round(now - path.stat().st_mtime, 1)
    except OSError:
        return None
