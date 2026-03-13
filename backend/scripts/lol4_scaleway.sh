#!/bin/bash
# vLLM Server Launch Script (Scaleway version)
# Automatically detects GPU configuration and adjusts vLLM parameters
# Uses /scratch partition for model storage

set -e

# Configure Docker/containerd to use /scratch if available (Scaleway has 5.8TB there)
if [ -d "/scratch" ] && [ -w "/scratch" ]; then
    # Check if Docker is already using /scratch
    if ! docker info 2>/dev/null | grep -q "/scratch"; then
        echo "Configuring Docker and containerd to use /scratch partition for storage..."
        sudo systemctl stop docker 2>/dev/null || true
        sudo systemctl stop containerd 2>/dev/null || true
        
        # Move Docker data to /scratch if not already there
        if [ ! -L "/var/lib/docker" ] && [ -d "/var/lib/docker" ]; then
            sudo mkdir -p /scratch/docker
            sudo mv /var/lib/docker /scratch/docker/ 2>/dev/null || true
        fi
        sudo mkdir -p /scratch/docker/docker
        sudo rm -rf /var/lib/docker
        sudo ln -sf /scratch/docker/docker /var/lib/docker 2>/dev/null || true
        
        # Move entire containerd directory to /scratch (includes tmpmounts and content store)
        if [ ! -L "/var/lib/containerd" ] && [ -d "/var/lib/containerd" ]; then
            sudo mkdir -p /scratch/containerd-full
            sudo mv /var/lib/containerd/* /scratch/containerd-full/ 2>/dev/null || true
        fi
        sudo mkdir -p /scratch/containerd-full
        sudo rm -rf /var/lib/containerd
        sudo ln -sf /scratch/containerd-full /var/lib/containerd 2>/dev/null || true
        
        sudo systemctl start containerd 2>/dev/null || true
        sudo systemctl start docker 2>/dev/null || true
        sleep 3
        echo "✅ Docker and containerd configured to use /scratch"
    fi
fi

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

# Configure NVIDIA Container Runtime to only expose compute capabilities
# This prevents mount failures for missing Vulkan/display/graphics libraries on cloud instances
echo "Configuring NVIDIA Container Runtime..."

# Ensure NVIDIA Container Toolkit is configured for Docker
sudo nvidia-ctk runtime configure --runtime=docker 2>/dev/null || true

# Create stub files for NVIDIA libraries that the container toolkit tries to mount
# The toolkit reads ldconfig cache to build mount list; missing .so files cause fatal errors
echo "Creating stub files for missing NVIDIA libraries..."
DRIVER_VERSION=$("$NVIDIA_SMI" --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | tr -d '[:space:]')
if [ -n "$DRIVER_VERSION" ]; then
    NVIDIA_LIB_DIR="/usr/lib/x86_64-linux-gnu"
    for lib in libnvidia-vulkan-producer.so libnvidia-api.so.1; do
        VERSIONED="${NVIDIA_LIB_DIR}/${lib%.so*}.so.${DRIVER_VERSION}"
        if [ ! -f "$VERSIONED" ] && [ ! -f "${NVIDIA_LIB_DIR}/${lib}" ]; then
            echo "  Creating stub: ${VERSIONED}"
            sudo touch "$VERSIONED" 2>/dev/null || true
        fi
    done
    # Create missing vulkan ICD/layer files
    sudo mkdir -p /usr/share/vulkan/icd.d /usr/share/vulkan/implicit_layer.d /usr/share/egl/egl_external_platform.d 2>/dev/null || true
    [ ! -f /usr/share/vulkan/icd.d/nvidia_icd.json ] && echo '{"ICD":{"api_version":"1.3","library_path":"libGLX_nvidia.so.0"}}' | sudo tee /usr/share/vulkan/icd.d/nvidia_icd.json > /dev/null 2>/dev/null || true
    [ ! -f /usr/share/vulkan/implicit_layer.d/nvidia_layers.json ] && echo '{"file_format_version":"1.0.0","layer":{"name":"VK_LAYER_NV_optimus","type":"INSTANCE","library_path":"libGLX_nvidia.so.0","api_version":"1.3","implementation_version":"1","description":"NVIDIA optimus layer"}}' | sudo tee /usr/share/vulkan/implicit_layer.d/nvidia_layers.json > /dev/null 2>/dev/null || true
    [ ! -f /usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json ] && echo '{"file_format_version":"1.0.0","ICD":{"library_path":"libnvidia-egl-gbm.so.1"}}' | sudo tee /usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json > /dev/null 2>/dev/null || true
fi

sudo systemctl restart docker 2>/dev/null || true
sleep 3

echo "✅ NVIDIA driver and Docker configured"

# Detect GPU information
GPU_COUNT=$(detect_gpu_count)
GPU_TYPE=$(detect_gpu_type)
GPU_MEMORY=$(detect_gpu_memory)

# Calculate optimal parameters
TENSOR_PARALLEL_SIZE=$(calculate_tensor_parallel_size "$GPU_COUNT")
GPU_MEM_UTIL=$(calculate_gpu_memory_utilization "$GPU_TYPE")
MAX_MODEL_LEN=$(calculate_max_model_len "$GPU_TYPE" "$GPU_COUNT" "$GPU_MEMORY")
MAX_NUM_SEQS=$(calculate_max_num_seqs "$GPU_COUNT" "$GPU_TYPE")

# Model path (configurable) - Scaleway uses /scratch for large storage
if [ -d "/scratch" ] && [ -w "/scratch" ]; then
    DEFAULT_MODEL_PATH="/scratch/BM/models/scout17b-fp8dyn"
else
    DEFAULT_MODEL_PATH="/root/BM/models/scout17b-fp8dyn"
fi
MODEL_PATH="${MODEL_PATH:-$DEFAULT_MODEL_PATH}"
# Derive container path from model path (use basename)
MODEL_BASENAME=$(basename "$MODEL_PATH")
CONTAINER_MODEL_PATH="/models/${MODEL_BASENAME}"

echo "=========================================="
echo "vLLM Server Configuration (Scaleway)"
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
sudo docker run --rm -d --name vllm \
  --gpus all \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
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
  --uvicorn-log-level info \
  --profiler-config '{"profiler":"torch","torch_profiler_dir":"/tmp/vllm_traces","torch_profiler_with_flops":true,"torch_profiler_use_gzip":false}'

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
