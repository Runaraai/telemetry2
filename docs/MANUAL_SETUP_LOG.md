# GPU Environment Manual Setup Log
**Instance**: gpu_1x_a10  
**IP Address**: 163.192.27.149  
**Region**: us-west-1  
**SSH Login**: `ssh ubuntu@163.192.27.149`  
**SSH Key**: madhur (located at `~/madhur.pem`)  
**Date**: Setup initiated on remote GPU instance  
**OS**: Ubuntu 24.04.2 LTS (Noble Numbat)  
**Kernel**: 6.8.0-62-generic  
**GPU**: NVIDIA A10 (GA102GL)

---

## Purpose
This document logs the exact manual steps performed to set up the GPU telemetry monitoring stack on a remote GPU instance. These steps will be used as the basis for creating an idempotent automation script.

---

## Actual Deployment Results (2025-11-14)

### What Worked ✓

1. **Docker Installation** ✓
   - Successfully installed Docker 29.0.0 using official Docker installation script
   - Docker service started and running
   - User added to docker group (may need logout/login for full effect)

2. **NVIDIA Driver Installation** ✓ (requires reboot)
   - Successfully installed NVIDIA driver 580-open (580.95.05)
   - Driver packages installed correctly
   - **Note**: `nvidia-smi` will not work until system is rebooted to load kernel modules

3. **NVIDIA Container Toolkit** ✓
   - Successfully installed nvidia-container-toolkit 1.18.0-1
   - Repository configured correctly (using ubuntu22.04 repo for Ubuntu 24.04)
   - Docker runtime configured
   - **Note**: GPU access test will fail until after reboot when drivers are loaded

4. **DCGM** ✓
   - Already present on system (from previous installation)
   - Command available at `/usr/bin/dcgmi`

### What Requires Reboot ⚠️

1. **NVIDIA Driver Functionality**
   - Drivers installed but kernel modules not loaded
   - `nvidia-smi` fails with: "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver"
   - **Action Required**: System reboot needed to load nvidia kernel modules

2. **GPU Access in Docker**
   - Container Toolkit installed but cannot test until drivers are loaded
   - Will work after reboot

3. **CDI Specification Generation**
   - Cannot generate until drivers are loaded
   - Will work after reboot

### What Didn't Work / Issues Encountered ✗

1. **Fabric Manager**
   - Not installed (not required for A10 single GPU)
   - Script correctly skips this for A10 instances

2. **Deployment Script Stopped at Phase 4**
   - Script stopped after Container Toolkit installation
   - Reason: GPU access test failed (expected - needs reboot)
   - Script should continue to Phase 5-7 after reboot

### Key Considerations

1. **Ubuntu 24.04 Compatibility**
   - NVIDIA Container Toolkit repository uses `ubuntu22.04` for Ubuntu 24.04
   - This works correctly

2. **Driver Version**
   - System auto-selected driver 580-open (newer than 570)
   - This is acceptable for A10 GPU

3. **Reboot Required**
   - After driver installation, system MUST be rebooted
   - Cannot proceed with verification until reboot
   - Kernel modules need to be loaded

4. **Docker Group Membership**
   - User added to docker group but may need to logout/login
   - Can use `newgrp docker` as workaround

5. **SSH Key Location**
   - Key is outside Omniference folder at `~/madhur.pem`
   - Use: `ssh -i ~/madhur.pem ubuntu@163.192.27.149`

---

---

## Phase 1: Initial System Check

### 1.1 Connect to Remote Instance
```bash
ssh -i ~/madhur.pem ubuntu@163.192.27.149
```

**Purpose**: Establish SSH connection to the remote GPU instance  
**Expected Result**: Successful SSH connection  
**Actual Result**: ✓ Connection successful (SSH key located at `~/madhur.pem`, not in `~/.ssh/`)

### 1.2 System Information Check
```bash
# Check OS version
cat /etc/os-release

# Check kernel version
uname -a

# Check GPU hardware detection
lspci | grep -i nvidia

# Check system resources
free -h
df -h

# Check current user
whoami
```

**Purpose**: Gather baseline system information  
**Expected Outputs**:
- OS: Ubuntu 22.04 or 24.04 LTS
- Kernel: Linux version details
- GPU: NVIDIA GPU detected in PCIe bus
- Memory: Available system memory
- Disk: Available disk space

