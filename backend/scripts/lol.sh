# Docker
# curl -fsSL https://get.docker.com | sh
# sudo usermod -aG docker $USER
# newgrp docker

# NVIDIA Container Toolkit (skip if already installed)
if command -v nvidia-ctk &>/dev/null && docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
    echo "NVIDIA Container Toolkit already installed and working. Skipping installation."
else
    echo "Installing NVIDIA Container Toolkit..."
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
 | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list \
 | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt -y install nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
fi

nvidia-smi    # should show 4× H100

# Install python3-venv if not already installed
sudo apt install -y python3-venv python3-full

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install packages in the virtual environment
pip install "huggingface_hub[cli]" hf-transfer
# Login with token from env
if [ -n "${HF_TOKEN:-}" ]; then
  venv/bin/hf login --token "$HF_TOKEN"
else
  echo "HF_TOKEN not set; skipping login (required for gated/private models)."
fi

# Create model directory in BM folder
mkdir -p ./models/scout17b-fp8dyn

# Download the model
venv/bin/hf download \
  RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic \
  --local-dir ./models/scout17b-fp8dyn



# Add NVIDIA CUDA repository (skip if already installed)
if dpkg -l | grep -q cuda-keyring; then
    echo "CUDA keyring already installed. Skipping."
else
    echo "Installing CUDA keyring..."
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
fi

# Install DCGM (skip if already installed and running)
if systemctl is-active --quiet dcgm && command -v dcgmi &>/dev/null; then
    echo "DCGM already installed and running. Restarting service..."
    sudo systemctl restart dcgm
else
    echo "Installing DCGM..."
sudo apt install -y datacenter-gpu-manager
sudo systemctl start dcgm
sudo systemctl enable dcgm
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
