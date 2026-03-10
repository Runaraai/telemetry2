#!/bin/bash
# Script to upload the provisioning agent binary and install script to the server

set -e

# Configuration
BINARY_NAME="omniference-agent-linux-amd64"
BINARY_PATH="./provisioning-agent/${BINARY_NAME}"
INSTALL_SCRIPT="./provisioning-agent/install-agent.sh"
PEM_FILE="${PEM_FILE:-madhur.pem}"
REMOTE_USER="${REMOTE_USER:-ubuntu}"
REMOTE_IP="${1:-}"

if [ -z "$REMOTE_IP" ]; then
    echo "Usage: $0 <SERVER_IP>"
    echo ""
    echo "Example:"
    echo "  $0 34.123.45.67"
    echo ""
    echo "Or set environment variables:"
    echo "  export REMOTE_USER=ubuntu"
    echo "  export PEM_FILE=your-key.pem"
    echo "  $0 <SERVER_IP>"
    exit 1
fi

# Check if binary exists, if not try to build it
if [ ! -f "$BINARY_PATH" ]; then
    echo "⚠️  Binary not found at $BINARY_PATH"
    echo "Building binary..."
    cd provisioning-agent
    GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o "${BINARY_NAME}" .
    cd ..
    if [ ! -f "$BINARY_PATH" ]; then
        echo "❌ Error: Failed to build binary"
        exit 1
    fi
    echo "✅ Binary built successfully"
fi

if [ ! -f "$INSTALL_SCRIPT" ]; then
    echo "❌ Error: Install script not found at $INSTALL_SCRIPT"
    exit 1
fi

if [ ! -f "$PEM_FILE" ]; then
    echo "❌ Error: PEM file not found at $PEM_FILE"
    echo "Set PEM_FILE environment variable:"
    echo "  export PEM_FILE=path/to/your-key.pem"
    exit 1
fi

echo "============================================"
echo "  Uploading Omniference Agent v2.0.0"
echo "============================================"
echo "  Server: $REMOTE_USER@$REMOTE_IP"
echo "  Binary: $BINARY_PATH"
echo "  Install Script: $INSTALL_SCRIPT"
echo "  PEM File: $PEM_FILE"
echo ""

# Upload binary to temp location
echo "📤 Uploading binary..."
scp -i "$PEM_FILE" "$BINARY_PATH" "$REMOTE_USER@$REMOTE_IP:/tmp/${BINARY_NAME}"

# Upload install script to temp location
echo "📤 Uploading install script..."
scp -i "$PEM_FILE" "$INSTALL_SCRIPT" "$REMOTE_USER@$REMOTE_IP:/tmp/install-agent.sh"

echo ""
echo "✅ Files uploaded to /tmp/"
echo ""
echo "Moving to final location and setting permissions..."

# Move to final location and set permissions
ssh -i "$PEM_FILE" "$REMOTE_USER@$REMOTE_IP" << EOF
set -e

# Create downloads directory
sudo mkdir -p /var/www/omniference/downloads

# Copy binary
sudo cp /tmp/${BINARY_NAME} /var/www/omniference/downloads/
sudo chmod 755 /var/www/omniference/downloads/${BINARY_NAME}

# Copy install script
sudo cp /tmp/install-agent.sh /var/www/omniference/downloads/
sudo chmod 644 /var/www/omniference/downloads/install-agent.sh

# Clean up temp files
rm -f /tmp/${BINARY_NAME} /tmp/install-agent.sh

# Show file info
echo ""
echo "✅ Files deployed:"
ls -lh /var/www/omniference/downloads/${BINARY_NAME}
ls -lh /var/www/omniference/downloads/install-agent.sh

echo ""
echo "✅ Binary is now available at:"
echo "   https://omniference.com/downloads/${BINARY_NAME}"
echo ""
echo "✅ Install script is now available at:"
echo "   https://omniference.com/downloads/install-agent.sh"
EOF

echo ""
echo "============================================"
echo "  ✅ Upload Complete!"
echo "============================================"
echo ""
echo "Verify deployment:"
echo "  curl -I https://omniference.com/downloads/${BINARY_NAME}"
echo "  curl -I https://omniference.com/downloads/install-agent.sh"
echo ""
echo "Test installation:"
echo "  curl -fsSL https://omniference.com/downloads/install-agent.sh | sudo bash"
