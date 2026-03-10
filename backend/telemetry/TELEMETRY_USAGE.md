# GPU Telemetry Stack Usage Guide

## Overview

The telemetry deployment now includes three exporters providing comprehensive GPU and workload metrics:

### 1. DCGM Exporter (Port 9400)
Exposes extended NVIDIA DCGM metrics including:
- **SM Utilization**: `DCGM_FI_PROF_SM_ACTIVE`, `DCGM_FI_PROF_SM_OCCUPANCY`
- **Pipeline Activity**: Tensor core, FP64, FP32, FP16 active percentages
- **Memory Bandwidth**: DRAM active, PCIe TX/RX bytes
- **NVLink**: TX/RX bytes for inter-GPU communication
- **Power & Thermal**: Power usage, temperature, throttle reasons
- **Clock Frequencies**: SM, memory, graphics clocks
- **ECC Errors**: Single-bit and double-bit error counts
- **PCIe**: Bandwidth and replay counters

### 2. NVIDIA-SMI Exporter (Port 9401)
Provides complementary metrics via nvidia-smi:
- GPU utilization and memory utilization percentages
- Memory total, free, and used (MiB)
- Temperature (Celsius)
- Power draw and power limit (Watts)
- Clock speeds: SM, memory, graphics (MHz)
- Fan speed percentage
- PCIe link generation and width
- Encoder session count, FPS, and latency

### 3. Token Throughput Exporter (Port 9402)
Application-level metrics placeholder for inference workloads:
- `token_throughput_per_second`: Current token generation rate
- `token_total_generated`: Cumulative token count
- `inference_requests_per_second`: Request throughput
- `inference_total_requests`: Total requests processed

## Using the Token Exporter

### Push Metrics from Your Workload

The token exporter accepts POST requests to update metrics in real-time:

```bash
curl -X POST http://localhost:9402/update \
  -H "Content-Type: application/json" \
  -d '{
    "tokens_per_second": 123.4,
    "total_tokens": 5000,
    "requests_per_second": 2.5,
    "total_requests": 100
  }'
```

### Python Example

```python
import requests
import time

def report_token_metrics(tokens_per_sec, total_tokens, req_per_sec, total_reqs):
    """Report token throughput to telemetry stack."""
    url = "http://localhost:9402/update"
    data = {
        "tokens_per_second": tokens_per_sec,
        "total_tokens": total_tokens,
        "requests_per_second": req_per_sec,
        "total_requests": total_reqs
    }
    try:
        response = requests.post(url, json=data, timeout=2)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to report metrics: {e}")

# Example: Report metrics every 5 seconds during inference
total_tokens = 0
total_requests = 0

while True:
    # Your inference logic here
    tokens_generated = run_inference()
    total_tokens += tokens_generated
    total_requests += 1
    
    # Calculate rates
    tokens_per_sec = tokens_generated / 5.0
    req_per_sec = 1 / 5.0
    
    # Report to telemetry
    report_token_metrics(tokens_per_sec, total_tokens, req_per_sec, total_requests)
    
    time.sleep(5)
```

### Integration with vLLM, Triton, or Custom Servers

For production inference servers, integrate the POST call into your request handler:

```python
# vLLM example
from vllm import LLM, SamplingParams
import requests

llm = LLM(model="meta-llama/Llama-2-7b-hf")
total_tokens = 0
total_requests = 0

def generate_and_report(prompt):
    global total_tokens, total_requests
    
    start = time.time()
    outputs = llm.generate([prompt], SamplingParams(max_tokens=100))
    elapsed = time.time() - start
    
    tokens = len(outputs[0].outputs[0].token_ids)
    total_tokens += tokens
    total_requests += 1
    
    # Report metrics
    requests.post("http://localhost:9402/update", json={
        "tokens_per_second": tokens / elapsed,
        "total_tokens": total_tokens,
        "requests_per_second": 1 / elapsed,
        "total_requests": total_requests
    })
    
    return outputs
```

## Viewing Metrics

### Prometheus Query Examples

```promql
# GPU utilization from DCGM
DCGM_FI_DEV_GPU_UTIL

# SM active percentage (profiling metric)
DCGM_FI_PROF_SM_ACTIVE

# NVLink bandwidth (bytes/sec)
rate(DCGM_FI_PROF_NVLINK_TX_BYTES[1m])

# Memory utilization from nvidia-smi
nvidia_smi_utilization_memory_percent

# Token throughput
token_throughput_per_second

# Total tokens generated
token_total_generated
```

### Grafana Dashboard

All metrics are available in Prometheus and can be visualized in Grafana. Key panels to add:

1. **GPU Utilization**: `DCGM_FI_DEV_GPU_UTIL` and `nvidia_smi_utilization_gpu_percent`
2. **Memory Usage**: `DCGM_FI_DEV_FB_USED / DCGM_FI_DEV_FB_FREE * 100`
3. **SM Activity**: `DCGM_FI_PROF_SM_ACTIVE`
4. **Token Throughput**: `token_throughput_per_second`
5. **NVLink Bandwidth**: `rate(DCGM_FI_PROF_NVLINK_TX_BYTES[1m]) + rate(DCGM_FI_PROF_NVLINK_RX_BYTES[1m])`
6. **Power Draw**: `DCGM_FI_DEV_POWER_USAGE`

## Troubleshooting

### DCGM Profiling Metrics Not Available

If `DCGM_FI_PROF_*` metrics show as unavailable:

1. Enable persistence mode: `sudo nvidia-smi -pm 1`
2. Restart the DCGM exporter: `docker compose restart dcgm-exporter`
3. Check GPU support: Some profiling metrics require Volta+ architecture

### NVIDIA-SMI Exporter Shows No Data

Ensure nvidia-smi is accessible inside the container:
```bash
docker compose exec nvidia-smi-exporter nvidia-smi
```

If it fails, the volume mounts may need adjustment for your system.

### Token Metrics Stay at Zero

The token exporter starts with zero values. Your workload must POST updates to `/update` endpoint. Verify connectivity:

```bash
curl http://localhost:9402/health
# Should return: OK

curl http://localhost:9402/metrics
# Should show token_throughput_per_second and other metrics
```

## Port Summary

- **9090**: Prometheus web UI
- **9400**: DCGM exporter metrics endpoint
- **9401**: NVIDIA-SMI exporter metrics endpoint
- **9402**: Token exporter metrics endpoint (also accepts POST to /update)

## Notes

- All exporters restart automatically if they crash
- Metrics are scraped every 1 second by Prometheus
- Data is retained for 2 hours in Prometheus local storage
- All metrics are forwarded to the backend via remote_write with the run_id label


