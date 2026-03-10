#!/bin/bash
set -euo pipefail

# Unified install script for Omniference provisioning agent
# Usage: curl -fsSL https://omniference.com/install | bash -s -- --api-key=YOUR_KEY --instance-id=YOUR_INSTANCE_ID

AGENT_VERSION="2.0.9"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
CONFIG_DIR="/etc/omniference"
AGENT_BINARY="${INSTALL_DIR}/provisioning-agent"
API_BASE_URL="${API_BASE_URL:-https://omniference.com}"

# Helper: apt-get with automatic allow-downgrades for non-update commands (needed on some clouds like Scaleway)
APT_GET_BIN="/usr/bin/apt-get"
apt_get() {
    local cmd=""
    for arg in "$@"; do
        case "$arg" in
            -*) ;;
            *) cmd="$arg"; break ;;
        esac
    done
    if [[ "$cmd" == "update" ]]; then
        "$APT_GET_BIN" "$@"
    else
        "$APT_GET_BIN" --allow-downgrades "$@"
    fi
}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse command line arguments
API_KEY=""
INSTANCE_ID=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --api-key=*)
            API_KEY="${1#*=}"
            shift
            ;;
        --instance-id=*)
            INSTANCE_ID="${1#*=}"
            shift
            ;;
        --api-key)
            API_KEY="$2"
            shift 2
            ;;
        --instance-id)
            INSTANCE_ID="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Usage: $0 --api-key=YOUR_KEY --instance-id=YOUR_INSTANCE_ID"
            exit 1
            ;;
    esac
done

if [[ -z "$API_KEY" ]] || [[ -z "$INSTANCE_ID" ]]; then
    log_error "Both --api-key and --instance-id are required"
    echo "Usage: $0 --api-key=YOUR_KEY --instance-id=YOUR_INSTANCE_ID"
    exit 1
fi

# Check if running as root or with sudo
if [[ "$EUID" -ne 0 ]]; then
    log_error "This script requires root privileges. Please run with sudo."
    exit 1
fi

log_info "Installing Omniference provisioning agent v${AGENT_VERSION}..."

# Detect OS
detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$ID
        OS_VERSION=$VERSION_ID
    else
        log_error "Cannot detect OS. This script requires /etc/os-release."
        exit 1
    fi
    log_info "Detected OS: $OS $OS_VERSION"
}

# Check NVIDIA driver
check_nvidia_driver() {
    if ! command -v nvidia-smi &> /dev/null; then
        log_error "nvidia-smi not found. NVIDIA driver must be installed first."
        echo ""
        echo "For Ubuntu/Debian:"
        echo "  sudo apt update"
        echo "  sudo ubuntu-drivers install"
        echo "  sudo reboot"
        echo ""
        echo "After reboot, run this script again."
        exit 1
    fi
    log_info "NVIDIA driver detected: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
}

# Wait for Docker to be ready
wait_for_docker() {
    local max_attempts=30
    local attempt=0
    while [[ $attempt -lt $max_attempts ]]; do
        if docker info &> /dev/null; then
            log_info "Docker is ready"
            return 0
        fi
        attempt=$((attempt + 1))
        log_warn "Waiting for Docker to be ready... ($attempt/$max_attempts)"
        sleep 2
    done
    log_error "Docker did not become ready after $max_attempts attempts"
    return 1
}

# Install Docker (idempotent)
install_docker() {
    if command -v docker &> /dev/null; then
        log_info "Docker is already installed"
        return 0
    fi

    log_info "Installing Docker..."
    case $OS in
        ubuntu|debian)
            apt_get update -qq
            apt_get install -y -qq docker.io docker-compose-v2
            systemctl enable docker
            systemctl start docker
            wait_for_docker
            ;;
        rhel|centos|fedora|amzn)
            yum install -y -q docker
            systemctl enable docker
            systemctl start docker
            wait_for_docker
            ;;
        *)
            log_error "Unsupported OS: $OS"
            exit 1
            ;;
    esac
    log_info "Docker installed successfully"
}

