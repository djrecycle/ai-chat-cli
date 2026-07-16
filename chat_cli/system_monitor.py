"""Lightweight CPU and memory monitoring for the current process."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResourceStats:
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0


class ProcessResourceMonitor:
    def __init__(self) -> None:
        self._clock_ticks = os.sysconf("SC_CLK_TCK")
        self._page_size = os.sysconf("SC_PAGE_SIZE")
        self._last_time = time.monotonic()
        self._last_cpu = self._read_cpu_seconds()

    def _read_cpu_seconds(self) -> float:
        raw = Path("/proc/self/stat").read_text(encoding="utf-8")
        fields = raw[raw.rfind(")") + 2 :].split()
        ticks = int(fields[11]) + int(fields[12])
        return ticks / self._clock_ticks

    def sample(self) -> ResourceStats:
        now = time.monotonic()
        cpu_seconds = self._read_cpu_seconds()
        elapsed = max(now - self._last_time, 1e-6)
        cpu_percent = max(0.0, (cpu_seconds - self._last_cpu) / elapsed * 100.0)
        self._last_time = now
        self._last_cpu = cpu_seconds

        statm = Path("/proc/self/statm").read_text(encoding="utf-8").split()
        resident_bytes = int(statm[1]) * self._page_size
        memory_mb = resident_bytes / (1024 * 1024)

        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
        total_kb = next(
            int(line.split()[1]) for line in meminfo if line.startswith("MemTotal:")
        )
        memory_percent = resident_bytes / (total_kb * 1024) * 100.0
        return ResourceStats(cpu_percent, memory_mb, memory_percent)