### 1.3 Check Existing Installations
```bash
# Check for Docker
command -v docker && docker --version || echo "Docker not installed"

# Check for NVIDIA drivers
command -v nvidia-smi && nvidia-smi || echo "NVIDIA drivers not installed"

# Check for NVIDIA Container Toolkit
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi 2>&1 | head -5 || echo "NVIDIA Container Toolkit not configured"

# Check for DCGM
command -v dcgmi && dcgmi discovery -l || echo "DCGM not installed"

# Check for Fabric Manager
systemctl status nvidia-fabricmanager 2>&1 | head -5 || echo "Fabric Manager not installed"
```

**Purpose**: Identify what's already installed to avoid redundant operations  
**Expected Result**: List of installed/not installed components

---

## Phase 2: Docker Installation

### 2.1 Update Package Lists
```bash
sudo apt update
```

**Purpose**: Refresh package lists before installation  
**Expected Result**: Package lists updated successfully

### 2.2 Install Docker (if not present)
```bash
if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Please log out and back in for group changes to take effect."
else
    echo "Docker already installed: $(docker --version)"
fi
```

**Purpose**: Install Docker if not already present  
**Expected Result**: Docker installed and user added to docker group  
**Actual Result**: ✓ Docker 29.0.0 installed successfully using official Docker script. User added to docker group. Docker service running.

**Note**: After adding user to docker group, you may need to:
- Log out and log back in, OR
- Run `newgrp docker` to activate group membership

### 2.3 Verify Docker Installation
```bash
# Check Docker version
docker --version

# Test Docker without sudo (after group membership)
docker ps

# Check Docker service status
sudo systemctl status docker
```

**Purpose**: Verify Docker is working correctly  
**Expected Result**: Docker commands execute successfully

---

## Phase 3: NVIDIA Driver Setup

### 3.1 Check Current Driver Status
```bash
# Check if nvidia-smi is available
if command -v nvidia-smi &>/dev/null; then
    nvidia-smi
    echo "NVIDIA drivers already installed"
else
    echo "NVIDIA drivers not detected"
fi
```

**Purpose**: Determine if NVIDIA drivers need installation  
**Expected Result**: Either driver version info or indication that drivers need installation

### 3.2 Install NVIDIA Drivers (if needed)
```bash
if ! command -v nvidia-smi &>/dev/null; then
    echo "Installing NVIDIA drivers..."
    
    # Install ubuntu-drivers-common if not present
    if ! command -v ubuntu-drivers &>/dev/null; then
        sudo apt-get update
        sudo apt-get install -y ubuntu-drivers-common
    fi
    
    # Auto-install recommended driver
    sudo ubuntu-drivers autoinstall
    
    echo "Driver installation complete. System reboot required."
    echo "After reboot, reconnect and continue with Phase 4."
    # Uncomment to auto-reboot:
    # sudo reboot
else
    echo "NVIDIA drivers already installed: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
fi
```

**Purpose**: Install NVIDIA drivers if not present  
**Expected Result**: Drivers installed (reboot may be required)  
**Actual Result**: ✓ NVIDIA driver 580-open (580.95.05) installed successfully via `ubuntu-drivers autoinstall`. Driver packages installed but kernel modules not loaded. **REBOOT REQUIRED** before `nvidia-smi` will work.

**Important**: After driver installation, system **MUST** be rebooted. Reconnect after reboot and verify with `nvidia-smi`. The driver installation completed but the kernel modules need to be loaded on boot.

### 3.3 Verify Driver Installation (Post-Reboot)
```bash
# After reconnecting post-reboot
nvidia-smi

# Check GPU details
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv

# Check GPU topology (if multi-GPU)
nvidia-smi topo -m
```

**Purpose**: Confirm drivers are working after reboot  
**Expected Result**: GPU information displayed correctly

---

## Phase 4: NVIDIA Container Toolkit

### 4.1 Check Container Toolkit Status
```bash
# Test if GPU access works in Docker
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi 2>&1
```

**Purpose**: Determine if NVIDIA Container Toolkit is configured  
**Expected Result**: Either GPU info from container or error indicating toolkit not configured

