# Continuous Inference Script

This script sends continuous requests to a vLLM API server to keep the GPU busy and generate throughput data.

## Automatic Execution

**The script now automatically runs after model deployment!** When you deploy a model through the orchestration system, the continuous inference script will automatically start in the background on the instance. This keeps the GPU busy and generates throughput metrics for monitoring.

### Configuration

You can configure the continuous inference behavior by including these parameters in your `vllm_config` when deploying:

- `inference_interval`: Seconds between requests (default: `5.0`)
- `max_tokens`: Maximum tokens to generate per request (default: `100`)
- `temperature`: Temperature for generation (default: `0.7`)
- `inference_prompt`: Custom prompt to use (default: `"What is 2+2? Please explain your answer."`)

### Manual Control

If you need to manually control the continuous inference:

**Stop continuous inference:**
```bash
ssh ubuntu@<instance_ip>
pkill -f continuous_inference.py
```

**View logs:**
```bash
ssh ubuntu@<instance_ip>
tail -f /tmp/continuous_inference.log
```

**Restart with custom settings:**
```bash
# Edit /tmp/continuous_inference.py on the instance, then:
nohup python3 /tmp/continuous_inference.py > /tmp/continuous_inference.log 2>&1 &
```

## Manual Usage

If you want to run the script manually (e.g., for testing or custom scenarios):

## Usage

### Basic Usage

```bash
python3 continuous_inference.py --ip 150.136.36.90
```

### With Custom Parameters

```bash
python3 continuous_inference.py \
  --ip 150.136.36.90 \
  --model mistralai/Mistral-7B-Instruct-v0.2 \
  --interval 5.0 \
  --max-tokens 100 \
  --temperature 0.7 \
  --prompt "Explain quantum computing in simple terms"
```

### Parameters

- `--ip` (required): IP address of the instance running vLLM
- `--model`: Model name (default: `mistralai/Mistral-7B-Instruct-v0.2`)
- `--interval`: Seconds between requests (default: `5.0`)
- `--max-tokens`: Maximum tokens to generate per request (default: `100`)
- `--temperature`: Temperature for generation (default: `0.7`)
- `--prompt`: Custom prompt (default: `"What is 2+2? Please explain your answer."`)

### Examples

**High frequency requests (1 second interval):**
```bash
python3 continuous_inference.py --ip 150.136.36.90 --interval 1.0
```

**Longer responses (more tokens):**
```bash
python3 continuous_inference.py --ip 150.136.36.90 --max-tokens 500
```

**Run in background:**
```bash
nohup python3 continuous_inference.py --ip 150.136.36.90 --interval 5.0 > inference.log 2>&1 &
```

**Stop background process:**
```bash
pkill -f continuous_inference.py
```

## Output

The script displays:
- Real-time request status
- Latency per request
- Token counts (prompt + completion)
- Throughput (tokens/second)
- Summary statistics every 10 requests
- Final summary when stopped (Ctrl+C)

## Example Output

```
================================================================================
Starting Continuous Inference
================================================================================
Target: http://150.136.36.90:8000/v1/chat/completions
Model: mistralai/Mistral-7B-Instruct-v0.2
Prompt: What is 2+2? Please explain your answer.
Interval: 5.0 seconds
Max Tokens: 100
Temperature: 0.7
================================================================================

[14:50:23] Request #1
  ✓ Success | Latency: 0.234s | Tokens: 45 (12 prompt + 33 completion)
  Throughput: 141.03 tokens/s | Avg Overall: 192.31 tokens/s
  Response preview: 2+2 equals 4. This is a basic arithmetic operation...

[14:50:28] Request #2
  ✓ Success | Latency: 0.198s | Tokens: 38 (12 prompt + 26 completion)
  Throughput: 131.31 tokens/s | Avg Overall: 178.57 tokens/s
  Response preview: The answer is 4. When you add two and two together...
```

