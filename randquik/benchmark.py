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
    print(f"{' '.join(iocmd)[:20]:<20}", end="", flush=True)

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
                print(" Interrupted\n\n", end="", flush=True)  # 6 not 8 to account for ^C
                print(f">>> {' '.join(cmd)}", file=sys.stderr)
                sys.exit(1)
            stderr = proc.stderr.decode(errors="ignore")
            if proc.returncode != 0:
                print(f"{'ERROR':>8}\n\n", end="", flush=True)
                print(f">>> {' '.join(cmd)}\n{stderr}", file=sys.stderr)
                sys.exit(1)
            m2 = re.findall(r"([0-9]+\.[0-9]+)\s+GB/s", stderr)
            if m2:
                speeds.append(float(m2[-1]))

        if speeds:
            sorted_speeds = sorted(speeds)
            median = sorted_speeds[len(speeds) // 2]
            print(f"{median:>8.2f}", end="", flush=True)
            results.append((workers, median, iocmd))
        else:
            print(f"{'---':>8}", end="", flush=True)

    print()  # newline after row

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

    length = args.len or "1G"
    max_threads = args.threads if args.threads is not None else os.cpu_count()

    all_results = {}
    tcounts = sparse_range(max_threads)

    # Print header row
    print(f"{'randquik':<20}", end="")
    for w in tcounts:
        print(f"{'-t' + str(w):>8}", end="")
    print()
    print("-" * (20 + 8 * len(tcounts)))

    for io_mode in ["dry", "null", "file"]:
        results = bench_mode(tcounts, io_mode, length, alg=args.alg, bench_file=bench_file)
        all_results[io_mode] = results

    print("-" * (20 + 8 * len(tcounts)))

    # Find fastest configuration and RNG speed
    gen_speed = max(r[1] for res in all_results.values() for r in res)
    best_speed, best_threads, best_iocmd = max(
        [(sp, w, iocmd) for w, sp, iocmd in all_results["file"]],
    )
    threads = f" -t{best_threads}" if best_threads != 1 else ""
    print(
        f"\n>>> Fastest wrote {best_speed:.2f} GB/s, plain RNG {gen_speed:.0f} GB/s\n"
        f"randquik {' '.join(best_iocmd)}{threads}\n"
    )