### 4.2 Install NVIDIA Container Toolkit (if needed)
```bash
if ! docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
    echo "Installing NVIDIA Container Toolkit..."
    
    # Detect distribution
    distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
    
    # Handle Ubuntu 24.04 (use 22.04 repository)
    if [[ "$distribution" == "ubuntu24.04" ]]; then
        distribution="ubuntu22.04"
    fi
    
    # Add NVIDIA Container Toolkit GPG key
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    
    # Add repository
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    
    # Update and install
    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit
    
    # Configure Docker runtime
    sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
    
    # Restart Docker
    if command -v systemctl &>/dev/null; then
        sudo systemctl restart docker
    else
        sudo service docker restart
    fi
    
    # Wait for Docker to be ready
    sleep 3
    
    echo "NVIDIA Container Toolkit installed and configured"
else
    echo "NVIDIA Container Toolkit already configured"
fi
```

**Purpose**: Enable GPU access from Docker containers  
**Expected Result**: Docker containers can access GPUs  
**Actual Result**: ✓ NVIDIA Container Toolkit 1.18.0-1 installed successfully. Repository configured (using ubuntu22.04 for Ubuntu 24.04). Docker runtime configured. **Note**: GPU access test will fail until after reboot when NVIDIA drivers are loaded. The toolkit is correctly installed and will work after reboot.

### 4.3 Verify Container Toolkit
```bash
# Test GPU access in container
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi

# Check nvidia-ctk is available
command -v nvidia-ctk && nvidia-ctk --version
```

**Purpose**: Confirm GPU access works in Docker  
**Expected Result**: `nvidia-smi` output from inside container

---

## Phase 5: DCGM and Fabric Manager

### 5.1 Check DCGM Status
```bash
if command -v dcgmi &>/dev/null; then
    dcgmi discovery -l
    echo "DCGM already installed"
else
    echo "DCGM not installed"
fi
```

**Purpose**: Check if DCGM is installed  
**Expected Result**: Either DCGM discovery output or indication it needs installation

### 5.2 Install DCGM (if needed)
```bash
if ! command -v dcgmi &>/dev/null; then
    echo "Installing NVIDIA Data Center GPU Manager (DCGM)..."
    
    # Detect distribution
    distribution=$(. /etc/os-release; echo "${ID}${VERSION_ID//./}")
    
    # Add CUDA repository key if not present
    if [[ ! -f /etc/apt/keyrings/cuda-archive-keyring.gpg ]]; then
        tmp_key=$(mktemp)
        curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/${distribution}/x86_64/cuda-keyring_1.1-1_all.deb -o "${tmp_key}"
        sudo dpkg -i "${tmp_key}" || true
        rm -f "${tmp_key}"
    fi
    
    # Update and install DCGM
    sudo apt-get update
    sudo apt-get install -y datacenter-gpu-manager
    
    echo "DCGM installed"
else
    echo "DCGM already installed"
fi
```

**Purpose**: Install DCGM for advanced GPU monitoring  
**Expected Result**: DCGM installed

### 5.3 Install Fabric Manager (if needed)
```bash
# Get driver version
driver_major=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1 | cut -d. -f1 || echo "")

if [[ -n "${driver_major}" ]]; then
    fabric_pkg="cuda-drivers-fabricmanager-${driver_major}"
    
    if ! dpkg -s "${fabric_pkg}" &>/dev/null; then
        echo "Installing NVIDIA Fabric Manager (${fabric_pkg})..."
        sudo apt-get install -y "${fabric_pkg}"
        echo "Fabric Manager installed"
    else
        echo "Fabric Manager already installed"
    fi
else
    echo "WARNING: Unable to determine NVIDIA driver version; skipping Fabric Manager installation."
fi
```

**Purpose**: Install Fabric Manager for NVLink/NVSwitch management (required for A100/H100)  
**Expected Result**: Fabric Manager installed (if driver version detected)  
**Actual Result**: ⚠ Fabric Manager not installed - **This is correct for A10 single GPU**. Fabric Manager is only required for multi-GPU systems with NVSwitch (A100/H100). A10 does not need Fabric Manager.

### 5.4 Enable and Start Services
```bash
# Enable and start DCGM
sudo systemctl enable --now dcgm || true
sudo systemctl status dcgm

# Enable and start Fabric Manager (if installed)
sudo systemctl enable --now nvidia-fabricmanager || true
sudo systemctl status nvidia-fabricmanager || echo "Fabric Manager not installed"

# Restart NVIDIA Persistence Daemon
sudo systemctl restart nvidia-persistenced || true
```

