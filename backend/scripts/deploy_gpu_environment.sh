#!/usr/bin/env bash
# GPU Environment Deployment Script
# Ansible-like idempotent script for setting up GPU telemetry stack prerequisites
# Can be run multiple times safely - only installs/configures what's missing
# Outputs structured logs for frontend consumption

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Progress tracking
# Steps: 1) System Info, 2) Docker, 3) NVIDIA Driver, 4) Container Toolkit, 5) DCGM, 6) Fabric Manager, 7) System Config, 8) Verification
TOTAL_STEPS=8
CURRENT_STEP=0
PROGRESS_FILE="/tmp/gpu_deployment_progress.json"

# Logging functions with structured output
log_step_start() {
    local step_id="$1"
    local step_name="$2"
    local description="$3"
    CURRENT_STEP=$((CURRENT_STEP + 1))
    local progress=$((CURRENT_STEP * 100 / TOTAL_STEPS))
    
    # Structured JSON log for frontend
    echo "{\"type\":\"step_start\",\"step_id\":\"$step_id\",\"step_name\":\"$step_name\",\"description\":\"$description\",\"progress\":$progress,\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    
    # Human-readable log
    echo -e "${BLUE}[STEP $CURRENT_STEP/$TOTAL_STEPS]${NC} ${GREEN}Starting:${NC} $step_name"
    echo -e "${BLUE}[INFO]${NC} $description"
}

log_step_success() {
    local step_id="$1"
    local step_name="$2"
    local message="${3:-Completed successfully}"
    local progress=$((CURRENT_STEP * 100 / TOTAL_STEPS))
    
    # Structured JSON log
    echo "{\"type\":\"step_success\",\"step_id\":\"$step_id\",\"step_name\":\"$step_name\",\"message\":\"$message\",\"progress\":$progress,\"status\":\"completed\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    
    # Human-readable log
    echo -e "${GREEN}[SUCCESS]${NC} $step_name: $message"
}

log_step_skip() {
    local step_id="$1"
    local step_name="$2"
    local reason="$3"
    local progress=$((CURRENT_STEP * 100 / TOTAL_STEPS))
    
    # Structured JSON log
    echo "{\"type\":\"step_skip\",\"step_id\":\"$step_id\",\"step_name\":\"$step_name\",\"reason\":\"$reason\",\"progress\":$progress,\"status\":\"skipped\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    
    # Human-readable log
    echo -e "${YELLOW}[SKIP]${NC} $step_name: $reason"
}

log_step_warn() {
    local step_id="$1"
    local step_name="$2"
    local message="$3"
    local progress=$((CURRENT_STEP * 100 / TOTAL_STEPS))
    
    # Structured JSON log
    echo "{\"type\":\"step_warn\",\"step_id\":\"$step_id\",\"step_name\":\"$step_name\",\"message\":\"$message\",\"progress\":$progress,\"status\":\"warning\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    
    # Human-readable log
    echo -e "${YELLOW}[WARN]${NC} $step_name: $message"
}

log_step_error() {
    local step_id="$1"
    local step_name="$2"
    local message="$3"
    local progress=$((CURRENT_STEP * 100 / TOTAL_STEPS))
    
    # Structured JSON log
    echo "{\"type\":\"step_error\",\"step_id\":\"$step_id\",\"step_name\":\"$step_name\",\"message\":\"$message\",\"progress\":$progress,\"status\":\"error\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    
    # Human-readable log
    echo -e "${RED}[ERROR]${NC} $step_name: $message" >&2
}

