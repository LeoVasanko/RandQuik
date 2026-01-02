"""Full-screen progress display with speed graph."""

import math
import os
import sys
import threading
import time

from randquik.utils import format_time

__all__ = ["ProgressDisplay"]

# Unicode block characters for graph (8 levels per cell)
GRAPH_BLOCKS = " ▁▂▃▄▅▆▇█"


class ProgressDisplay:
    """Full-screen progress display with speed graph, updated every 100ms.

    Only active when stderr is a tty. Reads progress from a shared state dict
    with a single 'written' key. All display logic is encapsulated here.

    The graph fills from left to right as progress advances, doubling as both
    a progress bar and a speed-over-time visualization.
    """

    def __init__(
        self,
        total_bytes: int | None,
        start_time: float,
        state: dict,
        infinite: bool | None = None,
        seed: str | None = None,
    ):
        self.total_bytes = total_bytes
        self.start_time = start_time
        self.state = state  # Must have 'written' key
        self.infinite = infinite if infinite is not None else total_bytes is None
        self.seed = seed
        self.active = sys.stderr.isatty()
        self._stop = threading.Event()
        self._thread = None
        self._last_written = 0
        self._last_time = start_time
        # Speed history for graph - fixed size, filled from left as progress advances
        self._graph_width = 80  # Will be updated on first render
        self._speed_history: list[float] = []  # Stores GB/s values, one per column
        self._max_speed: float = 0.1  # Start with small value to avoid div by zero
        # For infinite mode: track time of each speed sample
        self._time_history: list[float] = []

    def start(self):
        if not self.active:
            return
        self._save_terminal_state()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.active or self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=0.5)
        self._restore_terminal_state()

    def _save_terminal_state(self):
        """Save terminal state and enter alternate screen buffer."""
        sys.stderr.write("\x1b[?1049h")  # Enter alternate screen buffer
        sys.stderr.write("\x1b[?25l")  # Hide cursor
        sys.stderr.flush()

    def _restore_terminal_state(self):
        """Restore terminal state and exit alternate screen buffer."""
        sys.stderr.write("\x1b[?25h")  # Show cursor
        sys.stderr.write("\x1b[?1049l")  # Exit alternate screen buffer
        sys.stderr.flush()

    def _get_terminal_size(self) -> tuple[int, int]:
        """Return (columns, rows)."""
        try:
            size = os.get_terminal_size(sys.stderr.fileno())
            return size.columns, size.lines
        except (OSError, ValueError):
            return 80, 24

    def _render_graph_row(
        self,
        values: list[float],
        max_val: float,
        row: int,
        total_rows: int,
        width: int,
        avg_speed: float = 0,
    ) -> str:
        """Render one row of the graph using Unicode blocks.

        Row 0 is top, total_rows-1 is bottom. Each cell can show 8 levels.
        Values list may be shorter than width (unfilled area shown as dim bar at avg_speed).
        """
        filled_chars = []
        unfilled_chars = []
        filled_cols = len(values)
        # Calculate the row threshold for average speed
        avg_normalized = (avg_speed / max_val) * total_rows * 8 if max_val > 0 else 0
        row_bottom = (total_rows - row - 1) * 8
        row_top = row_bottom + 8

        # Build filled portion
        for i in range(filled_cols):
            v = values[i]
            # Normalize value to 0..total_rows*8 range
            normalized = (v / max_val) * total_rows * 8 if max_val > 0 else 0
            if normalized <= row_bottom:
                filled_chars.append(" ")
            elif normalized >= row_top:
                filled_chars.append("█")
            else:
                level = int(normalized - row_bottom)
                filled_chars.append(GRAPH_BLOCKS[min(level, 8)])

        # Build unfilled portion (dim grey at avg_speed level)
        unfilled_width = width - filled_cols
        if unfilled_width > 0:
            if avg_normalized <= row_bottom:
                unfilled_char = " "
            elif avg_normalized >= row_top:
                unfilled_char = "█"
            else:
                level = int(avg_normalized - row_bottom)
                unfilled_char = GRAPH_BLOCKS[min(level, 8)]
            unfilled_chars = [unfilled_char] * unfilled_width

        # Combine with color codes only at transitions
        filled_str = "".join(filled_chars)
        unfilled_str = "".join(unfilled_chars)
        if unfilled_str:
            return f"{filled_str}\x1b[0m\x1b[38;5;234m{unfilled_str}\x1b[0m\x1b[33m"
        return filled_str

    def _render_full_screen(self) -> str:
        """Render the full screen display."""
        if self.infinite:
            return self._render_infinite_screen()
        return self._render_progress_screen()

    def _render_infinite_screen(self) -> str:
        """Render screen for infinite mode (no known total)."""
        cols, rows = self._get_terminal_size()
        written = self.state.get("written", 0)
        now = time.perf_counter()
        elapsed = now - self.start_time

        # Calculate graph width (leave room for Y-axis labels)
        graph_width = cols - 8
        self._graph_width = graph_width

        # Calculate speeds
        overall_speed = written / elapsed if elapsed > 0 else 0
        dt = now - self._last_time
        instant_speed = (written - self._last_written) / dt if dt > 0 else 0
        self._last_written = written
        self._last_time = now

        # Update speed history
        speed_gbs = instant_speed / 1_000_000_000
        self._speed_history.append(speed_gbs)
        self._time_history.append(elapsed)

        # Update max speed
        if speed_gbs > self._max_speed:
            self._max_speed = speed_gbs
        scale_max = self._nice_scale(self._max_speed)

        # Build output
        lines = []
        lines.append("\x1b[2J\x1b[H")

        # Compact header with stats
        spinner = "◐◓◑◒"[int(elapsed * 4) % 4]
        written_gb = written / 1_000_000_000
        current_speed = instant_speed / 1_000_000_000
        seed_hint = f"  \x1b[2m-s {self.seed}\x1b[0m" if self.seed else ""
        header = (
            f"  \x1b[1;36mRandQuik {spinner}\x1b[0m  "
            f"\x1b[2m│\x1b[0m  {written_gb:6.2f}/∞ GB  "
            f"\x1b[2m@\x1b[0m {current_speed:5.2f} GB/s  "
            f"\x1b[2m│\x1b[0m  {format_time(elapsed):>8}{seed_hint}"
        )
        lines.append(header)
        lines.append("")

        # Calculate graph dimensions (footer_lines includes GB/s label, time axis, and footer)
        header_lines = len(lines)
        footer_lines = 4
        graph_rows = max(3, rows - header_lines - footer_lines)

        # Downsample speed history for display - average samples within each column's time range
        min_scale_time = 10.0
        scale_time = max(elapsed, min_scale_time)
        col_width_time = scale_time / (graph_width - 1) if graph_width > 1 else scale_time

        display_values = []
        for col in range(graph_width):
            col_time = col / (graph_width - 1) * scale_time if graph_width > 1 else 0
            if col_time > elapsed:
                break
            # Find all samples within this column's time range
            col_start = col_time - col_width_time / 2
            col_end = col_time + col_width_time / 2
            samples = [
                self._speed_history[idx]
                for idx, t in enumerate(self._time_history)
                if col_start <= t <= col_end
            ]
            if samples:
                display_values.append(sum(samples) / len(samples))
            elif self._speed_history:
                # Fallback to closest if no samples in range
                best_idx = 0
                best_diff = float("inf")
                for idx, t in enumerate(self._time_history):
                    diff = abs(t - col_time)
                    if diff < best_diff:
                        best_diff = diff
                        best_idx = idx
                display_values.append(self._speed_history[best_idx])

        avg_speed_gbs = overall_speed / 1_000_000_000

        # Add GB/s label above the graph
        lines.append(" \x1b[36mGB/s\x1b[0m")

        # Compute nice Y-axis tick values
        nice_ticks = set(self._nice_y_ticks(scale_max))
        labeled_values = set()  # Track which tick values have been labeled
        tolerance = scale_max / (graph_rows - 1) / 2 if graph_rows > 1 else 0.1

        for row in range(graph_rows):
            graph_line = self._render_graph_row(
                display_values,
                scale_max,
                row,
                graph_rows,
                len(display_values),
                avg_speed_gbs,
            )
            graph_line = graph_line.ljust(graph_width)

            # Y-axis labels - only label nice tick values
            row_value = (
                scale_max * (graph_rows - 1 - row) / (graph_rows - 1) if graph_rows > 1 else 0
            )
            label = "    "
            for tick in nice_ticks:
                if abs(row_value - tick) < tolerance and tick not in labeled_values:
                    label = f"{self._format_label(tick):>4}"
                    labeled_values.add(tick)
                    break
            lines.append(f" \x1b[36m{label}\x1b[0m \x1b[33m{graph_line}\x1b[0m")

        # Time axis
        time_axis = self._build_infinite_time_axis(graph_width, scale_time)
        lines.append(f"      {''.join(time_axis)}")

        # Footer
        lines.append(f"\x1b[2m{'[Ctrl+C to stop]':^{cols}}\x1b[0m")

        return "\n".join(lines)

    def _nice_scale(self, max_speed: float) -> float:
        """Round up to next nice number for scale."""
        if max_speed <= 0.1:
            return 0.1
        log_val = math.log10(max_speed)
        power = math.floor(log_val)
        mantissa = max_speed / (10**power)
        nice_mantissa = math.ceil(mantissa)
        if nice_mantissa > 9:
            nice_mantissa = 1
            power += 1
        return nice_mantissa * (10**power)

    def _format_label(self, val: float) -> str:
        """Format Y-axis label."""
        if val == 0:
            return "0"
        elif val >= 1:
            return f"{val:.0f}"
        else:
            return f"{val:.1f}"

    def _nice_y_ticks(self, scale_max: float, max_ticks: int = 5) -> list[float]:
        """Return nice Y-axis tick values from 0 to scale_max.

        Chooses a nice interval (1, 2, 5 × 10^N) that gives roughly max_ticks labels.
        """
        if scale_max <= 0:
            return [0]

        # Nice intervals: 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, ...
        nice_bases = [1, 2, 5]
        best_interval = scale_max
        for exp in range(-1, 10):
            for base in nice_bases:
                interval = base * (10**exp)
                num_ticks = scale_max / interval
                if 2 <= num_ticks <= max_ticks:
                    best_interval = interval
                    break
            else:
                continue
            break

        # Generate ticks from 0 to scale_max at best_interval
        ticks = []
        val = 0.0
        while val <= scale_max + 1e-9:
            ticks.append(val)
            val += best_interval
        return ticks

    def _build_infinite_time_axis(self, graph_width: int, scale_time: float) -> list[str]:
        """Build time axis for infinite mode with nice interval labels.

        Shows from 0 to scale_time with nice interval markers.
        """
        time_axis = [" "] * graph_width

        # Nice time intervals
        nice_intervals = [
            1,
            2,
            5,
            10,
            15,
            30,
            60,
            120,
            300,
            600,
            900,
            1800,
            3600,
            7200,
            18000,
            36000,
        ]

        def format_time_short(secs):
            """Format time for axis label."""
            if secs == 0:
                return "0"
            elif secs < 60:
                return f"{int(secs)}s"
            elif secs < 3600:
                m = int(secs // 60)
                return f"{m}m"
            else:
                h = int(secs // 3600)
                return f"{h}h"

        # Find a nice interval that gives us ~4-8 labels
        interval = nice_intervals[-1]
        for ni in nice_intervals:
            if scale_time / ni <= 8:
                interval = ni
                break

        # Place labels at nice intervals starting from 0
        t = 0
        while t <= scale_time:
            col = int(t / scale_time * (graph_width - 1)) if scale_time > 0 else 0
            if 0 <= col < graph_width:
                label = format_time_short(t)
                label_start = max(0, col - len(label) // 2)
                label_end = min(graph_width, label_start + len(label))
                if all(c == " " for c in time_axis[label_start:label_end]):
                    for i, ch in enumerate(label):
                        if label_start + i < graph_width:
                            time_axis[label_start + i] = ch
            t += interval

        return time_axis

    def _render_progress_screen(self) -> str:
        """Render the full screen display for finite progress."""
        cols, rows = self._get_terminal_size()
        written = self.state.get("written", 0)
        now = time.perf_counter()
        elapsed = now - self.start_time

        # Calculate graph width (leave room for Y-axis labels)
        graph_width = cols - 8
        self._graph_width = graph_width

        # Calculate speeds
        overall_speed = written / elapsed if elapsed > 0 else 0
        dt = now - self._last_time
        instant_speed = (written - self._last_written) / dt if dt > 0 else 0
        self._last_written = written
        self._last_time = now

        # ETA and total estimated time
        remaining = self.total_bytes - written
        # ETA based on current instant speed for responsiveness
        eta = remaining / instant_speed if instant_speed > 0 else -1
        # Graph X-axis scaling based on average speed for stability
        avg_eta = remaining / overall_speed if overall_speed > 0 else -1
        estimated_total_time = elapsed + avg_eta if avg_eta > 0 else elapsed

        # Progress percentage (for display)
        pct = min(100, written * 100 / self.total_bytes) if self.total_bytes > 0 else 0

        # Time-based progress: columns represent time, not percentage
        # Graph fills based on elapsed / estimated_total_time
        # Use ceiling so column appears when we've started it, not when complete
        if estimated_total_time > 0:
            time_pct = min(100, elapsed * 100 / estimated_total_time)
        else:
            time_pct = 100
        target_cols = min(graph_width, int(graph_width * time_pct / 100) + 1) if time_pct > 0 else 0

        # Update speed history - add new sample if we've advanced to a new column
        speed_gbs = instant_speed / 1_000_000_000
        if len(self._speed_history) < target_cols:
            # Fill in any skipped columns with the current speed
            while len(self._speed_history) < target_cols:
                self._speed_history.append(speed_gbs)
        elif len(self._speed_history) > 0 and target_cols > 0:
            # Update the current column with latest speed (smoothing)
            self._speed_history[-1] = (self._speed_history[-1] + speed_gbs) / 2

        # Update max speed - use "nice" scale values (1, 2, 3, ..., 9 × 10^N), minimum 0.1 GB/s
        if speed_gbs > self._max_speed:
            self._max_speed = speed_gbs
        # Round up to next "nice" number: 0.1, 0.2, ..., 0.9, 1, 2, ..., 9, 10, 20, ...
        if self._max_speed <= 0.1:
            scale_max = 0.1
        else:
            # Find the power of 10 just below max_speed
            log_val = math.log10(self._max_speed)
            power = math.floor(log_val)
            # Get the leading digit and round up
            mantissa = self._max_speed / (10**power)
            nice_mantissa = math.ceil(mantissa)
            if nice_mantissa > 9:
                nice_mantissa = 1
                power += 1
            scale_max = nice_mantissa * (10**power)

        # Build output
        lines = []
        lines.append("\x1b[2J\x1b[H")

        # Compact header with stats
        spinner = "◐◓◑◒"[int(elapsed * 4) % 4]
        current_speed = instant_speed / 1_000_000_000
        written_gb = written / 1_000_000_000
        total_gb = self.total_bytes / 1_000_000_000
        seed_hint = f"  \x1b[2m-s {self.seed}\x1b[0m" if self.seed else ""
        header = (
            f"  \x1b[1;36mRandQuik {spinner}\x1b[0m  "
            f"\x1b[2m│\x1b[0m  {written_gb:6.2f}\x1b[2m/\x1b[0m{total_gb:.2f} GB  "
            f"\x1b[2m@\x1b[0m {current_speed:5.2f} GB/s  "
            f"ETA {format_time(eta):>8}{seed_hint}"
        )
        lines.append(header)
        lines.append("")

        # Calculate graph dimensions (footer_lines includes GB/s label, time axis, and footer)
        header_lines = len(lines)
        footer_lines = 4
        graph_rows = max(3, rows - header_lines - footer_lines)

        # Render graph rows with Y-axis
        avg_speed_gbs = overall_speed / 1_000_000_000

        # Add GB/s label above the graph
        lines.append(" \x1b[36mGB/s\x1b[0m")

        # Compute nice Y-axis tick values
        nice_ticks = set(self._nice_y_ticks(scale_max))
        labeled_values = set()  # Track which tick values have been labeled
        tolerance = scale_max / (graph_rows - 1) / 2 if graph_rows > 1 else 0.1

        for row in range(graph_rows):
            graph_line = self._render_graph_row(
                self._speed_history,
                scale_max,
                row,
                graph_rows,
                graph_width,
                avg_speed_gbs,
            )
            # Y-axis labels - only label nice tick values
            row_value = (
                scale_max * (graph_rows - 1 - row) / (graph_rows - 1) if graph_rows > 1 else 0
            )
            label = "    "
            for tick in nice_ticks:
                if abs(row_value - tick) < tolerance and tick not in labeled_values:
                    label = f"{self._format_label(tick):>4}"
                    labeled_values.add(tick)
                    break
            lines.append(f" \x1b[36m{label}\x1b[0m \x1b[33m{graph_line}\x1b[0m")

        # Time labels on X-axis with nice intervals
        time_axis = self._build_time_axis(graph_width, estimated_total_time)
        lines.append(f"      {''.join(time_axis)}")

        # Footer
        lines.append(f"\x1b[2m{'[Ctrl+C to abort]':^{cols}}\x1b[0m")

        # Position percentage at top of bar at current progress point
        # Find the height of the bar at current progress (last value in speed_history)
        current_speed_gbs = self._speed_history[-1] if self._speed_history else 0
        # Normalize to find which row the top of the bar is at
        # Bar fills from bottom up; row 0 is top, graph_rows-1 is bottom
        if scale_max > 0 and current_speed_gbs > 0:
            # How many rows from bottom does the bar fill?
            bar_height_fraction = current_speed_gbs / scale_max
            # The top of the bar is at this row (0 = top, graph_rows-1 = bottom)
            bar_top_row = int(graph_rows * (1 - bar_height_fraction))
            bar_top_row = max(0, min(graph_rows - 1, bar_top_row))
        else:
            bar_top_row = graph_rows - 1  # At bottom if no speed

        # Graph starts at row 4 (1-indexed: header=1, empty=2, GB/s=3, first graph row=4)
        # Column offset is 6 (space + 4 char Y-label + space)
        progress_col = int(pct / 100 * (graph_width - 1)) + 7  # +7 for Y-axis offset (1-indexed)
        pct_label = f"{int(pct)}%"
        # Center the label on the progress point
        pct_col = max(7, progress_col - len(pct_label) // 2)
        # Calculate screen row (1-indexed for ANSI)
        pct_row = 4 + bar_top_row
        pct_position = f"\x1b[{pct_row};{pct_col}H\x1b[1;37m{pct_label}\x1b[0m"

        return "\n".join(lines) + pct_position

    def _build_time_axis(self, graph_width: int, estimated_total_time: float) -> list[str]:
        """Build time axis with nice interval labels."""

        def nice_time_interval(total_secs):
            """Return a nice interval for time axis labels."""
            nice_intervals = [
                1,
                2,
                5,
                10,
                15,
                30,
                60,
                120,
                300,
                600,
                900,
                1800,
                3600,
                7200,
                18000,
                36000,
            ]
            for interval in nice_intervals:
                if total_secs / interval <= 8:
                    return interval
            return 36000

        def format_time_short(secs):
            """Format time for axis label."""
            if secs < 60:
                return f"{int(secs)}s"
            elif secs < 3600:
                return f"{int(secs // 60)}m"
            else:
                return f"{int(secs // 3600)}h"

        time_axis = [" "] * graph_width
        if estimated_total_time > 0:
            interval = nice_time_interval(estimated_total_time)
            t = 0
            while t <= estimated_total_time:
                col = (
                    int(t / estimated_total_time * (graph_width - 1))
                    if estimated_total_time > 0
                    else 0
                )
                if col < graph_width:
                    label = format_time_short(t)
                    start = max(0, col - len(label) // 2)
                    end = min(graph_width, start + len(label))
                    if all(c == " " for c in time_axis[start:end]):
                        for i, ch in enumerate(label):
                            if start + i < graph_width:
                                time_axis[start + i] = ch
                t += interval
        else:
            time_axis = list(f"{'0s':<{graph_width}}")

        return time_axis

    def _run(self):
        """Background thread: update display every 100ms."""
        while not self._stop.wait(0.1):
            screen = self._render_full_screen()
            sys.stderr.write(screen)
            sys.stderr.flush()
