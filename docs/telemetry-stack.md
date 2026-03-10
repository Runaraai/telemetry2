# Omniference Telemetry Stack

Plain-language system design notes for the GPU telemetry feature. Covers architecture, data flow, dependencies, profiling requirements, and operational guidance.

---

## 1. High-Level Overview

- **Purpose:** Observe NVIDIA GPU fleets during remote workloads (e.g., vLLM benchmarks) without manually installing monitoring agents.
- **Control Plane:** FastAPI backend + React frontend hosted at `https://voertx.cloud`.
- **Data Plane:** On-demand Docker Compose bundle deployed over SSH to each target GPU host.
- **Storage & Query:** TimescaleDB (PostgreSQL) holds ingested metrics; FastAPI exposes REST + WebSocket endpoints; frontend renders time-series charts.

---

## 2. End-to-End Flow

1. **User action (frontend):** “Start Monitoring” submits an API request containing instance metadata, SSH credentials, polling interval, backend URL, and `enable_profiling` flag.
2. **Backend orchestration (`telemetry/deployment.py`):**
   - Generates a temporary deployment directory under `/tmp/gpu-telemetry-<run-id>` on the remote host.
   - Writes `docker-compose.yml`, exporter scripts, Prometheus config, collectors CSV, and a `check_prerequisites.sh` script.
   - Runs prerequisites script (installs DCGM, Fabric Manager, configures kernel profiling flag, regenerates CDI spec).
   - Boots the monitoring stack via `docker compose up -d`.
3. **Metrics collection (remote host services):**
   - `dcgm-exporter`: NVIDIA official exporter (profiling optional).
   - `nvidia-smi-exporter.py`: Python script streaming `nvidia-smi` fields.
   - `dcgm-health-exporter.py`: Python script for config, health, ECC, throttle counters.
   - `token-exporter.py`: Custom app-level metrics (tokens/sec etc.).
   - `prometheus`: Local scraper that forwards all metrics to control plane via remote_write.
4. **Ingestion pipeline (backend):**
   - `telemetry/routes/remote_write.py` receives Prometheus protobuf payloads.
     - **Rate limiting**: Per-run_id rate limiting (200 req/s with 400 burst)
     - **Circuit breaker**: Protects against database failures (opens after 5 failures)
   - `telemetry/remote_write.py` maps DCGM/NVIDIA field names to internal schema (`MetricSample`).
     - **Async parsing**: CPU-bound protobuf parsing offloaded to thread pool (4 workers) to prevent GIL blocking
   - `telemetry/repository.py` persists rows into TimescaleDB `gpu_metrics`.
     - **Chunked insertion**: Metrics inserted in batches of 100 samples per transaction
     - Prevents long-running transactions and lock contention
   - Optional policy checks create events in `gpu_policy_events`.
   - **Live broadcasting**: Metrics published to `LiveMetricsBroker` (in-memory or Redis pub/sub)
5. **Visualization:**
   - REST endpoints provide historical metrics.
   - WebSocket (`/ws/runs/{run_id}/live`) streams inserted samples to `TelemetryTab.jsx` for live charts.

---

## 3. Key Modules & Responsibilities

| Layer | File(s) | Responsibilities |
| --- | --- | --- |
| Frontend | `frontend/src/components/TelemetryTab.jsx` | UI for instance selection, start/stop, profiling consent, chart rendering |
| Frontend | `frontend/src/services/api.js` | Axios wrappers for run management, deployment control, metrics retrieval |
| Backend API | `backend/telemetry/routes/*.py` | REST routes for runs, deployments, health, remote write |
| Deployment | `backend/telemetry/deployment.py` | SSH orchestration, compose generation, prerequisites |
| Parsing | `backend/telemetry/remote_write.py` | Prometheus series → structured metrics mapping |
| Persistence | `backend/telemetry/models.py`, `repository.py`, `migrations/bootstrap.py` | ORM models, chunked batch writes (100 samples/transaction), schema migrations |
| Eventing | `backend/telemetry/services/policy_monitor.py` | Evaluates samples against thresholds (thermal, ECC, etc.) |
| Rate Limiting | `backend/telemetry/rate_limiter.py` | Per-run_id sliding window rate limiter (200 req/s, 400 burst) |
| Circuit Breaker | `backend/telemetry/circuit_breaker.py` | Database write circuit breaker (5 failure threshold, 30s recovery) |
| Live Broker | `backend/telemetry/realtime.py` | In-memory or Redis pub/sub broker for WebSocket distribution |

