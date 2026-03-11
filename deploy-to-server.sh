#!/bin/bash
# Deploy backend + frontend changes to the Omniference server.
# Usage: ./deploy-to-server.sh <SERVER_IP>
#   e.g. ./deploy-to-server.sh 3.19.87.64
#
# Environment variables:
#   PEM_FILE    - Path to SSH key (default: madhur.pem)
#   REMOTE_USER - SSH user (default: ubuntu)
#   REMOTE_APP  - App path on server (default: /opt/omniference/app)

set -e

PEM_FILE="${PEM_FILE:-madhur.pem}"
REMOTE_USER="${REMOTE_USER:-ubuntu}"
REMOTE_APP="${REMOTE_APP:-/opt/omniference/app}"
REMOTE_IP="${1:-}"

if [ -z "$REMOTE_IP" ]; then
    echo "Usage: $0 <SERVER_IP>"
    echo ""
    echo "Deploys backend and frontend to the Omniference server."
    echo ""
    echo "Example:"
    echo "  $0 3.19.87.64"
    echo ""
    echo "Environment variables:"
    echo "  PEM_FILE     - SSH key path (default: madhur.pem)"
    echo "  REMOTE_USER  - SSH user (default: ubuntu)"
    echo "  REMOTE_APP   - App path on server (default: /opt/omniference/app)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE="${REMOTE_USER}@${REMOTE_IP}"

# Build rsync/scp command with optional PEM
SSH_OPTS=()
[ -n "$PEM_FILE" ] && [ -f "$PEM_FILE" ] && SSH_OPTS=(-e "ssh -i $PEM_FILE")

echo "============================================"
echo "  Omniference Deploy"
echo "============================================"
echo "  Server: $REMOTE"
echo "  App path: $REMOTE_APP"
echo "  PEM: ${PEM_FILE:-none}"
echo ""

# Sync backend (exclude venv, __pycache__, etc.)
echo "📤 Syncing backend..."
rsync -avz --delete \
  "${SSH_OPTS[@]}" \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude '.mypy_cache' \
  "$SCRIPT_DIR/backend/" \
  "$REMOTE:$REMOTE_APP/backend/"

# Sync frontend source (exclude node_modules, build - we rebuild on server)
echo "📤 Syncing frontend..."
rsync -avz --delete \
  "${SSH_OPTS[@]}" \
  --exclude 'node_modules' \
  --exclude 'build' \
  "$SCRIPT_DIR/frontend/" \
  "$REMOTE:$REMOTE_APP/frontend/"

echo ""
echo "🔄 Rebuilding frontend and restarting backend on server..."

# Build ssh command - handle optional -i for PEM
SSH_CMD="ssh"
[ -n "$PEM_FILE" ] && [ -f "$PEM_FILE" ] && SSH_CMD="ssh -i $PEM_FILE"

$SSH_CMD "$REMOTE" "REMOTE_APP=$REMOTE_APP bash -s" << REMOTE_SCRIPT
set -e
REMOTE_APP="\${REMOTE_APP:-/opt/omniference/app}"

cd "\$REMOTE_APP/frontend"
echo "  Installing frontend dependencies..."
npm install --legacy-peer-deps
echo "  Building frontend..."
npm run build

echo "  Restarting backend (systemd)..."
sudo systemctl restart omniference-backend 2>/dev/null || \
  { echo "  (systemd service not found - if using Docker, restart containers manually)" ; true }

echo "  Reloading Nginx..."
sudo systemctl reload nginx 2>/dev/null || true

echo ""
echo "✅ Deploy complete!"
REMOTE_SCRIPT

echo ""
echo "============================================"
echo "  ✅ Deploy Complete!"
echo "============================================"
echo ""
echo "Verify at: http://${REMOTE_IP}/profiling"
echo ""