log_info() {
    local message="$1"
    echo "{\"type\":\"info\",\"message\":\"$message\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $message"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    log_step_error "root_check" "Root Check" "This script should not be run as root. It will use sudo when needed."
    exit 1
fi

# Source configuration if available
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/gpu_setup_config.sh" ]; then
    source "${SCRIPT_DIR}/gpu_setup_config.sh"
fi

# Default values (can be overridden by config file)
DOCKER_VERSION="${DOCKER_VERSION:-latest}"
NVIDIA_DRIVER_VERSION="${NVIDIA_DRIVER_VERSION:-auto}"
ENABLE_FABRIC_MANAGER="${ENABLE_FABRIC_MANAGER:-true}"
AUTO_REBOOT="${AUTO_REBOOT:-true}"

# Track what needs reboot
NEEDS_REBOOT=false
REBOOT_REASON=""

# Function to check if command exists
command_exists() {
    command -v "$1" &>/dev/null
}

# Function to check if service is active
service_is_active() {
    systemctl is-active --quiet "$1" 2>/dev/null
}

# Function to check if package is installed
package_is_installed() {
    dpkg -s "$1" &>/dev/null 2>&1
}

# Function to detect OS distribution
detect_distribution() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "${ID}${VERSION_ID//./}"
    else
        log_step_error "os_detect" "OS Detection" "Cannot detect OS distribution"
        exit 1
    fi
}

# Function to wait for Docker to be ready
wait_for_docker() {
    local max_attempts=30
    local attempt=1
    
    log_info "Waiting for Docker to be ready..."
    while [ $attempt -le $max_attempts ]; do
        if docker ps &>/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    
    log_step_error "docker_wait" "Docker Wait" "Docker did not become ready within ${max_attempts} seconds"
    return 1
}

# Function to wait for system services after reboot
# Note: This function is called when script resumes after reboot
wait_for_services_after_reboot() {
    local max_attempts=60
    local attempt=1
    
    log_info "Waiting for system services to initialize after reboot..."
    
    # Wait for systemd to be ready
    while [ $attempt -le $max_attempts ]; do
        if systemctl is-system-running &>/dev/null 2>&1; then
            break
        fi
        sleep 2
        attempt=$((attempt + 1))
    done
    
    # Wait for Docker
    wait_for_docker
    
    log_info "System services are ready"
    return 0
}

# Function to handle reboot
handle_reboot() {
    local reason="$1"
    
    if [ "$AUTO_REBOOT" != "true" ]; then
        log_step_warn "reboot_required" "Reboot Required" "System needs reboot: $reason. Auto-reboot is disabled. Please reboot manually and re-run this script."
        exit 0
    fi
    
    log_step_warn "reboot_initiated" "System Reboot" "Rebooting system in 10 seconds: $reason"
    log_info "After reboot, this script will automatically continue from where it left off"
    log_info "Press Ctrl+C within 10 seconds to cancel reboot"
    
    sleep 10
    
    # Save progress
    echo "{\"last_step\":$CURRENT_STEP,\"reboot_reason\":\"$reason\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$PROGRESS_FILE"
    
    # Output reboot notification for wrapper script
    echo "{\"type\":\"reboot_initiated\",\"step\":$CURRENT_STEP,\"reason\":\"$reason\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    
    log_info "Rebooting now..."
    log_info "After reboot, the deployment will automatically resume"
    sudo reboot
    exit 0
}

# Phase 1: System Information
phase_system_info() {
    log_step_start "system_info" "System Information" "Gathering system information and checking prerequisites"
    
    log_info "OS Information:"
    cat /etc/os-release | grep -E "^(NAME|VERSION|ID)=" || true
    
    log_info "Kernel: $(uname -r)"
    log_info "Architecture: $(uname -m)"
    
    log_info "GPU Hardware Detection:"
    lspci | grep -i nvidia || log_step_warn "system_info" "System Information" "No NVIDIA GPUs detected in PCIe bus"
    
    log_info "System Resources:"
    free -h | head -2
    df -h / | tail -1
    
    log_step_success "system_info" "System Information" "System information gathered successfully"
}

