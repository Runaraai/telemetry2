#!/bin/bash
# Deploy Omniference to EC2 using AWS CLI (bypasses direct SSH if blocked).
# Use SSM Session Manager for shell access, or fix security group for SSH.
#
# Prerequisites: AWS CLI configured (aws configure), correct region
# Usage:
#   ./scripts/deploy-via-aws.sh diagnose      # Check instance & security groups
#   ./scripts/deploy-via-aws.sh fix-sg        # Add your IP to SSH rule
#   ./scripts/deploy-via-aws.sh deploy        # Deploy via SSM (if available) or print manual steps

set -e

INSTANCE_ID="${INSTANCE_ID:-i-0d3bb2002c040644e}"
REGION="${AWS_REGION:-us-east-2}"
APP_PATH="/opt/omniference/app"

diagnose() {
  echo "=== Instance state (region: $REGION) ==="
  aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
    --query 'Reservations[0].Instances[0].{State:State.Name,PublicIP:PublicIpAddress,PrivateIP:PrivateIpAddress,SecurityGroups:SecurityGroups}' \
    --output table 2>/dev/null || { echo "Instance not found or not accessible"; return 1; }

  echo ""
  echo "=== Security groups (SSH port 22) ==="
  SG_IDS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
    --query 'Reservations[0].Instances[0].SecurityGroups[].GroupId' --output text)
  for sg in $SG_IDS; do
    echo "--- SG: $sg ---"
    aws ec2 describe-security-groups --group-ids "$sg" --region "$REGION" \
      --query 'SecurityGroups[0].IpPermissions[?FromPort==`22` || FromPort==null]' --output table
  done

  echo ""
  echo "=== SSM connectivity (Session Manager) ==="
  aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE_ID" --region "$REGION" \
    --query 'InstanceInformationList[0].{PingStatus:PingStatus,AgentVersion:AgentVersion}' \
    --output table 2>/dev/null || echo "SSM agent not reporting (instance may need SSM IAM role)"
}

fix_sg() {
  echo "Adding your current IP to SSH (port 22) rule..."
  MY_IP=$(curl -s https://checkip.amazonaws.com 2>/dev/null || curl -s ifconfig.me)
  echo "Your IP: $MY_IP"

  SG_IDS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
    --query 'Reservations[0].Instances[0].SecurityGroups[].GroupId' --output text)
  for sg in $SG_IDS; do
    echo "Adding $MY_IP/32 to SG $sg (port 22)..."
    aws ec2 authorize-security-group-ingress --group-id "$sg" --region "$REGION" \
      --protocol tcp --port 22 --cidr "${MY_IP}/32" 2>/dev/null || echo "  (Rule may already exist)"
  done
  echo "Done. Try: ssh -i omniference-key.pem ec2-user@3.19.87.64"
}

deploy_ssm() {
  echo "Attempting deploy via SSM Run Command..."
  S3_BUCKET="${DEPLOY_S3_BUCKET:-}"
  if [ -z "$S3_BUCKET" ]; then
    echo "Deploy via SSM requires S3 bucket to upload files. Set DEPLOY_S3_BUCKET=your-bucket"
    echo ""
    echo "Alternative: Run these commands manually after fixing SSH (./deploy-via-aws.sh fix-sg):"
    echo "  scp -i omniference-key.pem -r backend ec2-user@3.19.87.64:/tmp/omniference-backend"
    echo "  scp -i omniference-key.pem -r frontend ec2-user@3.19.87.64:/tmp/omniference-frontend"
    echo "  ssh -i omniference-key.pem ec2-user@3.19.87.64 'sudo cp -r /tmp/omniference-backend/* $APP_PATH/backend/ && cd $APP_PATH/frontend && sudo cp -r /tmp/omniference-frontend/* . && npm run build && sudo systemctl restart omniference-backend'"
    return 1
  fi
  # SSM Run Command could sync from S3 - more complex, skip for now
  echo "Use fix-sg then manual scp/ssh, or run deploy-to-server.sh after SSH works"
}

case "${1:-diagnose}" in
  diagnose) diagnose ;;
  fix-sg)   fix_sg ;;
  deploy)   deploy_ssm ;;
  *)        echo "Usage: $0 {diagnose|fix-sg|deploy}"; exit 1 ;;
esac
