"""Shared logging and progress utilities."""

import time
from datetime import datetime


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str, indent: int = 0) -> None:
    prefix = "  " * indent
    print(f"[{ts()}] {prefix}{msg}", flush=True)


def log_section(title: str) -> None:
    line = "─" * (54 - len(title))
    print(f"\n[{ts()}] ┌─ {title} {line}┐", flush=True)


def log_section_end() -> None:
    print(f"[{ts()}] └{'─' * 57}┘", flush=True)


class ProgressBar:
    """Single-line ASCII progress bar. Prints a new line each update (log-friendly)."""

    def __init__(self, total: int, prefix: str = "", width: int = 20) -> None:
        self.total = total
        self.prefix = prefix
        self.width = width
        self._start = time.time()
        self._done = 0

    def update(self, current: int, suffix: str = "") -> None:
        self._done = current
        pct = current / self.total if self.total else 0
        filled = int(self.width * pct)
        bar = "█" * filled + "░" * (self.width - filled)
        elapsed = time.time() - self._start
        if current > 0:
            eta = elapsed / current * (self.total - current)
            eta_str = f"ETA {eta:.0f}s"
        else:
            eta_str = "ETA ?s"
        print(
            f"[{ts()}]   {self.prefix}[{bar}] {current:>4}/{self.total} "
            f"({pct:>3.0%}) | {elapsed:.0f}s | {eta_str}  {suffix}",
            flush=True,
        )

    def done(self, suffix: str = "") -> None:
        elapsed = time.time() - self._start
        bar = "█" * self.width
        print(
            f"[{ts()}]   {self.prefix}[{bar}] {self.total:>4}/{self.total} "
            f"(100%) | {elapsed:.0f}s | done  {suffix}",
            flush=True,
        )


class RunStats:
    """Track crawl/enrich counts and print a live summary."""

    def __init__(self) -> None:
        self.found = 0
        self.skipped = 0
        self.no_match = 0
        self.errors = 0
        self._start = time.time()

    def elapsed(self) -> str:
        s = int(time.time() - self._start)
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    def summary_line(self) -> str:
        return (
            f"found={self.found} skipped={self.skipped} "
            f"no_match={self.no_match} errors={self.errors} "
            f"elapsed={self.elapsed()}"
        )
