# GPU Instance Runbook

Step-by-step guide to collecting telemetry on any GPU instance and getting a result JSON.

---

## Table of Contents

0. [Automated Setup (recommended)](#0-automated-setup-recommended)
1. [Prerequisites](#1-prerequisites)
2. [Install Python Dependencies](#2-install-python-dependencies)
3. [Set Up DCGM Exporter (Data-Centre GPUs)](#3-set-up-dcgm-exporter-data-centre-gpus)
4. [Start vLLM](#4-start-vllm)
5. [Run Telemetry](#5-run-telemetry)
6. [Retrieve the Result](#6-retrieve-the-result)
7. [GPU-Specific Notes](#7-gpu-specific-notes)
8. [CLI Reference](#8-cli-reference)
9. [Troubleshooting](#9-troubleshooting)

---

## 0. Automated Setup (recommended)

`setup.py` handles steps 1–5 automatically and prints a summary of what is working.

```bash
cd /path/to/Telemetry/scripts

# Check everything, start DCGM if possible
python setup.py

# Also run a 3-request smoke test to verify end-to-end
python setup.py --smoke-test

# Custom server / DCGM address
python setup.py --server http://localhost:8000 --dcgm-url http://localhost:9400/metrics

# Skip DCGM (no Docker available)
python setup.py --skip-dcgm

# Full option reference
python setup.py --help
```

The script will tell you exactly what is ready and what still needs attention.
If everything passes, it prints the exact command to run.

---

## 1. Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Python | 3.9+ | On the GPU instance |
| NVIDIA driver | 520+ | `nvidia-smi` must work |
| CUDA toolkit | 11.8+ | Must match vLLM build |
| vLLM | 0.4+ | Running on the GPU instance |
| Docker | any | Only for DCGM (optional, data-centre GPUs) |

Check that your GPU is visible:
```bash
nvidia-smi
```

---

## 2. Install Python Dependencies

SSH into the GPU instance, then:

```bash
pip install pynvml requests aiohttp
```

That is the minimum. If you also want `rich` for nicer live output in the older `04_benchmark.py` script:

```bash
pip install rich
```

No other dependencies are needed. The telemetry package has no third-party imports beyond the above.

---

## 3. Set Up DCGM Exporter (Data-Centre GPUs)

**Only needed for:** H100, A100, L40S, L40, A40, A30, V100.
**Skip for:** consumer GeForce / Quadro GPUs — NVML covers those automatically.

DCGM gives you the deep profiling counters: SM Active %, SM Occupancy %, Tensor Core Active %, DRAM Active %, NVLink bandwidth.

### Option A — Docker (easiest)

```bash
docker run -d \
  --name dcgm-exporter \
  --gpus all \
  --rm \
  -p 9400:9400 \
  nvcr.io/nvidia/k8s/dcgm-exporter:latest
```

Verify it is working:
```bash
curl -s http://localhost:9400/metrics | grep DCGM_FI_DEV_GPU_UTIL
```

You should see output like:
```
DCGM_FI_DEV_GPU_UTIL{gpu="0",modelName="NVIDIA H100 80GB HBM3",...} 0
```

### Option B — Native binary

```bash
# Install dcgm
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
dpkg -i cuda-keyring_1.1-1_all.deb
apt-get update && apt-get install -y datacenter-gpu-manager

# Start the DCGM daemon
nv-hostengine

# Run the exporter
dcgmi discovery -l   # list GPUs
dcgm-exporter &      # starts on :9400 by default
```

### Option C — Skip DCGM

If you cannot run DCGM, the tool automatically falls back to NVML. You lose the profiling counters (SM Active, Tensor Core, DRAM BW, NVLink) but still get GPU util, power, VRAM, temperature, and PCIe bandwidth.

---

## 4. Start vLLM

### With kernel profiling (recommended for full metrics)

```bash
nohup vllm serve <model-name-or-path> \
  --host 0.0.0.0 \
  --port 8000 \
  --enforce-eager \
  --profiler-config '{
    "profiler": "torch",
    "torch_profiler_dir": "/tmp/vllm_traces",
    "torch_profiler_with_flops": true,
    "torch_profiler_use_gzip": false
  }' \
  > vllm.log 2>&1 &

tail -f vllm.log   # wait until you see "Application startup complete"
```

Replace `<model-name-or-path>` with the HuggingFace model ID or local path, for example:
- `Qwen/Qwen2.5-3B-Instruct`
- `meta-llama/Llama-3.1-8B-Instruct`
- `/scratch/Qwen2.5-3B-Instruct`

### Without kernel profiling (faster startup, fewer metrics)

```bash
nohup vllm serve <model> \
  --host 0.0.0.0 \
  --port 8000 \
  --enforce-eager \
  > vllm.log 2>&1 &
```

Use `--no-kernel` when running `telemetry_run.py` in this case.

### Verify vLLM is ready

```bash
curl -s http://localhost:8000/v1/models | python3 -m json.tool
```

Should show the model name.

---

## 5. Run Telemetry

```bash
cd /path/to/Telemetry/scripts

python telemetry_run.py \
  --title "H100 Qwen2.5-3B saturated" \
  --output /tmp/my_run.json
```

That is it for a standard run. The script will:
1. Auto-detect GPU backend (DCGM if available, else NVML)
2. Auto-detect the model from vLLM `/v1/models`
3. Send 50 concurrent inference requests
4. Poll GPU metrics every 0.5 seconds
5. Profile kernels from request 10 to request 30
6. Print a summary report to stdout
7. Save the full result to the output path

### Common run variants

**More requests, higher concurrency (saturation test):**
```bash
python telemetry_run.py \
  --num-requests 100 \
  --concurrency 16 \
  --max-tokens 512 \
  --title "Saturation run" \
  --output /tmp/saturated.json
```

**Skip kernel profiling (faster, no profiler-config needed):**
```bash
python telemetry_run.py --no-kernel --output /tmp/quick.json
```

**Skip GPU monitoring entirely (workload metrics only):**
```bash
python telemetry_run.py --no-gpu --output /tmp/workload_only.json
```

**Custom vLLM server address:**
```bash
python telemetry_run.py \
  --server http://localhost:8000 \
  --model Qwen/Qwen2.5-3B-Instruct \
  --output /tmp/run.json
```

**Custom DCGM exporter URL (non-default port):**
```bash
python telemetry_run.py --dcgm-url http://localhost:9401/metrics
```

**Faster GPU polling (0.1s instead of 0.5s):**
```bash
python telemetry_run.py --gpu-poll 0.1
```

---

## 6. Retrieve the Result

Copy the JSON file back to your machine for the dashboard:

```bash
# From your local machine (Windows PowerShell):
scp user@gpu-host:/tmp/my_run.json E:\Telemetry\Runs\my_run.json

# From your local machine (bash/macOS/Linux):
scp user@gpu-host:/tmp/my_run.json ~/Telemetry/Runs/my_run.json
```

Then open the dashboard to analyse it:
```powershell
cd E:\Telemetry\claude-chat
npm run server   # terminal 1
npm run dev      # terminal 2
```

---

## 7. GPU-Specific Notes

### H100 (SXM or PCIe)

- DCGM is strongly recommended — provides SM Active, Tensor Core, DRAM Active, NVLink
- Peak BF16 TFLOPS: **989 TF** (SXM), **756 TF** (PCIe)
- Peak HBM3 BW: **3,350 GB/s** (SXM), **2,000 GB/s** (PCIe)
- NVLink BW: **900 GB/s** (SXM only)
- Expected MFU for well-optimised LLM inference: 40–60%
- Expected HBM BW utilization during decode (memory-bound): 60–90%

```bash
# Confirm DCGM sees H100 profiling counters
curl -s http://localhost:9400/metrics | grep DCGM_FI_PROF_SM_ACTIVE
```

### A100 (SXM4 80GB or 40GB)

- Same DCGM setup as H100
- Peak BF16 TFLOPS: **312 TF**
- Peak HBM2e BW: **2,000 GB/s** (80GB), **1,555 GB/s** (40GB)
- NVLink BW: **600 GB/s**

### L40S

- DCGM works but NVLink counters will be 0 (no NVLink on L40S)
- Peak BF16 TFLOPS: **362 TF**
- Peak GDDR6 BW: **864 GB/s**
- Tip: L40S is compute-heavy relative to HBM BW — decode is typically memory-bound

### V100 (SXM2)

- DCGM works; uses FP16 (not BF16) — `peak_tflops_bf16` shows FP16 value (112 TF)
- Peak HBM2 BW: **900 GB/s**
- NVLink BW: **300 GB/s**

### Consumer NVIDIA (RTX 3090, 4090, etc.)

- DCGM is **not** available (no data-centre driver)
- Tool automatically uses NVML — covers util, power, VRAM, temperature, PCIe, clocks
- SM Active / Tensor Core / DRAM Active will be **0.0** in the result (expected)
- Kernel profiling still works if vLLM is started with `--profiler-config`

### AMD (MI300X, MI250X) — future

- Not yet implemented — will use ROCm backend when available
- Kernel profiling will work if torch.profiler supports the device

---

## 8. CLI Reference

```
python telemetry_run.py [OPTIONS]

Server / model:
  --server URL          vLLM server URL              [default: http://localhost:8000]
  --model NAME          Model name (auto-detected if empty)
  --num-requests N      Number of inference requests [default: 50]
  --max-tokens N        Max output tokens per request [default: 200]
  --concurrency N       Max concurrent requests      [default: 4]

GPU backend:
  --dcgm-url URL        DCGM exporter URL            [default: http://localhost:9400/metrics]
  --gpu-index N         GPU index for NVML           [default: 0]
  --gpu-poll S          GPU sampling interval (s)    [default: 0.5]
  --no-gpu              Disable GPU monitoring entirely

Kernel profiling:
  --no-kernel           Skip kernel profiling
  --trace-dir PATH      vLLM torch profiler trace dir [default: /tmp/vllm_traces]
  --kernel-start N      Request index to start kernel profiling [default: 10]
  --kernel-stop N       Request index to stop kernel profiling  [default: 30]

Output:
  --output PATH         JSON output path (auto-generated if empty)
  --title TEXT          Run title in the JSON and report
  --quiet               Suppress per-request progress output
```

---

## 9. Troubleshooting

### "Cannot reach http://localhost:8000/v1/models"

vLLM is not running or not yet ready.

```bash
# Check if vLLM started
tail -50 vllm.log
# Check it is listening
curl http://localhost:8000/v1/models
# If port is different, pass --server
python telemetry_run.py --server http://localhost:8001
```

### "GPU backend unavailable"

`pynvml` is not installed or no NVIDIA GPU found.

```bash
pip install pynvml
nvidia-smi   # must succeed
```

### DCGM exporter reachable but profiling counters are 0

Two causes:

1. **Consumer GPU** — DCGM connects but the profiling counters are not available. The tool automatically falls back to NVML. This is expected behaviour.

2. **DCGM not configured to export profiling metrics** — Check the exporter's counter config. The default `dcgm-exporter` Docker image should export them on data-centre GPUs. If you see `DCGM_FI_DEV_GPU_UTIL` but not `DCGM_FI_PROF_SM_ACTIVE` in the metrics output, you may need a custom counter config file.

```bash
# Check which profiling counters are present
curl -s http://localhost:9400/metrics | grep DCGM_FI_PROF
```

### Kernel profiling: "not found — check trace_dir"

vLLM was not started with `--profiler-config`, or the trace directory path is wrong.

```bash
# Verify the profiling endpoint exists
curl -s -X POST http://localhost:8000/start_profile
# Should return 200, not 404

# Check the trace directory exists
ls /tmp/vllm_traces/
```

### JSON output path: permission denied

The default path `/tmp/telemetry_*.json` is Linux-specific. If running on Windows:

```bash
python telemetry_run.py --output ./runs/my_run.json
```

### TPOT / TTFT values look wrong

- Very high TTFT p99 but low p50 usually means some requests queued behind earlier ones. Increase concurrency or reduce `--num-requests`.
- TPOT of 0 means the request completed in one chunk (no streaming inter-token timing). Ensure vLLM is started with streaming enabled (it is by default).

---

## Quick Reference Card

```
# Minimum setup (any NVIDIA GPU, workload + GPU metrics only)
pip install pynvml requests aiohttp
# [start vLLM]
python telemetry_run.py --no-kernel

# Full setup (data-centre GPU, all metrics)
pip install pynvml requests aiohttp
docker run -d --gpus all --rm -p 9400:9400 nvcr.io/nvidia/k8s/dcgm-exporter:latest
# [start vLLM with --profiler-config]
python telemetry_run.py --title "My run" --output /tmp/run.json

# Copy result back
scp gpu-host:/tmp/run.json E:\Telemetry\Runs\
```
