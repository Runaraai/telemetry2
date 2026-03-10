#!/usr/bin/env python3
"""
setup.py — Automated GPU instance setup for the telemetry tool.

Run this once on a GPU instance before using telemetry_run.py.

What it does:
  1. Checks Python version and NVIDIA driver
  2. Detects GPU model and tier (data-centre vs consumer)
  3. Installs Python dependencies (pynvml, requests, aiohttp)
  4. Starts DCGM exporter via Docker (data-centre GPUs only)
  5. Checks if vLLM is running and prints the recommended start command
  6. Verifies the profiler endpoint is reachable
  7. Runs a 3-request smoke test and saves a sample JSON
  8. Prints a final summary of what is working and what is not

Usage:
    python setup.py [--server http://localhost:8000] [--dcgm-url http://localhost:9400/metrics]
                    [--skip-dcgm] [--skip-vllm-check] [--smoke-test] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"

def _ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def _warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def _fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def _info(msg): print(f"  {CYAN}·{RESET}  {msg}")
def _head(msg): print(f"\n{BOLD}{msg}{RESET}")
def _cmd(cmd):  print(f"     {CYAN}${RESET} {cmd}")

# Data-centre GPU name substrings (lowercase). These support DCGM profiling counters.
_DC_GPU_NAMES = [
    "h100", "h200", "b100", "b200",
    "a100", "a30", "a40", "a10g",
    "l40s", "l40",
    "v100",
    "tesla",
]


def _is_dc_gpu(gpu_name: str) -> bool:
    n = gpu_name.lower()
    return any(k in n for k in _DC_GPU_NAMES)


def _run(cmd: list[str], capture: bool = True) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True, timeout=30)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return 1, str(e)


def _pip_install(packages: list[str]) -> bool:
    code, out = _run([sys.executable, "-m", "pip", "install", "--quiet", *packages])
    return code == 0


def _try_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(4096).decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


# ── Step 1 — Python & driver ──────────────────────────────────────────────────

def check_python() -> bool:
    _head("Step 1 — Python & NVIDIA driver")
    ok = True

    if sys.version_info < (3, 9):
        _fail(f"Python {sys.version_info.major}.{sys.version_info.minor} — need 3.9+")
        ok = False
    else:
        _ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    code, out = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                       "--format=csv,noheader"])
    if code != 0:
        _fail("nvidia-smi not found or failed — is the NVIDIA driver installed?")
        ok = False
    else:
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                _ok(f"GPU: {parts[0]}  |  Driver: {parts[1]}  |  VRAM: {parts[2]}")
            else:
                _ok(f"GPU detected: {line}")

    return ok


# ── Step 2 — GPU model & tier detection ───────────────────────────────────────

def detect_gpu() -> dict:
    _head("Step 2 — GPU model & tier")

    result = {"name": "", "is_dc": False, "count": 0, "vram_mib": 0}

    code, out = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                       "--format=csv,noheader"])
    if code != 0:
        _fail("Could not query GPU info")
        return result

    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    result["count"] = len(lines)

    if lines:
        parts = [p.strip() for p in lines[0].split(",")]
        result["name"] = parts[0] if parts else ""
        if len(parts) > 1:
            try:
                result["vram_mib"] = int(parts[1].replace("MiB", "").strip())
            except ValueError:
                pass

    result["is_dc"] = _is_dc_gpu(result["name"])

    _ok(f"GPU model  : {result['name']}")
    _ok(f"GPU count  : {result['count']}")
    _ok(f"VRAM       : {result['vram_mib']:,} MiB")

    if result["is_dc"]:
        _ok("Tier       : Data-centre — DCGM profiling counters available")
    else:
        _warn("Tier       : Consumer / workstation — DCGM profiling counters not available")
        _info("NVML backend will be used: util, power, VRAM, temp, PCIe — no SM Active/Tensor/DRAM")

    # Look up spec constants
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from telemetry.gpu.specs import get_gpu_specs
        specs = get_gpu_specs(result["name"])
        if specs["peak_tflops_bf16"] > 0:
            _ok(f"Spec       : {specs['peak_tflops_bf16']} TF BF16  |  "
                f"{specs['peak_hbm_bw_gbps']} GB/s HBM BW  |  "
                f"{specs['nvlink_bw_gbps']} GB/s NVLink")
        else:
            _warn("Spec       : GPU not in specs.py — MFU and HBM BW util will be 0.0")
            _info("Add this GPU to scripts/telemetry/gpu/specs.py for derived metrics")
    except Exception:
        _warn("Could not load specs.py")

    return result


# ── Step 3 — Python dependencies ──────────────────────────────────────────────

def install_deps() -> bool:
    _head("Step 3 — Python dependencies")
    all_ok = True

    deps = {
        "pynvml":  "nvidia-ml-py3",
        "requests": "requests",
        "aiohttp":  "aiohttp",
    }

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


# ── Step 4 — DCGM exporter ────────────────────────────────────────────────────

def setup_dcgm(gpu: dict, dcgm_url: str, skip: bool) -> bool:
    _head("Step 4 — DCGM exporter")

    if skip:
        _info("Skipped (--skip-dcgm)")
        return True

    if not gpu["is_dc"]:
        _info("Consumer GPU — DCGM not applicable, skipping")
        return True

    # Check if already running
    host = dcgm_url.split("/metrics")[0]
    code, body = _http_get(f"{host}/metrics")
    if code == 200 and "DCGM_FI_DEV" in body:
        _ok(f"DCGM exporter already running at {dcgm_url}")
        if "DCGM_FI_PROF_SM_ACTIVE" in body:
            _ok("Profiling counters confirmed (SM Active, Tensor, DRAM)")
        else:
            _warn("Profiling counters not present — may need custom counter config")
            _info("See: https://github.com/NVIDIA/dcgm-exporter#changing-metrics")
        return True

    _info("DCGM exporter not running — attempting to start via Docker ...")

    # Check Docker
    code, _ = _run(["docker", "info"])
    if code != 0:
        _fail("Docker not available")
        _info("Start DCGM manually:")
        _cmd("docker run -d --gpus all --rm -p 9400:9400 nvcr.io/nvidia/k8s/dcgm-exporter:latest")
        _info("Or install the native dcgm-exporter binary:")
        _cmd("apt-get install -y datacenter-gpu-manager && nv-hostengine && dcgm-exporter &")
        return False

    _info("Starting DCGM exporter (Docker) ...")
    code, out = _run([
        "docker", "run", "-d",
        "--name", "dcgm-exporter",
        "--gpus", "all",
        "--rm",
        "-p", "9400:9400",
        "nvcr.io/nvidia/k8s/dcgm-exporter:latest",
    ])

    if code != 0 and "already in use" not in out:
        _fail(f"Docker run failed: {out[:200]}")
        return False

    # Wait for it to start
    _info("Waiting for DCGM exporter to initialise (up to 15s) ...")
    for _ in range(15):
        time.sleep(1)
        status, body = _http_get(f"{host}/metrics")
        if status == 200 and "DCGM_FI_DEV" in body:
            _ok("DCGM exporter is up")
            if "DCGM_FI_PROF_SM_ACTIVE" in body:
                _ok("Profiling counters confirmed")
            else:
                _warn("Profiling counters absent — consumer GPU or missing counter config")
            return True

    _fail("DCGM exporter did not become ready in 15s")
    _info(f"Check:  docker logs dcgm-exporter")
    _info(f"Manual verify:  curl {dcgm_url} | grep DCGM_FI_DEV_GPU_UTIL")
    return False


# ── Step 5 — vLLM check ───────────────────────────────────────────────────────

def check_vllm(server_url: str, skip: bool) -> dict:
    _head("Step 5 — vLLM server")

    result = {"running": False, "model": "", "has_profiler": False}

    if skip:
        _info("Skipped (--skip-vllm-check)")
        return result

    # Check /v1/models
    code, body = _http_get(f"{server_url}/v1/models")
    if code != 200:
        _fail(f"vLLM not reachable at {server_url}")
        _info("Start vLLM with kernel profiling support:")
        _cmd(f'vllm serve <model> --host 0.0.0.0 --port 8000 --enforce-eager \\')
        _cmd( '  --profiler-config \'{"profiler":"torch","torch_profiler_dir":"/tmp/vllm_traces",')
        _cmd( '                      "torch_profiler_with_flops":true,"torch_profiler_use_gzip":false}\'')
        _info("Or without kernel profiling (use --no-kernel when running telemetry_run.py):")
        _cmd("vllm serve <model> --host 0.0.0.0 --port 8000 --enforce-eager")
        return result

    result["running"] = True
    try:
        data = json.loads(body)
        models = data.get("data", [])
        if models:
            result["model"] = models[0].get("id", "")
    except Exception:
        pass

    _ok(f"vLLM running at {server_url}")
    if result["model"]:
        _ok(f"Model: {result['model']}")

    # Check profiler endpoint
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{server_url}/start_profile", method="POST", data=b""
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status == 200:
                result["has_profiler"] = True
                # Immediately stop so we don't leave it running.
                # Use a long timeout — vLLM 0.16+ flushes the trace before responding.
                stop_req = urllib.request.Request(
                    f"{server_url}/stop_profile", method="POST", data=b""
                )
                try:
                    urllib.request.urlopen(stop_req, timeout=120)
                except Exception:
                    pass
    except Exception:
        pass

    if result["has_profiler"]:
        _ok("Kernel profiler endpoint (/start_profile) reachable")
    else:
        _warn("Kernel profiler endpoint not reachable — kernel metrics will be unavailable")
        _info("Restart vLLM with --profiler-config to enable kernel profiling")

    return result


# ── Step 6 — Smoke test ───────────────────────────────────────────────────────

def smoke_test(server_url: str, dcgm_url: str, output_path: str) -> bool:
    _head("Step 6 — Smoke test (3 requests)")

    sys.path.insert(0, str(Path(__file__).parent))

    try:
        import asyncio
        from telemetry import (TelemetryRunner, VLLMOpenAIBackend,
                               AutoGpuBackend, print_report, save_json)
        from telemetry.gpu.base import GpuBackend, GpuSample

        # Build GPU backend
        try:
            gpu_backend = AutoGpuBackend(dcgm_url=dcgm_url)
            _ok(f"GPU backend: {gpu_backend.describe()}")
        except RuntimeError as e:
            _warn(f"GPU backend unavailable ({e}) — using no-op")
            class _Noop(GpuBackend):
                name = "noop"
                capabilities = []
                def collect(self): return None
                @classmethod
                def is_available(cls, **kw): return True
                def describe(self): return "disabled"
            gpu_backend = _Noop()

        workload = VLLMOpenAIBackend(
            server_url=server_url,
            max_concurrent=2,
        )

        runner = TelemetryRunner(
            gpu_backend=gpu_backend,
            workload_backend=workload,
            kernel_backend=None,   # skip kernel for smoke test
            gpu_poll_s=0.5,
        )

        prompts = [
            "What is the attention mechanism in transformers?",
            "Explain GPU memory hierarchy briefly.",
            "What is tensor parallelism?",
        ]

        _info("Running 3 inference requests ...")
        result = asyncio.run(runner.run(prompts=prompts, max_tokens=64, verbose=False))

        if result.workload and result.workload.successful > 0:
            _ok(f"Requests completed: {result.workload.successful}/3")
            _ok(f"TTFT mean: {result.workload.mean_ttft_ms:.0f} ms  |  "
                f"tok/s: {result.workload.total_tokens_per_sec:.0f}")
        else:
            _fail("No successful requests — check vLLM logs")
            return False

        saved = save_json(result, output_path=output_path, title="smoke-test")
        _ok(f"Sample JSON saved → {saved}")

        # Quick schema check
        doc = json.loads(saved.read_text())
        required = {"title", "timestamp", "run_metadata", "workload", "gpu", "bottleneck"}
        missing = required - set(doc.keys())
        if missing:
            _warn(f"JSON missing keys: {missing}")
        else:
            _ok("JSON schema validated (all required keys present)")

        return True

    except ImportError as e:
        _fail(f"Import error: {e}")
        _info("Ensure you are running from the scripts/ directory")
        return False
    except Exception as e:
        _fail(f"Smoke test failed: {e}")
        return False


# ── Step 7 — Summary ──────────────────────────────────────────────────────────

def print_summary(checks: dict) -> None:
    _head("Setup Summary")
    print()

    rows = [
        ("Python 3.9+",        checks.get("python")),
        ("NVIDIA driver",       checks.get("driver")),
        ("Python deps",         checks.get("deps")),
        ("DCGM exporter",       checks.get("dcgm")),
        ("vLLM running",        checks.get("vllm_running")),
        ("Kernel profiler",     checks.get("vllm_profiler")),
        ("Smoke test",          checks.get("smoke")),
    ]

    for label, status in rows:
        if status is True:
            _ok(f"{label:<22} ready")
        elif status is False:
            _fail(f"{label:<22} NOT ready")
        else:
            _info(f"{label:<22} skipped / unknown")

    print()

    # Overall verdict
    critical = [checks.get("python"), checks.get("driver"), checks.get("deps")]
    if all(critical):
        if checks.get("vllm_running"):
            print(f"  {GREEN}{BOLD}Ready to collect telemetry.{RESET}  Run:")
            _cmd("python telemetry_run.py --output /tmp/my_run.json --title 'My run'")
            if not checks.get("vllm_profiler"):
                _info("Kernel profiling unavailable — add --no-kernel flag, or restart vLLM with --profiler-config")
        else:
            _warn("Start vLLM first, then run telemetry_run.py")
    else:
        _fail("Critical checks failed — resolve the issues above before running telemetry")

    print()


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Set up a GPU instance for LLM telemetry collection",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--server",           default="http://localhost:8000",
                   help="vLLM server URL to check")
    p.add_argument("--dcgm-url",         default="http://localhost:9400/metrics",
                   help="DCGM exporter URL")
    p.add_argument("--skip-dcgm",        action="store_true",
                   help="Skip DCGM setup (use if Docker is unavailable)")
    p.add_argument("--skip-vllm-check",  action="store_true",
                   help="Skip vLLM reachability check")
    p.add_argument("--smoke-test",       action="store_true",
                   help="Run a 3-request smoke test after setup (requires vLLM running)")
    p.add_argument("--smoke-output",     default="/tmp/telemetry_smoke.json",
                   help="Output path for smoke test JSON")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    print(f"\n{BOLD}{'═' * 58}{RESET}")
    print(f"{BOLD}  Telemetry GPU Instance Setup{RESET}")
    print(f"{BOLD}{'═' * 58}{RESET}")

    checks: dict = {}

    # Step 1 — Python & driver
    ok = check_python()
    checks["python"] = ok
    checks["driver"] = ok  # nvidia-smi check is inside check_python

    # Step 2 — GPU detection
    gpu = detect_gpu()

    # Step 3 — Python deps
    checks["deps"] = install_deps()

    # Step 4 — DCGM
    dcgm_ok = setup_dcgm(gpu, args.dcgm_url, args.skip_dcgm)
    checks["dcgm"] = dcgm_ok if (gpu["is_dc"] and not args.skip_dcgm) else None

    # Step 5 — vLLM
    vllm = check_vllm(args.server, args.skip_vllm_check)
    checks["vllm_running"]  = vllm["running"]  if not args.skip_vllm_check else None
    checks["vllm_profiler"] = vllm["has_profiler"] if vllm["running"] else None

    # Step 6 — Smoke test (opt-in)
    if args.smoke_test:
        if not vllm["running"]:
            _head("Step 6 — Smoke test")
            _fail("Skipping — vLLM is not running")
            checks["smoke"] = False
        else:
            checks["smoke"] = smoke_test(args.server, args.dcgm_url, args.smoke_output)
    else:
        _head("Step 6 — Smoke test")
        _info("Skipped (pass --smoke-test to run a live 3-request verification)")

    # Summary
    print_summary(checks)


if __name__ == "__main__":
    main()
