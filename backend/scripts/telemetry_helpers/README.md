# Omniference Telemetry Helpers

This directory contains helper tools to automatically collect token metrics from running workloads without requiring code changes to your inference applications.

## Goal: Maximum Data Collection with Zero Code Changes

The telemetry stack automatically collects GPU metrics (DCGM, nvidia-smi), but token metrics require application-level data. These helpers make token collection as automatic as possible.

## Tools

### 1. `token_collector_wrapper.py` - Command Wrapper

Automatically extracts token metrics from stdout/stderr or log files when running inference commands.

**Usage:**
```bash
# Run any inference command - metrics automatically extracted
python token_collector_wrapper.py -- python your_inference.py --model llama

# Monitor a log file
python token_collector_wrapper.py --log-file /var/log/inference.log -- python your_script.py

# Just monitor a log file (no command)
python token_collector_wrapper.py --log-file /var/log/inference.log --monitor-only
```

**How it works:**
- Intercepts stdout/stderr from the command
- Parses output for common token metric patterns (vLLM, TensorRT-LLM, generic)
- Automatically sends metrics to token-exporter at `http://localhost:9402`
- Works with any inference framework that outputs token metrics

**Supported patterns:**
- `tokens/s: 123.4`
- `throughput: 123.4 tokens/s`
- `"tokens_per_second": 123.4` (JSON)
- `Total tokens: 5000`
- And many more...

### 2. `token_collector_lib.py` - Python Library

Simple Python library for applications that want to explicitly report metrics.

**Usage:**
```python
from telemetry_helpers.token_collector_lib import TokenReporter

reporter = TokenReporter()

# In your inference loop
for batch in batches:
    tokens = generate_tokens(batch)
    reporter.report_tokens(tokens, elapsed_time=1.0)

# Or report directly
reporter.report_metrics(
    tokens_per_second=123.4,
    total_tokens=5000
)
```

**Features:**
- Thread-safe and non-blocking
- Auto-calculates rates from token counts
- Silently fails if exporter unavailable (won't interrupt workload)
- Global instance available for convenience

### 3. Environment Variable Integration

Set `OMNIFERENCE_TOKEN_COLLECTOR=1` to enable automatic collection (if your application supports it).

## Deployment

These helpers are automatically deployed to `/opt/omniference/telemetry_helpers/` when the telemetry stack is deployed.

## Examples

### Example 1: vLLM Inference
```bash
# vLLM outputs metrics to stdout - wrapper automatically captures them
python token_collector_wrapper.py -- \
    python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-2-7b-chat-hf \
    --port 8000
```

### Example 2: TensorRT-LLM
```bash
# TensorRT-LLM logs to file - monitor it
python token_collector_wrapper.py \
    --log-file /var/log/trtllm.log \
    -- python trtllm_benchmark.py
```

### Example 3: Custom Application
```python
# Minimal code change - just import and use
from telemetry_helpers.token_collector_lib import report_tokens

def inference_loop():
    for request in requests:
        tokens = process_request(request)
        report_tokens(tokens)  # That's it!
```

## How It Works

1. **Token-exporter service** runs on port 9402 (automatically deployed)
2. **Helpers collect metrics** from stdout/stderr/logs or application code
3. **Metrics sent to exporter** via HTTP POST
4. **Prometheus scrapes** exporter every polling interval
5. **Backend receives** metrics via remote_write
6. **Frontend displays** in real-time charts

## Zero-Code-Change Approach

For maximum automation:

1. Use the wrapper script to run inference commands
2. Or monitor log files if your framework logs metrics
3. No code changes needed to your inference application

## With Minimal Code Changes

If you want more control:

1. Import `token_collector_lib`
2. Add 1-2 lines to report tokens
3. Get accurate, real-time metrics

## Troubleshooting

**No metrics appearing?**
- Check token-exporter is running: `curl http://localhost:9402/health`
- Check metrics endpoint: `curl http://localhost:9402/metrics`
- Verify your application outputs token metrics in a supported format
- Check wrapper is parsing correctly (it prints found metrics to stderr)

**Metrics not updating?**
- Token-exporter persists metrics to `/data/tokens.json`
- Check file exists and has recent timestamps
- Prometheus scrapes every polling interval (default 5s)

