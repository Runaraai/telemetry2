#!/usr/bin/env python3
"""
upload.py - Upload telemetry JSON to the Omniference backend and/or Runara.

Usage:
    # Upload to Omniference backend (requires run_id + ingest_token):
    python upload.py /tmp/telemetry_1234.json --backend-url https://omniference.com \\
        --run-id <uuid> --ingest-token <token>

    # Upload to Runara (legacy, requires ~/.runara/config):
    python upload.py /tmp/telemetry_1234.json --label "H100 full run"

    # Upload to both:
    python upload.py /tmp/telemetry_1234.json --backend-url https://omniference.com \\
        --run-id <uuid> --ingest-token <token> --label "H100 full run"

Config sources for Omniference backend (highest priority first):
  1) CLI args: --backend-url, --run-id, --ingest-token
  2) Env vars: OMNI_BACKEND_URL, OMNI_RUN_ID, OMNI_INGEST_TOKEN

Config sources for Runara (highest priority first):
  1) Env vars: RUNARA_TOKEN, RUNARA_API_BASE, RUNARA_WEB_BASE
  2) ~/.runara/config JSON
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".runara" / "config"
ENV_TOKEN = "RUNARA_TOKEN"
ENV_API = "RUNARA_API_BASE"
ENV_WEB = "RUNARA_WEB_BASE"

# Omniference backend env vars
ENV_OMNI_URL = "OMNI_BACKEND_URL"
ENV_OMNI_RUN_ID = "OMNI_RUN_ID"
ENV_OMNI_TOKEN = "OMNI_INGEST_TOKEN"


class ConfigError(Exception):
    pass


def _read_config_file() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def load_config() -> dict:
    """Load API token/base URL from env or ~/.runara/config."""
    file_cfg = _read_config_file()
    token = os.environ.get(ENV_TOKEN) or file_cfg.get("api_token", "")
    api_base = os.environ.get(ENV_API) or file_cfg.get("api_base", "")
    web_base = os.environ.get(ENV_WEB) or file_cfg.get("web_base", "")

    token = token.strip()
    api_base = api_base.strip().rstrip("/")
    web_base = web_base.strip().rstrip("/")

    if not token:
        raise ConfigError(
            "No API token found.\n"
            f"  Set {ENV_TOKEN} or run install.sh.\n"
            "  Get token at Runara dashboard -> Account."
        )
    if not api_base:
        raise ConfigError(
            "No API base URL found.\n"
            f"  Set {ENV_API} or run install.sh."
        )

    return {"api_token": token, "api_base": api_base, "web_base": web_base}


def is_configured() -> bool:
    try:
        load_config()
        return True
    except ConfigError:
        return False


def _derive_dashboard_base(api_base: str, web_base: str) -> str:
    """Choose dashboard base URL without producing incorrect execute-api links."""
    if web_base:
        return web_base.rstrip("/")
    if api_base.endswith("/api"):
        return api_base[:-4].rstrip("/")
    if "execute-api." in api_base:
        return ""
    return api_base.rstrip("/")


def _candidate_api_bases(api_base: str) -> list[str]:
    """
    Return plausible API bases for both deployment shapes:
      - CloudFront proxy: https://<site>/api
      - API Gateway URL:  https://<id>.execute-api... (no /api prefix)
    """
    base = api_base.rstrip("/")
    no_api = base[:-4].rstrip("/") if base.endswith("/api") else base
    with_api = f"{no_api}/api"

    if base.endswith("/api"):
        ordered = [base, no_api]
    elif "execute-api." in no_api:
        ordered = [no_api, with_api]
    else:
        ordered = [with_api, no_api]

    out: list[str] = []
    for item in ordered:
        if item and item not in out:
            out.append(item)
    return out


def _post_api_json(
    api_bases: list[str],
    endpoint: str,
    token: str,
    payload: dict,
    step: str,
    prefer_base: str = "",
    timeout: int = 15,
) -> tuple[dict, str]:
    """POST JSON to one of the candidate API bases, falling back on 404."""
    endpoint = endpoint.lstrip("/")
    ordered: list[str] = []
    if prefer_base:
        ordered.append(prefer_base.rstrip("/"))
    for base in api_bases:
        b = base.rstrip("/")
        if b not in ordered:
            ordered.append(b)

    for i, base in enumerate(ordered):
        url = f"{base}/{endpoint}"
        req = urllib.request.Request(
            url,
            method="POST",
            headers={"X-Api-Token": token, "Content-Type": "application/json"},
            data=json.dumps(payload).encode(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return (json.loads(raw) if raw else {}), base
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404 and i < (len(ordered) - 1):
                continue
            raise RuntimeError(f"{step} failed ({exc.code}) at {url}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach API at {base}: {exc.reason}") from exc

    raise RuntimeError(f"{step} failed: no reachable API endpoint for base {api_bases[0]}")


def upload(json_path: Path, label: str = "") -> tuple[str, Optional[str]]:
    """
    Upload telemetry JSON to Runara.

    Returns (run_id, dashboard_url_or_none).
    Raises ConfigError for missing configuration.
    """
    cfg = load_config()
    token = cfg["api_token"]
    api_base = cfg["api_base"]
    web_base = cfg["web_base"]

    raw_bytes = json_path.read_bytes()
    try:
        data = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {json_path}: {exc}") from exc

    api_bases = _candidate_api_bases(api_base)

    # Step 1: get presigned URL
    presign, active_api_base = _post_api_json(
        api_bases=api_bases,
        endpoint="presign",
        token=token,
        payload={},
        step="presign",
    )

    run_id = presign["run_id"]
    put_url = presign["url"]

    # Step 2: upload JSON directly to S3
    put_req = urllib.request.Request(
        put_url,
        method="PUT",
        data=raw_bytes,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(put_req, timeout=120):
            pass
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"S3 PUT failed ({exc.code}): {body}") from exc

    # Step 3: register run metadata
    workload = data.get("workload", {})
    run_meta = data.get("run_metadata", {})
    bottleneck = data.get("bottleneck", {})
    metadata = {
        "run_id": run_id,
        "timestamp": str(data.get("timestamp", "")),
        "model": workload.get("model", ""),
        "gpu_name": run_meta.get("gpu_name", ""),
        "duration_s": float(workload.get("duration_s", 0)),
        "mode": label or data.get("title", "standard"),
        "ttft_p95_ms": float(workload.get("ttft_p95_ms", 0)),
        "tokens_per_sec": float(workload.get("tokens_per_sec_total", 0)),
        "bottleneck": bottleneck.get("primary", "unknown"),
        "size_bytes": len(raw_bytes),
    }

    _post_api_json(
        api_bases=api_bases,
        endpoint="runs",
        token=token,
        payload=metadata,
        step="register-run",
        prefer_base=active_api_base,
    )

    dashboard_base = _derive_dashboard_base(api_base=api_base, web_base=web_base)
    dashboard_url = f"{dashboard_base}/runs/{run_id}" if dashboard_base else None
    return run_id, dashboard_url


def upload_if_configured(
    json_path: Path,
    label: str = "",
    verbose: bool = True,
) -> Optional[str]:
    """
    Upload JSON if token/API is configured.
    Returns dashboard URL when available; otherwise None.
    """
    reset = "\033[0m"
    green = "\033[32m"
    yellow = "\033[33m"
    cyan = "\033[36m"

    try:
        load_config()
    except ConfigError:
        if verbose:
            print(f"  {cyan}·{reset}  No Runara token/API config - run saved locally only")
            print(f"  {cyan}·{reset}  Run install.sh to configure upload")
        return None

    try:
        if verbose:
            print(f"  {cyan}·{reset}  Uploading {json_path.name} to Runara ...")
        run_id, dashboard_url = upload(json_path, label=label)
        if verbose:
            print(f"  {green}✓{reset}  Upload complete (run_id: {run_id})")
            if dashboard_url:
                print(f"  {green}✓{reset}  Dashboard: {dashboard_url}")
            else:
                print(f"  {yellow}!{reset}  Dashboard URL unknown. Set RUNARA_WEB_BASE or web_base in ~/.runara/config.")
        return dashboard_url
    except Exception as exc:
        if verbose:
            print(f"  {yellow}!{reset}  Upload failed (run saved locally): {exc}")
        return None


# ── Omniference backend upload ────────────────────────────────────────────────


def _transform_agent_json_to_profile_payload(data: dict) -> dict:
    """Transform agent.py/report.py JSON output into ProfileUpload schema format.

    The agent JSON has slightly different field names than the backend's
    ProfileUpload Pydantic schema. This function maps between them.
    """
    payload: dict = {}

    # Workload metrics
    w = data.get("workload")
    if w:
        payload["workload"] = {
            "model_name": w.get("model"),
            "server_url": w.get("server_url"),
            "concurrency": w.get("concurrency"),
            "num_requests": w.get("total_requests"),
            "successful_requests": w.get("successful"),
            "failed_requests": w.get("failed"),
            "duration_s": w.get("duration_s"),
            "ttft_mean_ms": w.get("ttft_mean_ms"),
            "ttft_p50_ms": w.get("ttft_p50_ms"),
            "ttft_p95_ms": w.get("ttft_p95_ms"),
            "ttft_p99_ms": w.get("ttft_p99_ms"),
            "tpot_mean_ms": w.get("tpot_mean_ms"),
            "tpot_p50_ms": w.get("tpot_p50_ms"),
            "tpot_p95_ms": w.get("tpot_p95_ms"),
            "tpot_p99_ms": w.get("tpot_p99_ms"),
            "e2e_latency_mean_ms": w.get("e2e_latency_mean_ms"),
            "e2e_latency_p99_ms": w.get("e2e_latency_p99_ms"),
            "throughput_req_sec": w.get("requests_per_sec"),
            "throughput_tok_sec": w.get("tokens_per_sec_total"),
            "total_input_tokens": w.get("total_input_tokens"),
            "total_output_tokens": w.get("total_output_tokens"),
        }
        logger.info("Mapped workload section: num_requests=%s, throughput_tok_sec=%s",
                    payload["workload"].get("num_requests"), payload["workload"].get("throughput_tok_sec"))
    else:
        logger.warning("Agent JSON missing workload section")

    # Kernel profile
    k = data.get("kernel")
    if k:
        categories = []
        for cat in k.get("categories", []):
            categories.append({
                "category": cat.get("category", ""),
                "total_ms": cat.get("total_ms", 0),
                "pct": cat.get("pct", 0),
                "kernel_count": cat.get("count", 0),
            })
        payload["kernel"] = {
            "total_cuda_ms": k.get("total_cuda_ms"),
            "total_flops": None,  # not in agent output; derived from estimated_tflops
            "estimated_tflops": k.get("estimated_tflops"),
            "profiled_requests": str(k.get("profiled_requests", "")),
            "trace_source": k.get("trace_source"),
            "categories": categories,
        }
        logger.info("Mapped kernel section: total_cuda_ms=%s, categories=%d",
                    k.get("total_cuda_ms"), len(categories))
    else:
        logger.debug("Agent JSON missing kernel section")

    # Bottleneck analysis
    b = data.get("bottleneck")
    if b:
        gpu = data.get("gpu", {})
        payload["bottleneck"] = {
            "primary_bottleneck": b.get("primary", "unknown"),
            "compute_util_pct": b.get("compute_util_pct"),
            "sm_active_mean_pct": b.get("sm_active_mean_pct"),
            "memory_bw_util_pct": b.get("memory_bw_util_pct"),
            "hbm_bw_mean_gbps": b.get("hbm_bw_mean_gbps"),
            "cpu_overhead_estimated_pct": b.get("cpu_overhead_estimated_pct"),
            "nvlink_util_pct": b.get("nvlink_util_pct"),
            "arithmetic_intensity": b.get("arithmetic_intensity"),
            "roofline_bound": b.get("roofline_bound"),
            "mfu_pct": gpu.get("mfu_pct"),
            "actual_tflops": gpu.get("actual_tflops"),
            "peak_tflops_bf16": gpu.get("theoretical_tflops_bf16"),
            "recommendations": b.get("recommendations"),
        }
        logger.info("Mapped bottleneck section: primary=%s, mfu_pct=%s",
                    payload["bottleneck"].get("primary_bottleneck"),
                    payload["bottleneck"].get("mfu_pct"))
    else:
        logger.warning("Agent JSON missing bottleneck section")

    # GPU aggregates and time series (full section for backend)
    gpu_section = data.get("gpu")
    if gpu_section:
        payload["gpu"] = gpu_section
        samples = gpu_section.get("samples", 0)
        util = gpu_section.get("util_mean_pct")
        logger.info("Mapped GPU section: samples=%s, util_mean_pct=%s",
                    samples, util)
    else:
        logger.warning("Agent JSON missing GPU section - no aggregates/time_series will be stored")

    # Run metadata (passed through as-is)
    rm = data.get("run_metadata")
    if rm:
        payload["run_metadata"] = rm

    return payload


def upload_to_backend(
    json_path: Path,
    backend_url: str,
    run_id: str,
    ingest_token: str,
) -> bool:
    """Upload profiling JSON to the Omniference backend.

    Args:
        json_path: Path to the agent's telemetry JSON file.
        backend_url: Base URL of the backend (e.g. https://omniference.com).
        run_id: UUID of the run to upload to.
        ingest_token: Ingest token for authentication.

    Returns:
        True if upload succeeded, False otherwise.
    """
    data = json.loads(json_path.read_bytes())
    payload = _transform_agent_json_to_profile_payload(data)

    url = f"{backend_url.rstrip('/')}/api/telemetry/profiling/runs/{run_id}"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Ingest-Token": ingest_token,
        },
        data=json.dumps(payload).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Backend upload failed ({exc.code}) at {url}: {body}"
        ) from exc


def upload_to_backend_if_configured(
    json_path: Path,
    backend_url: str = "",
    run_id: str = "",
    ingest_token: str = "",
    verbose: bool = True,
) -> bool:
    """Upload to Omniference backend if credentials are available.

    Checks CLI args first, then env vars. Returns True if uploaded.
    """
    reset = "\033[0m"
    green = "\033[32m"
    yellow = "\033[33m"
    cyan = "\033[36m"

    url = backend_url or os.environ.get(ENV_OMNI_URL, "").strip()
    rid = run_id or os.environ.get(ENV_OMNI_RUN_ID, "").strip()
    token = ingest_token or os.environ.get(ENV_OMNI_TOKEN, "").strip()

    if not url or not rid or not token:
        if verbose:
            print(f"  {cyan}·{reset}  No Omniference backend config — skipping backend upload")
            print(f"  {cyan}·{reset}  Set OMNI_BACKEND_URL, OMNI_RUN_ID, OMNI_INGEST_TOKEN or use CLI args")
        return False

    try:
        if verbose:
            print(f"  {cyan}·{reset}  Uploading {json_path.name} to Omniference backend ...")
        upload_to_backend(json_path, url, rid, token)
        if verbose:
            print(f"  {green}✓{reset}  Backend upload complete (run_id: {rid})")
        return True
    except Exception as exc:
        if verbose:
            print(f"  {yellow}!{reset}  Backend upload failed: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload telemetry JSON to Omniference backend and/or Runara",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("json_path", type=Path, help="Path to telemetry JSON")
    parser.add_argument("--label", default="", help="Optional run label/title (Runara)")

    # Omniference backend args
    parser.add_argument("--backend-url", default="",
                        help="Omniference backend URL (or set OMNI_BACKEND_URL)")
    parser.add_argument("--run-id", default="",
                        help="Run UUID for profiling upload (or set OMNI_RUN_ID)")
    parser.add_argument("--ingest-token", default="",
                        help="Ingest token for auth (or set OMNI_INGEST_TOKEN)")
    parser.add_argument("--skip-runara", action="store_true",
                        help="Skip Runara upload (only upload to Omniference backend)")

    args = parser.parse_args()

    if not args.json_path.exists():
        sys.exit(f"File not found: {args.json_path}")

    any_upload = False

    # Upload to Omniference backend
    if upload_to_backend_if_configured(
        args.json_path,
        backend_url=args.backend_url,
        run_id=args.run_id,
        ingest_token=args.ingest_token,
    ):
        any_upload = True

    # Upload to Runara (legacy)
    if not args.skip_runara:
        result = upload_if_configured(args.json_path, label=args.label)
        if result:
            any_upload = True

    if not any_upload:
        print("  ! No upload target configured. Run saved locally only.")
        print("  ! Set --backend-url/--run-id/--ingest-token for Omniference backend")
        print("  ! Or set RUNARA_TOKEN/RUNARA_API_BASE for Runara")


if __name__ == "__main__":
    main()
