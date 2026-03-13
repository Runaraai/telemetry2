"""Deployment orchestration for telemetry monitoring stack.

This module deploys a comprehensive GPU telemetry stack with three exporters:

1. DCGM Exporter (port 9400):
   - Extended metrics including SM utilization, NVLink throughput, HBM bandwidth
   - Profiling counters for tensor/FP64/FP32/FP16 pipeline activity
   - Power, temperature, clock frequencies, ECC errors
   - PCIe bandwidth and replay counters

2. NVIDIA-SMI Exporter (port 9401):
   - Complementary metrics from nvidia-smi
   - Temperature, utilization, memory stats
   - Power draw, clock speeds, fan speed
   - PCIe link generation and width
   - Encoder session stats

3. Token Throughput Exporter (port 9402):
   - Placeholder for application-level metrics
   - Accepts POST requests to /update endpoint with JSON:
     {"tokens_per_second": 123.4, "total_tokens": 5000, 
      "requests_per_second": 2.5, "total_requests": 100}
   - Workloads can push token generation metrics when available

All metrics are scraped by Prometheus and forwarded to the backend via remote_write.
"""

from __future__ import annotations

import asyncio
import io
import json
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from uuid import UUID, uuid4

import paramiko

from .schemas import DeploymentRequest, DeploymentLogsRequest, TeardownRequest


@dataclass
class _TeardownCreds:
    """Minimal credentials for fallback teardown (has same attrs as DeploymentRequest for _connect/_perform_teardown)."""

    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_key: str
    run_id: UUID


@dataclass
class DeploymentRecord:
    """Deployment state tracked in memory."""

    deployment_id: UUID
    instance_id: str
    run_id: UUID
    status: str
    request: DeploymentRequest
    message: Optional[str] = None
    services: Dict[str, str] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    task: Optional[asyncio.Task] = None


