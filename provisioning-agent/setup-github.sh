#!/bin/bash
# Script to set up GitHub repository and publish the agent
# Run this after creating the GitHub repository manually

set -e

REPO_NAME="provisioning-agent"
GITHUB_ORG="omniference"
VERSION="1.0.0"

echo "Setting up GitHub repository for Omniference provisioning agent..."
echo ""

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
    git branch -M main
fi

# Check if remote exists
if ! git remote get-url origin >/dev/null 2>&1; then
    echo "Adding GitHub remote..."
    git remote add origin "https://github.com/${GITHUB_ORG}/${REPO_NAME}.git"
else
    echo "Remote already exists: $(git remote get-url origin)"
fi

# Add all files
echo "Adding files..."
git add .

# Check if there are changes
if git diff --staged --quiet; then
    echo "No changes to commit."
else
    echo "Committing changes..."
    git commit -m "Initial commit: Omniference provisioning agent v${VERSION}"
fi

# Check if binary exists
if [ ! -f "provisioning-agent-linux-amd64" ]; then
    echo "Building binary..."
    GOOS=linux GOARCH=amd64 go build -o provisioning-agent-linux-amd64 main.go
fi

echo ""
echo "✅ Repository setup complete!"
echo ""
echo "Next steps:"
echo "1. Push to GitHub:"
echo "   git push -u origin main"
echo ""
echo "2. Create GitHub release:"
echo "   - Go to: https://github.com/${GITHUB_ORG}/${REPO_NAME}/releases/new"
echo "   - Tag: v${VERSION}"
echo "   - Title: v${VERSION}"
echo "   - Upload: provisioning-agent-linux-amd64"
echo "   - Publish release"
echo ""
echo "3. Test installation:"
echo "   curl -fsSL https://raw.githubusercontent.com/${GITHUB_ORG}/${REPO_NAME}/main/install-agent.sh | sudo bash"




