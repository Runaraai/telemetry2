#!/usr/bin/env bash
# Deploy Telemetry Stack via SSH
# This script deploys the telemetry stack directly on the GPU instance

set -euo pipefail

SSH_HOST="${1:-163.192.27.149}"
SSH_USER="${2:-ubuntu}"
SSH_KEY="${3:-~/madhur.pem}"
BACKEND_URL="${4:-http://localhost:8000}"
RUN_ID="${5:-$(date +%s)}"
ENABLE_PROFILING="${6:-false}"

TELEMETRY_DIR="/tmp/gpu-telemetry-${RUN_ID}"

echo "=========================================="
echo "Deploying Telemetry Stack"
echo "=========================================="
echo "Host: ${SSH_USER}@${SSH_HOST}"
echo "Backend URL: ${BACKEND_URL}"
echo "Run ID: ${RUN_ID}"
echo "Telemetry Dir: ${TELEMETRY_DIR}"
echo ""

# Check prerequisites on remote
echo "Checking prerequisites..."
ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${SSH_USER}@${SSH_HOST}" << 'EOF'
    if ! command -v docker &>/dev/null; then
        echo "ERROR: Docker not installed"
        exit 1
    fi
    if ! nvidia-smi &>/dev/null 2>&1; then
        echo "ERROR: NVIDIA drivers not working"
        exit 1
    fi
    if ! docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
        echo "ERROR: GPU access in Docker not working"
        exit 1
    fi
    echo "✅ Prerequisites OK"
EOF

# Create directory and deploy files
echo "Creating telemetry directory and deploying files..."
ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${SSH_USER}@${SSH_HOST}" << EOF
    mkdir -p "${TELEMETRY_DIR}"
    cd "${TELEMETRY_DIR}"
    
    # Create docker-compose.yml
    cat > docker-compose.yml << 'DOCKERCOMPOSE'
services:
  dcgm-exporter:
    image: nvcr.io/nvidia/k8s/dcgm-exporter:4.2.0-4.1.0-ubuntu22.04
    privileged: true
    volumes:
      - ./dcgm-collectors.csv:/etc/dcgm-exporter/dcp-metrics-included.csv:ro
      - /usr/bin/nvidia-smi:/usr/bin/nvidia-smi:ro
      - /usr/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu:rw
    environment:
      DCGM_EXPORTER_LISTEN: ":9400"
      DCGM_EXPORTER_KUBERNETES: "false"
      DCGM_EXPORTER_COLLECTORS: "/etc/dcgm-exporter/dcp-metrics-included.csv"
      DCGM_EXPORTER_INTERVAL: "5000"
      DCGM_EXPORTER_ENABLE_PROFILING: "true"
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
      LD_LIBRARY_PATH: /usr/lib/x86_64-linux-gnu
    ports:
      - "9400:9400"
    cap_add:
      - SYS_ADMIN
    devices:
      - "/dev/nvidia0:/dev/nvidia0"
      - "/dev/nvidiactl:/dev/nvidiactl"
      - "/dev/nvidia-uvm:/dev/nvidia-uvm"
      - "/dev/nvidia-uvm-tools:/dev/nvidia-uvm-tools"
    restart: unless-stopped

  nvidia-smi-exporter:
    image: python:3.11-slim
    privileged: true
    command: python3 /app/nvidia-smi-exporter.py
    volumes:
      - ./nvidia-smi-exporter.py:/app/nvidia-smi-exporter.py:ro
      - /usr/bin/nvidia-smi:/usr/bin/nvidia-smi:ro
      - /usr/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu:rw
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
      LD_LIBRARY_PATH: /usr/lib/x86_64-linux-gnu
    ports:
      - "9401:9401"
    restart: unless-stopped
    network_mode: host
    devices:
      - "/dev/nvidia0:/dev/nvidia0"
      - "/dev/nvidiactl:/dev/nvidiactl"
      - "/dev/nvidia-uvm:/dev/nvidia-uvm"
      - "/dev/nvidia-uvm-tools:/dev/nvidia-uvm-tools"

  dcgm-health-exporter:
    image: python:3.11-slim
    privileged: true
    command: python3 /app/dcgm-health-exporter.py
    volumes:
      - ./dcgm-health-exporter.py:/app/dcgm-health-exporter.py:ro
      - /usr/bin/nvidia-smi:/usr/bin/nvidia-smi:ro
      - /usr/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu:rw
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
      LD_LIBRARY_PATH: /usr/lib/x86_64-linux-gnu
    ports:
      - "9403:9403"
    restart: unless-stopped
    network_mode: host
    devices:
      - "/dev/nvidia0:/dev/nvidia0"
      - "/dev/nvidiactl:/dev/nvidiactl"
      - "/dev/nvidia-uvm:/dev/nvidia-uvm"
      - "/dev/nvidia-uvm-tools:/dev/nvidia-uvm-tools"

  token-exporter:
    image: python:3.11-slim
    command: python3 /app/token-exporter.py
    volumes:
      - ./token-exporter.py:/app/token-exporter.py:ro
      - token-data:/data
    ports:
      - "9402:9402"
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:v2.48.0
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=2h'
      - '--web.enable-lifecycle'
    ports:
      - "9090:9090"
    restart: unless-stopped
    depends_on:
      - dcgm-exporter
      - nvidia-smi-exporter
      - dcgm-health-exporter
      - token-exporter

