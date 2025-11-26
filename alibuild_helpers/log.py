import logging
import sys
import re
import time
import datetime
import signal
import os
from collections import deque
from typing import Optional, List

def dieOnError(err, msg) -> None:
  if err:
    error("%s", msg)
    sys.exit(1)

class LogFormatter(logging.Formatter):
  def __init__(self, fmtstr) -> None:
    self.fmtstr = fmtstr
    self.COLOR_RESET = "\033[m" if sys.stdout.isatty() else ""
    self.LEVEL_COLORS = { logging.WARNING:  "\033[4;33m",
                          logging.ERROR:    "\033[4;31m",
                          logging.CRITICAL: "\033[1;37;41m",
                          logging.SUCCESS:  "\033[1;32m" } if sys.stdout.isatty() else {}
  def format(self, record):
    record.msg = record.msg % record.args
    if record.levelno == logging.BANNER and sys.stdout.isatty():
      lines = record.msg.split("\n")
      return "\n\033[1;34m==>\033[m \033[1m%s\033[m" % lines[0] + \
             "".join("\n    \033[1m%s\033[m" % x for x in lines[1:])
    elif record.levelno == logging.INFO or record.levelno == logging.BANNER:
      return record.msg
    return "\n".join(self.fmtstr % {
      "asctime": datetime.datetime.now().strftime("%Y-%m-%d@%H:%M:%S"),
      "levelname": (self.LEVEL_COLORS.get(record.levelno, self.COLOR_RESET) +
                    record.levelname + self.COLOR_RESET),
      "message": x,
    } for x in record.msg.split("\n"))


def log_current_package(package, main_package, specs, devel_prefix) -> None:
  """Show PACKAGE as the one currently being processed in future log messages."""
  if logger_handler.level > logging.DEBUG:
    return
  if devel_prefix is not None:
    short_version = devel_prefix
  else:
    short_version = specs[main_package]["commit_hash"]
    if short_version != specs[main_package]["tag"]:
      short_version = short_version[:8]
  logger_handler.setFormatter(LogFormatter(
    "%(asctime)s:%(levelname)s:{}:{}: %(message)s"
    .format(main_package, short_version)
    if package is None else
    "%(asctime)s:%(levelname)s:{}:{}:{}: %(message)s"
    .format(main_package, package, short_version)
  ))


class ProgressPrint:
  def __init__(self, build_progress=None, begin_msg=""):
    self.build_progress = build_progress
    self.begin_msg = begin_msg
    self.started = False

  def __call__(self, txt: str, *args):
    """Log a line of output."""
    if args:
      txt = txt % args

    if self.build_progress:
      if not self.started:
        self.started = True
        # Parse package name from begin_msg if present
        # Format: "Compiling PACKAGE@VERSION" or "Unpacking PACKAGE@VERSION"
        if self.begin_msg:
          match = re.match(r'(?:Compiling|Unpacking)\s+([^@]+)(?:@(.+))?',
                         self.begin_msg)
          if match:
            package = match.group(1)
            version = match.group(2) or ""
            self.build_progress.start_package(package, version)

      self.build_progress.log(txt)
    else:
      # No TTY: just print debug output
      debug(txt)

  def erase(self):
    """No-op for compatibility."""
    pass

  def end(self, msg: str = "", error: bool = False):
    """Finish the current operation."""
    if self.build_progress and self.started:
      self.build_progress.finish_package(failed=error)
    elif msg:
      # No TTY: print the final message
      debug(msg)


# Add loglevel BANNER (same as INFO but with more emphasis on ttys)
logging.BANNER = 25
logging.addLevelName(logging.BANNER, "BANNER")
def log_banner(self, message, *args, **kws):
  if self.isEnabledFor(logging.BANNER):
    self._log(logging.BANNER, message, args, **kws)
logging.Logger.banner = log_banner

