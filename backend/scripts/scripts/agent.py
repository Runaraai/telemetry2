#!/usr/bin/env python3
"""
agent.py — Self-configuring telemetry agent for LLM inference profiling.

Drop this file on any GPU instance alongside the telemetry/ package and run:

    python agent.py

The agent will:
  1. Verify Python version and NVIDIA driver
  2. Install required Python dependencies (pynvml, requests, aiohttp)
  3. Detect GPU tier and start DCGM exporter if applicable
  4. Check whether vLLM is running; optionally start it as a subprocess
  5. Run the requested profiling mode and save results as JSON
  6. Print a final summary with file paths and key metrics

Profiling modes
---------------
  standard (default)
      Full GPU + workload profiling. kernel_backend=None means zero overhead
      from kernel tracing. Good for hardware characterisation and throughput
      baselines. Runs --num-requests (default 50) requests.

  kernel
      Short dedicated run whose sole purpose is kernel-level breakdown.
      Decoupled so it never affects standard hardware metrics.
      Runs --kernel-requests (default 20) requests with a tight profiling
      window (requests 5-15). vLLM must have --profiler-config enabled.

  full
      Runs standard first, then kernel sequentially. Produces two JSON files.

Why decouple kernel mode?
  The vLLM torch profiler writes a Chrome trace file on disk and the engine
  flushes it before /stop_profile returns. During the flush window the engine
  is partially stalled, which contaminates GPU utilisation and latency
  readings. Running kernel mode as a separate short pass prevents this from
  polluting standard metrics.

Usage examples
--------------
  python agent.py                                    # standard, auto-detect
  python agent.py --mode kernel                      # kernel breakdown only
  python agent.py --mode full                        # both passes
  python agent.py --model Qwen/Qwen3.5-9B  # specify model
  python agent.py --server http://10.0.0.2:8000      # remote server
  python agent.py --no-start-vllm                    # skip vLLM auto-start
  python agent.py --num-requests 100 --concurrency 8 # larger load test
  python agent.py --output /data/run.json            # custom output path
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── Colour helpers ────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
BLUE   = "\033[34m"

def _ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def _warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def _fail(msg):  print(f"  {RED}✗{RESET}  {msg}")
def _info(msg):  print(f"  {CYAN}·{RESET}  {msg}")
def _head(msg):  print(f"\n{BOLD}{msg}{RESET}")
def _cmd(cmd):   print(f"     {CYAN}${RESET} {cmd}")
def _sep():      print(f"  {'─' * 54}")


# ── Low-level utilities ────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return 1, str(e)


def _http_get(url: str, timeout: float = 4.0) -> tuple[int, str]:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(8192).decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def _pip_install(packages: list[str]) -> bool:
    code, _ = _run([sys.executable, "-m", "pip", "install", "--quiet", *packages])
    return code == 0


def _try_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# ── Data-centre GPU detection (mirrors setup.py) ──────────────────────────────

_DC_GPU_NAMES = [
    "h100", "h200", "b100", "b200",
    "a100", "a30", "a40", "a10g",
    "l40s", "l40",
    "v100",
    "tesla",
]

def _is_dc_gpu(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in _DC_GPU_NAMES)


_DEFAULT_MODEL = "Qwen/Qwen3.5-9B"


def _load_runara_config() -> dict:
    cfg_path = Path.home() / ".runara" / "config"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text())
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 — System check
# ═══════════════════════════════════════════════════════════════════════════════

def phase_system_check() -> dict:
    """Verify Python version, NVIDIA driver, and detect GPU hardware."""
    _head("Phase 1 — System check")
    info: dict = {
        "python_ok": False,
        "driver_ok": False,
        "gpu_name": "",
        "gpu_count": 0,
        "gpu_vram_mib": 0,
        "is_dc": False,
    }

    # Python version
    if sys.version_info >= (3, 9):
        _ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        info["python_ok"] = True
    else:
        _fail(f"Python {sys.version_info.major}.{sys.version_info.minor} — need 3.9+")
        return info

    # NVIDIA driver + GPU enumeration
    code, out = _run([
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.total",
        "--format=csv,noheader",
    ])
    if code != 0:
        _fail("nvidia-smi not found — is the NVIDIA driver installed?")
        return info

    info["driver_ok"] = True
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    info["gpu_count"] = len(lines)

    for i, line in enumerate(lines):
        parts = [p.strip() for p in line.split(",")]
        name    = parts[0] if len(parts) > 0 else "unknown"
        driver  = parts[1] if len(parts) > 1 else "?"
        vram    = parts[2] if len(parts) > 2 else "?"
        if i == 0:
            info["gpu_name"] = name
            try:
                info["gpu_vram_mib"] = int(vram.replace("MiB", "").strip())
            except ValueError:
                pass
            info["is_dc"] = _is_dc_gpu(name)
        _ok(f"GPU {i}: {name}  |  Driver {driver}  |  VRAM {vram}")

    if info["is_dc"]:
        _ok("Tier: data-centre — DCGM profiling counters available")
    else:
        _warn("Tier: consumer/workstation — will use NVML (no SM Active/Tensor/DRAM)")

    # Spec lookup
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from telemetry.gpu.specs import get_gpu_specs
        specs = get_gpu_specs(info["gpu_name"])
        if specs["peak_tflops_bf16"] > 0:
            _ok(
                f"Spec: {specs['peak_tflops_bf16']} TF BF16  |  "
                f"{specs['peak_hbm_bw_gbps']} GB/s HBM BW  |  "
                f"{specs['nvlink_bw_gbps']} GB/s NVLink"
            )
        else:
            _warn("GPU not in specs.py — MFU and HBM BW util will be 0.0")
    except Exception:
        pass

    return info


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Python dependencies
# ═══════════════════════════════════════════════════════════════════════════════

def phase_install_deps() -> bool:
    """Install required Python packages if missing."""
    _head("Phase 2 — Python dependencies")

    deps = {
        "pynvml":   "nvidia-ml-py3",
        "requests": "requests",
        "aiohttp":  "aiohttp",
    }
    all_ok = True
    for import_name, pkg_name in deps.items():
        if _try_import(import_name):
            _ok(f"{import_name} already installed")
        else:
            _info(f"Installing {pkg_name} ...")
            if _pip_install([pkg_name]):
                _ok(f"{pkg_name} installed")
            else:
                _fail(f"Failed to install {pkg_name} — run:  pip install {pkg_name}")
                all_ok = False
    return all_ok


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — DCGM exporter
# ═══════════════════════════════════════════════════════════════════════════════

_DCGM_COLLECTORS_CSV = """# Runara DCGM collectors (auto-generated)
# Keep this minimal and stable across DCGM versions.
DCGM_FI_DEV_GPU_UTIL, gauge, GPU utilization (%)
DCGM_FI_DEV_FB_USED, gauge, Framebuffer memory used (MiB)
DCGM_FI_DEV_FB_FREE, gauge, Framebuffer memory free (MiB)
DCGM_FI_DEV_POWER_USAGE, gauge, GPU power draw (W)
DCGM_FI_DEV_GPU_TEMP, gauge, GPU temperature (C)
DCGM_FI_DEV_SM_CLOCK, gauge, SM clock (MHz)
DCGM_FI_DEV_MEM_CLOCK, gauge, Memory clock (MHz)
DCGM_FI_DEV_PCIE_TX_THROUGHPUT, gauge, PCIe TX throughput (KB/s)
DCGM_FI_DEV_PCIE_RX_THROUGHPUT, gauge, PCIe RX throughput (KB/s)
DCGM_FI_PROF_SM_ACTIVE, gauge, SM active ratio
DCGM_FI_PROF_SM_OCCUPANCY, gauge, SM occupancy ratio
DCGM_FI_PROF_PIPE_TENSOR_ACTIVE, gauge, Tensor pipe active ratio
DCGM_FI_PROF_DRAM_ACTIVE, gauge, DRAM active ratio
DCGM_FI_DEV_NVLINK_BANDWIDTH_TX_TOTAL, gauge, NVLink TX bandwidth total (KB/s)
DCGM_FI_DEV_NVLINK_BANDWIDTH_RX_TOTAL, gauge, NVLink RX bandwidth total (KB/s)
"""


_DCGM_PROXY_PROC: subprocess.Popen | None = None
_DCGM_NATIVE_PROF_UNSUPPORTED = False


def _kill_dcgm_proxy():
    global _DCGM_PROXY_PROC
    if _DCGM_PROXY_PROC is not None and _DCGM_PROXY_PROC.poll() is None:
        _DCGM_PROXY_PROC.terminate()
        try:
            _DCGM_PROXY_PROC.wait(timeout=5)
        except Exception:
            _DCGM_PROXY_PROC.kill()
        _DCGM_PROXY_PROC = None


# Lightweight Python script written to /tmp and run as a subprocess.
# Reads dcgmi dmon output and exposes Prometheus metrics at :9400/metrics.
_DCGM_PROXY_SCRIPT = '''\
#!/usr/bin/env python3
"""Runara native DCGM proxy — dcgmi dmon → Prometheus text at :9400/metrics."""
import subprocess, threading, time, sys
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 9400

# (field_id, prometheus_metric_name)
# Order here determines column order in dcgmi dmon output
FIELDS = [
    (150,  "DCGM_FI_DEV_GPU_UTIL"),
    (203,  "DCGM_FI_DEV_FB_USED"),
    (252,  "DCGM_FI_DEV_POWER_USAGE"),
    (190,  "DCGM_FI_DEV_GPU_TEMP"),
    (100,  "DCGM_FI_DEV_SM_CLOCK"),
    (101,  "DCGM_FI_DEV_MEM_CLOCK"),
    (1002, "DCGM_FI_PROF_SM_ACTIVE"),
    (1003, "DCGM_FI_PROF_SM_OCCUPANCY"),
    (1005, "DCGM_FI_PROF_DRAM_ACTIVE"),
    (1006, "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE"),
    (1007, "DCGM_FI_PROF_PIPE_FP32_ACTIVE"),
    (1009, "DCGM_FI_PROF_PIPE_FP64_ACTIVE"),
]

_data: dict[str, float] = {}
_lock = threading.Lock()
_gpu_name = "Unknown GPU"


def _get_gpu_name() -> str:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        return lines[0] if lines else "Unknown GPU"
    except Exception:
        return "Unknown GPU"


def _reader():
    field_ids = [str(f) for f, _ in FIELDS]
    field_names = [n for _, n in FIELDS]
    cmd = ["dcgmi", "dmon", "-e", ",".join(field_ids), "-d", "1"]
    while True:
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except Exception as exc:
            print(f"[dcgm-proxy] dcgmi failed to start: {exc}", file=sys.stderr, flush=True)
            time.sleep(5)
            continue
        for raw in proc.stdout:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            # dcgmi output varies by version:
            #   "0 <vals...>" OR "GPU 0 <vals...>"
            if parts[0].isdigit():
                vals = parts[1:]
            elif parts[0].upper() == "GPU" and parts[1].isdigit():
                vals = parts[2:]
            else:
                continue
            update: dict[str, float] = {}
            for i, name in enumerate(field_names):
                if i >= len(vals) or vals[i] in ("N/A", "n/a", ""):
                    continue
                try:
                    update[name] = float(vals[i])
                except ValueError:
                    pass
            if update:
                with _lock:
                    _data.update(update)
        proc.wait()
        try:
            err = proc.stderr.read().strip() if proc.stderr else ""
            if err:
                for ln in err.splitlines()[-3:]:
                    print(f"[dcgm-proxy] {ln}", file=sys.stderr, flush=True)
        except Exception:
            pass
        time.sleep(1)


def _metrics_body() -> bytes:
    with _lock:
        snapshot = dict(_data)
    label = 'gpu="0",modelName="' + _gpu_name + '"'
    lines = [f"{k}{{{label}}} {v}" for k, v in sorted(snapshot.items())]
    return ("\\n".join(lines) + "\\n").encode()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = _metrics_body()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a, **k):
        pass


if __name__ == "__main__":
    _gpu_name = _get_gpu_name()
    threading.Thread(target=_reader, daemon=True).start()
    time.sleep(2)
    srv = HTTPServer(("0.0.0.0", PORT), _Handler)
    print(f"[dcgm-proxy] {_gpu_name} -> :{PORT}/metrics", flush=True)
    sys.stdout.flush()
    srv.serve_forever()
'''

_DCGM_PROXY_PATH = "/tmp/runara_dcgm_proxy.py"


def _start_native_dcgm_proxy(dcgm_url: str) -> bool:
    """Write the dcgmi proxy script and start it. Returns True if metrics come up."""
    global _DCGM_PROXY_PROC, _DCGM_NATIVE_PROF_UNSUPPORTED
    _DCGM_NATIVE_PROF_UNSUPPORTED = False

    # Ensure native hostengine is up before starting the dmon-backed proxy.
    if not _ensure_native_dcgm_running():
        _warn("Native DCGM hostengine is not running - skipping native proxy path")
        return False

    # Quick sanity check that dcgmi can query the engine.
    probe_code, _ = _run(["bash", "-c", "dcgmi discovery -l >/dev/null 2>&1"], timeout=8)
    if probe_code != 0:
        _warn("dcgmi cannot reach hostengine - skipping native proxy path")
        return False

    try:
        Path(_DCGM_PROXY_PATH).write_text(_DCGM_PROXY_SCRIPT, encoding="utf-8")
    except OSError as exc:
        _warn(f"Cannot write proxy script: {exc}")
        return False

    # Free port 9400 in case a stale exporter/proxy is running
    _run(["bash", "-c",
          "fuser -k 9400/tcp 2>/dev/null; docker rm -f dcgm-exporter 2>/dev/null; true"],
         timeout=8)
    time.sleep(1)

    log_path = "/tmp/runara_dcgm_proxy.log"
    try:
        with open(log_path, "w") as lf:
            _DCGM_PROXY_PROC = subprocess.Popen(
                [sys.executable, _DCGM_PROXY_PATH],
                stdout=lf, stderr=lf,
            )
        atexit.register(_kill_dcgm_proxy)
    except OSError as exc:
        _warn(f"Cannot start proxy: {exc}")
        return False

    host = dcgm_url.replace("/metrics", "")
    _info("Waiting for native DCGM proxy ...")
    for i in range(25):
        time.sleep(1)
        # Fast-fail if dcgmi reports unsupported profiling watches.
        try:
            log = Path(log_path).read_text(errors="replace")
            if "Error setting watches" in log and "Feature not supported" in log:
                _DCGM_NATIVE_PROF_UNSUPPORTED = True
                _warn("Native DCGM profiling watches are unsupported in current driver state")
                _kill_dcgm_proxy()
                return False
        except OSError:
            pass
        if _DCGM_PROXY_PROC.poll() is not None:
            _warn("Native DCGM proxy exited early")
            try:
                log = Path(log_path).read_text(errors="replace").strip()
                for ln in log.splitlines()[-5:]:
                    _info(f"  [proxy] {ln}")
            except OSError:
                pass
            return False
        status, body = _http_get(f"{host}/metrics")
        if status != 200 or not body.strip():
            continue
        has_basic = "DCGM_FI_DEV" in body
        has_prof = "DCGM_FI_PROF_SM_ACTIVE" in body
        if has_prof:
            _ok("Native DCGM proxy ready — profiling counters active (SM/Tensor/DRAM)")
            return True
        if has_basic and i >= 8:
            _warn("Native DCGM proxy ready — profiling counters absent (driver restriction?)")
            _info("  Metrics at :9400 are basic counters only; will use NVML for SM Active")
            return True

    _warn("Native DCGM proxy did not respond in time")
    try:
        log = Path(log_path).read_text(errors="replace").strip()
        for ln in log.splitlines()[-8:]:
            _info(f"  [proxy] {ln}")
    except OSError:
        pass
    _kill_dcgm_proxy()
    return False


def _nvidia_driver_major() -> int | None:
    code, out = _run(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
        timeout=5,
    )
    if code != 0 or not out.strip():
        return None
    first = out.splitlines()[0].strip()
    try:
        return int(first.split(".", 1)[0])
    except (ValueError, IndexError):
        return None


def _pick_dcgm_images() -> list[str]:
    """Pick ordered DCGM exporter image candidates for this host."""
    candidates: list[str] = []
    drv_major = _nvidia_driver_major()

    # NVIDIA R590 release notes require DCGM 4.3+.
    if drv_major is not None and drv_major >= 590:
        candidates.extend([
            "nvcr.io/nvidia/k8s/dcgm-exporter:4.5.2-4.8.1-distroless",
            "nvcr.io/nvidia/k8s/dcgm-exporter:4.2.3-4.1.1-ubuntu22.04",
            "nvcr.io/nvidia/k8s/dcgm-exporter:latest",
        ])
    else:
        _, out4 = _run(
            ["bash", "-c", "ls /usr/lib/x86_64-linux-gnu/libdcgm.so.4 2>/dev/null && echo ok"],
            timeout=3,
        )
        if "ok" in out4:
            candidates.append("nvcr.io/nvidia/k8s/dcgm-exporter:4.2.3-4.1.1-ubuntu22.04")

        _, out3 = _run(
            ["bash", "-c", "ls /usr/lib/x86_64-linux-gnu/libdcgm.so.3 2>/dev/null && echo ok"],
            timeout=3,
        )
        if "ok" in out3:
            candidates.append("nvcr.io/nvidia/k8s/dcgm-exporter:3.1.8-3.1.5-ubuntu20.04")

        candidates.extend([
            "nvcr.io/nvidia/k8s/dcgm-exporter:4.5.2-4.8.1-distroless",
            "nvcr.io/nvidia/k8s/dcgm-exporter:latest",
        ])

    # De-duplicate while preserving order.
    out: list[str] = []
    seen: set[str] = set()
    for image in candidates:
        if image not in seen:
            out.append(image)
            seen.add(image)
    return out


def _native_dcgm_available() -> bool:
    code, _ = _run(["bash", "-c", "command -v dcgmi"], timeout=5)
    return code == 0


def _ensure_native_dcgm_running() -> bool:
    # Check active services first
    for svc in ("nvidia-dcgm", "dcgm", "nv-hostengine"):
        code, _ = _run(["systemctl", "is-active", "--quiet", svc], timeout=5)
        if code == 0:
            return True

    # Try known service names
    for svc in ("nvidia-dcgm", "dcgm", "nv-hostengine"):
        sc, _ = _run(["bash", "-c", f"systemctl list-unit-files | grep -q {svc}.service"], timeout=5)
        if sc == 0:
            _run(["sudo", "systemctl", "start", svc], timeout=20)
            time.sleep(2)
            ac, _ = _run(["systemctl", "is-active", "--quiet", svc], timeout=5)
            if ac == 0:
                return True

    # Last resort: direct hostengine launch
    _run(["bash", "-c", "pidof nv-hostengine || (sudo nv-hostengine && sleep 2)"], timeout=15)
    pc, pout = _run(["bash", "-c", "pidof nv-hostengine && echo ok"], timeout=5)
    return pc == 0 and "ok" in pout


def _profiling_admin_only() -> bool | None:
    try:
        params = Path("/proc/driver/nvidia/params").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for line in params.splitlines():
        if "RmProfilingAdminOnly" in line:
            try:
                return int(line.split(":", 1)[1].strip()) == 1
            except Exception:
                return None
    return None


def _write_dcgm_collectors_file(path: str = "/tmp/runara_dcgm_collectors.csv") -> str | None:
    """Write the custom collectors CSV and return its host path."""
    try:
        p = Path(path)
        p.write_text(_DCGM_COLLECTORS_CSV, encoding="utf-8")
        return str(p)
    except OSError as exc:
        _warn(f"Could not write DCGM collectors file ({exc}); using exporter defaults")
        return None


def phase_setup_dcgm(gpu: dict, dcgm_url: str, skip: bool) -> bool:
    """Start DCGM exporter for data-centre GPUs. No-op on consumer hardware."""
    _head("Phase 3 - DCGM exporter")

    if skip:
        _info("Skipped (--skip-dcgm)")
        return True

    if not gpu["is_dc"]:
        _info("Consumer GPU - DCGM not applicable, using NVML instead")
        return True

    host = dcgm_url.replace("/metrics", "")
    status0, body0 = _http_get(f"{host}/metrics")
    had_exporter = (status0 == 200 and "DCGM_FI_DEV" in body0)
    had_prof = ("DCGM_FI_PROF_SM_ACTIVE" in body0) if had_exporter else False

    if had_exporter:
        _ok(f"DCGM exporter already running at {dcgm_url}")
        if had_prof:
            _ok("Profiling counters active (SM Active, Tensor, DRAM)")
            return True
        _warn("Profiling counters absent - will restart")

    # Native dcgmi proxy (preferred - matches h100/lol scripts, no Docker needed)
    if _native_dcgm_available():
        _info("dcgmi found - starting native proxy (no Docker required) ...")
        if _start_native_dcgm_proxy(dcgm_url):
            return True
        _warn("Native proxy did not provide profiling counters - trying Docker exporter")
    else:
        _info("dcgmi not found - falling back to Docker DCGM exporter")

    prof_restricted = _profiling_admin_only()
    native_watch_unsupported = _DCGM_NATIVE_PROF_UNSUPPORTED
    if native_watch_unsupported:
        _warn("Native profiling watches unsupported - proceeding with basic counters")
    if prof_restricted is True:
        _warn("Driver profiling is restricted (RmProfilingAdminOnly=1)")
        modprobe_conf = "/etc/modprobe.d/runara-nvidia-profiling.conf"
        # Always (re)write the fix in case an older conflicting file was the problem.
        _run(
            ["bash", "-c",
             f"echo 'options nvidia NVreg_RestrictProfilingToAdminUsers=0' "
             f"| sudo tee {modprobe_conf} >/dev/null"],
            timeout=10,
        )
        _run(["sudo", "update-initramfs", "-u"], timeout=60)

        # Try live reload; safe here since vLLM has not started yet.
        _info("Attempting live NVIDIA module reload to unlock profiling ...")
        reload_code, reload_out = _run(["bash", "-c", (
            "sudo systemctl stop dcgm nvidia-dcgm nv-hostengine 2>/dev/null; "
            "docker stop $(docker ps -q --filter ancestor=nvcr.io/nvidia/k8s/dcgm-exporter) "
            "$(docker ps -q --filter name=dcgm) 2>/dev/null; "
            "sleep 2; "
            "sudo rmmod nvidia_uvm nvidia_drm nvidia_modeset nvidia 2>&1 && "
            "sudo modprobe nvidia NVreg_RestrictProfilingToAdminUsers=0 2>&1 && "
            "sudo modprobe nvidia_modeset nvidia_uvm 2>/dev/null; "
            "echo EXIT:$?"
        )], timeout=30)
        if "EXIT:0" in reload_out:
            _ok("NVIDIA module reloaded - profiling unlocked (no reboot needed)")
            prof_restricted = False
        else:
            short = reload_out.strip().splitlines()[-1] if reload_out.strip() else "unknown"
            _warn(f"Live reload failed ({short}) - reboot the instance to apply the fix")
            _info("  Fix is written to /etc/modprobe.d/runara-nvidia-profiling.conf")

    code, _ = _run(["docker", "info"], timeout=10)
    if code != 0:
        if had_exporter:
            _warn("Docker unavailable - keeping existing exporter without profiling counters")
            return True
        _fail("Docker not available - DCGM cannot be started automatically")
        _info("Start manually:")
        _cmd("docker run -d --gpus all --cap-add SYS_ADMIN --network host --rm "
             "nvcr.io/nvidia/k8s/dcgm-exporter:latest")
        return False

    dcgm_images = _pick_dcgm_images()
    _info("DCGM image candidates: " + ", ".join(dcgm_images))

    collectors_file = _write_dcgm_collectors_file()
    collectors_mount: list[str] = []
    collectors_runtime: list[str] = []
    if collectors_file:
        collectors_in_container = "/etc/dcgm-exporter/runara-counters.csv"
        collectors_mount = ["-v", f"{collectors_file}:{collectors_in_container}:ro"]
        collectors_runtime = ["-f", collectors_in_container]
        _info(f"Using custom DCGM collectors file: {collectors_file}")
    else:
        _warn("Custom collectors unavailable - using exporter defaults")

    _run(["docker", "rm", "-f", "dcgm-exporter"], timeout=10)

    for dcgm_image in dcgm_images:
        _info(f"Trying DCGM image: {dcgm_image}")
        img_check, _ = _run(["docker", "image", "inspect", dcgm_image], timeout=5)
        if img_check != 0:
            _info("  Image not cached - pulling from registry ...")
            pull_code, pull_out = _run(["docker", "pull", dcgm_image], timeout=300)
            if pull_code != 0:
                _warn(f"  Failed to pull image: {pull_out[:200]}")
                continue
            _ok("  Image pulled")

        attempts: list[tuple[str, list[str]]] = []
        if _native_dcgm_available():
            _info("Native DCGM detected - trying hostengine mode first")
            _ensure_native_dcgm_running()
            attempts.append((
                "native-hostengine",
                [
                    "docker", "run", "-d",
                    "--name", "dcgm-exporter",
                    "--network", "host",
                    "--rm",
                    "--cap-add", "SYS_ADMIN",
                    "-e", "DCGM_EXPORTER_KUBERNETES=false",
                    "-e", "DCGM_REMOTE_HOSTENGINE_INFO=localhost:5555",
                    *collectors_mount,
                    dcgm_image,
                    *collectors_runtime,
                ],
            ))

        attempts.append((
            "container-gpu",
            [
                "docker", "run", "-d",
                "--name", "dcgm-exporter",
                "--gpus", "all",
                "--privileged",
                "--network", "host",
                "--rm",
                "--cap-add", "SYS_ADMIN",
                "-e", "DCGM_EXPORTER_KUBERNETES=false",
                "-e", "NVIDIA_VISIBLE_DEVICES=all",
                "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
                *collectors_mount,
                dcgm_image,
                *collectors_runtime,
            ],
        ))

        if collectors_runtime:
            attempts.append((
                "container-gpu-default-counters",
                [
                    "docker", "run", "-d",
                    "--name", "dcgm-exporter",
                    "--gpus", "all",
                    "--privileged",
                    "--network", "host",
                    "--rm",
                    "--cap-add", "SYS_ADMIN",
                    "-e", "DCGM_EXPORTER_KUBERNETES=false",
                    "-e", "NVIDIA_VISIBLE_DEVICES=all",
                    "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
                    dcgm_image,
                ],
            ))

        for mode, cmd in attempts:
            _run(["docker", "rm", "-f", "dcgm-exporter"], timeout=10)
            _info(f"Starting DCGM exporter ({mode}) ...")
            code, out = _run(cmd, timeout=30)
            if code != 0:
                _warn(f"  docker run failed: {out[:200]}")
                continue

            # If profiling is restricted or unsupported, basic counters are enough.
            accept_basic = (prof_restricted is True or native_watch_unsupported)
            basic_ready = False

            if prof_restricted is True:
                accept_suffix = " - reboot needed for profiling"
            elif native_watch_unsupported:
                accept_suffix = " - profiling watches unsupported on this host"
            else:
                accept_suffix = ""
            _info(
                "  Waiting for metrics endpoint"
                + (f" (accepting basic counters{accept_suffix})" if accept_basic else "")
                + " ..."
            )
            for i in range(60):
                time.sleep(1)
                status, body = _http_get(f"{host}/metrics")

                if status != 200 or "DCGM_FI_DEV" not in body:
                    # Container may have crashed.
                    if i > 5:
                        chk, _ = _run(
                            ["docker", "inspect", "--format", "{{.State.Status}}", "dcgm-exporter"],
                            timeout=5,
                        )
                        if chk != 0:
                            _warn(f"  Container exited early at {i}s")
                            break
                    continue

                if not basic_ready:
                    _info("  Basic GPU counters visible")
                    basic_ready = True

                if "DCGM_FI_PROF_SM_ACTIVE" in body:
                    _ok(f"DCGM exporter ready ({mode}) - profiling counters active (SM/Tensor/DRAM)")
                    return True

                if accept_basic:
                    _ok(f"DCGM exporter ready ({mode}) - basic counters only (reboot for SM/Tensor/DRAM)")
                    return True

                if i >= 45:
                    _warn(f"DCGM exporter ready ({mode}) - profiling counters still absent after 45 s")
                    _info("  This usually means NVreg_RestrictProfilingToAdminUsers=1 is still active")
                    _info("  Reboot the instance - the modprobe fix was already written")
                    return True

            # Container failed - print last few log lines.
            lc, lo = _run(["docker", "logs", "--tail", "20", "dcgm-exporter"], timeout=8)
            if lc == 0 and lo:
                for line in lo.splitlines()[-6:]:
                    _info(f"  [dcgm-log] {line}")

    _fail("DCGM exporter did not start with any strategy")
    _info("Check logs:  docker logs dcgm-exporter")
    _info("Or skip:     python agent.py --skip-dcgm  (will use NVML instead)")
    return False


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Phase 4 â€” vLLM management
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

_VLLM_PROC: subprocess.Popen | None = None   # module-level so atexit can reach it
_VLLM_CONTAINER_NAME = "runara-vllm"


def _kill_vllm():
    global _VLLM_PROC
    if _VLLM_PROC is not None and _VLLM_PROC.poll() is None:
        print("\n[agent] Stopping vLLM process ...")
        try:
            _VLLM_PROC.send_signal(signal.SIGTERM)
            _VLLM_PROC.wait(timeout=10)
        except Exception:
            _VLLM_PROC.kill()
        _VLLM_PROC = None

    # Also clean up Docker container if we started one.
    _run(["docker", "rm", "-f", _VLLM_CONTAINER_NAME], timeout=10)


def _wait_for_vllm(server_url: str, timeout_s: int = 600, log_path: str = "") -> bool:
    """Poll /v1/models until vLLM is ready or timeout expires.
    Prints the last log line every 15 s so the user can track progress."""
    deadline = time.time() + timeout_s
    dots = 0
    last_log = time.time()
    while time.time() < deadline:
        code, _ = _http_get(f"{server_url}/v1/models", timeout=3.0)
        if code == 200:
            print()
            return True
        time.sleep(3)
        dots += 1
        now = time.time()
        if log_path and now - last_log >= 15:
            last_log = now
            try:
                lines = [l.rstrip() for l in Path(log_path).read_text(errors="replace").splitlines() if l.strip()]
                if lines:
                    print(f"\n  {CYAN}[vLLM]{RESET} {lines[-1][:120]}", flush=True)
            except OSError:
                pass
        else:
            print("." if dots % 20 else "\n", end="", flush=True)
    print()
    return False


def _check_profiler(server_url: str, result: dict) -> None:
    """Probe /start_profile with a GET request (non-destructive)."""
    try:
        import urllib.request
        req = urllib.request.Request(f"{server_url.rstrip('/')}/start_profile", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as r:
                result["has_profiler"] = r.status in (200, 405)
        except Exception as e:
            import urllib.error
            if isinstance(e, urllib.error.HTTPError) and e.code in (200, 405):
                result["has_profiler"] = True
    except Exception:
        pass

    if result["has_profiler"]:
        _ok("Kernel profiler endpoint (/start_profile) reachable")
    else:
        _warn("Kernel profiler endpoint not reachable - kernel mode unavailable")
        _info("Restart vLLM with --profiler-config to enable kernel mode")


def _port_from_url(url: str) -> int:
    try:
        return int(url.rstrip("/").rsplit(":", 1)[-1])
    except ValueError:
        return 8000


def phase_ensure_vllm(
    server_url: str,
    model: str,
    trace_dir: str,
    auto_start: bool,
    gpu_mem_util: float,
    max_model_len: int,
) -> dict:
    """Check if vLLM is running; optionally start it (native or Docker)."""
    global _VLLM_PROC
    _head("Phase 4 - vLLM server")

    result: dict = {
        "running": False,
        "model": model,
        "has_profiler": False,
        "we_started": False,
    }

    # Check if already running
    code, body = _http_get(f"{server_url}/v1/models")
    if code == 200:
        result["running"] = True
        try:
            data = json.loads(body)
            models = data.get("data", [])
            if models:
                result["model"] = models[0].get("id", model)
        except Exception:
            pass
        _ok(f"vLLM already running at {server_url}")
        if result["model"]:
            _ok(f"Model: {result['model']}")
        _check_profiler(server_url, result)
        return result

    if not auto_start:
        _fail(f"vLLM not reachable at {server_url}")
        _info("Start vLLM manually, then re-run agent.py")
        return result

    if not model:
        _fail("--model is required when auto-starting vLLM")
        return result

    _info(f"Starting vLLM server for model: {model}")
    _info("Searching for vLLM installation ...")

    native_ok = (_run([sys.executable, "-c", "import vllm"], timeout=8)[0] == 0)
    docker_path = shutil.which("docker") or "docker"
    docker_ok = (_run([docker_path, "info"], timeout=10)[0] == 0)

    if native_ok:
        _ok(f"vLLM found via: python  ({sys.executable})")
    elif docker_ok:
        _ok(f"vLLM found via: docker  ({docker_path})")
    else:
        _fail("vLLM not found (no Python vllm and Docker unavailable)")
        _info("Install with: pip install vllm  OR install Docker")
        return result

    # Build profiler config - always include so kernel mode can work.
    Path(trace_dir).mkdir(parents=True, exist_ok=True)
    profiler_cfg = json.dumps({
        "profiler": "torch",
        "torch_profiler_dir": trace_dir,
        "torch_profiler_with_flops": True,
        "torch_profiler_use_gzip": False,
        "torch_profiler_with_stack": False,
    })

    port = str(_port_from_url(server_url))

    def _mark_ready(log_path: Path, verify_profiler: bool = False):
        result["running"] = True
        result["we_started"] = True
        result["model"] = model
        _ok(f"vLLM ready at {server_url}  (model: {model})")
        if verify_profiler:
            _check_profiler(server_url, result)
        else:
            result["has_profiler"] = True
            _ok("Kernel profiler endpoint enabled (--profiler-config was included)")
        _info(f"vLLM log -> {log_path}")

    # 1) Try native Python vLLM first.
    if native_ok:
        log_path = Path("/tmp/vllm_agent.log")
        cmd = [
            sys.executable, "-m", "vllm.entrypoints.openai.api_server",
            "--model", model,
            "--host", "0.0.0.0",
            "--port", port,
            "--gpu-memory-utilization", str(gpu_mem_util),
            "--max-model-len", str(max_model_len),
            "--dtype", "auto",
            "--trust-remote-code",
            "--enforce-eager",
            "--profiler-config", profiler_cfg,
        ]

        _info(f"vLLM log -> {log_path}")
        _info("Waiting up to 600 s for vLLM to become ready ...")
        try:
            log_f = open(log_path, "w")
            _VLLM_PROC = subprocess.Popen(cmd, stdout=log_f, stderr=log_f)
            atexit.register(_kill_vllm)
        except FileNotFoundError:
            native_ok = False

        if native_ok and _wait_for_vllm(server_url, timeout_s=600, log_path=str(log_path)):
            _mark_ready(log_path)
            return result

        if native_ok:
            _warn("Native vLLM did not become ready in time")
            _info(f"Check: tail {log_path}")
            _kill_vllm()

    # 2) Fallback to Docker-based vLLM.
    if not docker_ok:
        return result

    image = "vllm/vllm-openai:latest"
    _info(f"Using Docker image {image}")

    if _run([docker_path, "image", "inspect", image], timeout=5)[0] != 0:
        _info("vLLM image not cached - pulling ...")
        pull_code, pull_out = _run([docker_path, "pull", image], timeout=600)
        if pull_code != 0:
            _fail(f"Failed to pull vLLM image: {pull_out[:200]}")
            return result
        _ok("vLLM image pulled")

    _run([docker_path, "rm", "-f", _VLLM_CONTAINER_NAME], timeout=10)

    log_path = Path("/tmp/vllm_docker.log")
    hf_cache = str(Path.home() / ".cache" / "huggingface")
    Path(hf_cache).mkdir(parents=True, exist_ok=True)
    run_cmd = [
        docker_path, "run", "-d",
        "--name", _VLLM_CONTAINER_NAME,
        "--gpus", "all",
        "--network", "host",
        "--shm-size", "16g",
        "--rm",
        "-v", f"{hf_cache}:/root/.cache/huggingface",
        "-v", f"{trace_dir}:{trace_dir}",
        "-e", "NVIDIA_VISIBLE_DEVICES=all",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
        "-e", "PYTORCH_ALLOC_CONF=expandable_segments:True",
        image,
        "--model", model,
        "--host", "0.0.0.0",
        "--port", port,
        "--gpu-memory-utilization", str(gpu_mem_util),
        "--max-model-len", str(max_model_len),
        "--dtype", "auto",
        "--trust-remote-code",
        "--enforce-eager",
        "--uvicorn-log-level", "info",
        "--profiler-config", profiler_cfg,
    ]

    _info(f"vLLM log -> {log_path}")
    _info("Waiting up to 600 s for vLLM to become ready ...")
    code, out = _run(run_cmd, timeout=30)
    if code != 0:
        _fail(f"Docker vLLM start failed: {out[:200]}")
        return result

    # Attach a log-follower so _wait_for_vllm can tail progress
    try:
        log_f = open(log_path, "w")
        subprocess.Popen(["docker", "logs", "-f", _VLLM_CONTAINER_NAME],
                         stdout=log_f, stderr=log_f)
    except Exception:
        pass

    if _wait_for_vllm(server_url, timeout_s=600, log_path=str(log_path)):
        _mark_ready(log_path, verify_profiler=True)
        atexit.register(_kill_vllm)
        return result

    _fail("vLLM did not become ready in 600 s")
    _info(f"Check: docker logs --tail 120 {_VLLM_CONTAINER_NAME}")
    _kill_vllm()
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5a — Standard profiling run (GPU + workload, NO kernel)
# ═══════════════════════════════════════════════════════════════════════════════

def phase_run_standard(
    server_url: str,
    model: str,
    dcgm_url: str,
    gpu_index: int,
    num_requests: int,
    max_tokens: int,
    concurrency: int,
    gpu_poll: float,
    output_path: str,
    title: str,
) -> Path | None:
    """
    Standard mode: GPU hardware + workload metrics.
    kernel_backend is explicitly None — zero kernel trace overhead.
    """
    _head("Phase 5a — Standard profiling (GPU + workload)")
    _info(f"Requests: {num_requests}  |  max_tokens: {max_tokens}  |  concurrency: {concurrency}")
    _info("Kernel profiling: DISABLED (use --mode kernel for kernel breakdown)")
    _sep()

    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from telemetry import (
            TelemetryRunner, VLLMOpenAIBackend, AutoGpuBackend,
            print_report, save_json,
        )
        from telemetry.gpu.base import GpuBackend
    except ImportError as e:
        _fail(f"Cannot import telemetry package: {e}")
        _info("Ensure agent.py is in the scripts/ directory alongside telemetry/")
        return None

    # GPU backend
    gpu_backend = _build_gpu_backend(dcgm_url, gpu_index)

    workload = VLLMOpenAIBackend(
        server_url=server_url,
        model=model,
        max_concurrent=concurrency,
    )

    runner = TelemetryRunner(
        gpu_backend=gpu_backend,
        workload_backend=workload,
        kernel_backend=None,       # <-- no kernel overhead
        gpu_poll_s=gpu_poll,
    )

    prompts = _make_prompts(num_requests)

    try:
        result = asyncio.run(runner.run(
            prompts=prompts,
            max_tokens=max_tokens,
            verbose=True,
        ))
    except Exception as e:
        _fail(f"Standard run failed: {e}")
        return None

    print_report(result, title=f"{title} [standard]")
    out = output_path or None
    saved = save_json(result, output_path=out, title=f"{title} [standard]")
    _ok(f"Standard results → {saved}")
    return saved


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5b — Kernel profiling run (short, decoupled)
# ═══════════════════════════════════════════════════════════════════════════════

def phase_run_kernel(
    server_url: str,
    model: str,
    dcgm_url: str,
    gpu_index: int,
    kernel_requests: int,
    max_tokens: int,
    trace_dir: str,
    output_path: str,
    title: str,
) -> Path | None:
    """
    Kernel mode: short dedicated run whose only goal is kernel breakdown.

    Deliberately decoupled from standard run so trace flush overhead does not
    contaminate hardware or latency metrics. Small request count keeps the
    Chrome trace file manageable and the overall run brief.
    """
    _head("Phase 5b — Kernel profiling (decoupled short run)")
    _info(f"Requests: {kernel_requests}  |  max_tokens: {max_tokens}")
    _info(f"Kernel window: requests 5–{min(15, kernel_requests - 1)}")
    _info(f"Trace dir: {trace_dir}")
    _sep()

    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from telemetry import (
            TelemetryRunner, VLLMOpenAIBackend, AutoGpuBackend,
            TorchVLLMKernelBackend, print_report, save_json,
        )
    except ImportError as e:
        _fail(f"Cannot import telemetry package: {e}")
        return None

    # Check profiler availability
    if not TorchVLLMKernelBackend.is_available(server_url=server_url, trace_dir=trace_dir):
        _fail("Kernel profiler endpoint not reachable at /start_profile")
        _info("Restart vLLM with --profiler-config to enable kernel mode")
        _info("Or use --mode standard to skip kernel profiling")
        return None

    gpu_backend = _build_gpu_backend(dcgm_url, gpu_index)
    kernel_backend = TorchVLLMKernelBackend(server_url=server_url, trace_dir=trace_dir)
    workload = VLLMOpenAIBackend(
        server_url=server_url,
        model=model,
        max_concurrent=2,   # low concurrency during kernel window keeps trace clean
    )

    k_stop = min(15, kernel_requests - 1)
    runner = TelemetryRunner(
        gpu_backend=gpu_backend,
        workload_backend=workload,
        kernel_backend=kernel_backend,
        gpu_poll_s=0.5,
        kernel_start_idx=5,
        kernel_stop_idx=k_stop,
    )

    prompts = _make_prompts(kernel_requests)

    try:
        result = asyncio.run(runner.run(
            prompts=prompts,
            max_tokens=max_tokens,
            verbose=True,
        ))
    except Exception as e:
        _fail(f"Kernel run failed: {e}")
        return None

    print_report(result, title=f"{title} [kernel]")

    # Derive kernel-specific output path
    if output_path:
        p = Path(output_path)
        kernel_out = str(p.parent / (p.stem + "_kernel" + p.suffix))
    else:
        kernel_out = None

    saved = save_json(result, output_path=kernel_out, title=f"{title} [kernel]")
    _ok(f"Kernel results → {saved}")
    return saved


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6 — Final summary
# ═══════════════════════════════════════════════════════════════════════════════

def phase_final_summary(
    checks: dict,
    standard_path: Path | None,
    kernel_path: Path | None,
    kernel_attempted: bool = False,
) -> None:
    _head("Agent Summary")
    _sep()

    rows = [
        ("Python 3.9+",      checks.get("python")),
        ("NVIDIA driver",    checks.get("driver")),
        ("Python deps",      checks.get("deps")),
        ("DCGM exporter",    checks.get("dcgm")),
        ("vLLM running",     checks.get("vllm_running")),
        ("Kernel profiler",  checks.get("vllm_profiler")),
        ("Standard run",     standard_path is not None),
        # None = skipped (standard mode), True/False = attempted
        ("Kernel run",       (kernel_path is not None) if kernel_attempted else None),
    ]

    for label, status in rows:
        if status is True:
            _ok(f"{label:<22} ready")
        elif status is False:
            _fail(f"{label:<22} failed / unavailable")
        else:
            _info(f"{label:<22} skipped")

    _sep()
    print()
    if standard_path:
        print(f"  {GREEN}Standard JSON{RESET}  →  {standard_path}")
    if kernel_path:
        print(f"  {GREEN}Kernel JSON{RESET}    →  {kernel_path}")
    print()

    if standard_path or kernel_path:
        print(f"  {GREEN}{BOLD}Profiling complete.{RESET}")
        print()
        _info("Re-run anytime — the agent is idempotent:")
        _cmd("python agent.py")
        _cmd("python agent.py --mode kernel")
        _cmd("python agent.py --mode full")
    else:
        print(f"  {RED}{BOLD}No profiling output produced — review errors above.{RESET}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _build_gpu_backend(dcgm_url: str, gpu_index: int):
    """Build AutoGpuBackend, fall back to a no-op if unavailable."""
    sys.path.insert(0, str(Path(__file__).parent))
    from telemetry import AutoGpuBackend
    from telemetry.gpu.base import GpuBackend

    try:
        b = AutoGpuBackend(dcgm_url=dcgm_url, gpu_index=gpu_index)
        _ok(f"GPU backend: {b.describe()}")
        return b
    except RuntimeError as e:
        _warn(f"GPU backend unavailable ({e}) — using no-op")

    class _Noop(GpuBackend):
        name = "noop"
        capabilities: list = []
        def collect(self): return None
        @classmethod
        def is_available(cls, **kw): return True
        def describe(self): return "disabled"
        def get_metadata(self): return {}

    return _Noop()


# 50 diverse LLM prompts (same as telemetry_run.py, kept here for self-containment)
_PROMPTS = [
    "Explain the attention mechanism in transformers.",
    "What is the difference between supervised and unsupervised learning?",
    "Describe how a GPU executes parallel workloads.",
    "What are the main trade-offs between TTFT and throughput in LLM serving?",
    "How does FlashAttention reduce memory bandwidth requirements?",
    "Explain the KV-cache and how it speeds up autoregressive decoding.",
    "What is tensor parallelism and when is it beneficial?",
    "Describe the softmax operation and its numerical stability tricks.",
    "What is quantization in the context of neural networks?",
    "How does speculative decoding work?",
    "Explain the role of layer normalization in transformers.",
    "What is the difference between MHA and GQA attention?",
    "How does RLHF improve language model alignment?",
    "Describe the SwiGLU activation function.",
    "What is model distillation and why is it useful?",
    "Explain the PagedAttention algorithm.",
    "What metrics matter most for LLM production serving?",
    "Describe the Chinchilla scaling laws.",
    "How does beam search differ from greedy decoding?",
    "What is prefix caching and how does it save compute?",
    "Explain rotary position embeddings (RoPE).",
    "What is the role of the feed-forward network in a transformer block?",
    "How does weight tying reduce model size?",
    "Describe encoder-only, decoder-only, and encoder-decoder models.",
    "What is sparse attention and what problem does it solve?",
    "How does gradient checkpointing trade compute for memory?",
    "Explain the CUDA programming model briefly.",
    "What is warp divergence and why does it hurt GPU performance?",
    "How does NCCL enable multi-GPU communication?",
    "What is the difference between data parallelism and pipeline parallelism?",
    "Explain how continuous batching works in vLLM.",
    "What are the key bottlenecks when running large LLMs?",
    "Describe the memory layout of a transformer's KV cache.",
    "How do GPTQ and AWQ quantization formats differ?",
    "What is the role of the scheduler in an LLM inference server?",
    "Explain the concept of flops utilization (MFU).",
    "What is DRAM bandwidth and why is it critical for LLMs?",
    "How does temperature affect token sampling?",
    "Explain nucleus (top-p) sampling.",
    "What is a mixture-of-experts (MoE) model?",
    "How does LoRA enable parameter-efficient fine-tuning?",
    "Describe the differences between BF16 and FP16.",
    "What is INT8 quantization and when does it degrade quality?",
    "How does flash decoding parallelize across the sequence dimension?",
    "Explain what prefill and decode phases mean in LLM inference.",
    "What are the design goals of the Llama model family?",
    "Describe the Mistral 7B architecture improvements.",
    "How do sliding window attention and full attention compare?",
    "What is multi-query attention (MQA)?",
    "Explain the concept of a prompt template and its importance.",
]

def _make_prompts(n: int) -> list[str]:
    return (_PROMPTS * ((n // len(_PROMPTS)) + 1))[:n]


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Self-configuring LLM telemetry agent",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "Modes:\n"
            "  standard  GPU + workload profiling, zero kernel overhead (default)\n"
            "  kernel    Short dedicated kernel breakdown run (decoupled)\n"
            "  full      Runs standard then kernel sequentially\n"
        ),
    )

    # Mode
    p.add_argument(
        "--mode", choices=["standard", "kernel", "full"], default="standard",
        help="Profiling mode",
    )

    # Server / model
    p.add_argument("--server",        default="http://localhost:8000",
                   help="vLLM / OpenAI-compatible server URL")
    p.add_argument("--model",         default="",
                   help="Model name for vLLM (defaults to config/env or Qwen/Qwen3.5-9B)")
    p.add_argument("--no-start-vllm", action="store_true",
                   help="Do not attempt to start vLLM automatically")

    # vLLM launch params (used only when agent starts vLLM)
    p.add_argument("--gpu-mem-util",  type=float, default=0.85,
                   help="vLLM --gpu-memory-utilization (when auto-starting)")
    p.add_argument("--max-model-len", type=int, default=4096,
                   help="vLLM --max-model-len (when auto-starting)")

    # GPU
    p.add_argument("--dcgm-url",   default="http://localhost:9400/metrics",
                   help="DCGM exporter URL")
    p.add_argument("--gpu-index",  type=int, default=0,
                   help="GPU device index")
    p.add_argument("--gpu-poll",   type=float, default=0.5,
                   help="GPU sampling interval in seconds")
    p.add_argument("--skip-dcgm",  action="store_true",
                   help="Skip DCGM setup (useful when Docker is not available)")

    # Workload — standard run
    p.add_argument("--num-requests", type=int, default=50,
                   help="Number of requests for the standard run")
    p.add_argument("--max-tokens",   type=int, default=200,
                   help="Max output tokens per request")
    p.add_argument("--concurrency",  type=int, default=4,
                   help="Max concurrent requests (standard run)")

    # Workload — kernel run
    p.add_argument("--kernel-requests", type=int, default=20,
                   help="Number of requests for the kernel run (kept short to limit overhead)")
    p.add_argument("--trace-dir",       default="/tmp/vllm_traces",
                   help="Directory where vLLM writes torch profiler traces")

    # Output
    p.add_argument("--output",  default="",
                   help="Base output path for JSON results (auto-generated if empty)")
    p.add_argument("--title",   default="Agent Run",
                   help="Run title for reports")

    # Upload
    p.add_argument("--no-upload", action="store_true",
                   help="Skip uploading results (results saved locally only)")

    # Omniference backend upload
    p.add_argument("--backend-url", default="",
                   help="Omniference backend URL (or set OMNI_BACKEND_URL)")
    p.add_argument("--run-id", default="",
                   help="Run UUID for profiling upload (or set OMNI_RUN_ID)")
    p.add_argument("--ingest-token", default="",
                   help="Ingest token for auth (or set OMNI_INGEST_TOKEN)")
    p.add_argument("--skip-runara", action="store_true",
                   help="Skip Runara upload (only upload to Omniference backend)")

    return p.parse_args()


# ═══════════════════════════════════════════════════════════════════════════════
# Main orchestration
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    args = parse_args()

    if not args.model:
        cfg = _load_runara_config()
        args.model = (
            os.environ.get("RUNARA_DEFAULT_MODEL", "").strip()
            or str(cfg.get("default_model", "")).strip()
            or _DEFAULT_MODEL
        )

    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  Telemetry Agent  —  mode: {args.mode}{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}")
    _info(f"Model default: {args.model}")

    checks: dict = {}
    standard_path: Path | None = None
    kernel_path:   Path | None = None

    # ── Phase 1: system check ─────────────────────────────────────────────────
    gpu_info = phase_system_check()
    checks["python"] = gpu_info["python_ok"]
    checks["driver"] = gpu_info["driver_ok"]

    if not gpu_info["python_ok"] or not gpu_info["driver_ok"]:
        _fail("Critical system check failed — cannot continue")
        phase_final_summary(checks, None, None)
        sys.exit(1)

    # ── Phase 2: Python dependencies ──────────────────────────────────────────
    checks["deps"] = phase_install_deps()
    if not checks["deps"]:
        _fail("Dependency installation failed — cannot continue")
        phase_final_summary(checks, None, None)
        sys.exit(1)

    # ── Phase 3: DCGM exporter ────────────────────────────────────────────────
    dcgm_ok = phase_setup_dcgm(gpu_info, args.dcgm_url, args.skip_dcgm)
    checks["dcgm"] = dcgm_ok if (gpu_info["is_dc"] and not args.skip_dcgm) else None

    # ── Phase 4: vLLM ─────────────────────────────────────────────────────────
    vllm = phase_ensure_vllm(
        server_url=args.server,
        model=args.model,
        trace_dir=args.trace_dir,
        auto_start=not args.no_start_vllm,
        gpu_mem_util=args.gpu_mem_util,
        max_model_len=args.max_model_len,
    )
    checks["vllm_running"]  = vllm["running"]
    checks["vllm_profiler"] = vllm["has_profiler"] if vllm["running"] else False

    if not vllm["running"]:
        _fail("vLLM is not running — cannot profile. Start it and re-run agent.py")
        phase_final_summary(checks, None, None)
        sys.exit(1)

    model = vllm["model"] or args.model

    # ── Phase 5a: standard run ────────────────────────────────────────────────
    if args.mode in ("standard", "full"):
        standard_path = phase_run_standard(
            server_url=args.server,
            model=model,
            dcgm_url=args.dcgm_url,
            gpu_index=args.gpu_index,
            num_requests=args.num_requests,
            max_tokens=args.max_tokens,
            concurrency=args.concurrency,
            gpu_poll=args.gpu_poll,
            output_path=args.output,
            title=args.title,
        )

    # ── Phase 5b: kernel run ──────────────────────────────────────────────────
    if args.mode in ("kernel", "full"):
        if not vllm["has_profiler"]:
            _warn("Skipping kernel run — vLLM profiler endpoint not available")
            _info("Restart vLLM with --profiler-config to enable kernel mode")
        else:
            kernel_path = phase_run_kernel(
                server_url=args.server,
                model=model,
                dcgm_url=args.dcgm_url,
                gpu_index=args.gpu_index,
                kernel_requests=args.kernel_requests,
                max_tokens=args.max_tokens,
                trace_dir=args.trace_dir,
                output_path=args.output,
                title=args.title,
            )

    # ── Phase 6: summary ──────────────────────────────────────────────────────
    phase_final_summary(checks, standard_path, kernel_path,
                        kernel_attempted=args.mode in ("kernel", "full"))

    # ── Phase 7: upload ─────────────────────────────────────────────────────
    if not args.no_upload:
        _phase_upload(
            standard_path, kernel_path,
            backend_url=args.backend_url,
            run_id=args.run_id,
            ingest_token=args.ingest_token,
            skip_runara=args.skip_runara,
        )


def _phase_upload(
    standard_path: "Path | None",
    kernel_path: "Path | None",
    backend_url: str = "",
    run_id: str = "",
    ingest_token: str = "",
    skip_runara: bool = False,
) -> None:
    """Upload completed run files to Omniference backend and/or Runara."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from upload import upload_if_configured, upload_to_backend_if_configured  # type: ignore[import]
    except ImportError:
        return  # upload.py not present — silently skip

    paths = [p for p in [standard_path, kernel_path] if p is not None]
    if not paths:
        return

    _head("Phase 7 — Upload")
    for path in paths:
        # Upload to Omniference backend
        upload_to_backend_if_configured(
            path,
            backend_url=backend_url,
            run_id=run_id,
            ingest_token=ingest_token,
        )
        # Upload to Runara (legacy)
        if not skip_runara:
            upload_if_configured(path, verbose=True)


if __name__ == "__main__":
    main()
