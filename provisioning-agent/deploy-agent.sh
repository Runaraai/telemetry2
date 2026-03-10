#!/bin/bash
set -e

# Deploy script for Omniference provisioning agent
# This builds the agent binary and copies it to the domain hosting directory

AGENT_VERSION="2.0.9"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="/var/www/omniference/downloads"
BINARY_NAME="provisioning-agent-linux-amd64"
BINARY_NAME_ALT="omniference-agent-linux-amd64"

echo "============================================"
echo "  Deploying Omniference Agent v${AGENT_VERSION}"
echo "============================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script requires root privileges for copying files."
    echo "Please run with: sudo $0"
    exit 1
fi

# Check if Go is installed
if ! command -v go &> /dev/null; then
    echo "ERROR: Go is not installed. Please install Go 1.21+ first."
    echo "  sudo apt install golang-go"
    exit 1
fi

# Build the binary
echo "📦 Building agent binary..."
cd "$SOURCE_DIR"

# Clean previous build
rm -f "$BINARY_NAME" "$BINARY_NAME.tmp"

# Build with optimizations
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o "$BINARY_NAME" .

if [ ! -f "$BINARY_NAME" ]; then
    echo "ERROR: Build failed - binary not found"
    exit 1
fi

echo "✅ Binary built successfully: $(du -h "$BINARY_NAME" | cut -f1)"
echo ""

# Create download directory if it doesn't exist
if [ ! -d "$DOWNLOAD_DIR" ]; then
    echo "📁 Creating download directory: $DOWNLOAD_DIR"
    mkdir -p "$DOWNLOAD_DIR"
fi

# Copy binary to download directory (with both names for compatibility)
echo "📤 Copying files to download directory..."
cp "$BINARY_NAME" "$DOWNLOAD_DIR/$BINARY_NAME"
cp "$BINARY_NAME" "$DOWNLOAD_DIR/$BINARY_NAME_ALT"  # For install-agent.sh compatibility
cp "install-agent.sh" "$DOWNLOAD_DIR/"
cp "install.sh" "$DOWNLOAD_DIR/"  # For /install endpoint

# Set proper permissions
chmod 755 "$DOWNLOAD_DIR/$BINARY_NAME"
chmod 755 "$DOWNLOAD_DIR/$BINARY_NAME_ALT"
chmod 644 "$DOWNLOAD_DIR/install-agent.sh"
chmod 644 "$DOWNLOAD_DIR/install.sh"

# Set ownership (adjust if needed)
chown www-data:www-data "$DOWNLOAD_DIR/$BINARY_NAME" 2>/dev/null || true
chown www-data:www-data "$DOWNLOAD_DIR/$BINARY_NAME_ALT" 2>/dev/null || true
chown www-data:www-data "$DOWNLOAD_DIR/install-agent.sh" 2>/dev/null || true
chown www-data:www-data "$DOWNLOAD_DIR/install.sh" 2>/dev/null || true

echo "✅ Files copied to $DOWNLOAD_DIR"
echo ""

# Verify files
echo "🔍 Verifying deployment..."
if [ -f "$DOWNLOAD_DIR/$BINARY_NAME" ] && [ -f "$DOWNLOAD_DIR/install-agent.sh" ]; then
    echo "✅ Binary: $DOWNLOAD_DIR/$BINARY_NAME ($(du -h "$DOWNLOAD_DIR/$BINARY_NAME" | cut -f1))"
    echo "✅ Install script: $DOWNLOAD_DIR/install-agent.sh"
    echo ""
    
    # Test if nginx can serve the file
    if command -v nginx &> /dev/null; then
        echo "🔄 Reloading nginx..."
        nginx -t && systemctl reload nginx 2>/dev/null || echo "⚠️  Warning: Could not reload nginx (may need manual reload)"
    fi
    
    echo ""
    echo "============================================"
    echo "  ✅ Deployment Complete!"
    echo "============================================"
    echo ""
    echo "Agent is now available at:"
    echo "  https://omniference.com/downloads/$BINARY_NAME"
    echo "  https://omniference.com/downloads/install-agent.sh"
    echo ""
    echo "Test installation:"
    echo "  curl -fsSL https://omniference.com/downloads/install-agent.sh | sudo bash"
    echo ""
else
    echo "ERROR: Deployment verification failed"
    exit 1
fi


