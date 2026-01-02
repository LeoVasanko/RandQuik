"""Worker threads and ring buffer management for parallel generation."""

import logging
import os
import sys
import threading
from dataclasses import dataclass

from randquik.io import madvise_file
from randquik.utils import stopwatch

__all__ = [
    "BLOCK_SIZE",
    "FdProducer",
    "MmapProducer",
    "WorkerStats",
]


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
    madvise_time: float = 0.0
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
            + self.madvise_time
        )

    def format_report(self, label: str | None = None) -> str:
        """Format a human-readable report."""
        total = self.total_time()
        if total == 0:
            return f"Worker {self.worker_id}: no data"

        if label is None:
            label = f"Worker {self.worker_id}"

        def pct(val: float) -> str:
            return f"{100 * val / total:.1f}%" if total > 0 else "--"

        def ms(val: float) -> str:
            return f"{val * 1000:.1f}ms"

        lock_total = (
            self.lock_acquire_time
            + self.lock_wait_space_time
            + self.lock_claim_time
            + self.lock_notify_time
        )

        lines = [
            f"{label} ({self.blocks_processed} blocks, {self.bytes_generated / 1e6:.1f} MB):",
            f"  crypto:       {ms(self.crypto_time):>10} ({pct(self.crypto_time)})",
            f"  lock total:   {ms(lock_total):>10} ({pct(lock_total)})",
            f"    acquire:    {ms(self.lock_acquire_time):>10} ({pct(self.lock_acquire_time)})",
            f"    wait space: {ms(self.lock_wait_space_time):>10} ({pct(self.lock_wait_space_time)}) [{self.wait_cycles} cycles]",
            f"    claim:      {ms(self.lock_claim_time):>10} ({pct(self.lock_claim_time)})",
            f"    notify:     {ms(self.lock_notify_time):>10} ({pct(self.lock_notify_time)})",
        ]
        if self.madvise_time > 0:
            lines.append(f"  madvise:      {ms(self.madvise_time):>10} ({pct(self.madvise_time)})")
        lines.append(f"  total:        {ms(total):>10}")
        return "\n".join(lines)


BLOCK_SIZE = 1 << 20


