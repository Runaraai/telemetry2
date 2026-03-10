#!/usr/bin/env bash
# Remote GPU Environment Deployment Wrapper
# Handles SSH connection, reboot detection, and automatic resumption
# Usage: ./deploy_gpu_environment_remote.sh <ip> <user> <ssh_key_path>

set -euo pipefail

SSH_IP="${1:-}"
SSH_USER="${2:-ubuntu}"
SSH_KEY="${3:-}"

if [ -z "$SSH_IP" ]; then
    echo "Usage: $0 <ip_address> [user] [ssh_key_path]"
    echo "Example: $0 163.192.27.149 ubuntu ~/madhur.pem"
    exit 1
fi

# Find SSH key if not provided
if [ -z "$SSH_KEY" ]; then
    # Try common locations
    if [ -f ~/madhur.pem ]; then
        SSH_KEY=~/madhur.pem
    elif [ -f ~/.ssh/madhur ]; then
        SSH_KEY=~/.ssh/madhur
    elif [ -f ~/.ssh/id_rsa ]; then
        SSH_KEY=~/.ssh/id_rsa
    else
        echo "Error: SSH key not found. Please specify path."
        exit 1
    fi
fi

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"

# Function to check if system is online
check_system_online() {
    ssh $SSH_OPTS ${SSH_USER}@${SSH_IP} "echo 'online'" &>/dev/null 2>&1
}

# Function to wait for system to come back online
wait_for_system_online() {
    local max_attempts=120
    local attempt=1
    local check_interval=5
    
    echo "{\"type\":\"reboot_wait\",\"message\":\"Waiting for system to come back online after reboot...\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    echo "System rebooted. Waiting for system to come back online..."
    echo "This may take 1-2 minutes..."
    
    while [ $attempt -le $max_attempts ]; do
        if check_system_online; then
            echo "{\"type\":\"reboot_online\",\"message\":\"System is back online\",\"elapsed_seconds\":$((attempt * check_interval)),\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
            echo "System is back online! Waiting 10 seconds for services to initialize..."
            sleep 10
            return 0
        fi
        sleep $check_interval
        attempt=$((attempt + 1))
        if [ $((attempt % 12)) -eq 0 ]; then
            echo "{\"type\":\"reboot_wait_progress\",\"elapsed_seconds\":$((attempt * check_interval)),\"message\":\"Still waiting for system to come back online...\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
            echo "Still waiting... (${attempt}0 seconds elapsed)"
        fi
    done
    
    echo "{\"type\":\"reboot_timeout\",\"message\":\"System did not come back online within expected time\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    echo "Error: System did not come back online within expected time"
    return 1
}

# Function to upload and run deployment script
run_deployment() {
    local script_path="$1"
    local remote_script="~/deploy_gpu_environment.sh"
    local max_iterations=3  # Maximum number of reboot/resume cycles
    local iteration=0
    
    while [ $iteration -lt $max_iterations ]; do
        iteration=$((iteration + 1))
        
        if [ $iteration -gt 1 ]; then
            echo "{\"type\":\"deployment_resume\",\"iteration\":$iteration,\"message\":\"Resuming deployment after reboot\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
        else
            echo "{\"type\":\"upload_start\",\"message\":\"Uploading deployment script to remote system\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
        fi
        
        # Upload script (always upload to ensure latest version)
        scp $SSH_OPTS "$script_path" ${SSH_USER}@${SSH_IP}:${remote_script} || {
            echo "{\"type\":\"upload_error\",\"message\":\"Failed to upload deployment script\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
            return 1
        }
        
        # Upload config if exists
        local config_path="$(dirname "$script_path")/gpu_setup_config.sh"
        if [ -f "$config_path" ]; then
            scp $SSH_OPTS "$config_path" ${SSH_USER}@${SSH_IP}:~/gpu_setup_config.sh
        fi
        
        if [ $iteration -eq 1 ]; then
            echo "{\"type\":\"deployment_start\",\"message\":\"Starting deployment on remote system\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
        fi
        
        # Track if reboot was detected
        local reboot_detected=false
        
        # Run script and capture output
        ssh $SSH_OPTS ${SSH_USER}@${SSH_IP} "chmod +x ${remote_script} && bash ${remote_script}" 2>&1 | while IFS= read -r line || [ -n "$line" ]; do
            # Output structured logs as-is
            if [[ "$line" =~ ^\{.*\}$ ]]; then
                echo "$line"
                # Check for reboot notification
                if echo "$line" | grep -q "\"type\":\"reboot_initiated\""; then
                    reboot_detected=true
                fi
            else
                # Also output human-readable
                echo "$line"
            fi
        done
        
        # Check if system went offline (reboot happened)
        sleep 5  # Give system time to reboot
        if ! check_system_online; then
            echo "{\"type\":\"reboot_wait_start\",\"message\":\"System rebooted, waiting for it to come back online\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
            if wait_for_system_online; then
                # Continue loop to resume
                continue
            else
                echo "{\"type\":\"reboot_timeout\",\"message\":\"System did not come back online\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
                return 1
            fi
        else
            # System is online and script completed
            echo "{\"type\":\"deployment_complete\",\"message\":\"Deployment completed successfully\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
            return 0
        fi
    done
    
    echo "{\"type\":\"max_iterations\",\"message\":\"Maximum reboot iterations reached\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    return 1
}

# Main execution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="${SCRIPT_DIR}/deploy_gpu_environment.sh"

if [ ! -f "$DEPLOY_SCRIPT" ]; then
    echo "Error: Deployment script not found at $DEPLOY_SCRIPT"
    exit 1
fi

# Check initial connectivity
if ! check_system_online; then
    echo "{\"type\":\"connection_error\",\"message\":\"Cannot connect to ${SSH_IP}. Please check SSH connectivity.\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
    exit 1
fi

echo "{\"type\":\"deployment_init\",\"ip\":\"$SSH_IP\",\"user\":\"$SSH_USER\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
run_deployment "$DEPLOY_SCRIPT"