---

## 4. Remote Deployment Bundle (Docker Compose)

Each monitoring run launches a dedicated stack (service names prefixed by run ID):

| Service | Image | Notes |
| --- | --- | --- |
| `dcgm-exporter` | `nvcr.io/nvidia/k8s/dcgm-exporter:4.2.0-4.1.0-ubuntu22.04` | Collects `DCGM_FI_*` and optional `DCGM_FI_PROF_*` fields. Requires privileged access and `/dev/nvidia*` bindings. |
| `nvidia-smi-exporter` | `python:3.11-slim` | Wraps `nvidia-smi` CLI; supplements metrics not exposed via DCGM (overall GPU util, memory util). |
| `dcgm-health-exporter` | `python:3.11-slim` | Scrapes config, ECC, throttle status via `nvidia-smi --query`. |
| `token-exporter` | `python:3.11-slim` | Emits workload tokens/throughput (application specific). |
| `prometheus` | `prom/prometheus:v2.48.0` | Scrapes above services on localhost; remote_write to control plane. |

Runtime characteristics:
- All GPU-aware services run `privileged`, mount `/dev/nvidia*`, and share host networking where needed to reach GPUs.
- `DCGM_EXPORTER_INTERVAL` is `5000ms` by default; drops to `1000ms` when profiling metrics requested.
- Compose stacks bind ports `9400`-`9403` and `9090`; multiple simultaneous stacks will clash.

---

## 5. Profiling Mode vs Standard Mode

| Aspect | Standard Monitoring | Profiling Mode Enabled |
| --- | --- | --- |
| Metrics | GPU util, mem util, power, temperatures, ECC, PCIe total, clocks, config | Adds SM active %, SM occupancy, tensor/FP pipeline activity, DRAM active (HBM), graphics engine %, per-direction PCIe/NVLink throughput |
| Permissions | Works with default driver settings | Requires `NVreg_RestrictProfilingToAdminUsers=0` + driver reload/reboot |
| Services | Same exporters | `dcgm-exporter` collects `DCGM_FI_PROF_*` fields; runtime interval lowered |
| Overhead | Very low | NVIDIA states +1-3% GPU overhead; increased exporter CPU load |
| Conflicts | None notable | Clashes with Nsight, nvprof, CUPTI profilers; MIG must be disabled |

Prerequisite script responsibilities when profiling is requested:
1. Install/upgrade Data Center GPU Manager 4.x (ensures `libdcgm.so.4`).
2. Install matching Fabric Manager (`cuda-drivers-fabricmanager-<driver-major>`).
3. Write `/etc/modprobe.d/omniference-nvidia.conf` with `NVreg_RestrictProfilingToAdminUsers=0` and regenerate initramfs.
4. Restart `nvidia-persistenced`, enable `dcgm`/`nvidia-fabricmanager` services.
5. Generate CDI spec via `nvidia-ctk cdi generate`.

Note: driver reload (usually reboot) is required after first enabling profiling flag so `/proc/driver/nvidia/params` shows `RmProfilingAdminOnly: 0`.

---

## 6. Backend Data Model

- **Table `gpu_metrics`:** Wide Timescale hypertable storing per-sample metrics keyed by `(time, run_id, gpu_id)`.
  - Columns cover core utilization, profiling metrics, memory stats, clocks, power, temperatures, PCIe/NVLink stats, ECC counters, throttle reasons, config fields, retired pages, energy.
- **Table `gpu_policy_events`:** Stores rule-based alerts (thermal > threshold, ECC bursts, etc.).
- **Table `gpu_topology`:** Captures static topology (NVLink connectivity, NUMA placement) from health exporter.

Insert path:
1. Remote write handler checks rate limit (200 req/s per run_id, 400 burst).
2. Remote write handler checks circuit breaker (protects against DB failures).
3. Remote write handler decodes Prometheus protobuf in thread pool executor (prevents GIL blocking), applies `_FIELD_MAPPINGS`.
4. `TelemetryRepository.insert_metrics` performs chunked bulk insert (100 samples per transaction) via SQLAlchemy core.
   - Prevents long-running transactions and lock contention
   - Optimized for TimescaleDB hypertable partitioning
