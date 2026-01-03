"""Benchmark functions for measuring performance."""

import contextlib
import os
import pathlib
import re
import subprocess
import sys
import time

from randquik.utils import sparse_range

__all__ = ["bench_mode", "run_benchmark"]


def bench_mode(
    tcounts: list[int],
    io_mode: str,
    length: str,
    alg: str | None,
    bench_file: pathlib.Path | None,
) -> list[tuple[int, float, list[str]]]:
    max_repeats = 5
    max_time = 0.5  # Quit early if more than 500ms has passed
    results = []

    # Use a file in current folder for file modes
    if "file" in io_mode:
        iocmd = ["-o", str(bench_file)]
    elif "dry" in io_mode:
        iocmd = ["--dry"]
    elif "null" in io_mode:
        iocmd = ["-o", os.devnull]
    else:
        raise ValueError(f"Unknown io_mode: {io_mode}")

    # Print iocmd at start of row
    sys.stdout.write(f"{' '.join(iocmd)[:20]:<20}")
    sys.stdout.flush()

    for workers in tcounts:
        speeds = []
        worker_start = time.perf_counter()
        for rep in range(max_repeats):
            if rep > 0 and (time.perf_counter() - worker_start) > max_time:
                break
            cmd = [
                sys.executable,
                "-m",
                "randquik",
                f"-l{length}",
                f"-t{workers}",
                *([f"-a{alg}"] if alg else []),
                *iocmd,
            ]

            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=False,
                )
            except KeyboardInterrupt:
                sys.stderr.write(
                    f" Interrupted\n\n>>> {' '.join(cmd)}\n"
                )  # 6 not 8 to account for ^C
                sys.exit(1)
            stderr = proc.stderr.decode(errors="ignore")
            if proc.returncode != 0:
                sys.stderr.write(f"{'ERROR':>8}\n\n>>> {' '.join(cmd)}\n{stderr}")
                sys.exit(1)
            m2 = re.findall(r"([0-9]+\.[0-9]+)\s+GB/s", stderr)
            if m2:
                speeds.append(float(m2[-1]))

        if speeds:
            sorted_speeds = sorted(speeds)
            median = sorted_speeds[len(speeds) // 2]
            sys.stdout.write(f"{median:>8.2f}")
            sys.stdout.flush()
            results.append((workers, median, iocmd))
        else:
            sys.stdout.write(f"{'---':>8}")
            sys.stdout.flush()

    sys.stdout.write("\n")  # newline after row
    sys.stdout.flush()

    # Cleanup bench file
    if bench_file:
        with contextlib.suppress(OSError):
            bench_file.unlink()

    return results


def run_benchmark(args):
    """Run comprehensive benchmark across all I/O modes."""
    # Check if output file already exists
    bench_file = pathlib.Path(args.output or "test.dat")
    if bench_file.exists():
        if not args.output:
            raise ValueError(
                f"File test.dat already exists. Use -o {bench_file} to benchmark over it or choose another name."
            )
        bench_file.unlink()

    try:
        length = "1G" if args.len is None else args.len
        max_threads = args.threads if args.threads is not None else os.cpu_count()

        all_results = {}
        tcounts = sparse_range(max_threads)

        # Print header
        header = f"{'randquik':<20}"
        for w in tcounts:
            header += f"{'-t' + str(w):>8}"
        header += "\n" + "-" * (20 + 8 * len(tcounts)) + "\n"
        sys.stdout.write(header)

        for io_mode in ["dry", "null", "file"]:
            results = bench_mode(tcounts, io_mode, length, alg=args.alg, bench_file=bench_file)
            all_results[io_mode] = results

        sys.stdout.write("-" * (20 + 8 * len(tcounts)) + "\n")

        # Find fastest configuration and RNG speed
        gen_speed = max(r[1] for res in all_results.values() for r in res)
        best_speed, best_threads, best_iocmd = max(
            [(sp, w, iocmd) for w, sp, iocmd in all_results["file"]],
        )
        threads = f" -t{best_threads}" if best_threads != 1 else ""
        sys.stderr.write(
            f"\n>>> Fastest wrote {best_speed:.2f} GB/s, plain RNG {gen_speed:.0f} GB/s\n"
            f"randquik {' '.join(best_iocmd)}{threads}\n"
        )
    finally:
        # Cleanup bench file even if interrupted
        with contextlib.suppress(OSError):
            bench_file.unlink()