class DeploymentManager:
    """Manage asynchronous deployment lifecycles."""

    def __init__(self) -> None:
        self._records: Dict[UUID, DeploymentRecord] = {}
        self._lock = asyncio.Lock()

    async def start_deployment(
        self,
        instance_id: str,
        request: DeploymentRequest,
    ) -> DeploymentRecord:
        deployment_id = uuid4()
        record = DeploymentRecord(
            deployment_id=deployment_id,
            instance_id=instance_id,
            run_id=request.run_id,
            status="deploying",
            request=request,
        )

        async with self._lock:
            self._records[deployment_id] = record

        record.task = asyncio.create_task(self._run_deploy(record))
        return record

    async def get_status(self, deployment_id: UUID) -> Optional[DeploymentRecord]:
        async with self._lock:
            return self._records.get(deployment_id)

    async def teardown(
        self,
        instance_id: str,
        request: TeardownRequest,
    ) -> None:
        record = await self._find_record(instance_id, request.run_id)
        if not record:
            raise ValueError("Deployment not found for run")

        await asyncio.to_thread(
            self._perform_teardown,
            record.request,
            request.preserve_data,
        )

        await self._update_record(record.deployment_id, status="completed", message="Stack torn down")

    async def teardown_with_credentials(
        self,
        ssh_host: str,
        ssh_user: str,
        pem_content: str,
        run_id: UUID,
        preserve_data: bool,
        ssh_port: int = 22,
    ) -> None:
        """Tear down stack via SSH using explicit credentials (used when deployment record not found)."""
        creds = _TeardownCreds(
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_key=pem_content,
            run_id=run_id,
        )
        await asyncio.to_thread(self._perform_teardown, creds, preserve_data)

    def fetch_logs(self, req: DeploymentLogsRequest) -> Dict[str, str]:
        """SSH to host and return docker compose logs for telemetry services."""
        import base64

        key_content = req.ssh_key
        if not key_content and req.pem_base64:
            key_content = base64.b64decode(req.pem_base64).decode("utf-8")
        if not key_content:
            raise ValueError("Either ssh_key or pem_base64 is required")

        creds = _TeardownCreds(
            ssh_host=req.ssh_host,
            ssh_port=req.ssh_port,
            ssh_user=req.ssh_user,
            ssh_key=key_content,
            run_id=req.run_id,
        )
        remote_dir = f"/tmp/gpu-telemetry-{req.run_id}"
        services = (
            [req.service]
            if req.service and req.service != "all"
            else ["nvidia-smi-exporter", "dcgm-exporter", "dcgm-health-exporter", "token-exporter", "prometheus"]
        )
        result: Dict[str, str] = {}
        ssh = self._connect(creds)
        try:
            dir_ok = self._exec_safe(ssh, f"test -d {remote_dir} && echo ok").strip() == "ok"
            if not dir_ok:
                result["_error"] = f"Directory {remote_dir} not found. Has monitoring been deployed for this run?"
                return result
            for svc in services:
                out = self._exec_safe(
                    ssh,
                    f"cd {remote_dir} && sudo docker compose logs --tail={req.tail} {svc} 2>&1",
                )
                result[svc] = out or "(no output)"
        finally:
            ssh.close()
        return result

    async def _find_record(self, instance_id: str, run_id: UUID) -> Optional[DeploymentRecord]:
        async with self._lock:
            for record in self._records.values():
                if record.instance_id == instance_id and record.run_id == run_id:
                    return record
        return None

    async def _run_deploy(self, record: DeploymentRecord) -> None:
        import logging
        logger = logging.getLogger(__name__)
        try:
            services = await asyncio.to_thread(self._perform_deploy, record.request)
        except Exception as exc:  # pragma: no cover - remote failure path
            logger.error(
                "telemetry_deploy failed run_id=%s instance=%s: %s",
                str(record.run_id),
                record.instance_id,
                str(exc),
                exc_info=True,
            )
            await self._update_record(
                record.deployment_id,
                status="failed",
                message=str(exc),
            )
            return

        await self._update_record(
            record.deployment_id,
            status="running",
            message="Stack deployed successfully",
            services=services,
        )

    async def _update_record(
        self,
        deployment_id: UUID,
        *,
        status: Optional[str] = None,
        message: Optional[str] = None,
        services: Optional[Dict[str, str]] = None,
    ) -> None:
        async with self._lock:
            record = self._records.get(deployment_id)
            if not record:
                return
            if status:
                record.status = status
            if message is not None:
                record.message = message
            if services is not None:
                record.services = services
            record.updated_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # SSH deployment helpers executed in threads
    # ------------------------------------------------------------------
    def _perform_deploy(self, request: DeploymentRequest) -> Dict[str, str]:
        """Deploy telemetry stack with comprehensive validation and health checks."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            "telemetry_deploy starting run_id=%s instance=%s",
            str(request.run_id),
            request.ssh_host,
        )

        # Validate SSH configuration
        if not request.ssh_host or not request.ssh_user:
            raise ValueError("SSH host and user are required")
        
        ssh = self._connect(request)
        try:
            # Step 1: Validate system capabilities
            logger.info("Validating system capabilities...")
            system_info = self._validate_system(ssh)
            logger.info(f"System validation complete: {system_info['gpu_count']} GPU(s), "
                       f"Driver: {system_info['driver_version']}, "
                       f"DCGM: {system_info['dcgm_version']}")

            # Step 1b: Tear down ALL old telemetry stacks FIRST (before prerequisites).
            # This ensures orphaned Prometheus (e.g. from failed Stop, backend restart)
            # is stopped before we deploy. Prevents run_id mismatch: old stack sending
            # to old run while UI shows new run.
            logger.info("Tearing down any existing telemetry stacks (old runs)...")
            self._cleanup_port_conflicts(ssh)
            self._cleanup_old_telemetry_instances(ssh)
            
            # Step 2: Setup remote directory
            remote_dir = f"/tmp/gpu-telemetry-{request.run_id}"
            self._exec(ssh, f"mkdir -p {remote_dir}")

            # Step 3: Upload files with system-aware compose content
            with ssh.open_sftp() as sftp:
                self._write_remote_file(sftp, f"{remote_dir}/check_prerequisites.sh", self._prereq_script())
                self._write_remote_file(sftp, f"{remote_dir}/docker-compose.yml", 
                                       self._compose_content(request, system_info))
                # Pass system_info to prometheus config (to conditionally include DCGM)
                # and include ingest token so remote_write is authorized.
                self._write_remote_file(
                    sftp,
                    f"{remote_dir}/prometheus.yml",
                    self._prometheus_config(request, system_info, request.ingest_token or None),
                )
                self._write_remote_file(sftp, f"{remote_dir}/dcgm-collectors.csv", 
                                       self._dcgm_collectors_csv(request.enable_profiling))
                self._write_remote_file(sftp, f"{remote_dir}/nvidia-smi-exporter.py", 
                                       self._nvidia_smi_exporter_script())
                self._write_remote_file(sftp, f"{remote_dir}/token-exporter.py", 
                                       self._token_exporter_script())
                self._write_remote_file(sftp, f"{remote_dir}/dcgm-health-exporter.py", 
                                       self._dcgm_health_exporter_script())

            # Step 4: Make scripts executable
            self._exec(ssh, f"chmod +x {remote_dir}/check_prerequisites.sh")
            self._exec(ssh, f"chmod +x {remote_dir}/nvidia-smi-exporter.py")
            self._exec(ssh, f"chmod +x {remote_dir}/dcgm-health-exporter.py")
            self._exec(ssh, f"chmod +x {remote_dir}/token-exporter.py")
            
            # Step 5: Validate and auto-install prerequisites on the remote host
            # This script is idempotent: it installs Docker, NVIDIA drivers (if missing),
            # NVIDIA Container Toolkit, DCGM, and required system config. If a reboot is
            # required (e.g., after first driver install), it exits non‑zero with a clear
            # message that is surfaced back to the UI.
            logger.info("Running remote prerequisite checks and installation...")
            self._exec(ssh, f"cd {remote_dir} && sudo bash ./check_prerequisites.sh")
            
            # Step 6: Deploy stack (cleanup already done at start)
            logger.info("Starting Docker Compose stack...")
            # Force recreate DCGM exporter if profiling mode is enabled to ensure it picks up the configuration
            if request.enable_profiling and system_info.get('dcgm_image'):
                logger.info("Profiling mode enabled - forcing DCGM exporter restart...")
                # Check if GPU workloads are running (this will prevent profiling from working)
                gpu_processes = self._exec_safe(ssh, "nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l").strip()
                if gpu_processes and gpu_processes.isdigit() and int(gpu_processes) > 0:
                    logger.warning(f"WARNING: {gpu_processes} GPU process(es) detected. DCGM profiling requires monitoring to start BEFORE GPU workloads. Profiling will be disabled to prevent crashes.")
                    # Remove profiling metrics from CSV and disable profiling env var
                    logger.info("Removing profiling metrics from collectors CSV and disabling profiling...")
                    self._exec_safe(ssh, f"cd {remote_dir} && sed -i '/DCGM_FI_PROF/d' dcgm-collectors.csv")
                    # Update docker-compose.yml to disable profiling
                    self._exec_safe(ssh, f"cd {remote_dir} && sed -i 's/DCGM_EXPORTER_ENABLE_PROFILING: \"true\"/DCGM_EXPORTER_ENABLE_PROFILING: \"false\"/' docker-compose.yml")
                else:
                    # Stop DCGM exporter first to ensure clean restart
                    self._exec_safe(ssh, f"cd {remote_dir} && sudo docker compose stop dcgm-exporter 2>/dev/null || true")
                    # Remove the container to force recreation
                    self._exec_safe(ssh, f"cd {remote_dir} && sudo docker compose rm -f dcgm-exporter 2>/dev/null || true")
            compose_output = self._exec(ssh, f"cd {remote_dir} && sudo docker compose up -d")
            logger.info(
                "telemetry_deploy: docker compose up completed run_id=%s instance=%s output=%s",
                str(request.run_id),
                request.ssh_host,
                (compose_output or "")[:500],
            )

            # Step 8: Wait briefly for services to start
            logger.info("Waiting for services to start...")
            has_dcgm = system_info.get('dcgm_image') is not None
            service_health = self._wait_for_services(ssh, remote_dir, has_dcgm, timeout=15)
            
            # Step 8.5: Verify profiling metrics are available if profiling is enabled, and handle crashes
            if request.enable_profiling and has_dcgm:
                logger.info("Verifying profiling metrics availability...")
                # Wait a bit for DCGM exporter to start collecting metrics
                import time
                time.sleep(8)
                # Check if DCGM exporter is crashing due to profiling errors
                dcgm_logs = self._exec_safe(ssh, f"cd {remote_dir} && sudo docker compose logs --tail=30 dcgm-exporter 2>&1")
                if "Profiling module returned an unrecoverable error" in dcgm_logs or "Failed to watch metrics" in dcgm_logs:
                    logger.error("DCGM exporter is crashing due to profiling errors. Automatically disabling profiling...")
                    # Remove profiling metrics from CSV
                    self._exec_safe(ssh, f"cd {remote_dir} && sed -i '/DCGM_FI_PROF/d' dcgm-collectors.csv")
                    # Update docker-compose.yml to disable profiling
                    self._exec_safe(ssh, f"cd {remote_dir} && sed -i 's/DCGM_EXPORTER_ENABLE_PROFILING: \"true\"/DCGM_EXPORTER_ENABLE_PROFILING: \"false\"/' docker-compose.yml")
                    # Restart DCGM exporter
                    logger.info("Restarting DCGM exporter without profiling...")
                    self._exec_safe(ssh, f"cd {remote_dir} && sudo docker compose stop dcgm-exporter 2>/dev/null || true")
                    self._exec_safe(ssh, f"cd {remote_dir} && sudo docker compose rm -f dcgm-exporter 2>/dev/null || true")
                    self._exec(ssh, f"cd {remote_dir} && sudo docker compose up -d dcgm-exporter")
                    logger.warning("Profiling has been disabled due to DCGM errors. Standard metrics will still be available.")
                else:
                    # Check if profiling metrics are being exposed
                    metrics_check = self._exec_safe(ssh, f"curl -s http://localhost:9400/metrics 2>/dev/null | grep -c 'DCGM_FI_PROF_SM_ACTIVE' || echo '0'")
                    if metrics_check.strip() == '0':
                        logger.warning("WARNING: DCGM_FI_PROF_SM_ACTIVE metrics not found in DCGM exporter endpoint. Profiling may not be working correctly.")
                        logger.warning("This usually means: 1) GPU workloads were running when monitoring started, or 2) DCGM daemon needs to be restarted.")
                    else:
                        logger.info(f"Profiling metrics found: {metrics_check.strip()} DCGM_FI_PROF_SM_ACTIVE metric(s) detected")
            
            # Check if all services are healthy
            unhealthy_services = [svc for svc, status in service_health.items() if status != 'healthy']
            if unhealthy_services:
                logger.warning(f"Some services are unhealthy: {unhealthy_services}")
            else:
                logger.info("All services are healthy!")
            
            return service_health
        finally:
            ssh.close()

    def _perform_teardown(self, request: DeploymentRequest, preserve_data: bool) -> None:
        ssh = self._connect(request)
        try:
            remote_dir = f"/tmp/gpu-telemetry-{request.run_id}"
            down_cmd = "sudo docker compose down"
            if not preserve_data:
                down_cmd += " -v"

            # Compose directory may already be gone (manual cleanup, failed deploy, etc.).
            # Guard the command so teardown is idempotent instead of raising on missing dirs.
            teardown_cmd = (
                f"if [ -d {remote_dir} ]; then "
                f"cd {remote_dir} && {down_cmd}; "
                f"else "
                f"echo 'Telemetry directory {remote_dir} not found; skipping docker compose down.'; "
                f"fi"
            )
            self._exec(ssh, teardown_cmd)

            if not preserve_data:
                cleanup_cmd = (
                    f"if [ -d {remote_dir} ]; then "
                    f"sudo rm -rf {remote_dir}; "
                    f"fi"
                )
                self._exec(ssh, cleanup_cmd)
        finally:
            ssh.close()

    # ------------------------------------------------------------------
    # SSH utilities
    # ------------------------------------------------------------------
    def _connect(self, request: DeploymentRequest) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        key = self._load_private_key(request.ssh_key)
        client.connect(
            hostname=request.ssh_host,
            port=request.ssh_port,
            username=request.ssh_user,
            pkey=key,
            look_for_keys=False,
            allow_agent=False,
        )
        return client

    def _load_private_key(self, key_data: str) -> paramiko.PKey:
        if Path(key_data).expanduser().exists():
            key_path = str(Path(key_data).expanduser())
            loaders = (
                paramiko.RSAKey,
                paramiko.ECDSAKey,
                paramiko.Ed25519Key,
            )
            for loader in loaders:
                try:
                    return loader.from_private_key_file(key_path)
                except Exception:
                    continue
            raise ValueError("Unsupported private key format")

        stream = io.StringIO(key_data)
        loaders = (
            paramiko.RSAKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key,
        )
        for loader in loaders:
            stream.seek(0)
            try:
                return loader.from_private_key(stream)
            except Exception:
                continue
        raise ValueError("Unsupported private key format")

    def _write_remote_file(self, sftp: paramiko.SFTPClient, path: str, content: str) -> None:
        import logging
        logger = logging.getLogger(__name__)
        try:
            logger.info(f"Writing remote file: {path} ({len(content)} bytes)")
            with sftp.file(path, "w") as remote_file:
                remote_file.write(content)
            logger.info(f"Successfully wrote {path}")
        except Exception as e:
            logger.error(f"Failed to write {path}: {e}", exc_info=True)
            raise

    def _exec(self, ssh: paramiko.SSHClient, command: str, timeout: int = 300, ignore_errors: bool = False) -> str:
        """Execute SSH command with timeout and comprehensive error reporting."""
        try:
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8', errors='replace').strip()
            error_output = stderr.read().decode('utf-8', errors='replace').strip()
            
            if exit_status != 0 and not ignore_errors:
                # Build comprehensive error message
                error_msg = f"Command failed (exit code {exit_status}):\n"
                error_msg += f"Command: {command}\n"
                
                if output:
                    error_msg += f"Output: {output[:1000]}\n"
                
                if error_output:
                    error_msg += f"Error: {error_output[:1000]}\n"
                
                raise RuntimeError(error_msg)
            
            return output
        except Exception as e:
            if ignore_errors:
                return ""
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"SSH command execution failed: {command}\nError: {str(e)}")

    def _service_status(self, ssh: paramiko.SSHClient, remote_dir: str) -> Dict[str, str]:
        try:
            output = self._exec(ssh, f"cd {remote_dir} && docker compose ps --format json")
            entries = json.loads(output) if output else []
            return {
                entry.get("Service", entry.get("Name", "unknown")): entry.get("State", "unknown")
                for entry in entries
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # System validation and detection helpers
    # ------------------------------------------------------------------
    def _exec_safe(self, ssh: paramiko.SSHClient, command: str) -> str:
        """Execute command, return empty string on error instead of raising."""
        try:
            stdin, stdout, stderr = ssh.exec_command(command, timeout=30)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status == 0:
                return stdout.read().decode().strip()
        except Exception:
            pass
        return ""

    def _detect_gpu_count(self, ssh: paramiko.SSHClient) -> int:
        """Detect number of GPUs via nvidia-smi."""
        try:
            output = self._exec_safe(ssh, "nvidia-smi --list-gpus | wc -l")
            if output:
                return int(output)
        except Exception:
            pass
        return 1  # Default to 1 GPU

    def _detect_dcgm_version(self, ssh: paramiko.SSHClient) -> Optional[str]:
        """Detect installed DCGM version and return compatible exporter image tag."""
        import logging
        logger = logging.getLogger(__name__)
        
        # Try to get DCGM version from dcgmi
        dcgmi_version = self._exec_safe(ssh, "dcgmi --version 2>/dev/null | head -n1")
        if dcgmi_version:
            logger.info(f"Found DCGM via dcgmi: {dcgmi_version}")
        
        # Check for libdcgm.so to determine major version
        libdcgm_check = self._exec_safe(ssh, "ls -la /usr/lib/x86_64-linux-gnu/libdcgm.so.* 2>/dev/null | head -n1")
        
        if "libdcgm.so.4" in libdcgm_check:
            logger.info("Detected DCGM 4.x (libdcgm.so.4)")
            return "nvcr.io/nvidia/k8s/dcgm-exporter:4.2.0-4.1.0-ubuntu22.04"
        elif "libdcgm.so.3" in libdcgm_check:
            logger.info("Detected DCGM 3.x (libdcgm.so.3)")
            return "nvcr.io/nvidia/k8s/dcgm-exporter:3.1.8-3.1.5-ubuntu20.04"
        elif dcgmi_version:
            # DCGM is installed but we couldn't determine version from library
            # Default to 3.x which is more common
            logger.warning("DCGM detected but version unclear, defaulting to 3.x exporter")
            return "nvcr.io/nvidia/k8s/dcgm-exporter:3.1.8-3.1.5-ubuntu20.04"
        
        logger.info("DCGM not detected, will skip dcgm-exporter")
        return None

    def _check_port_availability(self, ssh: paramiko.SSHClient, ports: list) -> list:
        """Return list of ports that are already in use."""
        blocked = []
        for port in ports:
            # Check if any container is using this port
            output = self._exec_safe(ssh, f"sudo docker ps --filter 'publish={port}' -q")
            if output.strip():
                blocked.append(port)
        return blocked

    def _validate_system(self, ssh: paramiko.SSHClient) -> Dict[str, any]:
        """Pre-flight validation returning system capabilities."""
        import logging
        logger = logging.getLogger(__name__)
        
        system_info = {
            'os_version': 'unknown',
            'driver_version': 'unknown',
            'dcgm_version': None,
            'dcgm_image': None,
            'gpu_count': 1,
            'blocked_ports': [],
            'docker_installed': False,
        }
        
        # Detect OS version
        os_release = self._exec_safe(ssh, "cat /etc/os-release | grep VERSION_ID | cut -d= -f2 | tr -d '\"'")
        if os_release:
            system_info['os_version'] = f"ubuntu{os_release}"
            logger.info(f"Detected OS: {system_info['os_version']}")
        
        # Check Docker
        docker_check = self._exec_safe(ssh, "docker --version")
        system_info['docker_installed'] = bool(docker_check)
        
        # Detect driver version
        driver_version = self._exec_safe(ssh, "nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1")
        if driver_version:
            system_info['driver_version'] = driver_version.strip()
            logger.info(f"Detected NVIDIA driver: {system_info['driver_version']}")
        
        # Detect GPU count
        system_info['gpu_count'] = self._detect_gpu_count(ssh)
        logger.info(f"Detected {system_info['gpu_count']} GPU(s)")
        
        # Detect DCGM
        dcgm_image = self._detect_dcgm_version(ssh)
        system_info['dcgm_image'] = dcgm_image
        system_info['dcgm_version'] = 'detected' if dcgm_image else 'not_installed'
        
        # Detect NVIDIA ML library path and versioned filename (for precise container mounts).
        # We mount only libnvidia-ml.so.1 and its versioned counterpart into the container's
        # standard lib path so nvidia-smi can dlopen it without overriding container glibc.
        nvml_so = self._exec_safe(
            ssh,
            "find /usr/lib /usr/lib64 /usr/lib/x86_64-linux-gnu -maxdepth 2 -name 'libnvidia-ml.so.1' 2>/dev/null | head -1"
        ).strip()
        if nvml_so and nvml_so.startswith('/'):
            system_info['nvidia_lib_path'] = nvml_so.rsplit('/', 1)[0]
        else:
            system_info['nvidia_lib_path'] = '/usr/lib/x86_64-linux-gnu'
        logger.info(f"Detected NVIDIA lib path: {system_info['nvidia_lib_path']}")

        # Find versioned libnvidia-ml.so (e.g. libnvidia-ml.so.535.288.01)
        nvml_versioned = self._exec_safe(
            ssh,
            f"ls {system_info['nvidia_lib_path']}/libnvidia-ml.so.*.* 2>/dev/null | head -1 | xargs -r basename"
        ).strip()
        system_info['nvidia_ml_versioned'] = nvml_versioned if nvml_versioned else ''
        logger.info(f"Detected versioned NVML: {system_info['nvidia_ml_versioned']}")
        
        # Check port availability
        required_ports = [9400, 9401, 9402, 9403, 9090]
        system_info['blocked_ports'] = self._check_port_availability(ssh, required_ports)
        if system_info['blocked_ports']:
            logger.warning(f"Ports in use: {system_info['blocked_ports']}")
        
        return system_info

    def _cleanup_port_conflicts(self, ssh: paramiko.SSHClient) -> None:
        """Stop containers using required ports and clean up networks."""
        import logging
        logger = logging.getLogger(__name__)
        
        for port in [9400, 9401, 9402, 9403, 9090]:
            try:
                # Get container IDs using port
                container_ids = self._exec_safe(ssh, f"sudo docker ps --filter 'publish={port}' -q")
                
                for cid in container_ids.split('\n'):
                    cid = cid.strip()
                    if cid:
                        logger.info(f"Stopping container {cid} using port {port}")
                        self._exec_safe(ssh, f"sudo docker stop {cid}")
                        self._exec_safe(ssh, f"sudo docker rm {cid}")
            except Exception as e:
                logger.warning(f"Error cleaning up port {port}: {e}")
        
        # Clean up Docker networks
        try:
            self._exec_safe(ssh, "sudo docker network prune -f")
            logger.info("Cleaned up unused Docker networks")
        except Exception as e:
            logger.warning(f"Error pruning networks: {e}")

    def _cleanup_old_telemetry_instances(self, ssh: paramiko.SSHClient) -> None:
        """Clean up ALL old telemetry instances to prevent run_id conflicts."""
        import logging
        import time
        logger = logging.getLogger(__name__)
        
        try:
            # Step 1: Find all telemetry directories
            find_cmd = "find /tmp -maxdepth 1 -type d -name 'gpu-telemetry-*' 2>/dev/null || true"
            telemetry_dirs = self._exec_safe(ssh, find_cmd)
            
            if telemetry_dirs and telemetry_dirs.strip():
                logger.info("Found old telemetry instances, cleaning them up...")
                for directory in telemetry_dirs.strip().split('\n'):
                    directory = directory.strip()
                    if directory and directory != '/tmp/gpu-telemetry-':
                        logger.info(f"Stopping old telemetry instance in {directory}")
                        # Stop and remove the docker compose stack
                        cleanup_cmd = (
                            f"if [ -d {directory} ]; then "
                            f"cd {directory} && sudo docker compose down -v 2>/dev/null || true; "
                            f"fi"
                        )
                        self._exec_safe(ssh, cleanup_cmd)
            
            # Step 2: Stop ALL containers using telemetry ports (more aggressive)
            logger.info("Stopping containers using telemetry ports...")
            for port in [9400, 9401, 9402, 9403, 9090]:
                # Get containers using this port (both running and stopped)
                container_ids = self._exec_safe(ssh, f"sudo docker ps -a --filter 'publish={port}' --format '{{{{.ID}}}}' 2>/dev/null || true")
                for cid in container_ids.strip().split('\n'):
                    cid = cid.strip()
                    if cid:
                        logger.info(f"Stopping container {cid} using port {port}")
                        self._exec_safe(ssh, f"sudo docker stop {cid} 2>/dev/null || true")
                        self._exec_safe(ssh, f"sudo docker rm -f {cid} 2>/dev/null || true")
            
            # Step 3: Stop containers by image name pattern (catch any we missed)
            logger.info("Stopping containers by image name pattern...")
            image_patterns = ['prom/prometheus', 'dcgm-exporter', 'nvidia-smi-exporter', 'token-exporter', 'dcgm-health-exporter']
            for pattern in image_patterns:
                container_ids = self._exec_safe(ssh, f"sudo docker ps -a --filter 'ancestor={pattern}' --format '{{{{.ID}}}}' 2>/dev/null || true")
                for cid in container_ids.strip().split('\n'):
                    cid = cid.strip()
                    if cid:
                        logger.info(f"Stopping container {cid} with image pattern {pattern}")
                        self._exec_safe(ssh, f"sudo docker stop {cid} 2>/dev/null || true")
                        self._exec_safe(ssh, f"sudo docker rm -f {cid} 2>/dev/null || true")
            
            # Step 4: Stop containers by name pattern (catch compose services)
            logger.info("Stopping containers by name pattern...")
            name_patterns = ['prometheus', 'dcgm-exporter', 'nvidia-smi-exporter', 'token-exporter', 'dcgm-health-exporter']
            for pattern in name_patterns:
                container_ids = self._exec_safe(ssh, f"sudo docker ps -a --filter 'name={pattern}' --format '{{{{.ID}}}}' 2>/dev/null || true")
                for cid in container_ids.strip().split('\n'):
                    cid = cid.strip()
                    if cid:
                        logger.info(f"Stopping container {cid} with name pattern {pattern}")
                        self._exec_safe(ssh, f"sudo docker stop {cid} 2>/dev/null || true")
                        self._exec_safe(ssh, f"sudo docker rm -f {cid} 2>/dev/null || true")
            
            # Step 5: Wait a moment for ports to be released
            logger.info("Waiting for ports to be released...")
            time.sleep(2)
            
            # Step 6: Verify ports are free
            blocked_ports = self._check_port_availability(ssh, [9400, 9401, 9402, 9403, 9090])
            if blocked_ports:
                logger.warning(f"Warning: Some ports are still in use after cleanup: {blocked_ports}")
            else:
                logger.info("All telemetry ports are now free")
            
            logger.info("Cleanup of old telemetry instances complete")
        except Exception as e:
            logger.warning(f"Error cleaning up old telemetry instances: {e}")

    def _wait_for_services(self, ssh: paramiko.SSHClient, remote_dir: str, has_dcgm: bool, timeout: int = 60) -> Dict[str, str]:
        """Wait briefly for services to start - balanced approach."""
        import logging
        import time
        logger = logging.getLogger(__name__)
        
        # Wait for containers to be created and running
        logger.info("Waiting for containers to start...")
        time.sleep(8)  # Give docker compose time to pull images and start containers
        
        services = ['nvidia-smi-exporter', 'token-exporter', 'dcgm-health-exporter', 'prometheus']
        if has_dcgm:
            services.append('dcgm-exporter')
        
        status = {}
        
        # Check if containers are actually running
        for attempt in range(3):  # Check 3 times over 15 seconds total
            container_status = self._exec_safe(ssh, f"cd {remote_dir} && sudo docker compose ps --format json")
            
            for service in services:
                if service in container_status and '"State":"running"' in container_status:
                    status[service] = 'healthy'
                    logger.info(f"✓ {service} is running")
                elif service in container_status:
                    status[service] = 'starting'
                    logger.info(f"⏳ {service} is starting...")
                else:
                    status[service] = 'unknown'
                    logger.warning(f"⚠ {service} not found")
            
            # If all critical services are running, we're good
            running_count = sum(1 for s in status.values() if s == 'healthy')
            if running_count >= len(services) - 1:  # Allow one service to still be starting
                break
                
            if attempt < 2:
                time.sleep(5)
        
        logger.info(f"Service startup check completed")
        return status

    def _compose_content(self, request: DeploymentRequest, system_info: Optional[Dict[str, any]] = None) -> str:
        """Generate Docker Compose configuration dynamically based on system capabilities."""
        dcgm_interval = "1000" if request.enable_profiling else "5000"
        
        # Use system info if available, otherwise use defaults
        if system_info is None:
            system_info = {
                'gpu_count': 8,  # Default to 8 for backward compatibility
                'dcgm_image': None,  # Will skip DCGM exporter
            }
        
        gpu_count = system_info.get('gpu_count', 1)
        dcgm_image = system_info.get('dcgm_image')
        has_dcgm = dcgm_image is not None
        
        # GPU device passthrough for nvidia-smi access.
        # We mount only the NVIDIA-specific .so files (not the whole lib dir),
        # so the container's own glibc is not overridden. nvidia-smi uses dlopen
        # to load libnvidia-ml.so.1 at runtime; mounting that file directly into
        # the container's standard lib path makes it discoverable without LD_LIBRARY_PATH.
        nvidia_lib_path = system_info.get('nvidia_lib_path', '/usr/lib/x86_64-linux-gnu')
        # Find the versioned libnvidia-ml.so (e.g. libnvidia-ml.so.535.288.01)
        nvidia_ml_versioned = system_info.get('nvidia_ml_versioned', '')

        gpu_devices = []
        for i in range(gpu_count):
            gpu_devices.append(f'      - "/dev/nvidia{i}:/dev/nvidia{i}"')
        gpu_devices_str = '\n'.join(gpu_devices) + '\n' + '\n'.join([
            '      - "/dev/nvidiactl:/dev/nvidiactl"',
            '      - "/dev/nvidia-uvm:/dev/nvidia-uvm"',
            '      - "/dev/nvidia-uvm-tools:/dev/nvidia-uvm-tools"'
        ])

        # Mount specific NVIDIA ML libs into container's standard lib path.
        # This avoids overriding glibc while still letting nvidia-smi find its libs.
        nvidia_ml_so = f'{nvidia_lib_path}/libnvidia-ml.so.1'
        nvidia_ml_vso = f'{nvidia_lib_path}/{nvidia_ml_versioned}' if nvidia_ml_versioned else ''
        nvidia_lib_mounts = f'      - {nvidia_ml_so}:/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1:ro'
        if nvidia_ml_vso:
            nvidia_lib_mounts += f'\n      - {nvidia_ml_vso}:/usr/lib/x86_64-linux-gnu/{nvidia_ml_versioned}:ro'

        # Build DCGM exporter service if DCGM is available.
        # Uses runtime: nvidia so the container toolkit injects all NVIDIA libs automatically.
        dcgm_service = ""
        if has_dcgm:
            dcgm_service = f"""
  dcgm-exporter:
    image: {dcgm_image}
    runtime: nvidia
    privileged: true
    network_mode: host
    volumes:
      - ./dcgm-collectors.csv:/etc/dcgm-exporter/dcp-metrics-included.csv:ro
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
      DCGM_EXPORTER_LISTEN: ":9400"
      DCGM_EXPORTER_KUBERNETES: "false"
      DCGM_EXPORTER_COLLECTORS: "/etc/dcgm-exporter/dcp-metrics-included.csv"
      DCGM_EXPORTER_INTERVAL: "{dcgm_interval}"
      DCGM_EXPORTER_ENABLE_PROFILING: "{str(request.enable_profiling).lower()}"
    cap_add:
      - SYS_ADMIN
    restart: unless-stopped
