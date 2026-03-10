#!/usr/bin/env python3
"""
dcgm_exporter_fallback.py — Lightweight GPU metrics exporter using pynvml.

Exposes Prometheus metrics on :9400 as a fallback when the Docker-based
DCGM Exporter isn't available. Polls nvidia-smi/NVML at 2-second intervals.
"""

import time
import threading
from prometheus_client import start_http_server, Gauge, Info
import pynvml

# ── Prometheus Gauges ─────────────────────────────────────────────────────────

GPU_INFO = Info("gpu", "GPU device information")

METRICS = {
    "gpu_utilization_pct": Gauge(
        "dcgm_fi_dev_gpu_util", "GPU utilization (%)", ["gpu"]
    ),
    "mem_utilization_pct": Gauge(
        "dcgm_fi_dev_mem_copy_util", "Memory controller utilization (%)", ["gpu"]
    ),
    "fb_used_mib": Gauge(
        "dcgm_fi_dev_fb_used", "Used framebuffer memory (MiB)", ["gpu"]
    ),
    "fb_free_mib": Gauge(
        "dcgm_fi_dev_fb_free", "Free framebuffer memory (MiB)", ["gpu"]
    ),
    "sm_clock_mhz": Gauge(
        "dcgm_fi_dev_sm_clock", "SM clock frequency (MHz)", ["gpu"]
    ),
    "mem_clock_mhz": Gauge(
        "dcgm_fi_dev_mem_clock", "Memory clock frequency (MHz)", ["gpu"]
    ),
    "power_w": Gauge(
        "dcgm_fi_dev_power_usage", "Power draw (W)", ["gpu"]
    ),
    "temperature_c": Gauge(
        "dcgm_fi_dev_gpu_temp", "GPU temperature (C)", ["gpu"]
    ),
    "pcie_tx_kbps": Gauge(
        "dcgm_fi_dev_pcie_tx_throughput", "PCIe TX throughput (KB/s)", ["gpu"]
    ),
    "pcie_rx_kbps": Gauge(
        "dcgm_fi_dev_pcie_rx_throughput", "PCIe RX throughput (KB/s)", ["gpu"]
    ),
    "fan_speed_pct": Gauge(
        "gpu_fan_speed_pct", "Fan speed (%)", ["gpu"]
    ),
}


def collect_metrics():
    """Poll NVML and update Prometheus gauges."""
    pynvml.nvmlInit()
    device_count = pynvml.nvmlDeviceGetCount()

    for i in range(device_count):
        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
        gpu_label = str(i)

        # Utilization
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        METRICS["gpu_utilization_pct"].labels(gpu=gpu_label).set(util.gpu)
        METRICS["mem_utilization_pct"].labels(gpu=gpu_label).set(util.memory)

        # Memory
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        METRICS["fb_used_mib"].labels(gpu=gpu_label).set(mem.used / (1024 * 1024))
        METRICS["fb_free_mib"].labels(gpu=gpu_label).set(mem.free / (1024 * 1024))

        # Clocks
        sm_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM)
        mem_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
        METRICS["sm_clock_mhz"].labels(gpu=gpu_label).set(sm_clock)
        METRICS["mem_clock_mhz"].labels(gpu=gpu_label).set(mem_clock)

        # Power
        power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW → W
        METRICS["power_w"].labels(gpu=gpu_label).set(power)

        # Temperature
        temp = pynvml.nvmlDeviceGetTemperature(
            handle, pynvml.NVML_TEMPERATURE_GPU
        )
        METRICS["temperature_c"].labels(gpu=gpu_label).set(temp)

        # PCIe throughput
        try:
            tx = pynvml.nvmlDeviceGetPcieThroughput(
                handle, pynvml.NVML_PCIE_UTIL_TX_BYTES
            )
            rx = pynvml.nvmlDeviceGetPcieThroughput(
                handle, pynvml.NVML_PCIE_UTIL_RX_BYTES
            )
            METRICS["pcie_tx_kbps"].labels(gpu=gpu_label).set(tx)
            METRICS["pcie_rx_kbps"].labels(gpu=gpu_label).set(rx)
        except pynvml.NVMLError:
            pass

        # Fan
        try:
            fan = pynvml.nvmlDeviceGetFanSpeed(handle)
            METRICS["fan_speed_pct"].labels(gpu=gpu_label).set(fan)
        except pynvml.NVMLError:
            pass

        # GPU info (set once)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode()
        GPU_INFO.info({"device": gpu_label, "model": name})

    pynvml.nvmlShutdown()


def polling_loop(interval: float = 2.0):
    """Continuously collect metrics at the given interval."""
    while True:
        try:
            collect_metrics()
        except Exception as e:
            print(f"[WARN] Metric collection error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    print("[DCGM Fallback] Starting Prometheus exporter on :9400")
    start_http_server(9400)

    poll_thread = threading.Thread(target=polling_loop, daemon=True)
    poll_thread.start()

    print("[DCGM Fallback] Collecting GPU metrics every 2s. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[DCGM Fallback] Shutting down.")
