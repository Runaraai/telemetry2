# Omniference User Flow Guide

This document explains how users interact with Omniference to monitor their GPU instances, covering both SSH-based and agent-based deployment methods.

## Table of Contents

1. [Quick Start](#quick-start)
2. [SSH Push Deployment Flow](#ssh-push-deployment-flow)
3. [Agent Pull Deployment Flow](#agent-pull-deployment-flow)
4. [Monitoring and Metrics](#monitoring-and-metrics)
5. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

Before you can monitor a GPU instance, you need:

1. **GPU Instance**: A remote server with NVIDIA GPUs
2. **NVIDIA Driver**: Must be installed on the instance (minimum requirement)
3. **SSH Access**: Either:
   - SSH private key (PEM file) for SSH push deployment, OR
   - Ability to download and run the provisioning agent for agent pull deployment
4. **Network Access**: Instance must be able to reach the Omniference backend (HTTPS)

### Choosing a Deployment Method

- **SSH Push**: Best for one-off deployments, when you have SSH access, or for testing
- **Agent Pull**: Best for persistent monitoring, when you want self-healing, or when SSH is restricted

---

## SSH Push Deployment Flow

### Step 1: Prepare Your Instance

Your GPU instance should have:
- ✅ NVIDIA driver installed (check with `nvidia-smi`)
- ✅ SSH access enabled (port 22)
- ✅ Sudo access (for auto-installing prerequisites)

**Note**: Docker, DCGM, and other prerequisites will be auto-installed if missing (requires sudo).

### Step 2: Access Omniference Frontend

1. Open your browser and navigate to your Omniference instance (e.g., `https://omniference.com`)
2. Log in (if authentication is enabled)
3. Navigate to **"Manage Instances"** or **"Telemetry"** tab

### Step 3: Configure Instance Credentials

1. **If instance already exists**:
   - Select your instance from the list
   - Verify SSH credentials are saved (upload PEM file if needed)

2. **If creating new instance**:
   - Click "Add Instance" or "New Instance"
   - Enter instance details:
     - **Instance ID/Name**: Unique identifier (e.g., "gpu-cluster-1")
     - **IP Address**: Public IP or hostname
     - **SSH User**: Usually "ubuntu" or "root"
     - **SSH Key**: Upload your PEM file (private key)
   - Save instance

### Step 4: Start Monitoring

1. Navigate to **Telemetry** tab
2. Select your instance from the dropdown
3. Verify SSH details are pre-filled:
   - **SSH Host**: IP address or hostname
   - **SSH User**: Username (default: ubuntu)
   - **SSH Key**: Should be loaded from instance credentials
4. Configure monitoring options:
   - **Backend URL**: Usually auto-detected (your Omniference domain)
   - **Poll Interval**: How often Prometheus scrapes (default: 5 seconds)
   - **Enable Profiling**: Check to enable SM-level profiling metrics (optional)
5. Click **"Start Monitoring"**

### Step 5: Monitor Deployment Progress

The frontend will show:

1. **Deployment Queue**:
   - Job appears in queue with status "pending"
   - Status changes: `pending` → `queued` → `running` → `completed` or `failed`
   - Shows attempt count (e.g., "Attempt 1/3")

2. **Component Status** (after deployment starts):
   - Green (✓): Component healthy
   - Red (✗): Component has errors
   - White (○): Component not found

3. **Deployment Status Messages**:
   - "Deploying monitoring stack..."
   - "Validating prerequisites..."
   - "Installing Docker..."
   - "Starting services..."
   - "Monitoring stack is running" (success)

### Step 6: View Real-Time Metrics

Once deployment completes:

1. **WebSocket Connection**: Automatically connects for real-time updates
2. **Real-Time Charts**: Display live GPU metrics:
   - GPU Utilization
   - Memory Utilization
   - Power Draw
   - Temperature
   - And 50+ more metrics
3. **Historical Data**: Click "Historical Runs" to view past monitoring sessions

### Step 7: Stop Monitoring (Optional)

1. Click **"Stop Monitoring"** button
2. Choose whether to preserve Prometheus data:
   - ✅ **Preserve Data**: Keeps metrics in Prometheus (can query later)
   - ❌ **Don't Preserve**: Removes all containers and data
3. Monitoring stack is torn down, run is marked "completed"

### Error Handling

If deployment fails:

1. **Check Queue UI**: See error message in job details
2. **View Error Log**: Full error traceback available
3. **Retry**: Click "Retry" button to retry failed job
4. **Check Prerequisites**: Verify instance has NVIDIA driver installed
5. **Check SSH Access**: Ensure SSH key is correct and instance is reachable

---

## Agent Pull Deployment Flow

### Step 1: Install Agent on GPU Instance (One-Time)

SSH into your GPU instance and install the agent:

```bash
# Option 1: Install script (recommended)
curl -fsSL https://raw.githubusercontent.com/omniference/provisioning-agent/main/install-agent.sh | sudo bash

# Option 2: Manual installation
wget https://github.com/omniference/provisioning-agent/releases/download/v1.0.0/provisioning-agent-linux-amd64
chmod +x provisioning-agent-linux-amd64
sudo mv provisioning-agent-linux-amd64 /usr/local/bin/provisioning-agent
```

**Verify installation**:
```bash
provisioning-agent --version  # Should show version 1.0.0
```

### Step 2: Create Deployment Job (via Frontend or API)

**Via Frontend** (when UI is enhanced):
1. Select instance
2. Choose "Agent Deployment" option
3. Frontend creates job with `deployment_type="agent"`

**Via API** (current):
```bash
# Create deployment job
curl -X POST https://api.example.com/api/instances/{instance_id}/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "your-run-id",
    "deployment_type": "agent",
    "ssh_host": "your-instance-ip",
    "ssh_user": "ubuntu",
    "ssh_key": "your-ssh-key",
    "backend_url": "https://api.example.com"
  }'
```

### Step 3: Generate Provisioning Manifest

```bash
# Get manifest and token
curl -X POST https://api.example.com/api/telemetry/provision/manifests/{deployment_job_id} \
  -H "Content-Type: application/json"

# Response:
# {
#   "token": "abc123...",
#   "manifest_url": "https://api.example.com/api/telemetry/provision/manifests/{manifest_id}?token=abc123...",
#   "expires_at": "2024-01-01T12:00:00Z"
# }
```

### Step 4: Run Agent on GPU Instance

On your GPU instance:

```bash
# Set environment variables
export MANIFEST_URL="https://api.example.com/api/telemetry/provision/manifests/{manifest_id}?token={token}"
export TOKEN="{token}"
export API_BASE_URL="https://api.example.com"  # Optional

# Run agent (one-time)
provisioning-agent "$MANIFEST_URL" "$TOKEN"
```

**Or install as systemd service** (for persistent monitoring):

```bash
# Edit systemd service file
sudo nano /etc/systemd/system/omniference-agent.service

# Add:
[Unit]
Description=Omniference Provisioning Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/provisioning-agent ${MANIFEST_URL} ${TOKEN}
Restart=on-failure
RestartSec=5
Environment="API_BASE_URL=https://api.example.com"

[Install]
WantedBy=multi-user.target

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable omniference-agent
sudo systemctl start omniference-agent

# Check status
sudo systemctl status omniference-agent
```

### Step 5: Monitor Agent Progress

The agent will:

1. **Fetch Manifest**: Downloads deployment configuration from backend
2. **Install Prerequisites**: Installs Docker, NVIDIA Container Toolkit, DCGM if needed
3. **Deploy Stack**: Starts Docker Compose stack
4. **Send Heartbeats**: Reports status to backend every 30 seconds

**Check agent logs**:
```bash
# If running manually
./provisioning-agent "$MANIFEST_URL" "$TOKEN"

# If running as systemd service
sudo journalctl -u omniference-agent -f
```

### Step 6: View Deployment Status

In the frontend:

1. **Queue UI**: Shows agent deployment job status
2. **Heartbeat History**: View agent heartbeats via API:
   ```bash
   curl https://api.example.com/api/telemetry/provision/callbacks/{manifest_id}/heartbeats
   ```
3. **Component Status**: Same as SSH deployment (check component health)

### Step 7: View Real-Time Metrics

Same as SSH deployment:
- WebSocket connects automatically
- Real-time charts display live metrics
- Historical data available

---

## Monitoring and Metrics

### Available Metrics

Omniference collects 50+ GPU metrics:

**Utilization**:
- GPU Utilization (standard)
- SM Utilization (profiling)
- SM Occupancy (profiling)
- HBM Utilization
- Memory Utilization

**Performance**:
- Tensor Core Activity (FP64, FP32, FP16)
- Graphics Engine Activity
- PCIe Bandwidth (TX/RX)
- NVLink Bandwidth (TX/RX)

**Power & Thermal**:
- Power Draw (Watts)
- Power Limit
- Temperature (°C)
- Memory Temperature

**Errors & Health**:
- ECC Errors (single-bit, double-bit)
- PCIe Replay Errors
- NVLink Errors
- XID Errors
- Throttle Reasons

### Real-Time Monitoring

- **Update Frequency**: Metrics update every 5 seconds (configurable)
- **WebSocket Connection**: Automatic reconnection on disconnect
- **Chart Types**: Line charts for time-series visualization
- **Multi-GPU Support**: Separate series for each GPU

### Historical Analysis

- **Time Range Selection**: Query metrics for any time period
- **Downsampling**: Automatic downsampling for long time ranges
- **Export**: Download metrics as JSON or CSV (future feature)

---

## Troubleshooting

### SSH Deployment Issues

**Problem**: Deployment fails with "SSH connection refused"
- **Solution**: Check firewall rules, ensure port 22 is open, verify SSH key is correct

**Problem**: "NVIDIA driver not found"
- **Solution**: Install NVIDIA driver manually: `sudo apt install nvidia-driver-535-server && sudo reboot`

**Problem**: "Docker installation failed"
- **Solution**: Check sudo access, ensure instance has internet connectivity

**Problem**: Deployment stuck in "queued" status
- **Solution**: Check backend logs, ensure deployment worker is running

### Agent Deployment Issues

**Problem**: Agent can't fetch manifest
- **Solution**: Verify token is correct, check manifest hasn't expired (1 hour), ensure instance can reach backend

**Problem**: Agent installation fails
- **Solution**: Check internet connectivity, ensure you have sudo access, verify Go binary is compatible with your architecture

**Problem**: Agent heartbeats not received
- **Solution**: Check agent logs, verify backend is accessible, check firewall allows outbound HTTPS

### General Issues

**Problem**: No metrics received
- **Solution**: Check component status, verify Prometheus is running, check remote_write endpoint is accessible

**Problem**: WebSocket disconnects frequently
- **Solution**: Check network stability, verify backend is accessible, check browser console for errors

**Problem**: Charts show "No data"
- **Solution**: Wait a few seconds for initial data, check WebSocket connection status, verify run is active

---

## Next Steps

- **SM-Level Profiling**: Enable profiling mode for detailed per-SM metrics
- **Policy Monitoring**: Set up alerts for thermal, power, and ECC errors
- **AI Insights**: Get AI-powered recommendations for optimization
- **Historical Analysis**: Analyze past runs to identify trends

For more information, see:
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Deployment guide
- [QUICK_START.md](QUICK_START.md) - Quick start guide