# Phase 2: Docker Installation
phase_docker() {
    log_step_start "docker_install" "Docker Installation" "Installing and configuring Docker"
    
    if command_exists docker; then
        local docker_version=$(docker --version)
        log_step_skip "docker_install" "Docker Installation" "Docker already installed: ${docker_version}"
        
        # Check if user is in docker group
        if groups | grep -q docker; then
            log_info "User is in docker group"
        else
            log_info "Adding user to docker group..."
            sudo usermod -aG docker "$USER"
            log_step_warn "docker_install" "Docker Installation" "User added to docker group. You may need to log out and back in."
        fi
        
        # Verify Docker is accessible
        if docker ps &>/dev/null 2>&1; then
            log_step_success "docker_install" "Docker Installation" "Docker is installed and accessible"
            return 0
        else
            log_step_warn "docker_install" "Docker Installation" "Docker is installed but not accessible. You may need to log out and back in."
        fi
        
        return 0
    fi
    
    log_info "Installing Docker..."
    
    # Update package lists
    sudo apt-get update -qq
    
    # Install Docker using official script
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sudo sh /tmp/get-docker.sh
    rm -f /tmp/get-docker.sh
    
    # Add user to docker group
    sudo usermod -aG docker "$USER"
    
    # Start and enable Docker
    sudo systemctl enable docker
    sudo systemctl start docker
    
    # Wait for Docker to be ready
    wait_for_docker
    
    log_step_success "docker_install" "Docker Installation" "Docker installed successfully"
    log_step_warn "docker_install" "Docker Installation" "You may need to log out and back in for docker group membership to take effect"
}

# Helper: ensure nvidia-uvm kernel module is loaded (required for CUDA in Docker containers)
# On Scaleway/bare-metal, the driver may be installed via .run without DKMS — missing nvidia-uvm.
# This installs the apt kernel modules package which rebuilds all modules via DKMS for the
# current kernel, including nvidia-uvm, without conflicting with the existing userspace driver.
ensure_nvidia_uvm() {
    # Already loaded
    if lsmod | grep -q nvidia_uvm || [ -e /dev/nvidia-uvm ]; then
        log_info "nvidia-uvm module already loaded"
        return 0
    fi

    # Try loading it (works if .ko exists but wasn't auto-loaded)
    sudo modprobe nvidia-uvm 2>/dev/null && return 0

    log_info "nvidia-uvm not loadable — installing kernel modules package via apt..."
    local driver_major
    driver_major=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)

    if [ -z "$driver_major" ]; then
        log_step_warn "nvidia_driver" "NVIDIA Driver" "Cannot determine driver version to install kernel modules"
        return 1
    fi

    sudo apt-get update -qq 2>&1 || true

    # On Scaleway/bare-metal, nvidia-firmware-<ver>-server conflicts with nvidia-kernel-common.
    # Both own the same firmware files. Remove the server variant to unblock the install.
    local driver_ver
    driver_ver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')
    if dpkg -l "nvidia-firmware-${driver_major}-server-${driver_ver}" 2>/dev/null | grep -q "^ii"; then
        log_info "Removing conflicting nvidia-firmware-${driver_major}-server package..."
        sudo dpkg -r --force-depends "nvidia-firmware-${driver_major}-server-${driver_ver}" 2>&1 || true
    fi

    # Install nvidia-kernel-common which triggers DKMS build including nvidia-uvm.ko
    if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "nvidia-kernel-common-${driver_major}" 2>&1; then
        log_info "Installed nvidia-kernel-common-${driver_major}"
    else
        log_info "Falling back to full nvidia-driver-${driver_major}..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "nvidia-driver-${driver_major}" 2>&1 || true
    fi
    sudo DEBIAN_FRONTEND=noninteractive apt-get -f install -y 2>&1 || true

    sudo depmod -a 2>&1 || true
    sudo modprobe nvidia-uvm 2>&1 || true

    if lsmod | grep -q nvidia_uvm || [ -e /dev/nvidia-uvm ]; then
        log_info "nvidia-uvm loaded successfully"
        return 0
    else
        log_step_warn "nvidia_driver" "NVIDIA Driver" "nvidia-uvm still not loadable after package install — reboot may be required"
        return 1
    fi
}

