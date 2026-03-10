"""Instance orchestration service for launching, setting up, and deploying models."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

import aiohttp
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session, get_session
from ..models import InstanceOrchestration
from ..services.ssh_executor import SSHExecutor

logger = logging.getLogger(__name__)


class InstanceOrchestrator:
    """Orchestrates instance launch, setup, and model deployment."""

    # Lambda Labs instance type to GPU count mapping
    # Common patterns: gpu_1x_a100, gpu_8x_h100, etc.
    INSTANCE_TYPE_GPU_MAP = {
        # A100 instances
        "gpu_1x_a100": 1,
        "gpu_1x_a10": 1,
        "gpu_1x_a6000": 1,
        # H100 instances
        "gpu_1x_h100": 1,
        "gpu_8x_h100": 8,
        # RTX 6000 Ada
        "gpu_1x_rtx6000ada": 1,
        "gpu_2x_rtx6000ada": 2,
        "gpu_4x_rtx6000ada": 4,
        # RTX 4090
        "gpu_1x_rtx4090": 1,
        "gpu_2x_rtx4090": 2,
        "gpu_4x_rtx4090": 4,
    }

    @staticmethod
    def _get_expected_gpu_count_from_instance_type(instance_type: str) -> Optional[int]:
        """
        Get expected GPU count from Lambda Labs instance type name.
        
        Args:
            instance_type: Lambda Labs instance type (e.g., "gpu_1x_a100", "gpu_8x_h100")
            
        Returns:
            Expected GPU count, or None if cannot determine
        """
        # Direct lookup
        if instance_type in InstanceOrchestrator.INSTANCE_TYPE_GPU_MAP:
            return InstanceOrchestrator.INSTANCE_TYPE_GPU_MAP[instance_type]
        
        # Pattern matching: gpu_Nx_* where N is the GPU count
        import re
        match = re.search(r'gpu_(\d+)x_', instance_type.lower())
        if match:
            return int(match.group(1))
        
        # Pattern matching: *_Nx_* where N is the GPU count
        match = re.search(r'_(\d+)x_', instance_type.lower())
        if match:
            return int(match.group(1))
        
        return None

    @staticmethod
    async def _detect_gpu_info(
        ip_address: str,
        ssh_key: str,
        instance_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Detect GPU information from instance.
        
        Returns:
            Dict with keys: gpu_count, gpu_type, gpu_memory_total (in GB), gpu_names
        """
        gpu_info = {
            "gpu_count": None,
            "gpu_type": None,
            "gpu_memory_total": None,
            "gpu_names": []
        }
        
        # First, try to get expected GPU count from instance type
        expected_gpu_count = None
        if instance_type:
            expected_gpu_count = InstanceOrchestrator._get_expected_gpu_count_from_instance_type(instance_type)
            if expected_gpu_count:
                logger.info(f"Expected GPU count from instance type '{instance_type}': {expected_gpu_count}")
                gpu_info["gpu_count"] = expected_gpu_count
        
        # Try to detect via nvidia-smi
        try:
            # Get GPU count
            gpu_count_cmd = "nvidia-smi --list-gpus | wc -l"
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=gpu_count_cmd,
                timeout=30,
                check_status=False
            )
            if exit_code == 0 and stdout:
                detected_count = int(stdout.strip())
                gpu_info["gpu_count"] = detected_count
                logger.info(f"Detected {detected_count} GPU(s) via nvidia-smi")
                
                # Validate against expected count if available
                if expected_gpu_count and detected_count != expected_gpu_count:
                    logger.warning(
                        f"GPU count mismatch: expected {expected_gpu_count} from instance type, "
                        f"but detected {detected_count} via nvidia-smi. Using detected count."
                    )
        except Exception as e:
            logger.warning(f"Could not detect GPU count via nvidia-smi: {e}")
        
        # Get GPU details (name, memory)
        try:
            gpu_details_cmd = "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=gpu_details_cmd,
                timeout=30,
                check_status=False
            )
            if exit_code == 0 and stdout:
                lines = stdout.strip().split('\n')
                gpu_names = []
                total_memory_gb = 0
                
                for line in lines:
                    if ',' in line:
                        parts = line.split(',')
                        if len(parts) >= 2:
                            gpu_name = parts[0].strip()
                            memory_str = parts[1].strip()
                            gpu_names.append(gpu_name)
                            
                            # Parse memory (format: "XXXXX MiB" or "XX GB")
                            try:
                                if 'MiB' in memory_str:
                                    memory_mib = float(memory_str.replace('MiB', '').strip())
                                    memory_gb = memory_mib / 1024
                                elif 'GB' in memory_str:
                                    memory_gb = float(memory_str.replace('GB', '').strip())
                                else:
                                    memory_gb = float(memory_str.strip()) / 1024  # Assume MiB if no unit
                                total_memory_gb += memory_gb
                            except:
                                pass
                
                if gpu_names:
                    gpu_info["gpu_names"] = gpu_names
                    gpu_info["gpu_type"] = gpu_names[0] if gpu_names else None
                    gpu_info["gpu_memory_total"] = round(total_memory_gb, 2)
                    logger.info(f"Detected GPU type: {gpu_info['gpu_type']}, total memory: {gpu_info['gpu_memory_total']} GB")
        except Exception as e:
            logger.warning(f"Could not detect GPU details: {e}")
        
        return gpu_info

    @staticmethod
    async def launch_and_setup(
        orchestration_id: UUID,
        instance_type: str,
        region: str,
        ssh_key_name: str,
        api_key: str,
        ssh_key_data: Optional[str] = None,  # SSH private key content
        model_name: Optional[str] = None,
        vllm_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Launch instance and orchestrate full setup in background.
        
        This runs as a background task and updates the orchestration record.
        """
        async with async_session() as session:
            try:
                # Update status to launching
                await InstanceOrchestrator._update_status(
                    session, orchestration_id, "launching", "launch", 5, "Launching instance via Lambda Cloud..."
                )

                # Step 1: Launch instance via Lambda Cloud API
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                from main import make_lambda_api_request

                # Check if SSH key exists in Lambda account before launching
                try:
                    ssh_keys_response = await make_lambda_api_request("ssh-keys", api_key_override=api_key)
                    existing_keys = ssh_keys_response.get("data", [])
                    key_exists = any(key.get("name") == ssh_key_name for key in existing_keys)
                    
                    if not key_exists:
                        logger.warning(f"SSH key '{ssh_key_name}' not found in Lambda account. Available keys: {[k.get('name') for k in existing_keys]}")
                        # Try to create the SSH key if we have the public key
                        # Note: We need the public key to create it. For now, we'll raise an error.
                        raise ValueError(
                            f"SSH key '{ssh_key_name}' not found in your Lambda account. "
                            f"Please create it first in Lambda Labs dashboard or use an existing key name. "
                            f"Available keys: {', '.join([k.get('name', 'unknown') for k in existing_keys]) if existing_keys else 'none'}"
                        )
                except Exception as e:
                    if "not found" in str(e).lower() or "SSH key" in str(e):
                        raise
                    # If checking keys fails, log but continue (might be permission issue)
                    logger.warning(f"Could not verify SSH key existence: {str(e)}")

                # Build launch payload according to Lambda Cloud API spec:
                # POST /api/v1/instance-operations/launch
                # Required: region_name, instance_type_name, ssh_key_names (array)
                # Optional: name, hostname, image, user_data, tags, file_system_names, etc.
                launch_payload = {
                    "region_name": region,
                    "instance_type_name": instance_type,
                    "ssh_key_names": [ssh_key_name]  # Array with exactly one SSH key (per API spec)
                }
                
                # Optionally add instance name for better tracking
                # launch_payload["name"] = f"omniference-{orchestration_id.hex[:8]}"

                # Launch instance via Lambda Cloud API
                # API: POST /api/v1/instance-operations/launch
                # Response: { "data": { "instance_ids": ["instance-id-1", ...] } }
                try:
                    launch_data = await make_lambda_api_request(
                        "instance-operations/launch",
                        method="POST",
                        data=launch_payload,
                        api_key_override=api_key
                    )
                except Exception as e:
                    error_msg = str(e)
                    # Check if it's a capacity error
                    if "not enough capacity" in error_msg.lower() or "capacity" in error_msg.lower():
                        # Try to get available regions/instance types with capacity
                        try:
                            instance_types_data = await make_lambda_api_request(
                                "instance-types",
                                api_key_override=api_key
                            )
                            available_options = []
                            if instance_types_data.get("data"):
                                for inst_type, details in instance_types_data["data"].items():
                                    if details.get("regions_with_capacity_available"):
                                        available_options.append(
                                            f"{inst_type} in {', '.join(details['regions_with_capacity_available'][:3])}"
                                        )
                            
                            suggestion = (
                                f"Not enough capacity for {instance_type} in {region}. "
                                f"Try a different region or instance type. "
                            )
                            if available_options:
                                suggestion += f"Available options: {', '.join(available_options[:5])}"
                            else:
                                suggestion += "Please try again later or check Lambda Cloud dashboard for availability."
                            
                            raise ValueError(suggestion) from e
                        except:
                            # If we can't get availability info, provide generic suggestion
                            raise ValueError(
                                f"Not enough capacity for {instance_type} in {region}. "
                                f"Please try: 1) A different region (us-west-1, eu-west-1), "
                                f"2) A different instance type, or 3) Retry later when capacity becomes available."
                            ) from e
                    raise

                # Extract instance ID from response
                # Per API spec: response.data.instance_ids is an array
                instance_ids = launch_data.get("data", {}).get("instance_ids", [])
                if not instance_ids or len(instance_ids) == 0:
                    raise ValueError("No instance IDs returned from Lambda Cloud API. Response: " + str(launch_data))
                
                instance_id = instance_ids[0]  # Get first instance ID
                if not instance_id:
                    raise ValueError("Empty instance ID returned from Lambda Cloud")

                await InstanceOrchestrator._update_status(
                    session, orchestration_id, "waiting_ip", "launch", 15,
                    f"Instance {instance_id} launched, waiting for IP address...",
                    instance_id=instance_id
                )

                # Step 2: Wait for IP address
                ip_address = await InstanceOrchestrator._wait_for_instance_ip(
                    instance_id, api_key, timeout=300
                )

                if not ip_address:
                    raise TimeoutError("Instance did not get an IP address within timeout")

                await InstanceOrchestrator._update_status(
                    session, orchestration_id, "setting_up", "setup", 20,
                    f"Instance ready at {ip_address}, waiting for SSH to be available...",
                    ip_address=ip_address
                )
                
                # Store instance_type in config for later use in deployment
                try:
                    # Get current config
                    config_stmt = select(InstanceOrchestration.config).where(
                        InstanceOrchestration.orchestration_id == orchestration_id
                    )
                    config_result = await session.execute(config_stmt)
                    current_config = config_result.scalar_one_or_none() or {}
                    
                    # Update config with instance_type
                    updated_config = {**current_config, "instance_type": instance_type}
                    
                    config_update_stmt = update(InstanceOrchestration).where(
                        InstanceOrchestration.orchestration_id == orchestration_id
                    ).values(config=updated_config)
                    await session.execute(config_update_stmt)
                    await session.commit()
                    logger.info(f"Stored instance_type '{instance_type}' in orchestration config")
                except Exception as e:
                    logger.warning(f"Could not store instance_type in config: {e}")

                # Step 3: Get SSH key from parameter or from orchestration config
                if not ssh_key_data:
                    # Try to get from orchestration config (stored when orchestration was created)
                    config_stmt = select(InstanceOrchestration.config).where(
                        InstanceOrchestration.orchestration_id == orchestration_id
                    )
                    config_result = await session.execute(config_stmt)
                    config_data = config_result.scalar_one_or_none()
                    if config_data:
                        ssh_key_data = config_data.get("ssh_key")
                
                if not ssh_key_data:
                    raise ValueError("SSH key data is required for setup. Please provide ssh_key in the request.")
                
                # Step 4: Wait for SSH to be available (instance may still be booting)
                await InstanceOrchestrator._wait_for_ssh_ready(
                    session, orchestration_id, ip_address, ssh_key_data,
                    instance_id=instance_id, api_key=api_key
                )
                
                # Step 5: Trigger automated setup
                await InstanceOrchestrator._update_status(
                    session, orchestration_id, "setting_up", "setup", 25,
                    f"SSH connection established, starting automated setup...",
                    ip_address=ip_address
                )
                await InstanceOrchestrator._trigger_automated_setup(
                    session, orchestration_id, ip_address, ssh_key_data, model_name
                )

                # Step 4: Deploy model if specified
                if model_name:
                    await InstanceOrchestrator._update_status(
                        session, orchestration_id, "deploying_model", "model_deploy", 90,
                        f"Setup complete, deploying model {model_name}..."
                    )
                    await InstanceOrchestrator._deploy_model(
                        session, orchestration_id, ip_address, ssh_key_data, model_name, vllm_config or {}
                    )
                    await InstanceOrchestrator._update_status(
                        session, orchestration_id, "ready", "ready", 100,
                        f"Instance setup and model deployment complete! Model {model_name} is now running.",
                        model_deployed=model_name,
                        completed_at=datetime.now(timezone.utc)
                    )
                else:
                    await InstanceOrchestrator._update_status(
                        session, orchestration_id, "ready", "ready", 100,
                        "Instance setup complete! Please select a model to deploy.",
                        completed_at=datetime.now(timezone.utc)
                    )

            except Exception as e:
                logger.error(f"Orchestration failed for {orchestration_id}: {str(e)}", exc_info=True)
                async with get_session() as error_session:
                    await InstanceOrchestrator._update_status(
                        error_session, orchestration_id, "failed", "error", 0,
                        f"Orchestration failed: {str(e)}",
                        error_message=str(e),
                        completed_at=datetime.now(timezone.utc)
                    )

    @staticmethod
    async def _wait_for_instance_ip(
        instance_id: str,
        api_key: str,
        timeout: int = 300,
        poll_interval: int = 10
    ) -> Optional[str]:
        """Wait for instance to get an IP address."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        from main import make_lambda_api_request

        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                instance_data = await make_lambda_api_request(
                    f"instances/{instance_id}",
                    method="GET",
                    api_key_override=api_key
                )
                
                instance = instance_data.get("data", {})
                ip = instance.get("ip")
                
                if ip:
                    logger.info(f"Instance {instance_id} got IP: {ip}")
                    return ip
                
                await asyncio.sleep(poll_interval)
            except Exception as e:
                logger.warning(f"Error checking instance IP: {e}")
                await asyncio.sleep(poll_interval)
        
        return None

    @staticmethod
    async def _wait_for_ssh_ready(
        session: AsyncSession,
        orchestration_id: UUID,
        ip_address: str,
        ssh_key: str,
        max_wait_time: int = 600,  # 10 minutes max wait (Lambda Labs instances can take 5-8 minutes to boot)
        check_interval: int = 10,  # Check every 10 seconds
        instance_id: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """Wait for SSH to become available on the instance."""
        await InstanceOrchestrator._update_status(
            session, orchestration_id, "setting_up", "setup", 22,
            f"Waiting for SSH to be available on {ip_address} (this may take 3-5 minutes for Lambda Labs instances)...",
            ip_address=ip_address
        )
        
        start_time = asyncio.get_event_loop().time()
        attempt = 0
        last_status_update = 0
        last_instance_state_check = 0
        last_port_check = 0
        
        while (asyncio.get_event_loop().time() - start_time) < max_wait_time:
            attempt += 1
            elapsed = int(asyncio.get_event_loop().time() - start_time)
            
            # Periodically check instance state via Lambda Cloud API (every 45 seconds)
            # This helps diagnose if the instance is actually running
            instance_state = None
            if instance_id and api_key and (elapsed - last_instance_state_check) >= 45:
                try:
                    instance_state = await InstanceOrchestrator._check_instance_state(
                        instance_id, api_key
                    )
                    if instance_state:
                        logger.info(f"Instance {instance_id} state: {instance_state}")
                        if instance_state != "active":
                            logger.warning(
                                f"Instance {instance_id} is in state '{instance_state}', "
                                f"not 'active'. SSH may not be available yet."
                            )
                    last_instance_state_check = elapsed
                except Exception as e:
                    logger.debug(f"Could not check instance state: {str(e)}")
            
            # Check if port 22 is open before attempting SSH (every 30 seconds)
            # This is faster than SSH attempts and helps diagnose network issues
            port_22_open = None
            if elapsed - last_port_check >= 30:
                try:
                    port_22_open = await asyncio.to_thread(
                        InstanceOrchestrator._check_port_open, ip_address, 22, 5
                    )
                    if port_22_open:
                        logger.debug(f"Port 22 is open on {ip_address}")
                    else:
                        logger.debug(f"Port 22 is not yet open on {ip_address}")
                    last_port_check = elapsed
                except Exception as e:
                    logger.debug(f"Port check failed: {str(e)}")
            
            try:
                # Use quick connectivity check with shorter timeout (10 seconds)
                # This is much faster than full command execution during boot
                is_connected = await SSHExecutor.check_ssh_connectivity(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    connection_timeout=10,  # Quick 10-second timeout for connectivity checks
                )
                
                if is_connected:
                    # Connection successful, verify with a quick command test
                    try:
                        test_cmd = "echo 'SSH connection test'"
                        stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                            ssh_host=ip_address,
                            ssh_user="ubuntu",
                            ssh_key=ssh_key,
                            command=test_cmd,
                            timeout=15,  # Short timeout for verification
                            check_status=False
                        )
                        if exit_code == 0:
                            logger.info(f"SSH connection verified to {ip_address} after {attempt} attempts ({elapsed}s elapsed)")
                            await InstanceOrchestrator._update_status(
                                session, orchestration_id, "setting_up", "setup", 24,
                                f"SSH connection established successfully!",
                                ip_address=ip_address
                            )
                            return
                    except Exception as e:
                        # Connection worked but command failed, might be still booting
                        logger.debug(f"SSH connected but command failed (instance may still be initializing): {str(e)}")
                        # Continue waiting
            except Exception as e:
                logger.debug(f"SSH not ready yet (attempt {attempt}, {elapsed}s elapsed): {str(e)}")
            
            # Update status every 40 seconds to avoid spam (increased from 30)
            if elapsed - last_status_update >= 40:
                status_msg = f"Waiting for SSH... ({elapsed}s/{max_wait_time}s elapsed, instance may still be booting)"
                if instance_state:
                    status_msg += f" [State: {instance_state}]"
                if port_22_open is not None:
                    status_msg += f" [Port 22: {'open' if port_22_open else 'closed'}]"
                await InstanceOrchestrator._update_status(
                    session, orchestration_id, "setting_up", "setup", 22,
                    status_msg,
                    ip_address=ip_address
                )
                last_status_update = elapsed
            
            await asyncio.sleep(check_interval)
        
        # If we get here, SSH never became available
        elapsed = int(asyncio.get_event_loop().time() - start_time)
        
        # Gather comprehensive diagnostics for error message
        instance_state_info = ""
        instance_details = {}
        port_22_status = "unknown"
        network_reachable = "unknown"
        
        # Get instance state and details
        if instance_id and api_key:
            try:
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                from main import make_lambda_api_request
                
                instance_data = await make_lambda_api_request(
                    f"instances/{instance_id}",
                    method="GET",
                    api_key_override=api_key
                )
                instance = instance_data.get("data", {})
                instance_state = instance.get("status", {}).get("state")
                if instance_state:
                    instance_state_info = f" Instance state: {instance_state}."
                    instance_details = {
                        "state": instance_state,
                        "status": instance.get("status", {}),
                        "region": instance.get("region", {}).get("name", "unknown"),
                        "instance_type": instance.get("instance_type", {}).get("name", "unknown"),
                    }
            except Exception as e:
                logger.debug(f"Could not get instance details for error message: {e}")
        
        # Check network connectivity
        try:
            network_reachable = await asyncio.to_thread(
                InstanceOrchestrator._check_network_reachable, ip_address, timeout=5
            )
            network_reachable = "reachable" if network_reachable else "unreachable"
        except Exception:
            network_reachable = "check failed"
        
        # Check port 22 status
        try:
            port_22_open = await asyncio.to_thread(
                InstanceOrchestrator._check_port_open, ip_address, 22, timeout=5
            )
            port_22_status = "open" if port_22_open else "closed"
        except Exception:
            port_22_status = "check failed"
        
        # Build comprehensive error message
        error_msg = (
            f"SSH connection to {ip_address} did not become available within {max_wait_time} seconds ({elapsed}s elapsed).{instance_state_info}\n\n"
        )
        
        error_msg += "=== DIAGNOSTIC INFORMATION ===\n"
        error_msg += f"Network reachable: {network_reachable}\n"
        error_msg += f"Port 22 status: {port_22_status}\n"
        
        if instance_details:
            state = instance_details.get("state", "unknown")
            error_msg += f"Instance state: {state}\n"
            error_msg += f"Instance type: {instance_details.get('instance_type', 'unknown')}\n"
            error_msg += f"Region: {instance_details.get('region', 'unknown')}\n"
            
            if state != "active":
                error_msg += (
                    f"\n⚠️  Instance is in state '{state}', not 'active'. "
                    f"This may indicate the instance is still booting or has encountered an issue.\n"
                )
            else:
                error_msg += (
                    f"\n⚠️  Instance state is 'active' but SSH is not accessible. "
                    f"This may indicate:\n"
                )
                if port_22_status == "closed":
                    error_msg += "  - Port 22 is closed (SSH service may not be running or firewall blocking)\n"
                if network_reachable == "unreachable":
                    error_msg += "  - Network unreachable (instance may not be fully provisioned)\n"
                error_msg += (
                    f"  - SSH service is not running on the instance\n"
                    f"  - SSH key mismatch\n"
                    f"  - Instance is still initializing SSH service\n"
                )
        
        error_msg += (
            f"\n=== TROUBLESHOOTING STEPS ===\n"
            f"1. Check Lambda Labs dashboard: https://cloud.lambdalabs.com/instances\n"
            f"   Look for instance ID: {instance_id if instance_id else 'N/A'}\n"
            f"2. Verify instance is in 'active' state (not 'booting' or 'initializing')\n"
            f"3. Test SSH manually: ssh -i <your-key> ubuntu@{ip_address}\n"
            f"4. Check port connectivity: telnet {ip_address} 22 (or: nc -zv {ip_address} 22)\n"
            f"5. Verify the SSH key name matches what's configured on the instance\n"
            f"6. Lambda Labs instances can take 5-8 minutes to fully boot - wait a bit longer if instance state is still 'booting'\n"
            f"7. Check instance console/logs in Lambda Labs dashboard for boot errors\n"
            f"8. Try terminating and relaunching the instance if it appears stuck\n"
        )
        
        if instance_id:
            error_msg += f"\nInstance ID: {instance_id}\n"
        
        raise TimeoutError(error_msg)
    
    @staticmethod
    def _check_port_open(host: str, port: int, timeout: int = 5) -> bool:
        """Check if a port is open on a remote host (synchronous)."""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    @staticmethod
    def _check_network_reachable(host: str, timeout: int = 5) -> bool:
        """Check if a host is network reachable via ping (synchronous)."""
        import subprocess
        import platform
        try:
            # Use ping with 1 packet and timeout
            if platform.system().lower() == 'windows':
                cmd = ['ping', '-n', '1', '-w', str(timeout * 1000), host]
            else:
                cmd = ['ping', '-c', '1', '-W', str(timeout), host]
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout + 2
            )
            return result.returncode == 0
        except Exception:
            # If ping fails, try a simple socket connection to port 80 or 443
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((host, 80))
                sock.close()
                return result == 0
            except Exception:
                return False
    
    @staticmethod
    async def _check_instance_state(instance_id: str, api_key: str) -> Optional[str]:
        """Check instance state via Lambda Cloud API."""
        try:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            from main import make_lambda_api_request
            
            instance_data = await make_lambda_api_request(
                f"instances/{instance_id}",
                method="GET",
                api_key_override=api_key
            )
            
            instance = instance_data.get("data", {})
            return instance.get("status", {}).get("state")
        except Exception as e:
            logger.debug(f"Failed to check instance state: {str(e)}")
            return None

    @staticmethod
    async def _get_ssh_key(ssh_key_name: str, api_key: str) -> str:
        """Get SSH private key from Lambda Cloud or credential store."""
        # For now, SSH key will be provided by frontend in the request
        # In production, we could fetch from Lambda Cloud API or credential store
        # This is a placeholder - the actual key should come from the orchestration request
        return ""  # Will be provided in orchestration config

    @staticmethod
    async def _trigger_automated_setup(
        session: AsyncSession,
        orchestration_id: UUID,
        ip_address: str,
        ssh_key: str,
        model_name: Optional[str],
    ) -> None:
        """Trigger automated setup with actual commands from user scripts."""
        import os
        telemetry_agent_image = os.getenv("TELEMETRY_AGENT_IMAGE", "allyin/telemetry-agent:latest")
        # Use TELEMETRY_BACKEND_URL if set, otherwise API_BASE_URL, otherwise default
        telemetry_backend_url = os.getenv("TELEMETRY_BACKEND_URL") or os.getenv("API_BASE_URL") or "https://voertx.cloud"
        
        try:
            # Phase 1: Docker Installation
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "setting_up", "setup", 10,
                "Setup phase: Docker Installation..."
            )
            docker_cmd = "curl -fsSL https://get.docker.com | sh"
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=docker_cmd,
                timeout=300,
                check_status=False
            )
            if exit_code != 0:
                logger.warning(f"Docker installation returned exit code {exit_code}: {stderr}")
            else:
                # Add user to docker group
                await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command="sudo usermod -aG docker $USER",
                    timeout=30,
                    check_status=False
                )
            
            # Phase 2: NVIDIA Container Toolkit
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "setting_up", "setup", 25,
                "Setup phase: NVIDIA Container Toolkit..."
            )
            nvidia_toolkit_cmd = (
                "distribution=$(. /etc/os-release;echo $ID$VERSION_ID) && "
                "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | "
                "sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg && "
                "curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | "
                "sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list && "
                "sudo apt update && sudo apt -y install nvidia-container-toolkit && "
                "sudo nvidia-ctk runtime configure --runtime=docker --set-as-default && "
                "sudo systemctl restart docker && "
                "sleep 5"
            )
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=nvidia_toolkit_cmd,
                timeout=300,
                check_status=False
            )
            if exit_code != 0:
                logger.warning(f"NVIDIA Container Toolkit installation returned exit code {exit_code}: {stderr}")
            
            # Verify GPU access in Docker
            logger.info("Verifying GPU access in Docker...")
            gpu_verify_cmd = "sudo docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi --query-gpu=name --format=csv,noheader"
            gpu_verify_stdout, gpu_verify_stderr, gpu_verify_exit = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=gpu_verify_cmd,
                timeout=60,
                check_status=False
            )
            if gpu_verify_exit == 0 and gpu_verify_stdout:
                logger.info(f"GPU access verified in Docker: {gpu_verify_stdout.strip()}")
            else:
                logger.warning(f"GPU access verification failed: {gpu_verify_stderr}. GPUs may not be accessible in containers.")
            
            # Phase 3: Python Environment
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "setting_up", "setup", 40,
                "Setup phase: Python Environment..."
            )
            python_cmd = (
                "sudo apt install -y python3-venv python3-full && "
                "python3 -m venv venv && "
                "source venv/bin/activate && "
                "pip install 'huggingface_hub[cli]' hf-transfer"
            )
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=python_cmd,
                timeout=300,
                check_status=False
            )
            if exit_code != 0:
                logger.warning(f"Python environment setup returned exit code {exit_code}: {stderr}")
            
            # Phase 4: DCGM Installation
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "setting_up", "setup", 55,
                "Setup phase: DCGM Installation..."
            )
            dcgm_cmd = (
                "wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb && "
                "sudo dpkg -i cuda-keyring_1.1-1_all.deb && "
                "sudo apt update && "
                "sudo apt install -y datacenter-gpu-manager && "
                "sudo systemctl start dcgm && "
                "sudo systemctl enable dcgm"
            )
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=dcgm_cmd,
                timeout=300,
                check_status=False
            )
            if exit_code != 0:
                logger.warning(f"DCGM installation returned exit code {exit_code}: {stderr}")
            
            # Phase 5: NVIDIA Driver (may require reboot)
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "setting_up", "setup", 70,
                "Setup phase: NVIDIA Driver Installation..."
            )
            # Check if nvidia-smi works first
            check_driver_cmd = "nvidia-smi > /dev/null 2>&1 && echo 'driver_ok' || echo 'driver_missing'"
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=check_driver_cmd,
                timeout=30,
                check_status=False
            )
            
            if "driver_missing" in stdout:
                driver_cmd = "sudo apt install -y nvidia-driver-570"
                stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=driver_cmd,
                    timeout=600,
                    check_status=False
                )
                if exit_code != 0:
                    logger.warning(f"NVIDIA Driver installation returned exit code {exit_code}: {stderr}")
                # Note: Driver installation may require reboot, but we continue
            
            # Phase 6: Telemetry Agent Installation
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "setting_up", "setup", 85,
                "Setup phase: Telemetry Agent Installation..."
            )
            try:
                agent_cmd = (
                    f"sudo docker run -d --name telemetry-agent --restart unless-stopped "
                    f"--network host --pid host --privileged "
                    f"-v /sys/fs/cgroup:/sys/fs/cgroup:ro "
                    f"-v /var/run/docker.sock:/var/run/docker.sock "
                    f"-e TELEMETRY_BACKEND_URL={telemetry_backend_url} "
                    f"{telemetry_agent_image}"
                )
                
                stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=agent_cmd,
                    timeout=120,
                    check_status=False
                )
                
                if exit_code == 0:
                    logger.info(f"Telemetry agent installed on {ip_address}")
                else:
                    logger.warning(f"Telemetry agent installation returned exit code {exit_code}: {stderr}")
            except Exception as e:
                logger.warning(f"Failed to install telemetry agent: {e}")
            
            # Phase 7: Post-Reboot Verification (check if services are running)
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "setting_up", "setup", 90,
                "Setup phase: Post-Reboot Verification..."
            )
            # Verify Docker is working
            verify_docker = "sudo docker ps > /dev/null 2>&1 && echo 'docker_ok' || echo 'docker_failed'"
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=verify_docker,
                timeout=30,
                check_status=False
            )
            if "docker_ok" not in stdout:
                logger.warning("Docker verification failed after setup")
            
            logger.info(f"Setup completed for instance at {ip_address}")
            
        except Exception as e:
            logger.error(f"Setup phase failed: {e}", exc_info=True)
            raise

    @staticmethod
    async def _deploy_model(
        session: AsyncSession,
        orchestration_id: UUID,
        ip_address: str,
        ssh_key: str,
        model_name: str,
        vllm_config: Dict[str, Any],
    ) -> None:
        """Deploy model via vLLM Docker container using HuggingFace model paths."""
        # model_name should be the HuggingFace model path (e.g., "meta-llama/Meta-Llama-3.1-8B-Instruct")
        # If it's an old format, map it to HuggingFace paths
        hf_model_paths = {
            "Llama3.1-8B": "meta-llama/Meta-Llama-3.1-8B-Instruct",
            "Llama3.1-70B": "meta-llama/Meta-Llama-3.1-70B-Instruct",
            "Llama4-Scout": "RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic",
            "Llama4-Maverick": "meta-llama/Llama-4-Maverick-70B-Instruct",
            "Qwen-32B-Omni": "Qwen/Qwen2.5-32B-Instruct",
            "Mistral-7B": "mistralai/Mistral-7B-Instruct-v0.2",
        }
        
        # Use provided model_name (should be HuggingFace path) or map from old format
        hf_model_path = hf_model_paths.get(model_name, model_name)
        
        # Reliable fallback models that are guaranteed to work (publicly available, standard format)
        RELIABLE_FALLBACK_MODELS = [
            "mistralai/Mistral-7B-Instruct-v0.2",     # Best fallback: publicly available, small, reliable, single GPU
            "Qwen/Qwen2.5-7B-Instruct",               # Alternative fallback: also publicly available
        ]
        
        # Models known to have issues (XET storage, compressed-tensors, gated repos, etc.)
        PROBLEMATIC_MODELS = [
            "RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic",  # Uses XET/compressed-tensors, download issues
            "meta-llama/Meta-Llama-3.1-8B-Instruct",  # Gated repository - requires HuggingFace authentication
        ]
        
        # If requested model is problematic, automatically use fallback
        original_model_path = hf_model_path
        if hf_model_path in PROBLEMATIC_MODELS:
            # Determine issue type based on model name
            if "meta-llama" in hf_model_path.lower():
                issue_desc = "requires HuggingFace authentication (gated repository)"
            elif "XET" in hf_model_path or "compressed-tensors" in hf_model_path.lower():
                issue_desc = "has download/storage issues (XET/compressed-tensors)"
            else:
                issue_desc = "has known issues"
            
            logger.warning(
                f"Model {hf_model_path} {issue_desc}. "
                f"Automatically switching to reliable fallback: {RELIABLE_FALLBACK_MODELS[0]}"
            )
            hf_model_path = RELIABLE_FALLBACK_MODELS[0]
            # Update status to inform user about the automatic switch
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "deploying_model", "model_deploy", 10,
                f"⚠️ Model {original_model_path} {issue_desc}. Automatically using reliable fallback: {hf_model_path}"
            )
        
        # Model-specific configurations for special requirements
        MODEL_CONFIGS = {
            # Smaller models that can run on single GPU (24GB+ VRAM)
            "meta-llama/Meta-Llama-3.1-8B-Instruct": {
                "requires_shm_size": "16g",
                "recommended_max_model_len": 8192,  # Supports up to 128K but 8K is safer for single GPU
                "recommended_max_num_seqs": 64,
                "recommended_gpu_memory_util": 0.90,  # Can use more memory since it's smaller
                "is_moe": False,
                "min_gpu_memory_per_gpu_gb": 20,  # Can run on RTX 4090 (24GB), A10 (24GB), or A100 (40GB)
                "recommended_tensor_parallel": 1,  # Single GPU is sufficient
            },
            "meta-llama/Meta-Llama-3.1-70B-Instruct": {
                "requires_shm_size": "64g",
                "recommended_max_model_len": 8192,
                "recommended_max_num_seqs": 32,
                "recommended_gpu_memory_util": 0.85,
                "is_moe": False,
                "min_gpu_memory_per_gpu_gb": 40,  # Needs A100/H100 (80GB) or multiple GPUs
                "recommended_tensor_parallel": 2,  # Recommended for 70B model
            },
            "RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic": {
                "kv_cache_dtype": "fp8",
                "requires_shm_size": "32g",
                "recommended_max_model_len": 1024,  # Very conservative for FP8 MoE models to avoid OOM
                "recommended_max_num_seqs": 16,  # Further reduced for MoE models to save memory
                "recommended_gpu_memory_util": 0.70,  # Even more conservative (reduced from 0.75) to prevent OOM
                "recommended_tensor_parallel": 2,  # REQUIRED: 17B MoE model needs at least 2 GPUs (can use 4 if available)
                "is_moe": True,  # Mark as MoE model for special handling
                "min_gpu_memory_per_gpu_gb": 20,  # Minimum memory per GPU in GB
            },
            "Qwen/Qwen2.5-7B-Instruct": {
                "requires_shm_size": "16g",
                "recommended_max_model_len": 8192,
                "recommended_max_num_seqs": 64,
                "recommended_gpu_memory_util": 0.90,  # Can use more memory since it's smaller
                "is_moe": False,
                "min_gpu_memory_per_gpu_gb": 15,  # 7B model is smaller, can run on RTX 4090 (24GB), A10 (24GB), or A100 (40GB)
                "recommended_tensor_parallel": 1,  # Single GPU is sufficient
            },
            "Qwen/Qwen2.5-32B-Instruct": {
                "requires_shm_size": "64g",  # Large model needs more shared memory
                "recommended_max_model_len": 32768,  # Supports long context
                "is_moe": False,
                "min_gpu_memory_per_gpu_gb": 30,  # 32B model needs significant memory
                "recommended_tensor_parallel": 4,  # Recommended for 32B model
            },
            "mistralai/Mistral-7B-Instruct-v0.2": {
                "requires_shm_size": "16g",
                "recommended_max_model_len": 8192,
                "recommended_max_num_seqs": 64,
                "recommended_gpu_memory_util": 0.90,  # Can use more memory since it's smaller
                "is_moe": False,
                "min_gpu_memory_per_gpu_gb": 15,  # 7B model is smaller, can run on RTX 4090 (24GB), A10 (24GB), or A100 (40GB)
                "recommended_tensor_parallel": 1,  # Single GPU is sufficient
            },
            "mistralai/Mixtral-8x7B-Instruct-v0.1": {
                "requires_shm_size": "64g",  # MoE model needs more shared memory
                "recommended_max_model_len": 32768,
                "recommended_max_num_seqs": 32,  # Reduced for MoE models
                "recommended_gpu_memory_util": 0.85,  # Conservative for MoE stability
                "is_moe": True,
                "min_gpu_memory_per_gpu_gb": 25,  # MoE model needs more memory
                "recommended_tensor_parallel": 8,  # MoE with 8 experts
            },
            "mistralai/Mixtral-8x22B-Instruct-v0.1": {
                "requires_shm_size": "128g",  # Very large MoE model
                "recommended_max_model_len": 65536,
                "recommended_max_num_seqs": 32,  # Reduced for large MoE models
                "recommended_gpu_memory_util": 0.85,  # Conservative for large MoE stability
                "is_moe": True,
                "min_gpu_memory_per_gpu_gb": 40,  # Large MoE model
                "recommended_tensor_parallel": 8,  # MoE with 8 experts
            },
        }
        
        # Get model-specific config if available
        model_config = MODEL_CONFIGS.get(hf_model_path, {})
        
        # Detect if model uses FP8 quantization (from config or name) - needed early for memory settings
        is_fp8_model = (
            model_config.get("kv_cache_dtype") == "fp8" or
            "FP8" in hf_model_path.upper() or
            "FP8" in model_name.upper()
        )
        
        # Get instance_type from orchestration config if available
        instance_type = None
        try:
            config_stmt = select(InstanceOrchestration.config).where(
                InstanceOrchestration.orchestration_id == orchestration_id
            )
            config_result = await session.execute(config_stmt)
            config_data = config_result.scalar_one_or_none()
            if config_data:
                instance_type = config_data.get("instance_type")
        except Exception as e:
            logger.debug(f"Could not get instance_type from config: {e}")
        
        # Detect GPU information (count, type, memory)
        logger.info(f"Detecting GPU information for instance {ip_address}...")
        gpu_info = await InstanceOrchestrator._detect_gpu_info(
            ip_address, ssh_key, instance_type
        )
        gpu_count = gpu_info.get("gpu_count")
        gpu_type = gpu_info.get("gpu_type")
        gpu_memory_total = gpu_info.get("gpu_memory_total")
        
        # Log detected GPU information
        if gpu_count:
            logger.info(
                f"GPU detection complete: {gpu_count} GPU(s), type: {gpu_type}, "
                f"total memory: {gpu_memory_total} GB" if gpu_memory_total else f"type: {gpu_type}"
            )
        else:
            logger.warning("Could not detect GPU count, will use defaults")
        
        # Store GPU info in orchestration config for reference
        try:
            current_config = config_data or {}
            updated_config = {
                **current_config,
                "gpu_info": gpu_info
            }
            config_update_stmt = update(InstanceOrchestration).where(
                InstanceOrchestration.orchestration_id == orchestration_id
            ).values(config=updated_config)
            await session.execute(config_update_stmt)
            await session.commit()
        except Exception as e:
            logger.debug(f"Could not store GPU info in config: {e}")
        
        # Validate and set tensor-parallel-size
        # Check if model config recommends tensor parallelism
        recommended_tensor_parallel = model_config.get("recommended_tensor_parallel")
        tensor_parallel = vllm_config.get("tensor_parallel_size")
        
        if tensor_parallel is None:
            # Use recommended value from model config, or detected GPU count, or default to 1
            if recommended_tensor_parallel is not None:
                # Use recommended value, but don't exceed available GPUs
                if gpu_count and recommended_tensor_parallel > gpu_count:
                    logger.warning(
                        f"Model recommends tensor-parallel-size {recommended_tensor_parallel} but only {gpu_count} GPUs available. "
                        f"Using {gpu_count} GPUs."
                    )
                    tensor_parallel = gpu_count
                else:
                    tensor_parallel = recommended_tensor_parallel
                    logger.info(f"Using recommended tensor-parallel-size: {tensor_parallel} for {hf_model_path}")
            else:
                # Use detected GPU count, or default to 1 for safety
                tensor_parallel = gpu_count if gpu_count else 1
                logger.info(f"Using tensor-parallel-size: {tensor_parallel} (detected GPUs: {gpu_count})")
        else:
            # User provided value - validate it doesn't exceed available GPUs
            if gpu_count and tensor_parallel > gpu_count:
                logger.warning(
                    f"Requested tensor-parallel-size {tensor_parallel} exceeds available GPUs ({gpu_count}), "
                    f"adjusting to {gpu_count}"
                )
                tensor_parallel = gpu_count
            elif tensor_parallel < 1:
                logger.warning(f"Invalid tensor-parallel-size {tensor_parallel}, using 1")
                tensor_parallel = 1
        
        # Validate GPU memory requirements for the model
        if gpu_memory_total and tensor_parallel:
            memory_per_gpu = gpu_memory_total / tensor_parallel
            logger.info(f"Memory per GPU: {memory_per_gpu:.2f} GB (total: {gpu_memory_total} GB, tensor-parallel: {tensor_parallel})")
            
            # Check model-specific memory requirements
            min_memory_per_gpu = model_config.get("min_gpu_memory_per_gpu_gb")
            if min_memory_per_gpu and memory_per_gpu < min_memory_per_gpu:
                error_msg = (
                    f"Insufficient GPU memory for model {hf_model_path}. "
                    f"Required: {min_memory_per_gpu} GB per GPU, "
                    f"Available: {memory_per_gpu:.2f} GB per GPU. "
                    f"Consider: 1) Using more GPUs (increase tensor-parallel-size), "
                    f"2) Using a smaller model, or 3) Reducing max_model_len."
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Warn if memory is close to minimum
            if min_memory_per_gpu and memory_per_gpu < min_memory_per_gpu * 1.1:
                logger.warning(
                    f"GPU memory is close to minimum requirement for {hf_model_path}. "
                    f"Recommended: {min_memory_per_gpu} GB per GPU, "
                    f"Current: {memory_per_gpu:.2f} GB per GPU. "
                    f"Consider reducing max_model_len or gpu_memory_utilization."
                )
        
        # Apply model-specific configurations with user overrides
        # Use recommended values from MODEL_CONFIGS, but allow user overrides
        recommended_max_model_len = model_config.get("recommended_max_model_len")
        is_moe = model_config.get("is_moe", False)
        
        # Set max_model_len: user override > model config recommended > default
        # Use recommended values from MODEL_CONFIGS if available
        recommended_max_num_seqs = model_config.get("recommended_max_num_seqs")
        recommended_gpu_memory_util = model_config.get("recommended_gpu_memory_util")
        
        if is_fp8_model or is_moe:
            # FP8 and MoE models need more conservative settings
            # FORCE recommended values for safety (user can override if needed, but defaults are conservative)
            if recommended_max_model_len is not None:
                # Use recommended value unless user explicitly provided a different one
                max_model_len = vllm_config.get("max_model_len")
                if max_model_len is None or max_model_len > recommended_max_model_len:
                    max_model_len = recommended_max_model_len
                    logger.info(f"Using conservative max_model_len={max_model_len} for {hf_model_path} (recommended for FP8/MoE)")
            else:
                default_max_model_len = 2048
                max_model_len = vllm_config.get("max_model_len", default_max_model_len)
            
            # Use recommended max_num_seqs from config, or default based on model type
            if recommended_max_num_seqs is not None:
                # Use recommended value unless user explicitly provided a different one
                max_num_seqs = vllm_config.get("max_num_seqs")
                if max_num_seqs is None or max_num_seqs > recommended_max_num_seqs:
                    max_num_seqs = recommended_max_num_seqs
                    logger.info(f"Using conservative max_num_seqs={max_num_seqs} for {hf_model_path} (recommended for FP8/MoE)")
            else:
                default_max_num_seqs = 32 if is_moe else 48
                max_num_seqs = vllm_config.get("max_num_seqs", default_max_num_seqs)
            
            # Use recommended gpu_memory_util from config, or conservative default
            if recommended_gpu_memory_util is not None:
                # Use recommended value unless user explicitly provided a lower one
                gpu_memory_util = vllm_config.get("gpu_memory_utilization")
                if gpu_memory_util is None or gpu_memory_util > recommended_gpu_memory_util:
                    gpu_memory_util = recommended_gpu_memory_util
                    logger.info(f"Using conservative gpu_memory_utilization={gpu_memory_util} for {hf_model_path} (recommended for FP8/MoE)")
            else:
                default_gpu_memory_util = 0.80 if is_fp8_model else 0.85
                gpu_memory_util = vllm_config.get("gpu_memory_utilization", default_gpu_memory_util)
        else:
            # Standard models can use more aggressive settings
            default_max_model_len = recommended_max_model_len if recommended_max_model_len else 4096
            max_model_len = vllm_config.get("max_model_len", default_max_model_len)
            
            # Use recommended values from config if available
            default_max_num_seqs = recommended_max_num_seqs if recommended_max_num_seqs is not None else 64
            max_num_seqs = vllm_config.get("max_num_seqs", default_max_num_seqs)
            
            default_gpu_memory_util = recommended_gpu_memory_util if recommended_gpu_memory_util is not None else 0.90
            gpu_memory_util = vllm_config.get("gpu_memory_utilization", default_gpu_memory_util)
        
        # FP8 models should use enforce-eager by default (required for compatibility)
        enforce_eager = vllm_config.get("enforce_eager", True if is_fp8_model else False)
        
        # Log final configuration
        logger.info(
            f"Model configuration: max_model_len={max_model_len}, "
            f"max_num_seqs={max_num_seqs}, gpu_memory_util={gpu_memory_util}, "
            f"enforce_eager={enforce_eager}, is_fp8={is_fp8_model}, is_moe={is_moe}"
        )

        # Log deployment start with GPU information
        logger.info(
            f"Starting model deployment: {hf_model_path} on {ip_address}. "
            f"GPU info: {gpu_count} GPU(s), type: {gpu_type}, "
            f"memory: {gpu_memory_total} GB" if gpu_memory_total else f"type: {gpu_type}"
        )
        
        # Initial deployment message
        await InstanceOrchestrator._update_status(
            session, orchestration_id, "deploying_model", "model_deploy", 90,
            f"Starting deployment of {hf_model_path} on {gpu_count} GPU(s) ({gpu_type})..."
        )
        
        # Verify SSH connection before attempting deployment
        await InstanceOrchestrator._update_status(
            session, orchestration_id, "deploying_model", "model_deploy", 90,
            f"Verifying SSH connection to {ip_address}..."
        )
        
        # Retry SSH connection with exponential backoff
        max_retries = 5  # Increased from 3 to 5
        retry_delay = 10  # Increased from 5 to 10 seconds
        ssh_verified = False
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Simple connection test
                test_cmd = "echo 'SSH connection test'"
                stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=test_cmd,
                    timeout=60,  # Increased timeout
                    check_status=False
                )
                if exit_code == 0:
                    ssh_verified = True
                    logger.info(f"SSH connection verified to {ip_address} on attempt {attempt + 1}")
                    break
            except Exception as e:
                last_error = str(e)
                logger.warning(f"SSH connection attempt {attempt + 1}/{max_retries} failed: {str(e)}")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    logger.info(f"Retrying SSH connection in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
        
        if not ssh_verified:
            error_msg = (
                f"Unable to establish SSH connection to {ip_address} after {max_retries} attempts.\n"
                f"Last error: {last_error}\n"
                f"Please verify:\n"
                f"  1) The instance is running and fully booted\n"
                f"  2) Port 22 (SSH) is open in the firewall/security group\n"
                f"  3) The SSH key is correct and matches the instance\n"
                f"  4) The instance IP address hasn't changed\n"
                f"  5) The instance is accessible from this network"
            )
            raise RuntimeError(error_msg)

        try:
            # Pre-flight checks: Verify system is ready
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "deploying_model", "model_deploy", 91,
                f"Verifying system readiness..."
            )
            
            # Check GPU availability
            gpu_check_cmd = "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1"
            gpu_stdout, gpu_stderr, gpu_exit = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=gpu_check_cmd,
                timeout=30,
                check_status=False
            )
            if gpu_exit != 0 or not gpu_stdout:
                raise RuntimeError(f"GPU not available or nvidia-smi failed: {gpu_stderr}")
            logger.info(f"GPU check passed: {gpu_stdout.strip()}")
            
            # Check Docker is running
            docker_check_cmd = "sudo docker ps > /dev/null 2>&1 && echo 'docker_ok' || echo 'docker_failed'"
            docker_stdout, _, docker_exit = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=docker_check_cmd,
                timeout=30,
                check_status=False
            )
            if "docker_ok" not in docker_stdout:
                raise RuntimeError("Docker is not running or not accessible")
            logger.info("Docker check passed")
            
            # Verify NVIDIA Container Toolkit is installed and configured
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "deploying_model", "model_deploy", 91,
                f"Verifying NVIDIA runtime..."
            )
            
            # Check if NVIDIA runtime is available
            nvidia_runtime_check_cmd = "sudo docker info 2>/dev/null | grep -i 'runtimes.*nvidia' || echo 'nvidia_not_found'"
            nvidia_runtime_stdout, _, _ = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=nvidia_runtime_check_cmd,
                timeout=30,
                check_status=False
            )
            
            if 'nvidia' not in nvidia_runtime_stdout.lower():
                logger.warning("NVIDIA runtime not found in Docker. Attempting to configure...")
                # Try to configure NVIDIA runtime
                configure_cmd = (
                    "sudo nvidia-ctk runtime configure --runtime=docker --set-as-default && "
                    "sudo systemctl restart docker && "
                    "sleep 5"
                )
                configure_stdout, configure_stderr, configure_exit = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=configure_cmd,
                    timeout=120,
                    check_status=False
                )
                
                if configure_exit != 0:
                    error_msg = (
                        f"NVIDIA Container Toolkit is not properly configured. "
                        f"Please ensure NVIDIA Container Toolkit is installed and configured. "
                        f"Error: {configure_stderr}"
                    )
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)
                
                logger.info("NVIDIA runtime configured successfully")
            else:
                logger.info("NVIDIA runtime verified in Docker")
            
            # Test GPU access in Docker
            gpu_docker_test_cmd = "sudo docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi --query-gpu=name --format=csv,noheader | head -1"
            gpu_docker_stdout, gpu_docker_stderr, gpu_docker_exit = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=gpu_docker_test_cmd,
                timeout=60,
                check_status=False
            )
            
            if gpu_docker_exit != 0 or not gpu_docker_stdout:
                # Check if this is a driver/library version mismatch error
                if "driver/library version mismatch" in gpu_docker_stderr or "nvml error" in gpu_docker_stderr.lower():
                    logger.warning("Detected NVIDIA driver/library version mismatch. Attempting to fix...")
                    
                    # Try to restart nvidia-container-runtime service
                    restart_cmd = "sudo systemctl restart nvidia-container-runtime 2>&1 || sudo service nvidia-container-runtime restart 2>&1 || true"
                    restart_stdout, restart_stderr, restart_exit = await SSHExecutor.execute_remote_command(
                        ssh_host=ip_address,
                        ssh_user="ubuntu",
                        ssh_key=ssh_key,
                        command=restart_cmd,
                        timeout=30,
                        check_status=False
                    )
                    
                    # Also try to reload the nvidia-container-toolkit
                    reload_cmd = "sudo systemctl daemon-reload && sudo systemctl restart docker 2>&1 || true"
                    reload_stdout, reload_stderr, reload_exit = await SSHExecutor.execute_remote_command(
                        ssh_host=ip_address,
                        ssh_user="ubuntu",
                        ssh_key=ssh_key,
                        command=reload_cmd,
                        timeout=30,
                        check_status=False
                    )
                    
                    logger.info("Restarted nvidia-container-runtime and Docker. Retrying GPU access test...")
                    
                    # Wait a moment for services to restart
                    await asyncio.sleep(5)
                    
                    # Retry the GPU access test
                    gpu_docker_stdout_retry, gpu_docker_stderr_retry, gpu_docker_exit_retry = await SSHExecutor.execute_remote_command(
                        ssh_host=ip_address,
                        ssh_user="ubuntu",
                        ssh_key=ssh_key,
                        command=gpu_docker_test_cmd,
                        timeout=60,
                        check_status=False
                    )
                    
                    if gpu_docker_exit_retry == 0 and gpu_docker_stdout_retry:
                        logger.info(f"GPU access verified after restart: {gpu_docker_stdout_retry.strip()}")
                        gpu_docker_stdout = gpu_docker_stdout_retry
                        gpu_docker_exit = gpu_docker_exit_retry
                    else:
                        # If retry failed, suggest reboot
                        error_msg = (
                            f"GPU access test in Docker failed due to driver/library version mismatch. "
                            f"Attempted to restart nvidia-container-runtime but issue persists. "
                            f"The instance may need a reboot. "
                            f"Error: {gpu_docker_stderr_retry or gpu_docker_stderr}\n\n"
                            f"To fix manually:\n"
                            f"1. SSH into the instance: ssh ubuntu@{ip_address}\n"
                            f"2. Reboot: sudo reboot\n"
                            f"3. Wait 2-3 minutes for instance to come back online\n"
                            f"4. Retry model deployment"
                        )
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)
                else:
                    error_msg = (
                        f"GPU access test in Docker failed. GPUs may not be accessible in containers. "
                        f"Please verify NVIDIA Container Toolkit is properly installed. "
                        f"Error: {gpu_docker_stderr}"
                    )
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)
            
            logger.info(f"GPU access in Docker verified: {gpu_docker_stdout.strip()}")
            
            # Step 1: Pull vLLM Docker image (if not already pulled)
            # Pin to stable vLLM version without v1 engine issues
            # v0.11.0 has a bug: setting VLLM_USE_V1=0 causes AssertionError
            # v0.11.0 requires VLLM_USE_V1 to be truthy, so we can't disable v1 engine
            # Solution: Use older versions (v0.10.x or v0.9.x) that don't have v1 engine
            # Prioritize v0.10.x versions which have better NVML handling and avoid initialization bugs
            # v0.9.2 has a known NVML initialization issue (NVMLError_Unknown) that causes crashes
            # Skip v0.9.2 entirely and prefer v0.10.x or other v0.9.x versions
            vllm_image_tags = [
                "vllm/vllm-openai:v0.10.5",  # Newer stable version with better NVML handling
                "vllm/vllm-openai:v0.10.4",  # Newer stable version
                "vllm/vllm-openai:v0.10.3",  # Newer stable version
                "vllm/vllm-openai:v0.10.2",  # Newer stable version
                "vllm/vllm-openai:v0.9.5",  # Fallback: newer v0.9.x (avoid v0.9.2 due to NVML bug)
                "vllm/vllm-openai:v0.9.4",  # Fallback: newer v0.9.x
                "vllm/vllm-openai:v0.9.3",  # Fallback: newer v0.9.x
                "vllm/vllm-openai:v0.9.1",  # Fallback: older stable (skip v0.9.2 - has NVML bug)
                "vllm/vllm-openai:v0.9.0",  # Fallback: older stable
                "vllm/vllm-openai:latest"     # Last resort: latest (may have v1 engine issues)
            ]
            
            vllm_image_tag = None
            for tag in vllm_image_tags:
                await InstanceOrchestrator._update_status(
                    session, orchestration_id, "deploying_model", "model_deploy", 92,
                    f"Pulling vLLM Docker image ({tag})..."
                )
                
                pull_cmd = f"sudo docker pull {tag}"
                stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=pull_cmd,
                    timeout=600,  # 10 minutes for image pull
                    check_status=False
                )
                
                if exit_code == 0:
                    vllm_image_tag = tag
                    logger.info(f"Successfully pulled vLLM image: {tag}")
                    break
                else:
                    # Log the actual error from stderr to understand why pull failed
                    error_detail = stderr[-500:] if stderr else "No error details"
                    logger.warning(f"Failed to pull {tag} (exit code {exit_code}): {error_detail[:200]}...")
                    # Continue to next version
            
            if not vllm_image_tag:
                # All versions failed, use latest as fallback
                vllm_image_tag = "vllm/vllm-openai:latest"
                logger.warning(f"All pinned versions failed, using {vllm_image_tag} as fallback")
            
            # Step 2: Stop and remove any existing vLLM container
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "deploying_model", "model_deploy", 94,
                f"Preparing for model deployment..."
            )
            
            cleanup_cmd = "sudo docker rm -f vllm 2>/dev/null || true"
            await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=cleanup_cmd,
                timeout=30,
                check_status=False
            )
            
            # Step 3: Deploy vLLM container with model
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "deploying_model", "model_deploy", 96,
                f"Starting vLLM container with model {hf_model_path}..."
            )
            
            # Build vLLM docker command using HuggingFace model path
            # Remove --rm flag so we can inspect logs if container fails
            # Determine shared memory size (use model config or default)
            shm_size = model_config.get("requires_shm_size", "32g")
            
            docker_cmd_parts = [
                "sudo docker run -d --gpus all --name vllm",
                "--restart unless-stopped",  # Auto-restart on failure
                f"--shm-size={shm_size}",  # Required for vLLM shared memory
                "-p 8000:8000",
                "-e NVIDIA_VISIBLE_DEVICES=all",  # Make all GPUs visible to container
                "-e NVIDIA_DRIVER_CAPABILITIES=compute,utility",  # Required GPU capabilities (include utility for NVML)
                "-e PYTORCH_ALLOC_CONF=expandable_segments:True",  # Reduce memory fragmentation
                "-e VLLM_WORKER_MULTIPROC_METHOD=spawn",  # Use spawn method for multiprocessing (more stable)
                "-e VLLM_TARGET_DEVICE=cuda",  # Explicitly target CUDA
                "-e VLLM_LOGGING_LEVEL=INFO",  # Use INFO instead of DEBUG to reduce NVML warnings
                "-e VLLM_USE_V1=0",  # Use v0 engine (more stable, avoids NVML initialization issues in v1)
            ]
            
            # v0.11.0 has a bug: setting VLLM_USE_V1=0 causes AssertionError
            # v0.11.0's code has: assert envs.VLLM_USE_V1 (requires it to be truthy)
            # So we can't disable v1 engine in v0.11.0 via environment variable
            # We skip v0.11.0 entirely and use older versions (v0.10.x or v0.9.x)
            # For v0.9.x versions, we use VLLM_USE_V1=0 to avoid NVML initialization issues
            # For latest, we don't set VLLM_USE_V1=0 to avoid the assertion error
            if "v0.11.0" in vllm_image_tag:
                logger.error(f"v0.11.0 has a bug with VLLM_USE_V1=0. This should not happen as v0.11.0 is skipped.")
            elif "v0.9" in vllm_image_tag or "v0.10" in vllm_image_tag:
                # v0.9.x and v0.10.x versions work better with VLLM_USE_V1=0 (v0 engine)
                # This avoids NVML initialization issues that occur in v1 engine
                logger.info(f"Using {vllm_image_tag} with VLLM_USE_V1=0 (v0 engine) to avoid NVML issues")
            elif "latest" in vllm_image_tag:
                logger.warning(f"Using {vllm_image_tag} - v1 engine will be enabled by default (may cause issues)")
            
            docker_cmd_parts.append(vllm_image_tag)  # Use pinned stable version or fallback
            docker_cmd_parts.extend([
                f"--model {hf_model_path}",
                f"--tokenizer {hf_model_path}",  # Explicitly set tokenizer path (as per user's working config)
                "--trust-remote-code",
                f"--tensor-parallel-size {tensor_parallel}",
                "--dtype auto",
                f"--max-model-len {max_model_len}",
                f"--max-num-seqs {max_num_seqs}",
                f"--gpu-memory-utilization {gpu_memory_util}",
                "--host 0.0.0.0 --port 8000",
                "--uvicorn-log-level info",
                "--disable-log-requests"  # Reduce logging overhead during initialization
            ])
            
            # For tensor parallelism > 1, use Ray backend for distributed execution
            if tensor_parallel > 1:
                docker_cmd_parts.append("--distributed-executor-backend ray")
                logger.info(f"Using Ray backend for tensor parallelism with {tensor_parallel} GPUs")
            
            # Always use enforce-eager for stability (avoids CUDA graph issues and NVML problems)
            # This is especially important for v0.9.2 which has NVML initialization issues
            docker_cmd_parts.append("--enforce-eager")
            logger.info("Using --enforce-eager for stability (avoids CUDA graph and NVML issues)")
            
            # For FP8 models: don't set kv-cache-dtype (vLLM auto-detects it)
            if is_fp8_model:
                logger.info(f"Detected FP8 model, kv-cache-dtype will be auto-detected")
            
            # Note: vLLM v1 engine uses EngineCoreClient which may have initialization issues
            # The latest vllm/vllm-openai:latest image uses v1 by default
            # If initialization fails, consider:
            # 1. Using an older image tag (e.g., vllm/vllm-openai:v0.6.0)  
            # 2. Reducing max-model-len or gpu-memory-utilization
            # 3. Checking GPU memory availability
            logger.info("Using vLLM (latest image, typically v1 API)")
            
            docker_cmd = " ".join(docker_cmd_parts)
            
            logger.info(
                f"Starting vLLM container with model {hf_model_path} "
                f"(tensor-parallel-size: {tensor_parallel}, max-model-len: {max_model_len}, "
                f"gpu-memory-util: {gpu_memory_util}, shm-size: {shm_size})"
            )
            
            # Clean up any existing container first
            cleanup_cmd = "sudo docker rm -f vllm 2>/dev/null || true"
            await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=cleanup_cmd,
                timeout=30,
                check_status=False
            )
            
            # Pre-flight check: Verify GPU is accessible in the vLLM container environment
            logger.info("Verifying GPU accessibility in vLLM container environment...")
            gpu_verify_cmd = (
                f"sudo docker run --rm --gpus all "
                f"-e NVIDIA_VISIBLE_DEVICES=all "
                f"-e NVIDIA_DRIVER_CAPABILITIES=compute,utility "
                f"{vllm_image_tag} "
                f"python -c 'import torch; print(f\"CUDA available: {{torch.cuda.is_available()}}\"); "
                f"print(f\"CUDA devices: {{torch.cuda.device_count()}}\"); "
                f"import sys; sys.exit(0 if torch.cuda.is_available() else 1)'"
            )
            gpu_verify_stdout, gpu_verify_stderr, gpu_verify_exit = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=gpu_verify_cmd,
                timeout=120,
                check_status=False
            )
            
            if gpu_verify_exit != 0:
                logger.warning(
                    f"GPU verification in vLLM container failed. Output: {gpu_verify_stdout}, "
                    f"Error: {gpu_verify_stderr}. Continuing with deployment anyway..."
                )
            else:
                logger.info(f"GPU verification successful: {gpu_verify_stdout.strip()}")
            
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=docker_cmd,
                timeout=600,  # 10 minutes for container start
                check_status=False
            )

            if exit_code != 0:
                error_msg = f"Failed to start vLLM container. Exit code: {exit_code}"
                if stderr:
                    error_msg += f"\nStderr: {stderr[-500:]}"
                if stdout:
                    error_msg += f"\nStdout: {stdout[-500:]}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Verify container is actually running with multiple checks
            # Increased initial wait time to allow container to start and begin initialization
            container_running = False
            max_checks = 3
            for check_attempt in range(max_checks):
                # Wait longer on first check to allow container to start
                wait_time = 10 if check_attempt == 0 else 3
                await asyncio.sleep(wait_time)
                
                # Check for engine core errors in logs before checking status
                # This helps catch initialization failures early
                logs_check_cmd = "sudo docker logs vllm 2>&1 | tail -50"
                logs_stdout, logs_stderr, _ = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=logs_check_cmd,
                    timeout=30,
                    check_status=False
                )
                
                # Check for common error patterns that indicate initialization failure
                if logs_stdout:
                    error_patterns = [
                        "Engine core initialization failed",
                        "RuntimeError",
                        "CUDA out of memory",
                        "OOM",
                        "out of memory",
                        "Failed core proc",
                        "initialization failed",
                        "Failed to infer device type",  # Device detection failure
                        "device type",  # Catch device-related errors
                    ]
                    if any(pattern in logs_stdout for pattern in error_patterns):
                        # Container is failing - capture full error logs with better diagnostics
                        full_logs_cmd = "sudo docker logs vllm 2>&1"
                        full_logs_stdout, _, _ = await SSHExecutor.execute_remote_command(
                            ssh_host=ip_address,
                            ssh_user="ubuntu",
                            ssh_key=ssh_key,
                            command=full_logs_cmd,
                            timeout=30,
                            check_status=False
                        )
                        
                        # Also check system resources and GPU status
                        gpu_check_cmd = "nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader"
                        gpu_status, _, _ = await SSHExecutor.execute_remote_command(
                            ssh_host=ip_address,
                            ssh_user="ubuntu",
                            ssh_key=ssh_key,
                            command=gpu_check_cmd,
                            timeout=30,
                            check_status=False
                        )
                        
                        error_msg = "Container started but engine core initialization failed.\n\n"
                        error_msg += "=== DIAGNOSTIC INFORMATION ===\n"
                        
                        if gpu_status:
                            error_msg += f"GPU Status:\n{gpu_status}\n\n"
                        
                        error_msg += "=== CONTAINER LOGS ===\n"
                        if full_logs_stdout:
                            # Extract the actual error traceback if present
                            lines = full_logs_stdout.split('\n')
                            error_section_start = None
                            for i, line in enumerate(lines):
                                if any(pattern.lower() in line.lower() for pattern in error_patterns):
                                    error_section_start = max(0, i - 20)  # Include 20 lines before error
                                    break
                            
                            if error_section_start is not None:
                                error_section = '\n'.join(lines[error_section_start:])
                                error_msg += f"Error section:\n{error_section}\n\n"
                            else:
                                # Get last 3000 chars of logs for debugging
                                error_msg += f"Last 3000 characters of logs:\n{full_logs_stdout[-3000:]}\n"
                        else:
                            error_msg += "No logs available. Container may have crashed immediately.\n"
                        
                        error_msg += "\n=== TROUBLESHOOTING SUGGESTIONS ===\n"
                        error_msg += "1. Check GPU memory availability (nvidia-smi)\n"
                        error_msg += "2. Verify NVIDIA drivers and CUDA are properly installed\n"
                        error_msg += "3. Check if other processes are using GPU memory\n"
                        error_msg += "4. Try reducing max-model-len or gpu-memory-utilization\n"
                        error_msg += "5. Ensure sufficient shared memory (--shm-size)\n"
                        error_msg += "6. Check Docker logs: sudo docker logs vllm\n"
                        
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)
                
                check_cmd = "sudo docker ps --filter name=vllm --format '{{.Status}}'"
                check_stdout, check_stderr, check_exit = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=check_cmd,
                    timeout=30,
                    check_status=False
                )
                
                if check_stdout and "Up" in check_stdout:
                    container_running = True
                    logger.info(f"Container verified running: {check_stdout.strip()}")
                    break
                else:
                    logger.warning(f"Container check {check_attempt + 1}/{max_checks}: Not running yet")
            
            if not container_running:
                # Container started but immediately exited - get logs before it's removed
                logs_cmd = "sudo docker logs vllm 2>&1 || sudo docker ps -a --filter name=vllm --format '{{.Status}}'"
                logs_stdout, logs_stderr, _ = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=logs_cmd,
                    timeout=30,
                    check_status=False
                )
                
                error_msg = f"Container started but immediately exited or failed to start.\n"
                if logs_stdout:
                    # Get last 1000 chars of logs for debugging
                    error_msg += f"Container logs/status:\n{logs_stdout[-1000:]}"
                else:
                    error_msg += "No logs available. Container may have crashed immediately."
                
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Container is running successfully
            logger.info(f"vLLM container started successfully on {ip_address}")
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "deploying_model", "model_deploy", 97,
                f"Container started. Downloading model {hf_model_path} from HuggingFace (this may take 10-15 minutes)..."
            )
            
            # Wait for model to be ready by checking vLLM health endpoint
            # The model download and loading happens inside the container
            max_wait_time = 1800  # 30 minutes total wait time
            check_interval = 30  # Check every 30 seconds
            elapsed = 0
            model_ready = False
            
            # Log that we're starting health checks
            logger.info(f"Starting health check loop for model {hf_model_path} on {ip_address}:8000 (checking every {check_interval}s, max wait: {max_wait_time // 60} minutes)")
            model_download_timeout = 900  # 15 minutes for model download (if stuck, likely download issue)
            last_progress_time = 0  # Track when we last saw progress
            # Check container more frequently in early phase (first 10 minutes) to catch crashes quickly
            container_check_interval = 60  # Check every 1 minute initially (reduced from 300)
            container_check_interval_long = 300  # Use 5 minutes after first 10 minutes
            last_container_check = -60  # Start at -60 so first check happens immediately
            early_phase_duration = 600  # First 10 minutes use shorter interval
            
            while elapsed < max_wait_time:
                # Check container more frequently in early phase when crashes are most likely
                current_check_interval = container_check_interval if elapsed < early_phase_duration else container_check_interval_long
                
                # Periodically verify container is still running
                if elapsed - last_container_check >= current_check_interval:
                    try:
                        check_cmd = "sudo docker ps --filter name=vllm --format '{{.Status}}'"
                        check_stdout, _, _ = await SSHExecutor.execute_remote_command(
                            ssh_host=ip_address,
                            ssh_user="ubuntu",
                            ssh_key=ssh_key,
                            command=check_cmd,
                            timeout=30,
                            check_status=False
                        )
                        if not check_stdout or "Up" not in check_stdout:
                            # Container died - get logs
                            logs_cmd = "sudo docker logs --tail 100 vllm 2>&1"
                            logs_stdout, _, _ = await SSHExecutor.execute_remote_command(
                                ssh_host=ip_address,
                                ssh_user="ubuntu",
                                ssh_key=ssh_key,
                                command=logs_cmd,
                                timeout=30,
                                check_status=False
                            )
                            error_msg = f"Container stopped running during model loading (after {elapsed // 60} minutes).\n"
                            if logs_stdout:
                                error_msg += f"Last 100 lines of logs:\n{logs_stdout[-2000:]}"
                            else:
                                error_msg += "No logs available."
                            logger.error(error_msg)
                            raise RuntimeError(error_msg)
                        
                        # Also check logs for actual error patterns during waiting
                        # Only check if container is still running (to avoid false positives)
                        if check_stdout and "Up" in check_stdout:
                            logs_check_cmd = "sudo docker logs vllm 2>&1 | tail -100"
                            logs_stdout, _, _ = await SSHExecutor.execute_remote_command(
                                ssh_host=ip_address,
                                ssh_user="ubuntu",
                                ssh_key=ssh_key,
                                command=logs_check_cmd,
                                timeout=30,
                                check_status=False
                            )
                            
                            if logs_stdout:
                                # Check for stuck model download (waiting for core engine processes for too long)
                                stuck_download_patterns = [
                                    "Waiting for 1 local, 0 remote core engine proc",
                                    ".no_exist",  # HuggingFace couldn't find model files
                                    "XET",  # XET storage issues
                                    "compressed-tensors",  # Compressed tensors download issues
                                ]
                                
                                # If stuck for more than 10 minutes and showing stuck patterns, try fallback
                                if elapsed > 600 and any(pattern in logs_stdout for pattern in stuck_download_patterns):
                                    if hf_model_path != RELIABLE_FALLBACK_MODELS[0] and hf_model_path == original_model_path:
                                        logger.warning(
                                            f"Model {hf_model_path} appears stuck downloading (detected after {elapsed // 60} minutes). "
                                            f"Automatically switching to reliable fallback: {RELIABLE_FALLBACK_MODELS[0]}"
                                        )
                                        # Stop current container
                                        stop_cmd = "sudo docker rm -f vllm 2>/dev/null || true"
                                        await SSHExecutor.execute_remote_command(
                                            ssh_host=ip_address,
                                            ssh_user="ubuntu",
                                            ssh_key=ssh_key,
                                            command=stop_cmd,
                                            timeout=30,
                                            check_status=False
                                        )
                                        # Update model path to fallback and retry
                                        hf_model_path = RELIABLE_FALLBACK_MODELS[0]
                                        model_config = MODEL_CONFIGS.get(hf_model_path, {})
                                        # Restart deployment with fallback model (will be handled by retry logic)
                                        raise RuntimeError(
                                            f"Model {original_model_path} download stuck. "
                                            f"Automatically switching to reliable fallback: {hf_model_path}. "
                                            f"Please retry deployment."
                                        )
                                
                                # More specific error patterns - only flag actual fatal errors
                                # Ignore expected warnings like Gloo messages, INFO logs, etc.
                                fatal_error_patterns = [
                                    "Engine core initialization failed",
                                    "CUDA out of memory",
                                    "CUDA error",
                                    "out of memory",
                                    "OOM",
                                    "Failed core proc",
                                    "FATAL",
                                    "Traceback (most recent call last)",
                                    "Exception:",
                                    "Error:",
                                    "failed to initialize",
                                    "initialization failed",
                                ]
                                
                                # Ignore expected warnings/patterns that are not errors
                                ignore_patterns = [
                                    "[Gloo]",  # Expected Gloo warnings for single-GPU
                                    "Rank 0 is connected to 0 peer ranks",  # Expected for single GPU
                                    "INFO",  # Info messages
                                    "WARNING",  # Warnings (not fatal)
                                    "DEBUG",  # Debug messages
                                ]
                                
                                # Check if log contains fatal errors (but ignore expected warnings)
                                log_lower = logs_stdout.lower()
                                has_fatal_error = any(
                                    pattern.lower() in log_lower 
                                    for pattern in fatal_error_patterns
                                )
                                
                                # Only raise error if we have a fatal error AND it's not just a warning
                                if has_fatal_error:
                                    # Double-check: make sure it's not just a warning by looking for actual error context
                                    # Look for error patterns that are clearly fatal (not just mentions)
                                    lines = logs_stdout.split('\n')
                                    fatal_lines = [
                                        line for line in lines
                                        if any(
                                            pattern.lower() in line.lower() 
                                            for pattern in fatal_error_patterns
                                        )
                                        and not any(
                                            ignore.lower() in line.lower() 
                                            for ignore in ignore_patterns
                                        )
                                    ]
                                    
                                    # Only raise if we found actual fatal error lines (not just warnings)
                                    if fatal_lines:
                                        # Get FULL error logs - need more context to find root cause
                                        # The "Engine core initialization failed" message says "See root cause above"
                                        # So we need to capture much more to see the actual error
                                        full_logs_cmd = "sudo docker logs vllm 2>&1 | tail -500"
                                        full_logs_stdout, _, _ = await SSHExecutor.execute_remote_command(
                                            ssh_host=ip_address,
                                            ssh_user="ubuntu",
                                            ssh_key=ssh_key,
                                            command=full_logs_cmd,
                                            timeout=30,
                                            check_status=False
                                        )
                                        
                                        # Also try to get the FULL logs to a file for analysis
                                        save_logs_cmd = "sudo docker logs vllm 2>&1 > /tmp/vllm_full_error.log 2>&1"
                                        await SSHExecutor.execute_remote_command(
                                            ssh_host=ip_address,
                                            ssh_user="ubuntu",
                                            ssh_key=ssh_key,
                                            command=save_logs_cmd,
                                            timeout=30,
                                            check_status=False
                                        )
                                        
                                        # Also check GPU status when error occurs
                                        gpu_check_cmd = "nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader"
                                        gpu_status, _, _ = await SSHExecutor.execute_remote_command(
                                            ssh_host=ip_address,
                                            ssh_user="ubuntu",
                                            ssh_key=ssh_key,
                                            command=gpu_check_cmd,
                                            timeout=30,
                                            check_status=False
                                        )
                                        
                                        # Check if this is a v1 engine error that we can recover from
                                        is_v1_engine_error = any(
                                            "v1/engine" in line.lower() or 
                                            "engine core initialization failed" in line.lower() or
                                            "vllm v1" in line.lower()
                                            for line in fatal_lines
                                        )
                                        
                                        # Check if this is an OOM (Out of Memory) error
                                        is_oom_error = any(
                                            "out of memory" in line.lower() or
                                            "cuda out of memory" in line.lower() or
                                            "oom" in line.lower()
                                            for line in fatal_lines
                                        )
                                        
                                        error_msg = f"Container error detected during model loading (after {elapsed // 60} minutes).\n\n"
                                        error_msg += "=== FATAL ERROR DETECTED ===\n"
                                        error_msg += "\n".join(fatal_lines[-15:])  # Show last 15 fatal error lines
                                        
                                        if gpu_status:
                                            error_msg += f"\n\n=== GPU STATUS AT TIME OF ERROR ===\n{gpu_status}\n"
                                        
                                        if full_logs_stdout:
                                            # Extract the actual root cause error
                                            # Look for errors BEFORE "Engine core initialization failed"
                                            log_lines = full_logs_stdout.split('\n')
                                            root_cause_found = False
                                            root_cause_section = []
                                            
                                            # Look backwards from "Engine core initialization failed" to find the real error
                                            for i in range(len(log_lines) - 1, -1, -1):
                                                line = log_lines[i]
                                                if "Engine core initialization failed" in line or "RuntimeError" in line:
                                                    # Found the generic error, now look backwards for the real cause
                                                    # Look for: OOM, CUDA error, ImportError, AttributeError, etc.
                                                    for j in range(i - 1, max(0, i - 100), -1):
                                                        prev_line = log_lines[j]
                                                        if any(pattern in prev_line for pattern in [
                                                            "OutOfMemoryError", "CUDA out of memory", "OOM",
                                                            "CUDA error", "RuntimeError", "ImportError", "AttributeError",
                                                            "ModuleNotFoundError", "FileNotFoundError", "ValueError",
                                                            "torch.OutOfMemoryError", "NCCL error", "distributed"
                                                        ]):
                                                            # Found potential root cause - capture surrounding context
                                                            root_cause_section = log_lines[max(0, j-20):min(len(log_lines), j+10)]
                                                            root_cause_found = True
                                                            break
                                                    if root_cause_found:
                                                        break
                                            
                                            error_msg += f"\n\n=== RECENT CONTAINER LOGS (last 500 lines) ===\n"
                                            if root_cause_section:
                                                error_msg += "\n=== ROOT CAUSE ERROR (extracted) ===\n"
                                                error_msg += "\n".join(root_cause_section)
                                                error_msg += "\n\n=== FULL RECENT LOGS ===\n"
                                            error_msg += full_logs_stdout[-5000:]  # Show more context
                                            error_msg += "\n\n=== FULL LOGS SAVED TO ===\n"
                                            error_msg += "Full logs saved to: /tmp/vllm_full_error.log on the instance"
                                            error_msg += "\nTo view: ssh into instance and run: sudo cat /tmp/vllm_full_error.log"
                                        else:
                                            error_msg += "\n\nNo additional logs available."
                                        
                                        # If v1 engine error and using latest tag, suggest retry with pinned version
                                        if is_v1_engine_error and "latest" in vllm_image_tag:
                                            error_msg += "\n\n=== V1 ENGINE ERROR DETECTED ===\n"
                                            error_msg += "The vLLM v1 engine is failing. This is a known issue with vLLM 0.11.2+.\n"
                                            error_msg += "The deployment will be retried with a pinned stable version (v0.10.5).\n"
                                            logger.warning("v1 engine error detected, will retry with pinned stable version")
                                            # Note: We'll handle retry at a higher level if needed
                                        
                                        # If OOM error, provide specific guidance
                                        if is_oom_error:
                                            error_msg += "\n\n=== CUDA OUT OF MEMORY ERROR DETECTED ===\n"
                                            error_msg += f"GPU memory exhausted. Current settings: max_model_len={max_model_len}, "
                                            error_msg += f"gpu_memory_utilization={gpu_memory_util}, max_num_seqs={max_num_seqs}\n"
                                            error_msg += "Suggested fixes:\n"
                                            error_msg += "1. Reduce max_model_len (try 512 or 1024)\n"
                                            error_msg += "2. Reduce gpu_memory_utilization (try 0.70 or 0.75)\n"
                                            error_msg += "3. Reduce max_num_seqs (try 8 or 16)\n"
                                            error_msg += "4. Increase tensor_parallel_size to distribute model across more GPUs\n"
                                            logger.error("OOM error detected - model configuration too aggressive for available GPU memory")
                                        
                                        error_msg += "\n\n=== TROUBLESHOOTING SUGGESTIONS ===\n"
                                        error_msg += "1. Check if the error is due to insufficient GPU memory\n"
                                        error_msg += "2. Verify the model is compatible with vLLM\n"
                                        error_msg += "3. Check NVIDIA driver and CUDA compatibility\n"
                                        error_msg += "4. Review full logs: sudo docker logs vllm > /tmp/vllm_logs.txt\n"
                                        error_msg += "5. Try reducing max-model-len or increasing tensor-parallel-size\n"
                                        
                                        logger.error(error_msg)
                                        raise RuntimeError(error_msg)
                        
                        last_container_check = elapsed
                    except RuntimeError:
                        raise
                    except Exception as e:
                        logger.warning(f"Error checking container status: {e}")
                
                # Check health endpoint and verify model actually works with test inference
                try:
                    async with aiohttp.ClientSession() as session_http:
                        # First check health endpoint
                        logger.debug(f"Checking health endpoint at http://{ip_address}:8000/health...")
                        try:
                            async with session_http.get(
                                f"http://{ip_address}:8000/health",
                                timeout=aiohttp.ClientTimeout(total=10)
                            ) as response:
                                logger.debug(f"Health endpoint returned status {response.status}")
                                if response.status == 200:
                                    # Health check passed (200 OK means server is up)
                                    # vLLM may return empty body or different format, so just check status code
                                    try:
                                        data = await response.json()
                                        health_ok = data.get("status") == "ok" if data else True
                                    except:
                                        # If response is not JSON or empty, 200 status is enough
                                        health_ok = True
                                    
                                    if health_ok:
                                        # Health check passed, now test actual inference
                                        logger.info(f"Health check passed (status 200), testing inference capability...")
                                        try:
                                            # Get the actual model ID from the API (vLLM uses full HuggingFace path)
                                            # First try to get it from /v1/models, otherwise use full hf_model_path
                                            model_id_for_api = hf_model_path  # Default to full path
                                            try:
                                                async with session_http.get(
                                                    f"http://{ip_address}:8000/v1/models",
                                                    timeout=aiohttp.ClientTimeout(total=5)
                                                ) as models_response:
                                                    if models_response.status == 200:
                                                        models_data = await models_response.json()
                                                        if models_data.get("data") and len(models_data.get("data", [])) > 0:
                                                            model_id_for_api = models_data["data"][0]["id"]
                                            except:
                                                pass  # Fall back to hf_model_path if /v1/models fails
                                            
                                            # Test with a simple chat completion request
                                            test_request = {
                                                "model": model_id_for_api,  # Use full HuggingFace path or model ID from API
                                                "messages": [{"role": "user", "content": "test"}],
                                                "max_tokens": 5,
                                                "temperature": 0.1
                                            }
                                            async with session_http.post(
                                                f"http://{ip_address}:8000/v1/chat/completions",
                                                json=test_request,
                                                timeout=aiohttp.ClientTimeout(total=30)
                                            ) as inference_response:
                                                if inference_response.status == 200:
                                                    inference_data = await inference_response.json()
                                                    if inference_data.get("choices") and len(inference_data.get("choices", [])) > 0:
                                                        model_ready = True
                                                        logger.info(
                                                            f"Model {hf_model_path} is ready and responding to inference requests on {ip_address}"
                                                        )
                                                        break
                                                    else:
                                                        logger.debug(f"Inference test returned empty choices, model may still be initializing...")
                                                else:
                                                    logger.debug(f"Inference test returned status {inference_response.status}, model may still be loading...")
                                        except Exception as inference_error:
                                            # Inference test failed, but health check passed - model might still be loading
                                            logger.debug(f"Inference test failed (model may still be initializing): {str(inference_error)}")
                                else:
                                    logger.debug(f"Health endpoint returned non-200 status: {response.status}")
                        except aiohttp.ClientError as conn_error:
                            # Connection error - log at INFO level so we can see network issues
                            if (elapsed // check_interval) % 5 == 0:  # Every 2.5 minutes
                                logger.info(f"Health check connection error (attempt {elapsed // check_interval + 1}, {elapsed // 60} minutes elapsed): {str(conn_error)}")
                            else:
                                logger.debug(f"Health check connection error: {str(conn_error)}")
                        except asyncio.TimeoutError as timeout_error:
                            # Timeout error - log at INFO level
                            if (elapsed // check_interval) % 5 == 0:  # Every 2.5 minutes
                                logger.info(f"Health check timeout (attempt {elapsed // check_interval + 1}, {elapsed // 60} minutes elapsed): {str(timeout_error)}")
                            else:
                                logger.debug(f"Health check timeout: {str(timeout_error)}")
                except Exception as e:
                    # Model still loading, continue waiting
                    # Log at INFO level every 10 attempts (every 5 minutes) to help debug
                    if (elapsed // check_interval) % 10 == 0:
                        logger.info(f"Model not ready yet (attempt {elapsed // check_interval + 1}, {elapsed // 60} minutes elapsed): {str(e)}")
                    else:
                        logger.debug(f"Model not ready yet (attempt {elapsed // check_interval + 1}): {str(e)}")
                
                await asyncio.sleep(check_interval)
                elapsed += check_interval
                
                # Update progress every 2-3 minutes with more detailed status
                if elapsed % 120 == 0 or (elapsed % 180 == 0):  # Every 2 or 3 minutes
                    progress = min(97 + int((elapsed / max_wait_time) * 2), 99)
                    minutes_elapsed = elapsed // 60
                    
                    # Provide more detailed status based on elapsed time
                    if minutes_elapsed < 5:
                        status_msg = f"Model downloading from HuggingFace... ({minutes_elapsed} minutes elapsed)"
                    elif minutes_elapsed < 15:
                        status_msg = f"Model loading into GPU memory... ({minutes_elapsed} minutes elapsed, this may take 10-15 minutes total)"
                    else:
                        status_msg = f"Model still initializing... ({minutes_elapsed} minutes elapsed, please wait)"
                    
                    await InstanceOrchestrator._update_status(
                        session, orchestration_id, "deploying_model", "model_deploy", progress,
                        status_msg
                    )
                    logger.info(f"Model loading progress: {status_msg}")
            
            # Check after loop completes - only raise timeout error if model is still not ready
            if not model_ready:
                # Get container status and logs for better error message
                try:
                    check_cmd = "sudo docker ps -a --filter name=vllm --format '{{.Status}}'"
                    check_stdout, _, _ = await SSHExecutor.execute_remote_command(
                        ssh_host=ip_address,
                        ssh_user="ubuntu",
                        ssh_key=ssh_key,
                        command=check_cmd,
                        timeout=30,
                        check_status=False
                    )
                    logs_cmd = "sudo docker logs --tail 50 vllm 2>&1"
                    logs_stdout, _, _ = await SSHExecutor.execute_remote_command(
                        ssh_host=ip_address,
                        ssh_user="ubuntu",
                        ssh_key=ssh_key,
                        command=logs_cmd,
                        timeout=30,
                        check_status=False
                    )
                    error_msg = (
                        f"Model {hf_model_path} did not become ready within {max_wait_time // 60} minutes.\n\n"
                        f"This may be due to:\n"
                        f"1) Large model size taking longer to download/load\n"
                        f"2) Insufficient GPU memory (current: {gpu_memory_total} GB total, "
                        f"{gpu_memory_total / tensor_parallel:.2f} GB per GPU)\n"
                        f"3) Network issues downloading from HuggingFace\n"
                        f"4) Model initialization taking longer than expected\n\n"
                    )
                    if check_stdout:
                        error_msg += f"Container status: {check_stdout.strip()}\n"
                    if logs_stdout:
                        error_msg += f"\nRecent container logs (last 1000 chars):\n{logs_stdout[-1000:]}"
                    else:
                        error_msg += "\nPlease check the container logs manually: sudo docker logs vllm"
                    error_msg += (
                        f"\n\nTo troubleshoot:\n"
                        f"1) SSH into the instance and check: sudo docker logs vllm\n"
                        f"2) Verify GPU memory: nvidia-smi\n"
                        f"3) Check if model is still downloading/loading\n"
                        f"4) Consider increasing max_wait_time or using a smaller model"
                    )
                    raise RuntimeError(error_msg)
                except RuntimeError:
                    raise
                except Exception as e:
                    # If we can't get container info, still raise timeout error
                    raise RuntimeError(
                        f"Model {hf_model_path} did not become ready within {max_wait_time // 60} minutes. "
                        f"Please check the container logs: sudo docker logs vllm"
                    ) from e
            
            # Model is ready - perform final verification with inference test
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "deploying_model", "model_deploy", 98,
                f"Model loaded. Performing final verification..."
            )
            logger.info(f"Model {hf_model_path} health check passed, performing final inference verification...")
            
            # Final verification: test actual inference to ensure model works
            try:
                async with aiohttp.ClientSession() as session_http:
                    # Get the actual model ID from the API (vLLM uses full HuggingFace path)
                    # First try to get it from /v1/models, otherwise use full hf_model_path
                    model_id_for_api = hf_model_path  # Default to full path
                    try:
                        async with session_http.get(
                            f"http://{ip_address}:8000/v1/models",
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as models_response:
                            if models_response.status == 200:
                                models_data = await models_response.json()
                                if models_data.get("data") and len(models_data.get("data", [])) > 0:
                                    model_id_for_api = models_data["data"][0]["id"]
                    except:
                        pass  # Fall back to hf_model_path if /v1/models fails
                    
                    # Test with a simple chat completion
                    test_request = {
                        "model": model_id_for_api,  # Use full HuggingFace path or model ID from API
                        "messages": [{"role": "user", "content": "Hello"}],
                        "max_tokens": 10,
                        "temperature": 0.1
                    }
                    
                    async with session_http.post(
                        f"http://{ip_address}:8000/v1/chat/completions",
                        json=test_request,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as verification_response:
                        if verification_response.status == 200:
                            verification_data = await verification_response.json()
                            if verification_data.get("choices") and len(verification_data.get("choices", [])) > 0:
                                logger.info(f"Final verification successful: Model {hf_model_path} is responding to inference requests")
                            else:
                                logger.warning(f"Verification returned empty choices, but continuing...")
                        else:
                            error_text = await verification_response.text()
                            logger.warning(
                                f"Verification request returned status {verification_response.status}: {error_text}. "
                                f"Model may still be initializing, but marking as ready."
                            )
            except Exception as verification_error:
                logger.warning(
                    f"Final verification test failed: {str(verification_error)}. "
                    f"Model health check passed, so marking as ready anyway."
                )
            
            # Mark deployment as complete
            await InstanceOrchestrator._update_status(
                session, orchestration_id, "deploying_model", "model_deploy", 99,
                f"Model {hf_model_path} deployed and verified successfully!"
            )
            logger.info(f"Model {model_name} deployed successfully on {ip_address}")
            
            # Automatically start continuous inference to keep GPU busy and generate metrics
            # This runs for ALL models and ALL GPU types - no conditions
            try:
                logger.info(f"Starting continuous inference for model {hf_model_path} on {ip_address}...")
                await InstanceOrchestrator._start_continuous_inference(
                    ip_address=ip_address,
                    ssh_key=ssh_key,
                    model_name=hf_model_path,
                    vllm_config=vllm_config
                )
                logger.info(f"✓ Successfully started continuous inference for model {hf_model_path} on {ip_address}")
            except Exception as e:
                # Log the full error for debugging, but don't fail deployment
                logger.error(f"✗ Failed to start continuous inference (non-critical, deployment continues): {e}", exc_info=True)
                logger.warning(f"Continuous inference will not run automatically. You can start it manually if needed.")

        except Exception as e:
            logger.error(f"Failed to deploy model: {e}")
            raise

    @staticmethod
    async def _start_continuous_inference(
        ip_address: str,
        ssh_key: str,
        model_name: str,
        vllm_config: Dict[str, Any],
    ) -> None:
        """
        Start continuous inference script on the instance to keep GPU busy and generate metrics.
        This runs in the background and sends requests at regular intervals.
        """
        try:
            # Get configuration from vllm_config or use defaults
            interval = vllm_config.get("inference_interval", 5.0)  # Default 5 seconds
            max_tokens = vllm_config.get("max_tokens", 100)  # Default 100 tokens
            temperature = vllm_config.get("temperature", 0.7)  # Default 0.7
            prompt = vllm_config.get("inference_prompt", "What is 2+2? Please explain your answer.")
            
            # Create a simple Python script that will run on the instance
            # We'll use requests library which is commonly available
            # Escape the prompt for shell heredoc
            escaped_prompt = prompt.replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
            
            script_content = f'''#!/usr/bin/env python3
import requests
import time
import sys
from datetime import datetime

IP = "{ip_address}"
MODEL = "{model_name}"
INTERVAL = {interval}
MAX_TOKENS = {max_tokens}
TEMPERATURE = {temperature}
PROMPT = """{escaped_prompt}"""

URL = "http://" + IP + ":8000/v1/chat/completions"

def send_request():
    payload = {{
        "model": MODEL,
        "messages": [{{"role": "user", "content": PROMPT}}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE
    }}
    try:
        start = time.time()
        response = requests.post(URL, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        latency = time.time() - start
        
        usage = data.get("usage", {{}})
        tokens = usage.get("total_tokens", 0)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{{timestamp}}] Request successful | Latency: {{latency:.3f}}s | Tokens: {{tokens}}")
        return True
    except Exception as e:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{{timestamp}}] Request failed: {{e}}")
        return False

if __name__ == "__main__":
    print(f"Starting continuous inference for {{MODEL}}")
    print(f"Interval: {{INTERVAL}}s, Max Tokens: {{MAX_TOKENS}}, Temperature: {{TEMPERATURE}}")
    print("Press Ctrl+C to stop\\n")
    
    try:
        while True:
            send_request()
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\\nStopping continuous inference...")
        sys.exit(0)
'''
            
            # Write script to instance
            script_path = "/tmp/continuous_inference.py"
            write_script_cmd = f"cat > {script_path} << 'SCRIPT_EOF'\n{script_content}\nSCRIPT_EOF"
            
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=write_script_cmd,
                timeout=30,
                check_status=False
            )
            
            if exit_code != 0:
                raise RuntimeError(f"Failed to write script: {stderr}")
            
            # Make script executable
            chmod_cmd = f"chmod +x {script_path}"
            await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=chmod_cmd,
                timeout=10,
                check_status=False
            )
            
            # Install requests if not available (non-blocking)
            install_requests_cmd = "python3 -c 'import requests' 2>/dev/null || pip3 install --quiet requests"
            await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=install_requests_cmd,
                timeout=60,
                check_status=False  # Don't fail if requests is already installed or install fails
            )
            
            # Start script in background using nohup
            # Kill any existing continuous inference process first
            kill_existing_cmd = "pkill -f continuous_inference.py 2>/dev/null || true"
            await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=kill_existing_cmd,
                timeout=10,
                check_status=False
            )
            
            # Start new process in background
            start_cmd = f"nohup python3 {script_path} > /tmp/continuous_inference.log 2>&1 &"
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=start_cmd,
                timeout=10,
                check_status=False
            )
            
            if exit_code != 0:
                raise RuntimeError(f"Failed to start continuous inference: {stderr}")
            
            # Verify it's running
            await asyncio.sleep(2)  # Give it a moment to start
            verify_cmd = "pgrep -f continuous_inference.py > /dev/null && echo 'running' || echo 'not_running'"
            verify_stdout, _, _ = await SSHExecutor.execute_remote_command(
                ssh_host=ip_address,
                ssh_user="ubuntu",
                ssh_key=ssh_key,
                command=verify_cmd,
                timeout=10,
                check_status=False
            )
            
            if "running" not in verify_stdout:
                # Try to get more info about why it failed
                log_check_cmd = "tail -20 /tmp/continuous_inference.log 2>/dev/null || echo 'No log file found'"
                log_stdout, _, _ = await SSHExecutor.execute_remote_command(
                    ssh_host=ip_address,
                    ssh_user="ubuntu",
                    ssh_key=ssh_key,
                    command=log_check_cmd,
                    timeout=10,
                    check_status=False
                )
                logger.warning(f"Continuous inference process may not have started correctly. Log output: {log_stdout[:500]}")
                raise RuntimeError(f"Continuous inference process verification failed. Process not found after start attempt.")
            else:
                logger.info(f"✓ Continuous inference started successfully on {ip_address} and verified running")
                
        except Exception as e:
            logger.error(f"Error starting continuous inference: {e}", exc_info=True)
            raise

    @staticmethod
    async def _update_status(
        session: AsyncSession,
        orchestration_id: UUID,
        status: str,
        phase: str,
        progress: int,
        log_message: str,
        instance_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        model_deployed: Optional[str] = None,
        error_message: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        """Update orchestration status in database."""
        stmt = (
            update(InstanceOrchestration)
            .where(InstanceOrchestration.orchestration_id == orchestration_id)
            .values(
                status=status,
                current_phase=phase,
                progress=progress,
                last_updated=datetime.now(timezone.utc),
            )
        )

        if instance_id:
            stmt = stmt.values(instance_id=instance_id)
        if ip_address:
            stmt = stmt.values(ip_address=ip_address)
        if model_deployed:
            stmt = stmt.values(model_deployed=model_deployed)
        if error_message:
            stmt = stmt.values(error_message=error_message)
        if completed_at:
            stmt = stmt.values(completed_at=completed_at)

        # Append to logs (handle None case)
        # First get current logs
        current_stmt = select(InstanceOrchestration.logs).where(
            InstanceOrchestration.orchestration_id == orchestration_id
        )
        result = await session.execute(current_stmt)
        current_logs = result.scalar_one_or_none() or ""
        
        new_log_entry = f"\n[{datetime.now(timezone.utc).isoformat()}] {log_message}"
        updated_logs = current_logs + new_log_entry if current_logs else new_log_entry.lstrip('\n')
        
        stmt = stmt.values(logs=updated_logs)

        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def get_orchestration_status(orchestration_id: UUID) -> Optional[InstanceOrchestration]:
        """Get orchestration status from database."""
        async with async_session() as session:
            try:
                stmt = select(InstanceOrchestration).where(
                    InstanceOrchestration.orchestration_id == orchestration_id
                )
                result = await session.execute(stmt)
                orchestration = result.scalar_one_or_none()
                if orchestration:
                    logger.debug(f"Found orchestration {orchestration_id} with status {orchestration.status}")
                else:
                    logger.warning(f"Orchestration {orchestration_id} not found in database")
                return orchestration
            except Exception as e:
                logger.error(f"Error fetching orchestration {orchestration_id}: {e}", exc_info=True)
                raise

