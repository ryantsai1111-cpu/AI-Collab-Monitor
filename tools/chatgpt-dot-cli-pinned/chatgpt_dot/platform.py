"""Paths, console encoding, and file helpers for Linux, macOS, and Windows.

This package does not spawn subprocesses, so there is no shell and no
executable lookup. The CLI does not write a config or cache file.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def codex_auth_path() -> Path:
    """Codex ChatGPT login. Codex keeps it under CODEX_HOME when that is set."""
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "auth.json"
    return Path.home() / ".codex" / "auth.json"


def configure_stdio() -> None:
    """On Windows, print UTF-8 so zh-TW text does not crash cp950 or cp1252.

    POSIX consoles are left alone. Newlines stay LF so JSON matches the docs.
    """
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace", newline="\n")
        except (OSError, ValueError):
            continue


def posix_mode(path: Path) -> int | None:
    """Unix permission bits, or None on Windows.

    Windows uses ACLs, not Unix mode bits, so this check does not run there.
    The CLI never refuses to read the auth file because of these bits.
    """
    if os.name == "nt":
        return None
    try:
        return path.stat().st_mode & 0o777
    except OSError:
        return None


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 LF text via a tempfile in the same directory, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class FileLock:
    """Exclusive lock. fcntl on POSIX, msvcrt on Windows."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+b")
        if self._fh.seek(0, os.SEEK_END) == 0:
            self._fh.write(b"\0")
            self._fh.flush()
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: object) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()
