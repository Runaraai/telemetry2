#!/bin/bash
# vLLM Benchmarking Script
# This script sends requests to a running vLLM server to benchmark performance
# Supports batch processing, input/output sequence lengths

set -e

# Configuration
VLLM_URL="${VLLM_URL:-http://localhost:8000}"
NUM_REQUESTS="${NUM_REQUESTS:-10}"
BATCH_SIZE="${BATCH_SIZE:-1}"
INPUT_SEQ_LEN="${INPUT_SEQ_LEN:-100}"
OUTPUT_SEQ_LEN="${OUTPUT_SEQ_LEN:-100}"
PROMPT="${PROMPT:-What is the capital of France?}"
MAX_TOKENS="${MAX_TOKENS:-${OUTPUT_SEQ_LEN}}"

echo "=========================================="
echo "vLLM Benchmarking"
echo "=========================================="
echo "Server URL: $VLLM_URL"
echo "Number of requests: $NUM_REQUESTS"
echo "Batch size: $BATCH_SIZE"
echo "Input sequence length: $INPUT_SEQ_LEN"
echo "Output sequence length: $OUTPUT_SEQ_LEN"
echo "Max tokens: $MAX_TOKENS"
echo "Prompt: $PROMPT"
echo "=========================================="

# Check if server is running
echo "Checking if vLLM server is running..."
if ! curl -s "${VLLM_URL}/health" > /dev/null 2>&1; then
    echo "❌ Error: vLLM server is not running at $VLLM_URL"
    echo "Please start the server first with: ./lol4.sh"
    exit 1
fi
echo "✅ Server is running"

# Benchmark using OpenAI-compatible API
echo ""
echo "Starting benchmark..."

# Create a temporary Python script for benchmarking
cat > /tmp/benchmark_vllm.py << PYTHON_SCRIPT
import requests
import time
import json
import sys
import concurrent.futures
from threading import Lock

url = sys.argv[1]
num_requests = int(sys.argv[2])
batch_size = int(sys.argv[3])
input_seq_len = int(sys.argv[4])
output_seq_len = int(sys.argv[5])
prompt = sys.argv[6]
max_tokens = int(sys.argv[7])

# Prepare prompt to match input_seq_len (pad or truncate)
# Simple token approximation: ~4 chars per token
target_chars = input_seq_len * 4
if len(prompt) < target_chars:
    # Pad with repetition
    prompt = (prompt + " ") * ((target_chars // len(prompt)) + 1)
    prompt = prompt[:target_chars]
else:
    # Truncate
    prompt = prompt[:target_chars]

print(f"Sending {num_requests} requests to {url}...")
print(f"Batch size: {batch_size}, Input seq len: {input_seq_len}, Output seq len: {output_seq_len}")
print(f"Prompt length: {len(prompt)} chars (~{len(prompt)//4} tokens)")

total_time = 0
total_tokens = 0
successful_requests = 0
failed_requests = 0
latencies = []
lock = Lock()

def send_request(request_id):
    global total_time, total_tokens, successful_requests, failed_requests, latencies
    start_time = time.time()
    
    try:
        response = requests.post(
            f"{url}/v1/completions",
            json={
                "model": "scout17b-fp8dyn",
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=300
        )
        response.raise_for_status()
        
        elapsed = time.time() - start_time
        data = response.json()
        
        # Extract token count
        tokens = data.get("usage", {}).get("total_tokens", 0)
        
        with lock:
            total_tokens += tokens
            total_time += elapsed
            latencies.append(elapsed)
            successful_requests += 1
        
        print(f"Request {request_id}/{num_requests}: {elapsed:.2f}s, {tokens} tokens")
        return True
        
    except Exception as e:
        with lock:
            failed_requests += 1
        print(f"Request {request_id}/{num_requests}: FAILED - {e}")
        return False

# Send requests in batches
if batch_size > 1:
    with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = []
        for i in range(num_requests):
            future = executor.submit(send_request, i + 1)
            futures.append(future)
        
        # Wait for all to complete
        for future in concurrent.futures.as_completed(futures):
            future.result()
else:
    # Sequential requests
    for i in range(num_requests):
        send_request(i + 1)
        time.sleep(0.1)  # Small delay between sequential requests
PYTHON_SCRIPT

# Calculate statistics
if successful_requests > 0:
    avg_latency = total_time / successful_requests
    tokens_per_sec = total_tokens / total_time if total_time > 0 else 0
    requests_per_sec = successful_requests / total_time if total_time > 0 else 0
    
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) > 0 else 0
    p99 = latencies[int(len(latencies) * 0.99)] if len(latencies) > 0 else 0
    
    print("\n" + "="*50)
    print("Benchmark Results")
    print("="*50)
    print(f"Successful requests: {successful_requests}/{num_requests}")
    print(f"Failed requests: {failed_requests}")
    print(f"Total tokens: {total_tokens}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Average latency: {avg_latency:.2f}s")
    print(f"Tokens per second: {tokens_per_sec:.2f}")
    print(f"Requests per second: {requests_per_sec:.2f}")
    print(f"P50 latency: {p50:.2f}s")
    print(f"P95 latency: {p95:.2f}s")
    print(f"P99 latency: {p99:.2f}s")
    print("="*50)
else:
    print("\n❌ No successful requests!")
    sys.exit(1)
PYTHON_SCRIPT

# Run benchmark
python3 /tmp/benchmark_vllm.py "$VLLM_URL" "$NUM_REQUESTS" "$BATCH_SIZE" "$INPUT_SEQ_LEN" "$OUTPUT_SEQ_LEN" "$PROMPT" "$MAX_TOKENS"

# Cleanup
rm -f /tmp/benchmark_vllm.py

