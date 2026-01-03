"""Command-line interface for RandQuik."""

import argparse
import gc
import sys

import aeg

from randquik.benchmark import run_benchmark
from randquik.crypto import derive_key, generate_random_seed
from randquik.utils import parse_size
from randquik.workers import run

__all__ = ["main"]

# Disable GC for performance
gc.disable()

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
        action="count",
        default=0,
        help="Verbose mode: -v for I/O mode, -vv for worker statistics",
    )

    args = parser.parse_args()

    # Normalize "-" output to None (stdout)
    if args.output == "-":
        args.output = None

    ciph = aeg.cipher(args.alg or DEFAULT_ALG)

    # Validate and process args
    seed, generated_seed = prepare_seed(args)
    key = prepare_key(seed, ciph.KEYBYTES)
    iseek, oseek = parse_seeks(args)
    total_bytes = parse_size(args.len)  # None if not specified, 0 if -l0
    # Always track the seed for commands, but only show repeat for generated seeds
    seed_for_display = seed

    if args.benchmark:
        if args.seed is not None:
            raise ValueError("Cannot specify seed in benchmark mode")
        if iseek or oseek:
            raise ValueError("Cannot use seek options in benchmark mode")
        run_benchmark(args)
        return

    # Build continue command for interruption
    action = "generated" if args.dry else "wrote"
    continue_cmd = None
    repeat_cmd = None
    if args.output and seed_for_display:
        # Will be updated with actual written bytes after run
        continue_cmd = f"randquik -s {seed_for_display} --seek {{seek}} -o {args.output}"
        if args.len:
            continue_cmd += f" -l {args.len}"
    # Build repeat command for randomly generated seeds (so user can reproduce)
    if generated_seed and not args.quiet:
        repeat_cmd = f"randquik -s {seed_for_display}"
        if args.len:
            repeat_cmd += f" -l {args.len}"
        if args.output:
            repeat_cmd += f" -o {args.output}"

    # Run generation
    workers = args.threads if args.threads is not None else 1
    result = run(
        output=args.output,
        total_bytes=total_bytes,
        iseek=iseek,
        oseek=oseek,
        key=key,
        ciph=ciph,
        workers=workers,
        dry=args.dry,
        quiet=args.quiet,
        action=action,
    )

    # Set repeat command for generated seeds
    result.repeat_cmd = repeat_cmd

    # Update continue command with actual written bytes
    if result.interrupted and result.written > 0 and args.output:
        new_iseek = iseek + result.written
        new_oseek = oseek + result.written
        if new_iseek == new_oseek:
            result.continue_cmd = (
                f"randquik -s {seed_for_display} --seek {new_iseek} -o {args.output}"
            )
        else:
            result.continue_cmd = f"randquik -s {seed_for_display} --iseek {new_iseek} --oseek {new_oseek} -o {args.output}"
        if args.len:
            result.continue_cmd += f" -l {args.len}"

    # Print summary
    show_summary = not args.quiet or args.verbose >= 1 or result.interrupted
    if show_summary and (total_bytes is not None or result.interrupted):
        result.print_summary(verbose=args.verbose)
    if args.verbose >= 2:
        result.print_detailed_stats()

    if result.interrupted:
        sys.exit(1)


def main():
    """Main entry point for the CLI with exception handling."""
    try:
        _main()
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