"""

        # Build prometheus depends_on list
        prometheus_deps = []
        if has_dcgm:
            prometheus_deps.append("      - dcgm-exporter")
        prometheus_deps.extend([
            "      - nvidia-smi-exporter",
            "      - dcgm-health-exporter",
            "      - token-exporter"
        ])
        prometheus_depends = '\n'.join(prometheus_deps)

        compose_content = f"""
services:{dcgm_service}
  nvidia-smi-exporter:
    image: python:3.11-slim
    privileged: true
    network_mode: host
    command: python3 /app/nvidia-smi-exporter.py
    volumes:
      - ./nvidia-smi-exporter.py:/app/nvidia-smi-exporter.py:ro
      - /usr/bin/nvidia-smi:/usr/bin/nvidia-smi:ro
{nvidia_lib_mounts}
    environment:
      NVIDIA_VISIBLE_DEVICES: all
    restart: unless-stopped
    devices:
{gpu_devices_str}

  dcgm-health-exporter:
    image: python:3.11-slim
    privileged: true
    network_mode: host
    command: python3 /app/dcgm-health-exporter.py
    volumes:
      - ./dcgm-health-exporter.py:/app/dcgm-health-exporter.py:ro
      - /usr/bin/nvidia-smi:/usr/bin/nvidia-smi:ro
{nvidia_lib_mounts}
    environment:
      NVIDIA_VISIBLE_DEVICES: all
    restart: unless-stopped
    devices:
{gpu_devices_str}

  token-exporter:
    image: python:3.11-slim
    network_mode: host
    command: python3 /app/token-exporter.py
    volumes:
      - ./token-exporter.py:/app/token-exporter.py:ro
      - token-data:/data
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:v2.48.0
    network_mode: host
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=2h'
      - '--web.enable-lifecycle'
    restart: unless-stopped
    depends_on:
{prometheus_depends}