# Phase 3: NVIDIA Driver Installation
phase_nvidia_driver() {
    log_step_start "nvidia_driver" "NVIDIA Driver Installation" "Installing NVIDIA GPU drivers"

    if command_exists nvidia-smi; then
        if nvidia-smi &>/dev/null 2>&1; then
            local driver_version=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
            log_info "NVIDIA drivers already installed and working: ${driver_version}"
            # Also ensure nvidia-uvm is available (required for CUDA inside Docker/vLLM)
            ensure_nvidia_uvm || true
            log_step_success "nvidia_driver" "NVIDIA Driver Installation" "NVIDIA drivers ready (version: ${driver_version})"
            return 0
        else
            log_step_warn "nvidia_driver" "NVIDIA Driver Installation" "nvidia-smi exists but is not working properly - may need reboot"
        fi
    fi
    
    log_info "Installing NVIDIA drivers..."
    
    # Update package lists
    sudo apt-get update -qq
    
    # Install ubuntu-drivers-common if not present
    if ! command_exists ubuntu-drivers; then
        log_info "Installing ubuntu-drivers-common..."
        sudo apt-get install -y ubuntu-drivers-common
    fi
    
    # Install drivers
    if [ "${NVIDIA_DRIVER_VERSION}" = "auto" ]; then
        log_info "Auto-installing recommended NVIDIA driver..."
        sudo ubuntu-drivers autoinstall
    else
        log_info "Installing NVIDIA driver ${NVIDIA_DRIVER_VERSION}..."
        sudo apt-get install -y "nvidia-driver-${NVIDIA_DRIVER_VERSION}"
    fi
    
    # Check if installation was successful
    if command_exists nvidia-smi; then
        # Test if drivers are working (may require reboot)
        if nvidia-smi &>/dev/null 2>&1; then
            ensure_nvidia_uvm || true
            log_step_success "nvidia_driver" "NVIDIA Driver Installation" "NVIDIA drivers installed and working"
        else
            log_step_warn "nvidia_driver" "NVIDIA Driver Installation" "NVIDIA drivers installed but require reboot to function"
            NEEDS_REBOOT=true
            REBOOT_REASON="NVIDIA driver kernel modules need to be loaded"
        fi
    else
        log_step_warn "nvidia_driver" "NVIDIA Driver Installation" "NVIDIA drivers were installed but nvidia-smi is not available yet"
        NEEDS_REBOOT=true
        REBOOT_REASON="NVIDIA driver installation completed - reboot required"
    fi
    
    if [ "$NEEDS_REBOOT" = true ]; then
        handle_reboot "$REBOOT_REASON"
    fi
}

# Phase 4: NVIDIA Container Toolkit
phase_nvidia_container_toolkit() {
    log_step_start "nvidia_container_toolkit" "NVIDIA Container Toolkit" "Installing NVIDIA Container Toolkit for GPU access in Docker"
    
    # Test if GPU access works in Docker
    if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
        log_step_skip "nvidia_container_toolkit" "NVIDIA Container Toolkit" "NVIDIA Container Toolkit already configured and working"
        return 0
    fi
    
    log_info "Installing NVIDIA Container Toolkit..."
    
    # Detect distribution
    local distribution
    distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
    
    # Handle Ubuntu 24.04 (use 22.04 repository)
    if [[ "$distribution" == "ubuntu24.04" ]]; then
        distribution="ubuntu22.04"
        log_info "Using ubuntu22.04 repository for Ubuntu 24.04"
    fi
    
    # Add GPG key
    log_info "Adding NVIDIA Container Toolkit GPG key..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    
    # Add repository
    log_info "Adding NVIDIA Container Toolkit repository..."
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    
    # Update and install
    sudo apt-get update -qq
    sudo apt-get install -y nvidia-container-toolkit
    
    # Configure Docker runtime
    log_info "Configuring Docker runtime..."
    sudo nvidia-ctk runtime configure --runtime=docker --set-as-default || true
    
    # Restart Docker
    log_info "Restarting Docker..."
    if command_exists systemctl; then
        sudo systemctl restart docker
    else
        sudo service docker restart
    fi
    
    # Wait for Docker to be ready
    wait_for_docker
    
    # Verify installation (may fail if drivers not loaded yet - that's OK)
    if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
        log_step_success "nvidia_container_toolkit" "NVIDIA Container Toolkit" "NVIDIA Container Toolkit installed and configured"
    else
        log_step_warn "nvidia_container_toolkit" "NVIDIA Container Toolkit" "Toolkit installed but GPU access test failed. This is expected if drivers need reboot. Will work after reboot."
    fi
}

