# DIO Platform - Complete Onboarding Guide

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Development Setup](#development-setup)
4. [Complete API Reference](#complete-api-reference)
5. [Database Schema](#database-schema)
6. [Frontend Structure](#frontend-structure)
7. [Backend Structure](#backend-structure)
8. [Deployment Workflows](#deployment-workflows)
9. [Testing](#testing)
10. [Troubleshooting](#troubleshooting)

---

## Overview

DIO (formerly Omniference) is a comprehensive GPU telemetry monitoring and AI performance analysis platform. It provides:

- **Remote GPU Monitoring**: Deploy lightweight monitoring stacks on remote GPU instances
- **Real-Time Metrics**: Stream GPU metrics via WebSocket
- **Historical Analysis**: Time-series data storage and querying
- **AI Performance Analysis**: Model workload analysis and optimization recommendations
- **Workflow Orchestration**: Multi-phase workflows for instance setup, deployment, and benchmarking
- **Cloud Integration**: Support for Scaleway, Lambda Cloud, and GCP

### Key Technologies

- **Frontend**: React 18, Material-UI, Recharts
- **Backend**: FastAPI (Python 3.9+)
- **Database**: TimescaleDB (PostgreSQL 15)
- **Cache**: Redis 7
- **Containerization**: Docker & Docker Compose

---

## System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend Layer                          │
│  React SPA → API Service → WebSocket Client                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ HTTP/REST + WebSocket
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                     Backend Layer                            │
│  FastAPI → Routers → Services → Repository → Database       │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼──────┐ ┌─────▼─────┐ ┌─────▼──────┐
│ TimescaleDB  │ │   Redis   │ │  Remote    │
│  (Metrics)   │ │  (Cache)  │ │  Instances │
└──────────────┘ └───────────┘ └────────────┘
```

### Component Diagram

```mermaid
graph TB
    subgraph "Frontend"
        UI[React UI]
        API[API Service]
        WS[WebSocket Client]
    end
    
    subgraph "Backend"
        FASTAPI[FastAPI App]
        ROUTES[API Routes]
        SERVICES[Services Layer]
        REPO[Repository]
    end
    
    subgraph "Data"
        TSDB[(TimescaleDB)]
        REDIS[(Redis)]
    end
    
    subgraph "Remote"
        SSH[SSH Deploy]
        AGENT[Agent Deploy]
        EXPORTERS[Exporters]
    end
    
    UI --> API
    UI --> WS
    API --> FASTAPI
    WS --> FASTAPI
    FASTAPI --> ROUTES
    ROUTES --> SERVICES
    SERVICES --> REPO
    REPO --> TSDB
    SERVICES --> REDIS
    ROUTES --> SSH
    ROUTES --> AGENT
    SSH --> EXPORTERS
    AGENT --> EXPORTERS
```

---

## Development Setup

### Prerequisites

- Docker & Docker Compose
- Node.js 20+ (for frontend development)
- Python 3.9+ (for backend development)
- PostgreSQL 15 with TimescaleDB extension (or use Docker)

### Local Development

1. **Clone Repository**
   ```bash
   git clone <repository-url>
   cd Omniference
   ```

2. **Environment Variables**
   
   Create `.env` file in root:
   ```bash
   # Database (Required)
   TELEMETRY_DATABASE_URL=postgresql://user:password@localhost:5432/telemetry
   
   # JWT Authentication (Required - change in production!)
   JWT_SECRET_KEY=your-jwt-secret-key-here
   
   # Credential Encryption (Required - change in production!)
   TELEMETRY_CREDENTIAL_SECRET_KEY=your-32-char-secret-key
   
   # Redis (Optional but recommended for production)
   # Enables: horizontal scaling, WebSocket persistence, cross-instance broadcasting
   TELEMETRY_REDIS_URL=redis://localhost:6379
   # With password: redis://:password@localhost:6379
   # With SSL: rediss://:password@redis.example.com:6379
   
   # OpenAI/OpenRouter (for AI insights)
   OPENROUTER_API_KEY=your-api-key
   
   # CORS
   CORS_ORIGINS=http://localhost:3000
   ```
   
   **Redis Setup (Recommended for Production)**:
   ```bash
   # Quick start with Docker
   docker run -d --name omniference-redis -p 6379:6379 redis:7-alpine
   
   # Then set environment variable
   export TELEMETRY_REDIS_URL=redis://localhost:6379/0
   ```
   
   **Why Redis?**
   - **Single-instance**: Optional, uses in-memory broker
   - **Multi-instance/Production**: Required for horizontal scaling and WebSocket persistence

3. **Start Services**
   ```bash
   docker compose up -d
   ```

   This starts:
   - TimescaleDB on port 5432
   - Redis on internal port
   - Backend on port 8000
   - Frontend on port 3000

4. **Verify Setup**
   ```bash
   # Backend health
   curl http://localhost:8000/health
   
   # Frontend
   open http://localhost:3000
   ```

### Development Workflow

**Backend Development:**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend Development:**
```bash
cd frontend
npm install
npm start  # Runs on port 3000
```

**Database Migrations:**
- Migrations run automatically on backend startup
- Located in `backend/telemetry/migrations/`

---

## Complete API Reference

### Base URL
- Local: `http://localhost:8000`
- Production: `https://your-domain.com`

### Authentication
The API uses JWT-based authentication for most endpoints:

**Public Endpoints** (no authentication required):
- `POST /api/telemetry/remote-write` - Prometheus remote_write (requires `X-Ingest-Token` header for token authentication)
- `POST /api/metrics/batch` - Batch metric ingestion
- `GET /api/runs/{run_id}/metrics` - Query historical metrics
- `WS /ws/runs/{run_id}/live?token={ingest_token}` or `?authorization=Bearer%20{jwt_token}` - WebSocket live metrics (requires ingest token or JWT)

**Protected Endpoints** (require JWT Bearer token):
- All `/api/runs/*` endpoints
- All `/api/instances/*` endpoints
- All `/api/credentials/*` endpoints
- All `/api/telemetry/provision/*` endpoints

**Authentication Flow**:
1. Register: `POST /api/auth/register` (email, password)
2. Login: `POST /api/auth/login` (email, password) → returns JWT token
3. Use token: Include `Authorization: Bearer <token>` header in requests

---

## Telemetry API Routes

### Authentication (`/api/auth`)

#### Register User
```http
POST /api/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secure-password"
}
```

**Response:**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "is_active": true,
  "created_at": "2025-01-01T00:00:00Z"
}
```

#### Login
```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secure-password"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

#### Get Current User
```http
GET /api/auth/me
Authorization: Bearer <token>
```

**Response:**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "is_active": true,
  "created_at": "2025-01-01T00:00:00Z",
  "last_login": "2025-01-01T01:00:00Z"
}
```

### Run Management (`/api/runs`)

**Note**: All endpoints in this section require JWT Bearer token authentication. Include `Authorization: Bearer <token>` header in all requests.

#### Create Run
```http
POST /api/runs
Authorization: Bearer <token>
Content-Type: application/json

{
  "instance_id": "instance-123",
  "gpu_model": "H100",
  "gpu_count": 8,
  "tags": {"environment": "production"},
  "notes": "Performance test run"
}
```

**Response:**
```json
{
  "run_id": "uuid",
  "instance_id": "instance-123",
  "status": "active",
  "start_time": "2025-01-01T00:00:00Z",
  "gpu_model": "H100",
  "gpu_count": 8
}
```

#### List Runs
```http
GET /api/runs?instance_id=instance-123&status=active&limit=10
```

#### Get Run Details
```http
GET /api/runs/{run_id}
```

#### Update Run
```http
PATCH /api/runs/{run_id}
Content-Type: application/json

{
  "status": "completed",
  "end_time": "2025-01-01T01:00:00Z",
  "notes": "Test completed"
}
```

#### Delete Run
```http
DELETE /api/runs/{run_id}
```

#### Get Run History
```http
GET /api/runs/history/all
GET /api/runs/history/no-data
```

#### Bulk Status Update
```http
PATCH /api/runs/bulk/status
Content-Type: application/json

{
  "run_ids": ["uuid1", "uuid2"],
  "status": "completed"
}
```

---

### Deployment (`/api/instances`)

#### Deploy Monitoring Stack
```http
POST /api/instances/{instance_id}/deploy?deployment_type=ssh
Content-Type: application/json

{
  "run_id": "uuid",
  "ssh_host": "123.45.67.89",
  "ssh_user": "ubuntu",
  "ssh_key": "-----BEGIN RSA PRIVATE KEY-----...",
  "backend_url": "https://backend.example.com",
  "poll_interval": 5,
  "enable_profiling": true
}
```

**For Agent Deployment:**
```http
POST /api/instances/{instance_id}/deploy?deployment_type=agent
Content-Type: application/json

{
  "run_id": "uuid",
  "backend_url": "https://backend.example.com",
  "poll_interval": 5,
  "enable_profiling": true
}
```

#### Get Deployment Status
```http
GET /api/instances/{instance_id}/deployments/{deployment_id}
```

#### Teardown Monitoring Stack
```http
POST /api/instances/{instance_id}/teardown
Content-Type: application/json

{
  "run_id": "uuid",
  "remove_volumes": false
}
```

#### Cleanup Deployment
```http
POST /api/instances/{instance_id}/cleanup
Content-Type: application/json

{
  "run_id": "uuid"
}
```

#### Get Component Status
```http
GET /api/instances/{instance_id}/component-status
```

**Response:**
```json
{
  "prometheus": {"status": "healthy", "url": "http://..."},
  "dcgm_exporter": {"status": "healthy", "url": "http://..."},
  "nvidia_smi_exporter": {"status": "healthy", "url": "http://..."},
  "token_exporter": {"status": "healthy", "url": "http://..."}
}
```

#### Get Prerequisites
```http
GET /api/instances/prerequisites
```

**Response:**
```json
{
  "prerequisites": [
    {
      "id": "nvidia_driver",
      "title": "NVIDIA Driver",
      "description": "NVIDIA GPU driver must be installed",
      "install_hint": "sudo apt install nvidia-driver-535",
      "docs_link": "https://docs.nvidia.com/..."
    }
  ]
}
```

---

### Deployment Queue (`/api/instances/jobs`)

#### List Deployment Jobs
```http
GET /api/instances/jobs?instance_id=instance-123&status=running&limit=20
```

**Response:**
```json
{
  "jobs": [
    {
      "job_id": "uuid",
      "run_id": "uuid",
      "instance_id": "instance-123",
      "status": "running",
      "deployment_type": "ssh",
      "attempt_count": 1,
      "max_attempts": 3,
      "created_at": "2025-01-01T00:00:00Z",
      "started_at": "2025-01-01T00:00:01Z"
    }
  ],
  "stats": {
    "pending": 0,
    "queued": 1,
    "running": 1,
    "completed": 10,
    "failed": 2,
    "cancelled": 0
  }
}
```

#### Get Job Details
```http
GET /api/instances/jobs/{job_id}
```

#### Retry Failed Job
```http
POST /api/instances/jobs/{job_id}/retry
```

#### Cancel Job
```http
POST /api/instances/jobs/{job_id}/cancel
```

#### Get Queue Statistics
```http
GET /api/instances/queue/stats
```

---

### Provisioning (`/api/telemetry/provision`)

#### Create API Key
```http
POST /api/telemetry/provision/api-keys
Content-Type: application/json

{
  "name": "Production Key",
  "description": "API key for production instances"
}
```

**Response:**
```json
{
  "key_id": "uuid",
  "api_key": "dio_xxxxxxxxxxxxx",  // Only shown once!
  "name": "Production Key",
  "description": "API key for production instances",
  "created_at": "2025-01-01T00:00:00Z"
}
```

#### List API Keys
```http
GET /api/telemetry/provision/api-keys?include_revoked=false
```

#### Revoke API Key
```http
POST /api/telemetry/provision/api-keys/{key_id}/revoke
```

#### Agent Heartbeat
```http
POST /api/telemetry/provision/callbacks
Content-Type: application/json

{
  "instance_id": "instance-123",
  "api_key": "dio_xxxxxxxxxxxxx",
  "phase": "running",
  "status": "healthy",
  "message": "All systems operational",
  "metadata": {
    "agent_version": "1.0.0",
    "docker_status": "running"
  }
}
```

#### Get Agent Status
```http
GET /api/telemetry/provision/callbacks/{instance_id}/status
```

#### Stop Agent
```http
POST /api/telemetry/provision/instances/{instance_id}/stop
```

#### Register Agent
```http
POST /api/telemetry/provision/register
Content-Type: application/json

{
  "instance_id": "instance-123",
  "api_key": "dio_xxxxxxxxxxxxx",
  "agent_version": "1.0.0"
}
```

#### Get Agent Config
```http
POST /api/telemetry/provision/config
Content-Type: application/json

{
  "instance_id": "instance-123",
  "api_key": "dio_xxxxxxxxxxxxx"
}
```

---

### Metrics (`/api/telemetry`)

#### Query Historical Metrics
```http
GET /api/telemetry/runs/{run_id}/metrics?start_time=2025-01-01T00:00:00Z&end_time=2025-01-01T01:00:00Z&gpu_id=0&metric_names[]=gpu_utilization&metric_names[]=power_draw_watts
```

**Response:**
```json
{
  "samples": [
    {
      "time": "2025-01-01T00:00:00Z",
      "gpu_id": 0,
      "gpu_utilization": 85.5,
      "power_draw_watts": 350.2,
      "temperature_celsius": 65.0
    }
  ]
}
```

#### Batch Ingest Metrics
```http
POST /api/telemetry/metrics/batch
Content-Type: application/json

{
  "run_id": "uuid",
  "metrics": [
    {
      "time": "2025-01-01T00:00:00Z",
      "gpu_id": 0,
      "gpu_utilization": 85.5,
      "power_draw_watts": 350.2
    }
  ]
}
```

---

### Remote Write (`/api/telemetry/remote-write`)

#### Prometheus Remote Write
```http
POST /api/telemetry/remote-write
X-Run-ID: {run_id}
X-Ingest-Token: {ingest_token}
Content-Encoding: snappy
Content-Type: application/x-protobuf

[Prometheus WriteRequest protobuf]
```

This endpoint accepts Prometheus remote_write protocol. Used by remote Prometheus instances to push metrics.

**Authentication**:
- The `X-Ingest-Token` header is **required** for runs that have a token
- The token is generated at run creation and returned once (store it securely!)
- Returns `401 Unauthorized` if the token is missing or invalid
- To regenerate a token: `POST /api/runs/{run_id}/regenerate-token`

**Performance Features**:
- **Rate Limiting**: 200 req/s per run_id with 400 burst (returns 429 if exceeded)
- **Circuit Breaker**: Returns 503 if database is failing (with Retry-After header)
- **Async Parsing**: Protobuf parsing offloaded to thread pool to prevent GIL blocking
- **Chunked Insertion**: Metrics inserted in batches of 100 samples per transaction

**Response Codes**:
- `202 Accepted`: Successfully ingested
- `401 Unauthorized`: Missing or invalid `X-Ingest-Token`
- `429 Too Many Requests`: Rate limit exceeded (check `Retry-After` header)
- `503 Service Unavailable`: Circuit breaker open (check `Retry-After` header)

**Prometheus Configuration Example**:
```yaml
remote_write:
  - url: 'https://api.omniference.com/api/telemetry/remote-write'
    headers:
      X-Run-ID: '${RUN_ID}'
      X-Ingest-Token: '${INGEST_TOKEN}'
    queue_config:
      capacity: 10000
      max_samples_per_send: 1000
```

---

### Health & Policy (`/api/telemetry/health`)

#### Get Health Summary
```http
GET /api/telemetry/health/runs/{run_id}/health
```

**Response:**
```json
{
  "gpu_count": 8,
  "sample_count": 10000,
  "latest_time": "2025-01-01T01:00:00Z",
  "alerts": [
    {
      "severity": "warning",
      "message": "Temperature above 80°C",
      "gpu_id": 0
    }
  ]
}
```

#### Get Policy Events
```http
GET /api/telemetry/health/runs/{run_id}/policy-events?severity=critical&limit=10
```

#### Create Topology
```http
POST /api/telemetry/health/runs/{run_id}/topology
Content-Type: application/json

{
  "gpu_count": 8,
  "nvlink_connections": [[0, 1], [1, 2]],
  "pcie_connections": []
}
```

#### Get Topology
```http
GET /api/telemetry/health/runs/{run_id}/topology
```

---

### Credentials (`/api/telemetry/credentials`)

#### Store Credential
```http
POST /api/telemetry/credentials
Content-Type: application/json

{
  "provider": "scaleway",
  "name": "production-key",
  "credential_type": "ssh_key",
  "secret": "-----BEGIN RSA PRIVATE KEY-----...",
  "description": "Production SSH key"
}
```

#### List Credentials
```http
GET /api/telemetry/credentials
```

#### Get Credential (Decrypted)
```http
GET /api/telemetry/credentials/{credential_id}
```

#### Update Credential
```http
PATCH /api/telemetry/credentials/{credential_id}
Content-Type: application/json

{
  "description": "Updated description"
}
```

#### Delete Credential
```http
DELETE /api/telemetry/credentials/{credential_id}
```

---

### SM Profiling (`/api/telemetry/sm-profiling`)

#### Trigger Profiling
```http
POST /api/telemetry/sm-profiling/trigger
Content-Type: application/json

{
  "run_id": "uuid",
  "gpu_id": 0,
  "metric_name": "sm_utilization",
  "ssh_host": "123.45.67.89",
  "ssh_user": "ubuntu",
  "ssh_key": "-----BEGIN RSA PRIVATE KEY-----..."
}
```

#### Get Profiling Status
```http
GET /api/telemetry/sm-profiling/sessions/{session_id}/status
```

#### Get Profiling Results
```http
GET /api/telemetry/sm-profiling/sessions/{session_id}/results
```

**Response:**
```json
{
  "metrics": [
    {
      "sm_id": 0,
      "metric_name": "sm_utilization",
      "value": 85.5
    }
  ]
}
```

#### Profiling Health
```http
GET /api/telemetry/sm-profiling/health
```

---

### AI Insights (`/api/telemetry/ai-insights`)

#### Get AI-Powered Analysis
```http
POST /api/telemetry/ai-insights
Content-Type: application/json

{
  "run_id": "uuid",
  "metric_name": "gpu_utilization",
  "gpu_id": 0
}
```

**Response:**
```json
{
  "insights": "GPU utilization shows periodic spikes...",
  "recommendations": [
    "Consider increasing batch size",
    "Check for memory bandwidth bottlenecks"
  ]
}
```

---

### WebSocket (`/ws/runs/{run_id}/live`)

#### Connect to Live Metrics Stream

**Authentication**: Supports two methods:
1. **JWT Token** (for authenticated users): Frontend automatically includes JWT token
   ```javascript
   // Frontend automatically appends JWT token from localStorage
   const ws = new WebSocket(
     `wss://your-domain.com/ws/runs/${runId}/live?authorization=Bearer%20${jwtToken}`
   );
   ```

2. **Ingest Token** (for unauthenticated access): Use ingest token from run creation
   ```javascript
   // Get the ingest_token from run creation response
   const ingestToken = 'your-ingest-token-from-run-creation';
   const runId = 'your-run-id';
   
   const ws = new WebSocket(
     `ws://localhost:8000/ws/runs/${runId}/live?token=${ingestToken}`
   );
   ```

**Note**: If the run has an ingest token, you must provide either JWT (if you own the run) or the ingest token. If the run has no token, connection is allowed (backwards compatibility).

ws.onopen = () => {
  console.log('Connected to live metrics stream');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === "metrics") {
    // data.data === [MetricSample, ...]
    console.log('Received metrics:', data.data);
  } else if (data.type === "ping" || data.type === "keepalive") {
    // Server keepalive, no action needed
  }
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = (event) => {
  if (event.code === 1008) {
    console.error('Unauthorized: Invalid or missing token');
  }
};
```

**Close Codes**:
- `1008` (Policy Violation): Invalid or missing token
- `1011` (Unexpected Condition): Run not found

**Message Format:**
```json
{
  "type": "metrics",
  "data": [
    {
      "time": "2025-01-01T00:00:00Z",
      "gpu_id": 0,
      "gpu_utilization": 85.5,
      "power_draw_watts": 350.2
    }
  ]
}
```

---

### Token Management (`/api/runs/{run_id}/regenerate-token`)

#### Regenerate Ingest Token
```http
POST /api/runs/{run_id}/regenerate-token
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "ingest_token": "new-secure-token-here",
  "message": "Token regenerated successfully. The old token is now invalid."
}
```

**Use Cases**:
- Token was leaked or compromised
- Periodic token rotation for security
- Revoke access from a previously deployed agent

**Important**: The old token is immediately invalidated. Update your Prometheus/agent configuration with the new token.

---

## Workflow API Routes

### Instance Setup (`/api/workflow/setup-instance`)

#### Setup Instance
```http
POST /api/workflow/setup-instance
Content-Type: application/json

{
  "ssh_host": "123.45.67.89",
  "ssh_user": "ubuntu",
  "pem_base64": "base64-encoded-pem",
  "model_name": "RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic",
  "model_path": "/home/ubuntu/BM/models/scout17b-fp8dyn"
}
```

**Response:**
```json
{
  "workflow_id": "workflow_uuid",
  "message": "Setup started",
  "status": "started"
}
```

#### Get Setup Status
```http
GET /api/workflow/setup-instance/status?workflow_id={workflow_id}
```

#### Save PEM File
```http
POST /api/workflow/setup-instance/save-pem
Content-Type: application/json

{
  "ip": "123.45.67.89",
  "ssh_user": "ubuntu",
  "pem_base64": "base64-encoded-pem"
}
```

#### Check Instance
```http
GET /api/workflow/setup-instance/check?ip=123.45.67.89&ssh_user=ubuntu
```

---

### Instance Check (`/api/workflow/check-instance`)

#### Check Instance
```http
POST /api/workflow/check-instance
Content-Type: application/json

{
  "ssh_host": "123.45.67.89",
  "ssh_user": "ubuntu",
  "pem_base64": "base64-encoded-pem"
}
```

---

### Deploy Inference (`/api/workflow/deploy-vllm`)

#### Deploy Inference Server
```http
POST /api/workflow/deploy-vllm
Content-Type: application/json

{
  "ssh_host": "123.45.67.89",
  "ssh_user": "ubuntu",
  "pem_base64": "base64-encoded-pem",
  "model_path": "/home/ubuntu/BM/models/scout17b-fp8dyn",
  "max_model_len": 4096,
  "max_num_seqs": 256,
  "gpu_memory_utilization": 0.9,
  "tensor_parallel_size": 1
}
```

---

### Run Benchmark (`/api/workflow/run-benchmark`)

#### Run Benchmark
```http
POST /api/workflow/run-benchmark
Content-Type: application/json

{
  "ssh_host": "123.45.67.89",
  "ssh_user": "ubuntu",
  "pem_base64": "base64-encoded-pem",
  "num_requests": 100,
  "input_seq_len": 100,
  "output_seq_len": 100,
  "max_concurrency": 10
}
```

---

### Workflow Logs (`/api/workflow/logs/{workflow_id}`)

#### Get Workflow Logs
```http
GET /api/workflow/logs/{workflow_id}?phase=deploy
```

**Query Parameters:**
- `phase`: Optional. Filter by phase (setup, check, deploy, benchmark)

---

## Analysis API Routes

### Simple Analysis (`/api/v1/analysis/analyze-simple`)

```http
POST /api/v1/analysis/analyze-simple
Content-Type: application/json

{
  "workload": {...},
  "hardware": {...}
}
```

### Interactive Analysis (`/api/v1/analysis/analyze-interactive`)

```http
POST /api/v1/analysis/analyze-interactive
Content-Type: application/json

{
  "workload": {...},
  "hardware": {...},
  "optimizations": {
    "flash_attention": true,
    "quantization": "int8"
  }
}
```

### Compare Parameters (`/api/v1/analysis/compare-parameters`)

```http
POST /api/v1/analysis/compare-parameters
Content-Type: application/json

{
  "base_workload": {...},
  "hardware": {...},
  "parameter_variations": [...]
}
```

### Get Parameter Presets (`/api/v1/analysis/parameter-presets`)

```http
GET /api/v1/analysis/parameter-presets
```

### Get Optimization Matrix (`/api/v1/analysis/optimization-matrix`)

```http
GET /api/v1/analysis/optimization-matrix
```

### Cross-Platform Metrics (`/api/v1/analysis/cross-platform-metrics`)

```http
POST /api/v1/analysis/cross-platform-metrics
Content-Type: application/json

{
  "workload": {...},
  "hardware_configs": [...]
}
```

---

## Cloud Provider APIs

### Scaleway (`/api/scaleway`)

#### Get Regions
```http
GET /api/scaleway/regions
```

#### Get Products
```http
POST /api/scaleway/products
Content-Type: application/json

{
  "region": "fr-par-1"
}
```

#### Launch Instance
```http
POST /api/scaleway/launch
Content-Type: application/json

{
  "region": "fr-par-1",
  "instance_type": "gpu-h100-1x",
  "ssh_key_id": "key-id"
}
```

#### Get Server Status
```http
POST /api/scaleway/server-status
Content-Type: application/json

{
  "server_id": "server-id"
}
```

---

### Lambda Cloud (`/api/v1/lambda-cloud`)

#### List Instances
```http
GET /api/v1/lambda-cloud/instances
```

#### Get Instance Details
```http
GET /api/v1/lambda-cloud/instances/{instance_id}
```

#### Get Instance Types
```http
GET /api/v1/lambda-cloud/instance-types
```

#### Get Regions
```http
GET /api/v1/lambda-cloud/regions
```

#### Launch Instance
```http
POST /api/v1/lambda-cloud/instance-operations/launch
Content-Type: application/json

{
  "instance_type": "gpu_1x_a100",
  "region": "us-east-1",
  "ssh_key_ids": ["key-id"]
}
```

#### SSH Keys
```http
GET /api/v1/lambda-cloud/ssh-keys
POST /api/v1/lambda-cloud/ssh-keys
DELETE /api/v1/lambda-cloud/ssh-keys/{key_id}
```

#### Health Check
```http
GET /api/v1/lambda-cloud/health
```

---

### GCP (`/api/v1/gcp`)

#### List Instances
```http
POST /api/v1/gcp/instances
Content-Type: application/json

{
  "project_id": "project-id",
  "zone": "us-central1-a",
  "credentials": {...}
}
```

#### Get Machine Types
```http
POST /api/v1/gcp/machine-types
Content-Type: application/json

{
  "project_id": "project-id",
  "zone": "us-central1-a"
}
```

#### Get Zones
```http
POST /api/v1/gcp/zones
Content-Type: application/json

{
  "project_id": "project-id"
}
```

#### Get Accelerator Types
```http
POST /api/v1/gcp/accelerator-types
Content-Type: application/json

{
  "project_id": "project-id",
  "zone": "us-central1-a"
}
```

#### Get Config
```http
GET /api/v1/gcp/config
```

---

## Instance Orchestration (`/api/orchestration`)

#### Start Orchestration
```http
POST /api/orchestration
Content-Type: application/json
X-Lambda-API-Key: {api_key}

{
  "instance_id": "instance-123",
  "action": "start"
}
```

#### Get Orchestration Status
```http
GET /api/orchestration/{orchestration_id}/status
```

#### Get Status by Instance
```http
GET /api/orchestration/by-instance/{instance_id}
```

#### Deploy Model
```http
POST /api/orchestration/{orchestration_id}/deploy-model
Content-Type: application/json

{
  "model_name": "model-name",
  "model_path": "/path/to/model"
}
```

#### Get Model Progress
```http
GET /api/orchestration/{orchestration_id}/model-progress
```

#### Proxy Inference
```http
POST /api/orchestration/proxy-inference
Content-Type: application/json

{
  "instance_id": "instance-123",
  "prompt": "Hello, world!",
  "max_tokens": 100
}
```

---

## Benchmark & Profiling APIs

### Benchmark Data (`/benchmark`)

#### Get Benchmark Data
```http
GET /benchmark/data
```

#### Get Models
```http
GET /benchmark/models
```

#### Get Results
```http
GET /benchmark/results/{model_name}
```

#### Dashboard Metadata
```http
GET /benchmark/dashboard/metadata
```

#### Detailed Metrics
```http
GET /benchmark/dashboard/detailed-metrics?system={system}
```

#### Aggregated Metrics
```http
GET /benchmark/dashboard/aggregated-metrics?system={system}
```

#### Time Series
```http
GET /benchmark/dashboard/time-series?system={system}&metric={metric}
```

#### Comparison
```http
GET /benchmark/dashboard/comparison?systems={system1,system2}
```

#### Summary Table
```http
GET /benchmark/dashboard/summary-table?systems={system1,system2}
```

### KPIs (`/benchmark/kpis`)

#### Throughput
```http
GET /benchmark/kpis/throughput?system={system}
```

#### GPU Metrics
```http
GET /benchmark/kpis/gpu-metrics?system={system}
```

#### Latency
```http
GET /benchmark/kpis/latency?system={system}
```

#### System Resources
```http
GET /benchmark/kpis/system-resources?system={system}
```

#### Summary
```http
GET /benchmark/kpis/summary?systems={system1,system2}
```

---

## Database Schema

### Core Tables

#### `runs`
```sql
CREATE TABLE runs (
    run_id UUID PRIMARY KEY,
    instance_id VARCHAR(255) NOT NULL,
    gpu_model VARCHAR(100),
    gpu_count INTEGER,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    status VARCHAR(50) NOT NULL,
    tags JSONB,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_runs_instance_id ON runs(instance_id);
CREATE INDEX idx_runs_start_time ON runs(start_time DESC);
CREATE INDEX idx_runs_status ON runs(status);
```

#### `gpu_metrics` (TimescaleDB Hypertable)
```sql
CREATE TABLE gpu_metrics (
    time TIMESTAMPTZ NOT NULL,
    run_id UUID NOT NULL,
    gpu_id INTEGER NOT NULL,
    gpu_utilization REAL,
    sm_utilization REAL,
    memory_utilization REAL,
    memory_used_mb REAL,
    memory_total_mb REAL,
    power_draw_watts REAL,
    power_limit_watts REAL,
    temperature_celsius REAL,
    memory_temperature_celsius REAL,
    sm_occupancy REAL,
    hbm_utilization REAL,
    tensor_active REAL,
    fp64_active REAL,
    fp32_active REAL,
    fp16_active REAL,
    pcie_rx_mb_per_sec REAL,
    pcie_tx_mb_per_sec REAL,
    nvlink_rx_mb_per_sec REAL,
    nvlink_tx_mb_per_sec REAL,
    ecc_sbe_errors INTEGER,
    ecc_dbe_errors INTEGER,
    tokens_per_second REAL,
    requests_per_second REAL,
    ttft_p50_ms REAL,
    ttft_p95_ms REAL,
    cost_per_watt REAL,
    -- ... 50+ more fields
    PRIMARY KEY (time, run_id, gpu_id)
);

SELECT create_hypertable('gpu_metrics', 'time');
CREATE INDEX idx_gpu_metrics_run_time ON gpu_metrics(run_id, time DESC);
CREATE INDEX idx_gpu_metrics_run_gpu_time ON gpu_metrics(run_id, gpu_id, time DESC);
```

#### `deployment_jobs`
```sql
CREATE TABLE deployment_jobs (
    job_id UUID PRIMARY KEY,
    run_id UUID REFERENCES runs(run_id),
    instance_id VARCHAR(255) NOT NULL,
    deployment_type VARCHAR(50) NOT NULL, -- 'ssh' or 'agent'
    status VARCHAR(50) NOT NULL, -- pending, queued, running, completed, failed, cancelled
    priority INTEGER DEFAULT 0,
    attempt_count INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    payload JSONB,
    error_message TEXT,
    error_log TEXT,
    locked_by VARCHAR(255),
    locked_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_deployment_jobs_instance ON deployment_jobs(instance_id, status);
CREATE INDEX idx_deployment_jobs_status ON deployment_jobs(status);
```

#### `provisioning_api_keys`
```sql
CREATE TABLE provisioning_api_keys (
    key_id UUID PRIMARY KEY,
    key_hash VARCHAR(255) NOT NULL UNIQUE, -- SHA256 hash
    name VARCHAR(255) NOT NULL,
    description TEXT,
    revoked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
```

#### `agent_heartbeats`
```sql
CREATE TABLE agent_heartbeats (
    heartbeat_id UUID PRIMARY KEY,
    instance_id VARCHAR(255) NOT NULL,
    agent_version VARCHAR(50),
    phase VARCHAR(50), -- installing, deploying, running
    status VARCHAR(50), -- healthy, error, warning
    message TEXT,
    metadata JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_heartbeats_instance ON agent_heartbeats(instance_id, timestamp DESC);
```

#### `credential_store`
```sql
CREATE TABLE credential_store (
    credential_id UUID PRIMARY KEY,
    provider VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    credential_type VARCHAR(50) NOT NULL,
    secret_ciphertext TEXT NOT NULL, -- Encrypted with Fernet
    description TEXT,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(provider, name, credential_type)
);
```

#### `gpu_policy_events`
```sql
CREATE TABLE gpu_policy_events (
    event_id UUID PRIMARY KEY,
    run_id UUID REFERENCES runs(run_id),
    gpu_id INTEGER,
    event_time TIMESTAMPTZ NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(50) NOT NULL, -- info, warning, critical
    message TEXT,
    metric_value REAL,
    threshold_value REAL
);

CREATE INDEX idx_policy_events_run ON gpu_policy_events(run_id, event_time DESC);
CREATE INDEX idx_policy_events_severity ON gpu_policy_events(run_id, severity, event_time DESC);
```

---

## Frontend Structure

### Key Components

#### Pages
- **`Benchmarking.js`**: Main benchmarking workflow page
  - Phase 1: Setup Instance
  - Phase 2: Check Instance
  - Phase 3: Deploy Inference
  - Phase 4: Run Benchmark

- **`ManageInstances.js`**: Instance management
  - List instances
  - Add/edit instances
  - SSH key management
  - Cloud provider integration

#### Components
- **`TelemetryTab.jsx`**: Real-time and historical telemetry monitoring
- **`ProvisioningTab.jsx`**: Agent-based provisioning interface
- **`SystemBenchmarkDashboard.jsx`**: Benchmark results dashboard
- **`InstanceOrchestration.jsx`**: Instance orchestration UI

#### Services
- **`api.js`**: Centralized API client
  - All REST endpoints
  - WebSocket management
  - Error handling
  - Request/response transformation

### State Management

- React hooks (`useState`, `useEffect`, `useCallback`)
- Context API for global state (if needed)
- Local component state for UI state

### Routing

- React Router for navigation
- Routes defined in `App.js`

---

## Backend Structure

### Directory Structure

```
backend/
├── main.py                 # FastAPI app entry point
├── telemetry/
│   ├── routes/            # API route handlers
│   │   ├── runs.py
│   │   ├── metrics.py
│   │   ├── deployments.py
│   │   ├── provisioning.py
│   │   ├── remote_write.py
│   │   ├── ws.py
│   │   └── ...
│   ├── services/          # Business logic
│   │   ├── deployment_queue.py
│   │   ├── deployment_worker.py
│   │   └── policy_monitor.py
│   ├── repository.py     # Database access
│   ├── models.py         # SQLAlchemy models
│   ├── schemas.py        # Pydantic schemas
│   ├── crypto.py         # Encryption utilities
│   └── migrations/       # Database migrations
├── mapper/               # AI analysis module
│   ├── api/
│   ├── services/
│   └── operators/
├── scripts/              # Utility scripts
│   ├── exporters/        # Metric exporters
│   └── run_benchmark.sh  # Benchmark script
└── tests/                # Test suite
```

### Key Modules

#### `telemetry/routes/`
- **`runs.py`**: Run CRUD operations
- **`metrics.py`**: Metric querying
- **`deployments.py`**: Deployment orchestration
- **`provisioning.py`**: Agent provisioning
- **`remote_write.py`**: Prometheus remote_write handler
- **`ws.py`**: WebSocket endpoint
- **`health.py`**: Health checks and policy events
- **`credentials.py`**: Encrypted credential storage
- **`sm_profiling.py`**: SM-level profiling
- **`ai_insights.py`**: AI-powered analysis

#### `telemetry/services/`
- **`deployment_queue.py`**: Job queue management
- **`deployment_worker.py`**: Background worker
- **`policy_monitor.py`**: Policy evaluation

#### `telemetry/repository.py`
- Database access abstraction
- Query builders
- Transaction management

---

## Deployment Workflows

### SSH-Based Deployment

1. **Create Run**: `POST /api/runs`
2. **Deploy Stack**: `POST /api/instances/{id}/deploy?deployment_type=ssh`
3. **Monitor Status**: `GET /api/instances/{id}/deployments/{deployment_id}`
4. **Connect WebSocket**: `WS /ws/runs/{run_id}/live`
5. **Query Metrics**: `GET /api/telemetry/runs/{run_id}/metrics`

### Agent-Based Deployment

1. **Create API Key**: `POST /api/telemetry/provision/api-keys`
2. **Install Agent**: Run install script on remote instance
3. **Agent Registers**: `POST /api/telemetry/provision/register`
4. **Agent Heartbeats**: `POST /api/telemetry/provision/callbacks` (every 30s)
5. **Monitor Status**: `GET /api/telemetry/provision/callbacks/{instance_id}/status`

### Workflow Deployment

1. **Setup Instance**: `POST /api/workflow/setup-instance`
2. **Check Instance**: `POST /api/workflow/check-instance`
3. **Deploy Inference**: `POST /api/workflow/deploy-vllm`
4. **Run Benchmark**: `POST /api/workflow/run-benchmark`
5. **Get Logs**: `GET /api/workflow/logs/{workflow_id}`

---

## Testing

### Backend Tests

```bash
cd backend
pytest tests/
```

### Frontend Tests

```bash
cd frontend
npm test
```

### Integration Tests

```bash
# Start services
docker compose up -d

# Run integration tests
pytest tests/integration/
```

---

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Check `TELEMETRY_DATABASE_URL`
   - Verify TimescaleDB is running
   - Check database permissions

2. **Deployment Failures**
   - Verify SSH credentials
   - Check network connectivity
   - Review deployment logs

3. **WebSocket Connection Issues**
   - Check CORS settings
   - Verify WebSocket endpoint URL
   - Check firewall rules

4. **Metric Ingestion Problems**
   - Verify remote_write endpoint is accessible
   - Check Prometheus configuration
   - Review metric mapping in `remote_write.py`

### Debugging

**Backend Logs:**
```bash
docker compose logs omniference-backend -f
```

**Database Queries:**
```sql
-- Check recent runs
SELECT * FROM runs ORDER BY start_time DESC LIMIT 10;

-- Check metric counts
SELECT run_id, COUNT(*) FROM gpu_metrics GROUP BY run_id;

-- Check deployment jobs
SELECT * FROM deployment_jobs WHERE status = 'failed';
```

**Frontend Console:**
- Open browser DevTools
- Check Network tab for API calls
- Check Console for errors

---

## Additional Resources

- **Architecture Documentation**: See `ARCHITECTURE.md`
- **API Interactive Docs**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **Backend README**: `backend/README.md`
- **Frontend README**: `frontend/README.md`

---

## Contributing

1. Create feature branch
2. Make changes
3. Add tests
4. Update documentation
5. Submit pull request

---

**Last Updated**: 2025-01-19
**Version**: 1.1.0

## Performance & Scalability Features (v1.1.0)

### High-Throughput Optimizations

The system has been optimized for production-scale deployments (1,000+ GPUs):

1. **Chunked Batch Insertion**: Metrics inserted in batches of 100 samples per transaction
   - Prevents long-running transactions
   - Reduces memory spikes
   - Optimized for TimescaleDB

2. **Async Protobuf Parsing**: CPU-bound parsing offloaded to thread pool
   - Prevents GIL blocking at high request rates
   - Maintains low latency (p99 <300ms at 200 req/s)

3. **Circuit Breaker**: Protects against database failures
   - Opens after 5 consecutive failures
   - Returns 503 with Retry-After header
   - Prevents cascading failures

4. **Rate Limiting**: Per-run_id rate limiting (200 req/s with 400 burst)
   - Sliding window algorithm
   - Returns 429 with Retry-After header when exceeded

5. **Redis-Backed Broker**: Optional Redis pub/sub for multi-instance deployments
   - Enable via `TELEMETRY_REDIS_URL` environment variable
   - Enables horizontal scaling
   - Survives backend restarts
   - **Note**: Requires `redis` Python package (automatically installed via `requirements.txt`)

### Performance Benchmarks

- **Before**: ~150-200 req/s sustainable, p99 latency 1000ms+ at 200 req/s
- **After**: 400+ req/s sustainable, p99 latency <300ms at 200 req/s
- **Scalability**: Handles 1,000 GPUs × 5s interval = 200 req/s with headroom