5. Policy monitor is invoked with each batch, optionally creating events.
6. `LiveMetricsBroker` publishes samples (in-memory or Redis pub/sub).
7. WebSocket subscribers receive the same samples for live visualization (no polling required).

---

## 7. Frontend Behavior

- `TelemetryTab.jsx`:
  - Derives backend URL (defaults to `https://voertx.cloud` for localhost testing).
  - Handles profiling consent dialog; `enable_profiling` flag persists in React state and is part of deploy payload.
  - Connects to `/ws/runs/{run_id}/live` once deployment status is `running`.
  - Renders ~20 `MetricChart` components with tooltips explaining standard vs profiling metrics.
  - Provides controls: Start/Stop, Refresh Runs, Preserve Prometheus data, profiling toggle.
- `MetricChart` gracefully handles zero values vs missing series, showing “No data” only when the run produces no samples yet.

---

## 8. Operational Procedures

### Starting a Run
1. Select instance (ensures `instance_id`, GPU metadata).
2. Provide SSH IP/user/key (key pasted into textarea; control plane never stores it permanently).
3. Decide whether to enable profiling; acknowledge dialog if choosing profiling.
4. Click **Start Monitoring**:
   - UI calls `createTelemetryRun` → run record created.
   - UI calls `deployTelemetryStack` with run ID and options.
   - Periodically polls `/deployments/{deployment_id}` until status `running`, then opens WebSocket.

### Stopping a Run
1. Click **Stop Monitoring**; UI sends `teardownTelemetryStack` followed by `updateTelemetryRun` (`status=completed`, `end_time=now`).
2. Backend executes remote teardown: `docker compose down`, optional volume retention.
3. Run disappears from “Active” list; historical metrics stay queryable.

### Cleanup
- If UI stop fails, manual SSH cleanup:
  - `cd /tmp/gpu-telemetry-<run-id> && sudo docker compose down`
  - Remove directory when safe.
- Avoid leaving multiple stacks running; they compete for fixed ports.

---

## 9. Failure Modes & Remedies

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| `dcgm-exporter` restart loop with `Profiling module returned an unrecoverable error` | Profiling flag not active (`RmProfilingAdminOnly: 1`), Fabric Manager stopped, or other profiler in use | Apply modprobe change, reboot host, ensure `nvidia-fabricmanager` active, disable other profilers |
| Frontend `ERR_CONNECTION_REFUSED` or `422 Unprocessable Entity` | API URL misconfigured, missing deploy fields | Ensure deployments point to `https://voertx.cloud`, verify required payload fields |
| `libdcgm.so.4 library was not found` | Host running older DCGM package | Install DCGM 4.x (`datacenter-gpu-manager`), create symlink if needed |
| Prometheus remote_write fails due to schema mismatch | New metric fields missing in `_FIELD_MAPPINGS`/DB | Update `remote_write.py`, `schemas.py`, `models.py`, migrations bootstrap |
| Charts show “No data available yet” indefinitely | Exporter failing, Prometheus down, or stack not actually running | Inspect remote logs via SSH (`docker compose logs`), ensure ports free |
| Stop Monitoring leaves run `active` | API patch failed | Manually patch via `PATCH /api/runs/{id}`; investigate UI error |

---

## 10. Resource & Security Considerations

- **CPU/GPU Overhead:** Standard metrics minimal; profiling introduces small constant load. Prometheus retains data locally (retention configurable; default 2h).
- **Network Usage:** Remote write emits compressed samples every scrape interval (~1–5s). Negligible relative to GPU workloads.
- **Privileges:** Control plane requires ability to SSH with sudo; credentials handled transiently. Remote stack runs privileged containers but limited to monitoring tasks.
- **Persistence:** TimescaleDB stores samples permanently unless retention policies are applied. Prometheus data on remote host is ephemeral unless `preserve_data` toggled.
- **Security:** SSH keys stay on client machine; ensure remote host security groups allow inbound SSH and necessary egress to `voertx.cloud`.