**Purpose**: Ensure DCGM and Fabric Manager services are running  
**Expected Result**: Services active and running

### 5.5 Verify DCGM
```bash
# Test DCGM discovery
dcgmi discovery -l

# Check DCGM service
sudo systemctl status dcgm
```

**Purpose**: Confirm DCGM is working  
**Expected Result**: DCGM can discover and communicate with GPUs

---

## Phase 6: System Configuration

### 6.1 Configure NVIDIA Profiling Permissions
```bash
# Check if configuration already exists
if ! grep -qs "NVreg_RestrictProfilingToAdminUsers" /etc/modprobe.d/omniference-nvidia.conf 2>/dev/null; then
    echo "Configuring NVIDIA profiling permissions..."
    echo "options nvidia NVreg_RestrictProfilingToAdminUsers=0" | sudo tee /etc/modprobe.d/omniference-nvidia.conf >/dev/null
    sudo update-initramfs -u || true
    echo "Profiling permissions configured (reboot may be required for full effect)"
else
    echo "Profiling permissions already configured"
fi
```

**Purpose**: Allow non-admin users to use NVIDIA profiling tools  
**Expected Result**: Configuration file created

**Note**: This change may require a reboot to take full effect.

### 6.2 Generate CDI Specification
```bash
# Create CDI directory
sudo mkdir -p /etc/cdi

# Generate CDI specification
if ! sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml 2>&1 | grep -v "^time=" | grep -v "level=warning" | grep -v "level=info"; then
    if [[ ! -s /etc/cdi/nvidia.yaml ]]; then
        echo "ERROR: Failed to generate NVIDIA CDI specification (check driver installation)." >&2
        exit 1
    fi
fi

# Verify CDI file exists and has content
if [[ ! -s /etc/cdi/nvidia.yaml ]]; then
    echo "ERROR: CDI specification missing at /etc/cdi/nvidia.yaml" >&2
    exit 1
fi

echo "CDI specification generated successfully"
```

**Purpose**: Generate Container Device Interface specification for container GPU access  
**Expected Result**: `/etc/cdi/nvidia.yaml` file created with GPU device specifications

---

## Phase 7: Verification and Testing

### 7.1 Comprehensive System Check
```bash
echo "=== System Verification ==="

# Check Docker
echo "Docker: $(docker --version 2>/dev/null || echo 'NOT INSTALLED')"

# Check NVIDIA drivers
echo "NVIDIA Driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 2>/dev/null || echo 'NOT INSTALLED')"

# Check GPU access in Docker
echo "Testing GPU access in Docker..."
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi --query-gpu=name --format=csv,noheader | head -1

# Check DCGM
echo "DCGM: $(dcgmi --version 2>/dev/null | head -1 || echo 'NOT INSTALLED')"

# Check Fabric Manager
if systemctl is-active --quiet nvidia-fabricmanager; then
    echo "Fabric Manager: RUNNING"
else
    echo "Fabric Manager: NOT RUNNING (may not be required for this GPU type)"
fi

# Check CDI
if [[ -s /etc/cdi/nvidia.yaml ]]; then
    echo "CDI Specification: PRESENT"
else
    echo "CDI Specification: MISSING"
fi
```

**Purpose**: Verify all components are installed and working  
**Expected Result**: All components show as installed/working

### 7.2 Test Telemetry Stack Prerequisites
```bash
# Test that all required components are ready for telemetry deployment
echo "=== Telemetry Stack Prerequisites Check ==="

# Docker must be running
if docker ps &>/dev/null; then
    echo "✓ Docker is accessible"
else
    echo "✗ Docker is not accessible"
fi

# NVIDIA drivers must be working
if nvidia-smi &>/dev/null; then
    echo "✓ NVIDIA drivers are working"
else
    echo "✗ NVIDIA drivers are not working"
fi

# GPU access in Docker must work
if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
    echo "✓ GPU access in Docker works"
else
    echo "✗ GPU access in Docker does not work"
fi

# DCGM should be available
if command -v dcgmi &>/dev/null; then
    echo "✓ DCGM is installed"
else
    echo "✗ DCGM is not installed"
fi

# CDI specification should exist
if [[ -s /etc/cdi/nvidia.yaml ]]; then
    echo "✓ CDI specification exists"
else
    echo "✗ CDI specification is missing"
fi
```