volumes:
  prometheus-data:
  token-data:
"""
        return compose_content.strip()

    def _prometheus_config(self, request: DeploymentRequest, system_info: Optional[Dict[str, Any]] = None, ingest_token: Optional[str] = None) -> str:
        """Generate Prometheus configuration, conditionally including DCGM if available.
        
        Args:
            request: Deployment request with run_id and backend_url
            system_info: Optional system information (e.g., dcgm_image)
            ingest_token: Optional ingest token for remote_write authentication
        """
        # Check if DCGM is available
        has_dcgm = False
        if system_info:
            has_dcgm = system_info.get('dcgm_image') is not None
        
        # Build DCGM scrape config only if DCGM is available
        dcgm_scrape = ""
        if has_dcgm:
            # Generate DCGM scrape config with proper indentation (14 spaces to match other jobs)
            dcgm_scrape = f"""              - job_name: 'dcgm'
                static_configs:
                  - targets: ['localhost:9400']
                    labels:
                      exporter: 'dcgm'
                      run_id: '{request.run_id}'

"""

        # vLLM metrics scrape — added when vLLM is detected as running on port 8000.
        # host.docker.internal resolves to the host from within Docker containers.
        # This is optional/non-fatal: if vLLM is not running the job will produce no data.
        vllm_scrape = f"""              - job_name: 'vllm'
                static_configs:
                  - targets: ['host.docker.internal:8000']
                    labels:
                      exporter: 'vllm'
                      run_id: '{request.run_id}'
                metrics_path: '/metrics'
                scrape_interval: 5s
                scrape_timeout: 4s

"""
        
        # Build remote_write headers
        remote_write_headers = f"                  X-Run-ID: '{request.run_id}'"
        if ingest_token:
            remote_write_headers += f"\n                  X-Ingest-Token: '{ingest_token}'"
        
        return textwrap.dedent(
            f"""
            global:
              scrape_interval: 1s
              evaluation_interval: 1s

            scrape_configs:
{dcgm_scrape}              - job_name: 'nvidia-smi'
                static_configs:
                  - targets: ['localhost:9401']
                    labels:
                      exporter: 'nvidia-smi'
                      run_id: '{request.run_id}'

              - job_name: 'dcgm-health'
                static_configs:
                  - targets: ['localhost:9403']
                    labels:
                      exporter: 'dcgm-health'
                      run_id: '{request.run_id}'

              - job_name: 'tokens'
                static_configs:
                  - targets: ['localhost:9402']
                    labels:
                      exporter: 'tokens'
                      run_id: '{request.run_id}'