---

## 11. Metrics Reference

### Standard Metrics (No Profiling)
- `gpu_utilization` (%): overall GPU active time (nvidia-smi equivalent).
- `memory_utilization`, `memory_used_mb`, `memory_total_mb`.
- `power_draw_watts`, `power_limit_watts`, `total_energy_joules`.
- `temperature_celsius`, `memory_temperature_celsius`.
- `pcie_tx_mb_per_sec`, `pcie_rx_mb_per_sec` (from DCGM standard fields).
- `ecc_sbe_errors`, `ecc_dbe_errors`, `xid_errors`, `throttle_*` flags.
- `sm_clock_mhz`, `memory_clock_mhz`.

### Profiling Metrics (Require Profiling Mode)
- `sm_utilization`: `DCGM_FI_PROF_SM_ACTIVE * 100`.
- `sm_occupancy`: `DCGM_FI_PROF_SM_OCCUPANCY * 100`.
- `tensor_active`, `fp32_active`, `fp16_active`, `fp64_active`.
- `gr_engine_active`.
- `hbm_utilization`: `DCGM_FI_PROF_DRAM_ACTIVE * 100`.
- `nvlink_tx_mb_per_sec`, `nvlink_rx_mb_per_sec`.
- `pcie_tx_mb_per_sec`, `pcie_rx_mb_per_sec` (profiling versions provide exact bandwidth).

Descriptions for each metric appear in `TelemetryTab.jsx` tooltips and the `transformSamplesToSeries` mapping.

---

## 12. Performance & Scalability (January 2025)

### High-Throughput Optimizations

The ingestion pipeline has been optimized for production-scale deployments (1,000+ GPUs):

1. **Chunked Batch Insertion**: 100 samples per transaction
   - Prevents long-running transactions
   - Reduces memory spikes
   - Optimized for TimescaleDB hypertables

2. **Async Protobuf Parsing**: Thread pool executor (4 workers)
   - Prevents GIL from blocking event loop
   - Maintains low latency at 200+ req/s

3. **Circuit Breaker**: Database write protection
   - Opens after 5 consecutive failures
   - 30s recovery timeout
   - Returns 503 with Retry-After header

4. **Rate Limiting**: Per-run_id sliding window (200 req/s, 400 burst)
   - Prevents overwhelming backend at scale
   - Returns 429 with Retry-After header

5. **Redis-Backed Broker**: Optional Redis pub/sub
   - Enable via `TELEMETRY_REDIS_URL` environment variable
   - Enables horizontal scaling across multiple backend instances
   - Survives backend restarts

### Performance Benchmarks

- **Before**: ~150-200 req/s sustainable, p99 latency 1000ms+ at 200 req/s
- **After**: 400+ req/s sustainable, p99 latency <300ms at 200 req/s
- **Scalability**: Handles 1,000 GPUs × 5s interval = 200 req/s with headroom

## 13. Suggested Enhancements (Backlog)

- **Auto-reboot prompt:** detect when profiling toggle enabled but driver flag still 1, suggest reboot within UI.
- **Run auto-cleanup:** cron or background task to mark runs completed if remote stack goes offline.
- **Grafana-style dashboards:** optional aggregator for multi-run comparisons.
- **Alerting:** expose `gpu_policy_events` via frontend with notifications.
- **Role-based SSH management:** integrate stored credentials or vault to avoid manual PEM paste.

---

## 14. Quick Verification Checklist

1. `ssh ubuntu@host` works; `sudo` available.
2. `nvidia-smi` and `dcgmi --version` return expected versions.
3. If profiling desired: `cat /proc/driver/nvidia/params | grep RmProfilingAdminOnly` → `0`; `systemctl is-active nvidia-fabricmanager` → `active`.
4. Deployment stack: `docker compose ps` shows services `Up`.
5. Prometheus endpoint `http://localhost:9090/targets` (via SSH tunnel) lists all targets `UP`.
6. Backend metrics API `GET /api/runs/{run_id}/metrics?limit=5` returns rows within ~10s of deployment.

---

This document should provide enough context for engineers and operators to understand how the telemetry stack is put together, the trade-offs of profiling mode, and how to troubleshoot common issues. Updates are welcome as the system evolves.