# Phase 5: DCGM Installation
phase_dcgm() {
    log_step_start "dcgm_install" "DCGM Installation" "Installing NVIDIA Data Center GPU Manager for advanced GPU monitoring"
    
    local distribution=$(detect_distribution)
    
    # Install DCGM
    if command_exists dcgmi; then
        local dcgm_version=$(dcgmi --version 2>/dev/null | head -1 || echo "installed")
        log_step_skip "dcgm_install" "DCGM Installation" "DCGM already installed: ${dcgm_version}"
    else
        log_info "Installing NVIDIA Data Center GPU Manager (DCGM)..."
        
        # Add CUDA repository key if not present
        if [ ! -f /etc/apt/keyrings/cuda-archive-keyring.gpg ]; then
            log_info "Adding CUDA repository key..."
            local tmp_key=$(mktemp)
            curl -fsSL "https://developer.download.nvidia.com/compute/cuda/repos/${distribution}/x86_64/cuda-keyring_1.1-1_all.deb" -o "${tmp_key}"
            sudo dpkg -i "${tmp_key}" || true
            rm -f "${tmp_key}"
        fi
        
        # Update and install
        sudo apt-get update -qq
        sudo apt-get install -y datacenter-gpu-manager
        
        log_step_success "dcgm_install" "DCGM Installation" "DCGM installed successfully"
    fi
    
    # Enable and start DCGM
    if service_is_active dcgm; then
        log_info "DCGM service is running"
    else
        log_info "Starting DCGM service..."
        sudo systemctl enable --now dcgm || true
        sleep 2
        if service_is_active dcgm; then
            log_step_success "dcgm_install" "DCGM Installation" "DCGM service started"
        else
            log_step_warn "dcgm_install" "DCGM Installation" "DCGM service may not have started properly"
        fi
    fi
}

# Phase 6: Fabric Manager Installation
phase_fabric_manager() {
    log_step_start "fabric_manager" "Fabric Manager Installation" "Installing NVIDIA Fabric Manager (if required)"
    
    if [ "${ENABLE_FABRIC_MANAGER}" != "true" ]; then
        log_step_skip "fabric_manager" "Fabric Manager Installation" "Fabric Manager disabled in configuration (not required for this GPU type)"
        return 0
    fi
    
    if ! command_exists nvidia-smi; then
        log_step_skip "fabric_manager" "Fabric Manager Installation" "Cannot determine driver version - nvidia-smi not available"
        return 0
    fi
    
    local driver_major=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1 || echo "")
    
    if [ -z "${driver_major}" ]; then
        log_step_skip "fabric_manager" "Fabric Manager Installation" "Unable to determine NVIDIA driver version"
        return 0
    fi
    
    local fabric_pkg="cuda-drivers-fabricmanager-${driver_major}"
    
    if package_is_installed "${fabric_pkg}"; then
        log_step_skip "fabric_manager" "Fabric Manager Installation" "Fabric Manager already installed: ${fabric_pkg}"
    else
        log_info "Installing NVIDIA Fabric Manager (${fabric_pkg})..."
        if sudo apt-get install -y "${fabric_pkg}" 2>&1; then
            log_step_success "fabric_manager" "Fabric Manager Installation" "Fabric Manager installed successfully"
        else
            log_step_warn "fabric_manager" "Fabric Manager Installation" "Fabric Manager installation failed (may not be required for this GPU type)"
            return 0
        fi
    fi
    
    # Enable and start Fabric Manager
    if service_is_active nvidia-fabricmanager; then
        log_info "Fabric Manager service is running"
    else
        log_info "Starting Fabric Manager service..."
        sudo systemctl enable --now nvidia-fabricmanager || true
        sleep 2
        if service_is_active nvidia-fabricmanager; then
            log_step_success "fabric_manager" "Fabric Manager Installation" "Fabric Manager service started"
        else
            log_step_warn "fabric_manager" "Fabric Manager Installation" "Fabric Manager service may not have started properly"
        fi
    fi
    
    # Restart NVIDIA Persistence Daemon
    sudo systemctl restart nvidia-persistenced || true
}

