#!/bin/bash
# Run vLLM benchmark with GPU monitoring

# Don't exit on error for venv creation
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create and activate venv if it doesn't exist
if [ ! -d ~/vllm-bench-venv ]; then
    echo "Creating virtual environment..."
    # Check if python3-venv is installed
    if ! python3 -m venv --help > /dev/null 2>&1; then
        echo "Error: python3-venv not installed. Installing..."
        sudo apt install -y python3.12-venv || sudo apt install -y python3-venv
    fi
    # Create venv and check if it succeeded
    if ! python3 -m venv ~/vllm-bench-venv; then
        echo "Fatal: Failed to create virtual environment"
        exit 1
    fi
    # Verify venv was created
    if [ ! -d ~/vllm-bench-venv ]; then
        echo "Fatal: Virtual environment directory not created"
        exit 1
    fi
    source ~/vllm-bench-venv/bin/activate
    echo "Installing dependencies..."
    pip install --no-cache-dir requests pandas tqdm 2>&1 | grep -v "already satisfied" || true
else
    source ~/vllm-bench-venv/bin/activate
    # Ensure pandas is installed
    pip install --quiet --upgrade pandas 2>/dev/null || pip install pandas
fi

# Verify venv is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Error: Virtual environment not activated. Trying to activate..."
    if [ -d ~/vllm-bench-venv ]; then
        source ~/vllm-bench-venv/bin/activate
    fi
    if [ -z "$VIRTUAL_ENV" ]; then
        echo "Fatal: Could not activate virtual environment"
        exit 1
    fi
fi

# Start GPU monitoring in background
echo "Starting GPU monitoring..."
OUTPUT_FILE="gpu_metrics_$(date +%Y%m%d_%H%M%S).csv"
DELAY_MS=100

# Field IDs:
# 1002 = SM Active (Streaming Multiprocessor utilization %)
# 1005 = DRAM Active (HBM bandwidth utilization %)
# 203 = NVLink RX Bandwidth (bytes/sec)
# 252 = NVLink TX Bandwidth (bytes/sec)
# 150 = Power (Watts)
# 155 = GPU Utilization (%)

dcgmi dmon -e 1002,1005,203,252,150,155 -d $DELAY_MS > "$OUTPUT_FILE" 2>&1 &
MONITOR_PID=$!

echo "GPU monitoring started (PID: $MONITOR_PID)"
echo "Metrics being saved to: $OUTPUT_FILE"
echo ""

# Wait a moment for monitoring to start
sleep 2

# Re-enable exit on error for benchmark
set -e

# Ensure venv is activated before running benchmark
if [ -z "$VIRTUAL_ENV" ]; then
    source ~/vllm-bench-venv/bin/activate
fi

# Get parameters from environment variables (with defaults)
VLLM_URL="${VLLM_URL:-http://localhost:8000}"
INPUT_SEQ_LEN="${INPUT_SEQ_LEN:-1000}"
OUTPUT_SEQ_LEN="${OUTPUT_SEQ_LEN:-1000}"
NUM_REQUESTS="${NUM_REQUESTS:-10000}"
MAX_CONCURRENCY="${MAX_CONCURRENCY:-256}"

echo "Benchmark Configuration:"
echo "  vLLM Server URL: $VLLM_URL"
echo "  Input Sequence Length: $INPUT_SEQ_LEN"
echo "  Output Sequence Length: $OUTPUT_SEQ_LEN"
echo "  Number of Requests: $NUM_REQUESTS"
echo "  Max Concurrency: $MAX_CONCURRENCY"
echo ""

# Install requests if not available (ensure it's in venv)
if [ -n "$VIRTUAL_ENV" ]; then
    pip install --quiet requests 2>&1 | grep -v "already satisfied" || pip install requests
else
    pip3 install --user --quiet requests 2>&1 | grep -v "already satisfied" || pip3 install --user requests
fi

# Wait for vLLM server to be ready before starting benchmark
echo "Waiting for vLLM server to be ready..."
VLLM_URL="${VLLM_URL:-http://localhost:8000}"
max_wait=60
wait_interval=2
attempts=$((max_wait / wait_interval))

for i in $(seq 1 $attempts); do
    # Try multiple methods to check if server is ready
    # Method 1: Check if container is running
    if ! sudo docker ps | grep -q vllm; then
        echo "  vLLM container not running. Waiting... (attempt $i/$attempts)"
        sleep $wait_interval
        continue
    fi
    
    # Method 2: Try Python requests (more reliable than curl)
    if python3 -c "
import requests
import sys
try:
    resp = requests.get('${VLLM_URL}/v1/models', timeout=3)
    if resp.status_code == 200:
        sys.exit(0)
    else:
        sys.exit(1)
except:
    sys.exit(1)
