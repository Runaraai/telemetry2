#!/bin/bash
# GPU LLM Benchmarking Setup Script (Adaptive for H100, A100, etc.)
# Based on successful commands from H100_Command_Log.md
# This script automatically detects GPU type and count and adapts configuration
#
# SECURITY & USAGE:
#   - Set a Hugging Face token securely before running:
#       export HF_TOKEN="your_read_token"
#   - Optional: enable dry-run to preview actions:
#       DRY_RUN=true ./h100_fp8_general.sh
#   - State and logs:
#       - State: /var/lib/gpu-setup/setup-state.json (idempotent phases)
#       - Lock:  /var/lock/gpu-setup.lock (prevents concurrent runs)
#       - Logs:  /var/log/gpu-setup/setup-YYYYMMDD-HHMMSS.log
#   - Never store tokens in the script or shell history.

set -euo pipefail
set -E
trap 'echo "ERROR at line $LINENO: $BASH_COMMAND"; exit 1' ERR

DRY_RUN="${DRY_RUN:-false}"
SETUP_USER="${SUDO_USER:-$USER}"
SCRIPT_ARGS=("$@")
DOCKER_GROUP_REEXEC="${DOCKER_GROUP_REEXEC:-0}"

STATE_DIR="/var/lib/gpu-setup"
STATE_FILE="$STATE_DIR/setup-state.json"
LOCK_FILE="/var/lock/gpu-setup.lock"
LOG_DIR="/var/log/gpu-setup"
LOG_FILE="$LOG_DIR/setup-$(date +%Y%m%d-%H%M%S).log"

VENV_DIR="$SCRIPT_DIR/h100_benchmark_env"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ "$DRY_RUN" = "true" ]; then
    echo "DRY_RUN enabled - commands will be echoed, no changes applied."
    LOG_DIR="/tmp/gpu-setup"
    LOG_FILE="$LOG_DIR/setup-$(date +%Y%m%d-%H%M%S).log"
fi

# Dry-run helpers
run_cmd() {
    if [ "$DRY_RUN" = "true" ]; then
        echo "[DRY-RUN] $*"
        return 0
    fi
    "$@"
}

TEMP_PATHS=()
CURRENT_PHASE="initialization"

register_temp_path() {
    TEMP_PATHS+=("$1")
}

# cleanup runs on any exit
cleanup() {
    local exit_code=$?
    if [ "$DRY_RUN" != "true" ]; then
        for path in "${TEMP_PATHS[@]}"; do
            if [ -e "$path" ]; then
                rm -rf "$path"
            fi
        done
        if [ "$exit_code" -ne 0 ] && [ -d "$MODEL_PATH" ]; then
            find "$MODEL_PATH" -maxdepth 1 -type f \( -name "*.incomplete" -o -name "*.partial" -o -name "*.tmp" \) -print -delete 2>/dev/null || true
        fi
    fi
    if [ -n "${LOCK_FD:-}" ]; then
        flock -u "$LOCK_FD" || true
    fi
    if [ "$exit_code" -ne 0 ]; then
        echo "❌ ERROR: Setup failed during phase '${CURRENT_PHASE}' (exit $exit_code). Check log: $LOG_FILE"
        echo "→ Try: re-run the script after addressing the error above."
    fi
}
trap cleanup EXIT

# Set up logging (always create to keep tee happy)
sudo mkdir -p "$LOG_DIR"
sudo touch "$LOG_FILE"
sudo chown "$SETUP_USER":"$SETUP_USER" "$LOG_FILE" "$LOG_DIR"
exec 1> >(tee -a "$LOG_FILE") 2>&1

# Concurrency control
LOCK_FD=200
exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    echo "❌ ERROR: Another gpu-setup instance is running (lock $LOCK_FILE)."
    echo "→ Try: check running processes or remove stale lock file if safe."
    exit 1
fi

# State tracking helpers (idempotency)
run_cmd sudo mkdir -p "$STATE_DIR"
if [ "$DRY_RUN" != "true" ] && [ ! -f "$STATE_FILE" ]; then
    echo "{}" | run_cmd sudo tee "$STATE_FILE" >/dev/null
fi
run_cmd sudo chown -R "$SETUP_USER":"$SETUP_USER" "$STATE_DIR" 2>/dev/null || true

is_phase_complete() {
    local phase="$1"
    if [ "$DRY_RUN" = "true" ] || [ ! -f "$STATE_FILE" ]; then
        return 1
    fi
    python3 - <<EOF
import json
from pathlib import Path
state_path = Path("$STATE_FILE")
try:
    data = json.loads(state_path.read_text())
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if data.get("$phase") else 1)
EOF
}

mark_phase_complete() {
    local phase="$1"
    if [ "$DRY_RUN" = "true" ]; then
        echo "[DRY-RUN] Marking phase '$phase' complete (state unchanged)."
        return 0
    fi
    python3 - <<EOF
import json
from pathlib import Path
state_path = Path("$STATE_FILE")
data = {}
if state_path.exists():
    try:
        data = json.loads(state_path.read_text())
    except Exception:
        data = {}
data["$phase"] = True
state_path.write_text(json.dumps(data, indent=2))
EOF
}

run_phase() {
    local phase="$1"
    local description="$2"
    shift 2
    if is_phase_complete "$phase"; then
        echo "⏭️  Skipping $description (already completed)."
        return 0
    fi
    echo ""
    echo "=== $description ==="
    "$@"
    mark_phase_complete "$phase"
}

