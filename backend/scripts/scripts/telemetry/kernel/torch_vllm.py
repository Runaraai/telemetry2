"""
telemetry.kernel.torch_vllm — Kernel profiling via vLLM's built-in PyTorch Profiler.

Uses vLLM's /start_profile and /stop_profile HTTP endpoints to trigger
torch.profiler inside the vLLM engine process, then parses the resulting
Chrome trace JSON for per-kernel timing.

Requirements:
  - vLLM server started with --profiler-config:
      --profiler-config '{"profiler":"torch",
                          "torch_profiler_dir":"/tmp/vllm_traces",
                          "torch_profiler_with_flops":true,
                          "torch_profiler_use_gzip":false}'

GPU-agnostic: works on any GPU supported by PyTorch (CUDA, ROCm, XPU once
torch.profiler supports them). The kernel categorization covers CUDA naming
conventions; add patterns for ROCm HIP kernels in _KERNEL_PATTERNS below.
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from collections import defaultdict
from typing import Optional

import requests

from .base import KernelBackend, KernelStats, KernelCategoryStats

# ── Kernel name → category mapping ───────────────────────────────────────────
# Add patterns here to support new GPU architectures or backends.
# Keys are substring patterns (lowercase), values are category labels.
_KERNEL_PATTERNS: list[tuple[list[str], str]] = [
    (["attention", "flash", "fmha", "sdpa", "triton_attn"],      "attention"),
    (["gemm", "cublas", "matmul", "cutlass", "sgemm", "hgemm",
      "dgemm", "cgemm", "tgemm"],                                 "matmul_gemm"),
    (["layernorm", "rmsnorm", "layer_norm", "rms_norm"],          "layernorm"),
    (["softmax"],                                                  "softmax"),
    (["gelu", "silu", "relu", "elementwise", "act_",
      "swiglu", "geglu"],                                         "activation"),
    (["embedding", "gather", "scatter", "index"],                 "embedding"),
    (["allreduce", "nccl", "reduce_scatter", "all_gather"],       "communication"),
    (["memcpy", "memset", "d2d", "h2d", "d2h"],                   "memory_transfer"),
    (["topk", "sample", "sort", "argmax", "repetition", "penalt",
      "greedy"],                                                   "sampling"),
    (["cumsum", "scan", "prefix"],                                 "scan"),
    # ROCm HIP kernel naming conventions (for future AMD GPU support)
    (["hip_", "rocblas", "miopen"],                               "rocm_hip"),
]


def categorize_kernel(name: str) -> str:
    n = name.lower()
    for patterns, category in _KERNEL_PATTERNS:
        if any(p in n for p in patterns):
            return category
    return "other"


def _parse_trace(trace_file: Path) -> KernelStats:
    """Parse a Chrome trace JSON and extract GPU kernel stats."""
    with open(trace_file) as f:
        data = json.load(f)

    events = data if isinstance(data, list) else data.get("traceEvents", [])

    raw: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_us": 0.0})
    total_us = 0.0
    total_flops = 0

    for ev in events:
        if not isinstance(ev, dict):
            continue
        # Only actual GPU kernel execution events (cat == "kernel")
        # Excludes CPU-side CUDA API calls (cat == "cuda_runtime")
        if ev.get("ph") != "X" or ev.get("cat", "").lower() != "kernel":
            continue
        dur = ev.get("dur", 0)
        if dur <= 0:
            continue

        name = ev.get("name", "unknown")
        cat  = categorize_kernel(name)
        raw[cat]["count"]    += 1
        raw[cat]["total_us"] += dur
        total_us             += dur

        args = ev.get("args", {})
        if isinstance(args, dict):
            total_flops += args.get("flops", 0) or 0

    categories = []
    for cat, info in raw.items():
        pct = round(info["total_us"] / total_us * 100, 1) if total_us else 0.0
        categories.append(KernelCategoryStats(
            category=cat,
            total_ms=round(info["total_us"] / 1000, 2),
            pct=pct,
            count=info["count"],
        ))

    return KernelStats(
        total_cuda_ms=round(total_us / 1000, 2),
        total_flops=total_flops,
        categories=categories,
        trace_source=str(trace_file),
    )


class TorchVLLMKernelBackend(KernelBackend):
    """
    Kernel profiling via vLLM's /start_profile + /stop_profile endpoints.
    Parses the torch.profiler Chrome trace for per-category GPU kernel time.
    """

    name = "torch_vllm"

    def __init__(self,
                 server_url: str = "http://localhost:8000",
                 trace_dir: str = "/tmp/vllm_traces",
                 timeout: float = 30.0,
                 stop_timeout: float = 300.0):
        self.server_url   = server_url.rstrip("/")
        self.trace_dir    = Path(trace_dir)
        self.timeout      = timeout          # /start_profile — may block briefly under load
        self.stop_timeout = stop_timeout     # /stop_profile flushes trace to disk — can be slow
        self._snapshot_before: set[Path] = set()

    def _snapshot_traces(self) -> set[Path]:
        if not self.trace_dir.exists():
            return set()
        return set(self.trace_dir.rglob("*.json"))

    def start(self) -> None:
        self._snapshot_before = self._snapshot_traces()
        r = requests.post(f"{self.server_url}/start_profile", timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"/start_profile returned {r.status_code}. "
                               "Is vLLM running with --profiler-config?")

    def stop(self) -> KernelStats:
        # Fire /stop_profile in a background thread — vLLM 0.16's endpoint is
        # synchronous and blocks until the entire trace is flushed (can be
        # minutes for large traces). We read the file from disk directly once
        # it stabilizes, without needing the HTTP response.
        def _do_stop():
            try:
                requests.post(
                    f"{self.server_url}/stop_profile",
                    timeout=self.stop_timeout,
                )
            except Exception:
                pass  # HTTP timeout is expected; trace file is still written

        stop_thread = threading.Thread(target=_do_stop, daemon=True)
        stop_thread.start()

        # Wait up to stop_timeout seconds for a new trace file to appear
        # then wait until it stops growing (flush complete).
        deadline = time.time() + self.stop_timeout
        trace_file: Optional[Path] = None

        # Phase 1: wait for a substantive new trace file to appear.
        # GPU worker traces are named with "rank" or "worker"; tiny CPU-metadata
        # files are <50 KB. Wait until at least one file exceeds that threshold,
        # then pick the largest (most likely to contain GPU kernels).
        _MIN_SIZE_BYTES = 50 * 1024   # ignore files smaller than 50 KB

        while time.time() < deadline:
            new_traces = self._snapshot_traces() - self._snapshot_before
            substantial = [f for f in new_traces if f.stat().st_size >= _MIN_SIZE_BYTES]
            worker = [
                f for f in substantial
                if any(kw in f.name.lower() for kw in ("worker", "rank"))
            ]
            candidates = worker if worker else substantial
            if candidates:
                trace_file = max(candidates, key=lambda f: f.stat().st_size)
                break
            time.sleep(0.5)

        if trace_file is None:
            return KernelStats(trace_source="not found — check trace_dir and profiler config")

        print(f"\n[kernel] trace file detected: {trace_file.name}"
              f" ({trace_file.stat().st_size / 1e6:.1f} MB) — waiting for flush...",
              flush=True)

        # Phase 2: wait for file size to stabilize (not growing for 3s straight).
        stable_needed = 3.0   # seconds of no growth = flush complete
        stable_since  = None
        last_size     = -1
        while time.time() < deadline:
            try:
                size = trace_file.stat().st_size
            except FileNotFoundError:
                time.sleep(0.5)
                continue

            if size != last_size:
                last_size    = size
                stable_since = time.time()   # reset timer on any growth
            elif stable_since is not None and (time.time() - stable_since) >= stable_needed:
                break  # file hasn't grown for stable_needed seconds → flush done

            time.sleep(0.5)

        print(f"[kernel] trace stable at {last_size / 1e6:.1f} MB — parsing...", flush=True)
        return _parse_trace(trace_file)

    @classmethod
    def is_available(cls, server_url: str = "http://localhost:8000",
                     trace_dir: str = "/tmp/vllm_traces", **kwargs) -> bool:
        """Check if /start_profile endpoint exists on the vLLM server.

        Uses a GET probe (returns 405 if route exists, 404 if not) so we never
        accidentally trigger the profiler during the availability check.
        """
        try:
            r = requests.get(f"{server_url.rstrip('/')}/start_profile", timeout=3.0)
            # 405 Method Not Allowed = route is registered (POST-only endpoint exists)
            # 200 = unexpected but also means it's there
            # 404 = endpoint not registered (vLLM started without --profiler-config)
            return r.status_code in (200, 405)
        except Exception:
            return False
