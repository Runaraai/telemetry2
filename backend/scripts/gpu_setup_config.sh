#!/usr/bin/env bash
# GPU Environment Setup Configuration
# Centralized configuration for GPU environment deployment
# Source this file or set these variables before running deploy_gpu_environment.sh

# Docker Configuration
# Version to install: "latest" or specific version
DOCKER_VERSION="${DOCKER_VERSION:-latest}"

# NVIDIA Driver Configuration
# "auto" for auto-detection, or specific version like "570", "535", etc.
NVIDIA_DRIVER_VERSION="${NVIDIA_DRIVER_VERSION:-auto}"

# Fabric Manager Configuration
# Set to "true" to install Fabric Manager (required for A100/H100 with NVSwitch)
# Set to "false" to skip (not required for A10 or single-GPU setups)
ENABLE_FABRIC_MANAGER="${ENABLE_FABRIC_MANAGER:-true}"

# Instance-Specific Configuration
# These can be set when deploying remotely via SSH
INSTANCE_IP="${INSTANCE_IP:-}"
INSTANCE_USER="${INSTANCE_USER:-ubuntu}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"

# CUDA Version for Container Testing
# Version to use when testing GPU access in Docker containers
CUDA_TEST_VERSION="${CUDA_TEST_VERSION:-11.8.0}"

# Logging Configuration
# Set to "true" to enable verbose logging
VERBOSE_LOGGING="${VERBOSE_LOGGING:-false}"

# Reboot Configuration
# Set to "true" to automatically reboot after driver installation (if needed)
# Set to "false" to prompt user or skip reboot
AUTO_REBOOT="${AUTO_REBOOT:-false}"

# Export all variables for use in deployment script
export DOCKER_VERSION
export NVIDIA_DRIVER_VERSION
export ENABLE_FABRIC_MANAGER
export INSTANCE_IP
export INSTANCE_USER
export SSH_KEY_PATH
export CUDA_TEST_VERSION
export VERBOSE_LOGGING
export AUTO_REBOOT

# Example usage:
# 
# 1. For local setup with defaults:
#    source gpu_setup_config.sh
#    ./deploy_gpu_environment.sh
#
# 2. For A10 instance (Fabric Manager not required):
#    export ENABLE_FABRIC_MANAGER=false
#    ./deploy_gpu_environment.sh
#
# 3. For A100/H100 instance (Fabric Manager required):
#    export ENABLE_FABRIC_MANAGER=true
#    export NVIDIA_DRIVER_VERSION=570
#    ./deploy_gpu_environment.sh
#
# 4. For remote deployment via SSH:
#    export INSTANCE_IP="163.192.27.149"
#    export INSTANCE_USER="ubuntu"
#    export SSH_KEY_PATH="~/.ssh/madhur"
#    # Then use SSH to run the script remotely

