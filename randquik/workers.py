"""Worker threads and ring buffer management for parallel generation."""

import logging
import os
import sys
import threading

from randquik.io import madvise_file
from randquik.utils import stopwatch

__all__ = [
    "BLOCK_SIZE",
    "FdProducer",
    "MmapProducer",
]

BLOCK_SIZE = 1 << 20


class FdProducer:
    """Multi-threaded producer with ring buffer for sequential file output."""

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

        # Ring buffer state
        self.num_slots = workers + 1
        self._buf = bytearray(self.num_slots * block_size)
        self._lock = threading.Lock()
        self.needdata = threading.Condition(self._lock)
        self.needspace = threading.Condition(self._lock)
        self._ready = [False] * self.num_slots
        self._genpos = 0
        self._conpos = 0
        self._quit = threading.Event()

        self._threads: list[threading.Thread] = []
        self.written = 0
        self.wait_time = 0.0
        self.write_time = 0.0

    def start(self):
        """Start worker threads."""
        for _ in range(self.workers):
            t = threading.Thread(target=self._worker, daemon=True)
            self._threads.append(t)
            t.start()

    def _worker_round(self, view) -> bool:
        """Process one block. Returns True if work was done, False if should quit."""
        with self._lock:
            while self._genpos - self._conpos >= self.num_slots:
                if self._quit.is_set():
                    return False
                self.needspace.wait()
            if self._quit.is_set():
                return False
            block_num = self._genpos
            self._genpos += 1
        slot = block_num % self.num_slots
        buf = view[slot * self.block_size : (slot + 1) * self.block_size]
        # Use start_block + block_num as actual nonce to handle iseek
        actual_block = self.start_block + block_num
        self.ciph.stream(self.key, actual_block.to_bytes(self.ciph.NONCEBYTES, "little"), into=buf)
        with self._lock:
            self._ready[slot] = True
            self.needdata.notify_all()
        return True

    def _worker(self):
        # Thread-local memoryview of the shared buffer
        view = memoryview(self._buf)
        try:
            while self._worker_round(view):
                pass
        except BaseException as e:
            logging.exception("Worker thread exception: %s", e)
        finally:
            view.release()
            self._quit.set()
            with self._lock:
                self.needdata.notify_all()

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
                        if self._quit.is_set():
                            return
                        self.needdata.wait()
                    self._ready[slot] = False

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

                with self._lock:
                    self._conpos += 1
                    self.needspace.notify_all()
        finally:
            view.release()

    def stop(self):
        """Signal workers to stop and wait for them."""
        with self._lock:
            self._quit.set()
            self.needspace.notify_all()
        for t in self._threads:
            t.join()


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
        try:
            while True:
                with self._lock:
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

                if self.use_madvise and self.mm_raw:
                    madvise_file(self.mm_raw, out_start, written)
                with self._lock:
                    self.written += written
                    if self.progress_state is not None:
                        self.progress_state["written"] = self.written
        except BaseException as e:
            logging.exception("Worker thread exception: %s", e)
        finally:
            view.release()
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
