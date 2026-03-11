#!/bin/bash
# Fix SSH access (add your IP to security group) and deploy Omniference to EC2.
# Run this from your local machine (Git Bash / WSL / Linux).
#
# Usage: ./scripts/fix-ssh-and-deploy.sh [deploy]
#   fix-ssh-and-deploy.sh       # Just fix SSH (add your IP to security group)
#   fix-ssh-and-deploy.sh deploy # Fix SSH + deploy backend & frontend

set -e

INSTANCE_ID="${INSTANCE_ID:-i-0d3bb2002c040644e}"
SG_ID="${SG_ID:-sg-0d61f51991cd715df}"
REGION="${AWS_REGION:-us-east-2}"
APP_PATH="/opt/omniference/app"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Adding your IP to SSH rule (security group $SG_ID) ==="
MY_IP=$(curl -s https://checkip.amazonaws.com 2>/dev/null || curl -s ifconfig.me)
echo "Your IP: $MY_IP"

aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGION" \
  --protocol tcp --port 22 --cidr "${MY_IP}/32" 2>/dev/null || echo "(Rule may already exist - continuing)"

echo ""
echo "Waiting 5s for rule to propagate..."
sleep 5

echo ""
echo "=== Testing SSH ==="
ssh -i "$PROJECT_ROOT/omniference-key.pem" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  ec2-user@3.19.87.64 "echo 'SSH OK'" || { echo "SSH still failed. Check PEM path and network."; exit 1; }

if [ "${1:-}" = "deploy" ]; then
  echo ""
  echo "=== Deploying backend and frontend ==="
  scp -i "$PROJECT_ROOT/omniference-key.pem" -o StrictHostKeyChecking=no -r \
    "$PROJECT_ROOT/backend" ec2-user@3.19.87.64:/tmp/omniference-backend
  scp -i "$PROJECT_ROOT/omniference-key.pem" -o StrictHostKeyChecking=no -r \
    "$PROJECT_ROOT/frontend" ec2-user@3.19.87.64:/tmp/omniference-frontend

  ssh -i "$PROJECT_ROOT/omniference-key.pem" -o StrictHostKeyChecking=no ec2-user@3.19.87.64 "bash -s" << 'REMOTE'
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
  echo "=== Verify at http://3.19.87.64/profiling ==="
fi
