# Provisioning Agent Distribution Setup Guide

This guide covers setting up **both** GitHub and domain hosting for the Omniference provisioning agent.

## ✅ Current Status

- ✅ Agent code is ready in `provisioning-agent/`
- ✅ Binary built: `provisioning-agent-linux-amd64` (8.5MB)
- ✅ Install script updated with fallback support
- ✅ Domain hosting files copied to `/var/www/omniference/downloads/`
- ✅ Nginx configured for `/downloads/` endpoint

## Option 1: GitHub Distribution (Recommended)

### Step 1: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `provisioning-agent`
3. Owner: `omniference` (or your organization)
4. Description: "Omniference provisioning agent for GPU telemetry deployment"
5. Visibility: **Public** (required for install script)
6. **Do NOT** initialize with README (we already have one)
7. Click "Create repository"

### Step 2: Push Code to GitHub

```bash
cd /home/madhur/Omniference/provisioning-agent

# Initialize git if not already done
git init
git branch -M main

# Add remote (replace with your actual GitHub URL)
git remote add origin https://github.com/omniference/provisioning-agent.git

# Add and commit files
git add .
git commit -m "Initial commit: Omniference provisioning agent v1.0.0"

# Push to GitHub
git push -u origin main
```

**Or use the setup script:**
```bash
cd /home/madhur/Omniference/provisioning-agent
./setup-github.sh
git push -u origin main  # Still need to push manually
```

### Step 3: Build Binary (if not already built)

```bash
cd /home/madhur/Omniference/provisioning-agent
GOOS=linux GOARCH=amd64 go build -o provisioning-agent-linux-amd64 main.go
```

### Step 4: Create GitHub Release

1. Go to: https://github.com/omniference/provisioning-agent/releases/new
2. **Tag**: `v1.0.0` (must match version in install script)
3. **Title**: `v1.0.0`
4. **Description**: "Initial release of Omniference provisioning agent"
5. **Attach binary**: Upload `provisioning-agent-linux-amd64`
6. Check "Set as the latest release"
7. Click "Publish release"

### Step 5: Verify GitHub Distribution

Test the install script:
```bash
curl -fsSL https://raw.githubusercontent.com/omniference/provisioning-agent/main/install-agent.sh | sudo bash
```

## Option 2: Domain Hosting (Already Set Up!)

### Current Setup

✅ Files are already hosted at:
- **Binary**: `https://omniference.com/downloads/provisioning-agent-linux-amd64`
- **Install Script**: `https://omniference.com/downloads/install-agent.sh`

### Verify Domain Hosting

```bash
# Test binary download
curl -I https://omniference.com/downloads/provisioning-agent-linux-amd64

# Test install script
curl -I https://omniference.com/downloads/install-agent.sh

# Test installation
curl -fsSL https://omniference.com/downloads/install-agent.sh | sudo bash
```

### Update Files (when needed)

When you update the agent:

```bash
cd /home/madhur/Omniference/provisioning-agent

# Rebuild binary
GOOS=linux GOARCH=amd64 go build -o provisioning-agent-linux-amd64 main.go

# Copy to domain hosting
sudo cp provisioning-agent-linux-amd64 /var/www/omniference/downloads/
sudo cp install-agent.sh /var/www/omniference/downloads/
sudo chmod 755 /var/www/omniference/downloads/provisioning-agent-linux-amd64
sudo chmod 644 /var/www/omniference/downloads/install-agent.sh
```

## How the Install Script Works

The install script (`install-agent.sh`) supports **automatic fallback**:

1. **First tries domain hosting**: `https://omniference.com/downloads/provisioning-agent-linux-amd64`
2. **Falls back to GitHub** if domain fails: `https://github.com/omniference/provisioning-agent/releases/download/v1.0.0/provisioning-agent-linux-amd64`

This ensures maximum reliability - if one source is down, the other works.

### Installation Methods

Users can install via either method:

**GitHub:**
```bash
curl -fsSL https://raw.githubusercontent.com/omniference/provisioning-agent/main/install-agent.sh | sudo bash
```

**Domain:**
```bash
curl -fsSL https://omniference.com/downloads/install-agent.sh | sudo bash
```

Both methods will automatically use the best available source for the binary.

## Testing

### Test GitHub Distribution

```bash
# On a test GPU instance
curl -fsSL https://raw.githubusercontent.com/omniference/provisioning-agent/main/install-agent.sh | sudo bash
```

### Test Domain Distribution

```bash
# On a test GPU instance
curl -fsSL https://omniference.com/downloads/install-agent.sh | sudo bash
```

### Test Fallback

To test the fallback mechanism, temporarily disable domain hosting and verify it falls back to GitHub.

## File Locations

- **Source code**: `/home/madhur/Omniference/provisioning-agent/`
- **Binary**: `/home/madhur/Omniference/provisioning-agent/provisioning-agent-linux-amd64`
- **Domain hosting**: `/var/www/omniference/downloads/`
- **Nginx config**: `/etc/nginx/sites-available/omniference`

## Next Steps

1. ✅ Domain hosting is **already set up and working**
2. ⏳ Create GitHub repository (follow Step 1-4 above)
3. ⏳ Push code to GitHub
4. ⏳ Create GitHub release with binary
5. ✅ Test both distribution methods

## Troubleshooting

### GitHub: 404 Not Found
- Ensure repository is **public**
- Check tag name matches exactly: `v1.0.0`
- Verify binary is uploaded to release

### Domain: 404 Not Found
- Check nginx config: `sudo nginx -t`
- Verify files exist: `ls -lh /var/www/omniference/downloads/`
- Check permissions: `sudo chmod 755 /var/www/omniference/downloads/provisioning-agent-linux-amd64`
- Reload nginx: `sudo systemctl reload nginx`

### Install Script Fails
- Check internet connectivity
- Verify URLs are accessible
- Check if both sources are available (fallback should work)




