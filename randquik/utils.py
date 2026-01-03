"""Utility functions for formatting and parsing."""

import pathlib
import re
import sys

__all__ = [
    "get_output_size",
    "get_sector_size",
    "parse_size",
    "sparse_range",
]


# Cache for sector size lookup (path -> size)
_sector_size_cache: dict[str, int] = {}


def get_sector_size(path: str | pathlib.Path) -> int:
    """Get sector size for a block device, or 512 as fallback."""
    import os
    import stat

    try:
        st = pathlib.Path(path).stat()
        if not stat.S_ISBLK(st.st_mode):
            return 512
    except OSError:
        return 512

    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            import fcntl
            import struct

            if sys.platform == "darwin":
                # macOS: DKIOCGETBLOCKSIZE = 0x40046418
                DKIOCGETBLOCKSIZE = 0x40046418
                buf = fcntl.ioctl(fd, DKIOCGETBLOCKSIZE, b"\x00" * 4)
                return struct.unpack("I", buf)[0]
            else:
                # Linux: BLKSSZGET = 0x1268
                BLKSSZGET = 0x1268
                buf = fcntl.ioctl(fd, BLKSSZGET, b"\x00" * 4)
                return struct.unpack("i", buf)[0]
        finally:
            os.close(fd)
    except (OSError, ImportError, Exception):
        return 512


def get_output_size(path: str | pathlib.Path | None) -> int | None:
    """Get the size of output file or block device.

    Returns None for stdout or non-existent files.
    Returns the size in bytes for existing files or block devices.
    """
    import os
    import stat

    if not path:
        return None  # stdout

    try:
        st = pathlib.Path(path).stat()
    except OSError:
        return None  # doesn't exist yet

    if stat.S_ISBLK(st.st_mode):
        # Block device - get size via ioctl
        try:
            fd = os.open(str(path), os.O_RDONLY)
            try:
                import fcntl
                import struct

                if sys.platform == "darwin":
                    # macOS: DKIOCGETBLOCKCOUNT and DKIOCGETBLOCKSIZE
                    DKIOCGETBLOCKCOUNT = 0x40086419
                    DKIOCGETBLOCKSIZE = 0x40046418
                    count_buf = fcntl.ioctl(fd, DKIOCGETBLOCKCOUNT, b"\x00" * 8)
                    size_buf = fcntl.ioctl(fd, DKIOCGETBLOCKSIZE, b"\x00" * 4)
                    block_count = struct.unpack("Q", count_buf)[0]
                    block_size = struct.unpack("I", size_buf)[0]
                    return block_count * block_size
                else:
                    # Linux: BLKGETSIZE64 = 0x80081272
                    BLKGETSIZE64 = 0x80081272
                    buf = fcntl.ioctl(fd, BLKGETSIZE64, b"\x00" * 8)
                    return struct.unpack("Q", buf)[0]
            finally:
                os.close(fd)
        except (OSError, ImportError, Exception):
            return None
    elif stat.S_ISREG(st.st_mode):
        return st.st_size
    else:
        return None


def parse_size(length: str | None, output_path: str | pathlib.Path | None = None) -> int | None:
    """Parse size string with SI/IEC prefixes.

    Supports:
    - Plain numbers: 1000, 1_000_000
    - SI prefixes: k, m, g, t, p (powers of 1000)
    - IEC prefixes: ki, mi, gi, ti, pi (powers of 1024)
    - Optional 'b' suffix: kb, kib, mb, mib, etc.
    - Special unit 'sect' = device sector size (detected, fallback 512)
    - Case insensitive

    Examples: 1k, 1ki, 1kb, 1kib, 100m, 100mi, 1g, 1gi, 10sect
    """
    if length is None:
        return None
    s = length.strip().lower().replace("_", "")

    # Handle sect unit
    m = re.match(r"^(\d+)\s*sect?s?$", s)
    if m:
        if output_path:
            path_str = str(output_path)
            if path_str not in _sector_size_cache:
                _sector_size_cache[path_str] = get_sector_size(output_path)
            sector_size = _sector_size_cache.get(path_str, 512)
        else:
            sector_size = 512
        return int(m.group(1)) * sector_size

    # SI/IEC prefixes
    si_prefixes = {"k": 1000, "m": 1000**2, "g": 1000**3, "t": 1000**4, "p": 1000**5}
    iec_prefixes = {
        "ki": 1024,
        "mi": 1024**2,
        "gi": 1024**3,
        "ti": 1024**4,
        "pi": 1024**5,
    }

    # Try IEC first (ki, mi, etc.) - must check before SI
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(ki|mi|gi|ti|pi)b?$", s)
    if m:
        num, prefix = m.groups()
        return int(float(num) * iec_prefixes[prefix])

    # Try SI (k, m, g, etc.)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kmgtp])b?$", s)
    if m:
        num, prefix = m.groups()
        return int(float(num) * si_prefixes[prefix])

    # Plain number
    m = re.match(r"^(\d+)$", s)
    if m:
        return int(m.group(1))

    raise ValueError(f"Invalid size format: {length}")


def sparse_range(n: int, max_items: int = 9) -> list[int]:
    """Generate a sparse range from 1 to N for benchmarking thread counts."""
    if n < 1:
        return [1]
    if n <= max_items - 1:
        return list(range(n + 1))

    keep = 3  # dense prefix: 1,2,3
    out = list(range(keep + 1))

    remaining = max_items - keep
    step = max(1, n // (remaining - 1))

    for k in range(1, remaining):
        v = k * step
        if v > out[-1]:
            out.append(v)

    if out[-1] != n:
        out[-1] = n

    return out
