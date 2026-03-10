"""
telemetry.bottleneck — GPU inference bottleneck classification and recommendations.

Given a TelemetryResult, this module:
  1. Classifies the primary bottleneck (compute / memory / cpu / network / unknown)
  2. Computes a roofline position (arithmetic intensity vs ridge point)
  3. Generates a list of actionable optimization recommendations

Thresholds are conservative and tuned for LLM inference on data-centre GPUs.
All thresholds can be overridden by passing a custom config dict to analyze().
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import TelemetryResult

# ── Default classification thresholds ────────────────────────────────────────

_DEFAULTS = {
    # MFU % above which the GPU is considered compute-saturated
    "compute_saturated_pct":    70.0,
    # SM Active % above which we flag compute pressure even without MFU data
    "sm_active_high_pct":       80.0,
    # HBM bandwidth utilization % above which memory is the bottleneck
    "memory_bw_saturated_pct":  75.0,
    # DRAM active % (fallback when HBM BW spec not known) above which mem-bound
    "dram_active_high_pct":     70.0,
    # GPU util % below which a CPU / scheduling bottleneck is suspected
    "gpu_idle_pct":             50.0,
    # NVLink utilization % above which inter-GPU comm is the bottleneck
    "nvlink_saturated_pct":     80.0,
    # SM Occupancy % below which we warn about low occupancy
    "sm_occupancy_low_pct":     20.0,
    # Tensor core active % below which we warn about underutilisation
    "tensor_low_pct":           20.0,
    # VRAM utilization % above which we warn about memory pressure
    "vram_high_pct":            90.0,
    # PCIe TX KB/s above which CPU→GPU transfer may be a concern
    "pcie_tx_high_kbps":        5_000_000,  # ~5 GB/s
}


def analyze(result: "TelemetryResult", config: dict | None = None) -> dict:
    """
    Classify the bottleneck and generate recommendations for a TelemetryResult.

    Returns a dict matching the canonical JSON `bottleneck` section.
    """
    cfg = {**_DEFAULTS, **(config or {})}

    # Pull key metrics from result (all default to 0.0 if not available)
    mfu_pct             = result.mfu_pct
    sm_active_mean      = result.gpu_mean_sm_active
    hbm_bw_util_pct     = result.gpu_mean_hbm_bw_util_pct
    dram_active_mean    = result.gpu_mean_dram_active
    gpu_util_mean       = result.gpu_mean_util_pct
    nvlink_tx_mean      = result.gpu_mean_nvlink_tx_kbps
    sm_occupancy_mean   = result.gpu_mean_sm_occupancy
    tensor_active_mean  = result.gpu_mean_tensor_pct
    vram_util_mean      = result.gpu_mean_vram_util_pct
    pcie_tx_mean        = result.gpu_mean_pcie_tx_kbps

    spec_peak_bw   = result.run_metadata.get("peak_hbm_bw_gbps", 0.0)
    nvlink_peak_bw = result.run_metadata.get("nvlink_bw_gbps", 0.0)

    # ── Compute effective BW utilization for roofline ─────────────────────────
    # Use hbm_bw_util_pct if we have spec data; fall back to dram_active %
    effective_mem_util = hbm_bw_util_pct if spec_peak_bw > 0 else dram_active_mean

    # ── Arithmetic intensity for roofline ─────────────────────────────────────
    arithmetic_intensity = 0.0
    roofline_bound = "unknown"
    if (result.kernel and result.kernel.total_flops > 0
            and result.gpu_mean_hbm_bw_gbps > 0
            and result.kernel.total_cuda_ms > 0):
        window_s = result.kernel.total_cuda_ms / 1000.0
        bytes_transferred = result.gpu_mean_hbm_bw_gbps * 1e9 * window_s
        arithmetic_intensity = result.kernel.total_flops / bytes_transferred
        if spec_peak_bw > 0 and result.run_metadata.get("peak_tflops_bf16", 0) > 0:
            ridge_point = (result.run_metadata["peak_tflops_bf16"] * 1e12
                           / (spec_peak_bw * 1e9))
            roofline_bound = "compute" if arithmetic_intensity >= ridge_point else "memory"

    # ── NVLink utilization % ──────────────────────────────────────────────────
    nvlink_util_pct = 0.0
    if nvlink_peak_bw > 0 and nvlink_tx_mean > 0:
        nvlink_util_pct = (nvlink_tx_mean / 1024.0) / (nvlink_peak_bw * 1e6) * 100.0

    # ── Primary bottleneck classification ─────────────────────────────────────
    primary = "unknown"

    if mfu_pct >= cfg["compute_saturated_pct"]:
        primary = "compute"
    elif sm_active_mean >= cfg["sm_active_high_pct"] and mfu_pct == 0.0:
        # MFU unavailable (no kernel profiling), use SM Active as proxy
        primary = "compute"
    elif effective_mem_util >= cfg["memory_bw_saturated_pct"]:
        primary = "memory"
    elif dram_active_mean >= cfg["dram_active_high_pct"] and spec_peak_bw == 0.0:
        # No spec data — use raw DRAM active % as fallback indicator
        primary = "memory"
    elif nvlink_util_pct >= cfg["nvlink_saturated_pct"]:
        primary = "network"
    elif gpu_util_mean < cfg["gpu_idle_pct"]:
        primary = "cpu"

    # ── Build recommendations ─────────────────────────────────────────────────
    recs: list[str] = []

    if primary == "compute":
        recs.append(
            f"GPU is compute-bound (MFU {mfu_pct:.0f}% / SM Active {sm_active_mean:.0f}%). "
            "Consider FP8 quantization, tensor parallelism, or Flash Attention to reduce FLOPs."
        )

    if primary == "memory":
        recs.append(
            f"GPU is memory-bandwidth bound (HBM util {effective_mem_util:.0f}%). "
            "Consider FP8/INT8 quantization (smaller weights → less BW), "
            "larger batch sizes, or prefix caching to reduce redundant HBM reads."
        )

    if primary == "cpu":
        recs.append(
            f"GPU is under-utilised ({gpu_util_mean:.0f}% avg). "
            "Likely CPU-side bottleneck: tokenization, Python overhead, or scheduler latency. "
            "Profile with py-spy or increase batch size / concurrency."
        )

    if primary == "network":
        recs.append(
            f"NVLink is saturated ({nvlink_util_pct:.0f}% util). "
            "Reduce tensor parallelism degree or check NCCL all-reduce overhead."
        )

    if sm_occupancy_mean > 0 and sm_occupancy_mean < cfg["sm_occupancy_low_pct"]:
        recs.append(
            f"SM Occupancy is low ({sm_occupancy_mean:.0f}%). "
            "Kernel is likely register- or shared-memory limited. "
            "Try larger batch sizes or review kernel launch configurations."
        )

    if tensor_active_mean > 0 and tensor_active_mean < cfg["tensor_low_pct"]:
        recs.append(
            f"Tensor core utilisation is low ({tensor_active_mean:.0f}%). "
            "Ensure inputs are in BF16/FP16/FP8 and matrix dimensions are multiples of 16 "
            "(ideally 128) for Tensor Core alignment."
        )

    if vram_util_mean >= cfg["vram_high_pct"]:
        recs.append(
            f"VRAM utilisation is very high ({vram_util_mean:.0f}%). "
            "Risk of OOM — consider quantization, smaller context length, or KV cache offloading."
        )

    if pcie_tx_mean > cfg["pcie_tx_high_kbps"]:
        pcie_gbps = pcie_tx_mean / 1_000_000
        recs.append(
            f"High PCIe TX traffic ({pcie_gbps:.1f} GB/s). "
            "CPU→GPU transfers are significant — check if input tokenization or "
            "activation offloading is adding overhead."
        )

    if roofline_bound == "memory" and primary == "compute":
        recs.append(
            "Roofline analysis suggests memory-bound despite high SM utilisation — "
            "workload may have low arithmetic intensity. Review KV cache access patterns."
        )

    if not recs:
        recs.append(
            "No clear bottleneck identified. GPU appears balanced or profiling data is limited. "
            "Enable kernel profiling (--profiler-config) and DCGM for deeper analysis."
        )

    return {
        "primary":                    primary,
        "compute_util_pct":           round(mfu_pct, 1),
        "sm_active_mean_pct":         round(sm_active_mean, 1),
        "memory_bw_util_pct":         round(effective_mem_util, 1),
        "hbm_bw_mean_gbps":           round(result.gpu_mean_hbm_bw_gbps, 1),
        "cpu_overhead_estimated_pct": round(max(0.0, 100.0 - gpu_util_mean), 1),
        "nvlink_util_pct":            round(nvlink_util_pct, 1),
        "arithmetic_intensity":       round(arithmetic_intensity, 2),
        "roofline_bound":             roofline_bound,
        "recommendations":            recs,
    }
