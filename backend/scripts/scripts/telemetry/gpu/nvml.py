"""
telemetry.gpu.nvml — pynvml (NVML) direct backend.

Works on ANY NVIDIA GPU — consumer GeForce, Quadro, and data-centre — without
requiring DCGM or any external exporter process.

Does NOT provide hardware profiling counters (SM Active, Tensor Core, DRAM BW).
Use DCGMBackend on data-centre GPUs to get those.

Adding support for a new NVIDIA GPU: nothing to do here — NVML works
across all NVIDIA architectures automatically.
"""

from __future__ import annotations

import time
from typing import Optional

from .base import (
    GpuBackend, GpuSample,
    CAP_UTIL, CAP_POWER, CAP_VRAM, CAP_TEMP, CAP_CLOCKS, CAP_PCIE,
)


class NVMLBackend(GpuBackend):
    """
    GPU metrics via pynvml (NVML C library, included with the NVIDIA driver).
    Zero external dependencies beyond the NVIDIA driver itself.
    """

    name = "nvml"
    capabilities = [CAP_UTIL, CAP_POWER, CAP_VRAM, CAP_TEMP, CAP_CLOCKS, CAP_PCIE]

    def __init__(self, gpu_index: int = 0):
        import pynvml
        self._pynvml    = pynvml
        self._gpu_index = gpu_index
        pynvml.nvmlInit()
        self._handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)

    def collect(self) -> Optional[GpuSample]:
        pynvml = self._pynvml
        h = self._handle
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            mem  = pynvml.nvmlDeviceGetMemoryInfo(h)
            power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0   # mW → W
            temp  = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            sm_clock  = pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_SM)
            mem_clock = pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM)

            tx = rx = 0.0
            try:
                tx = float(pynvml.nvmlDeviceGetPcieThroughput(h, pynvml.NVML_PCIE_UTIL_TX_BYTES))
                rx = float(pynvml.nvmlDeviceGetPcieThroughput(h, pynvml.NVML_PCIE_UTIL_RX_BYTES))
            except pynvml.NVMLError:
                pass

            return GpuSample(
                timestamp=time.time(),
                gpu_util_pct=float(util.gpu),
                hbm_used_mib=mem.used / (1024 ** 2),
                hbm_total_mib=mem.total / (1024 ** 2),
                power_w=power,
                temp_c=float(temp),
                sm_clock_mhz=float(sm_clock),
                mem_clock_mhz=float(mem_clock),
                pcie_tx_kbps=tx,
                pcie_rx_kbps=rx,
                # Profiling counters (sm_active, tensor, dram, nvlink) stay 0.0.
                # Use DCGMBackend on data-centre GPUs to get those.
            )
        except Exception:
            return None

    def get_metadata(self) -> dict:
        pynvml = self._pynvml
        h = self._handle
        gpu_name = driver = cuda_str = ""
        gpu_count = 1
        try:
            raw_name = pynvml.nvmlDeviceGetName(h)
            gpu_name = raw_name.decode() if isinstance(raw_name, bytes) else raw_name

            raw_driver = pynvml.nvmlSystemGetDriverVersion()
            driver = raw_driver.decode() if isinstance(raw_driver, bytes) else raw_driver

            cuda_int = pynvml.nvmlSystemGetCudaDriverVersion()
            # e.g. 12040 → "12.4"
            cuda_str = f"{cuda_int // 1000}.{(cuda_int % 1000) // 10}"

            gpu_count = pynvml.nvmlDeviceGetCount()
        except Exception:
            pass

        from .specs import get_gpu_specs
        specs = get_gpu_specs(gpu_name)

        return {
            "gpu_name":         gpu_name,
            "gpu_count":        gpu_count,
            "gpu_index":        self._gpu_index,
            "driver_version":   driver,
            "cuda_version":     cuda_str,
            "gpu_backend":      self.name,
            "gpu_capabilities": list(self.capabilities),
            "peak_hbm_bw_gbps": specs["peak_hbm_bw_gbps"],
            "peak_tflops_bf16": specs["peak_tflops_bf16"],
            "nvlink_bw_gbps":   specs["nvlink_bw_gbps"],
        }

    def __del__(self):
        try:
            self._pynvml.nvmlShutdown()
        except Exception:
            pass

    @classmethod
    def is_available(cls, **kwargs) -> bool:
        try:
            import pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            pynvml.nvmlShutdown()
            return count > 0
        except Exception:
            return False