class FdProducer:
    """Multi-threaded producer with ring buffer for sequential file output.

    Uses efficient synchronization:
    - Single lock with two conditions (has_data, has_space)
    - Workers wait on has_space, consumer waits on has_data
    - Crypto runs outside the lock
    """

    def __init__(
        self,
        workers: int,
        key: bytes,
        ciph,
        total_bytes: int | None,
        fd: int,
        dry: bool = False,
        iseek: int = 0,
        block_size: int = BLOCK_SIZE,
        profile: bool = False,
    ):
        self.workers = workers
        self.key = key
        self.ciph = ciph
        self.total_bytes = total_bytes
        self.fd = fd
        self.dry = dry
        self.iseek = iseek
        self.block_size = block_size
        self.profile = profile

        # iseek handling: which block to start at, and offset within first block
        self.start_block = iseek // block_size
        self.start_offset = iseek % block_size

        # Ring buffer state - more slots reduce wait time
        # With N workers, we want enough buffers so workers rarely wait
        self.num_slots = workers * 4
        self._buf = bytearray(self.num_slots * block_size)

        # Single lock with conditions (simpler, faster than semaphore + events)
        self._lock = threading.Lock()
        self._has_data = threading.Condition(self._lock)
        self._has_space = threading.Condition(self._lock)

        self._genpos = 0  # next block to generate
        self._conpos = 0  # next block to consume
        self._ready = [False] * self.num_slots  # which slots have data
        self._quit = False

        self._threads: list[threading.Thread] = []
        self.written = 0
        self.wait_time = 0.0
        self.write_time = 0.0

        # Per-worker stats, collected after threads finish
        self._worker_stats: list[WorkerStats] = []
        self._stats_lock = threading.Lock()

    def start(self):
        """Start worker threads."""
        for i in range(self.workers):
            t = threading.Thread(target=self._worker, args=(i,), daemon=True)
            self._threads.append(t)
            t.start()

    def _worker_fast(self, view):
        """Fast worker loop without profiling."""
        while True:
            with self._lock:
                # Wait for a slot
                while self._genpos - self._conpos >= self.num_slots:
                    if self._quit:
                        return
                    self._has_space.wait()
                if self._quit:
                    return
                block_num = self._genpos
                self._genpos += 1

            # Generate outside lock
            slot = block_num % self.num_slots
            buf = view[slot * self.block_size : (slot + 1) * self.block_size]
            actual_block = self.start_block + block_num
            self.ciph.stream(
                self.key, actual_block.to_bytes(self.ciph.NONCEBYTES, "little"), into=buf
            )

            # Mark ready
            with self._lock:
                self._ready[slot] = True
                self._has_data.notify()

    def _worker_profile(self, worker_id: int, view, stats: WorkerStats, timer):
        """Worker loop with detailed profiling."""
        stats.worker_id = worker_id
        while True:
            # Measure lock acquisition (contention)
            next(timer)
            self._lock.acquire()
            stats.lock_acquire_time += next(timer)

            try:
                # Measure time waiting for space
                while self._genpos - self._conpos >= self.num_slots:
                    if self._quit:
                        self._lock.release()
                        return
                    next(timer)
                    self._has_space.wait()
                    stats.lock_wait_space_time += next(timer)
                    stats.wait_cycles += 1

                if self._quit:
                    self._lock.release()
                    return

                # Measure claiming block number
                next(timer)
                block_num = self._genpos
                self._genpos += 1
                stats.lock_claim_time += next(timer)
            finally:
                self._lock.release()

            slot = block_num % self.num_slots
            buf = view[slot * self.block_size : (slot + 1) * self.block_size]
            actual_block = self.start_block + block_num

            # Measure crypto
            next(timer)
            self.ciph.stream(
                self.key, actual_block.to_bytes(self.ciph.NONCEBYTES, "little"), into=buf
            )
            stats.crypto_time += next(timer)
            stats.blocks_processed += 1
            stats.bytes_generated += self.block_size

            # Measure notify (lock acquire + mark ready + notify)
            next(timer)
            with self._lock:
                self._ready[slot] = True
                self._has_data.notify()
            stats.lock_notify_time += next(timer)

    def _worker(self, worker_id: int):
        view = memoryview(self._buf)
        stats = WorkerStats(worker_id=worker_id) if self.profile else None
        try:
            if self.profile:
                timer = stopwatch()
                self._worker_profile(worker_id, view, stats, timer)
            else:
                self._worker_fast(view)
        except BaseException as e:
            logging.exception("Worker thread exception: %s", e)
        finally:
            view.release()
            if stats:
                with self._stats_lock:
                    self._worker_stats.append(stats)
            with self._lock:
                self._quit = True
                self._has_data.notify_all()

    def run(self, progress_state: dict | None = None):
        """Consume blocks and write to fd. Call start() first."""
        view = memoryview(self._buf)
        timer = stopwatch()
        is_first_block = True
        try:
            while self.total_bytes is None or self.written < self.total_bytes:
                with self._lock:
                    slot = self._conpos % self.num_slots
                    while not self._ready[slot]:
                        if self._quit:
                            return
                        self._has_data.wait()
                    self._ready[slot] = False
                    self._conpos += 1
                    self._has_space.notify()

                self.wait_time += next(timer)
                buf = view[slot * self.block_size : (slot + 1) * self.block_size]
                # Handle first block: skip start_offset bytes
                if is_first_block and self.start_offset > 0:
                    buf_start = self.start_offset
                    is_first_block = False
                else:
                    buf_start = 0

                to_write = min(
                    self.block_size - buf_start,
                    self.total_bytes - self.written
                    if self.total_bytes is not None
                    else self.block_size - buf_start,
                )
                if not self.dry:
                    os.write(self.fd, buf[buf_start : buf_start + to_write])
                self.write_time += next(timer)
                self.written += to_write
                if progress_state is not None:
                    progress_state["written"] = self.written
        finally:
            view.release()

    def stop(self):
        """Signal workers to stop and wait for them."""
        with self._lock:
            self._quit = True
            self._has_space.notify_all()
        for t in self._threads:
            t.join()

    def get_worker_stats(self) -> list[WorkerStats]:
        """Get stats for each worker. Call after stop()."""
        with self._stats_lock:
            # Sort by worker_id for consistent output
            return sorted(self._worker_stats, key=lambda s: s.worker_id)

    def format_stats_report(self) -> str:
        """Format a complete stats report for all workers."""
        lines = []
        stats_list = self.get_worker_stats()

        if not stats_list:
            return "No worker stats available"

        # Per-worker stats
        for stats in stats_list:
            lines.append(stats.format_report())

        # Consumer stats
        lines.append("Consumer:")
        lines.append(f"  wait time:  {self.wait_time * 1000:.1f}ms")
        lines.append(f"  write time: {self.write_time * 1000:.1f}ms")

        return "\n".join(lines)


