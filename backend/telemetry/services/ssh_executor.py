"""SSH execution helper for remote commands (e.g., Nsight Compute profiling)."""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)


class SSHExecutor:
    """Helper class for executing remote SSH commands asynchronously."""

    @staticmethod
    def _load_private_key(key_data: str) -> paramiko.PKey:
        """Load SSH private key from file path or string data."""
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

        # Try loading from string
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

    @staticmethod
    async def execute_remote_command(
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
        command: str,
        timeout: int = 300,
        check_status: bool = True,
    ) -> Tuple[str, str, int]:
        """
        Execute a command on a remote host via SSH.

        Args:
            ssh_host: Remote host IP or hostname
            ssh_user: SSH username
            ssh_key: SSH private key (file path or key data)
            command: Command to execute
            timeout: Command timeout in seconds
            check_status: Whether to raise exception on non-zero exit code

        Returns:
            Tuple of (stdout, stderr, exit_code)

        Raises:
            RuntimeError: If command fails and check_status is True
        """
        return await asyncio.to_thread(
            SSHExecutor._execute_sync,
            ssh_host,
            ssh_user,
            ssh_key,
            command,
            timeout,
            check_status,
        )

    @staticmethod
    def _execute_sync(
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
        command: str,
        timeout: int,
        check_status: bool,
    ) -> Tuple[str, str, int]:
        """Synchronous SSH command execution (to be run in thread pool)."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            # Load private key
            key = SSHExecutor._load_private_key(ssh_key)

            # Connect with increased timeout and better error handling
            # Use 60 seconds for connection timeout to handle slow network or instance startup
            try:
                client.connect(
                    hostname=ssh_host,
                    username=ssh_user,
                    pkey=key,
                    timeout=60,  # Increased from 30 to 60 seconds
                    allow_agent=False,
                    look_for_keys=False,
                    banner_timeout=30,  # Add banner timeout
                )
            except paramiko.SSHException as e:
                error_msg = f"SSH connection failed to {ssh_host}:{22} ({ssh_user}@{ssh_host})"
                if "Unable to connect" in str(e) or "port 22" in str(e).lower():
                    error_msg += f"\nConnection error: Unable to connect to port 22 on {ssh_host}"
                    error_msg += f"\nPlease verify: 1) Instance is running, 2) Port 22 is open, 3) SSH key is correct, 4) Instance IP hasn't changed"
                else:
                    error_msg += f"\nSSH error: {str(e)}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e
            except Exception as e:
                error_msg = f"SSH connection failed to {ssh_host}: {str(e)}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e

            # Execute command
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8', errors='replace').strip()
            error_output = stderr.read().decode('utf-8', errors='replace').strip()

            logger.info(f"SSH command executed: {command[:100]}... (exit: {exit_status})")

            if check_status and exit_status != 0:
                error_msg = f"SSH command failed with exit code {exit_status}"
                if error_output:
                    error_msg += f"\nStderr: {error_output}"
                if output:
                    error_msg += f"\nStdout: {output}"
                raise RuntimeError(error_msg)

            return output, error_output, exit_status

        except RuntimeError:
            # Re-raise RuntimeError as-is (already has proper error message)
            raise
        except Exception as e:
            logger.error(f"SSH execution failed: {str(e)}")
            raise RuntimeError(f"SSH command execution failed: {command}\nError: {str(e)}")

        finally:
            client.close()

    @staticmethod
    async def execute_ncu_remote(
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
        ncu_command: str,
        output_path: str,
        timeout: int = 600,
    ) -> dict:
        """
        Execute Nsight Compute (ncu) command on remote GPU instance.

        Args:
            ssh_host: Remote host IP or hostname
            ssh_user: SSH username
            ssh_key: SSH private key
            ncu_command: Full ncu command to execute
            output_path: Remote path where ncu output will be saved
            timeout: Command timeout in seconds

        Returns:
            Dictionary with execution details:
            {
                "success": bool,
                "output_path": str,
                "stdout": str,
                "stderr": str,
                "exit_code": int
            }
        """
        try:
            # Execute ncu command
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                ssh_key=ssh_key,
                command=ncu_command,
                timeout=timeout,
                check_status=False,  # Don't raise on non-zero exit (we'll handle it)
            )

            success = exit_code == 0

            result = {
                "success": success,
                "output_path": output_path,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
            }

            if not success:
                logger.warning(f"ncu command failed with exit code {exit_code}: {stderr}")
            else:
                logger.info(f"ncu command succeeded, output saved to {output_path}")

            return result

        except Exception as e:
            logger.error(f"Failed to execute ncu command: {str(e)}")
            return {
                "success": False,
                "output_path": output_path,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    @staticmethod
    async def read_remote_file(
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
        remote_path: str,
    ) -> Optional[str]:
        """
        Read a file from remote host via SFTP.

        Args:
            ssh_host: Remote host IP or hostname
            ssh_user: SSH username
            ssh_key: SSH private key
            remote_path: Path to file on remote host

        Returns:
            File contents as string, or None if file doesn't exist
        """
        return await asyncio.to_thread(
            SSHExecutor._read_remote_file_sync,
            ssh_host,
            ssh_user,
            ssh_key,
            remote_path,
        )

    @staticmethod
    def _read_remote_file_sync(
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
        remote_path: str,
    ) -> Optional[str]:
        """Synchronous remote file read (to be run in thread pool)."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            # Load private key
            key = SSHExecutor._load_private_key(ssh_key)

            # Connect with increased timeout
            try:
                client.connect(
                    hostname=ssh_host,
                    username=ssh_user,
                    pkey=key,
                    timeout=60,  # Increased from 30 to 60 seconds
                    allow_agent=False,
                    look_for_keys=False,
                    banner_timeout=30,
                )
            except paramiko.SSHException as e:
                error_msg = f"SSH connection failed to {ssh_host}: {str(e)}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e
            except Exception as e:
                error_msg = f"SSH connection failed to {ssh_host}: {str(e)}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e

            # Read file via SFTP
            sftp = client.open_sftp()
            try:
                with sftp.open(remote_path, 'r') as f:
                    content = f.read().decode('utf-8', errors='replace')
                    logger.info(f"Successfully read remote file: {remote_path}")
                    return content
            finally:
                sftp.close()

        except FileNotFoundError:
            logger.warning(f"Remote file not found: {remote_path}")
            return None
        except Exception as e:
            logger.error(f"Failed to read remote file {remote_path}: {str(e)}")
            return None
        finally:
            client.close()

    @staticmethod
    async def check_ssh_connectivity(
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
        connection_timeout: int = 10,
    ) -> bool:
        """
        Quick SSH connectivity check with configurable timeout.
        Useful for checking if SSH is available during instance boot.

        Args:
            ssh_host: Remote host IP or hostname
            ssh_user: SSH username
            ssh_key: SSH private key
            connection_timeout: Connection timeout in seconds (default: 10 for quick checks)

        Returns:
            True if SSH connection is available, False otherwise
        """
        return await asyncio.to_thread(
            SSHExecutor._check_ssh_connectivity_sync,
            ssh_host,
            ssh_user,
            ssh_key,
            connection_timeout,
        )

    @staticmethod
    def _check_ssh_connectivity_sync(
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
        connection_timeout: int,
    ) -> bool:
        """Synchronous SSH connectivity check (to be run in thread pool)."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            # Load private key
            key = SSHExecutor._load_private_key(ssh_key)

            # Quick connection test with shorter timeout
            try:
                client.connect(
                    hostname=ssh_host,
                    username=ssh_user,
                    pkey=key,
                    timeout=connection_timeout,  # Use shorter timeout for quick checks
                    allow_agent=False,
                    look_for_keys=False,
                    banner_timeout=5,  # Shorter banner timeout
                )
                # If we get here, connection succeeded
                logger.debug(f"SSH connectivity check passed for {ssh_host}")
                return True
            except Exception:
                # Connection failed, but that's expected during boot
                return False
        except Exception as e:
            logger.debug(f"SSH connectivity check failed for {ssh_host}: {str(e)}")
            return False
        finally:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    async def check_ncu_installed(
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
    ) -> bool:
        """
        Check if Nsight Compute (ncu) is installed on the remote host.

        Returns:
            True if ncu is available, False otherwise
        """
        try:
            stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                ssh_key=ssh_key,
                command="which ncu || echo 'NOT_FOUND'",
                timeout=10,
                check_status=False,
            )

            if "NOT_FOUND" in stdout or exit_code != 0:
                logger.warning("ncu not found on remote host")
                return False

            logger.info(f"ncu found on remote host: {stdout}")
            return True

        except Exception as e:
            logger.error(f"Failed to check ncu installation: {str(e)}")
            return False




