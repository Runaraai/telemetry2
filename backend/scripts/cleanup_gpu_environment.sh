#!/usr/bin/env bash
# GPU Environment Cleanup Script
# Removes all GPU-related installations for a clean slate

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*" >&2
}

log_info "=========================================="
log_info "GPU Environment Cleanup Script"
log_info "=========================================="
log_warn "This will remove Docker, NVIDIA drivers, DCGM, and related components"
log_warn "Press Ctrl+C within 5 seconds to cancel..."
sleep 5

# Stop and remove Docker containers
log_info "Stopping Docker containers..."
sudo docker ps -aq | xargs -r sudo docker rm -f 2>/dev/null || true
sudo docker stop $(sudo docker ps -aq) 2>/dev/null || true

# Stop services
log_info "Stopping services..."
sudo systemctl stop dcgm 2>/dev/null || true
sudo systemctl stop nvidia-fabricmanager 2>/dev/null || true
sudo systemctl stop docker 2>/dev/null || true
sudo systemctl stop nvidia-persistenced 2>/dev/null || true

# Disable services
log_info "Disabling services..."
sudo systemctl disable dcgm 2>/dev/null || true
sudo systemctl disable nvidia-fabricmanager 2>/dev/null || true

# Remove DCGM
log_info "Removing DCGM..."
sudo apt-get remove -y datacenter-gpu-manager 2>/dev/null || true
sudo apt-get purge -y datacenter-gpu-manager 2>/dev/null || true

# Remove Fabric Manager
log_info "Removing Fabric Manager..."
sudo apt-get remove -y cuda-drivers-fabricmanager-* 2>/dev/null || true
sudo apt-get purge -y cuda-drivers-fabricmanager-* 2>/dev/null || true

# Remove NVIDIA Container Toolkit
log_info "Removing NVIDIA Container Toolkit..."
sudo apt-get remove -y nvidia-container-toolkit 2>/dev/null || true
sudo apt-get purge -y nvidia-container-toolkit 2>/dev/null || true

# Remove NVIDIA drivers
log_info "Removing NVIDIA drivers..."
sudo apt-get remove -y '^nvidia-.*' 2>/dev/null || true
sudo apt-get purge -y '^nvidia-.*' 2>/dev/null || true
sudo apt-get remove -y '^libnvidia-.*' 2>/dev/null || true
sudo apt-get purge -y '^libnvidia-.*' 2>/dev/null || true

# Remove Docker
log_info "Removing Docker..."
sudo apt-get remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 2>/dev/null || true
sudo apt-get purge -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 2>/dev/null || true
sudo rm -rf /var/lib/docker
sudo rm -rf /var/lib/containerd
sudo rm -rf /etc/docker

# Remove NVIDIA configuration files
log_info "Removing NVIDIA configuration files..."
sudo rm -rf /etc/modprobe.d/omniference-nvidia.conf
sudo rm -rf /etc/cdi/nvidia.yaml
sudo rm -rf /etc/cdi

# Remove NVIDIA repository keys and sources
log_info "Removing NVIDIA repositories..."
sudo rm -rf /etc/apt/keyrings/nvidia-container-toolkit-keyring.gpg
sudo rm -rf /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo rm -rf /etc/apt/keyrings/cuda-archive-keyring.gpg
sudo rm -rf /etc/apt/sources.list.d/cuda-*.list

# Clean up apt
log_info "Cleaning up package manager..."
sudo apt-get autoremove -y
sudo apt-get autoclean

# Remove user from docker group
log_info "Removing user from docker group..."
sudo deluser $USER docker 2>/dev/null || true

# Update initramfs
log_info "Updating initramfs..."
sudo update-initramfs -u 2>/dev/null || true

log_success "Cleanup complete!"
log_warn "A system reboot is recommended to fully clean up kernel modules"
log_info "After reboot, you can run deploy_gpu_environment.sh for a fresh installation"