validate_prerequisites() {
    echo "Validating prerequisites..."
    if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
        echo "❌ ERROR: sudo privileges are required."
        echo "→ Try: run with sudo or ensure your user is in the sudoers file."
        exit 1
    fi
    if ! command -v curl >/dev/null 2>&1; then
        echo "❌ ERROR: curl is required."
        echo "→ Try: sudo apt update && sudo apt install -y curl"
        exit 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "❌ ERROR: python3 is required."
        echo "→ Try: sudo apt install -y python3"
        exit 1
    fi
    if ! ping -c1 -W2 huggingface.co >/dev/null 2>&1; then
        echo "⚠️  WARNING: Network connectivity to huggingface.co could not be confirmed."
        echo "→ Try: verify internet access or proxy settings."
    fi
    if [ -f /etc/os-release ] && ! grep -qi "ubuntu" /etc/os-release; then
        echo "⚠️  WARNING: Script validated on Ubuntu. Proceed with caution."
    fi
}

validate_environment() {
    HF_TOKEN="${HF_TOKEN:-}"
    if [ -z "$HF_TOKEN" ]; then
        # Try to read from common .env locations without sourcing arbitrary code
        local env_files=(
            "$SCRIPT_DIR/../../.env"
            "$SCRIPT_DIR/../.env"
            "$SCRIPT_DIR/.env"
            "$HOME/.env"
            "/home/$SETUP_USER/.env"
            "/etc/gpu-setup/.env"
        )
        for env_file in "${env_files[@]}"; do
            if [ -f "$env_file" ]; then
                token_candidate=$(ENV_FILE="$env_file" ENV_KEY="HF_TOKEN" python3 <<'PY' 2>/dev/null || true
import os
from pathlib import Path

file_path = Path(os.environ["ENV_FILE"])
key = os.environ["ENV_KEY"]
for line in file_path.read_text().splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    k, v = stripped.split("=", 1)
    if k.strip() != key:
        continue
    value = v.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    print(value)
    raise SystemExit(0)
raise SystemExit(1)
PY
)
                if [ -n "${token_candidate:-}" ]; then
                    HF_TOKEN="$token_candidate"
                    export HF_TOKEN
                    echo "ℹ️  Loaded HF_TOKEN from $env_file"
                    break
                fi
            fi
        done
    fi
    if [ -z "$HF_TOKEN" ] && [ -n "${HF_TOKEN_FILE:-}" ] && [ -f "$HF_TOKEN_FILE" ]; then
        HF_TOKEN="$(head -n1 "$HF_TOKEN_FILE" | tr -d '\"' | xargs)"
        export HF_TOKEN
        echo "ℹ️  Loaded HF_TOKEN from HF_TOKEN_FILE=$HF_TOKEN_FILE"
    fi
    if [ -z "$HF_TOKEN" ] && [ -f "/etc/gpu-setup/hf_token" ]; then
        HF_TOKEN="$(sudo head -n1 /etc/gpu-setup/hf_token | tr -d '\"' | xargs)"
        export HF_TOKEN
        echo "ℹ️  Loaded HF_TOKEN from /etc/gpu-setup/hf_token"
    fi
    if [ -z "$HF_TOKEN" ]; then
        echo "❌ ERROR: HF_TOKEN must be set for Hugging Face downloads."
        echo "→ Try: export HF_TOKEN=\"<read_token>\" (token not stored on disk), or set HF_TOKEN_FILE to a secure file containing the token."
        exit 1
    fi

    # Persist the token for future runs in a secure location (non-interactive, avoids shell history)
    if [ "$DRY_RUN" != "true" ]; then
        run_cmd sudo mkdir -p /etc/gpu-setup
        if [ ! -f /etc/gpu-setup/hf_token ]; then
            python3 <<'PY'
import os
from pathlib import Path

token = os.environ.get("HF_TOKEN", "").strip()
if not token:
    raise SystemExit(0)
target = Path("/etc/gpu-setup/hf_token")
if not target.exists():
    target.write_text(token + "\n")
    os.chmod(target, 0o600)
PY
            run_cmd sudo chown "$SETUP_USER":"$SETUP_USER" /etc/gpu-setup/hf_token || true
        fi
    fi
}

validate_gpu_detected() {
    if ! command -v lspci >/dev/null 2>&1; then
        echo "⚠️  lspci not available to validate GPU presence."
        return 0
    fi
    if ! lspci | grep -qi nvidia; then
        echo "❌ ERROR: No NVIDIA GPU detected."
        echo "→ Try: confirm the instance has GPUs attached before running setup."
        exit 1
    fi
}

MIN_MODEL_FREE_BYTES=$((150 * 1024 * 1024 * 1024))

check_disk_space_for_model() {
    local target_dir="$1"
    local df_target="$target_dir"
    if [ ! -d "$df_target" ]; then
        df_target="$(dirname "$target_dir")"
        while [ "$df_target" != "/" ] && [ ! -d "$df_target" ]; do
            df_target="$(dirname "$df_target")"
        done
    fi
    local available_bytes
    available_bytes=$(df -PB1 "$df_target" 2>/dev/null | awk 'NR==2 {print $4}' || true)
    if [ -z "$available_bytes" ]; then
        echo "❌ ERROR: Unable to determine free space for $target_dir"
        echo "→ Try: ensure the path exists and df is available."
        exit 1
    fi
    if [ "$available_bytes" -lt "$MIN_MODEL_FREE_BYTES" ]; then
        echo "❌ ERROR: At least 150GB free space required for model downloads."
        echo "Available: $((available_bytes / 1024 / 1024 / 1024)) GB at $target_dir"
        echo "→ Try: free disk space or set MODEL_PATH to a volume with >150GB free."
        exit 1
    fi
    echo "✅ Disk space check passed: $((available_bytes / 1024 / 1024 / 1024)) GB available."
}