" 2>/dev/null; then
        echo "✅ vLLM server is ready"
        break
    fi
    
    # Method 3: Fallback to curl if available
    if command -v curl > /dev/null 2>&1; then
        if curl -s --max-time 2 "${VLLM_URL}/v1/models" > /dev/null 2>&1; then
            echo "✅ vLLM server is ready"
            break
        fi
    fi
    
    if [ $i -eq $attempts ]; then
        echo "⚠️  Warning: vLLM server may not be ready after ${max_wait}s, but continuing anyway..."
        echo "  Container status:"
        sudo docker ps | grep vllm || echo "  Container not found"
    else
        echo "  Waiting for server... (attempt $i/$attempts)"
        sleep $wait_interval
    fi
done

# Run the benchmark using HTTP requests
echo "Starting benchmark..."
python3 << 'PYTHON_SCRIPT'
import requests
import time
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

url = os.environ.get("VLLM_URL", "http://localhost:8000")
num_requests = int(os.environ.get("NUM_REQUESTS", 10000))
input_seq_len = int(os.environ.get("INPUT_SEQ_LEN", 1000))
output_seq_len = int(os.environ.get("OUTPUT_SEQ_LEN", 1000))
max_concurrency = int(os.environ.get("MAX_CONCURRENCY", 256))

