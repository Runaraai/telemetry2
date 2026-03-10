# Agent Distribution Guide

## Current Status

The provisioning agent code exists in this repository (`provisioning-agent/`), but it is **NOT yet published to GitHub**. The install script references GitHub URLs that don't exist yet.

## Distribution Options

### Option 1: GitHub Repository (Recommended)

**Steps to publish**:

1. **Create GitHub Repository**:
   ```bash
   # On GitHub, create a new repository:
   # Name: provisioning-agent
   # Owner: omniference (or your org)
   # Visibility: Public
   ```

2. **Push Agent Code**:
   ```bash
   cd provisioning-agent
   git init
   git add .
   git commit -m "Initial commit: Omniference provisioning agent"
   git remote add origin https://github.com/omniference/provisioning-agent.git
   git branch -M main
   git push -u origin main
   ```

3. **Build and Release Binary**:
   ```bash
   # Build for Linux amd64
   GOOS=linux GOARCH=amd64 go build -o provisioning-agent-linux-amd64 main.go
   
   # Create GitHub release
   # Tag: v1.0.0
   # Upload: provisioning-agent-linux-amd64
   ```

4. **Update Install Script** (if needed):
   - The install script already references the correct URLs
   - Just ensure the repository name matches: `omniference/provisioning-agent`

### Option 2: Host on Your Own Server

If you don't want to use GitHub, you can host the agent binary on your own server:

1. **Update Install Script**:
   ```bash
   # Edit install-agent.sh
   AGENT_BINARY_URL="${AGENT_BINARY_URL:-https://your-domain.com/downloads/provisioning-agent-linux-amd64}"
   ```

2. **Host Binary**:
   - Upload binary to your web server
   - Ensure HTTPS is enabled
   - Make it publicly accessible

### Option 3: Docker Hub / Container Registry

You could also distribute as a Docker image:

```dockerfile
FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY . .
RUN go build -o provisioning-agent main.go

FROM alpine:latest
COPY --from=builder /app/provisioning-agent /usr/local/bin/
ENTRYPOINT ["provisioning-agent"]
```

## Quick Setup Instructions

### For GitHub Distribution:

1. **Create the repository** (if it doesn't exist):
   - Go to https://github.com/new
   - Repository name: `provisioning-agent`
   - Description: "Omniference provisioning agent for GPU telemetry deployment"
   - Visibility: **Public** (required for install script)
   - Initialize with README: No (we already have one)

2. **Push the code**:
   ```bash
   cd /home/madhur/Omniference/provisioning-agent
   git init
   git add .
   git commit -m "Initial commit: Omniference provisioning agent v1.0.0"
   git remote add origin https://github.com/omniference/provisioning-agent.git
   git push -u origin main
   ```

3. **Build and create release**:
   ```bash
   # Install Go if not already installed
   # sudo apt install golang-go  # or download from golang.org
   
   # Build binary
   cd /home/madhur/Omniference/provisioning-agent
   GOOS=linux GOARCH=amd64 go build -o provisioning-agent-linux-amd64 main.go
   
   # Create release on GitHub:
   # 1. Go to https://github.com/omniference/provisioning-agent/releases/new
   # 2. Tag: v1.0.0
   # 3. Title: v1.0.0
   # 4. Upload: provisioning-agent-linux-amd64
   # 5. Publish release
   ```

4. **Verify install script works**:
   ```bash
   # Test the install script (on a test instance)
   curl -fsSL https://raw.githubusercontent.com/omniference/provisioning-agent/main/install-agent.sh | sudo bash
   ```

## Current URLs in Code

The install script (`install-agent.sh`) currently references:
- **Install Script URL**: `https://raw.githubusercontent.com/omniference/provisioning-agent/main/install-agent.sh`
- **Binary URL**: `https://github.com/omniference/provisioning-agent/releases/download/v1.0.0/provisioning-agent-linux-amd64`

**These will work once you**:
1. Create the GitHub repository
2. Push the code
3. Create a v1.0.0 release with the binary

## Alternative: Use Your Domain

If you prefer to host on your own domain (e.g., `omniference.com`):

1. **Update install script**:
   ```bash
   AGENT_BINARY_URL="${AGENT_BINARY_URL:-https://omniference.com/downloads/provisioning-agent-linux-amd64}"
   ```

2. **Host files**:
   - Upload `install-agent.sh` to `https://omniference.com/downloads/install-agent.sh`
   - Upload binary to `https://omniference.com/downloads/provisioning-agent-linux-amd64`

3. **Update documentation**:
   - Update `USER_FLOW.md` with new URLs
   - Update `ARCHITECTURE.md` if needed

## Testing the Agent

Before publishing, test locally:

```bash
# Build agent
cd provisioning-agent
go build -o provisioning-agent main.go

# Test with mock manifest (you'll need to set up a test backend)
export MANIFEST_URL="http://localhost:8000/api/telemetry/provision/manifests/{id}?token={token}"
export TOKEN="test-token"
./provisioning-agent "$MANIFEST_URL" "$TOKEN"
```

## Next Steps

1. ✅ Agent code is ready in `provisioning-agent/`
2. ⏳ Create GitHub repository (or use your own hosting)
3. ⏳ Build and publish binary
4. ⏳ Test install script
5. ⏳ Update documentation with actual URLs




