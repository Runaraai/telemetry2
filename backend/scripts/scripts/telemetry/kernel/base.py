"""
telemetry.kernel.base — Abstract kernel profiling backend + shared types.

To add a new kernel profiling method (e.g. Nsight Systems, CUPTI direct):
  1. Create a new file (e.g. nsys.py) subclassing KernelBackend
  2. Implement start() / stop() / is_available()
  3. Register it in runner.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class KernelCategoryStats:
    """Timing stats for one kernel category."""
    category: str
    total_ms: float = 0.0
    pct: float = 0.0
    count: int = 0


@dataclass
class KernelStats:
    """Kernel-level profiling results from one profiling window."""
    total_cuda_ms: float = 0.0
    total_flops: int = 0
    categories: list[KernelCategoryStats] = field(default_factory=list)
    trace_source: str = ""          # path or identifier of trace
    profiled_requests: str = ""     # e.g. "16–36"

    @property
    def estimated_tflops(self) -> float:
        return self.total_flops / 1e12 if self.total_flops else 0.0

    def sorted_categories(self) -> list[KernelCategoryStats]:
        return sorted(self.categories, key=lambda c: c.total_ms, reverse=True)


class KernelBackend(ABC):
    """
    Abstract base for kernel-level profiling.

    Lifecycle:
      backend.start()   — begin capturing
      [inference runs]
      stats = backend.stop()  — end capturing, return KernelStats
    """

    name: str = "base"

    @abstractmethod
    def start(self) -> None:
        """Begin kernel profiling."""
        ...

    @abstractmethod
    def stop(self) -> KernelStats:
        """End profiling and return parsed results."""
        ...

    @classmethod
    @abstractmethod
    def is_available(cls, **kwargs) -> bool:
        """Return True if this backend can be used in the current environment."""
        ...
