"""Worker threads and ring buffer management for parallel generation."""

import os
import sys
import threading
import time

from randquik.io import open_fd
from randquik.progress import ProgressDisplay
from randquik.stats import (
    ConsumerStats,
    RunResult,
    SingleThreadedStats,
    WorkerStats,
    stopwatch,
)

__all__ = [
    "BLOCK_SIZE",
    "RunResult",
    "run",
]


BLOCK_SIZE = 1 << 20


class _FdProducer:
    """Multi-threaded producer with ring buffer for sequential file output.

    Uses efficient synchronization:
    - Single lock with two conditions (has_data, has_space)
    - Workers wait on has_space, notify has_data when block is ready
    - Consumer waits on has_data, notifies has_space when block is consumed
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
    ):
        self.workers = workers
        self.key = key
        self.ciph = ciph
        self.total_bytes = total_bytes
        self.fd = fd
        self.dry = dry
        self.iseek = iseek
        self.block_size = block_size

        # iseek handling: which block to start at, and offset within first block
        self.start_block = iseek // block_size
        self.start_offset = iseek % block_size

        self.num_slots = workers + 2  # Tested optimal (+1 for I/O and +1 to avoid congestion)
        self._buf = bytearray(self.num_slots * block_size)

        # Separate conditions for producers and consumer
        self._lock = threading.Lock()
        self.has_data = threading.Condition(self._lock)  # Consumer waits, workers notify
        self.has_space = threading.Condition(self._lock)  # Workers wait, consumer notifies
        self.lock_blkno = threading.Lock()
        self.blkno = self.start_block  # next block to generate
        self.ready = [False] * self.num_slots  # which block number is there ready
        self.quit = False

        self.threads: list[threading.Thread] = []
        self.written = 0
        self.consumer_stats = ConsumerStats()

        # Per-worker stats, collected after threads finish
        self._worker_stats: list[WorkerStats] = []
        self._stats_lock = threading.Lock()

    def start(self):
        self.threads = [
            threading.Thread(target=self.worker, args=(i,)) for i in range(self.workers)
        ]
        for t in self.threads:
            t.start()

    def worker(self, worker_id: int):
        assert self.num_slots >= self.workers, "Ring buffer quarantee broken"
        view = memoryview(self._buf)
        slots = [
            view[i * self.block_size : (i + 1) * self.block_size] for i in range(self.num_slots)
        ]

        # Profiling setup
        stats = WorkerStats(worker_id=worker_id)
        timer = stopwatch()

        try:
            while True:
                # Claim next block number
                with self.lock_blkno:
                    blkno = self.blkno
                    self.blkno += 1
                stats.lock_claim_time += next(timer)

                with self._lock:
                    stats.lock_acquire_time += next(timer)
                    # Wait for the NEXT slot to be free
                    slot = blkno % self.num_slots
                    while self.ready[slot] and not self.quit:
                        stats.wait_cycles += 1
                        self.has_space.wait()
                    stats.lock_wait_space_time += next(timer)
                    if self.quit:
                        return

                # Generate block
                self.ciph.stream(
                    self.key,
                    blkno.to_bytes(self.ciph.NONCEBYTES, "little"),
                    into=slots[slot],
                )
                stats.crypto_time += next(timer)
                stats.blocks_processed += 1
                stats.bytes_generated += self.block_size

                # Commit block (mark ready + notify consumer)
                with self._lock:
                    self.ready[slot] = True
                    self.has_data.notify()

        finally:
            view.release()
            with self._stats_lock:
                self._worker_stats.append(stats)

    def consumer(self, progress_state: dict | None = None):
        """Consume blocks and write to fd. Call start() first."""
        view = memoryview(self._buf)
        try:
            slots = [
                view[i * self.block_size : (i + 1) * self.block_size] for i in range(self.num_slots)
            ]
            blkno = self.start_block
            slot = blkno % self.num_slots
            total = sys.maxsize if self.total_bytes is None else self.total_bytes
            # Handle the first block: skip start_offset bytes (note: this is purposefully left out of stats)
            with self.has_data:
                while not self.ready[slot] and not self.quit:
                    self.has_data.wait()
                if self.quit:
                    return

                buf = slots[slot][self.start_offset : self.start_offset + total]
                if not self.dry:
                    os.write(self.fd, buf)
                self.written += len(buf)
            # Other blocks
            timer = stopwatch()
            while self.written < total:
                # Take/wait for expected slot
                with self._lock:
                    # Release previous slot and notify workers
                    self.ready[slot] = False
                    self.has_space.notify_all()
                    # Wait for the next buffer to be ready
                    blkno += 1
                    slot = blkno % self.num_slots
                    while not self.ready[slot] and not self.quit:
                        self.has_data.wait()
                    if self.quit:
                        return
                self.consumer_stats.wait_time += next(timer)
                buf = slots[slot]
                # Last block? Trim to remaining size
                if self.written + len(buf) > total:
                    buf = buf[: total - self.written]
                if not self.dry:
                    os.write(self.fd, buf)

                self.consumer_stats.write_time += next(timer)
                self.written += len(buf)
                if progress_state is not None:
                    progress_state["written"] = self.written

        finally:
            self.stop()
            view.release()

    def stop(self):
        """Signal workers to stop and wait for them."""
        with self._lock:
            self.quit = True
            self.has_data.notify_all()
            self.has_space.notify_all()
        for t in self.threads:
            t.join()

    def get_worker_stats(self) -> list[WorkerStats]:
        """Get stats for each worker. Call after stop()."""
        with self._stats_lock:
            # Sort by worker_id for consistent output
            return sorted(self._worker_stats, key=lambda s: s.worker_id)

    def run(self, progress_state: dict | None = None):
        """Run multi-threaded generation."""
        self.start()
        try:
            self.consumer(progress_state)
        finally:
            self.stop()


class _SingleThreadedProducer:
    """Single-threaded producer for infinite output or workers=0 mode."""

    def __init__(
        self,
        key: bytes,
        ciph,
        total_bytes: int | None,
        fd: int,
        dry: bool = False,
        block_size: int = BLOCK_SIZE,
    ):
        self.key = key
        self.ciph = ciph
        self.total_bytes = total_bytes
        self.fd = fd
        self.dry = dry
        self.block_size = block_size

        self.written = 0
        self.stats = SingleThreadedStats()

    def run(self, progress_state: dict | None = None):
        """Generate and write blocks sequentially."""
        buf = bytearray(self.block_size)
        view = memoryview(buf)
        nonce = bytearray(self.ciph.NONCEBYTES)
        total = sys.maxsize if self.total_bytes is None else self.total_bytes
        timer = stopwatch()

        try:
            while self.written < total:
                size = min(self.block_size, total - self.written)
                chunk = view[:size]
                self.ciph.stream(self.key, nonce, size, into=chunk)
                self.stats.crypto_time += next(timer)
                if not self.dry:
                    os.write(self.fd, chunk)
                self.stats.write_time += next(timer)
                self.ciph.nonce_increment(nonce)
                self.written += size
                if progress_state is not None:
                    progress_state["written"] = self.written
        finally:
            view.release()


def run(
    output: str | None,
    total_bytes: int | None,
    iseek: int,
    oseek: int,
    key: bytes,
    ciph,
    workers: int = 1,
    dry: bool = False,
    quiet: bool = False,
    action: str = "wrote",
    continue_cmd: str | None = None,
) -> RunResult:
    """Run random generation with specified number of workers. Returns RunResult.

    Args:
        workers: Number of worker threads. 0 for single-threaded mode.
    """
    start_time = time.perf_counter()
    infinite = total_bytes is None
    fd_size = 0 if infinite else total_bytes

    with open_fd(output, fd_size, dry=dry, oseek=oseek) as fd:
        if workers == 0:
            producer = _SingleThreadedProducer(key, ciph, total_bytes, fd, dry=dry)
        else:
            producer = _FdProducer(workers, key, ciph, total_bytes, fd, dry=dry, iseek=iseek)

        progress_state = {"written": 0}
        progress = ProgressDisplay(
            total_bytes,
            start_time,
            progress_state,
            infinite=infinite,
            output_name=output,
            oseek=oseek,
        )
        if not quiet:
            progress.start()

        interrupted = False
        try:
            producer.run(progress_state)
        except (KeyboardInterrupt, BrokenPipeError):
            interrupted = True
        finally:
            progress.stop()

        elapsed = time.perf_counter() - start_time

        # Build result with raw stats
        if workers == 0:
            return RunResult(
                written=producer.written,
                elapsed=elapsed,
                interrupted=interrupted,
                action=action,
                singlethreaded_stats=producer.stats,
                continue_cmd=continue_cmd,
            )
        else:
            return RunResult(
                written=producer.written,
                elapsed=elapsed,
                interrupted=interrupted,
                action=action,
                consumer_stats=producer.consumer_stats,
                worker_stats=producer.get_worker_stats(),
                continue_cmd=continue_cmd,
            )
