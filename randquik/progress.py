"""Progress display with speed graph at bottom of terminal."""

import math
import os
import sys
import threading
import time

from randquik.stats import format_size, format_time

__all__ = ["ProgressDisplay"]

# Unicode block characters for graph (8 levels per cell)
GRAPH_BLOCKS = " ▁▂▃▄▅▆▇█"

# Maximum height of progress display in terminal rows
MAX_HEIGHT = 10


class ProgressDisplay:
    """Progress display with speed graph at bottom of terminal, updated every 100ms.

    Only active when stderr is a tty. Reads progress from a shared state dict
    with a single 'written' key. All display logic is encapsulated here.

    Uses the bottom portion of the terminal with a scrolling region preserved
    at the top, allowing normal output to scroll above the progress display.

    The graph fills from left to right as progress advances, doubling as both
    a progress bar and a speed-over-time visualization.
    """

    def __init__(
        self,
        total_bytes: int | None,
        start_time: float,
        state: dict,
        infinite: bool | None = None,
        output_name: str | None = None,
        oseek: int = 0,
    ):
        self.total_bytes = total_bytes
        self.start_time = start_time
        self.state = state  # Must have 'written' key
        self.infinite = infinite if infinite is not None else total_bytes is None
        self.output_name = output_name or "<stdout>"
        self.oseek = oseek
        self.active = sys.stderr.isatty()
        self._stop = threading.Event()
        self._thread = None
        self._last_written = 0
        self._last_time = start_time
        # Speed history for graph - fixed size, filled from left as progress advances
        self._graph_width = 80  # Will be updated on first render
        self._speed_history: list[float] = []  # Stores GB/s values, one per column
        self._max_speed: float = 0.01  # Start with small value to avoid div by zero
        # For infinite mode: track time of each speed sample
        self._time_history: list[float] = []
        # X-axis scale smoothing (hysteresis for estimated total time)
        self._smoothed_scale_time: float | None = None
        # Terminal handling
        self._current_scroll_bottom: int | None = None
        self._hidden_cursor = False
        self._first_draw = True

    def start(self):
        if not self.active:
            return
        self._setup_terminal_state()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.active or self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=0.5)
        # Final render so the finished state stays on screen
        if self.active:
            cols, rows, lines, overlay = self._render_frame()
            self._draw_frame(cols, rows, lines, overlay)
        self._restore_terminal_state()

    def _setup_terminal_state(self):
        """Prepare terminal: hide cursor and start using bottom reserved block."""
        sys.stderr.write("\x1b[?25l")  # Hide cursor to reduce flicker
        sys.stderr.flush()
        self._hidden_cursor = True

    def _get_smoothed_speed(self, window_secs: float = 1.0) -> float:
        """Calculate average speed over the last window_secs seconds.

        Returns speed in bytes/sec, averaged from recent samples in _speed_history.
        Falls back to the most recent sample if not enough history.
        """
        if not self._speed_history or not self._time_history:
            return 0.0

        current_time = self._time_history[-1]
        cutoff_time = current_time - window_secs

        # Find samples within the window
        total_speed = 0.0
        count = 0
        for idx in range(len(self._time_history) - 1, -1, -1):
            if self._time_history[idx] < cutoff_time:
                break
            total_speed += self._speed_history[idx]
            count += 1

        if count == 0:
            return self._speed_history[-1] * 1_000_000_000

        # Return average in bytes/sec (speed_history stores GB/s)
        return (total_speed / count) * 1_000_000_000

    def _restore_terminal_state(self):
        """Restore terminal scrolling and cursor after progress is done."""
        # Reset scrolling region to full screen
        sys.stderr.write("\x1b[r")
        self._current_scroll_bottom = None

        # Move cursor to a fresh line under the progress block
        cols, rows = self._get_terminal_size()
        sys.stderr.write(f"\x1b[{rows};1H\n")

        if self._hidden_cursor:
            sys.stderr.write("\x1b[?25h")
            self._hidden_cursor = False
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
                level = math.ceil(normalized - row_bottom)
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
            return f"{filled_str}\x1b[0m\x1b[38;5;235m{unfilled_str}\x1b[0m\x1b[33m"
        return filled_str

    def _build_header(
        self,
        cols: int,
        written: int,
        speed: float,
        elapsed: float,
        eta: float | None = None,
        total_bytes: int | None = None,
    ) -> str:
        """Build the header line with stats, output name, and position.

        Args:
            cols: Terminal width
            written: Bytes written so far
            speed: Current speed in bytes/sec
            elapsed: Elapsed time in seconds
            eta: Estimated time remaining (None for infinite mode)
            total_bytes: Total bytes to write (None for infinite mode)
        """
        spinner = "\u25d0\u25d3\u25d1\u25d2"[int(elapsed * 4) % 4]
        written_gb = written / 1_000_000_000
        speed_gbs = speed / 1_000_000_000

        # Build the fixed stats portion
        if total_bytes is not None:
            # Finite mode: show progress and ETA
            total_gb = total_bytes / 1_000_000_000
            eta_str = format_time(eta) if eta is not None else "--"
            stats = (
                f"\x1b[1;36mRandQuik {spinner}\x1b[0m  "
                f"{written_gb:6.2f}\x1b[2m/\x1b[0m{total_gb:.2f} GB  "
            )
            stats += (
                f"\x1b[2m@\x1b[0m {speed_gbs:5.2f} GB/s  \x1b[2mest.\x1b[0m {eta_str:<8}"
                if written < total_bytes
                else f"\x1b[2m{'done':>27}\x1b[0m"
            )

            # Visible: "RandQuik X  " (14) + "XXXX.XX/XXXX.XX GB  " (20) + "@ XX.XX GB/s  " (15) + "est. XXXXXXXX" (13) = 62
            stats_len = 62
        else:
            # Infinite mode: show written and elapsed
            stats = (
                f"  \x1b[1;36mRandQuik {spinner}\x1b[0m  "
                f"{written_gb:6.2f} GB \x1b[2m\u221e\x1b[0m  "
                f"\x1b[2m@\x1b[0m {speed_gbs:5.2f} GB/s  "
                f"\x1b[2m\u2502\x1b[0m  {format_time(elapsed):>8}"
            )
            # Visible: "  RandQuik X  " (16) + "XXXX.XX GB \u221e  " (14) + "@ XX.XX GB/s  " (15) + "\u2502  XXXXXXXX" (11) = 56
            stats_len = 56

        # Build position suffix if oseek was used
        if self.oseek > 0:
            file_pos = self.oseek + written
            pos_str = format_size(file_pos).replace(" ", "")
            if total_bytes is not None:
                pos_suffix = f" \x1b[2m[\x1b[0m{pos_str}\x1b[2m]\x1b[0m"
                pos_suffix_len = 3 + len(pos_str)  # " []" + size
            else:
                pos_suffix = f" \x1b[2m@\x1b[0m{pos_str}"
                pos_suffix_len = 2 + len(pos_str)  # " @" + size
        else:
            pos_suffix = ""
            pos_suffix_len = 0

        # Calculate available space for filename
        # Format: {stats}  > {name}{pos_suffix}
        available = cols - stats_len - 4 - pos_suffix_len  # 4 for "  > "
        name = self.output_name
        if len(name) > available > 3:
            name = "\u2026" + name[-(available - 1) :]
        elif available <= 3:
            name = ""

        if name:
            return f"{stats}  \x1b[2m>\x1b[0m {name}{pos_suffix}"
        return stats

    def _render_progress_block(
        self, cols: int, rows: int, max_height: int
    ) -> tuple[list[str], tuple[int, int, str] | None]:
        """Render the progress block constrained to max_height lines."""
        if self.infinite:
            return self._render_infinite_block(cols, rows, max_height), None
        return self._render_finite_block(cols, rows, max_height)

    def _render_infinite_block(self, cols: int, rows: int, max_height: int) -> list[str]:
        """Render progress block for infinite mode (no known total)."""
        written = self.state.get("written", 0)
        now = time.perf_counter()
        elapsed = now - self.start_time

        # Calculate graph width (leave room for Y-axis labels)
        graph_width = max(10, cols - 8)
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

        # Use smoothed speed for header display
        display_speed = self._get_smoothed_speed()

        # Build output
        lines: list[str] = []
        header = self._build_header(cols, written, display_speed, elapsed)
        lines.append(header)

        # Calculate graph dimensions based on remaining height
        # Layout: [header][GB/s label][graph rows][time axis]
        remaining_after_label = max_height - len(lines) - 2

        if remaining_after_label < 1:
            # Terminal is too short; fall back to header-only view
            return lines

        graph_rows = max(1, remaining_after_label)

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

        # Use MB/s scale if max speed < 1 GB/s
        use_mb = scale_max < 1
        unit_label = "MB/s" if use_mb else "GB/s"
        lines.append(f" \x1b[36m{unit_label}\x1b[0m")

        # Compute nice Y-axis tick values and map each to its best row
        nice_ticks = self._nice_y_ticks(scale_max, graph_rows)
        row_labels = self._assign_ticks_to_rows(nice_ticks, scale_max, graph_rows, use_mb)

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

            # Y-axis label from pre-computed mapping
            label = row_labels.get(row, "    ")
            lines.append(f" \x1b[36m{label}\x1b[0m \x1b[33m{graph_line}\x1b[0m")

        # Time axis
        time_axis = self._build_infinite_time_axis(graph_width, scale_time)
        lines.append(f"      {''.join(time_axis)}")

        return lines

    def _nice_scale(self, max_speed: float) -> float:
        """Round up to next nice number for scale."""
        if max_speed <= 0.01:
            return 0.01
        log_val = math.log10(max_speed)
        power = math.floor(log_val)
        mantissa = max_speed / (10**power)
        nice_mantissa = math.ceil(mantissa)
        if nice_mantissa > 9:
            nice_mantissa = 1
            power += 1
        return nice_mantissa * (10**power)

    def _format_label(self, val: float, use_mb: bool = False) -> str:
        """Format Y-axis label.

        Args:
            val: Value in GB/s (will be converted to MB/s if use_mb is True)
            use_mb: If True, multiply by 1000 and format as MB/s values
        """
        if use_mb:
            val = val * 1000  # Convert GB/s to MB/s
        if val == 0:
            return "0"
        elif val >= 1:
            return f"{val:.0f}"
        else:
            return f"{val:.1f}"

    def _nice_y_ticks(self, scale_max: float, graph_rows: int = 10) -> list[float]:
        """Return nice Y-axis tick values from 0 to scale_max.

        Chooses a nice interval (1, 2, 5 × 10^N) that gives labels with
        sufficient spacing (at least 3 rows between labels).
        """
        if scale_max <= 0:
            return [0]

        # We want at least 5 empty rows between labels for readability
        min_row_spacing = 5
        max_ticks = max(2, graph_rows // min_row_spacing)

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

    def _assign_ticks_to_rows(
        self, ticks: list[float], scale_max: float, graph_rows: int, use_mb: bool = False
    ) -> dict[int, str]:
        """Assign each tick to the row closest to its value.

        Returns a dict mapping row index to formatted label string.
        Each tick is assigned to exactly one row.

        Args:
            ticks: List of tick values in GB/s
            scale_max: Maximum scale value in GB/s
            graph_rows: Number of rows in the graph
            use_mb: If True, format labels as MB/s instead of GB/s
        """
        row_labels: dict[int, str] = {}
        if graph_rows <= 1 or scale_max <= 0:
            return {0: f"{self._format_label(ticks[0] if ticks else 0, use_mb):>4}"}

        for tick in ticks:
            # Calculate which row this tick value corresponds to
            # Row 0 is top (scale_max), row graph_rows-1 is bottom (0)
            exact_row = (1 - tick / scale_max) * (graph_rows - 1)
            best_row = round(exact_row)
            best_row = max(0, min(graph_rows - 1, best_row))

            # Only assign if row is not already taken (first tick wins)
            if best_row not in row_labels:
                row_labels[best_row] = f"{self._format_label(tick, use_mb):>4}"

        return row_labels

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
            elif secs < 120:
                return f"{int(secs)}s"
            elif secs < 3600:
                m = int(secs // 60)
                s = int(secs % 60)
                if s == 0:
                    return f"{m}m"
                return f"{m}m{s}s"
            else:
                h = int(secs // 3600)
                m = int((secs % 3600) // 60)
                if m == 0:
                    return f"{h}h"
                return f"{h}h{m}m"

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

    def _render_finite_block(
        self, cols: int, rows: int, max_height: int
    ) -> tuple[list[str], tuple[int, int, str] | None]:
        """Render the progress block for finite progress."""
        written = self.state.get("written", 0)
        now = time.perf_counter()
        elapsed = now - self.start_time

        # Calculate graph width (leave room for Y-axis labels)
        graph_width = max(10, cols - 8)
        self._graph_width = graph_width

        # Calculate speeds
        overall_speed = written / elapsed if elapsed > 0 else 0
        dt = now - self._last_time
        instant_speed = (written - self._last_written) / dt if dt > 0 else 0
        self._last_written = written
        self._last_time = now

        # Collect time-based speed samples (like infinite mode)
        speed_gbs = instant_speed / 1_000_000_000
        self._speed_history.append(speed_gbs)
        self._time_history.append(elapsed)

        # Use smoothed speed for header display and ETA
        display_speed = self._get_smoothed_speed()

        # ETA and total estimated time
        remaining = self.total_bytes - written
        # ETA based on smoothed speed for stability
        eta = remaining / display_speed if display_speed > 0 else -1
        # Graph X-axis scaling based on overall average speed for stability
        avg_eta = remaining / overall_speed if overall_speed > 0 else -1
        estimated_total_time = elapsed + avg_eta if avg_eta > 0 else elapsed

        # Apply hysteresis to scale_time to prevent jumping
        # Only update if change is significant (>20%) or if new estimate is larger
        raw_scale_time = max(estimated_total_time, 1.0)
        if self._smoothed_scale_time is None:
            self._smoothed_scale_time = raw_scale_time
        else:
            # Always grow immediately, shrink only gradually
            if raw_scale_time > self._smoothed_scale_time:
                self._smoothed_scale_time = raw_scale_time
            else:
                # Shrink slowly: blend 90% old, 10% new
                self._smoothed_scale_time = 0.9 * self._smoothed_scale_time + 0.1 * raw_scale_time
        scale_time = self._smoothed_scale_time

        # Progress percentage (for display)
        pct = min(100, written * 100 / self.total_bytes) if self.total_bytes > 0 else 0

        # Update max speed
        if speed_gbs > self._max_speed:
            self._max_speed = speed_gbs
        scale_max = self._nice_scale(self._max_speed)

        # Build output
        lines: list[str] = []
        header = self._build_header(
            cols, written, display_speed, elapsed, eta=eta, total_bytes=self.total_bytes
        )
        lines.append(header)

        # Calculate graph dimensions based on remaining height
        # Layout: [header][GB/s label][graph rows][time axis]
        remaining_after_label = max_height - len(lines) - 2

        if remaining_after_label < 1:
            # Terminal is too short; fall back to a compact header-only view
            return lines, None

        graph_rows = max(1, remaining_after_label)

        # Downsample speed history for display - average samples within each column's time range
        # Graph fills based on elapsed / scale_time (smoothed)
        col_width_time = scale_time / (graph_width - 1) if graph_width > 1 else scale_time

        # Calculate how many columns should be filled based on elapsed time
        if scale_time > 0:
            time_pct = min(100, elapsed * 100 / scale_time)
        else:
            time_pct = 100
        target_cols = min(graph_width, int(graph_width * time_pct / 100) + 1) if time_pct > 0 else 0

        display_values = []
        for col in range(target_cols):
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

        # Render graph rows with Y-axis
        avg_speed_gbs = overall_speed / 1_000_000_000

        # Use MB/s scale if max speed < 1 GB/s
        use_mb = scale_max < 1
        unit_label = "MB/s" if use_mb else "GB/s"
        lines.append(f" \x1b[36m{unit_label}\x1b[0m")

        # Compute nice Y-axis tick values and map each to its best row
        nice_ticks = self._nice_y_ticks(scale_max, graph_rows)
        row_labels = self._assign_ticks_to_rows(nice_ticks, scale_max, graph_rows, use_mb)

        for row in range(graph_rows):
            graph_line = self._render_graph_row(
                display_values,
                scale_max,
                row,
                graph_rows,
                graph_width,
                avg_speed_gbs,
            )
            graph_line = graph_line.ljust(graph_width)
            # Y-axis label from pre-computed mapping
            label = row_labels.get(row, "    ")
            lines.append(f" \x1b[36m{label}\x1b[0m \x1b[33m{graph_line}\x1b[0m")

        # Time labels on X-axis with nice intervals
        time_axis = self._build_time_axis(graph_width, scale_time)
        lines.append(f"      {''.join(time_axis)}")

        # Position percentage at top of bar at current progress point
        # Find the height of the bar at current progress (last value in display_values)
        current_speed_gbs = display_values[-1] if display_values else 0
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

        # Overlay position inside the progress block
        progress_col = int(pct / 100 * (graph_width - 1)) + 7
        pct_label = f"{int(pct)}%"
        pct_col = max(7, min(cols, progress_col - len(pct_label) // 2))
        first_graph_row = len(lines) - (graph_rows + 2)
        pct_row_offset = first_graph_row + bar_top_row
        pct_position = (pct_row_offset, pct_col, f"\x1b[1;37m{pct_label}\x1b[0m")

        return lines, pct_position

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
            if secs == 0:
                return "0s"
            elif secs < 120:
                return f"{int(secs)}s"
            elif secs < 3600:
                m = int(secs // 60)
                s = int(secs % 60)
                if s == 0:
                    return f"{m}m"
                return f"{m}m{s}s"
            else:
                h = int(secs // 3600)
                m = int((secs % 3600) // 60)
                if m == 0:
                    return f"{h}h"
                return f"{h}h{m}m"

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

    def _render_frame(self) -> tuple[int, int, list[str], tuple[int, int, str] | None]:
        cols, rows = self._get_terminal_size()
        max_height = min(MAX_HEIGHT, rows) if rows > 0 else MAX_HEIGHT
        lines, overlay = self._render_progress_block(cols, rows, max_height)
        # Guard against empty renders
        if not lines:
            lines = [""]
        return cols, rows, lines, overlay

    def _draw_frame(
        self, cols: int, rows: int, lines: list[str], overlay: tuple[int, int, str] | None
    ):
        """Draw the progress block at the bottom of the terminal."""
        height = min(len(lines), max(1, rows))
        progress_top = max(1, rows - height + 1)

        # Build entire frame as a single string
        buf: list[str] = []

        # On first draw, scroll terminal up to make room for progress block
        if self._first_draw:
            self._first_draw = False
            buf.append("\n" * height)

        # Update scrolling region so other output scrolls above the progress block
        top = 1
        bottom = max(1, rows - height)
        if self._current_scroll_bottom != bottom:
            buf.append(f"\x1b[{top};{bottom}r")
            self._current_scroll_bottom = bottom

        # Paint each progress line
        for idx in range(height):
            row = progress_top + idx
            line = lines[idx]
            buf.append(f"\x1b[{row};1H\x1b[2K{line}")

        # Overlay (e.g., percent marker)
        if overlay:
            row_offset, col, text = overlay
            abs_row = progress_top + row_offset
            abs_col = max(1, min(cols, col))
            buf.append(f"\x1b[{abs_row};{abs_col}H{text}")

        # Place cursor back at the bottom of the scrolling region
        anchor_row = max(1, progress_top - 1)
        buf.append(f"\x1b[{anchor_row};1H")

        # Single atomic write
        sys.stderr.write("".join(buf))
        sys.stderr.flush()

    def _run(self):
        """Background thread: update display every 100ms."""
        while not self._stop.wait(0.1):
            cols, rows, lines, overlay = self._render_frame()
            self._draw_frame(cols, rows, lines, overlay)
