#!/bin/bash
# Deploy Omniference via Git: push to GitHub, then pull on EC2.
# Run locally - step 1 pushes, step 2 SSHs to server and pulls.
#
# Usage:
#   ./scripts/deploy-via-git.sh              # Push + pull + rebuild (full deploy)
#   ./scripts/deploy-via-git.sh push-only    # Just push (you'll pull manually)
#   ./scripts/deploy-via-git.sh pull-only    # Just SSH + pull + rebuild (after you pushed)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PEM="${PEM_FILE:-$PROJECT_ROOT/omniference-key.pem}"
REMOTE="ec2-user@3.19.87.64"
APP_PATH="/opt/omniference/app"
BRANCH="${GIT_BRANCH:-main}"

push_step() {
  echo "=== Pushing to GitHub ==="
  cd "$PROJECT_ROOT"
  git status
  git add -A
  git diff --cached --quiet && { echo "Nothing to commit."; return 0; }
  git commit -m "Deploy: $(date +%Y-%m-%d) updates"
  git push origin "$BRANCH"
  echo ""
}

pull_step() {
  echo "=== Pulling on EC2 and rebuilding ==="
  ssh -i "$PEM" -o StrictHostKeyChecking=no "$REMOTE" "bash -s" << REMOTE
set -e
cd $APP_PATH
git pull origin $BRANCH
cd frontend
npm install --legacy-peer-deps
npm run build
sudo systemctl restart omniference-backend 2>/dev/null || true
sudo systemctl reload nginx 2>/dev/null || true
echo ""
echo "Deploy complete! Check http://3.19.87.64/profiling"
REMOTE
}

case "${1:-}" in
  push-only) push_step ;;
  pull-only) pull_step ;;
  "")        push_step; pull_step ;;
  *)         echo "Usage: $0 [push-only|pull-only]"; exit 1 ;;
esac
