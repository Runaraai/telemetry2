# GPU Adaptive Parameters Guide

This document explains which parameters in the setup scripts automatically adapt based on GPU type and count.

## Parameters That Change

### 1. **Tensor Parallel Size** (`--tensor-parallel-size`)
- **Based on**: GPU count
- **Logic**: Uses all available GPUs (capped at 8 for very large systems)
- **Examples**:
  - 1 GPU → `1`
  - 2 GPUs → `2`
  - 4 GPUs → `4`
  - 8 GPUs → `8`
  - 16 GPUs → `8` (capped)

### 2. **GPU Memory Utilization** (`--gpu-memory-utilization`)
- **Based on**: GPU type
- **Values**:
  - H100: `0.92` (can handle higher utilization)
  - A100: `0.90` (slightly lower)
  - Other GPUs: `0.85` (conservative)

### 3. **Max Model Length** (`--max-model-len`)
- **Based on**: GPU type, GPU count, GPU memory
- **Base values**:
  - H100: 8192
  - A100: 6144
  - Other: 4096
- **Scaling**:
  - 4+ GPUs: 2x base
  - 2 GPUs: 1.5x base
  - 80GB+ memory: 2x
  - 40GB+ memory: 1.5x

### 4. **Max Num Sequences** (`--max-num-seqs`)
- **Based on**: GPU count, GPU type
- **Base values**:
  - H100: 256
  - A100: 128
  - Other: 64
- **Scaling**:
  - 4+ GPUs: 2x base
  - 2 GPUs: 1.5x base

### 5. **CUDA Distribution** (for keyring installation)
- **Based on**: OS version
- **Mappings**:
  - Ubuntu 24.04 → `ubuntu2404`
  - Ubuntu 22.04 → `ubuntu2204`
  - Ubuntu 20.04 → `ubuntu2004`
  - Unknown → `ubuntu2204` (default)

## Scripts Updated

### 1. `h100_fp8.sh`
- Now detects GPU type and count
- Adapts CUDA keyring distribution
- Shows detected configuration at startup

### 2. `lol.sh` (setup script)
- Detects GPU count and type
- Uses correct CUDA distribution for keyring
- Verifies GPU detection after setup

### 3. `lol4.sh` (vLLM launch script)
- **All vLLM parameters are now adaptive**:
  - `--tensor-parallel-size`: Based on GPU count
  - `--gpu-memory-utilization`: Based on GPU type
  - `--max-model-len`: Based on GPU type, count, and memory
  - `--max-num-seqs`: Based on GPU count and type
- Model path is configurable via `MODEL_PATH` environment variable

## Usage Examples

### Example 1: 4x H100 Setup
```bash
# Scripts will automatically detect:
# - GPU Count: 4
# - GPU Type: H100
# - Tensor Parallel: 4
# - Memory Util: 0.92
# - Max Model Len: 16384 (8192 * 2 for 4 GPUs)
# - Max Num Seqs: 512 (256 * 2 for 4 GPUs)
./h100_fp8.sh
```

### Example 2: 8x A100 Setup
```bash
# Scripts will automatically detect:
# - GPU Count: 8
# - GPU Type: A100
# - Tensor Parallel: 8
# - Memory Util: 0.90
# - Max Model Len: 24576 (6144 * 2 * 2 for 8 GPUs and 80GB)
# - Max Num Seqs: 256 (128 * 2 for 8 GPUs)
./h100_fp8.sh
```

### Example 3: Custom Model Path
```bash
# Override model path
export MODEL_PATH=/custom/path/to/model
./lol4.sh
```

## Manual Override

If you need to override any parameter, you can modify the detection functions in `detect_gpu_info.sh` or set environment variables before running the scripts.

## Detection Functions

All detection functions are in `backend/scripts/detect_gpu_info.sh`:
- `detect_gpu_count()` - Returns number of GPUs
- `detect_gpu_type()` - Returns GPU type (H100, A100, etc.)
- `detect_gpu_memory()` - Returns memory per GPU in GB
- `detect_cuda_distribution()` - Returns CUDA repo distribution
- `calculate_tensor_parallel_size()` - Calculates optimal TP size
- `calculate_gpu_memory_utilization()` - Calculates memory util
- `calculate_max_model_len()` - Calculates max context length
- `calculate_max_num_seqs()` - Calculates max sequences

