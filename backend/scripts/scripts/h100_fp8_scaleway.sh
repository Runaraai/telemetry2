#!/bin/bash
# GPU LLM Benchmarking Setup Script (Adaptive for H100, A100, etc.)
# Based on successful commands from H100_Command_Log.md
# This script automatically detects GPU type and count and adapts configuration

# Don't exit on error immediately - we'll handle errors per section
set +e  # Continue on error (we'll check exit codes manually)

# Safer apt wrappers (Scaleway images sometimes require allow-downgrades for NVIDIA packages)
APT_GET="sudo DEBIAN_FRONTEND=noninteractive apt-get"
ALLOW_DOWNGRADE_CONF="/etc/apt/apt.conf.d/99allow-downgrades-omniference"

# Ensure allow-downgrades is set during this run (Scaleway images frequently need it for NVIDIA repos)
if [ ! -f "$ALLOW_DOWNGRADE_CONF" ]; then
    echo 'APT::Get::AllowDowngrades "true";' | sudo tee "$ALLOW_DOWNGRADE_CONF" >/dev/null
    # Cleanup on exit
    trap 'sudo rm -f "$ALLOW_DOWNGRADE_CONF" 2>/dev/null || true' EXIT
fi

apt_update() {
    $APT_GET update "$@"
}
apt_install() {
    # Allow downgrades because upstream repos can serve slightly older toolkit/DCGM versions
    $APT_GET install -y --allow-downgrades "$@"
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

# Detect GPU information
GPU_COUNT=$(detect_gpu_count)
GPU_TYPE=$(detect_gpu_type)
GPU_MEMORY=$(detect_gpu_memory)
CUDA_DIST=$(detect_cuda_distribution)

echo "Detected GPU Configuration:"
echo "  GPU Count: $GPU_COUNT"
echo "  GPU Type: $GPU_TYPE"
echo "  GPU Memory: ${GPU_MEMORY}GB per GPU"
echo "  CUDA Distribution: $CUDA_DIST"

echo "=========================================="
echo "H100 LLM Benchmarking Setup Script (Scaleway)"
echo "=========================================="

# Phase 1: System Configuration
echo ""
echo "=== Phase 1: System Configuration ==="

# System information checks
echo "Checking system information..."
uname -a
cat /etc/os-release
lspci | grep -i nvidia
free -h
df -h

# Phase 2: NVIDIA Driver Installation
echo ""
echo "=== Phase 2: NVIDIA Driver Installation ==="

# Clean up conflicting NVIDIA Container Toolkit GPG keys before updating
echo "Cleaning up conflicting NVIDIA Container Toolkit configurations..."
if [ -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]; then
    # Check if it references old cloud-init GPG key
    if grep -q "cloud-init.gpg.d\|nvidia-docker-container.gpg" /etc/apt/sources.list.d/nvidia-container-toolkit.list 2>/dev/null; then
        echo "Removing conflicting nvidia-container-toolkit.list..."
        sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list
    fi
fi
# Remove any GPG keys in cloud-init directory that might conflict
if [ -d /etc/apt/cloud-init.gpg.d ]; then
    for gpg_file in /etc/apt/cloud-init.gpg.d/*nvidia*.gpg; do
        if [ -f "$gpg_file" ]; then
            echo "Removing conflicting GPG key: $gpg_file"
            sudo rm -f "$gpg_file"
        fi
    done
fi
# Ensure the correct GPG keyring exists
if [ ! -f /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg ]; then
    echo "Installing NVIDIA Container Toolkit GPG key..."
    sudo mkdir -p /usr/share/keyrings
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor --yes --batch -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
fi
# Recreate the source list with correct GPG key reference if it doesn't exist
if [ ! -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]; then
    echo "Creating NVIDIA Container Toolkit source list..."
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
fi

# Update package lists (ignore GPG errors for now - packages may already be installed)
echo "Updating package lists..."
apt_update || echo "⚠️  apt update had some errors (GPG keys), but continuing..."

# Check for conflicting nvidia packages before driver installation
echo "Checking for conflicting NVIDIA packages..."
# Remove ALL nvidia-driver-570 packages first (they conflict with 535-server)
    if dpkg -l | grep -q "nvidia-driver-570\|nvidia-dkms-570\|nvidia-kernel-common-570\|nvidia-kernel-source-570"; then
        echo "⚠️  Found conflicting nvidia-driver-570 packages"
        echo "Removing all nvidia-driver-570 packages..."
        # First remove firmware packages that conflict
        $APT_GET remove -y --purge \
            nvidia-firmware-570-server \
            nvidia-firmware-570 \
            2>/dev/null || true
        # Then remove driver packages
        $APT_GET remove -y --purge \
            nvidia-driver-570 \
            nvidia-dkms-570 \
            nvidia-kernel-common-570 \
            nvidia-kernel-source-570 \
            nvidia-fabricmanager-570 \
        2>/dev/null || true
    # Force remove with dpkg if apt didn't work
    for pkg in nvidia-firmware-570-server nvidia-firmware-570 nvidia-driver-570 nvidia-dkms-570 nvidia-kernel-common-570; do
        sudo dpkg --remove --force-remove-reinstreq "$pkg" 2>/dev/null || true
    done
    echo "✅ Conflicting driver-570 packages removed"
fi

# Remove any remaining conflicting firmware packages
if dpkg -l | grep -q "nvidia-firmware-535-server"; then
    echo "⚠️  Found conflicting nvidia-firmware-535-server package"
    echo "Removing conflicting firmware package..."
    $APT_GET remove -y --purge nvidia-firmware-535-server 2>/dev/null || true
    sudo dpkg --remove --force-remove-reinstreq nvidia-firmware-535-server 2>/dev/null || true
    echo "✅ Conflicting firmware packages removed"
fi

# Remove legacy EGL preference pinning that blocks driver deps
if ls /etc/apt/preferences.d/nvidia-egl-block.* >/dev/null 2>&1; then
    echo "Removing legacy nvidia-egl preference files to allow driver deps..."
    sudo rm -f /etc/apt/preferences.d/nvidia-egl-block.*
fi

# Check if NVIDIA driver is already installed and working
if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
    echo "✅ NVIDIA driver already installed and working."
    # Check if driver package is installed
    if dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
        echo "✅ NVIDIA Driver 535-server package is installed."
    else
        echo "⚠️  Driver is working but package not found in dpkg - may need reinstall"
    fi
else
    # Check if driver package is already installed (might just need reboot)
    if dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
        echo "⚠️  NVIDIA Driver 535-server package is installed but driver is not loaded."
        echo "⚠️  A reboot is required for the driver to work."
        REBOOT_NEEDED=true
    else
        # Install driver using the standard sequence: update, fix-broken, install headers+driver
        # Use --no-install-recommends to avoid pulling in conflicting EGL packages
        echo "Installing NVIDIA Driver 535-server..."
        echo "Running: apt update && apt --fix-broken install && apt install --no-install-recommends linux-headers + nvidia-driver-535-server"
        
        # Try to install the driver
        if apt_update && \
           $APT_GET --fix-broken install -y && \
           $APT_GET install -y --allow-downgrades --no-install-recommends linux-headers-$(uname -r) nvidia-driver-535-server; then
            echo "✅ NVIDIA Driver 535-server installed successfully"
            echo "⚠️  WARNING: NVIDIA Driver installation requires a reboot."
            echo "⚠️  The driver has been installed, but the system needs to reboot for it to take effect."
            REBOOT_NEEDED=true
        else
            # Installation failed - check if package is already installed
            if dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
                echo "⚠️  Driver installation failed, but nvidia-driver-535-server package is already installed."
                echo "⚠️  The driver package exists but may not be properly configured."
                echo "⚠️  A reboot may be needed to activate the driver."
                # Only set reboot if driver is not loaded (package installed but not working)
                if ! nvidia-smi &> /dev/null; then
                    REBOOT_NEEDED=true
                fi
            else
                echo "❌ ERROR: Failed to install NVIDIA Driver 535-server"
                echo "⚠️  The driver installation failed. Please check the error messages above."
                echo "⚠️  Continuing with setup, but GPU operations will fail until driver is installed."
                # Don't set REBOOT_NEEDED if installation failed
            fi
        fi
    fi
fi

# Verify driver installation
echo "Verifying driver installation..."
if ! nvidia-smi &> /dev/null; then
    echo "⚠️  WARNING: Driver installed but not yet loaded."
    echo "⚠️  A reboot is required for the driver to work."
    echo "⚠️  Continuing with setup, but GPU operations will fail until reboot."
else
    echo "✅ Driver is working correctly"
    nvidia-smi
    nvidia-smi topo -m
fi

# Phase 2.5: Docker Installation
echo ""
echo "=== Phase 2.5: Docker Installation ==="

# Check if Docker is already installed
if command -v docker &> /dev/null && docker --version &> /dev/null; then
    echo "Docker already installed: $(docker --version)"
    # Check if user is in docker group
    if groups | grep -q docker; then
        echo "User is in docker group"
    else
        echo "Adding user to docker group..."
        sudo usermod -aG docker "$USER"
        echo "⚠️  Note: You may need to log out and back in for docker group membership to take effect"
    fi
    # Start Docker service if not running
    if ! sudo systemctl is-active --quiet docker; then
        echo "Starting Docker service..."
        sudo systemctl start docker
        sudo systemctl enable docker
    fi
else
    echo "Installing Docker..."
    # Install prerequisites
    apt_install ca-certificates curl
    
    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    
    # Add Docker repository
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Install Docker
    apt_update
    apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    # Add user to docker group
    sudo usermod -aG docker "$USER"
    
    # Start and enable Docker
    sudo systemctl enable docker
    sudo systemctl start docker
    
    echo "✅ Docker installed successfully"
    echo "⚠️  Note: You may need to log out and back in for docker group membership to take effect"
fi

# Verify Docker installation
echo "Verifying Docker installation..."
docker --version
docker compose version

# Phase 3: CUDA and Development Tools Setup
echo ""
echo "=== Phase 3: CUDA and Development Tools Setup ==="

# Check CUDA version (if installed)
if command -v nvcc &> /dev/null; then
    echo "CUDA version:"
    nvcc --version
else
    echo "CUDA not installed yet, proceeding with installation..."
fi

# Install CUDA Development Toolkit
echo "Installing CUDA Development Toolkit..."
apt_install nvidia-cuda-toolkit

# Verify CUDA installation
echo "Verifying CUDA installation..."
nvcc --version

# Phase 4: Python Environment and Dependencies
echo ""
echo "=== Phase 4: Python Environment and Dependencies ==="

# Install python3-venv if not already installed
echo "Installing python3-venv..."
apt_install python3-venv

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv h100_benchmark_env

# Activate virtual environment
echo "Activating virtual environment..."
source h100_benchmark_env/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Verify Python version
python --version

# Install vLLM (this will install compatible PyTorch automatically)
echo "Installing vLLM..."
pip install vllm --no-cache-dir

# Verify PyTorch CUDA access
echo "Verifying PyTorch CUDA access..."
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"

# Phase 5: CUDA Error 802 Resolution (if needed)
echo ""
echo "=== Phase 5: CUDA Error 802 Resolution (if needed) ==="

# First check if nvidia-smi is working (more reliable than PyTorch check)
NVIDIA_SMI_WORKING=false
if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
    NVIDIA_SMI_WORKING=true
    echo "✅ nvidia-smi is working"
else
    echo "⚠️  nvidia-smi is not working"
fi

# Check if CUDA is working in PyTorch (only if venv is activated and torch is installed)
CUDA_WORKING="False"
if [ -f "h100_benchmark_env/bin/activate" ]; then
    # Activate venv and check CUDA
    CUDA_WORKING=$(source h100_benchmark_env/bin/activate && python -c "import torch; print(torch.cuda.is_available())" 2>/dev/null || echo "False")
    if [ "$CUDA_WORKING" = "True" ]; then
        echo "✅ PyTorch CUDA is working"
    else
        echo "⚠️  PyTorch CUDA check returned: $CUDA_WORKING"
    fi
else
    echo "⚠️  Virtual environment not found, skipping PyTorch CUDA check"
fi

# Only proceed with Phase 5 if nvidia-smi is NOT working (driver issue)
# If nvidia-smi works but PyTorch CUDA doesn't, it's likely a PyTorch/environment issue, not a driver issue
if [ "$NVIDIA_SMI_WORKING" != "true" ]; then
    echo "CUDA not working. Installing DCGM and Fabric Manager..."
    
    # Aggressively remove ALL nvidia-driver-570 packages first
    echo "Removing all nvidia-driver-570 packages..."
    $APT_GET remove -y --purge \
        nvidia-driver-570 \
        nvidia-dkms-570 \
        nvidia-kernel-common-570 \
        nvidia-kernel-source-570 \
        nvidia-fabricmanager-570 \
        2>/dev/null || true
    
    # Remove conflicting firmware packages
    echo "Removing conflicting nvidia-firmware packages..."
    $APT_GET remove -y --purge \
        nvidia-firmware-570-server \
        nvidia-firmware-570 \
        2>/dev/null || true
    
    # Force remove with dpkg if apt didn't work
    for pkg in nvidia-driver-570 nvidia-dkms-570 nvidia-kernel-common-570 nvidia-firmware-570-server nvidia-firmware-570; do
        sudo dpkg --remove --force-remove-reinstreq "$pkg" 2>/dev/null || true
    done
    
    # Clean up any partially installed packages first
    echo "Configuring partially installed packages..."
    sudo DEBIAN_FRONTEND=noninteractive dpkg --configure -a 2>&1 | grep -v "^\(Reading\|Building\|Reading state\)" || true
    
    # Fix package dependencies (non-interactive)
    echo "Fixing broken package dependencies..."
    $APT_GET --fix-broken install -y 2>&1 | grep -v "^\(Reading\|Building\|Reading state\)" || echo "⚠️  Package fix had issues, but continuing..."
    
    # Remove any orphaned packages
    echo "Removing orphaned packages..."
    $APT_GET autoremove -y 2>&1 | grep -v "^\(Reading\|Building\|Reading state\)" || true
    
    # Install Linux headers first (required for driver compilation)
    echo "Installing Linux headers for current kernel..."
    $APT_GET install -y --allow-downgrades linux-headers-$(uname -r) || echo "⚠️  Linux headers installation had issues, but continuing..."
    
    # Install NVIDIA Driver 535-server (complete) - skip if already installed
    # Use --no-install-recommends to avoid pulling in conflicting EGL packages
    if ! dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
        echo "Installing NVIDIA Driver 535-server..."
        if $APT_GET install -y --allow-downgrades --no-install-recommends nvidia-driver-535-server; then
            echo "✅ Driver was just installed - reboot needed"
            REBOOT_NEEDED=true
        else
            echo "⚠️  Driver installation had issues, but continuing..."
            # Check if package got installed despite the error
            if dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
                echo "⚠️  Driver package is installed but may need reboot"
                if [ "$NVIDIA_SMI_WORKING" != "true" ]; then
                    REBOOT_NEEDED=true
                fi
            fi
        fi
    else
        echo "✅ NVIDIA Driver 535-server already installed."
        # If driver is installed but nvidia-smi doesn't work, we need reboot
        if [ "$NVIDIA_SMI_WORKING" != "true" ]; then
            echo "⚠️  Driver package installed but not loaded - reboot needed"
            REBOOT_NEEDED=true
        else
            echo "✅ Driver is working - no reboot needed"
        fi
    fi
    
    # Install NVIDIA Fabric Manager - skip if already installed
    if ! dpkg -l | grep -q "^ii.*nvidia-fabricmanager-535"; then
        echo "Installing NVIDIA Fabric Manager 535..."
        $APT_GET install -y --allow-downgrades nvidia-fabricmanager-535 || echo "⚠️  Fabric Manager installation had issues, but continuing..."
    else
        echo "NVIDIA Fabric Manager already installed."
    fi
    
    # Start Fabric Manager service (don't reboot - continue with workflow)
    echo "Starting Fabric Manager service..."
    sudo systemctl start nvidia-fabricmanager 2>/dev/null || true
    sudo systemctl enable nvidia-fabricmanager 2>/dev/null || true
    
    echo "✅ DCGM and Fabric Manager installation attempted."
    echo "⚠️  NOTE: If CUDA still doesn't work, a reboot may be needed, but continuing workflow..."
    
    # Verify GPU status
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi || echo "⚠️  nvidia-smi still not working - reboot required"
    fi
    
    # Test PyTorch CUDA access (only if venv exists)
    if [ -f "h100_benchmark_env/bin/activate" ]; then
        source h100_benchmark_env/bin/activate && python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')" 2>/dev/null || echo "⚠️  PyTorch CUDA check failed"
    fi
else
    echo "✅ nvidia-smi is working - skipping Phase 5 (no driver reinstall needed)"
    if [ "$CUDA_WORKING" != "True" ]; then
        echo "⚠️  Note: PyTorch CUDA check returned False, but nvidia-smi works."
        echo "⚠️  This may be a PyTorch/environment issue, not a driver issue."
    fi
fi

# Phase 6: Model Preparation
echo ""
echo "=== Phase 6: Model Preparation ==="

# Get model name and path from environment variables (with defaults)
# Scaleway instances typically run as root and have /scratch with more space
MODEL_NAME="${MODEL_NAME:-RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic}"
# Use /scratch if available (5.8TB), otherwise fall back to /root
if [ -d "/scratch" ] && [ -w "/scratch" ]; then
    MODEL_PATH="${MODEL_PATH:-/scratch/BM/models/scout17b-fp8dyn}"
else
    MODEL_PATH="${MODEL_PATH:-/root/BM/models/scout17b-fp8dyn}"
fi

echo "Model Configuration:"
echo "  Model Name: $MODEL_NAME"
echo "  Model Path: $MODEL_PATH"

# Create model directory with proper permissions
echo "Creating model directory..."
MODEL_DIR="$(dirname "$MODEL_PATH")"
mkdir -p "$MODEL_DIR"
# Scaleway instances run as root, so ensure root owns the directory
sudo chown -R root:root "$MODEL_DIR" 2>/dev/null || chown -R root:root "$MODEL_DIR" 2>/dev/null || true
# Create the specific model directory
mkdir -p "$MODEL_PATH"
sudo chown -R root:root "$MODEL_PATH" 2>/dev/null || chown -R root:root "$MODEL_PATH" 2>/dev/null || true
cd "$MODEL_DIR"
pwd

# Activate virtual environment (ensure it's active for Hugging Face operations)
VENV_DIR="$HOME/h100_benchmark_env"
if [ -f "$VENV_DIR/bin/activate" ]; then
    echo "Activating virtual environment for model download..."
    source "$VENV_DIR/bin/activate"
else
    echo "⚠️  Warning: Virtual environment not found at $VENV_DIR. Creating one..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    # Reinstall vLLM if venv was recreated (it includes PyTorch)
    echo "Installing vLLM (includes PyTorch)..."
    pip install vllm --no-cache-dir || echo "⚠️  vLLM installation had issues, but continuing..."
fi

# Verify we're using the venv Python
echo "Using Python: $(which python)"
echo "Python version: $(python --version)"

# Install Hugging Face CLI
echo "Installing Hugging Face CLI..."
pip install huggingface_hub

# Login to Hugging Face with token
echo "Logging in to Hugging Face..."
if [ -z "${HF_TOKEN:-}" ]; then
    echo "Warning: HF_TOKEN is not set. Public models may still download, but gated/private models will fail."
else
    huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential || echo "Warning: Hugging Face login had issues, continuing..."
fi

echo ""
echo "=========================================="
echo "Hugging Face Authenticated"
echo "=========================================="

# Download model using Python API (more reliable for permissions)
echo "Downloading $MODEL_NAME to $MODEL_PATH..."
python << EOF
import os
from huggingface_hub import snapshot_download

model_name = os.environ.get('MODEL_NAME', '$MODEL_NAME')
model_path = os.environ.get('MODEL_PATH', '$MODEL_PATH')
hf_token = os.environ.get('HF_TOKEN')

print(f'Starting model download for {model_name}...')
print(f'Destination: {model_path}')
print('Using Hugging Face token from environment:' + (' yes' if hf_token else ' no'))

try:
    snapshot_download(
        repo_id=model_name,
        local_dir=model_path,
        token=hf_token,
        local_dir_use_symlinks=False
    )
    print('✅ Model download complete!')
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
    exit(1)
EOF

DOWNLOAD_EXIT_CODE=$?
if [ $DOWNLOAD_EXIT_CODE -eq 0 ]; then
    echo "✅ Model download completed successfully!"
    # Fix permissions (Scaleway uses root user)
    sudo chown -R root:root "$MODEL_PATH" 2>/dev/null || chown -R root:root "$MODEL_PATH" 2>/dev/null || true
    # Verify model files exist
    if [ -f "$MODEL_PATH/config.json" ] || [ -f "$MODEL_PATH/model.safetensors" ] || [ -f "$MODEL_PATH/pytorch_model.bin" ] || [ -d "$MODEL_PATH" ] && [ "$(ls -A $MODEL_PATH 2>/dev/null)" ]; then
        echo "✅ Model files verified!"
        echo "Model directory size:"
        du -sh "$MODEL_PATH"
    else
        echo "❌ ERROR: Model directory exists but no model files found!"
        echo "Checking directory contents:"
        ls -la "$MODEL_PATH" | head -10
        exit 1
    fi
else
    echo ""
    echo "❌ ERROR: Model download failed with exit code $DOWNLOAD_EXIT_CODE!"
    echo "The model repository '$MODEL_NAME' may not exist or may require different permissions."
    echo "Please verify the correct model name and download manually:"
    echo "  cd $MODEL_DIR"
    echo "  source ~/h100_benchmark_env/bin/activate"
    echo "  huggingface-cli download $MODEL_NAME --local-dir $MODEL_PATH"
    echo ""
    exit 1
fi
echo "=========================================="

# Phase 7: Monitoring Setup (Optional)
echo ""
echo "=== Phase 7: Monitoring Setup (Optional) ==="

# Auto-install DCGM for monitoring (set to 'no' to skip)
INSTALL_DCGM="yes"

if [ "$INSTALL_DCGM" = "yes" ]; then
    # Install DCGM
    echo "Installing DCGM..."
    
    # Clean up any conflicting NVIDIA Container Toolkit configurations that might conflict with CUDA keyring
    echo "Checking for conflicting repository configurations..."
    if [ -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]; then
        echo "Found nvidia-container-toolkit.list, checking for conflicts..."
        # Remove any lines that reference libnvidia-container (these conflict with CUDA repos)
        sudo sed -i '/nvidia.github.io\/libnvidia-container/d' /etc/apt/sources.list.d/nvidia-container-toolkit.list 2>/dev/null || true
        # If file is now empty or only has comments, remove it
        if [ ! -s /etc/apt/sources.list.d/nvidia-container-toolkit.list ] || ! grep -q "^[^#]" /etc/apt/sources.list.d/nvidia-container-toolkit.list 2>/dev/null; then
            sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list
        fi
    fi
    
    # Remove conflicting cloud-init GPG keys if they exist
    if [ -f /etc/apt/cloud-init.gpg.d/nvidia-docker-container.gpg ]; then
        echo "Removing conflicting cloud-init GPG key..."
        sudo rm -f /etc/apt/cloud-init.gpg.d/nvidia-docker-container.gpg
    fi

    # Remove stale CUDA repo entries that use a different keyring (e.g., cudatools.gpg) to avoid Signed-By conflicts
    if ls /etc/apt/sources.list.d/*.list >/dev/null 2>&1; then
        for source_file in /etc/apt/sources.list.d/*.list; do
            [ -f "$source_file" ] || continue
            if grep -q "developer.download.nvidia.com/compute/cuda/repos" "$source_file" 2>/dev/null; then
                sudo sed -i '/developer.download.nvidia.com\/compute\/cuda\/repos/d' "$source_file" 2>/dev/null || true
            fi
        done
    fi
    
    # Check if CUDA keyring is already installed
    if dpkg -l | grep -q "^ii.*cuda-keyring"; then
        echo "CUDA keyring already installed, skipping installation..."
    else
        echo "Installing CUDA keyring for $CUDA_DIST..."
        wget -q "https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_DIST}/x86_64/cuda-keyring_1.1-1_all.deb" -O /tmp/cuda-keyring.deb
        if [ -f /tmp/cuda-keyring.deb ]; then
            sudo dpkg -i /tmp/cuda-keyring.deb
            rm -f /tmp/cuda-keyring.deb
        else
            echo "⚠️  Failed to download CUDA keyring, trying alternative method..."
            # Alternative: Set up CUDA repository manually
            DIST=$(lsb_release -cs)
            ARCH=$(dpkg --print-architecture)
            if [ "$DIST" = "noble" ]; then
                # Ubuntu 24.04 uses ubuntu2404 in CUDA repos
                CUDA_REPO_DIST="ubuntu2404"
            else
                CUDA_REPO_DIST="ubuntu$(lsb_release -rs | tr -d '.')"
            fi
            echo "Setting up CUDA repository for $CUDA_REPO_DIST/$ARCH..."
            wget -qO - https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_REPO_DIST}/${ARCH}/3bf863cc.pub | sudo gpg --dearmor -o /usr/share/keyrings/cuda-archive-keyring.gpg 2>/dev/null || true
            echo "deb [signed-by=/usr/share/keyrings/cuda-archive-keyring.gpg] https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_REPO_DIST}/${ARCH} /" | sudo tee /etc/apt/sources.list.d/cuda-${CUDA_REPO_DIST}-${ARCH}.list >/dev/null
        fi
    fi

    # Avoid apt "Signed-By" conflicts by ensuring only one active CUDA repo entry.
    # Some provider images ship a preconfigured CUDA repo that points to the same URL but uses a different keyring
    # (e.g., /usr/share/keyrings/cudatools.gpg). apt will refuse to read sources when they conflict.
    if [ "$CUDA_DIST" = "noble" ]; then
        CUDA_REPO_DIST="ubuntu2404"
    else
        CUDA_REPO_DIST="$CUDA_DIST"
    fi
    CUDA_REPO_URL="https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_REPO_DIST}/x86_64/"
    CUDA_KEYRING="/usr/share/keyrings/cuda-archive-keyring.gpg"
    if [ ! -f "$CUDA_KEYRING" ] && [ -f /etc/apt/keyrings/cuda-archive-keyring.gpg ]; then
        CUDA_KEYRING="/etc/apt/keyrings/cuda-archive-keyring.gpg"
    fi
    # If a cudatools.gpg keyring exists, align it to the official keyring to prevent Signed-By mismatches
    if [ -f /usr/share/keyrings/cudatools.gpg ] && [ -f "$CUDA_KEYRING" ]; then
        sudo cp -f "$CUDA_KEYRING" /usr/share/keyrings/cudatools.gpg || true
    fi
    if [ -f "$CUDA_KEYRING" ]; then
        echo "Normalizing CUDA apt repo to use keyring: $CUDA_KEYRING"
        echo "deb [signed-by=${CUDA_KEYRING}] ${CUDA_REPO_URL} /" | sudo tee /etc/apt/sources.list.d/omniference-cuda.list >/dev/null

        # Disable other CUDA repo entries that point to the same URL (keep file content, just comment matching lines)
        for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
            if [ -f "$source_file" ] && [ "$source_file" != "/etc/apt/sources.list.d/omniference-cuda.list" ]; then
                if grep -q "${CUDA_REPO_URL}" "$source_file" 2>/dev/null; then
                    # Also strip any cudatools.gpg Signed-By to avoid mismatched keyrings
                    sudo sed -i "s#\\[signed-by=/usr/share/keyrings/cudatools.gpg\\]#\\[signed-by=${CUDA_KEYRING}\\]#g" "$source_file" 2>/dev/null || true
                    sudo sed -i "\\#${CUDA_REPO_URL}# s|^[[:space:]]*deb[[:space:]]|# deb |" "$source_file" 2>/dev/null || true
                fi
            fi
        done
    fi
    
    # Update package lists (with error handling for conflicts)
    echo "Updating package lists..."
    if ! apt_update 2>&1 | grep -q "conflict\|signed-by"; then
        echo "Package lists updated successfully"
    else
        echo "Warning: Some repository conflicts detected, but continuing..."
        # Try to fix conflicts by removing problematic sources
        for source_file in /etc/apt/sources.list.d/*.list; do
            if [ -f "$source_file" ] && grep -q "nvidia.github.io/libnvidia-container" "$source_file" 2>/dev/null; then
                echo "Fixing conflict in $source_file..."
                sudo sed -i '/nvidia.github.io\/libnvidia-container/d' "$source_file"
            fi
        done
        apt_update || echo "apt update had issues, but continuing with DCGM installation..."
    fi
    
    # Try to install DCGM
    echo "Attempting to install datacenter-gpu-manager..."
    
    # First check if DCGM is available in current repos
    if ! apt-cache show datacenter-gpu-manager &>/dev/null; then
        echo "datacenter-gpu-manager not found in current repos, adding NVIDIA CUDA repo..."
        # If cuda-keyring is present, it should already provide the repo; just retry apt update.
        $APT_GET update -qq 2>/dev/null || true
        # Fallback: explicitly add CUDA repo for ubuntu2404 (Scaleway images sometimes miss it)
        if ! apt-cache show datacenter-gpu-manager &>/dev/null; then
            curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/3bf863cc.pub | \
                sudo gpg --dearmor -o /usr/share/keyrings/nvidia-drivers.gpg 2>/dev/null || true
            echo "deb [signed-by=/usr/share/keyrings/nvidia-drivers.gpg] https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/ /" | \
                sudo tee /etc/apt/sources.list.d/nvidia-cuda.list >/dev/null
            $APT_GET update -qq 2>/dev/null || true
        fi
    fi
    
    if apt_install datacenter-gpu-manager 2>&1 | tee /tmp/dcgm_install.log | grep -q "Unable to locate package\|E: Unable to locate"; then
        echo "⚠️  datacenter-gpu-manager not found in repositories"
        echo "Checking available DCGM packages..."
        sudo apt-cache search datacenter 2>&1 | head -5
        echo ""
        echo "⚠️  DCGM system package installation skipped"
        echo "   Note: The DCGM exporter container has its own DCGM libraries"
        echo "   Profiling can still work via the container, but agent detection may be limited"
        INSTALL_DCGM="no"
    else
        if command -v dcgmi &>/dev/null; then
            echo "✅ DCGM installed successfully"
            # Start and enable NVIDIA DCGM service
            sudo systemctl enable nvidia-dcgm 2>/dev/null || true
            sudo systemctl start nvidia-dcgm 2>/dev/null || true
        else
            echo "⚠️  DCGM package installed but dcgmi command not found"
            echo "   This may be normal - the DCGM exporter container will still work"
            INSTALL_DCGM="partial"
        fi
    fi
    
    # Configure profiling permissions for advanced metrics
    echo "Configuring NVIDIA profiling permissions for advanced metrics..."
    if ! grep -qs "NVreg_RestrictProfilingToAdminUsers" /etc/modprobe.d/omniference-nvidia.conf 2>/dev/null; then
        echo "options nvidia NVreg_RestrictProfilingToAdminUsers=0" | sudo tee /etc/modprobe.d/omniference-nvidia.conf >/dev/null
        if command -v update-initramfs &>/dev/null; then
            echo "Updating initramfs (this may take a minute)..."
            sudo update-initramfs -u 2>&1 | grep -v "^\(Reading\|Building\|Reading state\)" || echo "⚠️  initramfs update had issues (non-critical)"
        fi
        echo "✅ Profiling permissions configured"
        echo "⚠️  NOTE: A reboot is required for profiling permissions to take effect."
        REBOOT_NEEDED=true
    else
        echo "✅ Profiling permissions already configured"
        # Check if reboot is actually needed (check current driver param)
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
    
    # Start and enable DCGM (only if installation was successful)
    if [ "$INSTALL_DCGM" = "yes" ] || [ "$INSTALL_DCGM" = "partial" ]; then
        if command -v dcgmi &>/dev/null; then
            # Check if DCGM service exists
            if systemctl list-unit-files 2>/dev/null | grep -q "nvidia-dcgm.service"; then
                sudo systemctl start nvidia-dcgm 2>/dev/null || true
                sudo systemctl enable nvidia-dcgm 2>/dev/null || true
                sleep 2
                # Verify DCGM
                if dcgmi discovery -l &>/dev/null; then
                    echo "✅ DCGM installed and running."
                else
                    echo "⚠️  DCGM installed but not responding - may need reboot"
                fi
            elif systemctl list-unit-files 2>/dev/null | grep -q "dcgm.service"; then
                sudo systemctl start dcgm 2>/dev/null || true
                sudo systemctl enable dcgm 2>/dev/null || true
                sleep 2
                # Verify DCGM
                if dcgmi discovery -l &>/dev/null; then
                    echo "✅ DCGM installed and running."
                else
                    echo "⚠️  DCGM installed but not responding - may need reboot"
                fi
            elif systemctl list-unit-files 2>/dev/null | grep -q "nv-hostengine.service"; then
                sudo systemctl start nv-hostengine 2>/dev/null || true
                sudo systemctl enable nv-hostengine 2>/dev/null || true
                sleep 2
                if dcgmi discovery -l &>/dev/null; then
                    echo "✅ DCGM installed and running."
                else
                    echo "⚠️  DCGM installed but not responding - may need reboot"
                fi
            else
                echo "⚠️  DCGM service not found - DCGM may not be fully installed"
            fi
        else
            echo "⚠️  DCGM package installed but dcgmi command not available"
            echo "   The DCGM exporter container will work with its own DCGM libraries"
        fi
    else
        echo "⚠️  DCGM system package not installed"
        echo "   Profiling will still work via DCGM exporter container"
        echo "   Note: Provisioning agent may not auto-detect DCGM for profiling"
    fi
fi

# Final Verification
echo ""
echo "=== Final Verification ==="
echo "Verifying system setup..."

# Check GPU status
nvidia-smi

# Check CUDA
nvcc --version

# Check Python environment
python --version

# Check PyTorch CUDA
python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"

# Check vLLM
python -c "import vllm; print(f'vLLM version: {vllm.__version__}')"

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

# Reboot only if needed (driver installed or profiling configured)
if [ "$REBOOT_NEEDED" = true ]; then
    echo "⚠️  Rebooting system in 10 seconds to activate NVIDIA drivers/profiling..."
    echo "⚠️  Press Ctrl+C to cancel the reboot"
    sleep 10
    echo "Rebooting now..."
    sudo reboot
else
    echo "✅ No reboot needed - system is ready to use"
fi
