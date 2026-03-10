#!/bin/bash
# Quick start script for continuous inference
# Usage: ./run_inference.sh <IP_ADDRESS> [INTERVAL]

IP=${1:-"150.136.36.90"}
INTERVAL=${2:-"5.0"}

echo "Starting continuous inference for IP: $IP with interval: ${INTERVAL}s"
echo "Press Ctrl+C to stop"
echo ""

# Try to run from backend directory
cd "$(dirname "$0")/.." || exit 1

# Check if we're in a virtual environment or Docker
if [ -f "requirements.txt" ]; then
    # Try to use Python from the environment
    python3 scripts/continuous_inference.py --ip "$IP" --interval "$INTERVAL"
else
    echo "Error: Please run this from the backend directory or install dependencies"
    exit 1
fi


