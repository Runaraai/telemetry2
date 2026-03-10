# Provisioning Agent Deployment Guide

## Important: Agent is NOT in Docker

The provisioning agent is **NOT part of your Docker containers**. It's a standalone Go binary that:
- Runs directly on GPU instances (not in Docker)
- Gets downloaded from `https://omniference.com/downloads/`
- Is served via **nginx** (not the Docker backend)

## Deployment Process

### Step 1: Build the New Binary

```bash
cd /home/madhur/Omniference/provisioning-agent

# Build for Linux amd64
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o omniference-agent-linux-amd64 .

# Verify it was built
ls -lh omniference-agent-linux-amd64
```

### Step 2: Upload to Server

You have two options:

#### Option A: Use the Upload Script (Recommended)

```bash
# Update the script first (it needs the new binary name)
cd /home/madhur/Omniference

# Build the binary first
cd provisioning-agent
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o omniference-agent-linux-amd64 .

# Go back to root
cd ..

# Upload using the script (update it first - see below)
./upload-provisioning-agent.sh <YOUR_SERVER_IP>
```

#### Option B: Manual Upload

```bash
# On your local machine
cd /home/madhur/Omniference/provisioning-agent
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o omniference-agent-linux-amd64 .

# Upload to server
scp -i your-key.pem omniference-agent-linux-amd64 ubuntu@YOUR_SERVER_IP:/tmp/

# SSH into server
ssh -i your-key.pem ubuntu@YOUR_SERVER_IP

# Move to nginx directory
sudo mkdir -p /var/www/omniference/downloads
sudo cp /tmp/omniference-agent-linux-amd64 /var/www/omniference/downloads/
sudo chmod 755 /var/www/omniference/downloads/omniference-agent-linux-amd64

# Also update install script
sudo cp /tmp/install-agent.sh /var/www/omniference/downloads/  # if you updated it
sudo chmod 644 /var/www/omniference/downloads/install-agent.sh
```

### Step 3: Verify Deployment

```bash
# Test binary download
curl -I https://omniference.com/downloads/omniference-agent-linux-amd64

# Should return 200 OK

# Test install script
curl -I https://omniference.com/downloads/install-agent.sh

# Test full installation (on a test instance)
curl -fsSL https://omniference.com/downloads/install-agent.sh | sudo bash
```

## What Happens When You Rebuild Docker?

**Nothing changes for the agent!** 

- Docker rebuild only affects:
  - Backend API (`omniference-backend` container)
  - Frontend (`frontend` container)
  - Database (`timescaledb` container)

- The agent binary is served by **nginx on the host**, not Docker
- You must **manually upload** the new binary to `/var/www/omniference/downloads/`

## File Locations on Server

| File | Location | Purpose |
|------|----------|---------|
| Agent binary | `/var/www/omniference/downloads/omniference-agent-linux-amd64` | Served by nginx |
| Install script | `/var/www/omniference/downloads/install-agent.sh` | Served by nginx |
| Nginx config | `/etc/nginx/sites-available/omniference` | Routes `/downloads/` to files |

## Quick Update Workflow

```bash
# 1. Build locally
cd /home/madhur/Omniference/provisioning-agent
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o omniference-agent-linux-amd64 .

# 2. Upload (using updated script)
cd ..
./upload-provisioning-agent.sh YOUR_SERVER_IP

# 3. Verify
curl -I https://omniference.com/downloads/omniference-agent-linux-amd64
```

## Troubleshooting

### Binary not accessible (404)

```bash
# Check if file exists
ssh ubuntu@YOUR_SERVER_IP
sudo ls -lh /var/www/omniference/downloads/

# Check nginx config
sudo nginx -t
sudo systemctl reload nginx

# Check permissions
sudo chmod 755 /var/www/omniference/downloads/omniference-agent-linux-amd64
```

### Old version still being served

```bash
# Clear nginx cache (if any)
sudo systemctl reload nginx

# Verify file timestamp
ls -lh /var/www/omniference/downloads/omniference-agent-linux-amd64

# Force re-download on client
curl -fsSL https://omniference.com/downloads/install-agent.sh | sudo bash
```

## Version Management

The agent version is defined in:
- `main.go`: `AgentVersion = "2.0.0"`
- `install-agent.sh`: `AGENT_VERSION="2.0.0"`

When updating:
1. Update version in both files
2. Build new binary
3. Upload to server
4. Update install script on server (if changed)