# Phase 7: System Configuration
phase_system_config() {
    log_step_start "system_config" "System Configuration" "Configuring NVIDIA profiling permissions and generating CDI specification"
    
    # Configure NVIDIA profiling permissions
    if ! grep -qs "NVreg_RestrictProfilingToAdminUsers" /etc/modprobe.d/omniference-nvidia.conf 2>/dev/null; then
        log_info "Configuring NVIDIA profiling permissions..."
        echo "options nvidia NVreg_RestrictProfilingToAdminUsers=0" | sudo tee /etc/modprobe.d/omniference-nvidia.conf >/dev/null
        sudo update-initramfs -u || true
        log_info "Profiling permissions configured (reboot may be required for full effect)"
    else
        log_info "Profiling permissions already configured"
    fi
    
    # Generate CDI specification
    log_info "Generating CDI specification..."
    sudo mkdir -p /etc/cdi
    
    # Generate CDI (suppress warnings/info messages)
    if sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml 2>&1 | grep -vE "^(time=|level=(warning|info))" | grep -q .; then
        # If there's actual error output (not just warnings), check if file was created
        if [ ! -s /etc/cdi/nvidia.yaml ]; then
            log_step_error "system_config" "System Configuration" "Failed to generate NVIDIA CDI specification"
            return 1
        fi
    fi
    
    # Verify CDI file exists and has content
    if [ ! -s /etc/cdi/nvidia.yaml ]; then
        log_step_error "system_config" "System Configuration" "CDI specification missing at /etc/cdi/nvidia.yaml"
        return 1
    fi
    
    log_step_success "system_config" "System Configuration" "CDI specification generated successfully"
}