download_model_with_retry() {
    local max_attempts=3
    local backoff=5
    local attempt=1
    while [ "$attempt" -le "$max_attempts" ]; do
        echo "Starting model download attempt $attempt/$max_attempts..."
        if [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] Would download $MODEL_NAME to $MODEL_PATH"
            return 0
        fi
        if HF_TOKEN="$HF_TOKEN" MODEL_NAME="$MODEL_NAME" MODEL_PATH="$MODEL_PATH" python3 << 'EOF'
import os
from huggingface_hub import snapshot_download

hf_token = os.environ["HF_TOKEN"]
model_name = os.environ["MODEL_NAME"]
model_path = os.environ["MODEL_PATH"]

print(f"Downloading {model_name} to {model_path}")
snapshot_download(
    repo_id=model_name,
    local_dir=model_path,
    token=hf_token,
    local_dir_use_symlinks=False,
    resume_download=True,
)
EOF
        then
            return 0
        fi
        echo "⚠️  Download attempt $attempt failed. Retrying after ${backoff}s..."
        sleep "$backoff"
        backoff=$((backoff * 2))
        attempt=$((attempt + 1))
    done
    echo "❌ ERROR: Model download failed after $max_attempts attempts."
    echo "→ Try: verify HF_TOKEN permissions or network connectivity, then rerun."
    return 1
}

