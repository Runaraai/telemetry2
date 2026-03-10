#!/usr/bin/env python3
"""
upload.py - Upload telemetry JSON to the Runara platform.

Usage:
    python upload.py /tmp/telemetry_1234.json
    python upload.py /tmp/telemetry_1234.json --label "H100 full run"

Config sources (highest priority first):
  1) Env vars:
       RUNARA_TOKEN
       RUNARA_API_BASE
       RUNARA_WEB_BASE (optional, used for dashboard links)
  2) ~/.runara/config JSON:
       {
         "api_token": "...",
         "api_base": "https://...",
         "web_base": "https://... (optional)"
       }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path.home() / ".runara" / "config"
ENV_TOKEN = "RUNARA_TOKEN"
ENV_API = "RUNARA_API_BASE"
ENV_WEB = "RUNARA_WEB_BASE"


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload telemetry JSON to Runara",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("json_path", type=Path, help="Path to telemetry JSON")
    parser.add_argument("--label", default="", help="Optional run label/title")
    args = parser.parse_args()

    if not args.json_path.exists():
        sys.exit(f"File not found: {args.json_path}")

    print(f"  · Uploading {args.json_path.name} ...")
    try:
        run_id, dashboard_url = upload(args.json_path, label=args.label)
        print(f"  ✓ Upload complete (run_id: {run_id})")
        if dashboard_url:
            print(f"  → Dashboard: {dashboard_url}")
        else:
            print("  ! Dashboard URL unknown (set RUNARA_WEB_BASE or web_base in ~/.runara/config)")
    except ConfigError as exc:
        sys.exit(str(exc))
    except Exception as exc:
        sys.exit(f"Upload failed: {exc}")


if __name__ == "__main__":
    main()
