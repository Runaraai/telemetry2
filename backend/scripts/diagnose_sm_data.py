#!/usr/bin/env python3
"""Diagnostic script to check why SM data isn't being received.

This script checks:
1. DCGM exporter status and logs
2. Profiling mode configuration
3. Available DCGM metrics
4. Prometheus scraping status
"""

import sys
import json
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from telemetry.deployment import DeploymentManager
from telemetry.schemas import DeploymentRequest
import paramiko
import io

def diagnose_dcgm_profiling(ssh_host: str, ssh_user: str, ssh_key: str, run_id: str):
    """SSH into instance and diagnose DCGM profiling issues."""
    
    # Create deployment manager to reuse SSH connection logic
    manager = DeploymentManager()
    
    # Create a minimal request for SSH connection
    request = DeploymentRequest(
        run_id=run_id,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_key=ssh_key,
        backend_url=os.getenv("TELEMETRY_BACKEND_URL") or os.getenv("API_BASE_URL") or "https://voertx.cloud",
        poll_interval=5,
        enable_profiling=True
    )
    
    ssh = manager._connect(request)
    remote_dir = f"/tmp/gpu-telemetry-{run_id}"
    
    try:
        print("=" * 60)
        print("DCGM Profiling Diagnostic Report")
        print("=" * 60)
        print()
        
        # 1. Check if deployment directory exists
        print("1. Checking deployment directory...")
        dir_check = manager._exec_safe(ssh, f"test -d {remote_dir} && echo 'exists' || echo 'missing'")
        if 'exists' not in dir_check:
            print(f"   ❌ ERROR: Deployment directory {remote_dir} not found!")
            print(f"   The telemetry stack may not be deployed.")
            return
        print(f"   ✅ Directory exists: {remote_dir}")
        print()
        
        # 2. Check Docker Compose services status
        print("2. Checking Docker Compose services...")
        status_output = manager._exec_safe(ssh, f"cd {remote_dir} && docker compose ps --format json 2>/dev/null || echo '[]'")
        try:
            services = json.loads(status_output) if status_output else []
            for service in services:
                name = service.get('Service', service.get('Name', 'unknown'))
                state = service.get('State', 'unknown')
                status_icon = "✅" if state == "running" else "❌"
                print(f"   {status_icon} {name}: {state}")
        except:
            print(f"   ⚠️  Could not parse service status")
        print()
        
        # 3. Check DCGM exporter logs
        print("3. Checking DCGM exporter logs (last 50 lines)...")
        logs = manager._exec_safe(ssh, f"cd {remote_dir} && docker compose logs --tail=50 dcgm-exporter 2>&1 | tail -50")
        if logs:
            print("   Logs:")
            for line in logs.split('\n')[-20:]:  # Last 20 lines
                if line.strip():
                    print(f"   {line}")
        else:
            print("   ⚠️  No logs found")
        print()
        
        # 4. Check DCGM collectors CSV file
        print("4. Checking DCGM collectors configuration...")
        csv_content = manager._exec_safe(ssh, f"cat {remote_dir}/dcgm-collectors.csv 2>/dev/null")
        if csv_content:
            has_profiling = "DCGM_FI_PROF_SM_ACTIVE" in csv_content
            print(f"   Profiling metrics in CSV: {'✅ Yes' if has_profiling else '❌ No'}")
            if has_profiling:
                print("   ✅ Found DCGM_FI_PROF_SM_ACTIVE in collectors")
            else:
                print("   ❌ DCGM_FI_PROF_SM_ACTIVE NOT found in collectors!")
                print("   This means profiling mode was not enabled during deployment.")
        else:
            print("   ❌ Could not read dcgm-collectors.csv")
        print()
        
        # 5. Check DCGM exporter environment variables
        print("5. Checking DCGM exporter environment...")
        env_check = manager._exec_safe(ssh, f"cd {remote_dir} && docker compose exec -T dcgm-exporter env 2>/dev/null | grep -E 'DCGM_EXPORTER_ENABLE_PROFILING|DCGM_EXPORTER' || echo 'container not running'")
        if env_check and 'container not running' not in env_check:
            print("   Environment variables:")
            for line in env_check.split('\n'):
                if line.strip():
                    print(f"   {line}")
        else:
            print("   ⚠️  Could not check environment (container may not be running)")
        print()
        
        # 6. Check if DCGM metrics endpoint has profiling data
        print("6. Checking DCGM metrics endpoint...")
        metrics = manager._exec_safe(ssh, f"curl -s http://localhost:9400/metrics 2>/dev/null | grep -E 'DCGM_FI_PROF_SM_ACTIVE|DCGM_FI_PROF' | head -10 || echo 'endpoint not accessible'")
        if metrics and 'endpoint not accessible' not in metrics:
            has_sm_metric = "DCGM_FI_PROF_SM_ACTIVE" in metrics
            print(f"   Profiling metrics in endpoint: {'✅ Yes' if has_sm_metric else '❌ No'}")
            if has_sm_metric:
                print("   Sample metrics found:")
                for line in metrics.split('\n')[:5]:
                    if line.strip():
                        print(f"   {line[:80]}")
            else:
                print("   ❌ No DCGM_FI_PROF_SM_ACTIVE metrics found in endpoint!")
                print("   This means DCGM is not collecting profiling metrics.")
        else:
            print("   ⚠️  Could not access metrics endpoint")
        print()
        
        # 7. Check NVIDIA driver and DCGM support
        print("7. Checking NVIDIA driver and DCGM...")
        nvidia_smi = manager._exec_safe(ssh, "nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1")
        if nvidia_smi:
            print(f"   GPU Info: {nvidia_smi}")
        else:
            print("   ⚠️  nvidia-smi not accessible")
        
        # Check if persistence mode is enabled
        pm_check = manager._exec_safe(ssh, "nvidia-smi -q -d PERFORMANCE 2>/dev/null | grep -A 2 'Persistence Mode' || echo 'not found'")
        if pm_check and 'Enabled' in pm_check:
            print("   ✅ Persistence Mode: Enabled")
        else:
            print("   ⚠️  Persistence Mode: May not be enabled (required for profiling)")
        print()
        
        # 8. Check Prometheus configuration
        print("8. Checking Prometheus configuration...")
        prom_config = manager._exec_safe(ssh, f"cat {remote_dir}/prometheus.yml 2>/dev/null | grep -A 5 'dcgm-exporter' || echo 'config not found'")
        if prom_config and 'config not found' not in prom_config:
            print("   Prometheus scrape config for DCGM:")
            for line in prom_config.split('\n')[:10]:
                if line.strip():
                    print(f"   {line}")
        print()
        
        # 9. Check if profiling permissions are set
        print("9. Checking NVIDIA profiling permissions...")
        modprobe_check = manager._exec_safe(ssh, "cat /etc/modprobe.d/omniference-nvidia.conf 2>/dev/null || echo 'not found'")
        if modprobe_check and 'not found' not in modprobe_check:
            if 'NVreg_RestrictProfilingToAdminUsers=0' in modprobe_check:
                print("   ✅ Profiling permissions configured correctly")
            else:
                print("   ⚠️  Profiling permissions may not be set correctly")
        else:
            print("   ⚠️  Profiling permissions config file not found")
        print()
        
        print("=" * 60)
        print("Diagnostic Complete")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Error during diagnosis: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ssh.close()

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python diagnose_sm_data.py <ssh_host> <ssh_user> <ssh_key_file> <run_id>")
        print("Example: python diagnose_sm_data.py 51.159.138.188 root /path/to/key.pem <run-id>")
        sys.exit(1)
    
    ssh_host = sys.argv[1]
    ssh_user = sys.argv[2]
    ssh_key_path = sys.argv[3]
    run_id = sys.argv[4]
    
    # Read SSH key
    with open(ssh_key_path, 'r') as f:
        ssh_key = f.read()
    
    diagnose_dcgm_profiling(ssh_host, ssh_user, ssh_key, run_id)


