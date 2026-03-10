#!/bin/bash
# GPU LLM Benchmarking Setup Script (Adaptive for H100, A100, etc.)
# Based on successful commands from H100_Command_Log.md
# This script automatically detects GPU type and count and adapts configuration

# Don't exit on error immediately - we'll handle errors per section
set +e  # Continue on error (we'll check exit codes manually)

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
echo "H100 LLM Benchmarking Setup Script"
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
sudo apt update || echo "⚠️  apt update had some errors (GPG keys), but continuing..."

# Check for conflicting nvidia packages before driver installation
echo "Checking for conflicting NVIDIA packages..."
# Remove ALL nvidia-driver-570 packages first (they conflict with 535-server)
if dpkg -l | grep -q "nvidia-driver-570\|nvidia-dkms-570\|nvidia-kernel-common-570\|nvidia-kernel-source-570"; then
    echo "⚠️  Found conflicting nvidia-driver-570 packages"
    echo "Removing all nvidia-driver-570 packages..."
    # First remove firmware packages that conflict
    sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge \
        nvidia-firmware-570-server \
        nvidia-firmware-570 \
        2>/dev/null || true
    # Then remove driver packages
    sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge \
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
    sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge nvidia-firmware-535-server 2>/dev/null || true
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
        if sudo apt update && \
           sudo apt --fix-broken install -y && \
           sudo apt install -y --no-install-recommends linux-headers-$(uname -r) nvidia-driver-535-server; then
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
    sudo apt install -y ca-certificates curl
    
    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    
    # Add Docker repository
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Install Docker
    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
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
sudo apt install -y nvidia-cuda-toolkit

# Verify CUDA installation
echo "Verifying CUDA installation..."
nvcc --version

# Phase 4: Python Environment and Dependencies
echo ""
echo "=== Phase 4: Python Environment and Dependencies ==="

# Install python3-venv if not already installed
echo "Installing python3-venv..."
sudo apt install -y python3-venv

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
    sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge \
        nvidia-driver-570 \
        nvidia-dkms-570 \
        nvidia-kernel-common-570 \
        nvidia-kernel-source-570 \
        nvidia-fabricmanager-570 \
        2>/dev/null || true
    
    # Remove conflicting firmware packages
    echo "Removing conflicting nvidia-firmware packages..."
    sudo DEBIAN_FRONTEND=noninteractive apt remove -y --purge \
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
    sudo DEBIAN_FRONTEND=noninteractive apt --fix-broken install -y 2>&1 | grep -v "^\(Reading\|Building\|Reading state\)" || echo "⚠️  Package fix had issues, but continuing..."
    
    # Remove any orphaned packages
    echo "Removing orphaned packages..."
    sudo apt autoremove -y 2>&1 | grep -v "^\(Reading\|Building\|Reading state\)" || true
    
    # Install Linux headers first (required for driver compilation)
    echo "Installing Linux headers for current kernel..."
    sudo apt install -y linux-headers-$(uname -r) || echo "⚠️  Linux headers installation had issues, but continuing..."
    
    # Install NVIDIA Driver 535-server (complete) - skip if already installed
    # Use --no-install-recommends to avoid pulling in conflicting EGL packages
    if ! dpkg -l | grep -q "^ii.*nvidia-driver-535-server"; then
        echo "Installing NVIDIA Driver 535-server..."
        if sudo apt install -y --no-install-recommends nvidia-driver-535-server; then
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
        sudo apt install -y nvidia-fabricmanager-535 || echo "⚠️  Fabric Manager installation had issues, but continuing..."
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
MODEL_NAME="${MODEL_NAME:-RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic}"
MODEL_PATH="${MODEL_PATH:-/home/ubuntu/BM/models/scout17b-fp8dyn}"

echo "Model Configuration:"
echo "  Model Name: $MODEL_NAME"
echo "  Model Path: $MODEL_PATH"

# Create model directory with proper permissions
echo "Creating model directory..."
MODEL_DIR="$(dirname "$MODEL_PATH")"
mkdir -p "$MODEL_DIR"
# Ensure ubuntu user owns the directory
sudo chown -R ubuntu:ubuntu "$MODEL_DIR" 2>/dev/null || true
# Create the specific model directory
mkdir -p "$MODEL_PATH"
sudo chown -R ubuntu:ubuntu "$MODEL_PATH" 2>/dev/null || true
cd "$MODEL_DIR"
pwd

# Install Hugging Face CLI
echo "Installing Hugging Face CLI..."
pip install huggingface_hub

# Login to Hugging Face with token
echo "Logging in to Hugging Face..."
HF_TOKEN="${HF_TOKEN:-}"
if [ -n "$HF_TOKEN" ]; then
    huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential
else
    echo "HF_TOKEN not set; skipping login (required for gated/private models)."
fi

echo ""
echo "=========================================="
echo "Hugging Face Authenticated"
echo "=========================================="

# Download model using Python API (more reliable for permissions)
echo "Downloading $MODEL_NAME to $MODEL_PATH..."
python3 << EOF
import os
from huggingface_hub import snapshot_download

os.environ['HF_TOKEN'] = '$HF_TOKEN'
model_name = os.environ.get('MODEL_NAME', '$MODEL_NAME')
model_path = os.environ.get('MODEL_PATH', '$MODEL_PATH')

print(f'Starting model download for {model_name}...')
print(f'Destination: {model_path}')

try:
    snapshot_download(
        repo_id=model_name,
        local_dir=model_path,
        token=os.environ['HF_TOKEN'],
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
    # Fix permissions
    sudo chown -R ubuntu:ubuntu "$MODEL_PATH" 2>/dev/null || true
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
    echo "  source ~/venv/bin/activate"
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
    
    # Check if CUDA keyring is already installed
    if dpkg -l | grep -q "^ii.*cuda-keyring"; then
        echo "CUDA keyring already installed, skipping installation..."
    else
        echo "Installing CUDA keyring for $CUDA_DIST..."
        wget -q "https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_DIST}/x86_64/cuda-keyring_1.1-1_all.deb" -O /tmp/cuda-keyring.deb
        sudo dpkg -i /tmp/cuda-keyring.deb
        rm -f /tmp/cuda-keyring.deb
    fi
    
    # Update package lists (with error handling for conflicts)
    echo "Updating package lists..."
    if ! sudo apt update 2>&1 | grep -q "conflict\|signed-by"; then
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
        sudo apt update || echo "apt update had issues, but continuing with DCGM installation..."
    fi
    
    sudo apt install -y datacenter-gpu-manager
    
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
    
    # Start and enable DCGM
    sudo systemctl start dcgm
    sudo systemctl enable dcgm
    
    # Verify DCGM
    dcgmi discovery -l
    
    echo "DCGM installed and running."
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
