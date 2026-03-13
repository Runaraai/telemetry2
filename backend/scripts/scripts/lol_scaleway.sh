#!/bin/bash
# Scaleway-specific setup script (lol.sh)
# Handles disk space by using /scratch partition

set -e

# Fix broken NVIDIA driver packages (common after setup script reboot)
echo "Checking NVIDIA driver state..."
if ! nvidia-smi &>/dev/null 2>&1; then
    echo "⚠️  nvidia-smi not working, attempting to fix driver packages..."
    sudo dpkg --force-overwrite --configure -a 2>&1 | tail -5 || true
    sudo apt-get --fix-broken install -y 2>&1 | tail -5 || true
    if ! lsmod | grep -q '^nvidia'; then
        DRIVER_VER=$(dpkg -l 2>/dev/null | grep -oP 'nvidia-dkms-\K[0-9]+' | head -1)
        if [ -n "$DRIVER_VER" ]; then
            echo "Rebuilding DKMS modules for nvidia/$DRIVER_VER..."
            sudo dkms install nvidia/$DRIVER_VER -k $(uname -r) 2>&1 | tail -5 || true
        fi
        sudo modprobe nvidia 2>/dev/null || true
        sudo modprobe nvidia_uvm 2>/dev/null || true
    fi
    if nvidia-smi &>/dev/null 2>&1; then
        echo "✅ NVIDIA driver fixed successfully"
    else
        echo "❌ NVIDIA driver still not working. Instance may need a manual reboot."
    fi
else
    echo "✅ NVIDIA driver working"
fi

# Configure Docker/containerd to use /scratch if available (Scaleway has 5.8TB there)
if [ -d "/scratch" ] && [ -w "/scratch" ]; then
    echo "Configuring Docker to use /scratch partition for storage..."
    # Stop Docker services
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
    
    # Move containerd data to /scratch
    if [ -d "/var/lib/containerd" ]; then
        sudo mkdir -p /scratch/containerd
        sudo mv /var/lib/containerd /scratch/containerd/ 2>/dev/null || true
    fi
    sudo mkdir -p /scratch/containerd/containerd
    sudo rm -rf /var/lib/containerd
    sudo ln -sf /scratch/containerd/containerd /var/lib/containerd 2>/dev/null || true
    
    # Start services
    sudo systemctl start containerd 2>/dev/null || true
    sudo systemctl start docker 2>/dev/null || true
    sleep 2
    echo "✅ Docker configured to use /scratch"
fi

