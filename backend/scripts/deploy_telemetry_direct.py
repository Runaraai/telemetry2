#!/usr/bin/env python3
"""
Direct Telemetry Stack Deployment Script
Deploys telemetry stack directly on GPU instance using deployment.py logic
"""

import sys
import os
from pathlib import Path
from uuid import uuid4

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from telemetry.deployment import DeploymentManager
from telemetry.schemas import DeploymentRequest

def main():
    if len(sys.argv) < 4:
        print("Usage: deploy_telemetry_direct.py <ssh_host> <ssh_user> <ssh_key_path> [backend_url] [run_id]")
        print("Example: deploy_telemetry_direct.py 163.192.27.149 ubuntu ~/madhur.pem http://your-backend:8000")
        sys.exit(1)
    
    ssh_host = sys.argv[1]
    ssh_user = sys.argv[2]
    ssh_key_path = sys.argv[3]
    backend_url = sys.argv[4] if len(sys.argv) > 4 else "http://localhost:8000"
    run_id = sys.argv[5] if len(sys.argv) > 5 else str(uuid4())
    
    # Read SSH key
    with open(os.path.expanduser(ssh_key_path), 'r') as f:
        ssh_key = f.read()
    
    # Create deployment request
    request = DeploymentRequest(
        run_id=run_id,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_key=ssh_key,
        backend_url=backend_url,
        enable_profiling=False
    )
    
    # Deploy
    manager = DeploymentManager()
    instance_id = f"{ssh_host}"
    
    print(f"Deploying telemetry stack to {ssh_host}...")
    print(f"Run ID: {run_id}")
    print(f"Backend URL: {backend_url}")
    
    try:
        services = manager._perform_deploy(request, uuid4())
        print("\n✅ Telemetry stack deployed successfully!")
        print("\nServices:")
        for service, status in services.items():
            print(f"  - {service}: {status}")
        print(f"\nTelemetry directory: /tmp/gpu-telemetry-{run_id}")
        print("\nAccess points:")
        print("  - Prometheus: http://{}:9090".format(ssh_host))
        print("  - DCGM Exporter: http://{}:9400/metrics".format(ssh_host))
        print("  - NVIDIA-SMI Exporter: http://{}:9401/metrics".format(ssh_host))
        print("  - Token Exporter: http://{}:9402/metrics".format(ssh_host))
    except Exception as e:
        print(f"\n❌ Deployment failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