# Clean up conflicting NVIDIA Container Toolkit configurations
cleanup_nvidia_toolkit_conflicts() {
    log_info "Checking for conflicting NVIDIA Container Toolkit configurations..."
    
    case $OS in
        ubuntu|debian)
            # Remove conflicting source list files
            if [[ -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]]; then
                log_warn "Removing existing nvidia-container-toolkit.list to resolve conflicts"
                rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list
            fi
            if [[ -f /etc/apt/sources.list.d/nvidia-docker-container.list ]]; then
                log_warn "Removing existing nvidia-docker-container.list to resolve conflicts"
                rm -f /etc/apt/sources.list.d/nvidia-docker-container.list
            fi
            
            # Search for and remove any source files that reference the cloud-init GPG key or nvidia repository
            log_info "Scanning for conflicting repository entries..."
            for source_file in /etc/apt/sources.list.d/*.list /etc/apt/sources.list; do
                if [[ -f "$source_file" ]]; then
                    # Check if file contains references to nvidia repository with cloud-init GPG key
                    if grep -q "nvidia.github.io/libnvidia-container" "$source_file" 2>/dev/null; then
                        if grep -q "cloud-init.gpg.d/nvidia-docker-container.gpg" "$source_file" 2>/dev/null || \
                           grep -q "signed-by.*nvidia" "$source_file" 2>/dev/null; then
                            log_warn "Found conflicting NVIDIA repository entry in $source_file"
                            # Create backup
                            cp "$source_file" "${source_file}.bak.$(date +%s)"
                            # Remove or comment out lines with nvidia repository references
                            sed -i '/nvidia.github.io\/libnvidia-container/d' "$source_file"
                            log_info "Removed conflicting entries from $source_file (backup created)"
                        fi
                    fi
                fi
            done
            
            # Remove conflicting GPG keys
            if [[ -f /etc/apt/cloud-init.gpg.d/nvidia-docker-container.gpg ]]; then
                log_warn "Removing conflicting cloud-init GPG key"
                rm -f /etc/apt/cloud-init.gpg.d/nvidia-docker-container.gpg
            fi
            if [[ -f /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg ]]; then
                log_warn "Removing existing GPG keyring to ensure clean install"
                rm -f /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
            fi
            
            # Also check for any GPG key files in cloud-init directory that might be referenced
            if [[ -d /etc/apt/cloud-init.gpg.d ]]; then
                for gpg_file in /etc/apt/cloud-init.gpg.d/*nvidia*.gpg; do
                    if [[ -f "$gpg_file" ]]; then
                        log_warn "Removing conflicting GPG key: $gpg_file"
                        rm -f "$gpg_file"
                    fi
                done
            fi
            ;;
        rhel|centos|fedora|amzn)
            # Remove conflicting repo files
            if [[ -f /etc/yum.repos.d/nvidia-container-toolkit.repo ]]; then
                log_warn "Removing existing nvidia-container-toolkit.repo to resolve conflicts"
                rm -f /etc/yum.repos.d/nvidia-container-toolkit.repo
            fi
            ;;
    esac
    
    log_info "Cleanup complete"
}

# Install NVIDIA Container Toolkit (idempotent)
install_nvidia_toolkit() {
    if dpkg -l | grep -q nvidia-container-toolkit 2>/dev/null || rpm -q nvidia-container-toolkit &> /dev/null; then
        log_info "NVIDIA Container Toolkit is already installed"
        return 0
    fi

    log_info "Installing NVIDIA Container Toolkit..."
    
    # Clean up any conflicting configurations first
    cleanup_nvidia_toolkit_conflicts
    
    case $OS in
        ubuntu|debian)
            distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
            mkdir -p /usr/share/keyrings
            
            # Download and install GPG key
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor --yes --batch -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
            
            # Create source list with proper GPG key reference
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
                sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
                tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
            
            # Update package lists (with error handling)
            log_info "Updating package lists..."
            UPDATE_OUTPUT=$(apt_get update -qq 2>&1) || {
                UPDATE_EXIT_CODE=$?
                log_error "apt-get update failed (exit code: $UPDATE_EXIT_CODE)"
                echo "$UPDATE_OUTPUT" | grep -i "conflict\|signed-by\|error" || echo "$UPDATE_OUTPUT"
                
                log_error ""
                log_error "This is likely due to conflicting repository configurations."
                log_error "Attempting to find and fix conflicts..."
                
                # Try to find any remaining conflicting source files
                CONFLICT_FOUND=false
                for source_file in /etc/apt/sources.list.d/*.list /etc/apt/sources.list; do
                    if [[ -f "$source_file" ]] && grep -q "nvidia.github.io/libnvidia-container" "$source_file" 2>/dev/null; then
                        if grep -q "cloud-init.gpg.d\|nvidia-docker-container.gpg" "$source_file" 2>/dev/null; then
                            log_warn "Found additional conflict in: $source_file"
                            CONFLICT_FOUND=true
                            # Show the conflicting line
                            grep "nvidia" "$source_file" | head -5
                        fi
                    fi
                done
                
                if [[ "$CONFLICT_FOUND" == "true" ]]; then
                    log_error ""
                    log_error "Please manually fix the conflicts by:"
                    log_error "  1. Removing or commenting out conflicting lines in source files"
                    log_error "  2. Or removing the entire conflicting source file"
                    log_error "  3. Then run: sudo apt update"
                    log_error ""
                    log_error "You can search for conflicts with:"
                    log_error "  grep -r 'nvidia.github.io/libnvidia-container' /etc/apt/sources.list.d/ /etc/apt/sources.list"
                else
                    log_error ""
                    log_error "Please check the error output above and resolve manually."
                fi
                exit 1
            }
            
            apt_get install -y -qq nvidia-container-toolkit
            nvidia-ctk runtime configure --runtime=docker
            systemctl restart docker
            wait_for_docker
            ;;
        rhel|centos|fedora|amzn)
            distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
            mkdir -p /usr/share/keyrings
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor --yes --batch -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | \
                tee /etc/yum.repos.d/nvidia-container-toolkit.repo > /dev/null
            yum install -y -q nvidia-container-toolkit
            nvidia-ctk runtime configure --runtime=docker
            systemctl restart docker
            wait_for_docker
            ;;
        *)
            log_error "Unsupported OS for NVIDIA Container Toolkit: $OS"
            exit 1
            ;;
    esac
    log_info "NVIDIA Container Toolkit installed successfully"
}

# Download and install agent binary
install_agent_binary() {
    log_info "Downloading agent binary..."
    
    # Ensure install directory exists
    mkdir -p "${INSTALL_DIR}"
    
    # Try domain first, fallback to GitHub
    AGENT_URL="${AGENT_BINARY_URL:-https://omniference.com/downloads/provisioning-agent-linux-amd64}"
    GITHUB_URL="https://github.com/omniference/provisioning-agent/releases/download/v${AGENT_VERSION}/provisioning-agent-linux-amd64"
    
    # Download to temp file first, then move (more reliable)
    TEMP_BINARY="/tmp/provisioning-agent-${AGENT_VERSION}"
    
    if curl -fsSL -o "${TEMP_BINARY}" "${AGENT_URL}" 2>&1; then
        log_info "Downloaded from domain"
    else
        log_warn "Domain download failed, trying GitHub fallback..."
        if ! curl -fsSL -o "${TEMP_BINARY}" "${GITHUB_URL}" 2>&1; then
            log_error "Failed to download agent binary from both sources"
            log_error "Tried: ${AGENT_URL}"
            log_error "Tried: ${GITHUB_URL}"
            exit 1
        fi
        log_info "Downloaded from GitHub"
    fi
    
    # Move to final location
    mv "${TEMP_BINARY}" "${AGENT_BINARY}"
    chmod +x "${AGENT_BINARY}"
    log_info "Agent binary installed to ${AGENT_BINARY}"
}

# Create config directory and file
create_config() {
    mkdir -p "${CONFIG_DIR}"
    cat > "${CONFIG_DIR}/config.env" <<EOF
API_KEY=${API_KEY}
INSTANCE_ID=${INSTANCE_ID}
API_BASE_URL=${API_BASE_URL}
EOF
    chmod 600 "${CONFIG_DIR}/config.env"
    log_info "Configuration file created at ${CONFIG_DIR}/config.env"
}

# Register instance with backend
register_instance() {
    log_info "Registering instance with backend..."
    
    # Create JSON payload in temp file to avoid shell escaping issues
    TEMP_JSON=$(mktemp)
    cat > "${TEMP_JSON}" <<EOF
{
    "instance_id": "${INSTANCE_ID}",
    "api_key": "${API_KEY}"
}
EOF
    
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_BASE_URL}/api/telemetry/provision/register" \
        -H "Content-Type: application/json" \
        --data @"${TEMP_JSON}" 2>&1)
    
    rm -f "${TEMP_JSON}"
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    
    if [[ "$HTTP_CODE" != "200" ]] && [[ "$HTTP_CODE" != "201" ]]; then
        log_warn "Failed to register instance: HTTP $HTTP_CODE"
        log_warn "Response: $BODY"
        log_warn "Registration is optional - agent will retry on startup"
        # Don't exit - allow installation to continue
        return 1
    fi
    
    log_info "Instance registered successfully"
    return 0
}

# Create systemd service
create_systemd_service() {
    log_info "Creating systemd service..."
    cat > /etc/systemd/system/omniference-agent.service <<EOF
[Unit]
Description=Omniference Provisioning Agent
After=network.target docker.service

[Service]
Type=simple
EnvironmentFile=${CONFIG_DIR}/config.env
ExecStart=${AGENT_BINARY}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    log_info "Systemd service created"
}

# Clean up stale state
cleanup_stale_state() {
    log_info "Cleaning up stale deployment state..."
    # Remove old deployment directories that might cause conflicts
    find /tmp -maxdepth 1 -type d -name "gpu-telemetry-*" -mtime +1 -exec rm -rf {} + 2>/dev/null || true
    log_info "Cleanup complete"
}

# Main installation flow
main() {
    detect_os
    check_nvidia_driver
    install_docker
    install_nvidia_toolkit
    install_agent_binary
    create_config
    register_instance
    cleanup_stale_state
    create_systemd_service
    
    log_info ""
    log_info "Installation complete!"
    log_info ""
    log_info "To start the agent:"
    log_info "  sudo systemctl start omniference-agent"
    log_info ""
    log_info "To enable auto-start on boot:"
    log_info "  sudo systemctl enable omniference-agent"
    log_info ""
    log_info "To check status:"
    log_info "  sudo systemctl status omniference-agent"
    log_info ""
    log_info "To view logs:"
    log_info "  sudo journalctl -u omniference-agent -f"
    log_info ""
}

main "$@"
