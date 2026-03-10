# GPU Telemetry Metrics - In-Depth Guide

This document explains all metrics collected by the Omniference telemetry system, how they're calculated, and what they mean in simple terms.

## Table of Contents

1. [Overview](#overview)
2. [Data Sources](#data-sources)
3. [Core Utilization Metrics](#core-utilization-metrics)
4. [Memory Metrics](#memory-metrics)
5. [Power & Energy Metrics](#power--energy-metrics)
6. [Temperature Metrics](#temperature-metrics)
7. [Clock Frequency Metrics](#clock-frequency-metrics)
8. [PCIe Metrics](#pcie-metrics)
9. [NVLink Metrics](#nvlink-metrics)
10. [Pipeline Activity Metrics (Profiling)](#pipeline-activity-metrics-profiling)
11. [Error & Health Metrics](#error--health-metrics)
12. [Application-Level Metrics](#application-level-metrics)
13. [How Metrics Are Calculated](#how-metrics-are-calculated)

---

## Overview

The Omniference telemetry system collects comprehensive GPU metrics from multiple sources to provide a complete picture of GPU performance, utilization, and health. Metrics are collected every 1-5 seconds (depending on profiling mode) and stored in TimescaleDB for historical analysis.

### Metric Collection Modes

- **Standard Mode**: Basic metrics available on all GPUs without special configuration
- **Profiling Mode**: Advanced metrics requiring DCGM profiling capabilities (enabled automatically when DCGM is detected)

---

## Data Sources

### 1. DCGM Exporter (Port 9400)
**What it is**: NVIDIA Data Center GPU Manager (DCGM) provides low-level hardware metrics directly from the GPU driver.

**Metrics provided**: 
- Core utilization (SM, GPU)
- Memory bandwidth (HBM)
- Pipeline activity (Tensor, FP64, FP32, FP16)
- Power, temperature, clocks
- PCIe and NVLink throughput
- ECC errors and health status

**How it works**: DCGM queries the NVIDIA driver for hardware counters and exposes them as Prometheus metrics.

### 2. NVIDIA-SMI Exporter (Port 9401)
**What it is**: A Python script that queries `nvidia-smi` command-line tool for complementary metrics.

**Metrics provided**:
- GPU and memory utilization percentages
- Memory usage (used, free, total)
- Temperature, power, clocks
- Fan speed, performance state
- PCIe link information
- Encoder/decoder utilization

**How it works**: Runs `nvidia-smi --query-gpu=...` commands periodically and formats results as Prometheus metrics.

### 3. Token Throughput Exporter (Port 9402)
**What it is**: Application-level metrics for LLM inference workloads.

**Metrics provided**:
- Token generation rate
- Request throughput
- Time-to-first-token (TTFT) latency
- Cost and efficiency metrics

**How it works**: Accepts POST requests from your workload application to report custom metrics.

---

## Core Utilization Metrics

### GPU Utilization (Standard)
- **Metric Name**: `gpu_utilization`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM `DCGM_FI_DEV_GPU_UTIL` or nvidia-smi
- **What it shows**: The percentage of time the GPU was actively executing compute kernels (not idle)
- **How it's calculated**: DCGM/nvidia-smi measures the ratio of time the GPU was busy vs. idle over the sampling period
- **What it means**: 
  - **0%**: GPU is completely idle
  - **50%**: GPU is active half the time
  - **100%**: GPU is fully utilized (always executing kernels)
- **When to use**: General workload activity indicator. Good for identifying if your workload is keeping the GPU busy.

### SM Utilization (Profiling)
- **Metric Name**: `sm_utilization`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM profiling `DCGM_FI_PROF_SM_ACTIVE` or device-level `DCGM_FI_DEV_SM_ACTIVE`
- **What it shows**: The percentage of Streaming Multiprocessors (SMs) that are actively executing instructions
- **How it's calculated**: 
  - Profiling mode: Counts active SMs over time, returns ratio (0-1), converted to percentage
  - Device-level: Direct percentage from DCGM
- **What it means**:
  - **0%**: No SMs are executing work
  - **50%**: Half of the SMs are active
  - **100%**: All SMs are executing instructions
- **When to use**: More detailed than GPU utilization. Helps identify if work is evenly distributed across SMs or if some SMs are idle.

### SM Occupancy (Profiling)
- **Metric Name**: `sm_occupancy`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM profiling `DCGM_FI_PROF_SM_OCCUPANCY`
- **What it shows**: Average percentage of active warps (groups of 32 threads) per SM
- **How it's calculated**: DCGM counts active warps across all SMs and calculates the average occupancy ratio (0-1), converted to percentage
- **What it means**:
  - **Low (<30%)**: SMs are underutilized - not enough threads to fill the GPU
  - **Medium (30-70%)**: Reasonable thread utilization
  - **High (>70%)**: SMs are well-filled with threads
- **When to use**: Identifies if your workload has enough parallelism. Low occupancy suggests you need more threads or larger batch sizes.

### Encoder Utilization
- **Metric Name**: `encoder_utilization`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM `DCGM_FI_DEV_ENC_UTIL`
- **What it shows**: How much the GPU's video encoder is being used
- **How it's calculated**: DCGM measures encoder activity time vs. idle time
- **What it means**: Useful for video encoding/streaming workloads. Most ML workloads will show 0%.

### Decoder Utilization
- **Metric Name**: `decoder_utilization`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM `DCGM_FI_DEV_DEC_UTIL`
- **What it shows**: How much the GPU's video decoder is being used
- **How it's calculated**: DCGM measures decoder activity time vs. idle time
- **What it means**: Useful for video decoding workloads. Most ML workloads will show 0%.

---

## Memory Metrics

### Memory Utilization
- **Metric Name**: `memory_utilization`
- **Unit**: Percentage (0-100%)
- **Source**: Calculated from `memory_used_mb / memory_total_mb * 100`
- **What it shows**: Percentage of GPU memory (VRAM) that is currently allocated
- **How it's calculated**: `(memory_used_mb / memory_total_mb) * 100`
- **What it means**:
  - **0%**: No memory allocated
  - **50%**: Half of VRAM is in use
  - **100%**: All VRAM is allocated (may cause out-of-memory errors)
- **When to use**: Monitor to avoid OOM errors. High utilization is normal for large models.

### Memory Used
- **Metric Name**: `memory_used_mb`
- **Unit**: Megabytes (MB)
- **Source**: DCGM `DCGM_FI_DEV_FB_USED` (converted from bytes) or nvidia-smi
- **What it shows**: Total amount of GPU memory currently allocated
- **How it's calculated**: DCGM reports bytes, divided by 1,048,576 to get MB
- **What it means**: Actual memory footprint of your workload. Includes model weights, activations, and CUDA allocations.

### Memory Total
- **Metric Name**: `memory_total_mb`
- **Unit**: Megabytes (MB)
- **Source**: DCGM `DCGM_FI_DEV_FB_TOTAL` (converted from bytes) or nvidia-smi
- **What it shows**: Total GPU memory capacity
- **How it's calculated**: DCGM reports bytes, divided by 1,048,576 to get MB
- **What it means**: Physical memory size of the GPU (e.g., 40GB for A100, 80GB for H100).

### Memory Free
- **Metric Name**: `memory_free_mb`
- **Unit**: Megabytes (MB)
- **Source**: DCGM `DCGM_FI_DEV_FB_FREE` (converted from bytes) or nvidia-smi
- **What it shows**: Unallocated GPU memory available for use
- **How it's calculated**: `memory_total_mb - memory_used_mb`
- **What it means**: How much memory is available for new allocations.

### HBM Utilization (Profiling)
- **Metric Name**: `hbm_utilization`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM profiling `DCGM_FI_PROF_DRAM_ACTIVE` or device-level `DCGM_FI_DEV_MEM_COPY_UTIL`
- **What it shows**: Memory bandwidth utilization - how much of the GPU's memory bandwidth is being used
- **How it's calculated**:
  - Profiling: Ratio of time DRAM is active (0-1), converted to percentage
  - Device-level: Direct percentage from DCGM
- **What it means**:
  - **Low (<30%)**: Memory bandwidth is not a bottleneck
  - **High (>70%)**: Memory bandwidth is heavily utilized - may indicate memory-bound workload
- **When to use**: Identifies memory-bound workloads. High HBM utilization with low SM utilization suggests memory bandwidth is the bottleneck.

---

## Power & Energy Metrics

### Power Draw
- **Metric Name**: `power_draw_watts`
- **Unit**: Watts (W)
- **Source**: DCGM `DCGM_FI_DEV_POWER_USAGE` or nvidia-smi
- **What it shows**: Current power consumption of the GPU
- **How it's calculated**: Direct reading from GPU power sensors
- **What it means**:
  - **Low**: GPU is idle or under light load
  - **Medium**: Moderate workload
  - **High (near limit)**: GPU is under heavy load
- **When to use**: Monitor power consumption for cost tracking and thermal management. Power draw should be stable during steady-state workloads.

### Power Limit
- **Metric Name**: `power_limit_watts`
- **Unit**: Watts (W)
- **Source**: DCGM `DCGM_FI_DEV_POWER_LIMIT` or nvidia-smi
- **What it shows**: Maximum power the GPU is allowed to draw
- **How it's calculated**: Configuration value from GPU settings
- **What it means**: The power cap set for the GPU. If power draw is near the limit, the GPU may throttle to stay within the limit.
- **When to use**: Compare against power draw to see if you're hitting power limits (which can cause throttling).

### Total Energy Consumption
- **Metric Name**: `total_energy_joules`
- **Unit**: Joules (J), also displayed as Watt-hours (Wh) in UI
- **Source**: DCGM `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION`
- **What it shows**: Cumulative energy consumed since GPU boot or counter reset
- **How it's calculated**: DCGM maintains a running counter of energy consumption
- **What it means**: Total energy used over time. Convert to kWh for cost calculations: `(joules / 3,600,000) * cost_per_kwh`
- **When to use**: Track energy costs over long-running workloads. Useful for cost optimization.

---

## Temperature Metrics

### GPU Temperature
- **Metric Name**: `temperature_celsius`
- **Unit**: Celsius (°C)
- **Source**: DCGM `DCGM_FI_DEV_GPU_TEMP` or nvidia-smi
- **What it shows**: Current temperature of the GPU core
- **How it's calculated**: Direct reading from GPU temperature sensors
- **What it means**:
  - **<60°C**: Cool, GPU is idle or under light load
  - **60-80°C**: Normal operating temperature under load
  - **80-90°C**: Warm, but still safe
  - **>90°C**: Hot - may trigger thermal throttling
- **When to use**: Monitor to prevent thermal throttling. High temperatures can reduce performance.

### Memory Temperature
- **Metric Name**: `memory_temperature_celsius`
- **Unit**: Celsius (°C)
- **Source**: DCGM `DCGM_FI_DEV_MEMORY_TEMP`
- **What it shows**: Temperature of GPU memory (HBM)
- **How it's calculated**: Direct reading from memory temperature sensors
- **What it means**: Memory can get hot during high-bandwidth operations. Similar ranges as GPU temperature.
- **When to use**: Monitor memory temperature during memory-intensive workloads.

### Slowdown Temperature
- **Metric Name**: `slowdown_temperature_celsius`
- **Unit**: Celsius (°C)
- **Source**: DCGM `DCGM_FI_DEV_SLOWDOWN_TEMP`
- **What it shows**: Temperature threshold at which the GPU begins to throttle performance
- **How it's calculated**: Configuration value from GPU thermal management settings
- **What it means**: If GPU temperature exceeds this value, the GPU will reduce clock speeds to prevent overheating.
- **When to use**: Compare against current temperature to see how close you are to thermal throttling.

---

## Clock Frequency Metrics

### SM Clock
- **Metric Name**: `sm_clock_mhz`
- **Unit**: Megahertz (MHz)
- **Source**: DCGM `DCGM_FI_DEV_SM_CLOCK` or nvidia-smi
- **What it shows**: Current clock frequency of the Streaming Multiprocessors (compute units)
- **How it's calculated**: Direct reading from GPU clock sensors
- **What it means**: Higher clock = faster computation. Clock speeds can be reduced due to:
  - Thermal throttling (too hot)
  - Power throttling (hitting power limit)
  - Performance state (P-state) changes
- **When to use**: Correlate with temperature and power to understand throttling behavior.

### Memory Clock
- **Metric Name**: `memory_clock_mhz`
- **Unit**: Megahertz (MHz)
- **Source**: DCGM `DCGM_FI_DEV_MEM_CLOCK` or nvidia-smi
- **What it shows**: Current clock frequency of GPU memory (HBM)
- **How it's calculated**: Direct reading from memory clock sensors
- **What it means**: Higher clock = faster memory bandwidth. Memory clock can also be throttled for thermal/power reasons.
- **When to use**: Monitor during memory-intensive workloads. Low memory clock can indicate throttling.

---

## PCIe Metrics

### PCIe TX Throughput
- **Metric Name**: `pcie_tx_mb_per_sec`
- **Unit**: Megabytes per second (MB/s)
- **Source**: DCGM profiling `DCGM_FI_PROF_PCIE_TX_BYTES` (preferred) or device-level `DCGM_FI_DEV_PCIE_TX_THROUGHPUT`
- **What it shows**: Data transfer rate from GPU to CPU/host memory
- **How it's calculated**: 
  - Profiling: Counter of bytes transferred, Prometheus calculates rate (bytes/sec), converted to MB/s
  - Device-level: Direct throughput measurement
- **What it means**: How fast data is being sent from GPU to host. High values indicate GPU is sending results back to CPU.
- **When to use**: Monitor data transfer bottlenecks. PCIe bandwidth is limited compared to GPU memory bandwidth.

### PCIe RX Throughput
- **Metric Name**: `pcie_rx_mb_per_sec`
- **Unit**: Megabytes per second (MB/s)
- **Source**: DCGM profiling `DCGM_FI_PROF_PCIE_RX_BYTES` (preferred) or device-level `DCGM_FI_DEV_PCIE_RX_THROUGHPUT`
- **What it shows**: Data transfer rate from CPU/host memory to GPU
- **How it's calculated**: Same as TX, but for incoming data
- **What it means**: How fast data is being sent from host to GPU. High values indicate data is being loaded onto GPU.
- **When to use**: Monitor data loading bottlenecks. If RX is high and GPU utilization is low, data loading may be the bottleneck.

### PCIe Replay Errors
- **Metric Name**: `pcie_replay_errors`
- **Unit**: Count (cumulative)
- **Source**: DCGM `DCGM_FI_DEV_PCIE_REPLAY_COUNTER`
- **What it shows**: Number of PCIe link errors that required retransmission
- **How it's calculated**: Cumulative counter of PCIe replay events
- **What it means**: 
  - **0 errors**: PCIe link is healthy
  - **Increasing errors**: PCIe link has issues (cable, slot, or electrical problems)
- **When to use**: Monitor for hardware issues. Increasing replay errors indicate PCIe problems.

---

## NVLink Metrics

### NVLink TX Throughput (Profiling)
- **Metric Name**: `nvlink_tx_mb_per_sec`
- **Unit**: Megabytes per second (MB/s)
- **Source**: DCGM profiling `DCGM_FI_PROF_NVLINK_TX_BYTES`
- **What it shows**: Data transfer rate from this GPU to other GPUs via NVLink
- **How it's calculated**: Counter of bytes transferred, Prometheus calculates rate, converted to MB/s
- **What it means**: Inter-GPU communication bandwidth. High values indicate multi-GPU workloads are actively communicating.
- **When to use**: Monitor multi-GPU workloads. High NVLink usage is normal for distributed training.

### NVLink RX Throughput (Profiling)
- **Metric Name**: `nvlink_rx_mb_per_sec`
- **Unit**: Megabytes per second (MB/s)
- **Source**: DCGM profiling `DCGM_FI_PROF_NVLINK_RX_BYTES`
- **What it shows**: Data transfer rate from other GPUs to this GPU via NVLink
- **How it's calculated**: Same as TX, but for incoming data
- **What it means**: How much data this GPU is receiving from other GPUs.
- **When to use**: Monitor multi-GPU communication patterns.

### NVLink Bandwidth Total
- **Metric Name**: `nvlink_bandwidth_total`
- **Unit**: Megabytes per second (MB/s)
- **Source**: DCGM `DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL`
- **What it shows**: Total NVLink bandwidth capacity for this GPU
- **How it's calculated**: Configuration value based on NVLink version and number of links
- **What it means**: Maximum theoretical NVLink bandwidth. Compare against TX/RX to see utilization.

### NVLink Replay Errors
- **Metric Name**: `nvlink_replay_errors`
- **Unit**: Count (cumulative)
- **Source**: DCGM `DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL`
- **What it shows**: Number of NVLink errors that required retransmission
- **How it's calculated**: Cumulative counter
- **What it means**: NVLink link health. Increasing errors indicate hardware issues.

### NVLink Recovery Errors
- **Metric Name**: `nvlink_recovery_errors`
- **Unit**: Count (cumulative)
- **Source**: DCGM `DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL`
- **What it shows**: Number of NVLink errors that required link recovery
- **How it's calculated**: Cumulative counter
- **What it means**: More serious NVLink errors. Increasing values indicate significant link problems.

### NVLink CRC Errors
- **Metric Name**: `nvlink_crc_errors`
- **Unit**: Count (cumulative)
- **Source**: DCGM `DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL`
- **What it shows**: Number of CRC (checksum) errors detected on NVLink
- **How it's calculated**: Cumulative counter
- **What it means**: Data corruption detected on NVLink. May indicate electrical issues.

---

## Pipeline Activity Metrics (Profiling)

These metrics show which specific compute pipelines are active. They require profiling mode.

### Tensor Core Activity
- **Metric Name**: `tensor_active`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM profiling `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE`
- **What it shows**: Percentage of time Tensor Cores are executing operations
- **How it's calculated**: Ratio of time Tensor Cores are active (0-1), converted to percentage
- **What it means**:
  - **High (>50%)**: Workload is using Tensor Cores (good for mixed-precision training/inference)
  - **Low (<10%)**: Workload is not using Tensor Cores (may be using CUDA cores instead)
- **When to use**: Verify that your workload is utilizing Tensor Cores for optimal performance.

### FP64 Active
- **Metric Name**: `fp64_active`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM profiling `DCGM_FI_PROF_PIPE_FP64_ACTIVE`
- **What it shows**: Percentage of time FP64 (double-precision) units are active
- **How it's calculated**: Ratio of time FP64 pipeline is active (0-1), converted to percentage
- **What it means**: 
  - **High**: Workload uses double-precision math (common in scientific computing)
  - **Low/Zero**: Workload uses single or half-precision (common in ML)
- **When to use**: Identify precision requirements. FP64 is slower but more accurate.

### FP32 Active
- **Metric Name**: `fp32_active`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM profiling `DCGM_FI_PROF_PIPE_FP32_ACTIVE`
- **What it shows**: Percentage of time FP32 (single-precision) units are active
- **How it's calculated**: Ratio of time FP32 pipeline is active (0-1), converted to percentage
- **What it means**: Standard precision for most ML workloads. High values are normal for FP32 training.

### FP16 Active
- **Metric Name**: `fp16_active`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM profiling `DCGM_FI_PROF_PIPE_FP16_ACTIVE`
- **What it shows**: Percentage of time FP16/BF16 (half-precision) units are active
- **How it's calculated**: Ratio of time FP16 pipeline is active (0-1), converted to percentage
- **What it means**: 
  - **High**: Workload uses mixed-precision (common in modern ML training)
  - **Low**: Workload primarily uses FP32
- **When to use**: Verify mixed-precision training is working correctly.

### Graphics Engine Activity
- **Metric Name**: `gr_engine_active`
- **Unit**: Percentage (0-100%)
- **Source**: DCGM profiling `DCGM_FI_PROF_GR_ENGINE_ACTIVE`
- **What it shows**: Percentage of time the graphics engine is active
- **How it's calculated**: Ratio of time graphics engine is active (0-1), converted to percentage
- **What it means**: 
  - **High**: GPU is being used for graphics/visualization
  - **Low/Zero**: GPU is being used for compute only (typical for ML workloads)
- **When to use**: Identify if graphics and compute workloads are running simultaneously.

---

## Error & Health Metrics

### ECC Single-Bit Errors (SBE)
- **Metric Name**: `ecc_sbe_errors`
- **Unit**: Count (cumulative)
- **Source**: DCGM `DCGM_FI_DEV_ECC_SBE_VOL_TOTAL`
- **What it shows**: Number of single-bit memory errors corrected by ECC
- **How it's calculated**: Cumulative counter of corrected errors
- **What it means**: 
  - **0 errors**: Memory is healthy
  - **Low errors (<100)**: Normal - ECC is working as designed
  - **High/Increasing errors**: Memory may be degrading
- **When to use**: Monitor memory health. Increasing SBE errors may indicate failing memory.

### ECC Double-Bit Errors (DBE)
- **Metric Name**: `ecc_dbe_errors`
- **Unit**: Count (cumulative)
- **Source**: DCGM `DCGM_FI_DEV_ECC_DBE_VOL_TOTAL`
- **What it shows**: Number of uncorrectable double-bit memory errors
- **How it's calculated**: Cumulative counter
- **What it means**: 
  - **0 errors**: Good - no uncorrectable errors
  - **Any errors**: Serious - memory corruption detected, data may be corrupted
- **When to use**: Critical health metric. Any DBE errors indicate memory problems.

### XID Errors
- **Metric Name**: `xid_errors`
- **Unit**: Count (cumulative)
- **Source**: DCGM `DCGM_FI_DEV_XID_ERRORS`
- **What it shows**: Number of XID (eXtended IDentifier) errors from the GPU driver
- **How it's calculated**: Cumulative counter of driver-reported errors
- **What it means**: GPU driver errors. Common causes:
  - Out of memory
  - Driver crashes
  - Hardware faults
- **When to use**: Monitor for driver/hardware issues. XID errors often indicate serious problems.

### Throttle Reasons
- **Metric Name**: `throttle_reasons`
- **Unit**: Bitmask (integer)
- **Source**: DCGM `DCGM_FI_DEV_CLOCK_THROTTLE_REASONS`
- **What it shows**: Reasons why GPU clocks are being throttled
- **How it's calculated**: Bitmask where each bit represents a throttle reason:
  - Bit 0: Power limit
  - Bit 1: Thermal limit
  - Bit 2: Reliability voltage limit
  - Bit 3: Sync boost limit
- **What it means**: 
  - **0**: No throttling
  - **Non-zero**: GPU is throttling for the indicated reasons
- **When to use**: Identify why performance is reduced. Helps diagnose power/thermal issues.

---

## Application-Level Metrics

These metrics are reported by your workload application, not the GPU hardware.

### Tokens Per Second
- **Metric Name**: `tokens_per_second`
- **Unit**: Tokens/second
- **Source**: Token exporter (application reports via POST to `/update`)
- **What it shows**: Rate at which tokens are being generated by an LLM
- **How it's calculated**: Application measures tokens generated over time
- **What it means**: 
  - **High**: Model is generating tokens quickly
  - **Low**: Model is generating tokens slowly (may indicate bottleneck)
- **When to use**: Measure inference throughput for LLM workloads.

### Requests Per Second
- **Metric Name**: `requests_per_second`
- **Unit**: Requests/second
- **Source**: Token exporter (application reports)
- **What it shows**: Rate at which inference requests are being processed
- **How it's calculated**: Application counts requests processed over time
- **What it means**: Request throughput. Higher is better for serving workloads.
- **When to use**: Measure request throughput for serving workloads.

### Time to First Token (P50)
- **Metric Name**: `ttft_p50_ms`
- **Unit**: Milliseconds (ms)
- **Source**: Token exporter (application reports)
- **What it shows**: Median (50th percentile) latency from request start to first token
- **How it's calculated**: Application measures latency for each request, calculates 50th percentile
- **What it means**: 
  - **Low (<100ms)**: Fast response time
  - **High (>1000ms)**: Slow response time
- **When to use**: Measure user-perceived latency for interactive applications.

### Time to First Token (P95)
- **Metric Name**: `ttft_p95_ms`
- **Unit**: Milliseconds (ms)
- **Source**: Token exporter (application reports)
- **What it shows**: 95th percentile latency from request start to first token
- **How it's calculated**: Application calculates 95th percentile of TTFT measurements
- **What it means**: Worst-case latency for 95% of requests. Higher than P50 indicates latency variance.
- **When to use**: Measure tail latency for SLA compliance.

### Performance Per Watt
- **Metric Name**: `cost_per_watt` (also called `performance_per_watt`)
- **Unit**: Tokens/second per Watt
- **Source**: Token exporter (application calculates)
- **What it shows**: Efficiency metric: tokens generated per second per watt of power consumed
- **How it's calculated**: `tokens_per_second / power_draw_watts`
- **What it means**: 
  - **High**: Efficient - generating many tokens per watt
  - **Low**: Inefficient - using lots of power for few tokens
- **When to use**: Optimize for energy efficiency and cost.

---

## How Metrics Are Calculated

### Data Flow

1. **Collection**: Exporters (DCGM, nvidia-smi, token) collect metrics and expose them as Prometheus metrics
2. **Scraping**: Prometheus scrapes exporters every 1-5 seconds (configurable)
3. **Remote Write**: Prometheus forwards metrics to backend via remote_write API
4. **Parsing**: Backend parses Prometheus remote_write protobuf format
5. **Transformation**: Metrics are transformed and normalized (e.g., ratios to percentages, bytes to MB)
6. **Storage**: Metrics are stored in TimescaleDB as time-series data
7. **Query**: Frontend queries metrics via API and displays them in charts

### Metric Transformations

Many metrics require transformation from raw DCGM values:

- **Ratios to Percentages**: Profiling metrics return ratios (0-1), multiplied by 100 to get percentages
  - Example: `DCGM_FI_PROF_SM_ACTIVE = 0.75` → `sm_utilization = 75%`

- **Bytes to Megabytes**: Memory and bandwidth metrics are in bytes, divided by 1,048,576
  - Example: `DCGM_FI_DEV_FB_USED = 21474836480` bytes → `memory_used_mb = 20480` MB

- **Counters to Rates**: Some metrics are cumulative counters, Prometheus calculates rates
  - Example: `DCGM_FI_PROF_PCIE_TX_BYTES` is a counter, Prometheus calculates `rate()` to get MB/s

- **Joules to Watt-hours**: Energy metrics are in Joules, divided by 3600 for Watt-hours
  - Example: `total_energy_joules = 3600000` → `energy_wh = 1000` Wh

### Sampling Rates

- **Standard Mode**: Metrics collected every 5 seconds
- **Profiling Mode**: Metrics collected every 1 second (more frequent for detailed analysis)

### Metric Availability

- **Standard Metrics**: Available on all GPUs without special configuration
- **Profiling Metrics**: Require DCGM with profiling mode enabled (automatic when DCGM is detected)
- **NVLink Metrics**: Only available on multi-GPU systems with NVLink connections
- **ECC Metrics**: Only available on GPUs with ECC support (datacenter GPUs)

---

## Summary

The Omniference telemetry system provides comprehensive GPU monitoring through:

- **3 Data Sources**: DCGM (hardware), nvidia-smi (complementary), Token exporter (application)
- **50+ Metrics**: Covering utilization, memory, power, temperature, clocks, I/O, errors, and application performance
- **2 Collection Modes**: Standard (basic) and Profiling (advanced)
- **Real-time & Historical**: Metrics collected every 1-5 seconds, stored in TimescaleDB for historical analysis

Use these metrics to:
- **Identify Bottlenecks**: Low SM utilization + high HBM utilization = memory-bound workload
- **Optimize Performance**: High SM occupancy = good parallelism; low = need more threads
- **Monitor Health**: ECC errors, temperature, power limits indicate hardware issues
- **Track Efficiency**: Performance per watt, energy consumption for cost optimization
- **Debug Issues**: Throttle reasons, XID errors, replay errors help diagnose problems

For more information, see:
- [Telemetry Stack Documentation](./telemetry-stack.md)
- [Telemetry Usage Guide](../backend/telemetry/TELEMETRY_USAGE.md)
