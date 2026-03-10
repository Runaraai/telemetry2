"""
telemetry.report — Console summary and canonical JSON output for TelemetryResult.

save_json() is the single source of truth for the JSON output format.
Schema contract:
  - All keys always present; unsupported metrics = 0.0 / 0 / ""
  - Only the "kernel" top-level key is omitted when kernel profiling is disabled
  - Fields are never removed or renamed — only added (additive-only schema)
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .runner import TelemetryResult
from .gpu.base import CAP_SM_ACTIVE, CAP_TENSOR


def _fmt(val: float, unit: str = "", decimals: int = 1) -> str:
    return f"{val:.{decimals}f}{unit}"


# ── Console report ────────────────────────────────────────────────────────────

def print_report(result: TelemetryResult, title: str = "Telemetry Report") -> None:
    """Print a formatted summary to stdout."""
    SEP = "─" * 60

    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")

    # GPU identity
    meta = result.run_metadata
    if meta.get("gpu_name"):
        print(f"\n  GPU   : {meta['gpu_name']}")
        print(f"  Driver: {meta.get('driver_version', 'n/a')}  "
              f"CUDA: {meta.get('cuda_version', 'n/a')}  "
              f"Backend: {meta.get('gpu_backend', 'n/a')}")

    # ── Workload ──────────────────────────────────────────────────────────────
    w = result.workload
    if w:
        print(f"\n{'▶ Workload':}")
        print(SEP)
        print(f"  Model              : {w.model}")
        print(f"  Requests           : {w.successful}/{w.total_requests} ok  "
              f"({w.failed} failed)")
        print(f"  Duration           : {_fmt(w.total_duration_s, 's', 2)}")
        print(f"  Throughput         : {_fmt(w.requests_per_sec, ' req/s', 2)}  "
              f"| {_fmt(w.total_tokens_per_sec, ' tok/s total', 1)}")
        print()
        print(f"  TTFT  mean         : {_fmt(w.mean_ttft_ms, ' ms')}")
        print(f"  TTFT  p50/p95/p99  : {_fmt(w.p50_ttft_ms)} / "
              f"{_fmt(w.p95_ttft_ms)} / {_fmt(w.p99_ttft_ms)} ms")
        print(f"  TPOT  mean         : {_fmt(w.mean_tpot_ms, ' ms/tok')}")
        print(f"  TPOT  p50/p95/p99  : {_fmt(w.p50_tpot_ms)} / "
              f"{_fmt(w.p95_tpot_ms)} / {_fmt(w.p99_tpot_ms)} ms/tok")
        print(f"  E2E   mean/p99     : {_fmt(w.mean_e2e_latency_ms)} / "
              f"{_fmt(w.p99_e2e_latency_ms)} ms")
        print(f"  Tokens/s  (mean)   : {_fmt(w.mean_tokens_per_sec, ' tok/s')}")
        print(f"  Total tokens out   : {w.total_output_tokens}")
        print(f"  Total tokens in    : {w.total_input_tokens}")

    # ── GPU Hardware ──────────────────────────────────────────────────────────
    print(f"\n{'▶ GPU Hardware':}")
    print(SEP)
    if result.gpu_samples:
        print(f"  Samples            : {len(result.gpu_samples)}"
              f"  (every {result.gpu_poll_s}s)")
        print(f"  GPU util  mean/peak: "
              f"{_fmt(result.gpu_mean_util_pct)}% / {_fmt(result.gpu_peak_util_pct)}%")
        print(f"  Power     mean/peak: "
              f"{_fmt(result.gpu_mean_power_w, 'W')} / {_fmt(result.gpu_peak_power_w, 'W')}")
        print(f"  Temp      mean/peak: "
              f"{_fmt(result.gpu_mean_temp_c, '°C')} / {_fmt(result.gpu_peak_temp_c, '°C')}")
        print(f"  VRAM      peak/total: "
              f"{_fmt(result.gpu_peak_vram_mib, ' MiB', 0)} / "
              f"{_fmt(result.gpu_total_vram_mib, ' MiB', 0)}")
        if result.gpu_mean_sm_active > 0:
            print(f"  SM Active mean/peak: "
                  f"{_fmt(result.gpu_mean_sm_active)}% / {_fmt(result.gpu_peak_sm_active)}%")
        if result.gpu_mean_sm_occupancy > 0:
            print(f"  SM Occupancy  mean : {_fmt(result.gpu_mean_sm_occupancy)}%")
        if result.gpu_mean_tensor_pct > 0:
            print(f"  Tensor Active mean : {_fmt(result.gpu_mean_tensor_pct)}%")
        if result.gpu_mean_dram_active > 0:
            print(f"  DRAM Active   mean : {_fmt(result.gpu_mean_dram_active)}%")
        if result.gpu_mean_hbm_bw_gbps > 0:
            print(f"  HBM BW mean/peak   : "
                  f"{_fmt(result.gpu_mean_hbm_bw_gbps, ' GB/s')} / "
                  f"{_fmt(result.gpu_peak_hbm_bw_gbps, ' GB/s')}")
        if result.gpu_mean_nvlink_tx_kbps > 0:
            print(f"  NVLink TX mean     : "
                  f"{_fmt(result.gpu_mean_nvlink_tx_kbps / 1_000_000, ' GB/s', 2)}")
        if result.gpu_mean_l2_read_hit_pct > 0:
            print(f"  L2 hit  read/write : "
                  f"{_fmt(result.gpu_mean_l2_read_hit_pct)}% / "
                  f"{_fmt(result.gpu_mean_l2_write_hit_pct)}%")
        if result.mfu_pct > 0:
            print(f"  MFU                : {_fmt(result.mfu_pct)}%  "
                  f"(actual {_fmt(result.actual_tflops, ' TF', 3)} / "
                  f"peak {_fmt(result.run_metadata.get('peak_tflops_bf16', 0), ' TF BF16', 0)})")
    else:
        print("  No GPU samples collected.")

    # ── Kernel ────────────────────────────────────────────────────────────────
    k = result.kernel
    if k:
        print(f"\n{'▶ Kernel Profiling':}")
        print(SEP)
        print(f"  Trace source       : {k.trace_source}")
        if k.profiled_requests:
            print(f"  Profiled requests  : {k.profiled_requests}")
        print(f"  Total GPU time     : {_fmt(k.total_cuda_ms, ' ms')}")
        if k.estimated_tflops > 0:
            print(f"  Estimated TFLOPs   : {_fmt(k.estimated_tflops, ' TFLOPs', 3)}")
        print()
        print(f"  {'Category':<20} {'Time (ms)':>10} {'%':>7} {'Count':>8}")
        print(f"  {'-'*20} {'-'*10} {'-'*7} {'-'*8}")
        for cat in k.sorted_categories():
            print(f"  {cat.category:<20} {cat.total_ms:>10.1f} {cat.pct:>6.1f}% {cat.count:>8,}")

    # ── Bottleneck ────────────────────────────────────────────────────────────
    b = result.bottleneck
    if b:
        print(f"\n{'▶ Bottleneck Analysis':}")
        print(SEP)
        print(f"  Primary bottleneck : {b.get('primary', 'unknown').upper()}")
        print(f"  Roofline bound     : {b.get('roofline_bound', 'unknown')}")
        print(f"  Memory BW util     : {_fmt(b.get('memory_bw_util_pct', 0))}%")
        print(f"  Compute util (MFU) : {_fmt(b.get('compute_util_pct', 0))}%")
        print()
        for rec in b.get("recommendations", []):
            # Wrap at 75 chars for readability
            words = rec.split()
            line, lines = [], []
            for w in words:
                if len(" ".join(line + [w])) > 75:
                    lines.append(" ".join(line))
                    line = [w]
                else:
                    line.append(w)
            if line:
                lines.append(" ".join(line))
            print(f"  • {lines[0]}")
            for l in lines[1:]:
                print(f"    {l}")

    print(f"\n{'═' * 60}\n")


# ── JSON output ───────────────────────────────────────────────────────────────

def save_json(result: TelemetryResult,
              output_path: Optional[str] = None,
              title: str = "telemetry") -> Path:
    """
    Serialize TelemetryResult to the canonical JSON schema and return the path.

    Schema contract: all keys always present; only "kernel" may be absent.
    Unsupported metrics are 0.0. Never returns null values.
    """
    if output_path is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        output_path = f"/tmp/telemetry_{ts}.json"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    meta = result.run_metadata
    doc: dict = {
        "title":     title,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),

        # ── GPU identity & hardware spec ──────────────────────────────────────
        "run_metadata": {
            "gpu_name":          meta.get("gpu_name", ""),
            "gpu_count":         meta.get("gpu_count", 0),
            "gpu_index":         meta.get("gpu_index", 0),
            "driver_version":    meta.get("driver_version", ""),
            "cuda_version":      meta.get("cuda_version", ""),
            "gpu_backend":       meta.get("gpu_backend", ""),
            "gpu_capabilities":  meta.get("gpu_capabilities", []),
            "peak_hbm_bw_gbps":  meta.get("peak_hbm_bw_gbps", 0.0),
            "peak_tflops_bf16":  meta.get("peak_tflops_bf16", 0.0),
            "nvlink_bw_gbps":    meta.get("nvlink_bw_gbps", 0.0),
        },
    }

    # ── Workload ──────────────────────────────────────────────────────────────
    w = result.workload
    if w:
        doc["workload"] = {
            "model":                  w.model,
            "server_url":             w.server_url,
            "concurrency":            w.concurrency,
            "total_requests":         w.total_requests,
            "successful":             w.successful,
            "failed":                 w.failed,
            "duration_s":             round(w.total_duration_s, 3),
            "requests_per_sec":       round(w.requests_per_sec, 3),
            # TTFT
            "ttft_mean_ms":           round(w.mean_ttft_ms, 2),
            "ttft_p50_ms":            round(w.p50_ttft_ms, 2),
            "ttft_p95_ms":            round(w.p95_ttft_ms, 2),
            "ttft_p99_ms":            round(w.p99_ttft_ms, 2),
            # TPOT (inter-token latency in decode phase)
            "tpot_mean_ms":           round(w.mean_tpot_ms, 2),
            "tpot_p50_ms":            round(w.p50_tpot_ms, 2),
            "tpot_p95_ms":            round(w.p95_tpot_ms, 2),
            "tpot_p99_ms":            round(w.p99_tpot_ms, 2),
            # End-to-end latency
            "e2e_latency_mean_ms":    round(w.mean_e2e_latency_ms, 2),
            "e2e_latency_p99_ms":     round(w.p99_e2e_latency_ms, 2),
            # Throughput
            "tokens_per_sec_mean":    round(w.mean_tokens_per_sec, 2),
            "tokens_per_sec_total":   round(w.total_tokens_per_sec, 2),
            "total_output_tokens":    w.total_output_tokens,
            "total_input_tokens":     w.total_input_tokens,
        }

    # ── GPU hardware ──────────────────────────────────────────────────────────
    doc["gpu"] = {
        "samples":          len(result.gpu_samples),
        "poll_interval_s":  result.gpu_poll_s,

        # Compute
        "util_mean_pct":            round(result.gpu_mean_util_pct, 1),
        "util_peak_pct":            round(result.gpu_peak_util_pct, 1),
        "sm_active_mean_pct":       round(result.gpu_mean_sm_active, 1),
        "sm_active_peak_pct":       round(result.gpu_peak_sm_active, 1),
        "sm_occupancy_mean_pct":    round(result.gpu_mean_sm_occupancy, 1),
        "sm_occupancy_peak_pct":    round(result.gpu_peak_sm_occupancy, 1),
        "tensor_active_mean_pct":   round(result.gpu_mean_tensor_pct, 1),
        "tensor_active_peak_pct":   round(result.gpu_peak_tensor_pct, 1),
        "fp32_active_mean_pct":     round(result.gpu_mean_fp32_active, 1),
        "fp64_active_mean_pct":     round(result.gpu_mean_fp64_active, 1),

        # Memory
        "vram_peak_mib":            round(result.gpu_peak_vram_mib, 0),
        "vram_total_mib":           round(result.gpu_total_vram_mib, 0),
        "vram_util_mean_pct":       round(result.gpu_mean_vram_util_pct, 1),
        "dram_active_mean_pct":     round(result.gpu_mean_dram_active, 1),
        "dram_active_peak_pct":     round(result.gpu_peak_dram_active, 1),
        "hbm_bw_mean_gbps":         round(result.gpu_mean_hbm_bw_gbps, 1),
        "hbm_bw_peak_gbps":         round(result.gpu_peak_hbm_bw_gbps, 1),
        "hbm_bw_util_mean_pct":     round(result.gpu_mean_hbm_bw_util_pct, 1),
        # L2 cache — 0.0 on NVML / consumer GPU
        "l2_read_hit_mean_pct":     round(result.gpu_mean_l2_read_hit_pct, 1),
        "l2_write_hit_mean_pct":    round(result.gpu_mean_l2_write_hit_pct, 1),

        # Power & thermal
        "power_mean_w":  round(result.gpu_mean_power_w, 1),
        "power_peak_w":  round(result.gpu_peak_power_w, 1),
        "temp_mean_c":   round(result.gpu_mean_temp_c, 1),
        "temp_peak_c":   round(result.gpu_peak_temp_c, 1),

        # Clocks
        "sm_clock_mean_mhz":  round(result.gpu_mean_sm_clock_mhz, 0),
        "mem_clock_mean_mhz": round(result.gpu_mean_mem_clock_mhz, 0),

        # PCIe (CPU↔GPU)
        "pcie_tx_mean_kbps": round(result.gpu_mean_pcie_tx_kbps, 0),
        "pcie_tx_peak_kbps": round(result.gpu_peak_pcie_tx_kbps, 0),
        "pcie_rx_mean_kbps": round(result.gpu_mean_pcie_rx_kbps, 0),
        "pcie_rx_peak_kbps": round(result.gpu_peak_pcie_rx_kbps, 0),

        # NVLink (GPU↔GPU) — 0.0 on single-GPU or PCIe-only systems
        "nvlink_tx_mean_kbps": round(result.gpu_mean_nvlink_tx_kbps, 0),
        "nvlink_tx_peak_kbps": round(result.gpu_peak_nvlink_tx_kbps, 0),
        "nvlink_rx_mean_kbps": round(result.gpu_mean_nvlink_rx_kbps, 0),
        "nvlink_rx_peak_kbps": round(result.gpu_peak_nvlink_rx_kbps, 0),

        # FLOPS efficiency
        "theoretical_tflops_bf16": meta.get("peak_tflops_bf16", 0.0),
        "actual_tflops":           round(result.actual_tflops, 4),
        "mfu_pct":                 round(result.mfu_pct, 2),

        # Time series — all raw samples for dashboards / plots
        "time_series": [
            {
                "t":               round(s.timestamp, 3),
                "gpu_util_pct":    round(s.gpu_util_pct, 1),
                "sm_active_pct":   round(s.sm_active_pct, 1),
                "sm_occupancy_pct": round(s.sm_occupancy_pct, 1),
                "tensor_active_pct": round(s.tensor_active_pct, 1),
                "dram_active_pct": round(s.dram_active_pct, 1),
                "fp32_active_pct": round(s.fp32_active_pct, 1),
                "hbm_used_mib":    round(s.hbm_used_mib, 0),
                "power_w":         round(s.power_w, 1),
                "temp_c":          round(s.temp_c, 1),
                "sm_clock_mhz":    round(s.sm_clock_mhz, 0),
                "pcie_tx_kbps":    round(s.pcie_tx_kbps, 0),
                "pcie_rx_kbps":    round(s.pcie_rx_kbps, 0),
                "nvlink_tx_kbps":    round(s.nvlink_tx_kbps, 0),
                "nvlink_rx_kbps":    round(s.nvlink_rx_kbps, 0),
                "l2_read_hit_pct":   round(s.l2_read_hit_pct, 1),
                "l2_write_hit_pct":  round(s.l2_write_hit_pct, 1),
            }
            for s in result.gpu_samples
        ],
    }

    # ── Kernel profiling ──────────────────────────────────────────────────────
    k = result.kernel
    if k:
        doc["kernel"] = {
            "total_cuda_ms":      k.total_cuda_ms,
            "estimated_tflops":   round(k.estimated_tflops, 4),
            "trace_source":       k.trace_source,
            "profiled_requests":  k.profiled_requests,
            "categories": [
                {
                    "category": c.category,
                    "total_ms": c.total_ms,
                    "pct":      c.pct,
                    "count":    c.count,
                }
                for c in k.sorted_categories()
            ],
        }

    # ── Bottleneck analysis ───────────────────────────────────────────────────
    b = result.bottleneck
    doc["bottleneck"] = {
        "primary":                    b.get("primary", "unknown"),
        "compute_util_pct":           b.get("compute_util_pct", 0.0),
        "sm_active_mean_pct":         b.get("sm_active_mean_pct", 0.0),
        "memory_bw_util_pct":         b.get("memory_bw_util_pct", 0.0),
        "hbm_bw_mean_gbps":           b.get("hbm_bw_mean_gbps", 0.0),
        "cpu_overhead_estimated_pct": b.get("cpu_overhead_estimated_pct", 0.0),
        "nvlink_util_pct":            b.get("nvlink_util_pct", 0.0),
        "arithmetic_intensity":       b.get("arithmetic_intensity", 0.0),
        "roofline_bound":             b.get("roofline_bound", "unknown"),
        "recommendations":            b.get("recommendations", []),
    }

    path.write_text(json.dumps(doc, indent=2))
    return path
