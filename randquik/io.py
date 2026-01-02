"""File I/O helpers for output handling and mmap operations."""

import contextlib
import ctypes
import mmap
import os
import pathlib
import sys
from collections.abc import Generator

__all__ = [
    "HAS_MADVISE",
    "madvise_buffer",
    "madvise_file",
    "open_fd",
    "open_memoryview",
]

# Platform-specific constants for madvise
MADV_DONTNEED = 4  # Linux/macOS
MADV_SEQUENTIAL = 2  # Hint for sequential access
MADV_WILLNEED = 3  # Pre-fault pages
MADV_RANDOM = getattr(mmap, "MADV_RANDOM", 1)  # Not available on Windows

# Try to get O_DIRECT (Linux only, not available on macOS)
O_DIRECT = getattr(os, "O_DIRECT", 0)

# Load libc for madvise (not available on Windows)
HAS_MADVISE = False
_madvise = None
if sys.platform != "win32":
    try:
        if sys.platform == "darwin":
            _libc = ctypes.CDLL("libc.dylib", use_errno=True)
        else:
            _libc = ctypes.CDLL("libc.so.6", use_errno=True)
        _madvise = _libc.madvise
        _madvise.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        _madvise.restype = ctypes.c_int
        HAS_MADVISE = True
    except (OSError, AttributeError):
        pass


def _madvise_call(mm: mmap.mmap, advice: int, offset: int = 0, length: int = 0):
    """Call madvise with specified advice."""
    if length == 0:
        length = len(mm)
    mm.madvise(advice, offset, length)


def madvise_buffer(mm: mmap.mmap, offset: int = 0, length: int = 0):
    """Mark mmap region for random access (avoid caching)."""
    _madvise_call(mm, MADV_RANDOM, offset, length)


def madvise_file(mm: mmap.mmap, offset: int = 0, length: int = 0):
    """Mark mmap region for sequential access (pre-fault pages)."""
    _madvise_call(mm, MADV_WILLNEED, offset, length)


def _open_output(
    output_path: str,
    total_bytes: int | None,
    oseek: int = 0,
) -> int:
    """Open output file descriptor, preallocate and apply platform hints."""
    if output_path:
        flags = os.O_RDWR | os.O_CREAT
        fd = os.open(str(pathlib.Path(output_path)), flags, 0o644)
    else:
        if sys.stdout.isatty():
            raise ValueError("Refusing to write binary data to terminal. Use -o to specify a file.")
        fd = sys.stdout.fileno()

    required_size = oseek + (total_bytes if total_bytes is not None else 0)
    current_size = os.fstat(fd).st_size
    if required_size > current_size:
        with contextlib.suppress(OSError):
            os.ftruncate(fd, required_size)

    # Seek to output position
    if oseek > 0:
        try:
            os.lseek(fd, oseek, os.SEEK_SET)
        except OSError as e:
            raise ValueError(
                f"Cannot oseek in {output_path or 'stdout'}. Use only --iseek or specify a seekable file."
            ) from e

    # macOS: try to bypass unified buffer cache (F_NOCACHE)
    if sys.platform == "darwin":
        try:
            import fcntl

            fcntl.fcntl(fd, fcntl.F_NOCACHE, 1)
        except (OSError, AttributeError, ImportError):
            pass

    return fd


@contextlib.contextmanager
def open_fd(
    output_path: str | None,
    total_bytes: int | None,
    dry: bool = False,
    oseek: int = 0,
) -> Generator[int]:
    """Context manager for output file descriptor.

    Args:
        output_path: Path to output file, or None for stdout
        total_bytes: Total bytes to write
        dry: If True, skip truncation/preallocation and tty check
        oseek: Seek position for output

    Yields:
        Integer file descriptor
    """
    if dry:
        yield -1
        return
    if not output_path:
        yield sys.stdout.fileno()
        return
    fd = _open_output(output_path, total_bytes, oseek)
    try:
        yield fd
    finally:
        with contextlib.suppress(Exception):
            os.close(fd)


@contextlib.contextmanager
def open_memoryview(buf) -> Generator[memoryview]:
    """Context manager for memoryview.

    Args:
        buf: Buffer to create memoryview from

    Yields:
        memoryview object
    """
    view = memoryview(buf)
    try:
        yield view
    finally:
        view.release()
