#!/bin/bash
# Check driver and DCGM (Scaleway version)

# Check driver
echo "Checking NVIDIA driver..."
nvidia-smi || {
    echo "❌ ERROR: nvidia-smi failed"
    exit 1
}

# Check if DCGM is installed
if ! command -v dcgmi &>/dev/null; then
    echo "⚠️  DCGM (dcgmi) is not installed."
    echo "   To install: sudo apt install -y datacenter-gpu-manager"
    exit 1
fi

# Restart DCGM service (if it exists)
if systemctl list-unit-files | grep -q "dcgm.service"; then
    echo "Restarting DCGM service..."
    sudo systemctl restart dcgm 2>/dev/null || echo "⚠️  Could not restart DCGM service"
else
    echo "⚠️  DCGM service not found. DCGM may not be installed as a service."
fi

# Run dcgmi dmon
echo "Starting DCGM monitoring..."
dcgmi dmon -e 1002,1005,203,252,150,155