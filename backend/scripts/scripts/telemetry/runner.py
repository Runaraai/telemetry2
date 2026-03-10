"""
telemetry.runner — TelemetryRunner: orchestrates GPU sampling, workload
benchmarking, and kernel profiling in a single concurrent run.

Architecture:
  ┌─────────────────────────────────────────────────┐
  │  TelemetryRunner.run()                          │
  │                                                 │
  │  Thread: GpuPoller (polls GPU every poll_s)     │
  │  Async:  WorkloadBackend.run()                  │
  │    └─ on_request_done callback:                 │
  │         • at kernel_start_idx → start kernel    │
  │         • at kernel_stop_idx  → stop kernel     │
  └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .gpu.base      import GpuBackend, GpuSample
from .kernel.base   import KernelBackend, KernelStats
from .workload.base import WorkloadBackend, WorkloadStats, RequestResult


# ── GPU polling thread ────────────────────────────────────────────────────────

class _GpuPoller(threading.Thread):
    """Background thread that polls the GPU backend at a fixed interval."""

    def __init__(self, backend: GpuBackend, interval_s: float = 0.5):
        super().__init__(daemon=True, name="gpu-poller")
        self.backend    = backend
        self.interval_s = interval_s
        self.samples: list[GpuSample] = []
        self._stop_evt  = threading.Event()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                sample = self.backend.collect()
                if sample is not None:
                    self.samples.append(sample)
            except Exception:
                pass
            self._stop_evt.wait(self.interval_s)

    def stop(self) -> list[GpuSample]:
        self._stop_evt.set()
        self.join(timeout=5.0)
        return self.samples


# ── TelemetryResult ───────────────────────────────────────────────────────────

@dataclass
class TelemetryResult:
    """Combined result from a single TelemetryRunner.run() call."""
    workload:     Optional[WorkloadStats] = None
    gpu_samples:  list[GpuSample]         = field(default_factory=list)
    kernel:       Optional[KernelStats]   = None
    run_metadata: dict                    = field(default_factory=dict)
    gpu_poll_s:   float                   = 0.5

    # ── GPU compute aggregates ────────────────────────────────────────────────
    gpu_mean_util_pct:       float = 0.0
    gpu_peak_util_pct:       float = 0.0
    gpu_mean_sm_active:      float = 0.0   # 0.0 on NVML / consumer GPU
    gpu_peak_sm_active:      float = 0.0
    gpu_mean_sm_occupancy:   float = 0.0
    gpu_peak_sm_occupancy:   float = 0.0
    gpu_mean_tensor_pct:     float = 0.0
    gpu_peak_tensor_pct:     float = 0.0
    gpu_mean_fp32_active:    float = 0.0
    gpu_mean_fp64_active:    float = 0.0

    # ── GPU memory aggregates ─────────────────────────────────────────────────
    gpu_peak_vram_mib:        float = 0.0
    gpu_total_vram_mib:       float = 0.0
    gpu_mean_vram_util_pct:   float = 0.0
    gpu_mean_dram_active:     float = 0.0
    gpu_peak_dram_active:     float = 0.0
    gpu_mean_hbm_bw_gbps:     float = 0.0   # derived: dram_active * spec_peak_bw
    gpu_peak_hbm_bw_gbps:     float = 0.0
    gpu_mean_hbm_bw_util_pct: float = 0.0   # mean_hbm_bw / spec_peak * 100

    # ── GPU power / thermal ───────────────────────────────────────────────────
    gpu_mean_power_w:  float = 0.0
    gpu_peak_power_w:  float = 0.0
    gpu_mean_temp_c:   float = 0.0
    gpu_peak_temp_c:   float = 0.0

    # ── GPU clocks ────────────────────────────────────────────────────────────
    gpu_mean_sm_clock_mhz:  float = 0.0
    gpu_mean_mem_clock_mhz: float = 0.0

    # ── GPU data movement ─────────────────────────────────────────────────────
    gpu_mean_pcie_tx_kbps:   float = 0.0
    gpu_peak_pcie_tx_kbps:   float = 0.0
    gpu_mean_pcie_rx_kbps:   float = 0.0
    gpu_peak_pcie_rx_kbps:   float = 0.0
    gpu_mean_nvlink_tx_kbps: float = 0.0
    gpu_peak_nvlink_tx_kbps: float = 0.0
    gpu_mean_nvlink_rx_kbps: float = 0.0
    gpu_peak_nvlink_rx_kbps: float = 0.0

    # ── L2 cache efficiency ───────────────────────────────────────────────────
    gpu_mean_l2_read_hit_pct:  float = 0.0   # 0.0 on NVML / consumer GPU
    gpu_mean_l2_write_hit_pct: float = 0.0

    # ── FLOPS efficiency ──────────────────────────────────────────────────────
    actual_tflops: float = 0.0   # from kernel profiling window; 0.0 if unavailable
    mfu_pct:       float = 0.0   # actual_tflops / peak_tflops_bf16 * 100

    # ── Bottleneck analysis output ────────────────────────────────────────────
    bottleneck: dict = field(default_factory=dict)

    # ── Aggregate computation ─────────────────────────────────────────────────

    def _compute_gpu_aggs(self) -> None:
        """Compute all aggregate and derived GPU metrics from raw samples."""
        s = self.gpu_samples
        if not s:
            return

        def _mean(f): return sum(f(x) for x in s) / len(s)
        def _peak(f): return max(f(x) for x in s)

        # Compute utilisation
        self.gpu_mean_util_pct     = _mean(lambda x: x.gpu_util_pct)
        self.gpu_peak_util_pct     = _peak(lambda x: x.gpu_util_pct)
        self.gpu_mean_sm_active    = _mean(lambda x: x.sm_active_pct)
        self.gpu_peak_sm_active    = _peak(lambda x: x.sm_active_pct)
        self.gpu_mean_sm_occupancy = _mean(lambda x: x.sm_occupancy_pct)
        self.gpu_peak_sm_occupancy = _peak(lambda x: x.sm_occupancy_pct)
        self.gpu_mean_tensor_pct   = _mean(lambda x: x.tensor_active_pct)
        self.gpu_peak_tensor_pct   = _peak(lambda x: x.tensor_active_pct)
        self.gpu_mean_fp32_active  = _mean(lambda x: x.fp32_active_pct)
        self.gpu_mean_fp64_active  = _mean(lambda x: x.fp64_active_pct)

        # Memory
        self.gpu_peak_vram_mib      = _peak(lambda x: x.hbm_used_mib)
        self.gpu_total_vram_mib     = _peak(lambda x: x.hbm_total_mib)
        self.gpu_mean_vram_util_pct = _mean(lambda x: x.hbm_util_pct)
        self.gpu_mean_dram_active   = _mean(lambda x: x.dram_active_pct)
        self.gpu_peak_dram_active   = _peak(lambda x: x.dram_active_pct)

        # Derived HBM bandwidth using GPU spec
        spec_peak_bw = self.run_metadata.get("peak_hbm_bw_gbps", 0.0)
        if spec_peak_bw > 0:
            self.gpu_mean_hbm_bw_gbps = (self.gpu_mean_dram_active / 100.0) * spec_peak_bw
            self.gpu_peak_hbm_bw_gbps = (self.gpu_peak_dram_active / 100.0) * spec_peak_bw
            self.gpu_mean_hbm_bw_util_pct = (
                self.gpu_mean_hbm_bw_gbps / spec_peak_bw * 100.0
            )

        # Power / thermal
        self.gpu_mean_power_w = _mean(lambda x: x.power_w)
        self.gpu_peak_power_w = _peak(lambda x: x.power_w)
        self.gpu_mean_temp_c  = _mean(lambda x: x.temp_c)
        self.gpu_peak_temp_c  = _peak(lambda x: x.temp_c)

        # Clocks
        self.gpu_mean_sm_clock_mhz  = _mean(lambda x: x.sm_clock_mhz)
        self.gpu_mean_mem_clock_mhz = _mean(lambda x: x.mem_clock_mhz)

        # Data movement — PCIe
        self.gpu_mean_pcie_tx_kbps = _mean(lambda x: x.pcie_tx_kbps)
        self.gpu_peak_pcie_tx_kbps = _peak(lambda x: x.pcie_tx_kbps)
        self.gpu_mean_pcie_rx_kbps = _mean(lambda x: x.pcie_rx_kbps)
        self.gpu_peak_pcie_rx_kbps = _peak(lambda x: x.pcie_rx_kbps)

        # Data movement — NVLink
        self.gpu_mean_nvlink_tx_kbps = _mean(lambda x: x.nvlink_tx_kbps)
        self.gpu_peak_nvlink_tx_kbps = _peak(lambda x: x.nvlink_tx_kbps)
        self.gpu_mean_nvlink_rx_kbps = _mean(lambda x: x.nvlink_rx_kbps)
        self.gpu_peak_nvlink_rx_kbps = _peak(lambda x: x.nvlink_rx_kbps)

        # L2 cache
        self.gpu_mean_l2_read_hit_pct  = _mean(lambda x: x.l2_read_hit_pct)
        self.gpu_mean_l2_write_hit_pct = _mean(lambda x: x.l2_write_hit_pct)

    def _compute_mfu(self) -> None:
        """Compute Model FLOPS Utilization from kernel data and GPU spec."""
        if self.kernel is None or self.kernel.total_cuda_ms <= 0:
            return
        spec_peak = self.run_metadata.get("peak_tflops_bf16", 0.0)
        if spec_peak <= 0:
            return
        self.actual_tflops = self.kernel.estimated_tflops
        if self.actual_tflops > 0 and self.kernel.total_cuda_ms > 0:
            # estimated_tflops = total_flops / 1e12 (total in window)
            # Convert to a rate over the kernel window duration
            window_s = self.kernel.total_cuda_ms / 1000.0
            actual_tflops_rate = self.actual_tflops / window_s if window_s > 0 else 0.0
            self.mfu_pct = (actual_tflops_rate / spec_peak) * 100.0


# ── TelemetryRunner ───────────────────────────────────────────────────────────

class TelemetryRunner:
    """
    Runs all three metric streams together in a single benchmark call.

    Parameters
    ----------
    gpu_backend     : GpuBackend instance (use AutoGpuBackend for auto-detect)
    workload_backend: WorkloadBackend instance (e.g. VLLMOpenAIBackend)
    kernel_backend  : Optional KernelBackend; if None, kernel profiling is skipped
    gpu_poll_s      : GPU sampling interval in seconds (default 0.5)
    kernel_start_idx: Request index at which to start kernel profiling (default 10)
    kernel_stop_idx : Request index at which to stop  kernel profiling (default 30)
    """

    def __init__(
        self,
        gpu_backend:      GpuBackend,
        workload_backend:  WorkloadBackend,
        kernel_backend:   Optional[KernelBackend] = None,
        gpu_poll_s:       float = 0.5,
        kernel_start_idx: int   = 10,
        kernel_stop_idx:  int   = 30,
    ):
        self.gpu      = gpu_backend
        self.workload = workload_backend
        self.kernel   = kernel_backend
        self.poll_s   = gpu_poll_s
        self.k_start  = kernel_start_idx
        self.k_stop   = kernel_stop_idx

        self._kernel_started = False
        self._kernel_stopped = False
        self._kernel_stats:  Optional[KernelStats] = None
        self._kernel_stop_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ── kernel trigger callback ───────────────────────────────────────────────

    def _on_request_done(self, idx: int, result: RequestResult) -> None:
        if self.kernel is None:
            return

        with self._lock:
            if idx == self.k_start and not self._kernel_started:
                try:
                    self.kernel.start()
                    self._kernel_started = True
                    print(f"\n[kernel] profiling started at request {idx}")
                except Exception as exc:
                    print(f"\n[kernel] start failed: {exc}")

            elif idx == self.k_stop and self._kernel_started and not self._kernel_stopped:
                self._kernel_stopped = True
                # Run stop() in a background thread so the workload loop is
                # not blocked during the (potentially long) trace flush.
                def _stop_kernel():
                    try:
                        stats = self.kernel.stop()
                        with self._lock:
                            self._kernel_stats = stats
                        print(f"\n[kernel] profiling stopped at request {idx}")
                    except Exception as exc:
                        print(f"\n[kernel] stop failed: {exc}")
                self._kernel_stop_thread = threading.Thread(
                    target=_stop_kernel, daemon=True, name="kernel-stop"
                )
                self._kernel_stop_thread.start()

    # ── main entry point ──────────────────────────────────────────────────────

    async def run(
        self,
        prompts: list[str],
        max_tokens: int = 200,
        verbose: bool = True,
    ) -> TelemetryResult:
        """
        Run the full telemetry suite.

        Returns a TelemetryResult with workload stats, GPU time-series samples,
        all GPU aggregates, run_metadata, MFU, and bottleneck analysis.
        """
        self._kernel_started      = False
        self._kernel_stopped      = False
        self._kernel_stats        = None
        self._kernel_stop_thread  = None

        # Clamp kernel window to prompt list length
        n = len(prompts)
        k_start = min(self.k_start, max(0, n - 2))
        k_stop  = min(self.k_stop,  n - 1)
        self.k_start = k_start
        self.k_stop  = k_stop

        if verbose:
            gpu_desc = self.gpu.describe() if hasattr(self.gpu, "describe") else self.gpu.name
            print(f"[runner] GPU backend  : {gpu_desc}")
            print(f"[runner] Workload      : {self.workload.name}")
            kname = self.kernel.name if self.kernel else "disabled"
            print(f"[runner] Kernel prof   : {kname}")
            if self.kernel:
                print(f"[runner] Kernel window : requests {k_start}–{k_stop}")
            print(f"[runner] Prompts       : {n}  |  max_tokens={max_tokens}")
            print()

        # ── collect GPU metadata before the run ───────────────────────────────
        run_metadata: dict = {}
        try:
            run_metadata = self.gpu.get_metadata()
        except Exception:
            pass

        # ── start GPU poller ──────────────────────────────────────────────────
        poller = _GpuPoller(self.gpu, interval_s=self.poll_s)
        poller.start()

        # ── run workload (async, kernel callback fires mid-run) ───────────────
        try:
            workload_stats = await self.workload.run(
                prompts=prompts,
                max_tokens=max_tokens,
                on_request_done=self._on_request_done,
            )
        finally:
            # Ensure kernel profiling is stopped even if workload crashes
            # before the stop callback fired (run stop synchronously in that case).
            if self.kernel and self._kernel_started and not self._kernel_stopped:
                try:
                    self._kernel_stats   = self.kernel.stop()
                    self._kernel_stopped = True
                except Exception:
                    pass
            gpu_samples = poller.stop()

        # Wait for the background kernel-stop thread (started by the callback)
        # before assembling results — it may still be waiting for trace flush.
        if self._kernel_stop_thread is not None:
            stop_timeout = getattr(self.kernel, "stop_timeout", 600.0)
            self._kernel_stop_thread.join(timeout=stop_timeout)

        # ── assemble & enrich result ──────────────────────────────────────────
        result = TelemetryResult(
            workload=workload_stats,
            gpu_samples=gpu_samples,
            kernel=self._kernel_stats,
            run_metadata=run_metadata,
            gpu_poll_s=self.poll_s,
        )
        result._compute_gpu_aggs()
        result._compute_mfu()

        # Bottleneck analysis (imported lazily to avoid circular dependency)
        from .bottleneck import analyze
        result.bottleneck = analyze(result)

        return result
