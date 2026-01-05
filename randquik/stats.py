"""Statistics collection and formatting for workers."""

import re
import sys
import time
from dataclasses import dataclass, field

__all__ = [
    "ConsumerStats",
    "RunResult",
    "SingleThreadedStats",
    "WorkerStats",
    "format_size",
    "format_time",
    "format_worker_stats_report",
    "stopwatch",
]


def stopwatch():
    """Generator that yields elapsed time since last yield."""
    t = time.perf_counter()
    while True:
        now = time.perf_counter()
        yield now - t
        t = now


def format_size(size: float) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "kB", "MB", "GB", "TB"]:
        if abs(size) < 1000:
            return f"{size:.0f} {unit}"
        size /= 1000
    return f"{size:.0f} PB"


def format_time(seconds: float) -> str:
    """Format seconds as human-readable time."""
    if seconds < 0:
        return "--"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 120:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        if s == 0:
            return f"{m}m"
        return f"{m}m{s}s"
    elif seconds < 172800:  # 48 hours
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        if m == 0:
            return f"{h}h"
        return f"{h}h{m}m"
    else:
        d = int(seconds // 86400)
        h = int((seconds % 86400) // 3600)
        if h == 0:
            return f"{d}d"
        return f"{d}d{h}h"


@dataclass
class WorkerStats:
    """Timing statistics for a worker thread."""

    worker_id: int = -1
    # Lock timing breakdown
    lock_acquire_time: float = 0.0  # Time to acquire the lock (contention)
    lock_wait_space_time: float = 0.0  # Time waiting for has_space condition
    lock_claim_time: float = 0.0  # Time inside lock claiming block number
    lock_notify_time: float = 0.0  # Time inside lock marking ready + notify
    # Work timing
    crypto_time: float = 0.0
    # Counters
    blocks_processed: int = 0
    bytes_generated: int = 0
    wait_cycles: int = 0  # How many times we had to wait for space

    def total_time(self) -> float:
        """Total measured time."""
        return (
            self.lock_acquire_time
            + self.lock_wait_space_time
            + self.lock_claim_time
            + self.lock_notify_time
            + self.crypto_time
        )


@dataclass
class ConsumerStats:
    """Timing statistics for the consumer thread."""

    wait_time: float = 0.0
    write_time: float = 0.0

    def total_time(self) -> float:
        return self.wait_time + self.write_time


@dataclass
class SingleThreadedStats:
    """Timing statistics for single-threaded mode."""

    crypto_time: float = 0.0
    write_time: float = 0.0

    def total_time(self) -> float:
        return self.crypto_time + self.write_time


@dataclass
class RunResult:
    """Result from running a worker."""

    written: int
    elapsed: float
    interrupted: bool
    action: str = "wrote"
    # Raw stats objects (optional, for verbose output)
    consumer_stats: ConsumerStats | None = None
    singlethreaded_stats: SingleThreadedStats | None = None
    worker_stats: list[WorkerStats] = field(default_factory=list)
    # For continue command on interrupt
    continue_cmd: str | None = None
    # For repeat command (when seed was randomly generated)
    repeat_cmd: str | None = None

    def _format_io_stats(self) -> str | None:
        """Format I/O timing stats for the summary line."""
        if self.singlethreaded_stats is not None:
            st = self.singlethreaded_stats
            tt = st.total_time()
            if tt <= 0:
                return None
            return f"crypto {st.crypto_time / tt:.0%} — write {st.write_time / tt:.0%}"
        elif self.consumer_stats is not None:
            cs = self.consumer_stats
            tt = cs.total_time()
            if tt <= 0:
                return None
            return f"wait {cs.wait_time / tt:.0%} — write {cs.write_time / tt:.0%}"
        return None

    def print_summary(self, verbose: int = 0):
        """Print a nice one-liner summary with optional colors."""
        speed_gbs = (self.written / 1_000_000_000) / self.elapsed if self.elapsed > 0 else 0
        size_str = format_size(self.written)
        time_str = format_time(self.elapsed)

        # I/O stats for verbose mode
        io_stats = self._format_io_stats() if verbose >= 1 else None
        stats_fmt = f"\033[0;32m • {io_stats}" if io_stats else ""
        status_fmt = " \033[31m(interrupted)\033[0m" if self.interrupted else ""

        # Continue or repeat command
        cmd_line = ""
        if self.interrupted and self.continue_cmd:
            cmd_line = f"\n\033[2mContinue >>>\033[0;34m {self.continue_cmd}\033[0m"
        elif not self.interrupted and self.repeat_cmd:
            cmd_line = f"\n\033[2mRepeat >>>\033[0;34m {self.repeat_cmd}\033[0m"

        msg = (
            f"\n\033[36m[RandQuik]\033[32m {self.action} \033[1m{size_str}\033[0;32m in "
            f"\033[1m{time_str}\033[0;32m @ \033[1;32m{speed_gbs:.2f} GB/s{stats_fmt}\033[0m"
            f"{status_fmt}\033[1m{cmd_line}\n"
        )

        if not sys.stderr.isatty():
            msg = re.sub(r"\033\[[0-9;]*m", "", msg)

        sys.stderr.write(msg)

    def print_detailed_stats(self):
        """Print detailed worker statistics table (for -vv)."""
        if self.worker_stats and self.consumer_stats:
            report = format_worker_stats_report(self.worker_stats, self.consumer_stats)
            sys.stderr.write(report + "\n")


def format_worker_stats_report(
    worker_stats: list[WorkerStats], consumer_stats: ConsumerStats
) -> str:
    """Format a complete stats report for all workers as a table."""
    if not worker_stats:
        return "No worker stats available"

    def ms(val: float) -> str:
        return f"{val * 1000:.0f} ms"

    # Column width for worker data
    col_w = 8
    pct_w = 6  # Width for percentage column

    # Total time across all workers for percentage calculation
    total_all = sum(s.total_time() for s in worker_stats)

    def pct(val: float) -> str:
        return f"{100 * val / total_all:.0f}%" if total_all > 0 else "--"

    # Header row with worker numbers
    header = (
        "Worker stats"
        + f"{'%':>{pct_w}}"
        + "".join(f"{'W' + str(s.worker_id):>{col_w}}" for s in worker_stats)
    )
    sep = "-" * len(header)

    # Non-timing rows (counters)
    total_blocks = sum(s.blocks_processed for s in worker_stats)
    total_cycles = sum(s.wait_cycles for s in worker_stats)

    def cycles_pct() -> str:
        return f"{100 * total_cycles / total_blocks:.0f}%" if total_blocks > 0 else "--"

    counter_rows = [
        ("1MiB blocks", "", [str(s.blocks_processed) for s in worker_stats]),
        ("wait_cycles", cycles_pct(), [str(s.wait_cycles) for s in worker_stats]),
    ]

    # Timing rows with summed values for percentage
    timing_rows = [
        (
            "crypto",
            sum(s.crypto_time for s in worker_stats),
            [ms(s.crypto_time) for s in worker_stats],
        ),
        (
            "lock_acq",
            sum(s.lock_acquire_time for s in worker_stats),
            [ms(s.lock_acquire_time) for s in worker_stats],
        ),
        (
            "wait_sp",
            sum(s.lock_wait_space_time for s in worker_stats),
            [ms(s.lock_wait_space_time) for s in worker_stats],
        ),
        (
            "claim",
            sum(s.lock_claim_time for s in worker_stats),
            [ms(s.lock_claim_time) for s in worker_stats],
        ),
        (
            "notify",
            sum(s.lock_notify_time for s in worker_stats),
            [ms(s.lock_notify_time) for s in worker_stats],
        ),
    ]

    timing_rows.append(("total", total_all, [ms(s.total_time()) for s in worker_stats]))

    lines = [header, sep]
    for label, pct_val, values in counter_rows:
        row = f"{label:<12}" + f"{pct_val:>{pct_w}}" + "".join(f"{v:>{col_w}}" for v in values)
        lines.append(row)
    lines.append(sep)
    for label, total_val, values in timing_rows:
        row = (
            f"{label:<12}" + f"{pct(total_val):>{pct_w}}" + "".join(f"{v:>{col_w}}" for v in values)
        )
        lines.append(row)

    # Consumer stats
    lines.append(sep)
    return "\n".join(lines)
