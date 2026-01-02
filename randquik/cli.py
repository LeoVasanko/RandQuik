"""Command-line interface for RandQuik."""

import argparse
import gc
import mmap
import os
import sys
import time

import aeg
import tracerite

from randquik.benchmark import run_benchmark
from randquik.crypto import derive_key, generate_random_seed
from randquik.io import open_fd
from randquik.progress import ProgressDisplay
from randquik.utils import (
    parse_size,
    print_summary,
)
from randquik.workers import (
    BLOCK_SIZE,
    FdProducer,
    MmapProducer,
)

tracerite.load()

__all__ = ["main"]

# Disable GC for performance
gc.disable()

ciph: aeg.Cipher = None  # type: ignore (set in main after parsing args)

DEFAULT_ALG = "AEGIS-128X2"


def prepare_seed(args):
    """Prepare seed and determine if it was generated."""
    generated_seed = args.seed is None
    seed = generate_random_seed() if generated_seed else args.seed
    return seed, generated_seed


def prepare_key(seed, keybytes):
    """Derive key from seed."""
    key = derive_key(seed, keybytes)
    return key


def parse_seeks(args):
    """Parse seek values from arguments."""
    try:
        iseek = parse_size(args.iseek, args.output) or 0
        oseek = parse_size(args.oseek, args.output) or 0
        if args.seek:
            iseek = oseek = parse_size(args.seek, args.output) or 0
    except ValueError as e:
        raise ValueError(f"Error parsing seek: {e}") from None
    return iseek, oseek


def _mmap(output: str | None, oseek: int, length: int, *, dry=False) -> mmap.mmap:
    with open_fd(output, length, oseek=oseek, dry=dry) as fd:
        try:
            return mmap.mmap(fd, length)
        except (OSError, ValueError) as e:
            if fd == -1:
                raise ValueError("Cannot mmap all memory: specify --len SIZE") from e
            if not output:
                raise ValueError("Cannot mmap stdout: remove --mmap or use -o FILE") from e
            raise ValueError(f"Cannot mmap {output}: {e}") from e


def singlethreaded(args, total_bytes, oseek, start_time, key, seed_for_display):
    if args.verbose:
        mode_desc = "infinite output" if total_bytes is None else "workers=0"
        print(
            f"Special mode: {mode_desc} — single-buffer, single-threaded generation",
            file=sys.stderr,
        )

    with open_fd(
        args.output, 0 if total_bytes is None else total_bytes, dry=args.dry, oseek=oseek
    ) as fd:
        written = 0
        buf = bytearray(BLOCK_SIZE)
        view = memoryview(buf)
        nonce = bytearray(ciph.NONCEBYTES)

        progress_state = {"written": 0}
        progress = ProgressDisplay(
            total_bytes,
            start_time,
            progress_state,
            infinite=total_bytes is None,
            seed=seed_for_display,
        )
        if not args.quiet:
            progress.start()

        try:
            while total_bytes is None or written < total_bytes:
                start = written
                if total_bytes is None:
                    size = BLOCK_SIZE
                else:
                    end = min(start + BLOCK_SIZE, total_bytes)
                    size = end - start
                chunk = view[:size]
                ciph.stream(key, nonce, size, into=chunk)
                if not args.dry:
                    os.write(fd, chunk)
                ciph.nonce_increment(nonce)
                written += size
                progress_state["written"] = written
        finally:
            progress.stop()
            elapsed = time.perf_counter() - start_time
            action = "generated" if args.dry else "wrote"
            if not args.quiet and total_bytes is not None:
                print_summary(written, elapsed, action, seed=seed_for_display)


