"""
telemetry.gpu.specs — GPU hardware spec constants.

Used to compute derived metrics:
  - HBM bandwidth utilization %  (actual_bw / peak_bw * 100)
  - MFU %                        (actual_tflops / peak_tflops * 100)
  - Roofline ridge point         (peak_tflops / peak_hbm_bw)

To add a new GPU:
  1. Find the official spec sheet values for BF16 TFLOPS and HBM peak BW.
  2. Add an entry to GPU_SPECS whose key is a lowercase substring of the
     NVML device name (e.g. from nvmlDeviceGetName) or DCGM modelName label.
  3. Use the most specific key possible so it matches before a shorter one.
"""

from __future__ import annotations

# Keys are lowercase substrings of the GPU name returned by NVML / DCGM.
# First match wins — list more-specific entries before less-specific ones.
# BF16 TFLOPS: peak Tensor Core throughput in BF16 (sparse = False / dense).
# peak_hbm_bw_gbps: theoretical maximum HBM bandwidth in GB/s.

GPU_SPECS: list[tuple[str, dict]] = [
    # ── NVIDIA Blackwell ─────────────────────────────────────────────────────
    ("b200",           {"peak_tflops_bf16": 2250.0, "peak_hbm_bw_gbps": 8000.0,
                        "nvlink_bw_gbps": 1800.0}),

    # ── NVIDIA Hopper ────────────────────────────────────────────────────────
    ("h100 sxm",       {"peak_tflops_bf16":  989.0, "peak_hbm_bw_gbps": 3350.0,
                        "nvlink_bw_gbps":  900.0}),
    ("h100 pcie",      {"peak_tflops_bf16":  756.0, "peak_hbm_bw_gbps": 2000.0,
                        "nvlink_bw_gbps":    0.0}),
    ("h100",           {"peak_tflops_bf16":  989.0, "peak_hbm_bw_gbps": 3350.0,
                        "nvlink_bw_gbps":  900.0}),

    # ── NVIDIA Ampere (data-centre) ──────────────────────────────────────────
    ("a100 sxm4 80gb", {"peak_tflops_bf16":  312.0, "peak_hbm_bw_gbps": 2000.0,
                        "nvlink_bw_gbps":  600.0}),
    ("a100 sxm4 40gb", {"peak_tflops_bf16":  312.0, "peak_hbm_bw_gbps": 1555.0,
                        "nvlink_bw_gbps":  600.0}),
    ("a100 sxm",       {"peak_tflops_bf16":  312.0, "peak_hbm_bw_gbps": 2000.0,
                        "nvlink_bw_gbps":  600.0}),
    ("a100 pcie 80gb", {"peak_tflops_bf16":  312.0, "peak_hbm_bw_gbps": 1935.0,
                        "nvlink_bw_gbps":    0.0}),
    ("a100 pcie",      {"peak_tflops_bf16":  312.0, "peak_hbm_bw_gbps": 1555.0,
                        "nvlink_bw_gbps":    0.0}),
    ("a100",           {"peak_tflops_bf16":  312.0, "peak_hbm_bw_gbps": 2000.0,
                        "nvlink_bw_gbps":  600.0}),

    # ── NVIDIA Ada Lovelace (data-centre) ────────────────────────────────────
    ("l40s",           {"peak_tflops_bf16":  362.0, "peak_hbm_bw_gbps":  864.0,
                        "nvlink_bw_gbps":    0.0}),
    ("l40",            {"peak_tflops_bf16":  181.0, "peak_hbm_bw_gbps":  864.0,
                        "nvlink_bw_gbps":    0.0}),

    # ── NVIDIA Ampere (workstation / pro-vis) ────────────────────────────────
    ("a40",            {"peak_tflops_bf16":  149.7, "peak_hbm_bw_gbps":  696.0,
                        "nvlink_bw_gbps":    0.0}),
    ("a30",            {"peak_tflops_bf16":  165.0, "peak_hbm_bw_gbps":  933.0,
                        "nvlink_bw_gbps":  200.0}),
    ("a16",            {"peak_tflops_bf16":   62.5, "peak_hbm_bw_gbps":  200.0,
                        "nvlink_bw_gbps":    0.0}),
    ("a10g",           {"peak_tflops_bf16":   31.2, "peak_hbm_bw_gbps":  600.0,
                        "nvlink_bw_gbps":    0.0}),
    ("a10",            {"peak_tflops_bf16":   31.2, "peak_hbm_bw_gbps":  600.0,
                        "nvlink_bw_gbps":    0.0}),

    # ── NVIDIA Volta ─────────────────────────────────────────────────────────
    # Note: Volta uses FP16 not BF16; peak_tflops_bf16 ≈ peak_tflops_fp16
    ("v100 sxm2 32gb", {"peak_tflops_bf16":  112.0, "peak_hbm_bw_gbps":  900.0,
                        "nvlink_bw_gbps":  300.0}),
    ("v100 sxm2 16gb", {"peak_tflops_bf16":  112.0, "peak_hbm_bw_gbps":  900.0,
                        "nvlink_bw_gbps":  300.0}),
    ("v100 sxm",       {"peak_tflops_bf16":  112.0, "peak_hbm_bw_gbps":  900.0,
                        "nvlink_bw_gbps":  300.0}),
    ("v100 pcie 32gb", {"peak_tflops_bf16":  112.0, "peak_hbm_bw_gbps":  900.0,
                        "nvlink_bw_gbps":    0.0}),
    ("v100 pcie",      {"peak_tflops_bf16":  112.0, "peak_hbm_bw_gbps":  900.0,
                        "nvlink_bw_gbps":    0.0}),
    ("v100",           {"peak_tflops_bf16":  112.0, "peak_hbm_bw_gbps":  900.0,
                        "nvlink_bw_gbps":  300.0}),

    # ── AMD (future) ─────────────────────────────────────────────────────────
    ("mi300x",         {"peak_tflops_bf16": 1307.0, "peak_hbm_bw_gbps": 5300.0,
                        "nvlink_bw_gbps":    0.0}),  # AMD uses Infinity Fabric, not NVLink
    ("mi250x",         {"peak_tflops_bf16":  383.0, "peak_hbm_bw_gbps": 3200.0,
                        "nvlink_bw_gbps":    0.0}),
]

_UNKNOWN: dict = {"peak_tflops_bf16": 0.0, "peak_hbm_bw_gbps": 0.0, "nvlink_bw_gbps": 0.0}


def get_gpu_specs(gpu_name: str) -> dict:
    """
    Return spec dict for a GPU by matching its name (case-insensitive substring).

    Returns {"peak_tflops_bf16": 0.0, "peak_hbm_bw_gbps": 0.0, "nvlink_bw_gbps": 0.0}
    for unknown GPUs — callers must handle zeros gracefully (MFU will be 0.0).
    """
    name_lower = gpu_name.lower()
    for key, specs in GPU_SPECS:
        if key in name_lower:
            return dict(specs)
    return dict(_UNKNOWN)
