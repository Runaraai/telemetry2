# Omniference Deep Codebase Report

Date: 2026-03-10
Scope: `backend/`, `frontend/`, `provisioning-agent/`, key docs

## 1) Executive Summary

Omniference is a GPU telemetry + cloud instance orchestration platform with three major runtime surfaces:

- Backend API (FastAPI, monolithic `main.py` + modular telemetry package)
- Frontend SPA (React + MUI)
- Remote provisioning agent (Go binary running on GPU hosts)

The backend is functionally rich but operationally coupled to PostgreSQL on startup. The telemetry subsystem is the most mature and modular part. There are several production hardening gaps (secrets handling, stale tests/docs, hardcoded tenant/domain assumptions).

## 2) Actual Runtime Topology (from source)

### Backend

- Primary app entrypoint: `backend/main.py` (8475 lines)
- Startup initializes telemetry schema and starts deployment worker:
  - `backend/main.py` lines 752, 754, 760
- Router wiring in `main.py` includes:
  - auth/runs/metrics/remote-write/deployments/provisioning/credentials/health
  - scaleway + nebius cloud APIs
  - instance orchestration + websocket
  - `backend/main.py` lines 767-781

### Telemetry Core

- Config + DB:
  - `backend/telemetry/config.py`
  - `backend/telemetry/db.py` lines 12-17
- Schema/bootstrap:
  - `backend/telemetry/migrations/bootstrap.py`
- Ingestion:
  - `backend/telemetry/routes/remote_write.py`
  - `backend/telemetry/remote_write.py`
- Real-time broker:
  - `backend/telemetry/realtime.py` (in-memory by default, Redis optional)
- Queue worker:
  - `backend/telemetry/services/deployment_queue.py`
  - `backend/telemetry/services/deployment_worker.py`

### Frontend

- App shell and routing: `frontend/src/App.js`
- API client: `frontend/src/services/api.js`
- Main operational views:
  - `frontend/src/pages/Benchmarking.js`
  - `frontend/src/pages/ManageInstances.js`
  - `frontend/src/components/TelemetryTab.jsx`
  - `frontend/src/components/ProvisioningTab.jsx`

### Provisioning Agent

- Standalone Go service:
  - `provisioning-agent/main.go`
- Pulls deployment config from backend and manages telemetry stack on remote GPU host.

## 3) Key End-to-End Flows

### A) SSH-based telemetry deployment

1. UI logs in via `/api/auth/*`.
2. UI creates run (`/api/runs`) and receives one-time ingest token.
3. UI requests deployment (`/api/instances/{instance_id}/deploy`).
4. Job is enqueued (`deployment_jobs`), background worker executes SSH deployment.
5. Remote Prometheus sends `remote_write` to `/api/telemetry/remote-write` with `X-Run-ID` and ingest token.
6. Samples stored in DB and published over websocket (`/ws/runs/{run_id}/live`).

### B) Agent-based telemetry deployment

1. Control plane creates API key/manifest.
2. Agent requests config (`/api/telemetry/provision/config`).
3. Agent deploys telemetry stack on host and sends heartbeats (`/api/telemetry/provision/callbacks`).
4. Metrics flow is same as SSH path through remote_write + websocket.

## 4) Data Layer and Operational Behavior

- PostgreSQL is required for backend startup (telemetry bootstrap runs at startup).
- Timescale-specific steps are conditionally skipped if extension is unavailable:
  - `backend/telemetry/migrations/bootstrap.py` line 204
- Redis is optional; if not configured, in-memory broker is used:
  - `backend/telemetry/realtime.py` lines 300-311

## 5) Verified Local Execution Findings (on this machine)

### Backend

- Installed `backend/requirements-local.txt` in Python 3.13 virtual environment.
- Startup initially failed because `aiohttp` was missing.
- After adding `aiohttp`, backend boot proceeds until DB initialization, then fails with PostgreSQL connection refused (expected because no local DB is running).

### Frontend

- `npm install` fails with `ENOSPC` because disk free space is critically low (~0.17 GB on drive D:).

## 6) Findings and Risks

### Critical

1. Secrets exposure risk in tracked `.env`
- `.env` contains non-placeholder credential-like values (API keys/cloud credentials).
- Immediate action: rotate exposed credentials and remove secrets from VCS history if applicable.

### High

2. Missing backend dependency (`aiohttp`) in requirements (fixed in this pass)
- `instance_orchestrator` imports `aiohttp`, but it was absent from requirements files.
- Files updated:
  - `backend/requirements.txt`
  - `backend/requirements-local.txt`

3. Hard startup dependency on DB
- App cannot start without DB connectivity because telemetry bootstrap runs unconditionally at startup.
- `backend/main.py` line 754 -> `init_telemetry()`.

### Medium

4. Stale tests vs current signatures
- Test dummy repository defines `create_run(self, payload)` but production repo is `create_run(self, payload, user_id)`.
- Evidence:
  - `backend/tests/telemetry/test_routes.py` line 22
  - `backend/telemetry/repository.py` line 63

5. Stale backend README and inaccurate structure docs
- References to files/modules not present (e.g., `start.py`, `hardware_builder/`, `engine/`).
- `backend/README.md` lines 192-217, 204, 211

6. Hardcoded tenant/domain assumptions
- Demo account auto-created on startup (`demo@allyin.ai`):
  - `backend/telemetry/startup.py` lines 39-70
- Migration backfills to hardcoded user `madhur@allyin.ai`:
  - `backend/telemetry/migrations/bootstrap.py` lines 323, 405, 468
- Frontend one-time credential migration hardcoded for same user:
  - `frontend/src/pages/ManageInstances.js` lines 1283, 1298
- Provisioning defaults to hosted domains when env unset:
  - `backend/telemetry/routes/provisioning.py` lines 96, 421

### Low

7. Monolithic API surface
- `backend/main.py` holds large amount of unrelated route/domain logic (8475 lines), raising maintenance and regression risk.

## 7) Architecture Quality Snapshot

Strengths:

- Telemetry domain has clear modular separation (`routes`, `services`, `repository`, `schemas`).
- Ingestion path includes rate limiting + circuit breaker + async parse offload.
- Agent path provides non-SSH deployment option.

Weaknesses:

- Core app composition still centralized in huge `main.py`.
- Documentation drift and test drift are significant.
- Runtime defaults include project-specific assumptions.

## 8) Priority Recommendations

1. Security first
- Remove secrets from tracked `.env`, rotate all leaked keys, enforce secret manager strategy.

2. Stabilize local/dev bootstrap
- Keep dependency files in sync with imports (done for `aiohttp`).
- Consider optional `TELEMETRY_SKIP_STARTUP` for non-telemetry local dev mode.

3. Reduce hardcoded assumptions
- Replace tenant/domain literals with env/config.

4. Repair test suite baseline
- Update telemetry tests to current auth/repo signatures.

5. Split `main.py`
- Move cloud/workflow/benchmark endpoints into dedicated routers under `backend/routes/`.
