#!/bin/bash
# Fix SSH access (add your IP to security group) and deploy Omniference to EC2.
# Run this from your local machine (Git Bash / WSL / Linux).
#
# Usage: ./scripts/fix-ssh-and-deploy.sh [deploy]
#   fix-ssh-and-deploy.sh       # Just fix SSH (add your IP to security group)
#   fix-ssh-and-deploy.sh deploy # Fix SSH + deploy backend & frontend
#
# EC2 config: set in .env or env vars (EC2_SSH_HOST, EC2_SSH_USER, EC2_PEM_FILE, etc.)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$PROJECT_ROOT/.env" ] && set -a && source "$PROJECT_ROOT/.env" && set +a

INSTANCE_ID="${EC2_INSTANCE_ID:-${INSTANCE_ID:-i-0d3bb2002c040644e}}"
SG_ID="${SG_ID:-sg-0d61f51991cd715df}"
REGION="${EC2_REGION:-${AWS_REGION:-us-east-2}}"
APP_PATH="${EC2_APP_PATH:-/opt/omniference/app}"
EC2_HOST="${EC2_SSH_HOST:-3.19.87.64}"
EC2_USER="${EC2_SSH_USER:-ec2-user}"
PEM="${EC2_PEM_FILE:-$PROJECT_ROOT/omniference-key.pem}"
[ "${PEM#/}" = "$PEM" ] && PEM="$PROJECT_ROOT/$PEM"

echo "=== Adding your IP to SSH rule (security group $SG_ID) ==="
MY_IP=$(curl -s https://checkip.amazonaws.com 2>/dev/null || curl -s ifconfig.me)
echo "Your IP: $MY_IP"

aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGION" \
  --protocol tcp --port 22 --cidr "${MY_IP}/32" 2>/dev/null || echo "(Rule may already exist - continuing)"

echo ""
echo "Waiting 5s for rule to propagate..."
sleep 5

echo ""
echo "=== Testing SSH ($EC2_USER@$EC2_HOST) ==="
ssh -i "$PEM" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  "$EC2_USER@$EC2_HOST" "echo 'SSH OK'" || { echo "SSH still failed. Check PEM path and network."; exit 1; }

if [ "${1:-}" = "deploy" ]; then
  echo ""
  echo "=== Deploying backend and frontend ==="
  scp -i "$PEM" -o StrictHostKeyChecking=no -r \
    "$PROJECT_ROOT/backend" "$EC2_USER@$EC2_HOST:/tmp/omniference-backend"
  scp -i "$PEM" -o StrictHostKeyChecking=no -r \
    "$PROJECT_ROOT/frontend" "$EC2_USER@$EC2_HOST:/tmp/omniference-frontend"

  ssh -i "$PEM" -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" "APP_PATH=$APP_PATH bash -s" << 'REMOTE'
set -e
sudo cp -r /tmp/omniference-backend/* /opt/omniference/app/backend/
sudo cp -r /tmp/omniference-frontend/* /opt/omniference/app/frontend/
cd /opt/omniference/app/frontend
npm install --legacy-peer-deps
npm run build
sudo systemctl restart omniference-backend 2>/dev/null || true
sudo systemctl reload nginx 2>/dev/null || true
echo "Deploy complete!"
REMOTE

  echo ""
  echo "=== Verify at http://$EC2_HOST/profiling ==="
fi
