"""RandQuik - High-performance cryptographic random data generator.

This package provides fast random data generation using AEGIS ciphers,
with support for multi-threaded generation and various I/O modes.
"""

from randquik.crypto import derive_key, generate_random_seed
from randquik.progress import ProgressDisplay
from randquik.stats import format_size, format_time
from randquik.utils import parse_size

try:
    from randquik._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"

__all__ = [
    "ProgressDisplay",
    "__version__",
    "derive_key",
    "format_size",
    "format_time",
    "generate_random_seed",
    "parse_size",
]
