"""File I/O helpers for output handling."""

import contextlib
import errno
import os
import pathlib
import sys
from collections.abc import Generator

__all__ = [
    "open_fd",
    "open_memoryview",
]


def _open_output(
    output_path: str,
    total_bytes: int | None,
    oseek: int = 0,
) -> tuple[int, bool]:
    """Open output file descriptor, preallocate and apply platform hints.

    Returns:
        Tuple of (file descriptor, whether we created the file)
    """
    created = False
    if output_path:
        path = pathlib.Path(output_path)
        created = not path.exists()
        flags = os.O_WRONLY | os.O_CREAT
        fd = os.open(str(path), flags, 0o644)
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

    return fd, created


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
    fd, created = _open_output(output_path, total_bytes, oseek)
    try:
        yield fd
    except OSError as e:
        if e.errno == errno.ENOSPC:
            # Clean up file we created on disk full
            if created:
                with contextlib.suppress(Exception):
                    os.unlink(output_path)
            raise ValueError(f"No space left on device: {output_path}") from None
        raise
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
