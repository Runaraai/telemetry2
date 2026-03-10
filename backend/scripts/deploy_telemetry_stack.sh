#!/usr/bin/env bash
# Telemetry Stack Deployment Script
# Deploys the GPU telemetry monitoring stack (DCGM, Prometheus, exporters)
# This is a standalone script that can be run directly on the GPU instance

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

# Configuration
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
RUN_ID="${RUN_ID:-$(uuidgen 2>/dev/null || echo $(date +%s))}"
ENABLE_PROFILING="${ENABLE_PROFILING:-false}"
TELEMETRY_DIR="/tmp/gpu-telemetry-${RUN_ID}"

log_info "=========================================="
log_info "GPU Telemetry Stack Deployment"
log_info "=========================================="
log_info "Backend URL: ${BACKEND_URL}"
log_info "Run ID: ${RUN_ID}"
log_info "Telemetry Directory: ${TELEMETRY_DIR}"
log_info ""

# Check prerequisites
log_info "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    log_error "Docker is not installed"
    exit 1
fi

if ! docker ps &>/dev/null 2>&1; then
    log_error "Docker is not accessible"
    exit 1
fi

if ! command -v nvidia-smi &>/dev/null || ! nvidia-smi &>/dev/null 2>&1; then
    log_error "NVIDIA drivers are not working. Please reboot and try again."
    exit 1
fi

if ! docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
    log_error "GPU access in Docker is not working. Check NVIDIA Container Toolkit."
    exit 1
fi

log_success "All prerequisites met"

# Create telemetry directory
log_info "Creating telemetry directory..."
mkdir -p "${TELEMETRY_DIR}"
cd "${TELEMETRY_DIR}"

# Generate docker-compose.yml
log_info "Generating docker-compose.yml..."
cat > docker-compose.yml << 'EOF'
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
EOF

# Get the exporter scripts and configs from deployment.py logic
# For now, we'll create simplified versions
log_info "Creating exporter scripts..."

# This would normally come from deployment.py, but for standalone use,
# we'll need to extract those functions or create a Python helper
log_warn "Note: This script needs the exporter Python scripts from deployment.py"
log_warn "For full deployment, use the backend API or extract scripts from deployment.py"

log_info ""
log_info "To deploy the full telemetry stack, use the backend API:"
log_info "POST /api/instances/{instance_id}/deploy"
log_info ""
log_info "Or extract the scripts from backend/telemetry/deployment.py"

