"""Finder aliases on macOS.

A Finder alias is a regular file holding a bookmark, not a symlink: the file
system doesn't follow it, so corral asks Core Foundation where it leads.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_MAGIC = b"book\0\0\0\0mark"
_NO_UI_NO_MOUNT = 1 << 8 | 1 << 9  # resolving never prompts or mounts a volume
_PATH_MAX = 1024


def follow(path: Path) -> Path:
    """Where the alias at `path` leads; `path` itself if it isn't an alias or
    its target can't be found."""
    if sys.platform != "darwin" or not _is_alias(path):
        return path
    return _resolve(path) or path


def _is_alias(path: Path) -> bool:
    try:
        if not path.is_file():  # opening a FIFO would block
            return False
        with path.open("rb") as f:
            return f.read(len(_MAGIC)) == _MAGIC
    except OSError:
        return False


def _resolve(path: Path) -> Path | None:
    ptr, size = ctypes.c_void_p, ctypes.c_long
    cf = ctypes.CDLL(_CORE_FOUNDATION)
    cf.CFURLCreateFromFileSystemRepresentation.restype = ptr
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
        ptr,
        ctypes.c_char_p,
        size,
        ctypes.c_bool,
    ]
    cf.CFURLCreateBookmarkDataFromFile.restype = ptr
    cf.CFURLCreateBookmarkDataFromFile.argtypes = [ptr, ptr, ptr]
    cf.CFURLCreateByResolvingBookmarkData.restype = ptr
    cf.CFURLCreateByResolvingBookmarkData.argtypes = [
        ptr,
        ptr,
        ctypes.c_ulong,
        ptr,
        ptr,
        ptr,
        ptr,
    ]
    cf.CFURLGetFileSystemRepresentation.restype = ctypes.c_bool
    cf.CFURLGetFileSystemRepresentation.argtypes = [ptr, ctypes.c_bool, ctypes.c_char_p, size]
    cf.CFRelease.restype = None
    cf.CFRelease.argtypes = [ptr]

    raw = os.fsencode(path)
    made = []
    try:
        url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
        made.append(url)
        data = url and cf.CFURLCreateBookmarkDataFromFile(None, url, None)
        made.append(data)
        target = data and cf.CFURLCreateByResolvingBookmarkData(
            None, data, _NO_UI_NO_MOUNT, None, None, None, None
        )
        made.append(target)
        buf = ctypes.create_string_buffer(_PATH_MAX)
        if target and cf.CFURLGetFileSystemRepresentation(target, True, buf, _PATH_MAX):
            return Path(os.fsdecode(buf.value))
        return None
    finally:
        for ref in made:
            if ref:
                cf.CFRelease(ref)