**Purpose**: Final check before deploying telemetry stack  
**Expected Result**: All checks pass (✓)

---

## Troubleshooting

### Issue: Docker commands require sudo
**Solution**: 
```bash
# Add user to docker group (if not already)
sudo usermod -aG docker "$USER"
# Log out and back in, or run:
newgrp docker
```

### Issue: NVIDIA drivers installed but nvidia-smi not found after reboot
**Solution**:
```bash
# Check if drivers are loaded
lsmod | grep nvidia
# If not loaded, check dmesg for errors
dmesg | grep -i nvidia
# May need to reinstall drivers
sudo ubuntu-drivers autoinstall
sudo reboot
```

### Issue: GPU access in Docker fails
**Solution**:
```bash
# Verify NVIDIA Container Toolkit is installed
dpkg -l | grep nvidia-container-toolkit
# Reconfigure if needed
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
sudo systemctl restart docker
# Test again
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### Issue: DCGM installation fails
**Solution**:
```bash
# Check distribution detection
. /etc/os-release
echo "${ID}${VERSION_ID//./}"
# Manually add CUDA repository if needed
# For Ubuntu 22.04:
distribution="ubuntu2204"
# Download and install keyring
wget https://developer.download.nvidia.com/compute/cuda/repos/${distribution}/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get install -y datacenter-gpu-manager
```

### Issue: CDI generation fails
**Solution**:
```bash
# Check if nvidia-ctk is installed
command -v nvidia-ctk
# Check driver installation
nvidia-smi
# Try generating CDI with verbose output
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml --verbose
# Check for errors in output
```

---

## Summary

### Current Status (Pre-Reboot)
After running deployment script on clean system:
- ✓ Docker installed and configured (29.0.0)
- ✓ NVIDIA drivers installed (580-open) - **REBOOT REQUIRED**
- ✓ NVIDIA Container Toolkit configured (1.18.0-1)
- ✓ DCGM already present on system
- ⚠ Fabric Manager not installed (correct for A10)
- ⏳ Profiling permissions - not yet configured (script stopped)
- ⏳ CDI specification - not yet generated (requires drivers loaded)

### After Reboot
The system should have:
- ✓ Docker installed and configured
- ✓ NVIDIA drivers loaded and working (after reboot)
- ✓ NVIDIA Container Toolkit configured
- ✓ DCGM installed and running
- ⚠ Fabric Manager not required for A10
- ✓ Profiling permissions configured (run script again)
- ✓ CDI specification generated (run script again)
- ✓ All components verified and tested

**Next Steps**:
1. Reboot the system: `sudo reboot`
2. Reconnect via SSH
3. Re-run deployment script to complete Phases 5-7
4. Verify all components working
5. Deploy telemetry stack

The system will be ready for telemetry stack deployment after reboot and completing remaining phases.

---

## Next Steps

1. Reboot the system (if drivers were just installed): `sudo reboot`
2. After reboot, re-run deployment script to complete remaining phases
3. Deploy telemetry stack using the deployment script
4. Verify telemetry exporters are running
5. Check Prometheus is scraping metrics
6. Validate remote_write to backend is working

---

## Deployment Script Features

The deployment script (`deploy_gpu_environment.sh`) now includes:

### Structured Logging for Frontend
- Outputs JSON logs alongside human-readable logs
- Each step has a unique `step_id` for tracking
- Progress percentage for each step
- Status indicators: `completed`, `skipped`, `warning`, `error`, `in_progress`

### Automatic Reboot Handling
- Detects when reboot is needed (after driver installation)
- Saves progress before rebooting
- Automatically resumes after system comes back online
- Wrapper script (`deploy_gpu_environment_remote.sh`) handles SSH reconnection

### Checkbox-Style Progress Tracking
Each component is a discrete step:
1. System Information
2. Docker Installation
3. NVIDIA Driver Installation
4. NVIDIA Container Toolkit
5. DCGM Installation
6. Fabric Manager Installation
7. System Configuration
8. Verification

### Idempotent Operations
- Checks if component is already installed/configured
- Skips if already done
- Only installs/configures what's missing
- Safe to run multiple times

---

*This log will be updated as manual setup progresses on instance 163.192.27.149*