# Clean apt cache to free up space
sudo apt clean 2>/dev/null || true
sudo rm -rf /var/cache/apt/archives/* 2>/dev/null || true

# NVIDIA Container Toolkit (skip if already installed)
# Clean apt cache first to avoid disk space issues
sudo apt clean 2>/dev/null || true
sudo rm -rf /var/cache/apt/archives/* 2>/dev/null || true

if command -v nvidia-ctk &>/dev/null && sudo docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
    echo "NVIDIA Container Toolkit already installed and working. Skipping installation."
else
    echo "Installing NVIDIA Container Toolkit..."
    distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
     | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null || true
    curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list \
     | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null 2>&1 || true
    sudo apt clean 2>/dev/null || true
    sudo apt update 2>&1 | grep -v "Conflicting values" || true
    sudo apt -y install nvidia-container-toolkit || echo "⚠️  nvidia-container-toolkit installation had issues"
    sudo nvidia-ctk runtime configure --runtime=docker 2>/dev/null || true
    sudo systemctl restart docker 2>/dev/null || true
    sleep 2
fi

nvidia-smi    # should show 4× H100

# Install python3-venv if not already installed (skip python3-full if low disk space)
sudo apt install -y python3-venv || echo "⚠️  python3-venv installation had issues, but continuing..."

# Use existing venv if available, otherwise create new one
VENV_DIR="${HOME}/h100_benchmark_env"
if [ -f "$VENV_DIR/bin/activate" ]; then
    echo "Using existing virtual environment at $VENV_DIR"
    source "$VENV_DIR/bin/activate"
else
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
fi

# Install packages in the virtual environment
pip install "huggingface_hub[cli]" hf-transfer || echo "⚠️  Package installation had issues, but continuing..."

# Login with token
if [ -z "${HF_TOKEN:-}" ]; then
    echo "Warning: HF_TOKEN is not set. Public models may still download, but gated/private models will fail."
else
    hf login --token "$HF_TOKEN" || echo "⚠️  HF login had issues, but continuing..."
fi

# Create model directory - use /scratch if available (Scaleway has 5.8TB there)
if [ -d "/scratch" ] && [ -w "/scratch" ]; then
    MODEL_DIR="/scratch/BM/models"
else
    MODEL_DIR="${HOME}/BM/models"
fi
mkdir -p "$MODEL_DIR/scout17b-fp8dyn"

# Download the model
hf download \
  RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic \
  --local-dir "$MODEL_DIR/scout17b-fp8dyn" || echo "⚠️  Model download had issues"



# Add NVIDIA CUDA repository (skip if already installed and working)
if dpkg -l | grep -q cuda-keyring && apt-cache policy | grep -q "developer.download.nvidia.com"; then
    echo "CUDA keyring already installed and configured. Skipping."
else
    echo "Installing CUDA keyring..."
    # Remove conflicting keyrings first
    sudo rm -f /usr/share/keyrings/cudatools.gpg /etc/apt/sources.list.d/cuda*.list 2>/dev/null || true
    wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb -O /tmp/cuda-keyring.deb
    sudo dpkg -i /tmp/cuda-keyring.deb 2>/dev/null || true
    sudo apt update 2>&1 | grep -v "Conflicting values" || true
fi

# Install DCGM (skip if already installed and running)
if command -v dcgmi &>/dev/null; then
    echo "DCGM already installed. Checking service..."
    if systemctl list-unit-files | grep -q "dcgm.service"; then
        sudo systemctl restart dcgm 2>/dev/null || true
    fi
else
    echo "Installing DCGM..."
    # Fix apt sources if there are conflicts
    sudo rm -f /etc/apt/sources.list.d/cuda*.list 2>/dev/null || true
    sudo apt update 2>&1 | grep -v "Conflicting values" || true
    sudo apt install -y datacenter-gpu-manager || echo "⚠️  DCGM installation had issues"
    if systemctl list-unit-files | grep -q "dcgm.service"; then
        sudo systemctl start dcgm 2>/dev/null || true
        sudo systemctl enable dcgm 2>/dev/null || true
    fi
fi

# Configure profiling permissions for advanced metrics (SM, HBM, NVLink)
echo "Configuring NVIDIA profiling permissions for advanced metrics..."
if ! grep -qs "NVreg_RestrictProfilingToAdminUsers" /etc/modprobe.d/omniference-nvidia.conf 2>/dev/null; then
    echo "options nvidia NVreg_RestrictProfilingToAdminUsers=0" | sudo tee /etc/modprobe.d/omniference-nvidia.conf >/dev/null
    if command -v update-initramfs &>/dev/null; then
        echo "Updating initramfs..."
        sudo update-initramfs -u 2>&1 | grep -v "^\(Reading\|Building\|Reading state\)" || true
    fi
    echo "✅ Profiling permissions configured"
    echo "⚠️  NOTE: A reboot is required for profiling permissions to take effect."
else
    echo "✅ Profiling permissions already configured"
    # Check if reboot is actually needed
    if [ -f /proc/driver/nvidia/params ]; then
        CURRENT_PROFILING=$(grep -o "RmProfilingAdminOnly:[[:space:]]*[0-9]*" /proc/driver/nvidia/params 2>/dev/null | awk '{print $2}' || echo "1")
        if [ "$CURRENT_PROFILING" = "1" ]; then
            echo "⚠️  Profiling is still restricted (RmProfilingAdminOnly=1) - reboot needed"
        else
            echo "✅ Profiling is already enabled (RmProfilingAdminOnly=0)"
        fi
    fi
fi

# Note: dcgmi dmon is commented out as it blocks script completion
# To monitor GPU metrics, run: dcgmi dmon -e 1002,1005,203,252,150,155

# Check if NVIDIA driver is already installed and working
if nvidia-smi &>/dev/null; then
    echo "NVIDIA driver already installed and working. Skipping driver installation."
    echo "Current driver version:"
    nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1
else
    echo "NVIDIA driver not working. Installing nvidia-driver-535-server..."
    
    # Clean up conflicting nvidia packages before driver installation
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
    
    # Install driver using the standard sequence: update, fix-broken, install headers+driver
    echo "Installing NVIDIA Driver 535-server..."
    echo "Running: apt update && apt --fix-broken install && apt install linux-headers + nvidia-driver-535-server"
    sudo apt update && \
    sudo apt --fix-broken install -y && \
    sudo apt install -y linux-headers-$(uname -r) nvidia-driver-535-server
    
    echo "Driver installed. A reboot may be required."
    echo "⚠️  WARNING: System reboot may be required for driver to take effect."
fi