class MmapProducer:
    """Multi-threaded producer that writes directly into mmap."""

    def __init__(
        self,
        workers: int,
        key: bytes,
        ciph,
        total_bytes: int | None,
        mm_raw=None,
        use_madvise: bool = False,
        oseek: int = 0,
        iseek: int = 0,
        block_size: int = BLOCK_SIZE,
        dry: bool = False,
    ):
        self.workers = workers
        self.key = key
        self.ciph = ciph
        self.total_bytes = total_bytes
        self.use_madvise = use_madvise
        self.oseek = oseek
        self.iseek = iseek
        self.block_size = block_size
        self.dry = dry
        self.written = 0

        # For dry runs, create an anonymous mmap
        import mmap as mmap_module

        if dry:
            length = oseek + (total_bytes if total_bytes is not None else 0)
            self.mm_raw = mmap_module.mmap(-1, length)
            self._owns_mmap = True
        else:
            self.mm_raw = mm_raw
            self._owns_mmap = False

        # iseek handling: which block to start at, and offset within first block
        self.start_block = iseek // block_size
        self.start_offset = iseek % block_size

        if total_bytes is None:
            self.num_blocks = sys.maxsize // block_size
        else:
            self.num_blocks = (total_bytes + block_size - 1) // block_size
            # If first block is partial, we need one more block to cover total_bytes
            if self.start_offset > 0 and total_bytes > 0:
                self.num_blocks = (self.start_offset + total_bytes + block_size - 1) // block_size
        self._lock = threading.Lock()
        self._next_block = 0
        self._quit = threading.Event()
        self._threads: list[threading.Thread] = []
        self.progress_state: dict | None = None

        # Per-worker stats, collected after threads finish
        self._worker_stats: list[WorkerStats] = []
        self._stats_lock = threading.Lock()

    def start(self):
        """Start worker threads."""
        for _ in range(self.workers):
            t = threading.Thread(target=self._worker, daemon=True)
            self._threads.append(t)
            t.start()

    def _worker(self):
        # Create thread-local memoryview from mmap
        view = memoryview(self.mm_raw)
        # Temporary buffer for first/last partial blocks
        tmp_buf = bytearray(self.block_size)
        stats = WorkerStats()
        timer = stopwatch()
        try:
            while True:
                next(timer)  # reset
                with self._lock:
                    stats.lock_acquire_time += next(timer)
                    if self._next_block >= self.num_blocks:
                        return
                    block_num = self._next_block
                    self._next_block += 1

                # Calculate actual nonce (accounting for iseek)
                actual_block = self.start_block + block_num
                nonce = actual_block.to_bytes(self.ciph.NONCEBYTES, "little")

                # Calculate byte range within output
                # block_num=0 corresponds to output byte 0
                # But if start_offset > 0, first block is partial
                next(timer)  # reset for crypto timing
                if block_num == 0 and self.start_offset > 0:
                    # First partial block: generate full block, copy from start_offset
                    self.ciph.stream(self.key, nonce, self.block_size, into=tmp_buf)
                    if self.total_bytes is None:
                        copy_len = self.block_size - self.start_offset
                    else:
                        copy_len = min(self.block_size - self.start_offset, self.total_bytes)
                    out_start = self.oseek
                    out_end = out_start + copy_len
                    view[out_start:out_end] = tmp_buf[
                        self.start_offset : self.start_offset + copy_len
                    ]
                    written = copy_len
                else:
                    # Full block or last partial block
                    # Output position: account for first block being partial
                    if self.start_offset > 0:
                        out_start = (
                            self.oseek
                            + (self.block_size - self.start_offset)
                            + (block_num - 1) * self.block_size
                        )
                    else:
                        out_start = self.oseek + block_num * self.block_size
                    if self.total_bytes is None:
                        out_end = out_start + self.block_size
                    else:
                        out_end = min(out_start + self.block_size, self.oseek + self.total_bytes)
                    size = out_end - out_start
                    self.ciph.stream(self.key, nonce, size, into=view[out_start:out_end])
                    written = size

                stats.crypto_time += next(timer)
                stats.blocks_processed += 1
                stats.bytes_generated += written

                if self.use_madvise and self.mm_raw:
                    next(timer)  # reset
                    madvise_file(self.mm_raw, out_start, written)
                    stats.madvise_time += next(timer)

                next(timer)  # reset
                with self._lock:
                    self.written += written
                    if self.progress_state is not None:
                        self.progress_state["written"] = self.written
                stats.notify_time += next(timer)
        except BaseException as e:
            logging.exception("Worker thread exception: %s", e)
        finally:
            view.release()
            # Collect stats before signaling quit
            with self._stats_lock:
                self._worker_stats.append(stats)
            self._quit.set()
            self._quit.wait()

    def join(self):
        """Wait for all worker threads to finish."""
        for t in self._threads:
            t.join()

    def stop(self):
        """Signal workers to stop."""
        self._quit.set()

    def cleanup(self):
        """Release references to mmap resources."""
        if self._owns_mmap and self.mm_raw is not None:
            self.mm_raw.close()
        self.mm_raw = None
        self._threads.clear()

    def get_combined_stats(self) -> WorkerStats:
        """Get combined stats from all workers. Call after join()."""
        combined = WorkerStats()
        with self._stats_lock:
            for s in self._worker_stats:
                combined.merge(s)
        return combined
