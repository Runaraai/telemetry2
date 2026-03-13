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

# Configure NVIDIA Container Runtime (only if not already configured)
if ! sudo docker info 2>/dev/null | grep -q "nvidia"; then
    echo "Configuring NVIDIA Container Runtime (first time)..."
    sudo nvidia-ctk runtime configure --runtime=docker 2>&1 || true
    sudo ldconfig 2>/dev/null || true
    sudo systemctl restart docker 2>/dev/null || true
    echo "Waiting for Docker to fully restart..."
    sleep 10
    echo "✅ NVIDIA Container Runtime configured"
else
    echo "✅ NVIDIA Container Runtime already configured, skipping restart"
fi

# Ensure nvidia-uvm kernel module is loaded (required for CUDA inside Docker)
echo "Loading nvidia-uvm kernel module..."

# Fast path: try loading it (works if .ko exists and was just not auto-loaded)
sudo modprobe nvidia-uvm 2>/dev/null || true

# If still missing, the driver installation is incomplete — install nvidia-kernel-common via apt.
# On Scaleway, nvidia-firmware-535-server conflicts with nvidia-kernel-common-535 (both own
# the same firmware files). Remove the server variant first, then install the common package
# which triggers DKMS to build nvidia_uvm.ko for the current kernel.
if [ ! -e /dev/nvidia-uvm ]; then
    echo "nvidia-uvm not available — fixing kernel modules via apt..."
    DRIVER_MAJOR=$("$NVIDIA_SMI" --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)
    sudo apt-get update -qq 2>&1 || true
    # Remove the conflicting server firmware package if present (it blocks nvidia-kernel-common install)
    DRIVER_VER=$("$NVIDIA_SMI" --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')
    if dpkg -l "nvidia-firmware-${DRIVER_MAJOR}-server-${DRIVER_VER}" 2>/dev/null | grep -q "^ii"; then
        echo "Removing conflicting nvidia-firmware-${DRIVER_MAJOR}-server package..."
        sudo dpkg -r --force-depends "nvidia-firmware-${DRIVER_MAJOR}-server-${DRIVER_VER}" 2>&1 || true
    fi
    # Install nvidia-kernel-common which triggers DKMS build of all modules including nvidia-uvm
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "nvidia-kernel-common-${DRIVER_MAJOR}" 2>&1 || \
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "nvidia-driver-${DRIVER_MAJOR}" 2>&1 || true
    sudo DEBIAN_FRONTEND=noninteractive apt-get -f install -y 2>&1 || true
    sudo depmod -a 2>&1 || true
    sudo modprobe nvidia-uvm 2>&1 || true
fi

# If module is loaded but device file still missing, create it from /proc/devices
if [ ! -e /dev/nvidia-uvm ]; then
    UVM_MAJOR=$(grep nvidia-uvm /proc/devices 2>/dev/null | awk '{print $1}')
    if [ -n "$UVM_MAJOR" ]; then
        echo "Creating /dev/nvidia-uvm device node (major=$UVM_MAJOR)..."
        sudo mknod -m 666 /dev/nvidia-uvm c "$UVM_MAJOR" 0 2>/dev/null || true
        sudo mknod -m 666 /dev/nvidia-uvm-tools c "$UVM_MAJOR" 1 2>/dev/null || true
    fi
fi

# Verify GPU devices are accessible on the host
echo "Checking GPU device availability..."
if ls /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm &>/dev/null; then
    echo "✅ GPU device files present: $(ls /dev/nvidia* 2>/dev/null | tr '\n' ' ')"
else
    echo "❌ GPU device files still missing: $(ls /dev/nvidia* 2>/dev/null | tr '\n' ' ')"
    echo "❌ /proc/devices nvidia entries: $(grep -i nvidia /proc/devices 2>/dev/null || echo 'none')"
    echo "❌ Loaded kernel modules: $(lsmod 2>/dev/null | grep nvidia || echo 'none')"
    exit 1
fi

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

# Stop any existing vLLM container and free port 8000
sudo docker stop vllm 2>/dev/null || true
sudo docker rm -f vllm 2>/dev/null || true
# Kill any process holding port 8000 (leftover from previous runs)
sudo fuser -k 8000/tcp 2>/dev/null || true
sleep 2

# Run vLLM server with adaptive parameters (no --rm so crash logs persist)
echo "Starting vLLM server..."
sudo docker run -d --name vllm \
  --runtime=nvidia \
  --gpus all \
  --shm-size=10.24gb \
  --ulimit memlock=-1 \
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
