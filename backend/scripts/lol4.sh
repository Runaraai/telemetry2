#!/bin/bash
# vLLM Server Launch Script (Adaptive for GPU type and count)
# Automatically detects GPU configuration and adjusts vLLM parameters

set -e

# Source GPU detection utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DETECT_SCRIPT="$SCRIPT_DIR/detect_gpu_info.sh"
if [ -f "$DETECT_SCRIPT" ]; then
    source "$DETECT_SCRIPT"
else
    echo "Warning: GPU detection script not found, using defaults"
    detect_gpu_count() { echo "4"; }
    detect_gpu_type() { echo "H100"; }
    detect_gpu_memory() { echo "80"; }
    calculate_tensor_parallel_size() { echo "$1"; }
    calculate_gpu_memory_utilization() { echo "0.90"; }
    calculate_max_model_len() { echo "8192"; }
    calculate_max_num_seqs() { echo "256"; }
fi

# Verify NVIDIA driver is working before proceeding
echo "Verifying NVIDIA driver and GPU access..."

# Ensure PATH includes common directories (needed for non-interactive SSH sessions)
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

# Find nvidia-smi in common locations
NVIDIA_SMI=""
for path in /usr/bin/nvidia-smi /usr/local/bin/nvidia-smi $(command -v nvidia-smi 2>/dev/null); do
    if [ -x "$path" ] 2>/dev/null; then
        NVIDIA_SMI="$path"
        break
    fi
done

if [ -z "$NVIDIA_SMI" ]; then
    echo "❌ ERROR: nvidia-smi not found. NVIDIA driver must be installed."
    echo "⚠️  Checked: /usr/bin/nvidia-smi, /usr/local/bin/nvidia-smi, and PATH"
    exit 1
fi

if ! "$NVIDIA_SMI" &> /dev/null; then
    echo "❌ ERROR: nvidia-smi exists but driver is not loaded."
    echo "⚠️  The system may need a reboot to activate the NVIDIA driver."
    echo "⚠️  Please reboot the system and try again."
    exit 1
fi

# Verify Docker can access GPUs
if ! sudo docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
    echo "❌ ERROR: Docker cannot access GPUs."
    echo "⚠️  This usually means:"
    echo "   1. NVIDIA driver is not loaded (reboot may be needed)"
    echo "   2. NVIDIA Container Toolkit is not properly configured"
    echo "⚠️  Please check the driver status and reboot if needed."
    exit 1
fi

echo "✅ NVIDIA driver and GPU access verified"

# Detect GPU information
GPU_COUNT=$(detect_gpu_count)
GPU_TYPE=$(detect_gpu_type)
GPU_MEMORY=$(detect_gpu_memory)

# Calculate optimal parameters
TENSOR_PARALLEL_SIZE=$(calculate_tensor_parallel_size "$GPU_COUNT")
GPU_MEM_UTIL=$(calculate_gpu_memory_utilization "$GPU_TYPE")
MAX_MODEL_LEN=$(calculate_max_model_len "$GPU_TYPE" "$GPU_COUNT" "$GPU_MEMORY")
MAX_NUM_SEQS=$(calculate_max_num_seqs "$GPU_COUNT" "$GPU_TYPE")

# Model path (configurable)
MODEL_PATH="${MODEL_PATH:-/home/ubuntu/BM/models/scout17b-fp8dyn}"
# Derive container path from model path (use basename)
MODEL_BASENAME=$(basename "$MODEL_PATH")
CONTAINER_MODEL_PATH="/models/${MODEL_BASENAME}"

echo "=========================================="
echo "vLLM Server Configuration"
echo "=========================================="
echo "GPU Count: $GPU_COUNT"
echo "GPU Type: $GPU_TYPE"
echo "GPU Memory: ${GPU_MEMORY}GB per GPU"
echo "Tensor Parallel Size: $TENSOR_PARALLEL_SIZE"
echo "GPU Memory Utilization: $GPU_MEM_UTIL"
echo "Max Model Length: $MAX_MODEL_LEN"
echo "Max Num Sequences: $MAX_NUM_SEQS"
echo "Model Path: $MODEL_PATH"
echo "=========================================="

# Pull vLLM image
echo "Pulling vLLM image..."
sudo docker pull vllm/vllm-openai:latest

# Stop existing container if running
docker rm -f vllm 2>/dev/null || true

# Run vLLM server with adaptive parameters
echo "Starting vLLM server..."
sudo docker run --rm -d --gpus all --name vllm \
  -p 8000:8000 \
  -v "${MODEL_PATH}:${CONTAINER_MODEL_PATH}" \
  vllm/vllm-openai:latest \
  --model "${CONTAINER_MODEL_PATH}" \
  --tokenizer "${CONTAINER_MODEL_PATH}" \
  --served-model-name "${MODEL_BASENAME} ${CONTAINER_MODEL_PATH}" \
  --trust-remote-code \
  --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" \
  --dtype auto \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --gpu-memory-utilization "$GPU_MEM_UTIL" \
  --enforce-eager \
  --host 0.0.0.0 \
  --port 8000 \
  --uvicorn-log-level info

# Alternative configuration (commented out - uncomment to use)
# docker rm -f vllm 2>/dev/null || true
#
# sudo docker run --rm -it --gpus all --name vllm \
#   -p 8000:8000 \
#   -v "${MODEL_PATH}:${CONTAINER_MODEL_PATH}" \
#   vllm/vllm-openai:latest \
#   --model "${CONTAINER_MODEL_PATH}" \
#   --trust-remote-code \
#   --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" \
#   --dtype auto \
#   --max-model-len "$MAX_MODEL_LEN" \
#   --max-num-seqs "$MAX_NUM_SEQS" \
#   --gpu-memory-utilization "$GPU_MEM_UTIL" \
#   --host 0.0.0.0 \
#   --port 8000 \
#   --uvicorn-log-level info

# To access container shell:
# docker exec -it vllm bash
# pip install --no-cache-dir "vllm==0.11.0"