def _main():
    """Internal main function that may raise exceptions."""
    parser = argparse.ArgumentParser(description="Generate random bytes using AEGIS ciphers")
    parser.add_argument("-s", "--seed", help="Alphanumeric seed string", type=str)
    parser.add_argument(
        "-l",
        "--len",
        help="Length to generate (e.g. 1g, 100mi, 1000sect)",
        type=str,
        default=None,
    )
    parser.add_argument("-o", "--output", help="Output file (default: stdout)", type=str)
    parser.add_argument(
        "-t",
        "--threads",
        help="Number of worker threads (benchmark: upper limit)",
        type=int,
        default=None,
    )
    parser.add_argument(
        "-a",
        "--alg",
        help=f"Cipher algorithm (default: {DEFAULT_ALG})",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--mmap",
        action="store_true",
        help="Use file-backed mmap for output instead of writing via fd",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run benchmark (generates 1GB and reports speed)",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Dry run: open output but skip writes (for benchmarking)",
    )
    parser.add_argument(
        "--seek",
        type=str,
        default=None,
        help="Seek both input stream and output to position (e.g. 1g, 100mi)",
    )
    parser.add_argument(
        "--iseek",
        type=str,
        default=None,
        help="Seek input random stream to position (overrides --seek)",
    )
    parser.add_argument(
        "--oseek",
        type=str,
        default=None,
        help="Seek output file to position (overrides --seek)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode: suppress all output except errors",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose mode: show I/O mode and timing statistics",
    )

    args = parser.parse_args()

    # Normalize "-" output to None (stdout)
    if args.output == "-":
        args.output = None

    global ciph
    ciph = aeg.cipher(args.alg or DEFAULT_ALG)

    # Validate and process args
    seed, generated_seed = prepare_seed(args)
    key = prepare_key(seed, ciph.KEYBYTES)
    iseek, oseek = parse_seeks(args)
    total_bytes = parse_size(args.len)  # None if not specified, 0 if -l0
    # Seed hint for generated seeds
    seed_for_display = seed if generated_seed else None

    start_time = time.perf_counter()

    if args.benchmark:
        if args.seed is not None:
            raise ValueError("Cannot specify seed in benchmark mode")
        if iseek or oseek:
            raise ValueError("Cannot use seek options in benchmark mode")
        run_benchmark(args)
        return

    # Single-threaded mode (workers == 0)
    if args.threads == 0:
        return singlethreaded(args, total_bytes, oseek, start_time, key, seed_for_display)

    workers = args.threads if args.threads is not None else 1
    # File-backed mmap output
    if args.mmap:
        with (
            _mmap(
                args.output,
                oseek,
                length=oseek + (total_bytes if total_bytes is not None else 0),
                dry=args.dry,
            ) as mm,
        ):
            producer = MmapProducer(
                workers,
                key,
                ciph,
                total_bytes,
                mm,
                use_madvise=True,
                oseek=oseek,
                iseek=iseek,
            )
            progress_state = {"written": 0}
            producer.progress_state = progress_state
            producer.start()

            progress = ProgressDisplay(
                total_bytes, start_time, progress_state, seed=seed_for_display
            )
            if not args.quiet:
                progress.start()

            try:
                producer.join()
            finally:
                progress.stop()
                producer.cleanup()
        elapsed = time.perf_counter() - start_time
        if not args.quiet:
            print_summary(producer.written, elapsed, "wrote", seed=seed_for_display)
        return

    # Standard file mode with ring buffers
    with open_fd(args.output, total_bytes, dry=args.dry, oseek=oseek) as fd:
        producer = FdProducer(workers, key, ciph, total_bytes, fd, dry=args.dry, iseek=iseek)

        if args.verbose:
            dry_str = " (dry run)" if args.dry else ""
            print(
                f"I/O mode: {workers} workers, {producer.num_slots} buffers, sequential writes{dry_str}",
                file=sys.stderr,
            )

        progress_state = {"written": 0}
        progress = ProgressDisplay(total_bytes, start_time, progress_state, seed=seed_for_display)
        if not args.quiet:
            progress.start()

        try:
            producer.start()
            producer.run(progress_state)
        finally:
            producer.stop()
            progress.stop()
            elapsed = time.perf_counter() - start_time
            if not args.quiet:
                print_summary(producer.written, elapsed, "wrote", seed=seed_for_display)


def main():
    """Main entry point for the CLI with exception handling."""
    try:
        _main()
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
