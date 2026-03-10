"""
telemetry.workload.base — Abstract workload backend + shared result types.

To add a new workload type (e.g. embedding, image gen, whisper):
  1. Create a new file subclassing WorkloadBackend
  2. Implement run() and is_available()
  3. Register it in runner.py or use directly via TelemetryRunner
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable


@dataclass
class RequestResult:
    """Timing breakdown for a single inference request."""
    prompt:          str   = ""
    input_tokens:    int   = 0
    output_tokens:   int   = 0
    ttft_ms:         float = 0.0    # time-to-first-token
    total_ms:        float = 0.0    # full generation time (prefill + decode)
    success:         bool  = True
    error:           str   = ""

    @property
    def tpot_ms(self) -> float:
        """Time-per-output-token during the decode phase (excludes TTFT)."""
        toks = self.output_tokens - 1
        if toks <= 0 or self.total_ms <= self.ttft_ms:
            return 0.0
        return (self.total_ms - self.ttft_ms) / toks

    @property
    def tokens_per_sec(self) -> float:
        if self.total_ms <= 0:
            return 0.0
        return self.output_tokens / (self.total_ms / 1000.0)


def _percentile(lst: list[float], p: int) -> float:
    if not lst:
        return 0.0
    idx = int(len(lst) * p / 100)
    return lst[min(idx, len(lst) - 1)]


@dataclass
class WorkloadStats:
    """Aggregate workload metrics from a benchmark run."""
    model:              str   = ""
    server_url:         str   = ""
    concurrency:        int   = 0
    total_requests:     int   = 0
    successful:         int   = 0
    failed:             int   = 0
    total_duration_s:   float = 0.0

    # TTFT — time-to-first-token
    mean_ttft_ms:       float = 0.0
    p50_ttft_ms:        float = 0.0
    p95_ttft_ms:        float = 0.0
    p99_ttft_ms:        float = 0.0

    # TPOT — time-per-output-token (inter-token latency during decode)
    mean_tpot_ms:       float = 0.0
    p50_tpot_ms:        float = 0.0
    p95_tpot_ms:        float = 0.0
    p99_tpot_ms:        float = 0.0

    # End-to-end latency (prefill + full decode per request)
    mean_e2e_latency_ms: float = 0.0
    p99_e2e_latency_ms:  float = 0.0

    # Throughput
    mean_tokens_per_sec:  float = 0.0   # mean per-request output tok/s
    total_tokens_per_sec: float = 0.0   # total output tokens / total wall time
    total_output_tokens:  int   = 0
    total_input_tokens:   int   = 0
    requests_per_sec:     float = 0.0

    results: list[RequestResult] = field(default_factory=list)

    @classmethod
    def from_results(
        cls,
        results: list[RequestResult],
        model: str = "",
        duration_s: float = 0.0,
        server_url: str = "",
        concurrency: int = 0,
    ) -> "WorkloadStats":
        ok = [r for r in results if r.success]
        failed = len(results) - len(ok)

        ttfts = sorted(r.ttft_ms for r in ok)
        tpots = sorted(r.tpot_ms for r in ok if r.tpot_ms > 0)
        e2es  = sorted(r.total_ms for r in ok)

        total_out = sum(r.output_tokens for r in ok)
        total_in  = sum(r.input_tokens  for r in ok)

        return cls(
            model=model,
            server_url=server_url,
            concurrency=concurrency,
            total_requests=len(results),
            successful=len(ok),
            failed=failed,
            total_duration_s=duration_s,
            # TTFT
            mean_ttft_ms=sum(ttfts) / len(ttfts) if ttfts else 0.0,
            p50_ttft_ms=_percentile(ttfts, 50),
            p95_ttft_ms=_percentile(ttfts, 95),
            p99_ttft_ms=_percentile(ttfts, 99),
            # TPOT
            mean_tpot_ms=sum(tpots) / len(tpots) if tpots else 0.0,
            p50_tpot_ms=_percentile(tpots, 50),
            p95_tpot_ms=_percentile(tpots, 95),
            p99_tpot_ms=_percentile(tpots, 99),
            # E2E
            mean_e2e_latency_ms=sum(e2es) / len(e2es) if e2es else 0.0,
            p99_e2e_latency_ms=_percentile(e2es, 99),
            # Throughput
            mean_tokens_per_sec=sum(r.tokens_per_sec for r in ok) / len(ok) if ok else 0.0,
            total_tokens_per_sec=total_out / duration_s if duration_s > 0 else 0.0,
            total_output_tokens=total_out,
            total_input_tokens=total_in,
            requests_per_sec=len(ok) / duration_s if duration_s > 0 else 0.0,
            results=results,
        )


class WorkloadBackend(ABC):
    """
    Abstract base for workload / benchmark execution.

    Usage:
        stats = await backend.run(
            prompts=[...],
            max_tokens=200,
            on_request_done=callback,   # optional; called after each request
        )
    """

    name: str = "base"

    @abstractmethod
    async def run(
        self,
        prompts: list[str],
        max_tokens: int = 200,
        on_request_done: Optional[Callable[[int, RequestResult], None]] = None,
    ) -> WorkloadStats:
        """
        Send all prompts to the inference backend and return aggregate stats.

        on_request_done(request_index, result) is called after each request
        completes, which lets the runner trigger kernel profiling windows.
        """
        ...

    @classmethod
    @abstractmethod
    def is_available(cls, **kwargs) -> bool:
        """Return True if this backend can connect to its inference server."""
        ...