# Add loglevel SUCCESS (same as ERROR, but green)
logging.SUCCESS = 45
logging.addLevelName(logging.SUCCESS, "SUCCESS")
def log_success(self, message, *args, **kws):
  if self.isEnabledFor(logging.SUCCESS):
    self._log(logging.SUCCESS, message, args, **kws)
logging.Logger.success = log_success

logger = logging.getLogger('alibuild')
logger_handler = logging.StreamHandler()
logger.addHandler(logger_handler)
logger_handler.setFormatter(LogFormatter("%(levelname)s: %(message)s"))

debug = logger.debug
error = logger.error
warning = logger.warning
info = logger.info
banner = logger.banner
success = logger.success


class BuildStep:
    """Represents a single build step with timing information."""

    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"

    def __init__(self, name: str, version: str = ""):
        self.name = name
        self.version = version
        self.status = self.STATUS_PENDING
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def start(self):
        """Mark this step as started."""
        self.status = self.STATUS_IN_PROGRESS
        self.start_time = time.time()

    def finish(self, failed: bool = False):
        """Mark this step as completed."""
        self.end_time = time.time()
        self.status = self.STATUS_FAILED if failed else self.STATUS_DONE

    def get_duration(self) -> float:
        """Get the duration of this step in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.time()
        return end - self.start_time

    def format_duration(self) -> str:
        """Format the duration as a human-readable string."""
        duration = self.get_duration()
        if duration == 0:
            return ""
        elif duration < 60:
            return f"{duration:.1f}s"
        elif duration < 3600:
            minutes = int(duration / 60)
            seconds = duration % 60
            return f"{minutes}m {seconds:.0f}s"
        else:
            hours = int(duration / 3600)
            minutes = int((duration % 3600) / 60)
            return f"{hours}h {minutes}m"


class BuildProgress:
    def __init__(self, total_packages: int, max_log_lines: int = 5):
        self.total_packages = total_packages
        self.max_log_lines = max_log_lines
        self.build_steps: List[BuildStep] = []
        self.current_step: Optional[BuildStep] = None
        self.log_buffer = deque(maxlen=max_log_lines)
        self.is_tty = sys.stderr.isatty()
        self.enabled = self.is_tty
        self.last_update = 0
        self.update_interval = 0.1  # Update display at most every 100ms
        self.last_output = ""
        self.terminal_width = 80
        self.terminal_height = 24
        self.needs_redraw = False

        # ANSI escape codes
        self.CLEAR_LINE = "\033[2K"
        self.CLEAR_SCREEN = "\033[2J"
        self.CURSOR_HOME = "\033[H"
        self.HIDE_CURSOR = "\033[?25l"
        self.SHOW_CURSOR = "\033[?25h"
        self.SAVE_CURSOR = "\033[7"
        self.RESTORE_CURSOR = "\033[8"

        # Status symbols and colors
        self.SYMBOL_DONE = "\033[32m✓\033[m"      # Green checkmark
        self.SYMBOL_FAILED = "\033[31m✗\033[m"    # Red X
        self.SYMBOL_BUILDING = "\033[34m⋯\033[m"  # Blue ellipsis
        self.COLOR_DIM = "\033[2m"
        self.COLOR_RESET = "\033[m"
        self.COLOR_BOLD = "\033[1m"

        if self.enabled:
            self._update_terminal_size()
            self._setup_signal_handlers()
            sys.stderr.write(self.HIDE_CURSOR)
            sys.stderr.flush()

    def _setup_signal_handlers(self):
        """
        Set up signal handlers for terminal resize. We try to keep the output
        as clean as possible when resizing the terminal
        """
        try:
            signal.signal(signal.SIGWINCH, self._handle_resize)
        except (AttributeError, ValueError):
            # SIGWINCH not available on this platform or not in main thread
            pass

    def _handle_resize(self, signum, frame):
        """Handle terminal resize signal."""
        self._update_terminal_size()
        self.needs_redraw = True

    def _update_terminal_size(self):
        """Update the cached terminal size."""
        try:
            size = os.get_terminal_size(sys.stderr.fileno())
            self.terminal_width = size.columns
            self.terminal_height = size.lines
        except (OSError, AttributeError):
            self.terminal_width = 80
            self.terminal_height = 24

    def add_package(self, package_name: str, version: str = "") -> BuildStep:
        """Add a new package to the build queue."""
        step = BuildStep(package_name, version)
        self.build_steps.append(step)
        return step

    def start_package(self, package_name: str, version: str = ""):
        """Start building a package."""
        # Find existing step or create new one
        step = None
        for s in self.build_steps:
            if s.name == package_name:
                step = s
                break

        if step is None:
            step = self.add_package(package_name, version)

        step.start()
        self.current_step = step
        self.log_buffer.clear()

        if self.enabled:
            self._render()

    def finish_package(self, failed: bool = False):
        """Finish the current package."""
        if self.current_step:
            self.current_step.finish(failed)
            self.current_step = None

        if self.enabled:
            self._render()

    def log(self, line: str):
        """Add a log line to the scrolling buffer."""
        if not line:
            return

        # Strip ANSI codes for length calculation
        clean_line = re.sub(r'\033\[[0-9;]*m', '', line)

        # Truncate very long lines to terminal width
        max_len = self.terminal_width - 5  # Leave room for " => " prefix
        if len(clean_line) > max_len:
            line = clean_line[:max_len - 3] + "..."

        self.log_buffer.append(line)

        if self.enabled:
            now = time.time()
            # Rate limit updates
            if now - self.last_update > self.update_interval or self.needs_redraw:
                self._render()
                self.last_update = now

    def _format_step_line(self, step: BuildStep, index: int) -> str:
        """Format a single build step line"""
        step_num = f"[{index + 1}/{self.total_packages}]"
        version_str = f"@{step.version}" if step.version else ""
        name_with_version = f"{step.name}{version_str}"

        if step.status == BuildStep.STATUS_DONE:
            duration = step.format_duration()
            return f"{self.COLOR_DIM}{step_num}{self.COLOR_RESET} {self.SYMBOL_DONE} {name_with_version} {self.COLOR_DIM}{duration}{self.COLOR_RESET}"
        elif step.status == BuildStep.STATUS_FAILED:
            duration = step.format_duration()
            return f"{self.COLOR_DIM}{step_num}{self.COLOR_RESET} {self.SYMBOL_FAILED} {name_with_version} {self.COLOR_DIM}{duration}{self.COLOR_RESET}"
        elif step.status == BuildStep.STATUS_IN_PROGRESS:
            # Animate with spinner
            spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            spinner_idx = int((time.time() * 10) % len(spinner_chars))
            spinner = f"\033[36m{spinner_chars[spinner_idx]}\033[m"  # Cyan
            duration = step.format_duration()
            return f"{self.COLOR_DIM}{step_num}{self.COLOR_RESET} {spinner} {self.COLOR_BOLD}{name_with_version}{self.COLOR_RESET} {self.COLOR_DIM}{duration}{self.COLOR_RESET}"
        else:
            # Pending
            return f"{self.COLOR_DIM}{step_num} • {name_with_version}{self.COLOR_RESET}"

    def _format_output(self) -> str:
        """Format the complete output"""
        lines = []

        # Calculate available terminal lines (leave some margin for safety)
        max_lines = max(10, self.terminal_height - 3)
        
        # Find current step index
        current_idx = -1
        if self.current_step:
            for i, step in enumerate(self.build_steps):
                if step == self.current_step:
                    current_idx = i
                    break
        
        # Count completed steps
        completed_count = sum(1 for s in self.build_steps if s.status == BuildStep.STATUS_DONE)
        failed_count = sum(1 for s in self.build_steps if s.status == BuildStep.STATUS_FAILED)
        
        # Estimate lines needed for current step (step line + log lines)
        current_step_lines = 1 + (len(self.log_buffer) if self.current_step and self.log_buffer else 0)
        
        # Reserve lines for: summary line + current step + some context
        lines_for_summary = 1 if self.total_packages > 10 else 0
        available_for_steps = max_lines - lines_for_summary - current_step_lines
        
        # If we have many packages, show a summary + windowed view
        if len(self.build_steps) > available_for_steps:
            # Show summary of completed packages
            if completed_count > 0 or failed_count > 0:
                status_parts = []
                if completed_count > 0:
                    status_parts.append(f"{self.SYMBOL_DONE} {completed_count}")
                if failed_count > 0:
                    status_parts.append(f"{self.SYMBOL_FAILED} {failed_count}")
                summary = f"{self.COLOR_DIM}[{' '.join(status_parts)} / {self.total_packages} total]{self.COLOR_RESET}"
                lines.append(summary)
            
            # Determine window of steps to show
            # Show: last 2 completed + current + next 3 pending
            steps_to_show = []
            
            if current_idx >= 0:
                # Show recent completed steps (up to 2)
                recent_completed = []
                for i in range(current_idx - 1, -1, -1):
                    if self.build_steps[i].status in (BuildStep.STATUS_DONE, BuildStep.STATUS_FAILED):
                        recent_completed.insert(0, i)
                        if len(recent_completed) >= 2:
                            break
                
                # Show pending steps (up to 3)
                upcoming_pending = []
                for i in range(current_idx + 1, len(self.build_steps)):
                    if self.build_steps[i].status == BuildStep.STATUS_PENDING:
                        upcoming_pending.append(i)
                        if len(upcoming_pending) >= 3:
                            break
                
                steps_to_show = recent_completed + [current_idx] + upcoming_pending
            else:
                # No current step, show first available steps
                steps_to_show = list(range(min(available_for_steps, len(self.build_steps))))
            
            # Render the windowed steps
            for i in steps_to_show:
                step = self.build_steps[i]
                lines.append(self._format_step_line(step, i))
                
                # Show log output only for the currently building step
                if step == self.current_step and self.log_buffer:
                    for log_line in self.log_buffer:
                        lines.append(f" {self.COLOR_DIM}=>{self.COLOR_RESET} {log_line}")
        else:
            # Terminal is large enough, show all steps
            for i, step in enumerate(self.build_steps):
                lines.append(self._format_step_line(step, i))

                # Show log output only for the currently building step
                if step == self.current_step and self.log_buffer:
                    for log_line in self.log_buffer:
                        # Add " => " prefix like Docker
                        lines.append(f" {self.COLOR_DIM}=>{self.COLOR_RESET} {log_line}")

        return "\n".join(lines)

    def _render(self):
        """Render the complete display."""
        if not self.enabled:
            return

        new_output = self._format_output()

        # Handle terminal resize by doing a more aggressive clear
        if self.needs_redraw and self.last_output:
            # After resize, line wrapping changes, so calculate actual screen lines
            # Use a conservative estimate (double the logical lines, capped at 100)
            estimated_lines = min(self.last_output.count("\n") * 2 + 5, 100)
            sys.stderr.write(f"\033[{estimated_lines}A")
            sys.stderr.write("\r")
            # Clear everything from here down
            sys.stderr.write("\033[J")
            self.needs_redraw = False
        elif self.last_output:
            # Normal case: move cursor to beginning of last output
            num_lines = self.last_output.count("\n")
            if num_lines > 0:
                sys.stderr.write(f"\033[{num_lines}A")
                sys.stderr.write("\r")
            # Clear everything below cursor
            sys.stderr.write("\033[J")

        # Write new output
        sys.stderr.write(new_output)
        sys.stderr.flush()

        self.last_output = new_output

    def cleanup(self):
        """Clean up terminal state."""
        if self.enabled:
            # Move to next line and show cursor
            sys.stderr.write("\n")
            sys.stderr.write(self.SHOW_CURSOR)
            sys.stderr.flush()
            self.enabled = False  # Prevent duplicate cleanup

    def __del__(self):
        """Ensure cursor is shown on deletion."""
        try:
            self.cleanup()
        except Exception:
            pass
