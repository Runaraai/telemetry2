#!/bin/bash
# GPU Detection Utility Functions
# Source this file in other scripts: source detect_gpu_info.sh

# Detect GPU count
detect_gpu_count() {
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi --list-gpus 2>/dev/null | wc -l
    else
        echo "0"
    fi
}

# Detect GPU type (H100, A100, etc.)
detect_gpu_type() {
    if command -v nvidia-smi &> /dev/null; then
        # Get first GPU name and extract model
        nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | sed 's/.*\(H100\|A100\|A10\|V100\|RTX\).*/\1/' | head -1
    else
        echo "UNKNOWN"
    fi
}

# Detect GPU memory per GPU (in GB)
detect_gpu_memory() {
    if command -v nvidia-smi &> /dev/null; then
        # Get memory in MiB, convert to GB
        nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | awk '{print int($1/1024)}'
    else
        echo "0"
    fi
}

# Detect OS distribution for CUDA keyring
detect_cuda_distribution() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        # Map Ubuntu versions to CUDA repo format
        case "$VERSION_ID" in
            22.04)
                echo "ubuntu2204"
                ;;
            24.04)
                echo "ubuntu2404"
                ;;
            20.04)
                echo "ubuntu2004"
                ;;
            *)
                # Default to 22.04 if unknown
                echo "ubuntu2204"
                ;;
        esac
    else
        echo "ubuntu2204"
    fi
}

# Calculate optimal tensor parallel size based on GPU count
calculate_tensor_parallel_size() {
    local gpu_count=$1
    # Use all available GPUs, but cap at 8 for very large systems
    if [ "$gpu_count" -gt 8 ]; then
        echo "8"
    else
        echo "$gpu_count"
    fi
}

# Calculate GPU memory utilization based on GPU type
calculate_gpu_memory_utilization() {
    local gpu_type=$1
    case "$gpu_type" in
        H100)
            echo "0.92"  # H100 can handle higher utilization
            ;;
        A100)
            echo "0.90"  # A100 slightly lower
            ;;
        *)
            echo "0.85"  # Conservative for other GPUs
            ;;
    esac
}

# Calculate max model length based on GPU type and count
calculate_max_model_len() {
    local gpu_type=$1
    local gpu_count=$2
    local gpu_memory=$3
    
    # Base calculation: more GPUs and memory = longer context
    local base_len=4096
    
    if [ "$gpu_type" = "H100" ]; then
        base_len=8192
    elif [ "$gpu_type" = "A100" ]; then
        base_len=6144
    fi
    
    # Scale with GPU count (up to 4x)
    if [ "$gpu_count" -ge 8 ]; then
        base_len=$((base_len * 4))  # 8 GPUs: 4x scaling
    elif [ "$gpu_count" -ge 4 ]; then
        base_len=$((base_len * 2))   # 4 GPUs: 2x scaling
    elif [ "$gpu_count" -ge 2 ]; then
        base_len=$((base_len * 3 / 2))  # 2 GPUs: 1.5x scaling
    fi
    
    # Scale with memory (80GB+ GPUs can handle longer)
    if [ "$gpu_memory" -ge 80 ]; then
        base_len=$((base_len * 2))
    elif [ "$gpu_memory" -ge 40 ]; then
        base_len=$((base_len * 3 / 2))
    fi
    
    echo "$base_len"
}

# Calculate max num seqs based on GPU count and type
calculate_max_num_seqs() {
    local gpu_count=$1
    local gpu_type=$2
    
    # Base calculation
    local base_seqs=64
    
    if [ "$gpu_type" = "H100" ]; then
        base_seqs=256  # H100 can handle more sequences
    elif [ "$gpu_type" = "A100" ]; then
        base_seqs=128
    fi
    
    # Scale with GPU count
    if [ "$gpu_count" -ge 8 ]; then
        base_seqs=$((base_seqs * 4))  # 8 GPUs: 4x scaling
    elif [ "$gpu_count" -ge 4 ]; then
        base_seqs=$((base_seqs * 2))   # 4 GPUs: 2x scaling
    elif [ "$gpu_count" -ge 2 ]; then
        base_seqs=$((base_seqs * 3 / 2))  # 2 GPUs: 1.5x scaling
    fi
    
    echo "$base_seqs"
}