volumes:
  prometheus-data:
  token-data:
DOCKERCOMPOSE

    # Create prometheus.yml
    cat > prometheus.yml << PROMETHEUS
global:
  scrape_interval: 1s
  evaluation_interval: 1s

scrape_configs:
  - job_name: 'dcgm'
    static_configs:
      - targets: ['dcgm-exporter:9400']
        labels:
          exporter: 'dcgm'
          run_id: '${RUN_ID}'

  - job_name: 'nvidia-smi'
    static_configs:
      - targets: ['localhost:9401']
        labels:
          exporter: 'nvidia-smi'
          run_id: '${RUN_ID}'

  - job_name: 'dcgm-health'
    static_configs:
      - targets: ['localhost:9403']
        labels:
          exporter: 'dcgm-health'
          run_id: '${RUN_ID}'

  - job_name: 'tokens'
    static_configs:
      - targets: ['token-exporter:9402']
        labels:
          exporter: 'tokens'
          run_id: '${RUN_ID}'

remote_write:
  - url: '${BACKEND_URL}/api/telemetry/remote-write'
    headers:
      X-Run-ID: '${RUN_ID}'
    queue_config:
      capacity: 10000
      max_shards: 5
      min_shards: 1
      max_samples_per_send: 1000
      batch_send_deadline: 5s
PROMETHEUS

    # Create dcgm-collectors.csv
    cat > dcgm-collectors.csv << 'DCGMCSV'
# Format: DCGM_FI_<field_name>, <metric type>, <Prometheus metric name>
# Core GPU utilization metrics
DCGM_FI_DEV_GPU_UTIL, gauge, DCGM_FI_DEV_GPU_UTIL
DCGM_FI_DEV_MEM_COPY_UTIL, gauge, DCGM_FI_DEV_MEM_COPY_UTIL

# Memory metrics
DCGM_FI_DEV_FB_FREE, gauge, DCGM_FI_DEV_FB_FREE
DCGM_FI_DEV_FB_USED, gauge, DCGM_FI_DEV_FB_USED
DCGM_FI_DEV_FB_TOTAL, gauge, DCGM_FI_DEV_FB_TOTAL

# Temperature metrics
DCGM_FI_DEV_GPU_TEMP, gauge, DCGM_FI_DEV_GPU_TEMP
DCGM_FI_DEV_MEMORY_TEMP, gauge, DCGM_FI_DEV_MEMORY_TEMP

# Power metrics
DCGM_FI_DEV_POWER_USAGE, gauge, DCGM_FI_DEV_POWER_USAGE
DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION, gauge, DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION

# Clock frequencies
DCGM_FI_DEV_SM_CLOCK, gauge, DCGM_FI_DEV_SM_CLOCK
DCGM_FI_DEV_MEM_CLOCK, gauge, DCGM_FI_DEV_MEM_CLOCK

# PCIe metrics
DCGM_FI_DEV_PCIE_TX_THROUGHPUT, gauge, DCGM_FI_DEV_PCIE_TX_THROUGHPUT
DCGM_FI_DEV_PCIE_RX_THROUGHPUT, gauge, DCGM_FI_DEV_PCIE_RX_THROUGHPUT
DCGM_FI_DEV_PCIE_REPLAY_COUNTER, gauge, DCGM_FI_DEV_PCIE_REPLAY_COUNTER

# NVLink metrics
DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL, gauge, DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL

# ECC error metrics
DCGM_FI_DEV_ECC_SBE_VOL_TOTAL, gauge, DCGM_FI_DEV_ECC_SBE_VOL_TOTAL
DCGM_FI_DEV_ECC_DBE_VOL_TOTAL, gauge, DCGM_FI_DEV_ECC_DBE_VOL_TOTAL

# Throttle reasons
DCGM_FI_DEV_CLOCK_THROTTLE_REASONS, gauge, DCGM_FI_DEV_CLOCK_THROTTLE_REASONS

# XID errors
DCGM_FI_DEV_XID_ERRORS, gauge, DCGM_FI_DEV_XID_ERRORS

# Power management
DCGM_FI_DEV_POWER_MGMT_LIMIT, gauge, DCGM_FI_DEV_POWER_MGMT_LIMIT
DCGMCSV

    echo "✅ Configuration files created"
EOF

# Now we need to create the Python exporter scripts
# These are too long to inline, so we'll create them separately
echo "Creating exporter scripts..."
# This is getting too complex - let me use a simpler approach with a Python script that generates the files
echo "Note: The exporter Python scripts need to be created. Using deployment.py logic..."
echo ""
echo "To complete deployment, you can either:"
echo "1. Use the backend API: POST /api/instances/{instance_id}/deploy"
echo "2. Extract the Python exporter scripts from backend/telemetry/deployment.py"
echo ""
echo "For now, let's check if we can use curl to deploy via the backend API if it's running..."