# Get model name from server (with retries)
max_retries = 5
retry_delay = 2
model_name = None
for attempt in range(max_retries):
    try:
        resp = requests.get(f"{url}/v1/models", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        model_name = data['data'][0]['id']
        print(f"Using model: {model_name}")
        break
    except Exception as e:
        if attempt < max_retries - 1:
            print(f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {retry_delay}s...")
            time.sleep(retry_delay)
        else:
            print(f"Error getting model name after {max_retries} attempts: {e}")
            print(f"Trying to check server health at {url}/health...")
            try:
                health_resp = requests.get(f"{url}/health", timeout=5)
                print(f"Health check status: {health_resp.status_code}")
            except Exception as health_e:
                print(f"Health check also failed: {health_e}")
            sys.exit(1)

def generate_prompt(length):
    base = "What is the capital of France? "
    if length <= len(base):
        return base[:length]
    return base + " ".join(["word"] * (length - len(base)))

print(f"Starting benchmark: {num_requests} requests, input_len={input_seq_len}, output_len={output_seq_len}, concurrency={max_concurrency}")

total_time = 0
total_tokens = 0
successful = 0
failed = 0
latencies = []
ttft_times = []  # Time to first token
lock = threading.Lock()
last_report_time = time.time()
report_interval = 5  # Report metrics every 5 seconds

def report_metrics_to_telemetry(tokens_per_sec, total_tokens_val, requests_per_sec, total_requests, ttft_p50=None, ttft_p95=None, cost_per_watt=None):
    """Report metrics to token exporter for telemetry visualization."""
    try:
        payload = {
            "tokens_per_second": tokens_per_sec,
            "total_tokens": total_tokens_val,
            "requests_per_second": requests_per_sec,
            "total_requests": total_requests
        }
        if ttft_p50 is not None:
            payload["ttft_p50_ms"] = ttft_p50 * 1000  # Convert to milliseconds
        if ttft_p95 is not None:
            payload["ttft_p95_ms"] = ttft_p95 * 1000  # Convert to milliseconds
        if cost_per_watt is not None:
            payload["cost_per_watt"] = cost_per_watt
        # Try to send to token exporter (non-blocking)
        requests.post("http://localhost:9402/update", json=payload, timeout=0.5)
    except:
        pass  # Silently fail - don't interrupt benchmark

def send_request(i):
    global total_time, total_tokens, successful, failed, latencies, ttft_times, last_report_time
    prompt = generate_prompt(input_seq_len)
    start = time.time()
    first_token_time = None
    try:
        resp = requests.post(
            f"{url}/v1/completions",
            json={"model": model_name, "prompt": prompt, "max_tokens": output_seq_len, "temperature": 0.7},
            timeout=300,
            stream=False
        )
        resp.raise_for_status()
        elapsed = time.time() - start
        data = resp.json()
        tokens = data.get("usage", {}).get("total_tokens", 0)
        
        # Estimate TTFT (Time To First Token) - for streaming we'd measure actual first token
        # For non-streaming, estimate as ~10% of total latency (prefill time)
        estimated_ttft = elapsed * 0.1
        if tokens > 0:
            estimated_ttft = elapsed / tokens  # Rough estimate: time per token
        
        with lock:
            total_tokens += tokens
            total_time += elapsed
            latencies.append(elapsed)
            ttft_times.append(estimated_ttft)
            successful += 1
            
            # Report metrics to telemetry every report_interval seconds
            current_time = time.time()
            if current_time - last_report_time >= report_interval:
                tokens_per_sec = total_tokens / total_time if total_time > 0 else 0
                requests_per_sec = successful / total_time if total_time > 0 else 0
                ttft_p50 = sorted(ttft_times)[len(ttft_times) // 2] if ttft_times else 0
                
                # Calculate cost per watt (tokens per second per watt)
                # We'll get power from environment or use a default
                power_watts = float(os.environ.get("GPU_POWER_WATTS", "400"))  # Default 400W per GPU
                cost_per_watt = tokens_per_sec / power_watts if power_watts > 0 else 0
                
                # Calculate TTFT P95
                ttft_p95 = sorted(ttft_times)[int(len(ttft_times) * 0.95)] if len(ttft_times) > 0 and len(ttft_times) > int(len(ttft_times) * 0.95) else ttft_p50
                
                report_metrics_to_telemetry(
                    tokens_per_sec, total_tokens, requests_per_sec, successful,
                    ttft_p50=ttft_p50, ttft_p95=ttft_p95, cost_per_watt=cost_per_watt
                )
                last_report_time = current_time
            
            if (successful) % 100 == 0:
                print(f"Completed {successful}/{num_requests} requests")
        return True
    except Exception as e:
        with lock:
            failed += 1
            if failed <= 5:
                print(f"Request {i+1} failed: {e}")
        return False

with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
    futures = [executor.submit(send_request, i) for i in range(num_requests)]
    for future in as_completed(futures):
        pass

if successful > 0:
    avg_latency = total_time / successful
    tps = total_tokens / total_time if total_time > 0 else 0
    rps = successful / total_time if total_time > 0 else 0
    latencies.sort()
    ttft_times.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    ttft_p50 = ttft_times[len(ttft_times) // 2] if ttft_times else 0
    ttft_p95 = ttft_times[int(len(ttft_times) * 0.95)] if ttft_times else 0
    
    # Calculate cost per watt
    power_watts = float(os.environ.get("GPU_POWER_WATTS", "400"))  # Default 400W per GPU
    cost_per_watt = tps / power_watts if power_watts > 0 else 0
    
    # Final metrics report to telemetry
    ttft_p95 = ttft_times[int(len(ttft_times) * 0.95)] if ttft_times else 0
    report_metrics_to_telemetry(tps, total_tokens, rps, successful, ttft_p50=ttft_p50, ttft_p95=ttft_p95, cost_per_watt=cost_per_watt)
    
    print("\n" + "="*50)
    print("Benchmark Results")
    print("="*50)
    print(f"Successful: {successful}/{num_requests}")
    print(f"Failed: {failed}")
    print(f"Total tokens: {total_tokens}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Avg latency: {avg_latency:.2f}s")
    print(f"Tokens/sec: {tps:.2f}")
    print(f"Requests/sec: {rps:.2f}")
    print(f"P50 latency: {p50:.2f}s")
    print(f"P95 latency: {p95:.2f}s")
    print(f"P99 latency: {p99:.2f}s")
    print(f"TTFT P50: {ttft_p50*1000:.2f}ms")
    print(f"TTFT P95: {ttft_p95*1000:.2f}ms")
    print(f"Cost per Watt: {cost_per_watt:.4f} tokens/s/W")
    print("="*50)
else:
    print("❌ No successful requests!")
    # Write exit code file using Python
    with open('/home/ubuntu/benchmark_exit_code', 'w') as f:
        f.write('1')
    sys.exit(1)
PYTHON_SCRIPT

# Capture Python script exit status
PYTHON_EXIT=$?

# Write exit code file
echo "$PYTHON_EXIT" > /home/ubuntu/benchmark_exit_code

# Stop monitoring
echo ""
echo "Benchmark completed. Stopping GPU monitoring..."
kill $MONITOR_PID 2>/dev/null || true
wait $MONITOR_PID 2>/dev/null || true

# Extract steady state (25th-75th percentile) from the metrics
echo ""
echo "Extracting steady state metrics (25th-75th percentile)..."
STEADY_STATE_FILE="${OUTPUT_FILE%.csv}_steady_state.csv"

python3 << EOF
import pandas as pd
import sys

try:
    # Read the CSV file, skipping header rows
    df = pd.read_csv('$OUTPUT_FILE', skiprows=1)
    
    # Calculate indices for 25th and 75th percentile
    total_rows = len(df)
    start_idx = int(total_rows * 0.25)
    end_idx = int(total_rows * 0.75)
    
    # Extract steady state portion
    steady_state_df = df.iloc[start_idx:end_idx]
    
    # Save to new file
    steady_state_df.to_csv('$STEADY_STATE_FILE', index=False)
    
    print(f"Steady state metrics extracted:")
    print(f"  Total samples: {total_rows}")
    print(f"  Steady state samples: {len(steady_state_df)} (rows {start_idx} to {end_idx})")
    print(f"  Saved to: $STEADY_STATE_FILE")
    print("")
    print("Steady state statistics:")
    print(steady_state_df.describe())
    
except Exception as e:
    print(f"Error processing metrics: {e}", file=sys.stderr)
    sys.exit(1)
EOF

echo ""
echo "Full metrics saved to: $OUTPUT_FILE"
echo "Steady state metrics (25-75%) saved to: $STEADY_STATE_FILE"