verify_model_files() {
    if [ "$DRY_RUN" = "true" ]; then
        echo "[DRY-RUN] Skipping model file verification"
        return 0
    fi
    if [ ! -d "$MODEL_PATH" ] || [ -z "$(ls -A "$MODEL_PATH" 2>/dev/null)" ]; then
        echo "❌ ERROR: Model directory exists but no files found at $MODEL_PATH"
        echo "→ Try: rerun download or check HF credentials."
        return 1
    fi
    if [ -f "$MODEL_PATH/config.json" ] || ls "$MODEL_PATH"/*.safetensors >/dev/null 2>&1 || [ -f "$MODEL_PATH/pytorch_model.bin" ]; then
        echo "✅ Model files detected."
    else
        echo "❌ ERROR: Expected model artifacts not found in $MODEL_PATH"
        return 1
    fi
    for checksum_file in SHA256SUMS sha256sums.txt checksums.txt checksum.sha256; do
        if [ -f "$MODEL_PATH/$checksum_file" ]; then
            echo "Validating checksums using $checksum_file..."
            (cd "$MODEL_PATH" && sha256sum -c "$checksum_file") || {
                echo "❌ ERROR: Checksum verification failed for $checksum_file"
                return 1
            }
            echo "✅ Checksum verification passed."
            break
        fi
    done
    return 0
}

health_check() {
    if [ "$DRY_RUN" = "true" ]; then
        echo "[DRY-RUN] Skipping health checks"
        return 0
    fi
    local py_cmd="python"
    if [ -x "$VENV_PYTHON" ]; then
        py_cmd="$VENV_PYTHON"
    fi
    local status=0
    echo "Running health checks..."
    if ! nvidia-smi; then
        echo "❌ ERROR: nvidia-smi failed"
        echo "→ Try: ensure drivers are loaded and consider rebooting."
        status=1
    fi
    if ! nvcc --version; then
        echo "❌ ERROR: nvcc not available"
        echo "→ Try: reinstall CUDA toolkit."
        status=1
    fi
    if ! "$py_cmd" --version; then
        echo "❌ ERROR: Python missing"
        status=1
    fi
    if ! "$py_cmd" - <<'PY'
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"GPU count: {torch.cuda.device_count()}")
PY
    then
        echo "❌ ERROR: PyTorch health check failed"
        echo "→ Try: reinstall vLLM/PyTorch inside the virtual environment."
        status=1
    fi
    if ! "$py_cmd" - <<'PY'
import vllm
print(f"vLLM version: {vllm.__version__}")
PY
    then
        echo "❌ ERROR: vLLM import failed"
        echo "→ Try: reinstall vLLM inside the virtual environment."
        status=1
    fi
    if ! verify_model_files; then
        status=1
    fi
    return $status
}

# Track if reboot is needed
REBOOT_NEEDED=false

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source GPU detection utilities
# Check in same directory as script first, then in home directory
DETECT_SCRIPT="$SCRIPT_DIR/detect_gpu_info.sh"
if [ ! -f "$DETECT_SCRIPT" ]; then
    DETECT_SCRIPT="$HOME/detect_gpu_info.sh"
fi
if [ -f "$DETECT_SCRIPT" ]; then
    source "$DETECT_SCRIPT"
else
    echo "Warning: GPU detection script not found at $DETECT_SCRIPT"
    echo "Using defaults..."
    detect_gpu_count() { echo "4"; }
    detect_gpu_type() { echo "H100"; }
    detect_gpu_memory() { echo "80"; }
    detect_cuda_distribution() { echo "ubuntu2404"; }
    calculate_tensor_parallel_size() { echo "$1"; }
    calculate_gpu_memory_utilization() { echo "0.90"; }
    calculate_max_model_len() { echo "8192"; }
    calculate_max_num_seqs() { echo "256"; }
fi

validate_prerequisites

# Detect GPU information
GPU_COUNT=$(detect_gpu_count)
GPU_TYPE=$(detect_gpu_type)
GPU_MEMORY=$(detect_gpu_memory)
CUDA_DIST=$(detect_cuda_distribution)

validate_gpu_detected

MODEL_NAME="${MODEL_NAME:-RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic}"
MODEL_PATH="${MODEL_PATH:-/home/${SETUP_USER}/BM/models/scout17b-fp8dyn}"

echo "Detected GPU Configuration:"
echo "  GPU Count: $GPU_COUNT"
echo "  GPU Type: $GPU_TYPE"
echo "  GPU Memory: ${GPU_MEMORY}GB per GPU"
echo "  CUDA Distribution: $CUDA_DIST"

echo "=========================================="
echo "H100 LLM Benchmarking Setup Script"
echo "=========================================="

if is_phase_complete "system_configuration"; then
    echo "⏭️  Skipping Phase 1: System Configuration (already completed)."
else
    CURRENT_PHASE="Phase 1: System Configuration"
    echo ""
    echo "=== Phase 1: System Configuration ==="
    echo "Checking system information..."
    uname -a || true
    cat /etc/os-release || true
    lspci | grep -i nvidia || true
    free -h || true
    df -h || true
    mark_phase_complete "system_configuration"
fi

if is_phase_complete "driver_installation"; then
    echo "⏭️  Skipping Phase 2: NVIDIA Driver Installation (already completed)."
else
    CURRENT_PHASE="Phase 2: NVIDIA Driver Installation"
    echo ""
    echo "=== Phase 2: NVIDIA Driver Installation ==="

    # Clean up conflicting NVIDIA Container Toolkit GPG keys before updating
    echo "Cleaning up conflicting NVIDIA Container Toolkit configurations..."
    if [ -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]; then
        if grep -q "cloud-init.gpg.d\|nvidia-docker-container.gpg" /etc/apt/sources.list.d/nvidia-container-toolkit.list 2>/dev/null; then
            echo "Removing conflicting nvidia-container-toolkit.list..."
            run_cmd sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list
        fi
    fi
    if [ -d /etc/apt/cloud-init.gpg.d ]; then
        for gpg_file in /etc/apt/cloud-init.gpg.d/*nvidia*.gpg; do
            if [ -f "$gpg_file" ]; then
                echo "Removing conflicting GPG key: $gpg_file"
                run_cmd sudo rm -f "$gpg_file"
            fi
        done
    fi
    if [ ! -f /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg ]; then
        echo "Installing NVIDIA Container Toolkit GPG key..."
        run_cmd sudo mkdir -p /usr/share/keyrings
        if [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor --yes --batch -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
        else
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor --yes --batch -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        fi
    fi
    if [ ! -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]; then
        echo "Creating NVIDIA Container Toolkit source list..."
        if [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list"
        else
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
                sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
                sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
        fi
    fi

    echo "Updating package lists..."
    run_cmd sudo apt update || echo "⚠️  apt update had some errors (GPG keys), but continuing..."

    echo "Checking for conflicting NVIDIA packages..."
    if dpkg -l | grep -q "nvidia-driver-570\|nvidia-dkms-570\|nvidia-kernel-common-570\|nvidia-kernel-source-570"; then
        echo "⚠️  Found conflicting nvidia-driver-570 packages"
        echo "Removing all nvidia-driver-570 packages..."
        run_cmd sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge \
            nvidia-firmware-570-server \
            nvidia-firmware-570 \
            2>/dev/null || true
        run_cmd sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge \
            nvidia-driver-570 \
            nvidia-dkms-570 \
            nvidia-kernel-common-570 \
            nvidia-kernel-source-570 \
            nvidia-fabricmanager-570 \
            2>/dev/null || true
        for pkg in nvidia-firmware-570-server nvidia-firmware-570 nvidia-driver-570 nvidia-dkms-570 nvidia-kernel-common-570; do
            run_cmd sudo dpkg --remove --force-remove-reinstreq "$pkg" 2>/dev/null || true
        done
        echo "✅ Conflicting driver-570 packages removed"
    fi

    if dpkg -l | grep -q "nvidia-firmware-535-server"; then
        echo "⚠️  Found conflicting nvidia-firmware-535-server package"
        echo "Removing conflicting firmware package..."
        run_cmd sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge nvidia-firmware-535-server 2>/dev/null || true
        run_cmd sudo dpkg --remove --force-remove-reinstreq nvidia-firmware-535-server 2>/dev/null || true
        echo "✅ Conflicting firmware packages removed"
    fi

    if ls /etc/apt/preferences.d/nvidia-egl-block.* >/dev/null 2>&1; then
        echo "Removing legacy nvidia-egl preference files to allow driver deps..."
        run_cmd sudo rm -f /etc/apt/preferences.d/nvidia-egl-block.*
    fi

    if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
        echo "✅ NVIDIA driver already installed and working."
        if dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
            echo "✅ NVIDIA Driver 535-server package is installed."
        else
            echo "⚠️  Driver is working but package not found in dpkg - may need reinstall"
        fi
    else
        if dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
            echo "⚠️  NVIDIA Driver 535-server package is installed but driver is not loaded."
            echo "⚠️  A reboot is required for the driver to work."
            REBOOT_NEEDED=true
        else
            echo "Installing NVIDIA Driver 535-server..."
            echo "Running: apt update && apt --fix-broken install && apt install --no-install-recommends linux-headers + nvidia-driver-535-server"
            
            if run_cmd sudo apt update && \
               run_cmd sudo apt --fix-broken install -y && \
               run_cmd sudo apt install -y --no-install-recommends linux-headers-$(uname -r) nvidia-driver-535-server; then
                echo "✅ NVIDIA Driver 535-server installed successfully"
                echo "⚠️  WARNING: NVIDIA Driver installation requires a reboot."
                REBOOT_NEEDED=true
            else
                if dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
                    echo "⚠️  Driver installation failed, but nvidia-driver-535-server package is already installed."
                    echo "⚠️  The driver package exists but may not be properly configured."
                    echo "⚠️  A reboot may be needed to activate the driver."
                    if ! nvidia-smi &> /dev/null; then
                        REBOOT_NEEDED=true
                    fi
                else
                    echo "❌ ERROR: Failed to install NVIDIA Driver 535-server"
                    echo "→ Try: review apt output above or install manually, then rerun the script."
                fi
            fi
        fi
    fi

    echo "Verifying driver installation..."
    if ! nvidia-smi &> /dev/null; then
        echo "⚠️  WARNING: Driver installed but not yet loaded."
        echo "⚠️  A reboot is required for the driver to work."
    else
        echo "✅ Driver is working correctly"
        nvidia-smi
        nvidia-smi topo -m || true
    fi

    mark_phase_complete "driver_installation"
fi

if is_phase_complete "docker_installation"; then
    echo "⏭️  Skipping Phase 2.5: Docker Installation (already completed)."
else
    CURRENT_PHASE="Phase 2.5: Docker Installation"
    echo ""
    echo "=== Phase 2.5: Docker Installation ==="

    if command -v docker &> /dev/null && docker --version &> /dev/null; then
        echo "Docker already installed: $(docker --version)"
        if groups | grep -q docker; then
            echo "User is in docker group"
        else
            echo "Adding user to docker group..."
            run_cmd sudo usermod -aG docker "$SETUP_USER"
            if [ "$DRY_RUN" != "true" ] && [ "$DOCKER_GROUP_REEXEC" != "1" ]; then
                echo "Re-executing under docker group to refresh permissions..."
                DOCKER_GROUP_REEXEC=1 exec sg docker "$0" "${SCRIPT_ARGS[@]}"
            elif [ "$DRY_RUN" = "true" ]; then
                echo "[DRY-RUN] Skipping docker group re-exec; run script normally after enabling group."
            else
                echo "⚠️  Docker group change detected. Please log out/in if permissions are missing."
            fi
        fi
        if ! systemctl is-active --quiet docker 2>/dev/null; then
            echo "Starting Docker service..."
            run_cmd sudo systemctl start docker
            run_cmd sudo systemctl enable docker
        fi
    else
        echo "Installing Docker..."
        run_cmd sudo apt install -y ca-certificates curl
        
        run_cmd sudo install -m 0755 -d /etc/apt/keyrings
        if [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg"
        else
            curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        fi
        run_cmd sudo chmod a+r /etc/apt/keyrings/docker.gpg
        
        if [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable\" | sudo tee /etc/apt/sources.list.d/docker.list"
        else
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
                sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        fi
        
        run_cmd sudo apt update
        run_cmd sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        run_cmd sudo usermod -aG docker "$SETUP_USER"
        run_cmd sudo systemctl enable docker
        run_cmd sudo systemctl start docker
        
        echo "✅ Docker installed successfully"
        if [ "$DRY_RUN" != "true" ] && [ "$DOCKER_GROUP_REEXEC" != "1" ]; then
            DOCKER_GROUP_REEXEC=1 exec sg docker "$0" "${SCRIPT_ARGS[@]}"
        elif [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] Skipping docker group re-exec; rerun script after enabling docker group."
        else
            echo "⚠️  Note: You may need to log out and back in for docker group membership to take effect"
        fi
    fi

    echo "Verifying Docker installation..."
    docker --version || { echo "❌ ERROR: Docker not available"; exit 1; }
    docker compose version || { echo "❌ ERROR: Docker Compose not available"; exit 1; }

    mark_phase_complete "docker_installation"
fi

if is_phase_complete "cuda_setup"; then
    echo "⏭️  Skipping Phase 3: CUDA and Development Tools Setup (already completed)."
else
    CURRENT_PHASE="Phase 3: CUDA and Development Tools Setup"
    echo ""
    echo "=== Phase 3: CUDA and Development Tools Setup ==="

    if [ "$DRY_RUN" = "true" ]; then
        echo "[DRY-RUN] Would check and install CUDA toolkit"
    else
        if command -v nvcc &> /dev/null; then
            echo "CUDA version:"
            nvcc --version || true
        else
            echo "CUDA not installed yet, proceeding with installation..."
        fi

        echo "Installing CUDA Development Toolkit..."
        run_cmd sudo apt install -y nvidia-cuda-toolkit

        echo "Verifying CUDA installation..."
        nvcc --version || { echo "❌ ERROR: nvcc missing after install"; exit 1; }
    fi

    mark_phase_complete "cuda_setup"
fi

if is_phase_complete "python_env"; then
    echo "⏭️  Skipping Phase 4: Python Environment and Dependencies (already completed)."
else
    CURRENT_PHASE="Phase 4: Python Environment and Dependencies"
    echo ""
    echo "=== Phase 4: Python Environment and Dependencies ==="

    if [ "$DRY_RUN" = "true" ]; then
        echo "[DRY-RUN] Would create virtual environment and install python deps"
    else
        echo "Installing python3-venv..."
        run_cmd sudo apt install -y python3-venv

        echo "Creating virtual environment..."
        run_cmd python3 -m venv h100_benchmark_env

        echo "Activating virtual environment..."
        # shellcheck disable=SC1091
        source h100_benchmark_env/bin/activate

        echo "Upgrading pip..."
        run_cmd pip install --upgrade pip

        python --version || true

        echo "Installing vLLM..."
        run_cmd pip install vllm --no-cache-dir

        echo "Verifying PyTorch CUDA access..."
        python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')" || true
    fi

    mark_phase_complete "python_env"
fi

if is_phase_complete "cuda_error_resolution"; then
    echo "⏭️  Skipping Phase 5: CUDA Error 802 Resolution (already completed)."
else
    CURRENT_PHASE="Phase 5: CUDA Error 802 Resolution"
    echo ""
    echo "=== Phase 5: CUDA Error 802 Resolution (if needed) ==="

    NVIDIA_SMI_WORKING=false
    if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
        NVIDIA_SMI_WORKING=true
        echo "✅ nvidia-smi is working"
    else
        echo "⚠️  nvidia-smi is not working"
    fi

    CUDA_WORKING="False"
    if [ -f "h100_benchmark_env/bin/activate" ]; then
        CUDA_WORKING=$(source h100_benchmark_env/bin/activate && python -c "import torch; print(torch.cuda.is_available())" 2>/dev/null || echo "False")
        if [ "$CUDA_WORKING" = "True" ]; then
            echo "✅ PyTorch CUDA is working"
        else
            echo "⚠️  PyTorch CUDA check returned: $CUDA_WORKING"
        fi
    else
        echo "⚠️  Virtual environment not found, skipping PyTorch CUDA check"
    fi

    if [ "$NVIDIA_SMI_WORKING" != "true" ]; then
        echo "CUDA not working. Installing DCGM and Fabric Manager..."
        
        echo "Removing all nvidia-driver-570 packages..."
        run_cmd sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge \
            nvidia-driver-570 \
            nvidia-dkms-570 \
            nvidia-kernel-common-570 \
            nvidia-kernel-source-570 \
            nvidia-fabricmanager-570 \
            2>/dev/null || true
        
        echo "Removing conflicting nvidia-firmware packages..."
        run_cmd sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge \
            nvidia-firmware-570-server \
            nvidia-firmware-570 \
            2>/dev/null || true
        
        for pkg in nvidia-driver-570 nvidia-dkms-570 nvidia-kernel-common-570 nvidia-firmware-570-server nvidia-firmware-570; do
            run_cmd sudo dpkg --remove --force-remove-reinstreq "$pkg" 2>/dev/null || true
        done
        
        echo "Configuring partially installed packages..."
        run_cmd sudo DEBIAN_FRONTEND=noninteractive dpkg --configure -a || true
        
        echo "Fixing broken package dependencies..."
        run_cmd sudo DEBIAN_FRONTEND=noninteractive apt --fix-broken install -y || echo "⚠️  Package fix had issues, but continuing..."
        
        echo "Removing orphaned packages..."
        run_cmd sudo apt autoremove -y || true
        
        echo "Installing Linux headers for current kernel..."
        run_cmd sudo apt install -y linux-headers-$(uname -r) || echo "⚠️  Linux headers installation had issues, but continuing..."
        
        if ! dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
            echo "Installing NVIDIA Driver 535-server..."
            if run_cmd sudo apt install -y --no-install-recommends nvidia-driver-535-server; then
                echo "✅ Driver was just installed - reboot needed"
                REBOOT_NEEDED=true
            else
                echo "⚠️  Driver installation had issues, but continuing..."
                if dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
                    echo "⚠️  Driver package is installed but may need reboot"
                    if [ "$NVIDIA_SMI_WORKING" != "true" ]; then
                        REBOOT_NEEDED=true
                    fi
                fi
            fi
        else
            echo "✅ NVIDIA Driver 535-server already installed."
            if [ "$NVIDIA_SMI_WORKING" != "true" ]; then
                echo "⚠️  Driver package installed but not loaded - reboot needed"
                REBOOT_NEEDED=true
            else
                echo "✅ Driver is working - no reboot needed"
            fi
        fi
        
        if ! dpkg -l | grep -q "^ii.*nvidia-fabricmanager-535"; then
            echo "Installing NVIDIA Fabric Manager 535..."
            run_cmd sudo apt install -y nvidia-fabricmanager-535 || echo "⚠️  Fabric Manager installation had issues, but continuing..."
        else
            echo "NVIDIA Fabric Manager already installed."
        fi
        
        echo "Starting Fabric Manager service..."
        run_cmd sudo systemctl start nvidia-fabricmanager 2>/dev/null || true
        run_cmd sudo systemctl enable nvidia-fabricmanager 2>/dev/null || true
        
        echo "✅ DCGM and Fabric Manager installation attempted."
        echo "⚠️  NOTE: If CUDA still doesn't work, a reboot may be needed, but continuing workflow..."
        
        if command -v nvidia-smi &> /dev/null; then
            nvidia-smi || echo "⚠️  nvidia-smi still not working - reboot required"
        fi
        
        if [ -f "h100_benchmark_env/bin/activate" ]; then
            # shellcheck disable=SC1091
            source h100_benchmark_env/bin/activate && python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')" 2>/dev/null || echo "⚠️  PyTorch CUDA check failed"
        fi
    else
        echo "✅ nvidia-smi is working - skipping Phase 5 (no driver reinstall needed)"
        if [ "$CUDA_WORKING" != "True" ]; then
            echo "⚠️  Note: PyTorch CUDA check returned False, but nvidia-smi works."
            echo "⚠️  This may be a PyTorch/environment issue, not a driver issue."
        fi
    fi

    mark_phase_complete "cuda_error_resolution"
fi

if is_phase_complete "model_preparation"; then
    echo "⏭️  Skipping Phase 6: Model Preparation (already completed)."
else
    CURRENT_PHASE="Phase 6: Model Preparation"
    echo ""
    echo "=== Phase 6: Model Preparation ==="

    validate_environment
    HF_TOKEN="${HF_TOKEN:?ERROR: HF_TOKEN must be set}"
    MODEL_NAME="${MODEL_NAME:-RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic}"
    MODEL_PATH="${MODEL_PATH:-/home/${SETUP_USER}/BM/models/scout17b-fp8dyn}"

    echo "Model Configuration:"
    echo "  Model Name: $MODEL_NAME"
    echo "  Model Path: $MODEL_PATH"

    MODEL_DIR="$(dirname "$MODEL_PATH")"
    check_disk_space_for_model "$MODEL_DIR"

    if [ "$DRY_RUN" = "true" ]; then
        echo "[DRY-RUN] Would create model directory at $MODEL_DIR and download $MODEL_NAME"
    else
        echo "Creating model directory..."
        run_cmd mkdir -p "$MODEL_DIR"
        run_cmd sudo chown -R "$SETUP_USER":"$SETUP_USER" "$MODEL_DIR" 2>/dev/null || true
        run_cmd mkdir -p "$MODEL_PATH"
        run_cmd sudo chown -R "$SETUP_USER":"$SETUP_USER" "$MODEL_PATH" 2>/dev/null || true
        cd "$MODEL_DIR"
        pwd

        echo "Installing Hugging Face CLI..."
        run_cmd pip install --user huggingface_hub
        export PATH="$HOME/.local/bin:$PATH"

        echo "Logging in to Hugging Face..."
        if ! python3 - <<EOF
from huggingface_hub import login
import os
token = os.environ.get("HF_TOKEN")
if not token:
    raise SystemExit(1)
login(token=token, add_to_git_credential=True)
print("HF login successful")
EOF
        then
            echo "❌ ERROR: Hugging Face authentication failed."
            echo "→ Try: ensure HF_TOKEN has repo access."
            exit 1
        fi

        echo ""
        echo "=========================================="
        echo "Hugging Face Authenticated"
        echo "=========================================="

        echo "Downloading $MODEL_NAME to $MODEL_PATH..."
        if download_model_with_retry; then
            echo "✅ Model download completed successfully!"
            run_cmd sudo chown -R "$SETUP_USER":"$SETUP_USER" "$MODEL_PATH" 2>/dev/null || true
            if verify_model_files; then
                echo "✅ Model files verified!"
                echo "Model directory size:"
                du -sh "$MODEL_PATH" || true
            else
                exit 1
            fi
        else
            exit 1
        fi
    fi
    echo "=========================================="
    mark_phase_complete "model_preparation"
fi

if is_phase_complete "monitoring_setup"; then
    echo "⏭️  Skipping Phase 7: Monitoring Setup (already completed)."
else
    CURRENT_PHASE="Phase 7: Monitoring Setup"
    echo ""
    echo "=== Phase 7: Monitoring Setup (Optional) ==="

    INSTALL_DCGM="yes"

    if [ "$INSTALL_DCGM" = "yes" ]; then
        echo "Installing DCGM..."
        
        echo "Checking for conflicting repository configurations..."
        if [ -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]; then
            echo "Found nvidia-container-toolkit.list, checking for conflicts..."
            if [ "$DRY_RUN" = "true" ]; then
                echo "[DRY-RUN] sudo sed -i '/nvidia.github.io\\/libnvidia-container/d' /etc/apt/sources.list.d/nvidia-container-toolkit.list"
            else
                sudo sed -i '/nvidia.github.io\/libnvidia-container/d' /etc/apt/sources.list.d/nvidia-container-toolkit.list 2>/dev/null || true
            fi
            if [ ! -s /etc/apt/sources.list.d/nvidia-container-toolkit.list ] || ! grep -q "^[^#]" /etc/apt/sources.list.d/nvidia-container-toolkit.list 2>/dev/null; then
                run_cmd sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list
            fi
        fi
        
        if [ -f /etc/apt/cloud-init.gpg.d/nvidia-docker-container.gpg ]; then
            echo "Removing conflicting cloud-init GPG key..."
            run_cmd sudo rm -f /etc/apt/cloud-init.gpg.d/nvidia-docker-container.gpg
        fi
        
        if dpkg -l | grep -q "^ii.*cuda-keyring"; then
            echo "CUDA keyring already installed, skipping installation..."
        else
            echo "Installing CUDA keyring for $CUDA_DIST..."
            register_temp_path "/tmp/cuda-keyring.deb"
            if [ "$DRY_RUN" = "true" ]; then
                echo "[DRY-RUN] wget -q \"https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_DIST}/x86_64/cuda-keyring_1.1-1_all.deb\" -O /tmp/cuda-keyring.deb"
                echo "[DRY-RUN] sudo dpkg -i /tmp/cuda-keyring.deb"
            else
                wget -q "https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_DIST}/x86_64/cuda-keyring_1.1-1_all.deb" -O /tmp/cuda-keyring.deb
                sudo dpkg -i /tmp/cuda-keyring.deb
            fi
        fi

        # Avoid apt "Signed-By" conflicts by ensuring only one active CUDA repo entry.
        # Some images ship a preconfigured CUDA repo that points to the same URL but uses a different keyring
        # (e.g., /usr/share/keyrings/cudatools.gpg). apt will refuse to read sources when they conflict.
        CUDA_REPO_URL="https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_DIST}/x86_64/"
        CUDA_KEYRING="/usr/share/keyrings/cuda-archive-keyring.gpg"
        if [ ! -f "$CUDA_KEYRING" ] && [ -f /etc/apt/keyrings/cuda-archive-keyring.gpg ]; then
            CUDA_KEYRING="/etc/apt/keyrings/cuda-archive-keyring.gpg"
        fi
        if [ -f "$CUDA_KEYRING" ]; then
            echo "Normalizing CUDA apt repo to use keyring: $CUDA_KEYRING"
            echo "deb [signed-by=${CUDA_KEYRING}] ${CUDA_REPO_URL} /" | sudo tee /etc/apt/sources.list.d/omniference-cuda.list >/dev/null

            # Disable other CUDA repo entries (keep file content, just comment matching lines)
            for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
                if [ -f "$source_file" ] && [ "$source_file" != "/etc/apt/sources.list.d/omniference-cuda.list" ]; then
                    if grep -q "${CUDA_REPO_URL}" "$source_file" 2>/dev/null; then
                        sudo sed -i "\\#${CUDA_REPO_URL}# s|^[[:space:]]*deb[[:space:]]|# deb |" "$source_file" 2>/dev/null || true
                    fi
                fi
            done
        fi
        
        echo "Updating package lists..."
        if [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] sudo apt update"
        else
            if ! sudo apt update 2>&1 | grep -q "conflict\|signed-by"; then
                echo "Package lists updated successfully"
            else
                echo "Warning: Some repository conflicts detected, but continuing..."
                for source_file in /etc/apt/sources.list.d/*.list; do
                    if [ -f "$source_file" ] && grep -q "nvidia.github.io/libnvidia-container" "$source_file" 2>/dev/null; then
                        echo "Fixing conflict in $source_file..."
                        sudo sed -i '/nvidia.github.io\/libnvidia-container/d' "$source_file"
                    fi
                done
                sudo apt update || echo "apt update had issues, but continuing with DCGM installation..."
            fi
        fi
        
        # Check if DCGM is available in current repos, if not add NVIDIA CUDA repo
        if ! apt-cache show datacenter-gpu-manager &>/dev/null; then
            echo "datacenter-gpu-manager not found in current repos, adding NVIDIA CUDA repo..."
            # If cuda-keyring is present, it should already provide the repo; just retry apt update.
            sudo apt-get update -qq 2>/dev/null || true
        fi
        
        if run_cmd sudo apt install -y datacenter-gpu-manager; then
            echo "✅ DCGM installed successfully"
        else
            echo "⚠️  DCGM installation had issues"
        fi
        
        echo "Configuring NVIDIA profiling permissions for advanced metrics..."
        if ! grep -qs "NVreg_RestrictProfilingToAdminUsers" /etc/modprobe.d/omniference-nvidia.conf 2>/dev/null; then
            if [ "$DRY_RUN" = "true" ]; then
                echo "[DRY-RUN] echo \"options nvidia NVreg_RestrictProfilingToAdminUsers=0\" | sudo tee /etc/modprobe.d/omniference-nvidia.conf"
            else
                echo "options nvidia NVreg_RestrictProfilingToAdminUsers=0" | sudo tee /etc/modprobe.d/omniference-nvidia.conf >/dev/null
            fi
            if command -v update-initramfs &>/dev/null; then
                echo "Updating initramfs (this may take a minute)..."
                run_cmd sudo update-initramfs -u || echo "⚠️  initramfs update had issues (non-critical)"
            fi
            echo "✅ Profiling permissions configured"
            echo "⚠️  NOTE: A reboot is required for profiling permissions to take effect."
            REBOOT_NEEDED=true
        else
            echo "✅ Profiling permissions already configured"
            if [ -f /proc/driver/nvidia/params ]; then
                CURRENT_PROFILING=$(grep -o "RmProfilingAdminOnly:[[:space:]]*[0-9]*" /proc/driver/nvidia/params 2>/dev/null | awk '{print $2}' || echo "1")
                if [ "$CURRENT_PROFILING" = "1" ]; then
                    echo "⚠️  Profiling is still restricted (RmProfilingAdminOnly=1) - reboot needed"
                    REBOOT_NEEDED=true
                else
                    echo "✅ Profiling is already enabled (RmProfilingAdminOnly=0) - no reboot needed"
                fi
            else
                echo "⚠️  Cannot check current profiling status - assuming reboot may be needed"
            fi
        fi
        
        # Start and enable DCGM (service name may be 'nvidia-dcgm' or 'dcgm')
        if systemctl list-unit-files | grep -q nvidia-dcgm; then
            run_cmd sudo systemctl start nvidia-dcgm
            run_cmd sudo systemctl enable nvidia-dcgm
        else
            run_cmd sudo systemctl start dcgm || true
            run_cmd sudo systemctl enable dcgm || true
        fi
        
        if command -v dcgmi &>/dev/null; then
            dcgmi discovery -l && echo "✅ DCGM installed and running."
        else
            echo "⚠️  DCGM installed but dcgmi command not available"
        fi
    else
        echo "Skipping DCGM installation as INSTALL_DCGM is not 'yes'."
    fi

    mark_phase_complete "monitoring_setup"
fi

CURRENT_PHASE="Final Verification"
echo ""
echo "=== Final Verification ==="
echo "Verifying system setup..."

PY_CMD="python"
if [ -x "$VENV_PYTHON" ]; then
    PY_CMD="$VENV_PYTHON"
fi

VERIFICATION_STATUS=0
if [ "$DRY_RUN" = "true" ]; then
    echo "[DRY-RUN] Skipping verification commands"
else
    if ! nvidia-smi; then
        echo "❌ ERROR: nvidia-smi failed during verification"
        VERIFICATION_STATUS=1
    fi
    if ! nvcc --version; then
        echo "❌ ERROR: nvcc unavailable during verification"
        VERIFICATION_STATUS=1
    fi
    "$PY_CMD" --version || true
    if ! "$PY_CMD" -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"; then
        echo "❌ ERROR: PyTorch verification failed"
        VERIFICATION_STATUS=1
    fi
    if ! "$PY_CMD" -c "import vllm; print(f'vLLM version: {vllm.__version__}')"; then
        echo "❌ ERROR: vLLM verification failed"
        VERIFICATION_STATUS=1
    fi
    if ! verify_model_files; then
        VERIFICATION_STATUS=1
    fi
    if ! health_check; then
        VERIFICATION_STATUS=1
    fi
fi

if [ "$VERIFICATION_STATUS" -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "Setup Complete!"
    echo "=========================================="
    echo "Virtual environment: $SCRIPT_DIR/h100_benchmark_env"
    echo "To activate: source $SCRIPT_DIR/h100_benchmark_env/bin/activate"
    echo ""
    echo "Next steps:"
    echo "1. Model $MODEL_NAME is available at $MODEL_PATH"
    echo "2. Run benchmarks with your benchmark script"
    echo "=========================================="
    echo ""
else
    echo "❌ ERROR: One or more verification checks failed."
    echo "→ Try: review logs at $LOG_FILE and rerun after fixing issues."
    exit 1
fi

if [ "$REBOOT_NEEDED" = true ]; then
    echo "Reboot required - please run: sudo reboot"
else
    echo "✅ No reboot needed - system is ready to use"
fi