# Phase 8: Verification
phase_verification() {
    log_step_start "verification" "System Verification" "Verifying all components are installed and working correctly"
    
    local all_checks_passed=true
    local check_results=()
    
    # Check Docker
    if command_exists docker && docker ps &>/dev/null 2>&1; then
        local docker_version=$(docker --version)
        check_results+=("{\"component\":\"docker\",\"status\":\"ok\",\"version\":\"$docker_version\"}")
        log_info "✓ Docker is installed and accessible"
    else
        check_results+=("{\"component\":\"docker\",\"status\":\"error\",\"message\":\"Docker is not accessible\"}")
        log_step_error "verification" "System Verification" "Docker is not accessible"
        all_checks_passed=false
    fi
    
    # Check NVIDIA drivers
    if command_exists nvidia-smi && nvidia-smi &>/dev/null 2>&1; then
        local driver_version=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
        check_results+=("{\"component\":\"nvidia_driver\",\"status\":\"ok\",\"version\":\"$driver_version\"}")
        log_info "✓ NVIDIA drivers are working (${driver_version})"
    else
        check_results+=("{\"component\":\"nvidia_driver\",\"status\":\"error\",\"message\":\"NVIDIA drivers are not working\"}")
        log_step_error "verification" "System Verification" "NVIDIA drivers are not working"
        all_checks_passed=false
    fi
    
    # Check GPU access in Docker
    if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
        check_results+=("{\"component\":\"gpu_docker_access\",\"status\":\"ok\"}")
        log_info "✓ GPU access in Docker works"
    else
        check_results+=("{\"component\":\"gpu_docker_access\",\"status\":\"error\",\"message\":\"GPU access in Docker does not work\"}")
        log_step_error "verification" "System Verification" "GPU access in Docker does not work"
        all_checks_passed=false
    fi
    
    # Check DCGM
    if command_exists dcgmi; then
        if dcgmi discovery -l &>/dev/null 2>&1; then
            check_results+=("{\"component\":\"dcgm\",\"status\":\"ok\"}")
            log_info "✓ DCGM is installed and working"
        else
            check_results+=("{\"component\":\"dcgm\",\"status\":\"warning\",\"message\":\"DCGM is installed but discovery failed\"}")
            log_step_warn "verification" "System Verification" "DCGM is installed but discovery failed"
        fi
    else
        check_results+=("{\"component\":\"dcgm\",\"status\":\"warning\",\"message\":\"DCGM is not installed\"}")
        log_step_warn "verification" "System Verification" "DCGM is not installed"
    fi
    
    # Check Fabric Manager
    if service_is_active nvidia-fabricmanager; then
        check_results+=("{\"component\":\"fabric_manager\",\"status\":\"ok\"}")
        log_info "✓ Fabric Manager is running"
    else
        check_results+=("{\"component\":\"fabric_manager\",\"status\":\"info\",\"message\":\"Fabric Manager is not running (may not be required for this GPU type)\"}")
        log_info "⚠ Fabric Manager is not running (may not be required for this GPU type)"
    fi
    
    # Check CDI specification
    if [ -s /etc/cdi/nvidia.yaml ]; then
        check_results+=("{\"component\":\"cdi_spec\",\"status\":\"ok\"}")
        log_info "✓ CDI specification exists"
    else
        check_results+=("{\"component\":\"cdi_spec\",\"status\":\"error\",\"message\":\"CDI specification is missing\"}")
        log_step_error "verification" "System Verification" "CDI specification is missing"
        all_checks_passed=false
    fi
    
    # Output structured verification results
    local results_json=$(IFS=','; echo "[${check_results[*]}]")
    echo "{\"type\":\"verification_results\",\"checks\":$results_json,\"all_passed\":$all_checks_passed,\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    
    if [ "$all_checks_passed" = true ]; then
        log_step_success "verification" "System Verification" "All critical checks passed! System is ready for telemetry stack deployment."
        return 0
    else
        log_step_error "verification" "System Verification" "Some checks failed. Please review the errors above."
        return 1
    fi
}

# Main execution
main() {
    log_info "=========================================="
    log_info "GPU Environment Deployment Script"
    log_info "=========================================="
    log_info "This script will set up GPU telemetry stack prerequisites"
    log_info "It is idempotent and can be run multiple times safely"
    log_info "Output includes structured logs for frontend consumption"
    log_info ""
    
    # Check if we're resuming after reboot
    if [ -f "$PROGRESS_FILE" ]; then
        # Parse JSON without jq (simple grep approach)
        local last_step=$(grep -o '"last_step":[0-9]*' "$PROGRESS_FILE" 2>/dev/null | cut -d: -f2 || echo "0")
        if [ -n "$last_step" ] && [ "$last_step" != "0" ]; then
            log_info "Resuming deployment after reboot (was at step $last_step)"
            wait_for_services_after_reboot
            rm -f "$PROGRESS_FILE"
        else
            rm -f "$PROGRESS_FILE"
        fi
    fi
    
    # Run all phases
    phase_system_info
    phase_docker
    phase_nvidia_driver
    phase_nvidia_container_toolkit
    phase_dcgm
    phase_fabric_manager
    phase_system_config
    phase_verification
    
    log_info ""
    log_info "=========================================="
    if [ "$NEEDS_REBOOT" = true ]; then
        log_step_warn "completion" "Deployment Complete" "A system reboot is recommended. After reboot, re-run this script to complete setup."
    else
        log_step_success "completion" "Deployment Complete" "Setup complete! System is ready for telemetry stack deployment."
        echo "{\"type\":\"deployment_complete\",\"status\":\"success\",\"progress\":100,\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    fi
    log_info "=========================================="
}

# Run main function
main "$@"