{vllm_scrape}
            remote_write:
              - url: '{request.backend_url.rstrip('/')}/api/telemetry/remote-write'
                headers:
{remote_write_headers}
                queue_config:
                  capacity: 10000
                  max_shards: 5
                  min_shards: 1
                  max_samples_per_send: 1000
                  batch_send_deadline: 5s
            """
        ).strip()

    def _dcgm_collectors_csv(self, enable_profiling: bool = False) -> str:
        """Generate DCGM collectors CSV with widely-supported metrics.
        
        Args:
            enable_profiling: If True, includes profiling metrics (SM active, Tensor, DRAM active)
        
        Only includes metrics that are available on most GPUs without requiring profiling mode.
        Note: DCGM_FI_DEV_SM_ACTIVE and other profiling metrics are not universally available.
        """
        profiling_metrics = ""
        if enable_profiling:
            profiling_metrics = textwrap.dedent(
                """
                # Profiling metrics (requires profiling mode)
                DCGM_FI_PROF_GR_ENGINE_ACTIVE, DCGM_FI_PROF_GR_ENGINE_ACTIVE
                DCGM_FI_PROF_SM_ACTIVE, DCGM_FI_PROF_SM_ACTIVE
                DCGM_FI_PROF_SM_OCCUPANCY, DCGM_FI_PROF_SM_OCCUPANCY
                DCGM_FI_PROF_PIPE_TENSOR_ACTIVE, DCGM_FI_PROF_PIPE_TENSOR_ACTIVE
                DCGM_FI_PROF_DRAM_ACTIVE, DCGM_FI_PROF_DRAM_ACTIVE
                DCGM_FI_PROF_PIPE_FP64_ACTIVE, DCGM_FI_PROF_PIPE_FP64_ACTIVE
                DCGM_FI_PROF_PIPE_FP32_ACTIVE, DCGM_FI_PROF_PIPE_FP32_ACTIVE
                DCGM_FI_PROF_PIPE_FP16_ACTIVE, DCGM_FI_PROF_PIPE_FP16_ACTIVE
                # Profiling NVLink metrics (fields 1011, 1012 - most reliable for NVLink throughput)
                DCGM_FI_PROF_NVLINK_TX_BYTES, DCGM_FI_PROF_NVLINK_TX_BYTES
                DCGM_FI_PROF_NVLINK_RX_BYTES, DCGM_FI_PROF_NVLINK_RX_BYTES
                # Profiling PCIe metrics (DCP metrics)
                DCGM_FI_PROF_PCIE_TX_BYTES, DCGM_FI_PROF_PCIE_TX_BYTES
                DCGM_FI_PROF_PCIE_RX_BYTES, DCGM_FI_PROF_PCIE_RX_BYTES
                """
            ).strip()
        
        raw = textwrap.dedent(
            f"""
            # Format: DCGM_FI_<field_name>, <Prometheus metric name>
            # Core GPU utilization metrics
            DCGM_FI_DEV_GPU_UTIL, DCGM_FI_DEV_GPU_UTIL
            DCGM_FI_DEV_MEM_COPY_UTIL, DCGM_FI_DEV_MEM_COPY_UTIL
            DCGM_FI_DEV_ENC_UTIL, DCGM_FI_DEV_ENC_UTIL
            DCGM_FI_DEV_DEC_UTIL, DCGM_FI_DEV_DEC_UTIL
            
            # Memory metrics
            DCGM_FI_DEV_FB_FREE, DCGM_FI_DEV_FB_FREE
            DCGM_FI_DEV_FB_USED, DCGM_FI_DEV_FB_USED
            DCGM_FI_DEV_FB_TOTAL, DCGM_FI_DEV_FB_TOTAL
            DCGM_FI_DEV_FB_RESERVED, DCGM_FI_DEV_FB_RESERVED
            DCGM_FI_DEV_FB_USED_PERCENT, DCGM_FI_DEV_FB_USED_PERCENT
            
            # Temperature metrics
            DCGM_FI_DEV_GPU_TEMP, DCGM_FI_DEV_GPU_TEMP
            DCGM_FI_DEV_MEMORY_TEMP, DCGM_FI_DEV_MEMORY_TEMP
            DCGM_FI_DEV_SLOWDOWN_TEMP, DCGM_FI_DEV_SLOWDOWN_TEMP
            
            # Power metrics
            DCGM_FI_DEV_POWER_USAGE, DCGM_FI_DEV_POWER_USAGE
            DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION, DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION
            
            # Clock frequencies
            DCGM_FI_DEV_SM_CLOCK, DCGM_FI_DEV_SM_CLOCK
            DCGM_FI_DEV_MEM_CLOCK, DCGM_FI_DEV_MEM_CLOCK
            
            # PCIe metrics
            # Note: BYTES fields (DCGM_FI_DEV_PCIE_TX_BYTES/RX_BYTES) are not available in DCGM 3.x
            # Use THROUGHPUT fields which are available in DCGM 3.x and 4.x
            DCGM_FI_DEV_PCIE_TX_THROUGHPUT, DCGM_FI_DEV_PCIE_TX_THROUGHPUT
            DCGM_FI_DEV_PCIE_RX_THROUGHPUT, DCGM_FI_DEV_PCIE_RX_THROUGHPUT
            DCGM_FI_DEV_PCIE_REPLAY_COUNTER, DCGM_FI_DEV_PCIE_REPLAY_COUNTER
            
            # NVLink metrics (may not be available on all GPUs)
            # Note: DEV_NVLINK_TX_BYTES/RX_BYTES are not available in DCGM 3.x
            # Use BANDWIDTH_TOTAL and error counters which are available
            DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL, DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL
            # NVLink error counters
            DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL, DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL
            DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL, DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL
            DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL, DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL
            # Note: For NVLink throughput per GPU, use profiling metrics (DCGM_FI_PROF_NVLINK_TX_BYTES/RX_BYTES)
            # which are included in the profiling_metrics section when enable_profiling=True
            
            # ECC error metrics (only on GPUs with ECC support)
            DCGM_FI_DEV_ECC_SBE_VOL_TOTAL, DCGM_FI_DEV_ECC_SBE_VOL_TOTAL
            DCGM_FI_DEV_ECC_DBE_VOL_TOTAL, DCGM_FI_DEV_ECC_DBE_VOL_TOTAL
            
            # Throttle reasons
            DCGM_FI_DEV_CLOCK_THROTTLE_REASONS, DCGM_FI_DEV_CLOCK_THROTTLE_REASONS
            
            # XID errors (critical hardware errors)
            DCGM_FI_DEV_XID_ERRORS, DCGM_FI_DEV_XID_ERRORS
            
            # Power management
            DCGM_FI_DEV_POWER_MGMT_LIMIT, DCGM_FI_DEV_POWER_MGMT_LIMIT
            
            # Remapped rows (memory error correction)
            DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS, DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS
            DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS, DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS
            DCGM_FI_DEV_ROW_REMAP_FAILURE, DCGM_FI_DEV_ROW_REMAP_FAILURE
            
            # Datadog recommended fields
            DCGM_FI_DEV_COUNT, DCGM_FI_DEV_COUNT
            DCGM_FI_DEV_FAN_SPEED, DCGM_FI_DEV_FAN_SPEED
            DCGM_FI_DEV_PSTATE, DCGM_FI_DEV_PSTATE
            
            # VGPU License status
            DCGM_FI_DEV_VGPU_LICENSE_STATUS, DCGM_FI_DEV_VGPU_LICENSE_STATUS
            
            {profiling_metrics}
            """
        ).strip()

        lines: list[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append("")
                continue
            if stripped.startswith("#"):
                lines.append(stripped)
                continue
            parts = [part.strip() for part in stripped.split(",")]
            if len(parts) == 1:
                # Skip malformed rows to avoid breaking the exporter.
                continue
            if len(parts) == 2:
                # DCGM expects the Prometheus metric type in the second column.
                # BYTES fields should be counters (cumulative) for rate calculation
                field_name = parts[0]
                metric_type = "counter" if "BYTES" in field_name or "COUNTER" in field_name else "gauge"
                parts = [parts[0], metric_type, parts[1]]
            lines.append(", ".join(parts))

        return "\n".join(lines)

    def _nvidia_smi_exporter_script(self) -> str:
        """Generate nvidia-smi metrics exporter script with error handling and self-tests."""
        return textwrap.dedent(
            """
            #!/usr/bin/env python3
            import subprocess
            import time
            import sys
            from http.server import HTTPServer, BaseHTTPRequestHandler
            import threading

            class MetricsCollector:
                def __init__(self):
                    self.metrics = ""
                    self.lock = threading.Lock()
                    self.error_count = 0
                    self.last_error = None

                def self_test(self):
                    \"\"\"Verify nvidia-smi works before starting collector.\"\"\"
                    try:
                        result = subprocess.run(['nvidia-smi', '--list-gpus'], 
                                              capture_output=True, text=True, timeout=10)
                        if result.returncode != 0:
                            print(f"ERROR: nvidia-smi failed: {result.stderr}", file=sys.stderr)
                            return False
                        
                        gpu_count = len(result.stdout.strip().split('\\n'))
                        print(f"✓ Self-test passed: Found {gpu_count} GPU(s)", file=sys.stderr)
                        return True
                    except Exception as e:
                        print(f"ERROR: Self-test failed: {e}", file=sys.stderr)
                        return False

                def collect(self):
                    try:
                        # Query comprehensive nvidia-smi metrics
                        cmd = [
                            'nvidia-smi',
                            '--query-gpu=index,name,uuid,temperature.gpu,utilization.gpu,utilization.memory,'
                            'memory.total,memory.free,memory.used,power.draw,power.limit,clocks.sm,clocks.mem,'
                            'clocks.gr,fan.speed,pcie.link.gen.current,pcie.link.width.current,encoder.stats.sessionCount,'
                            'encoder.stats.averageFps,encoder.stats.averageLatency',
                            '--format=csv,noheader,nounits'
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                        
                        if result.returncode != 0:
                            self.error_count += 1
                            self.last_error = f"nvidia-smi returned exit code {result.returncode}"
                            if self.error_count % 10 == 1:  # Log every 10th error
                                print(f"WARNING: {self.last_error}: {result.stderr}", file=sys.stderr)
                            return
                        
                        lines = result.stdout.strip().split('\\n')
                        metrics_lines = []
                        
                        for line in lines:
                            if not line.strip():
                                continue
                            
                            try:
                                parts = [p.strip() for p in line.split(',')]
                                if len(parts) < 20:
                                    print(f"WARNING: Incomplete metric data: {len(parts)} fields", file=sys.stderr)
                                    continue
                                
                                gpu_idx, name, uuid, temp, util_gpu, util_mem, mem_total, mem_free, mem_used, \\
                                power_draw, power_limit, clock_sm, clock_mem, clock_gr, fan_speed, \\
                                pcie_gen, pcie_width, enc_sessions, enc_fps, enc_latency = parts[:20]
                                
                                labels = f'gpu="{gpu_idx}",name="{name}",uuid="{uuid}"'
                                
                                # Temperature
                                if temp and temp != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_temperature_celsius{{{labels}}} {temp}')
                                
                                # Utilization
                                if util_gpu and util_gpu != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_utilization_gpu_percent{{{labels}}} {util_gpu}')
                                if util_mem and util_mem != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_utilization_memory_percent{{{labels}}} {util_mem}')
                                
                                # Memory
                                if mem_total and mem_total != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_memory_total_mib{{{labels}}} {mem_total}')
                                if mem_free and mem_free != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_memory_free_mib{{{labels}}} {mem_free}')
                                if mem_used and mem_used != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_memory_used_mib{{{labels}}} {mem_used}')
                                
                                # Power
                                if power_draw and power_draw != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_power_draw_watts{{{labels}}} {power_draw}')
                                if power_limit and power_limit != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_power_limit_watts{{{labels}}} {power_limit}')
                                
                                # Clocks
                                if clock_sm and clock_sm != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_clock_sm_mhz{{{labels}}} {clock_sm}')
                                if clock_mem and clock_mem != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_clock_memory_mhz{{{labels}}} {clock_mem}')
                                if clock_gr and clock_gr != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_clock_graphics_mhz{{{labels}}} {clock_gr}')
                                
                                # Fan
                                if fan_speed and fan_speed != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_fan_speed_percent{{{labels}}} {fan_speed}')
                                
                                # PCIe
                                if pcie_gen and pcie_gen != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_pcie_link_gen{{{labels}}} {pcie_gen}')
                                if pcie_width and pcie_width != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_pcie_link_width{{{labels}}} {pcie_width}')
                                
                                # Encoder
                                if enc_sessions and enc_sessions != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_encoder_sessions{{{labels}}} {enc_sessions}')
                                if enc_fps and enc_fps != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_encoder_fps{{{labels}}} {enc_fps}')
                                if enc_latency and enc_latency != '[N/A]':
                                    metrics_lines.append(f'nvidia_smi_encoder_latency_us{{{labels}}} {enc_latency}')
                            
                            except Exception as line_error:
                                print(f"WARNING: Failed to parse GPU metrics line: {line_error}", file=sys.stderr)
                                continue
                        
                        # Add exporter health metric
                        metrics_lines.append(f'nvidia_smi_exporter_up 1')
                        metrics_lines.append(f'nvidia_smi_exporter_errors_total {self.error_count}')
                        
                        with self.lock:
                            self.metrics = '\\n'.join(metrics_lines) + '\\n'
                        
                        # Reset error count on successful collection
                        if self.error_count > 0:
                            self.error_count = 0
                    
                    except subprocess.TimeoutExpired:
                        self.error_count += 1
                        if self.error_count % 10 == 1:
                            print(f"WARNING: nvidia-smi timeout (attempt {self.error_count})", file=sys.stderr)
                    except Exception as e:
                        self.error_count += 1
                        if self.error_count % 10 == 1:
                            print(f"ERROR: Failed to collect metrics (attempt {self.error_count}): {e}", file=sys.stderr)

                def get_metrics(self):
                    with self.lock:
                        return self.metrics if self.metrics else "nvidia_smi_exporter_up 0\\n"

            collector = MetricsCollector()

            class MetricsHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == '/metrics':
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/plain; version=0.0.4')
                        self.end_headers()
                        self.wfile.write(collector.get_metrics().encode())
                    elif self.path == '/health':
                        # Health check endpoint
                        health = "healthy" if collector.error_count < 10 else "unhealthy"
                        self.send_response(200 if collector.error_count < 10 else 503)
                        self.send_header('Content-Type', 'text/plain')
                        self.end_headers()
                        self.wfile.write(health.encode())
                    else:
                        self.send_response(404)
                        self.end_headers()
                
                def log_message(self, format, *args):
                    pass  # Suppress HTTP logs

            def collect_loop():
                while True:
                    collector.collect()
                    time.sleep(1)

            if __name__ == '__main__':
                print("nvidia-smi exporter starting...", file=sys.stderr)
                
                # Run self-test before starting
                if not collector.self_test():
                    print("ERROR: Self-test failed, exiting", file=sys.stderr)
                    sys.exit(1)
                
                # Collect initial metrics
                collector.collect()
                if not collector.get_metrics() or "nvidia_smi_exporter_up 0" in collector.get_metrics():
                    print("WARNING: Initial metrics collection failed, but continuing...", file=sys.stderr)
                
                # Start collection thread
                thread = threading.Thread(target=collect_loop, daemon=True)
                thread.start()
                
                # Start HTTP server
                try:
                    server = HTTPServer(('0.0.0.0', 9401), MetricsHandler)
                    print("✓ nvidia-smi exporter listening on :9401", file=sys.stderr)
                    server.serve_forever()
                except Exception as e:
                    print(f"ERROR: Failed to start HTTP server: {e}", file=sys.stderr)
                    sys.exit(1)
            """
        ).strip()

    def _token_exporter_script(self) -> str:
        """Generate token throughput exporter script."""
        return textwrap.dedent(
            """
            #!/usr/bin/env python3
            import json
            import time
            from http.server import HTTPServer, BaseHTTPRequestHandler
            import threading
            from pathlib import Path

            class TokenMetrics:
                def __init__(self):
                    self.lock = threading.Lock()
                    self.data_file = Path('/data/tokens.json')
                    self.metrics = {
                        'tokens_per_second': 0.0,
                        'total_tokens': 0,
                        'requests_per_second': 0.0,
                        'total_requests': 0,
                        'ttft_p50_ms': 0.0,
                        'ttft_p95_ms': 0.0,
                        'cost_per_watt': 0.0,
                        'last_update': 0
                    }
                    self.load_data()

                def load_data(self):
                    try:
                        if self.data_file.exists():
                            with open(self.data_file, 'r') as f:
                                data = json.load(f)
                                with self.lock:
                                    self.metrics.update(data)
                    except Exception as e:
                        print(f"Error loading data: {e}")

                def save_data(self):
                    try:
                        self.data_file.parent.mkdir(parents=True, exist_ok=True)
                        with self.lock:
                            with open(self.data_file, 'w') as f:
                                json.dump(self.metrics, f)
                    except Exception as e:
                        print(f"Error saving data: {e}")

                def update_metrics(self, tokens_per_sec=None, total_tokens=None, 
                                 requests_per_sec=None, total_requests=None,
                                 ttft_p50_ms=None, ttft_p95_ms=None, cost_per_watt=None):
                    with self.lock:
                        if tokens_per_sec is not None:
                            self.metrics['tokens_per_second'] = float(tokens_per_sec)
                        if total_tokens is not None:
                            self.metrics['total_tokens'] = int(total_tokens)
                        if requests_per_sec is not None:
                            self.metrics['requests_per_second'] = float(requests_per_sec)
                        if total_requests is not None:
                            self.metrics['total_requests'] = int(total_requests)
                        if ttft_p50_ms is not None:
                            self.metrics['ttft_p50_ms'] = float(ttft_p50_ms)
                        if ttft_p95_ms is not None:
                            self.metrics['ttft_p95_ms'] = float(ttft_p95_ms)
                        if cost_per_watt is not None:
                            self.metrics['cost_per_watt'] = float(cost_per_watt)
                        self.metrics['last_update'] = time.time()
                    self.save_data()

                def get_prometheus_metrics(self):
                    with self.lock:
                        lines = [
                            '# HELP token_throughput_per_second Current token generation throughput',
                            '# TYPE token_throughput_per_second gauge',
                            f'token_throughput_per_second {self.metrics["tokens_per_second"]}',
                            '',
                            '# HELP tokens_per_second Alias for token_throughput_per_second (for compatibility)',
                            '# TYPE tokens_per_second gauge',
                            f'tokens_per_second {self.metrics["tokens_per_second"]}',
                            '',
                            '# HELP token_total_generated Total tokens generated',
                            '# TYPE token_total_generated counter',
                            f'token_total_generated {self.metrics["total_tokens"]}',
                            '',
                            '# HELP inference_requests_per_second Current request throughput',
                            '# TYPE inference_requests_per_second gauge',
                            f'inference_requests_per_second {self.metrics["requests_per_second"]}',
                            '',
                            '# HELP inference_total_requests Total inference requests',
                            '# TYPE inference_total_requests counter',
                            f'inference_total_requests {self.metrics["total_requests"]}',
                            '',
                            '# HELP ttft_p50_ms Time to first token P50 in milliseconds',
                            '# TYPE ttft_p50_ms gauge',
                            f'ttft_p50_ms {self.metrics["ttft_p50_ms"]}',
                            '',
                            '# HELP ttft_p95_ms Time to first token P95 in milliseconds',
                            '# TYPE ttft_p95_ms gauge',
                            f'ttft_p95_ms {self.metrics["ttft_p95_ms"]}',
                            '',
                            '# HELP cost_per_watt Performance per watt (tokens per second per watt)',
                            '# TYPE cost_per_watt gauge',
                            f'cost_per_watt {self.metrics["cost_per_watt"]}',
                            '',
                            '# HELP performance_per_watt Alias for cost_per_watt (for compatibility)',
                            '# TYPE performance_per_watt gauge',
                            f'performance_per_watt {self.metrics["cost_per_watt"]}',
                            '',
                            '# HELP token_metrics_last_update_timestamp Last update timestamp',
                            '# TYPE token_metrics_last_update_timestamp gauge',
                            f'token_metrics_last_update_timestamp {self.metrics["last_update"]}',
                            ''
                        ]
                        return '\\n'.join(lines)

            token_metrics = TokenMetrics()

            class TokenHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == '/metrics':
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/plain; version=0.0.4')
                        self.end_headers()
                        self.wfile.write(token_metrics.get_prometheus_metrics().encode())
                    elif self.path == '/health':
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/plain')
                        self.end_headers()
                        self.wfile.write(b'OK')
                    else:
                        self.send_response(404)
                        self.end_headers()

                def do_POST(self):
                    if self.path == '/update':
                        try:
                            content_length = int(self.headers.get('Content-Length', 0))
                            body = self.rfile.read(content_length)
                            data = json.loads(body.decode())
                            
                            token_metrics.update_metrics(
                                tokens_per_sec=data.get('tokens_per_second'),
                                total_tokens=data.get('total_tokens'),
                                requests_per_sec=data.get('requests_per_second'),
                                total_requests=data.get('total_requests'),
                                ttft_p50_ms=data.get('ttft_p50_ms'),
                                ttft_p95_ms=data.get('ttft_p95_ms'),
                                cost_per_watt=data.get('cost_per_watt')
                            )
                            
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({'status': 'ok'}).encode())
                        except Exception as e:
                            self.send_response(400)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({'error': str(e)}).encode())
                    else:
                        self.send_response(404)
                        self.end_headers()

                def log_message(self, format, *args):
                    pass  # Suppress logs

            def reload_loop():
                while True:
                    time.sleep(5)
                    token_metrics.load_data()

            if __name__ == '__main__':
                # Start reload thread
                thread = threading.Thread(target=reload_loop, daemon=True)
                thread.start()
                
                # Start HTTP server
                server = HTTPServer(('0.0.0.0', 9402), TokenHandler)
                print("Token exporter listening on :9402")
                print("POST metrics to http://localhost:9402/update with JSON:")
                print('  {"tokens_per_second": 123.4, "total_tokens": 5000, "requests_per_second": 2.5, "total_requests": 100}')
                server.serve_forever()
            """
        ).strip()

    def _dcgm_health_exporter_script(self) -> str:
        """Generate DCGM health and configuration exporter script."""
        return textwrap.dedent(
            """
            #!/usr/bin/env python3
            import subprocess
            import time
            import json
            from http.server import HTTPServer, BaseHTTPRequestHandler
            import threading

            class HealthMetricsCollector:
                def __init__(self):
                    self.metrics = ""
                    self.lock = threading.Lock()

                def collect(self):
                    try:
                        metrics_lines = []
                        
                        # Query GPU configuration and health status
                        cmd = [
                            'nvidia-smi',
                            '--query-gpu=index,name,uuid,compute_mode,persistence_mode,power.management,'
                            'power.limit,power.default_limit,power.min_limit,power.max_limit,'
                            'temperature.gpu,temperature.memory,clocks.current.sm,clocks.current.memory,'
                            'clocks.max.sm,clocks.max.memory,clocks_throttle_reasons.active,'
                            'clocks_throttle_reasons.gpu_idle,clocks_throttle_reasons.applications_clocks_setting,'
                            'clocks_throttle_reasons.sw_power_cap,clocks_throttle_reasons.hw_slowdown,'
                            'clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.hw_power_brake_slowdown,'
                            'clocks_throttle_reasons.sync_boost,ecc.mode.current,ecc.errors.corrected.volatile.total,'
                            'ecc.errors.uncorrected.volatile.total',
                            '--format=csv,noheader,nounits'
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                        
                        if result.returncode != 0:
                            return
                        
                        lines = result.stdout.strip().split('\\n')
                        
                        for line in lines:
                            if not line.strip():
                                continue
                            parts = [p.strip() for p in line.split(',')]
                            if len(parts) < 28:
                                continue
                            
                            gpu_idx, name, uuid = parts[0], parts[1], parts[2]
                            compute_mode, persistence_mode, power_mgmt = parts[3], parts[4], parts[5]
                            power_limit, power_default, power_min, power_max = parts[6], parts[7], parts[8], parts[9]
                            temp_gpu, temp_mem = parts[10], parts[11]
                            clock_sm, clock_mem, clock_sm_max, clock_mem_max = parts[12], parts[13], parts[14], parts[15]
                            
                            # Throttle reasons (bitmask flags)
                            throttle_active = parts[16]
                            throttle_idle = parts[17]
                            throttle_app_clocks = parts[18]
                            throttle_sw_power = parts[19]
                            throttle_hw_slowdown = parts[20]
                            throttle_hw_thermal = parts[21]
                            throttle_hw_power_brake = parts[22]
                            throttle_sync_boost = parts[23]
                            
                            ecc_mode = parts[24]
                            ecc_sbe = parts[25]
                            ecc_dbe = parts[26]
                            
                            labels = f'gpu="{gpu_idx}",name="{name}",uuid="{uuid}"'
                            
                            # Configuration metrics
                            if compute_mode and compute_mode != '[N/A]':
                                # Convert compute mode to numeric (0=Default, 1=Exclusive Thread, 2=Prohibited, 3=Exclusive Process)
                                mode_map = {'Default': 0, 'Exclusive_Thread': 1, 'Prohibited': 2, 'Exclusive_Process': 3}
                                mode_val = mode_map.get(compute_mode, 0)
                                metrics_lines.append(f'gpu_compute_mode{{{labels}}} {mode_val}')
                            
                            if persistence_mode and persistence_mode != '[N/A]':
                                persist_val = 1 if persistence_mode == 'Enabled' else 0
                                metrics_lines.append(f'gpu_persistence_mode{{{labels}}} {persist_val}')
                            
                            # Power limits
                            if power_limit and power_limit != '[N/A]':
                                metrics_lines.append(f'gpu_power_limit_watts{{{labels}}} {power_limit}')
                            if power_default and power_default != '[N/A]':
                                metrics_lines.append(f'gpu_power_default_limit_watts{{{labels}}} {power_default}')
                            if power_min and power_min != '[N/A]':
                                metrics_lines.append(f'gpu_power_min_limit_watts{{{labels}}} {power_min}')
                            if power_max and power_max != '[N/A]':
                                metrics_lines.append(f'gpu_power_max_limit_watts{{{labels}}} {power_max}')
                            
                            # Temperature thresholds (these are typically fixed per GPU model)
                            if temp_gpu and temp_gpu != '[N/A]':
                                # Most GPUs throttle around 83-87C and shutdown around 92-95C
                                metrics_lines.append(f'gpu_slowdown_temp_celsius{{{labels}}} 87')
                                metrics_lines.append(f'gpu_shutdown_temp_celsius{{{labels}}} 92')
                            
                            # Clock maximums
                            if clock_sm_max and clock_sm_max != '[N/A]':
                                metrics_lines.append(f'gpu_sm_clock_max_mhz{{{labels}}} {clock_sm_max}')
                            if clock_mem_max and clock_mem_max != '[N/A]':
                                metrics_lines.append(f'gpu_memory_clock_max_mhz{{{labels}}} {clock_mem_max}')
                            
                            # Throttle reasons (convert Active to bitmask)
                            if throttle_active and throttle_active != '[N/A]':
                                try:
                                    throttle_val = int(throttle_active, 16) if 'x' in throttle_active.lower() else int(throttle_active)
                                    metrics_lines.append(f'gpu_throttle_reasons{{{labels}}} {throttle_val}')
                                except:
                                    pass
                            
                            # Individual throttle flags
                            if throttle_idle and throttle_idle != '[N/A]':
                                val = 1 if throttle_idle.lower() == 'active' else 0
                                metrics_lines.append(f'gpu_throttle_idle{{{labels}}} {val}')
                            if throttle_app_clocks and throttle_app_clocks != '[N/A]':
                                val = 1 if throttle_app_clocks.lower() == 'active' else 0
                                metrics_lines.append(f'gpu_throttle_app_clocks{{{labels}}} {val}')
                            if throttle_sw_power and throttle_sw_power != '[N/A]':
                                val = 1 if throttle_sw_power.lower() == 'active' else 0
                                metrics_lines.append(f'gpu_throttle_sw_power{{{labels}}} {val}')
                            if throttle_hw_slowdown and throttle_hw_slowdown != '[N/A]':
                                val = 1 if throttle_hw_slowdown.lower() == 'active' else 0
                                metrics_lines.append(f'gpu_throttle_hw_slowdown{{{labels}}} {val}')
                            if throttle_hw_thermal and throttle_hw_thermal != '[N/A]':
                                val = 1 if throttle_hw_thermal.lower() == 'active' else 0
                                metrics_lines.append(f'gpu_throttle_hw_thermal{{{labels}}} {val}')
                            if throttle_hw_power_brake and throttle_hw_power_brake != '[N/A]':
                                val = 1 if throttle_hw_power_brake.lower() == 'active' else 0
                                metrics_lines.append(f'gpu_throttle_hw_power_brake{{{labels}}} {val}')
                            
                            # ECC status
                            if ecc_mode and ecc_mode != '[N/A]':
                                ecc_val = 1 if ecc_mode == 'Enabled' else 0
                                metrics_lines.append(f'gpu_ecc_mode{{{labels}}} {ecc_val}')
                            if ecc_sbe and ecc_sbe != '[N/A]':
                                metrics_lines.append(f'gpu_ecc_sbe_total{{{labels}}} {ecc_sbe}')
                            if ecc_dbe and ecc_dbe != '[N/A]':
                                metrics_lines.append(f'gpu_ecc_dbe_total{{{labels}}} {ecc_dbe}')
                        
                        # Query topology information
                        try:
                            topo_cmd = ['nvidia-smi', 'topo', '-m']
                            topo_result = subprocess.run(topo_cmd, capture_output=True, text=True, timeout=5)
                            if topo_result.returncode == 0:
                                # Store topology as info metric
                                topo_data = topo_result.stdout.strip()
                                # Simplified: just indicate topology was captured
                                metrics_lines.append(f'gpu_topology_available{{}} 1')
                        except:
                            pass
                        
                        with self.lock:
                            self.metrics = '\\n'.join(metrics_lines) + '\\n'
                    
                    except Exception as e:
                        print(f"Error collecting health metrics: {e}")

                def get_metrics(self):
                    with self.lock:
                        return self.metrics

            collector = HealthMetricsCollector()

            class HealthHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == '/metrics':
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/plain; version=0.0.4')
                        self.end_headers()
                        self.wfile.write(collector.get_metrics().encode())
                    else:
                        self.send_response(404)
                        self.end_headers()
                
                def log_message(self, format, *args):
                    pass  # Suppress logs

            def collect_loop():
                while True:
                    collector.collect()
                    time.sleep(5)  # Collect every 5 seconds (config/health changes less frequently)

            if __name__ == '__main__':
                # Start collection thread
                thread = threading.Thread(target=collect_loop, daemon=True)
                thread.start()
                
                # Start HTTP server
                server = HTTPServer(('0.0.0.0', 9403), HealthHandler)
                print("DCGM health exporter listening on :9403")
                server.serve_forever()
            """
        ).strip()

    def _prereq_script(self) -> str:
        return textwrap.dedent(
            """
            #!/usr/bin/env bash
            set -euo pipefail

            # ==================================================================
            # Logging functions
            # ==================================================================
            log_info() { echo "[INFO] $*"; }
            log_warn() { echo "[WARN] $*" >&2; }
            log_error() { echo "[ERROR] $*" >&2; }
            log_success() { echo "[✓] $*"; }

            # ==================================================================
            # Retry wrapper for apt-get operations
            # ==================================================================
            apt_retry() {
                local max_attempts=3
                local attempt=1
                
                while [[ $attempt -le $max_attempts ]]; do
                    # Wait for apt lock if needed
                    while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
                          sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
                        log_warn "Waiting for apt lock to be released..."
                        sleep 5
                    done
                    
                    if sudo apt-get "$@"; then
                        return 0
                    fi
                    
                    if [[ $attempt -lt $max_attempts ]]; then
                        log_warn "apt-get command failed (attempt $attempt/$max_attempts), retrying in 5s..."
                        sleep 5
                    fi
                    ((attempt++))
                done
                
                log_error "apt-get command failed after $max_attempts attempts"
                return 1
            }

            # ==================================================================
            # 1. Check Docker installation and daemon
            # ==================================================================
            log_info "Checking Docker installation..."
            
            if ! command -v docker &>/dev/null; then
                log_info "Docker not found, installing..."
                curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
                sh /tmp/get-docker.sh
                rm -f /tmp/get-docker.sh
                sudo usermod -aG docker "$USER" || true
                log_success "Docker installed"
            else
                log_success "Docker already installed"
            fi

            # Verify Docker daemon is responding
            if ! docker ps &>/dev/null 2>&1; then
                log_warn "Docker daemon not responding, attempting to start..."
                if command -v systemctl &>/dev/null; then
                    sudo systemctl start docker
                    sleep 3
                else
                    sudo service docker start
                    sleep 3
                fi
                
                if ! docker ps &>/dev/null 2>&1; then
                    log_error "Docker daemon still not responding after restart"
                    exit 2
                fi
            fi
            log_success "Docker daemon is running"

            # ==================================================================
            # 2. Check NVIDIA drivers
            # ==================================================================
            log_info "Checking NVIDIA drivers..."
            
            # Start Monitoring should NEVER attempt to install or upgrade drivers automatically.
            # It only verifies that a working NVIDIA driver is present. Installation/upgrades
            # are a manual prerequisite surfaced in the UI.
            if ! command -v nvidia-smi &>/dev/null; then
                log_error "nvidia-smi not found on this host."
                log_error "NVIDIA datacenter driver must be installed manually before using Start Monitoring."
                log_error "See Omniference prerequisites card for the recommended install command."
                exit 1
            fi
            
            # Verify driver actually works (not just that the binary exists)
            if ! nvidia-smi &>/dev/null 2>&1; then
                log_info "nvidia-smi failed, attempting auto-repair..."

                # Step 1: Fix broken dpkg/apt state (firmware conflicts)
                sudo dpkg --force-overwrite --configure -a 2>&1 | tail -3 || true
                sudo apt-get --fix-broken install -y 2>&1 | tail -3 || true

                # Step 2: Rebuild DKMS modules if missing
                if ! lsmod | grep -q '^nvidia'; then
                    DRIVER_VER=$(dpkg -l 2>/dev/null | grep -oP 'nvidia-dkms-\K[0-9]+' | head -1)
                    if [ -n "$DRIVER_VER" ]; then
                        log_info "Rebuilding DKMS modules for nvidia/$DRIVER_VER..."
                        sudo dkms install "nvidia/$DRIVER_VER" -k "$(uname -r)" 2>&1 | tail -5 || true
                    fi
                fi

                # Step 3: Load kernel modules
                sudo modprobe nvidia 2>/dev/null || true
                sudo modprobe nvidia_uvm 2>/dev/null || true
                sleep 2

                if ! nvidia-smi &>/dev/null 2>&1; then
                    log_error "nvidia-smi still not working after auto-repair."
                    log_error "The host may need a reboot after driver installation."
                    log_error "Try: sudo reboot, then run Start Monitoring again."
                    exit 1
                fi
                log_info "NVIDIA driver repaired and kernel modules loaded successfully."
            fi

            # Extract GPU information
            GPU_COUNT=$(nvidia-smi --list-gpus 2>/dev/null | wc -l || echo "0")
            DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 || echo "unknown")
            
            if [[ "$GPU_COUNT" -eq 0 ]]; then
                log_error "No GPUs detected by nvidia-smi"
                exit 1
            fi
            
            log_success "Found $GPU_COUNT GPU(s), driver version $DRIVER_VERSION"

            # ==================================================================
            # 3. Check NVIDIA Container Toolkit
            # ==================================================================
            log_info "Checking NVIDIA Container Toolkit..."
            
            # Test if GPU access works in Docker
            if ! docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
                log_info "NVIDIA Container Toolkit not functional, installing..."
                
                # Fix broken apt state (common on fresh Scaleway/cloud images)
                # Use --force-overwrite to resolve nvidia-kernel-common vs nvidia-firmware conflicts
                log_info "Fixing broken package dependencies..."
                sudo dpkg --force-overwrite --configure -a 2>&1 || true
                sudo apt-get --fix-broken install -y 2>&1 || true
                sudo apt-get autoremove -y 2>&1 || true
                
                distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
                
                # Map Ubuntu 24.04 to 22.04 repos (toolkit not yet available for 24.04)
                if [[ "$distribution" == "ubuntu24.04" ]]; then
                    distribution="ubuntu22.04"
                fi
                
                # Add NVIDIA Container Toolkit repository
                curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
                    sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
                
                curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
                    sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | \
                    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
                
                # Install toolkit
                apt_retry update
                apt_retry install -y nvidia-container-toolkit
                
                # Configure Docker runtime
                log_info "Configuring Docker runtime..."
                sudo nvidia-ctk runtime configure --runtime=docker --set-as-default || true
                
                # Restart Docker
                log_info "Restarting Docker daemon..."
                if command -v systemctl &>/dev/null; then
                    sudo systemctl restart docker
                else
                    sudo service docker restart
                fi
                sleep 5
                
                # Verify GPU access now works
                if ! docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
                    log_error "GPU access via Docker still not working after toolkit installation"
                    exit 3
                fi
                
                log_success "NVIDIA Container Toolkit installed and configured"
            else
                log_success "GPU access via Docker already functional"
            fi

            # ==================================================================
            # 4. Install DCGM (optional, non-fatal)
            # ==================================================================
            log_info "Checking DCGM installation..."
            
            if ! command -v dcgmi &>/dev/null; then
                log_info "DCGM not found, attempting installation..."
                
                distribution=$(. /etc/os-release; echo "${ID}${VERSION_ID//./}")
                
                # Add CUDA repository if not already present
                if [[ ! -f /etc/apt/keyrings/cuda-archive-keyring.gpg ]]; then
                    tmp_key=$(mktemp)
                    if curl -fsSL "https://developer.download.nvidia.com/compute/cuda/repos/${distribution}/x86_64/cuda-keyring_1.1-1_all.deb" -o "${tmp_key}" 2>/dev/null; then
                        sudo dpkg -i "${tmp_key}" 2>/dev/null || true
                    fi
                    rm -f "${tmp_key}"
                fi

                # Avoid apt "Signed-By" conflicts: ensure only one active CUDA repo entry for this distro.
                # Some images ship a preconfigured CUDA repo that points to the same URL but uses a different keyring,
                # which causes apt to refuse to read sources (e.g., cuda-archive-keyring.gpg != cudatools.gpg).
                CUDA_REPO_URL="https://developer.download.nvidia.com/compute/cuda/repos/${distribution}/x86_64/"
                CUDA_KEYRING="/usr/share/keyrings/cuda-archive-keyring.gpg"
                if [[ ! -f "${CUDA_KEYRING}" && -f /etc/apt/keyrings/cuda-archive-keyring.gpg ]]; then
                    CUDA_KEYRING="/etc/apt/keyrings/cuda-archive-keyring.gpg"
                fi
                if [[ -f "${CUDA_KEYRING}" ]]; then
                    echo "deb [signed-by=${CUDA_KEYRING}] ${CUDA_REPO_URL} /" | sudo tee /etc/apt/sources.list.d/omniference-cuda.list >/dev/null
                    for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
                        [[ -f "${source_file}" ]] || continue
                        [[ "${source_file}" == "/etc/apt/sources.list.d/omniference-cuda.list" ]] && continue
                        if grep -q "${CUDA_REPO_URL}" "${source_file}" 2>/dev/null; then
                            sudo sed -i "\\#${CUDA_REPO_URL}# s|^[[:space:]]*deb[[:space:]]|# deb |" "${source_file}" 2>/dev/null || true
                        fi
                    done
                fi
                
                # Try to install DCGM
                apt_retry update || log_warn "apt-get update had issues"
                if apt_retry install -y datacenter-gpu-manager 2>/dev/null; then
                    log_success "DCGM installed"
                    
                    # Try to get version
                    DCGM_VERSION=$(dcgmi --version 2>/dev/null | head -n1 || echo "unknown")
                    log_info "DCGM version: $DCGM_VERSION"
                else
                    log_warn "DCGM installation failed (non-critical, will use nvidia-smi-exporter only)"
                fi
            else
                DCGM_VERSION=$(dcgmi --version 2>/dev/null | head -n1 || echo "unknown")
                log_success "DCGM already installed: $DCGM_VERSION"
            fi

            # Enable DCGM service if available
            if command -v dcgmi &>/dev/null; then
                if systemctl list-unit-files 2>/dev/null | grep -q "^nvidia-dcgm\\.service"; then
                    sudo systemctl enable --now nvidia-dcgm 2>/dev/null || true
                elif systemctl list-unit-files 2>/dev/null | grep -q "^dcgm\\.service"; then
                    sudo systemctl enable --now dcgm 2>/dev/null || true
                elif systemctl list-unit-files 2>/dev/null | grep -q "^nv-hostengine\\.service"; then
                    sudo systemctl enable --now nv-hostengine 2>/dev/null || true
                fi
            fi

            # ==================================================================
            # 5. Fabric Manager (optional, non-fatal - only needed for multi-GPU NVLink)
            # ==================================================================
            log_info "Checking Fabric Manager..."
            
            driver_major=$(echo "$DRIVER_VERSION" | cut -d. -f1)
            if [[ -n "${driver_major}" && "${driver_major}" =~ ^[0-9]+$ ]]; then
                fabric_pkg="cuda-drivers-fabricmanager-${driver_major}"
                
                if ! dpkg -s "${fabric_pkg}" &>/dev/null 2>&1; then
                    log_info "Attempting to install Fabric Manager (${fabric_pkg})..."
                    
                    if apt_retry install -y "${fabric_pkg}" 2>/dev/null; then
                        log_success "Fabric Manager installed"
                        sudo systemctl enable nvidia-fabricmanager 2>/dev/null || true
                        sudo systemctl start nvidia-fabricmanager 2>/dev/null || true
                    else
                        log_warn "Fabric Manager installation failed (non-critical, only needed for multi-GPU NVLink systems)"
                    fi
                else
                    log_success "Fabric Manager already installed"
                fi
            else
                log_warn "Could not determine driver version for Fabric Manager"
            fi

            # ==================================================================
            # 6. Configure profiling permissions (if not already set)
            # ==================================================================
            log_info "Checking profiling permissions..."
            
            if ! grep -qs "NVreg_RestrictProfilingToAdminUsers" /etc/modprobe.d/omniference-nvidia.conf 2>/dev/null; then
                log_info "Configuring NVIDIA profiling permissions..."
                echo "options nvidia NVreg_RestrictProfilingToAdminUsers=0" | sudo tee /etc/modprobe.d/omniference-nvidia.conf >/dev/null
                
                # Only update initramfs if the file was just created
                if command -v update-initramfs &>/dev/null; then
                    log_info "Updating initramfs (this may take a minute)..."
                    sudo update-initramfs -u 2>/dev/null || log_warn "initramfs update had issues (non-critical)"
                fi
                log_success "Profiling permissions configured"
            else
                log_success "Profiling permissions already configured"
            fi

            # Ensure nvidia-persistenced is running
            sudo systemctl restart nvidia-persistenced 2>/dev/null || true

            # ==================================================================
            # 7. Generate CDI specification (non-fatal)
            # ==================================================================
            log_info "Generating CDI specification..."
            
            sudo mkdir -p /etc/cdi
            
            # Try to generate CDI, but don't fail if it doesn't work
            if sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml 2>&1 | grep -v "^time=" | grep -v "level=warning" | grep -v "level=info" >/dev/null; then
                if [[ -s /etc/cdi/nvidia.yaml ]]; then
                    log_success "CDI specification generated"
                else
                    log_warn "CDI generation completed but file is empty (non-critical)"
                fi
            else
                log_warn "CDI generation had issues (non-critical, containers will use legacy GPU access)"
            fi

            # ==================================================================
            # 8. Final Docker daemon check
            # ==================================================================
            log_info "Verifying Docker daemon is ready..."
            
            for i in {1..30}; do
                if docker ps &>/dev/null 2>&1; then
                    break
                fi
                sleep 1
            done
            
            if ! docker ps &>/dev/null 2>&1; then
                log_error "Docker daemon not responding after all setup steps"
                exit 2
            fi

            # ==================================================================
            # Summary
            # ==================================================================
            echo ""
            log_success "Prerequisites validated successfully"
            log_info "GPU Count: $GPU_COUNT"
            log_info "Driver Version: $DRIVER_VERSION"
            log_info "DCGM: $(command -v dcgmi &>/dev/null && echo 'installed' || echo 'not installed (will use nvidia-smi-exporter)')"
            echo ""
            """
        ).strip()


deployment_manager = DeploymentManager()
