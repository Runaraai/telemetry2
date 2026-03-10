#!/bin/bash
set -e

# Install script for Omniference GPU Telemetry Agent
# Supports both GitHub and domain hosting with automatic fallback
# Usage: 
#   curl -fsSL https://omniference.com/downloads/install-agent.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/omniference/provisioning-agent/main/install-agent.sh | bash

AGENT_VERSION="2.0.9"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
AGENT_BINARY="${INSTALL_DIR}/omniference-agent"
CONFIG_DIR="/etc/omniference"
DATA_DIR="/var/lib/omniference"
LOCK_DIR="/var/lock"

# Try domain first, fallback to GitHub
AGENT_BINARY_URL="${AGENT_BINARY_URL:-}"
if [ -z "$AGENT_BINARY_URL" ]; then
    AGENT_BINARY_URL="https://omniference.com/downloads/omniference-agent-linux-amd64"
    GITHUB_URL="https://github.com/omniference/provisioning-agent/releases/download/v${AGENT_VERSION}/omniference-agent-linux-amd64"
fi

echo "Installing Omniference GPU Telemetry Agent v${AGENT_VERSION}..."
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script requires root privileges. Please run with sudo."
    exit 1
fi

# Create required directories with secure permissions
echo "Creating directories..."
mkdir -p "${CONFIG_DIR}"
chmod 750 "${CONFIG_DIR}"

mkdir -p "${DATA_DIR}/deployments"
chmod 750 "${DATA_DIR}"

# Download agent binary with fallback
echo "Downloading agent binary..."
if ! curl -fsSL -o "${AGENT_BINARY}" "${AGENT_BINARY_URL}" 2>/dev/null; then
    if [ -z "$AGENT_BINARY_URL" ] || [ "$AGENT_BINARY_URL" = "https://omniference.com/downloads/omniference-agent-linux-amd64" ]; then
        echo "Domain download failed, trying GitHub fallback..."
        if ! curl -fsSL -o "${AGENT_BINARY}" "${GITHUB_URL}" 2>/dev/null; then
            echo "ERROR: Failed to download agent binary from both sources."
            echo "Tried: ${AGENT_BINARY_URL}"
            echo "Tried: ${GITHUB_URL}"
            exit 1
        fi
    else
        echo "ERROR: Failed to download agent binary from ${AGENT_BINARY_URL}"
        exit 1
    fi
fi

# Make executable
chmod +x "${AGENT_BINARY}"
echo "✓ Agent binary installed to ${AGENT_BINARY}"

# Create environment file template if it doesn't exist
if [ ! -f "${CONFIG_DIR}/agent.env" ]; then
    cat > "${CONFIG_DIR}/agent.env" <<'EOF'
# Omniference Agent Configuration
# Set your API key and instance ID here

# Required: Your API key from the Omniference dashboard
OMNIFERENCE_API_KEY=

# Required: Unique identifier for this instance
OMNIFERENCE_INSTANCE_ID=

# Optional: Override the default API URL (defaults to https://omniference.com)
# OMNIFERENCE_API_URL=https://omniference.com
EOF
    chmod 600 "${CONFIG_DIR}/agent.env"
    echo "✓ Configuration template created at ${CONFIG_DIR}/agent.env"
else
    echo "✓ Existing configuration preserved at ${CONFIG_DIR}/agent.env"
fi

# Install systemd service
cat > /etc/systemd/system/omniference-agent.service <<'EOF'
[Unit]
Description=Omniference GPU Telemetry Agent
Documentation=https://omniference.com/docs/agent
After=network-online.target docker.service nvidia-persistenced.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=root
Group=root

# Environment configuration - secrets should be set in /etc/omniference/agent.env
EnvironmentFile=-/etc/omniference/agent.env

# Hardcoded environment
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="HOME=/root"

# Main process
ExecStart=/usr/local/bin/omniference-agent

# Restart configuration
Restart=on-failure
RestartSec=10s
RestartPreventExitStatus=0

# Resource limits
LimitNOFILE=65536
LimitNPROC=4096

# Security hardening (while still allowing necessary operations)
NoNewPrivileges=no
ProtectSystem=false
ProtectHome=read-only
PrivateTmp=true
ReadWritePaths=/var/lib/omniference /var/lock /tmp

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=omniference-agent

# Watchdog
WatchdogSec=120s

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload
echo "✓ Systemd service installed"

echo ""
echo "============================================"
echo "  Omniference Agent v${AGENT_VERSION} Installed!"
echo "============================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Configure your credentials:"
echo "   sudo nano ${CONFIG_DIR}/agent.env"
echo ""
echo "   Set OMNIFERENCE_API_KEY and OMNIFERENCE_INSTANCE_ID"
echo ""
echo "2. Start the agent:"
echo "   sudo systemctl start omniference-agent"
echo ""
echo "3. Enable auto-start on boot:"
echo "   sudo systemctl enable omniference-agent"
echo ""
echo "4. Check status:"
echo "   sudo systemctl status omniference-agent"
echo "   sudo journalctl -u omniference-agent -f"
echo ""
echo "Alternative: Set credentials via environment variables:"
echo "   export OMNIFERENCE_API_KEY='your-api-key'"
echo "   export OMNIFERENCE_INSTANCE_ID='your-instance-id'"
echo "   sudo -E omniference-agent"
echo ""
