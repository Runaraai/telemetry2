# Omniference Telemetry Monitoring System Architecture

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [High-Level Architecture](#high-level-architecture)
3. [Component Breakdown](#component-breakdown)
4. [Data Flow Diagrams](#data-flow-diagrams)
5. [Technology Stack](#technology-stack)
6. [Deployment Architecture](#deployment-architecture)
7. [API Endpoints Overview](#api-endpoints-overview)
8. [Database Schema](#database-schema)
9. [Security Considerations](#security-considerations)
10. [Monitoring and Observability](#monitoring-and-observability)

---

## Executive Summary

DIO (formerly Omniference) is a comprehensive GPU telemetry monitoring platform that enables real-time and historical analysis of remote GPU systems. The system analyzes user's live GPU setups for utilization patterns and performance bottlenecks through remote system monitoring.

**Last Updated:** January 2025

### Key Capabilities

- **Remote GPU Monitoring**: Deploy lightweight monitoring stacks on remote GPU instances via SSH or lightweight provisioning agent
- **Deployment Queue System**: Robust job queue with retry logic, per-instance locking, and automatic error recovery
- **Dual Deployment Modes**: 
  - **SSH Push**: Traditional SSH-based deployment (push model)
  - **Agent Pull**: API key-based agent deployment (pull model, fully functional)
- **Multi-Cloud Support**: Supports 5 cloud providers (Lambda Labs, AWS, GCP, Scaleway, Nebius)
- **Instance Orchestration**: Automated instance launch, setup, and model deployment workflows
- **Real-Time Metrics**: Stream GPU metrics in real-time through WebSocket connections
- **Historical Analysis**: Store and query time-series metrics for trend analysis
- **Bottleneck Detection**: Identify performance constraints through policy monitoring and AI-powered insights
- **Comprehensive Metrics**: Collect 50+ GPU metrics including utilization, power, temperature, memory bandwidth, and profiling counters
- **SM-Level Profiling**: Per-Streaming-Multiprocessor breakdown for detailed performance analysis

### Main Use Cases

1. **Performance Optimization**: Monitor GPU workloads to identify utilization bottlenecks and optimize resource allocation
2. **Cost Analysis**: Track power consumption and energy usage for cost optimization
3. **Health Monitoring**: Detect thermal issues, ECC errors, and hardware problems before they cause failures
4. **Workload Characterization**: Understand workload patterns through profiling metrics (tensor cores, FP precision, memory bandwidth)
5. **Multi-Instance Management**: Monitor multiple GPU instances from a single dashboard

---

## High-Level Architecture

The system consists of three main layers: Frontend (React), Backend (FastAPI), and Remote Systems (SSH-deployed or agent-based monitoring stack).

### Mermaid Diagram

```mermaid
graph TB
    subgraph "Frontend Layer"
        UI[React UI<br/>Material-UI + Recharts]
        WS[WebSocket Client]
        API[API Service Layer]
    end
    
    subgraph "Backend Layer"
        FASTAPI[FastAPI Application]
        ROUTES[API Routes<br/>REST + WebSocket]
        QUEUE[Deployment Queue<br/>Job Manager]
        WORKER[Deployment Worker<br/>Background Processor]
        DEPLOY[Deployment Manager<br/>SSH Orchestration]
        PROVISION[Provisioning API<br/>Manifest & Tokens]
        REPO[Repository Layer<br/>Database Access]
        BROKER[Live Metrics Broker<br/>WebSocket Pub/Sub]
        POLICY[Policy Monitor<br/>Alert Generation]
    end
    
    subgraph "Data Layer"
        TSDB[(TimescaleDB<br/>Time-Series Storage)]
        REDIS[(Redis<br/>Cache & Sessions)]
    end
    
    subgraph "Remote GPU Instance - SSH Path"
        SSH[SSH Connection]
        DOCKER_SSH[Docker Compose Stack]
        PROM_SSH[Prometheus<br/>Metrics Aggregation]
        DCGM_SSH[DCGM Exporter<br/>Port 9400]
        SMI_SSH[NVIDIA-SMI Exporter<br/>Port 9401]
        TOKEN_SSH[Token Exporter<br/>Port 9402]
        GPU_SSH[GPU Hardware]
    end
    
    subgraph "Remote GPU Instance - Agent Path"
        AGENT[Provisioning Agent<br/>Go Binary]
        DOCKER_AGENT[Docker Compose Stack]
        PROM_AGENT[Prometheus<br/>Metrics Aggregation]
        DCGM_AGENT[DCGM Exporter<br/>Port 9400]
        SMI_AGENT[NVIDIA-SMI Exporter<br/>Port 9401]
        TOKEN_AGENT[Token Exporter<br/>Port 9402]
        GPU_AGENT[GPU Hardware]
    end
    
    UI --> API
    UI --> WS
    API --> FASTAPI
    WS --> FASTAPI
    FASTAPI --> ROUTES
    ROUTES --> QUEUE
    ROUTES --> PROVISION
    ROUTES --> REPO
    ROUTES --> BROKER
    ROUTES --> POLICY
    QUEUE --> WORKER
    WORKER --> DEPLOY
    WORKER --> PROVISION
    REPO --> TSDB
    BROKER --> REDIS
    
    DEPLOY -.SSH Push.-> SSH
    SSH --> DOCKER_SSH
    DOCKER_SSH --> PROM_SSH
    PROM_SSH --> DCGM_SSH
    PROM_SSH --> SMI_SSH
    PROM_SSH --> TOKEN_SSH
    DCGM_SSH --> GPU_SSH
    SMI_SSH --> GPU_SSH
    
    PROVISION -.API Key Auth.-> AGENT
    AGENT -.HTTPS POST.-> PROVISION
    AGENT --> DOCKER_AGENT
    DOCKER_AGENT --> PROM_AGENT
    PROM_AGENT --> DCGM_AGENT
    PROM_AGENT --> SMI_AGENT
    PROM_AGENT --> TOKEN_AGENT
    DCGM_AGENT --> GPU_AGENT
    SMI_AGENT --> GPU_AGENT
    AGENT -.Heartbeats.-> PROVISION
    
    PROM_SSH -.Remote Write.-> FASTAPI
    PROM_AGENT -.Remote Write.-> FASTAPI
```

### ASCII Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND LAYER                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  React UI    │  │  WebSocket   │  │  API Service │        │
│  │  Components  │  │   Client      │  │    Layer     │        │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘        │
│         │                 │                  │                  │
└─────────┼─────────────────┼──────────────────┼──────────────────┘
          │                 │                  │
          │  HTTP/REST      │  WebSocket       │
          │                 │                  │
┌─────────┼─────────────────┼──────────────────┼──────────────────┐
│         │                 │                  │  BACKEND LAYER    │
│  ┌──────▼─────────────────▼──────────────────▼──────┐           │
│  │         FastAPI Application                       │           │
│  │  ┌──────────────┐  ┌──────────────┐            │           │
│  │  │ API Routes   │  │  Deployment  │            │           │
│  │  │ (REST/WS)    │  │   Queue      │            │           │
│  │  └──────┬───────┘  └──────┬───────┘            │           │
│  │         │                 │                      │           │
│  │  ┌──────▼───────┐  ┌──────▼───────┐            │           │
│  │  │  Repository   │  │ Live Broker  │            │           │
│  │  │    Layer      │  │  (Pub/Sub)   │            │           │
│  │  └──────┬───────┘  └──────┬───────┘            │           │
│  │         │                 │                      │           │
│  │  ┌──────▼───────┐  ┌──────▼───────┐            │           │
│  │  │  Deployment  │  │ Provisioning  │            │           │
│  │  │   Worker     │  │     API      │            │           │
│  │  └──────┬───────┘  └──────┬───────┘            │           │
│  └─────────┼─────────────────┼────────────────────┘           │
│            │                 │                                   │
└────────────┼─────────────────┼───────────────────────────────────┘
             │                 │
    ┌────────▼────────┐  ┌─────▼─────┐
    │  TimescaleDB    │  │   Redis   │
    │  (PostgreSQL)   │  │  (Cache)  │
    └─────────────────┘  └───────────┘

┌─────────────────────────────────────────────────────────────────┐
│              REMOTE GPU INSTANCE - SSH DEPLOYMENT               │
│                                                                   │
│  ┌─────────────────────────────────────────────────────┐        │
│  │  SSH Connection (Paramiko) ──► Backend              │        │
│  └──────────────────┬──────────────────────────────────┘        │
│                     │                                            │
│  ┌──────────────────▼──────────────────────────────────┐        │
│  │  Docker Compose Stack                                │        │
│  │  ┌──────────────┐  ┌──────────────┐                │        │
│  │  │ Prometheus   │  │  Exporters   │                │        │
│  │  │ (Port 9090)  │  │              │                │        │
│  │  └──────┬───────┘  └──────┬───────┘                │        │
│  │         │                 │                          │        │
│  │  ┌──────▼───────┐  ┌──────▼───────┐                │        │
│  │  │ DCGM Exp.    │  │ NVIDIA-SMI   │                │        │
│  │  │ (Port 9400)  │  │ (Port 9401)  │                │        │
│  │  └──────┬───────┘  └──────┬───────┘                │        │
│  │         │                 │                          │        │
│  │  ┌──────▼─────────────────▼───────┐                │        │
│  │  │      GPU Hardware                │                │        │
│  │  └──────────────────────────────────┘                │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                   │
│  Remote Write ────────────────────────► Backend API             │
│  (Prometheus Protocol)                                           │
└───────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│            REMOTE GPU INSTANCE - AGENT DEPLOYMENT               │
│                                                                   │
│  ┌─────────────────────────────────────────────────────┐        │
│  │  Provisioning Agent (Go Binary)                      │        │
│  │  ┌──────────────────────────────────────────────┐  │        │
│  │  │  HTTPS GET Manifest ──► Provisioning API     │  │        │
│  │  │  Heartbeats ──► Provisioning API              │  │        │
│  │  └──────────────────────────────────────────────┘  │        │
│  └──────────────────┬──────────────────────────────────┘        │
│                     │                                            │
│  ┌──────────────────▼──────────────────────────────────┐        │
│  │  Docker Compose Stack                                │        │
│  │  ┌──────────────┐  ┌──────────────┐                │        │
│  │  │ Prometheus   │  │  Exporters   │                │        │
│  │  │ (Port 9090)  │  │              │                │        │
│  │  └──────┬───────┘  └──────┬───────┘                │        │
│  │         │                 │                          │        │
│  │  ┌──────▼───────┐  ┌──────▼───────┐                │        │
│  │  │ DCGM Exp.    │  │ NVIDIA-SMI   │                │        │
│  │  │ (Port 9400)  │  │ (Port 9401)  │                │        │
│  │  └──────┬───────┘  └──────┬───────┘                │        │
│  │         │                 │                          │        │
│  │  ┌──────▼─────────────────▼───────┐                │        │
│  │  │      GPU Hardware                │                │        │
│  │  └──────────────────────────────────┘                │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                   │
│  Remote Write ────────────────────────► Backend API             │
│  (Prometheus Protocol)                                           │
└───────────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 3.1 Frontend Layer

The frontend is a React single-page application that provides the user interface for monitoring GPU telemetry.

#### Key Components

**`TelemetryTab.jsx`** - Main telemetry monitoring interface
- Displays real-time and historical GPU metrics
- Manages monitoring lifecycle (start/stop)
- Handles WebSocket connections for live updates
- Renders metric charts using Recharts
- Manages SSH credential configuration for remote deployments
- Displays deployment queue jobs with status, retry, and cancel actions
- Shows component health status for remote monitoring stack
- Prerequisites display card showing required system prerequisites with install hints and documentation links
- Automatically fetches and displays prerequisites from backend API

**`ProvisioningTab.jsx`** - Agent-based provisioning interface
- API key management (create, list, revoke provisioning API keys)
- Prerequisites display card (same as TelemetryTab) showing required system prerequisites
- Displays prerequisites with install hints, descriptions, and documentation links
- Notes that agent automatically installs Docker, NVIDIA Container Toolkit, DCGM, and Fabric Manager
- Single-step installation command with API key and instance ID
- Step-by-step installation guide with stepper UI
- Agent status monitoring and heartbeat tracking
- Agent phase tracking (installing, deploying, running)
- Stop agent functionality
- Navigation to telemetry metrics when available

**`ManageInstances.js`** - Instance management interface (4,790 lines)
- Lists available GPU instances from 5 cloud providers (Lambda, AWS, GCP, Scaleway, Nebius)
- Manages instance credentials with encrypted backend storage
- Provides navigation to telemetry monitoring
- Instance launch with region filtering (fixed December 2024)
- Success/error message display for user feedback
- Instance orchestration integration for automated workflows

**`api.js`** - API service layer
- Centralized API client for all backend endpoints
- Handles authentication and error handling
- WebSocket URL construction
- Request/response transformation utilities
- Deployment queue API methods (list, retry, cancel jobs)
- Provisioning API methods (create manifest, get heartbeats)

#### State Management

- React hooks (`useState`, `useEffect`, `useCallback`) for component state
- WebSocket connection management with automatic reconnection
- Real-time chart data aggregation and display
- Historical data fetching and caching

#### Key Features

- **Real-Time Charts**: Live updating charts for all GPU metrics
- **Historical Analysis**: Time-range selection for historical data
- **Multi-GPU Support**: Separate series for each GPU in multi-GPU systems
- **SM-Level Profiling**: Per-Streaming-Multiprocessor breakdown visualization
- **Component Status**: Health checks for remote monitoring stack components
- **Prerequisites Display**: Shows required system prerequisites with install hints and documentation links (available in both TelemetryTab and ProvisioningTab)
- **Deployment Queue UI**: View, retry, and cancel deployment jobs
- **Dual Deployment Modes**: SSH push and Agent pull deployment options
- **Agent Management**: Create agent deployment jobs, generate manifests, monitor heartbeats

### 3.2 Backend Layer

The backend is a FastAPI application that orchestrates remote deployments, ingests metrics, and serves the frontend API.

#### Application Structure

**`backend/main.py`** - FastAPI application entry point
- Initializes FastAPI app with CORS middleware
- Registers telemetry routers
- Configures database connections
- Sets up startup/shutdown handlers

**Telemetry Module Organization** (`backend/telemetry/`):

**`routes/`** - API endpoint definitions
- `auth.py`: User registration, login, JWT token generation (`/api/auth/*`)
- `deployments.py`: Deployment orchestration endpoints (requires auth)
- `runs.py`: Run lifecycle management (create, list, update, delete) (requires auth)
- `metrics.py`: Metric query endpoints (historical data) - public for remote_write compatibility
- `remote_write.py`: Prometheus remote_write protocol handler (public, no auth required)
  - Rate limiting (200 req/s per run_id with 400 burst)
  - Circuit breaker protection against DB failures
  - Async protobuf parsing (thread pool executor, 4 workers)
- `ws.py`: WebSocket endpoint for live metrics (requires ingest token via query param)
- `health.py`: Health check and policy event endpoints
- `credentials.py`: Encrypted credential storage (requires auth, user-scoped)
- `sm_profiling.py`: SM-level profiling session management
- `ai_insights.py`: AI-powered metric analysis and recommendations
- `instance_orchestration.py`: Instance launch and orchestration workflows (fixed `get_session` import December 2024)
- `scaleway.py`: Scaleway cloud provider integration
- `nebius.py`: Nebius cloud provider integration
- `provisioning.py`: Agent-based provisioning with API key authentication (requires auth)

**Core Modules**:
- `circuit_breaker.py`: Circuit breaker pattern for fault tolerance (database write protection)
- `rate_limiter.py`: Sliding window rate limiter for high-throughput endpoints
- `realtime.py`: Live metrics broker (InMemoryBroker or RedisBroker)
- `remote_write.py`: Prometheus protobuf parser (with async thread pool executor)
- `repository.py`: Database access layer with chunked batch insertion

**`deployment.py`** - SSH-based remote stack deployment
- `DeploymentManager`: Manages deployment lifecycle
- `_perform_deploy()`: SSH connection, prerequisite validation, file upload, Docker Compose deployment
- `_validate_system()`: Checks GPU count, driver version, DCGM availability
- `_compose_content()`: Generates Docker Compose configuration
- `_prometheus_config()`: Creates Prometheus configuration with remote_write
- Health check validation and status reporting

**`services/deployment_queue.py`** - Deployment job queue manager
- `DeploymentQueueManager`: Manages deployment job queue with retry logic
- Per-instance locking to prevent concurrent deployments
- Exponential backoff retry mechanism
- Job status tracking (pending, queued, running, completed, failed, cancelled)
- Priority-based job scheduling

**`services/deployment_worker.py`** - Background worker for processing deployment jobs
- `DeploymentWorker`: Async background worker that processes queued jobs
- Polls queue for pending jobs
- Locks jobs for processing
- Executes SSH deployments via DeploymentManager
- Handles job state transitions and error recovery

**`routes/provisioning.py`** - Manifest-driven provisioning endpoints
- `POST /provision/manifests/{deployment_job_id}`: Generate provisioning manifest and token
- `GET /provision/manifests/{manifest_id}`: Fetch manifest (for agent)
- `POST /provision/callbacks`: Receive agent heartbeats and status updates
- `GET /provision/callbacks/{manifest_id}/heartbeats`: Get agent heartbeat history

**`repository.py`** - Database access layer
- `TelemetryRepository`: High-level data access methods
- Run CRUD operations
- **Chunked batch insertion**: Metrics inserted in batches of 100 samples per transaction
  - Prevents long-running transactions and lock contention
  - Reduces memory spikes from large INSERT statements
  - Optimized for TimescaleDB hypertable partitioning
- Credential encryption/decryption
- Query builders for time-range queries

**`realtime.py`** - WebSocket broker for live metrics
- `LiveMetricsBroker`: Pub/sub broker for WebSocket connections
- **InMemoryBroker**: Single-instance deployments with bounded queues (maxsize=500)
- **RedisBroker**: Multi-instance deployments with Redis pub/sub (optional, via `TELEMETRY_REDIS_URL`)
- Per-run subscription management
- Queue-based message delivery with backpressure handling (drop-oldest when full)
- Automatic broker selection based on Redis configuration

**`services/`** - Business logic services
- `policy_monitor.py`: Evaluates metrics against thresholds (thermal, power, ECC)
- Generates policy violation events stored in database
- `instance_orchestrator.py`: Manages instance lifecycle (launch, setup, deployment) - fixed `get_session` import December 2024
- `deployment_queue.py`: Deployment job queue manager with retry logic
- `deployment_worker.py`: Background worker for processing deployment jobs
- `nebius_client.py`: Nebius API client for instance management
- `ssh_executor.py`: SSH command execution utilities

**`circuit_breaker.py`** - Circuit breaker pattern for fault tolerance
- `CircuitBreaker`: Async circuit breaker with three states (CLOSED, OPEN, HALF_OPEN)
- **`db_write_breaker`**: Global circuit breaker for database writes
  - Opens after 5 consecutive failures
  - 30s recovery timeout before testing recovery
  - Returns 503 with `Retry-After` header when open
- Prevents cascading failures when database is overloaded
- Statistics tracking for monitoring

**`rate_limiter.py`** - Sliding window rate limiter
- `RateLimiter`: Per-client rate limiting with sliding window algorithm
- **`remote_write_limiter`**: Global limiter for remote_write endpoint
  - 200 req/s per run_id with 400 burst allowance
  - Prevents overwhelming backend at scale (1,000+ GPUs)
- Returns 429 with `Retry-After` header when limit exceeded
- Automatic cleanup of stale entries

**`models.py`** - SQLAlchemy ORM models
- `Run`: Monitoring session metadata
- `GpuMetric`: Individual metric samples (50+ fields)
- `RunSummary`: Aggregated statistics
- `GpuPolicyEvent`: Policy violation events
- `StoredCredential`: Encrypted credential storage
- `SMProfilingSession`: SM profiling session metadata
- `DeploymentJob`: Deployment job queue entries with retry tracking
- `ProvisioningAPIKey`: API key records for agent authentication (SHA256 hashed)
- `AgentHeartbeat`: Agent status and heartbeat records
- `ProvisioningManifest`: Legacy manifest-driven provisioning configurations (deprecated)

**`remote_write.py`** - Prometheus remote_write protocol parser
- Decodes Prometheus protobuf format
- Maps Prometheus metrics to `GpuMetric` fields
- Handles compression (snappy, gzip)
- **Async parsing**: CPU-bound protobuf parsing offloaded to thread pool (4 workers) to prevent GIL blocking
- **`parse_remote_write_async()`**: Async wrapper that runs parsing in thread pool executor

#### Database: TimescaleDB

- PostgreSQL 15 with TimescaleDB extension
- Hypertables for time-series optimization
- Automatic data retention policies
- Efficient time-range queries with indexes

#### Cache: Redis

- **WebSocket pub/sub** (optional): When `TELEMETRY_REDIS_URL` is configured, `LiveMetricsBroker` uses Redis pub/sub for cross-instance message distribution
- Session management
- Temporary data caching
- **Note**: Redis is optional - system works with in-memory broker for single-instance deployments

### 3.3 Remote Monitoring Stack

The remote monitoring stack is deployed on GPU instances via SSH and consists of multiple exporters and Prometheus.

#### Three Exporters

**1. DCGM Exporter (Port 9400)**
- Exposes NVIDIA DCGM metrics via HTTP
- Profiling metrics: SM utilization, SM occupancy, tensor core activity
- Pipeline activity: FP64, FP32, FP16 active percentages
- Memory bandwidth: HBM utilization, PCIe TX/RX, NVLink TX/RX
- Power & thermal: Power draw, temperature, throttle reasons
- Clock frequencies: SM, memory, graphics clocks
- Error tracking: ECC errors (single-bit, double-bit), PCIe replay errors
- Requires DCGM library and profiling mode enabled

**2. NVIDIA-SMI Exporter (Port 9401)**
- Python script that queries `nvidia-smi` periodically
- Standard metrics: GPU utilization, memory utilization
- Memory stats: Total, free, used (MiB)
- Temperature, power draw, power limit
- Clock speeds: SM, memory, graphics (MHz)
- Fan speed, PCIe link info, encoder stats
- No special requirements (works with standard nvidia-smi)

**3. Token Throughput Exporter (Port 9402)**
- Application-level metrics placeholder
- Accepts POST requests to `/update` endpoint
- Metrics: `tokens_per_second`, `total_tokens`, `requests_per_second`, `total_requests`
- Workloads can push inference metrics in real-time
- Health check endpoint for verification

#### Prometheus

- Scrapes all three exporters at configurable intervals
- Aggregates metrics and forwards to backend via `remote_write`
- Configured with backend URL and run_id in headers
- Handles metric relabeling and filtering

#### Deployment Process

**SSH-Based Deployment (Push Model)**:
1. **Job Enqueueing**: Frontend creates deployment request → Job enqueued in `deployment_jobs` table
2. **Worker Processing**: Background worker picks up job, locks it for processing
3. **SSH Connection**: Backend connects to remote host using provided credentials
4. **Prerequisite Validation**: Checks NVIDIA driver, Docker, DCGM, etc.
5. **Auto-Installation**: Installs missing prerequisites (Docker, NVIDIA Container Toolkit, DCGM) if user has sudo access
6. **File Upload**: Uploads Docker Compose file, Prometheus config, exporter scripts
7. **Docker Compose**: Starts all services in isolated network
8. **Health Checks**: Validates all exporters are responding
9. **Status Reporting**: Updates job status, returns deployment status to frontend
10. **Retry Logic**: On failure, job is retried up to `max_attempts` with exponential backoff

**Agent-Based Deployment (Pull Model - API Key-Based)** - ✅ **Fully Functional**:
1. **API Key Creation**: User creates a provisioning API key via frontend (one key can be used for all instances)
2. **Agent Installation**: User runs single install command on GPU instance (one-time setup):
   ```bash
   curl -fsSL https://omniference.com/install | sudo bash -s -- --api-key={api_key} --instance-id={instance_id}
   ```
3. **Install Script Execution**: The install script automatically:
   - Checks for NVIDIA driver (nvidia-smi)
   - Installs Docker if not present
   - Installs NVIDIA Container Toolkit
   - Downloads and installs the agent binary from `https://omniference.com/install`
   - Registers the instance with the backend using API key
   - Deploys the monitoring stack (Prometheus, exporters) automatically
   - Creates and starts the agent service (systemd)
4. **Prerequisite Installation**: Agent installs Docker, NVIDIA Container Toolkit, DCGM if needed (automatic)
5. **Stack Deployment**: Agent deploys Docker Compose stack automatically
6. **Heartbeat Reporting**: Agent sends periodic heartbeats to backend with status updates (every 30s)
7. **Status Tracking**: Backend updates deployment status based on agent heartbeats
8. **UI Monitoring**: Frontend displays agent status, deployment phases, and heartbeats in real-time
9. **Status (December 2024)**: ✅ Fully operational - agent successfully deploys monitoring stack on remote instances

#### Network Flow

- Remote Prometheus → Backend `/api/telemetry/remote-write` (HTTPS)
- Backend must be accessible from remote instance (public IP or VPN)
- WebSocket connections: Frontend → Backend `/ws/runs/{run_id}/live`

---

## Data Flow Diagrams

### 4.1 Deployment Flow

#### Mermaid Sequence Diagram - SSH Deployment

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Backend
    participant Queue
    participant Worker
    participant SSH
    participant Remote
    
    User->>Frontend: Click "Start Monitoring" (SSH)
    Frontend->>Backend: POST /api/runs (create run)
    Backend->>Backend: Create Run record in DB
    Backend-->>Frontend: Run ID
    
    Frontend->>Backend: POST /instances/{id}/deploy?deployment_type=ssh
    Backend->>Queue: Enqueue deployment job
    Queue->>Backend: Job ID (queued)
    Backend-->>Frontend: Deployment job queued
    
    Worker->>Queue: Poll for next job
    Queue-->>Worker: Job (locked)
    Worker->>SSH: Connect via Paramiko
    SSH->>Remote: Establish SSH connection
    
    Worker->>Remote: Validate prerequisites
    Remote-->>Worker: System info
    
    alt Prerequisites Missing
        Worker->>Remote: Auto-install (Docker, DCGM, etc.)
        Remote-->>Worker: Installation status
    end
    
    Worker->>Remote: Upload docker-compose.yml
    Worker->>Remote: Upload prometheus.yml
    Worker->>Remote: Upload exporter scripts
    
    Worker->>Remote: docker compose up -d
    Remote->>Remote: Start all services
    
    Worker->>Remote: Health check
    Remote-->>Worker: Health status
    
    Worker->>Queue: Mark job completed
    Backend-->>Frontend: Deployment status: running
    
    Frontend->>Frontend: Connect WebSocket when ready
```

#### Mermaid Sequence Diagram - Agent Deployment (API Key-Based)

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Backend
    participant InstallScript
    participant Agent
    participant Remote
    
    User->>Frontend: Create API Key
    Frontend->>Backend: POST /api/telemetry/provision/api-keys
    Backend->>Backend: Generate API key (SHA256 hash stored)
    Backend-->>Frontend: API Key (shown once)
    
    User->>Remote: SSH into GPU instance
    User->>Remote: Run install command
    Note over User,Remote: curl -fsSL https://omniference.com/install | sudo bash -s -- --api-key={key} --instance-id={id}
    
    Remote->>InstallScript: Download & execute install script
    InstallScript->>Remote: Check NVIDIA driver
    InstallScript->>Remote: Install Docker (if needed)
    InstallScript->>Remote: Install NVIDIA Container Toolkit
    InstallScript->>Remote: Download agent binary
    InstallScript->>Backend: Register instance (API key auth)
    Backend->>Backend: Validate API key & create run
    Backend-->>InstallScript: Registration confirmed
    
    InstallScript->>Remote: Deploy Docker Compose stack
    InstallScript->>Remote: Create systemd service
    InstallScript->>Remote: Start agent service
    Remote->>Agent: Start agent process
    
    Agent->>Remote: Install prerequisites (Docker, DCGM, etc.)
    Remote-->>Agent: Installation status
    
    Agent->>Remote: Deploy Docker Compose stack
    Remote->>Remote: Start Prometheus & Exporters
    
    Agent->>Backend: POST /provision/callbacks (heartbeat: deploying)
    Backend->>Backend: Update deployment status
    
    Agent->>Backend: POST /provision/callbacks (heartbeat: running)
    Backend->>Backend: Mark deployment completed
    Backend-->>Frontend: Deployment status: running
    
    loop Every 30 seconds
        Agent->>Backend: POST /provision/callbacks (heartbeat: healthy)
        Backend-->>Frontend: Update agent status
    end
    
    Frontend->>Frontend: Connect WebSocket when ready
```

#### ASCII Sequence Diagram

```
User                    Frontend                Backend              Remote Host
 │                         │                       │                      │
 │  Click "Start"          │                       │                      │
 ├────────────────────────>│                       │                      │
 │                         │  POST /runs            │                      │
 │                         ├───────────────────────>│                      │
 │                         │                       │  Create Run          │
 │                         │                       │  (Database)          │
 │                         │  Run ID               │                      │
 │                         │<───────────────────────┤                      │
 │                         │                       │                      │
 │                         │  POST /deploy          │                      │
 │                         ├───────────────────────>│                      │
 │                         │                       │  SSH Connect         │
 │                         │                       ├─────────────────────>│
 │                         │                       │  Validate Prereqs     │
 │                         │                       │<─────────────────────┤
 │                         │                       │  Upload Files        │
 │                         │                       ├─────────────────────>│
 │                         │                       │  docker compose up   │
 │                         │                       ├─────────────────────>│
 │                         │                       │                      │  Start Services
 │                         │                       │  Health Check        │
 │                         │                       │<─────────────────────┤
 │                         │  Status: deploying     │                      │
 │                         │<───────────────────────┤                      │
 │                         │                       │                      │
 │                         │  Poll Status          │                      │
 │                         ├───────────────────────>│                      │
 │                         │  Status: running       │                      │
 │                         │<───────────────────────┤                      │
 │  Connect WebSocket      │                       │                      │
 ├────────────────────────>│                       │                      │
```

### 4.2 Metrics Collection Flow

#### Mermaid Sequence Diagram

```mermaid
sequenceDiagram
    participant GPU
    participant Exporters
    participant Prometheus
    participant Backend
    participant DB
    participant Broker
    participant Frontend
    
    GPU->>Exporters: Hardware metrics (DCGM/nvidia-smi)
    Exporters->>Prometheus: HTTP metrics (port 9400/9401/9402)
    
    Prometheus->>Prometheus: Scrape exporters (every 5s)
    Prometheus->>Prometheus: Aggregate metrics
    
    Prometheus->>Backend: POST /remote-write (Prometheus protocol)
    Note over Prometheus,Backend: X-Run-ID header identifies run
    
    Backend->>Backend: Rate limit check (200 req/s per run_id)
    alt Rate limit exceeded
        Backend-->>Prometheus: 429 Too Many Requests (Retry-After)
    end
    
    Backend->>Backend: Parse remote_write (protobuf in thread pool)
    Note over Backend: Async parsing prevents GIL blocking
    
    Backend->>Backend: Map to GpuMetric schema
    
    Backend->>Backend: Circuit breaker check
    alt Circuit breaker open
        Backend-->>Prometheus: 503 Service Unavailable (Retry-After)
    end
    
    par Parallel Processing
        Backend->>DB: INSERT metrics (chunked: 100 samples/transaction)
        Note over Backend,DB: Chunked batches prevent long transactions
        DB-->>Backend: Confirmation
    and
        Backend->>Broker: publish(run_id, metrics)
        alt Redis configured
            Broker->>Redis: PUBLISH channel
            Redis->>Broker: Distribute to all instances
        end
        Broker->>Frontend: WebSocket message
        Frontend->>Frontend: Update charts (real-time)
    and
        Backend->>Backend: Policy evaluation
        Backend->>DB: INSERT policy events (if violations)
    end
    
    Frontend->>Backend: GET /api/runs/{run_id}/metrics?start_time=...
    Backend->>DB: Query time-range
    DB-->>Backend: Historical metrics
    Backend-->>Frontend: JSON response
    Frontend->>Frontend: Render historical charts
```

#### ASCII Flow Diagram

```
┌─────────┐
│   GPU   │
└────┬────┘
     │ Hardware Metrics
     │
┌────▼─────────────────────────────────┐
│         Exporters                     │
│  ┌──────────┐  ┌──────────┐        │
│  │  DCGM     │  │ NVIDIA-  │        │
│  │  (9400)   │  │ SMI (9401)│        │
│  └────┬──────┘  └────┬──────┘        │
│       │              │                │
└───────┼──────────────┼────────────────┘
        │ HTTP Metrics │
        │              │
┌───────▼──────────────▼────────────────┐
│      Prometheus                        │
│  - Scrapes every 5s                   │
│  - Aggregates metrics                 │
└───────┬────────────────────────────────┘
        │
        │ Remote Write (Prometheus Protocol)
        │ POST /api/telemetry/remote-write
        │
┌───────▼────────────────────────────────┐
│         Backend                        │
│  ┌──────────────────────────────────┐ │
│  │  Parse & Map Metrics             │ │
│  └──────┬───────────────────────────┘ │
│         │                              │
│  ┌──────▼──────────┐  ┌─────────────┐│
│  │  Database        │  │ Live Broker ││
│  │  (TimescaleDB)   │  │ (Pub/Sub)   ││
│  └─────────────────┘  └──────┬──────┘│
└────────────────────────────────┼───────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
            ┌───────▼───┐  ┌─────▼────┐  ┌───▼────┐
            │ Historical│  │ Real-Time│  │ Policy │
            │   Query   │  │ WebSocket│  │ Events │
            └───────────┘  └──────────┘  └────────┘
                    │            │
            ┌───────▼────────────▼───────┐
            │        Frontend            │
            │  - Historical Charts       │
            │  - Real-Time Charts       │
            └───────────────────────────┘
```

### 4.3 WebSocket Real-Time Streaming

#### Mermaid Diagram

```mermaid
graph LR
    subgraph "Backend"
        RW[remote_write<br/>Endpoint]
        PARSE[Parse Metrics]
        BROKER[LiveMetricsBroker]
        WS_EP[WebSocket<br/>Endpoint]
        QUEUE[asyncio.Queue<br/>per run_id]
    end
    
    subgraph "Frontend"
        WS_CLIENT[WebSocket<br/>Client]
        CHARTS[Chart<br/>Components]
    end
    
    RW --> PARSE
    PARSE --> BROKER
    BROKER --> QUEUE
    QUEUE --> WS_EP
    WS_EP <--> WS_CLIENT
    WS_CLIENT --> CHARTS
    
    style BROKER fill:#e1f5ff
    style QUEUE fill:#fff4e1
```

#### Authentication

The WebSocket endpoint supports two authentication methods:

1. **JWT Token** (for authenticated users): Frontend automatically includes JWT token
   - URL: `wss://domain.com/ws/runs/{run_id}/live?authorization=Bearer%20{jwt_token}`
   - Validates that the user owns the run
   - Preferred method for frontend connections

2. **Ingest Token** (for unauthenticated access): Use ingest token from run creation
   - URL: `ws://domain.com/ws/runs/{run_id}/live?token={ingest_token}`
   - Validates token hash against run's `ingest_token_hash`
   - Used by external systems or when JWT is not available

**Note**: If the run has no ingest token, connection is allowed (backwards compatibility). If the run has a token, either JWT (user must own run) or ingest token is required.

#### Connection Lifecycle

```
1. Frontend connects: ws://backend/ws/runs/{run_id}/live?authorization=Bearer%20{jwt_token}
   OR: ws://backend/ws/runs/{run_id}/live?token={ingest_token}
2. Backend validates authentication:
   - If JWT: Verify user owns the run
   - If ingest token: Verify token hash matches run's ingest_token_hash
   - If no token and run has no ingest_token_hash: Allow (backwards compatibility)
3. If authentication fails: Close connection with code 1008 (Policy Violation)
4. If authentication succeeds: Backend accepts connection
5. Backend registers queue with LiveMetricsBroker
6. When metrics arrive via remote_write:
   a. Parse and map metrics (async, offloaded to thread pool)
   b. Call live_broker.publish(run_id, metrics)
   c. Broker puts message in all queues for that run_id (or Redis pub/sub)
   d. WebSocket endpoint reads from queue
   e. Send JSON to frontend
7. Frontend receives message and updates charts
8. On disconnect, unregister queue
```

---

## Technology Stack

### Frontend

- **React 18**: UI framework
- **Material-UI (MUI)**: Component library
- **Recharts**: Charting library for time-series visualization
- **WebSocket API**: Native browser WebSocket for real-time updates
- **Axios**: HTTP client for REST API calls

### Backend

- **FastAPI**: Modern Python web framework with async support
- **SQLAlchemy (async)**: ORM with async database drivers
- **Paramiko**: SSH client library for remote deployments
- **asyncio**: Asynchronous I/O for concurrent operations
- **Pydantic**: Data validation and serialization
- **Prometheus Client**: Remote_write protocol parsing

### Database

- **TimescaleDB**: PostgreSQL extension optimized for time-series data
  - Hypertables for automatic partitioning
  - Compression and retention policies
  - Efficient time-range queries
- **PostgreSQL 15**: Underlying relational database

### Cache

- **Redis 7**: In-memory data store
  - Optional WebSocket session management
  - Temporary data caching

### Remote Stack

- **Docker**: Containerization platform
- **Docker Compose**: Multi-container orchestration
- **Prometheus**: Metrics aggregation and forwarding
- **NVIDIA DCGM**: GPU management and profiling library
- **nvidia-smi**: Command-line GPU monitoring tool
- **Python 3**: Exporter scripts runtime

### Infrastructure

- **Docker Compose**: Local development and deployment
- **Nginx**: Reverse proxy for frontend (production)
- **SSH**: Secure remote access protocol

---

## Deployment Architecture

### 6.1 Local Development Stack

#### Mermaid Diagram

```mermaid
graph TB
    subgraph "Docker Compose Network"
        TSDB[TimescaleDB<br/>Port 5432]
        REDIS[Redis<br/>Internal]
        BACKEND[Backend<br/>Port 8000]
        FRONTEND[Frontend<br/>Port 3000]
    end
    
    TSDB -.->|Health Check| TSDB
    REDIS -.->|Health Check| REDIS
    BACKEND -->|Depends On| TSDB
    BACKEND -->|Depends On| REDIS
    FRONTEND -->|Depends On| BACKEND
    BACKEND -->|Connects| TSDB
    BACKEND -->|Connects| REDIS
    
    DEV[Developer] -->|HTTP :3000| FRONTEND
    DEV -->|HTTP :8000| BACKEND
    FRONTEND -->|API Calls| BACKEND
```

#### Service Dependencies

```
timescaledb (PostgreSQL 15 + TimescaleDB)
  ├─ Health check: pg_isready
  ├─ Port: 5432 (host) → 5432 (container)
  └─ Volume: timescaledb-data (persistent)

redis (Redis 7 Alpine)
  ├─ Health check: redis-cli ping
  ├─ Port: Internal only (no host mapping)
  └─ Purpose: Cache and sessions

omniference-backend (FastAPI)
  ├─ Depends on: timescaledb (healthy), redis (healthy)
  ├─ Port: 8000 (host) → 8000 (container)
  ├─ Environment: Database URL, Redis URL, API keys
  ├─ Health check: curl http://localhost:8000/health
  └─ Volumes: ./backend/examples (for examples)

frontend (React + Nginx)
  ├─ Depends on: omniference-backend (healthy)
  ├─ Port: 3000 (host) → 80 (container)
  ├─ Build args: REACT_APP_API_URL
  └─ Serves: Static React build via Nginx
```

### 6.2 Remote GPU Instance Deployment

#### Mermaid Diagram - Dual Deployment Methods

```mermaid
graph TB
    subgraph "Backend Server"
        QUEUE[Deployment Queue]
        WORKER[Deployment Worker]
        DEPLOY[Deployment Manager<br/>SSH Orchestration]
        PROVISION[Provisioning API<br/>API Keys & Heartbeats]
        SSH_CLIENT[Paramiko SSH Client]
    end
    
    subgraph "Network"
        INTERNET[Internet/Cloud Network]
    end
    
    subgraph "Remote GPU Instance - SSH Path"
        SSH_DAEMON[SSH Daemon]
        DOCKER_HOST_SSH[Docker Engine]
        
        subgraph "Docker Network: gpu-telemetry"
            PROM_SSH[Prometheus<br/>:9090]
            DCGM_SSH[DCGM Exporter<br/>:9400]
            SMI_SSH[NVIDIA-SMI Exporter<br/>:9401]
            TOKEN_SSH[Token Exporter<br/>:9402]
        end
        
        GPU_HW_SSH[GPU Hardware]
    end
    
    subgraph "Remote GPU Instance - Agent Path"
        AGENT[Provisioning Agent<br/>Go Binary]
        DOCKER_HOST_AGENT[Docker Engine]
        
        subgraph "Docker Network: gpu-telemetry"
            PROM_AGENT[Prometheus<br/>:9090]
            DCGM_AGENT[DCGM Exporter<br/>:9400]
            SMI_AGENT[NVIDIA-SMI Exporter<br/>:9401]
            TOKEN_AGENT[Token Exporter<br/>:9402]
        end
        
        GPU_HW_AGENT[GPU Hardware]
    end
    
    QUEUE --> WORKER
    WORKER --> DEPLOY
    WORKER --> PROVISION
    
    DEPLOY -->|SSH Connection| SSH_CLIENT
    SSH_CLIENT -->|Port 22| INTERNET
    INTERNET -->|Port 22| SSH_DAEMON
    SSH_DAEMON --> DOCKER_HOST_SSH
    DOCKER_HOST_SSH --> PROM_SSH
    DOCKER_HOST_SSH --> DCGM_SSH
    DOCKER_HOST_SSH --> SMI_SSH
    DOCKER_HOST_SSH --> TOKEN_SSH
    DCGM_SSH --> GPU_HW_SSH
    SMI_SSH --> GPU_HW_SSH
    
    PROVISION -.Manifest & Token.->|HTTPS| INTERNET
    INTERNET -.Manifest Request.->|HTTPS GET| AGENT
    AGENT -.Heartbeats.->|HTTPS POST| INTERNET
    INTERNET -.Heartbeats.->|HTTPS POST| PROVISION
    AGENT --> DOCKER_HOST_AGENT
    DOCKER_HOST_AGENT --> PROM_AGENT
    DOCKER_HOST_AGENT --> DCGM_AGENT
    DOCKER_HOST_AGENT --> SMI_AGENT
    DOCKER_HOST_AGENT --> TOKEN_AGENT
    DCGM_AGENT --> GPU_HW_AGENT
    SMI_AGENT --> GPU_HW_AGENT
    
    PROM_SSH -->|Remote Write<br/>HTTPS| INTERNET
    PROM_AGENT -->|Remote Write<br/>HTTPS| INTERNET
    INTERNET -->|POST /remote-write| DEPLOY
```

#### Remote Directory Structure

```
/tmp/gpu-telemetry-{run_id}/
├── docker-compose.yml          # Service definitions
├── prometheus.yml               # Prometheus configuration
├── dcgm-collectors.csv         # DCGM metric collectors
├── nvidia-smi-exporter.py      # NVIDIA-SMI exporter script
├── token-exporter.py           # Token metrics exporter
├── dcgm-health-exporter.py     # DCGM health check exporter
└── check_prerequisites.sh      # Prerequisite validation script
```

#### Network Flow

```
Remote Prometheus → Backend API
  - Protocol: Prometheus remote_write (HTTP POST)
  - Endpoint: https://backend-domain/api/telemetry/remote-write
  - Headers: X-Run-ID: {run_id}, Content-Encoding: snappy/gzip
  - Payload: Prometheus WriteRequest protobuf

Backend must be accessible from remote instance:
  - Public IP address, OR
  - VPN connection, OR
  - Cloud provider private network
```

#### Port Requirements

**Remote Instance (Inbound)**:
- Port 22 (SSH): Required for deployment
- No other inbound ports needed (exporters are internal to Docker network)

**Remote Instance (Outbound)**:
- HTTPS (443): To reach backend remote_write endpoint
- HTTP (80): For package repositories, Docker Hub

**Backend Server (Inbound)**:
- Port 8000 (HTTP): API endpoints
- Port 443 (HTTPS): If using reverse proxy
- WebSocket: Upgraded from HTTP connection

---

## API Endpoints Overview

### REST Endpoints

#### Run Management (`/api/runs`)

- `POST /api/runs` - Create a new monitoring run
  - Request: `RunCreate` (instance_id, gpu_model, gpu_count, tags, notes)
  - Response: `RunDetail` (run_id, status, timestamps)

- `GET /api/runs` - List runs
  - Query params: `instance_id`, `status`, `limit`
  - Response: `RunListResponse` (runs array)

- `GET /api/runs/{run_id}` - Get run details
  - Response: `RunDetail`

- `PATCH /api/runs/{run_id}` - Update run
  - Request: `RunUpdate` (status, end_time, notes)
  - Response: `RunDetail`

- `DELETE /api/runs/{run_id}` - Delete run and all metrics

- `GET /api/runs/history/all` - List all runs (history view)
- `GET /api/runs/history/no-data` - List runs with no metric data
- `DELETE /api/runs/cleanup/no-data` - Delete runs with no metric data
- `PATCH /api/runs/bulk/status` - Bulk update run statuses

#### Deployment (`/api/instances/{instance_id}`)

- `POST /api/instances/{instance_id}/deploy` - Deploy monitoring stack (enqueues job)
  - Query params: `deployment_type` ("ssh" or "agent", default: "ssh")
  - Request: `DeploymentRequest` 
    - For SSH: `run_id`, `ssh_host`, `ssh_user`, `ssh_key`, `backend_url`, `poll_interval`, `enable_profiling`
    - For Agent: `run_id`, `backend_url`, `poll_interval`, `enable_profiling` (SSH fields optional)
  - Response: `DeploymentResponse` (deployment_id=job_id, status="queued")

- `GET /api/instances/{instance_id}/deployments/{deployment_id}` - Get deployment status
  - Response: `DeploymentStatusResponse` (status, services, message)
  - Supports both job_id (new queue-based) and legacy deployment_id

- `POST /api/instances/{instance_id}/teardown` - Stop and remove monitoring stack
  - Request: `TeardownRequest` (run_id)

- `GET /api/instances/{instance_id}/component-status` - Check component health
  - Response: Component status for each service

- `GET /api/instances/prerequisites` - Get prerequisite list
  - Response: `PrerequisitesResponse` (prerequisites array)
  - Used by both TelemetryTab and ProvisioningTab to display required system prerequisites
  - Each prerequisite includes: title, description, install_hint (optional), docs_link (optional)

#### Deployment Queue (`/api/instances/jobs`)

- `GET /api/instances/jobs` - List deployment jobs
  - Query params: `instance_id`, `status`, `limit`
  - Response: `DeploymentJobListResponse` (jobs array, stats)

- `GET /api/instances/jobs/{job_id}` - Get specific deployment job
  - Response: `DeploymentJobRead` (full job details)

- `POST /api/instances/jobs/{job_id}/retry` - Retry a failed job
  - Response: `DeploymentJobRead` (updated job)

- `POST /api/instances/jobs/{job_id}/cancel` - Cancel a pending/queued job
  - Response: `DeploymentJobRead` (cancelled job)

- `GET /api/instances/queue/stats` - Get queue statistics
  - Response: `{"pending": int, "queued": int, "running": int, "completed": int, "failed": int, "cancelled": int}`

#### Provisioning (`/api/telemetry/provision`)

**API Key Management**:
- `POST /api/telemetry/provision/api-keys` - Create provisioning API key
  - Request: `ProvisioningAPIKeyCreate` (name, description)
  - Response: `ProvisioningAPIKeyResponse` (key_id, api_key, name, description, created_at)
  - Note: API key is only shown once in response - must be copied immediately

- `GET /api/telemetry/provision/api-keys` - List all API keys
  - Query params: `include_revoked` (default: false)
  - Response: `list[ProvisioningAPIKeyRead]` (keys without secret values)

- `POST /api/telemetry/provision/api-keys/{key_id}/revoke` - Revoke an API key
  - Response: `ProvisioningAPIKeyRead` (revoked key)

**Agent Heartbeats**:
- `POST /api/telemetry/provision/callbacks` - Agent heartbeat endpoint
  - Request: `AgentHeartbeatCreate` (instance_id, api_key, phase, status, message, metadata)
  - Response: `AgentHeartbeatRead`
  - Used by agent to report status every 30 seconds

- `GET /api/telemetry/provision/callbacks/{instance_id}/status` - Get latest agent status
  - Response: Latest heartbeat for instance

**Legacy Manifest Endpoints** (deprecated, may still exist for backward compatibility):
- `POST /api/telemetry/provision/manifests/{deployment_job_id}` - Create provisioning manifest
- `GET /api/telemetry/provision/manifests/{manifest_id}` - Fetch manifest (for agent)

#### Metrics (`/api`)

- `GET /api/runs/{run_id}/metrics` - Query historical metrics
  - Query params: `start_time`, `end_time`, `gpu_id`, `limit`
  - Response: `MetricsResponse` (samples array with time-series data)

- `POST /api/metrics/batch` - Batch ingest metrics (alternative to remote_write)
  - Request: `MetricsBatch` (run_id, metrics array)
  - Response: `{"inserted": count}`

#### Remote Write (`/api/telemetry/remote-write`)

- `POST /api/telemetry/remote-write` - Prometheus remote_write endpoint
  - Headers:
    - `X-Run-ID` (required): The run ID to ingest metrics for
    - `X-Ingest-Token` (required if run has token): Authentication token returned at run creation
    - `Content-Encoding` (optional): `snappy` or `gzip` for compressed payloads
  - Body: Prometheus WriteRequest protobuf
  - **Authentication**: Token-based authentication via `X-Ingest-Token` header
    - Token is generated when run is created and returned once
    - Must be stored securely and included in all remote_write requests
    - 401 Unauthorized if token is missing or invalid
  - **Rate Limiting**: 200 req/s per run_id with 400 burst (429 if exceeded)
  - **Circuit Breaker**: Returns 503 if database is failing (with Retry-After header)
  - **Performance Optimizations**:
    - Async protobuf parsing (thread pool executor, 4 workers)
    - Chunked batch insertion (100 samples per transaction)
    - Backpressure-aware live broadcasting
  - Response: `202 Accepted`, `401 Unauthorized`, `429 Too Many Requests`, or `503 Service Unavailable`
  
  **Prometheus Configuration Example**:
  ```yaml
  remote_write:
    - url: 'https://api.omniference.com/api/telemetry/remote-write'
      headers:
        X-Run-ID: '${RUN_ID}'
        X-Ingest-Token: '${INGEST_TOKEN}'  # Token from run creation
      queue_config:
        capacity: 10000
        max_samples_per_send: 1000
  ```

#### Health & Policy (`/api`)

- `GET /api/runs/{run_id}/health` - Get health summary
  - Response: `HealthSummary` (gpu_count, sample_count, latest_time, alerts)

- `GET /api/runs/{run_id}/policy-events` - Get policy violation events
  - Query params: `severity`, `limit`
  - Response: `PolicyEventsResponse` (events array)

- `POST /api/runs/{run_id}/topology` - Create/update GPU topology
- `GET /api/runs/{run_id}/topology` - Get GPU topology

#### Credentials (`/api/credentials`)

- `POST /api/credentials` - Store encrypted credential
  - Request: `CredentialCreate` (provider, name, credential_type, secret, description)
  - Response: `CredentialDetail`

- `GET /api/credentials` - List credentials
  - Response: `CredentialDetail[]`

- `GET /api/credentials/with-secret` - List credentials with decrypted secrets
- `GET /api/credentials/{credential_id}` - Get credential (decrypted)
  - Response: `CredentialWithSecret`

- `PATCH /api/credentials/{credential_id}` - Update credential
- `DELETE /api/credentials/{credential_id}` - Delete credential

#### SM Profiling (`/api/sm-profiling`)

- `POST /api/sm-profiling/trigger` - Trigger SM-level profiling
  - Request: `TriggerProfilingRequest` (run_id, gpu_id, metric_name, ssh_host, ssh_user, ssh_key)
  - Response: `TriggerProfilingResponse` (session_id)

- `GET /api/sm-profiling/sessions/{session_id}/status` - Get profiling status
  - Response: `ProfilingStatusResponse` (status, error_message)

- `GET /api/sm-profiling/sessions/{session_id}/results` - Get profiling results
  - Response: `SMMetricsResponse` (metrics array per SM)

- `GET /api/sm-profiling/health` - Health check for profiling service

#### AI Insights (`/api/ai-insights`)

- `POST /api/ai-insights` - Get AI-powered metric analysis
  - Request: `TelemetryInsightRequest` (metric_name, metric_key, unit, data, gpu_ids)
  - Response: `TelemetryInsightResponse` (insights, recommendations)

#### Workflow Orchestration (`/api/workflow`)

The workflow API provides multi-phase orchestration for instance setup, deployment, and benchmarking:

- `POST /api/workflow/setup-instance` - Phase 1: Setup instance (install drivers, CUDA, DCGM, download model)
  - Request: `SetupInstanceRequest` (ssh_host, ssh_user, pem_base64, model_name, model_path)
  - Response: `WorkflowResponse` (workflow_id, message, status)

- `POST /api/workflow/check-instance` - Phase 2: Check instance (verify nvidia-smi, restart DCGM)
  - Request: `CheckInstanceRequest` (ssh_host, ssh_user, pem_base64)
  - Response: `WorkflowResponse` (workflow_id, message, status)

- `POST /api/workflow/deploy-vllm` - Phase 3: Deploy inference server
  - Request: `DeployVLLMRequest` (ssh_host, ssh_user, pem_base64, model_path, max_model_len, max_num_seqs, gpu_memory_utilization, tensor_parallel_size)
  - Response: `WorkflowResponse` (workflow_id, message, status)

- `POST /api/workflow/run-benchmark` - Phase 4: Run benchmark
  - Request: `RunBenchmarkRequest` (ssh_host, ssh_user, pem_base64, num_requests, input_seq_len, output_seq_len, max_concurrency)
  - Response: `WorkflowResponse` (workflow_id, message, status)

- `GET /api/workflow/logs/{workflow_id}` - Get workflow logs
  - Query params: `phase` (optional: setup, check, deploy, benchmark)
  - Response: `WorkflowLogsResponse` (logs, status, message, container_logs)

#### Instance Orchestration (`/api/telemetry/instances/orchestrate`)

- `POST /api/telemetry/instances/orchestrate` - Start instance orchestration
  - Headers: `X-Lambda-API-Key` (optional, for Lambda Cloud)
  - Request: `InstanceOrchestrationRequest` (instance_type, region, ssh_key_name, ssh_key)
  - Response: `InstanceOrchestrationStatus` (orchestration_id, status, phases)
  - **Status (December 2024)**: ✅ Fixed - `get_session` import issue resolved

- `GET /api/telemetry/instances/orchestrate/{orchestration_id}/status` - Get orchestration status
- `GET /api/telemetry/instances/orchestrate/by-instance/{instance_id}` - Get status by instance
- `POST /api/telemetry/instances/orchestrate/{orchestration_id}/deploy-model` - Deploy model to instance
- `GET /api/telemetry/instances/orchestrate/{orchestration_id}/model-progress` - Get model download progress
- `POST /api/telemetry/instances/orchestrate/proxy-inference` - Proxy inference requests to instance

### WebSocket Endpoints

- `WS /ws/runs/{run_id}/live?token={ingest_token}` - Live metrics stream
  - Protocol: WebSocket (upgraded from HTTP)
  - **Authentication**: Token-based via query parameter
    - `token` (required if run has ingest token): The ingest token from run creation
    - Connection closed with code 1008 (Policy Violation) if token is invalid/missing
  - Messages: JSON `{"type": "metrics", "data": [MetricSample...]}`
  - Client sends: Ping/pong for keepalive
  - Server sends: Metric samples as they arrive via remote_write
  - **Example**: `ws://localhost:8000/ws/runs/{run_id}/live?token=abc123...`

### Token Management Endpoints

- `POST /api/runs/{run_id}/regenerate-token` - Regenerate ingest token (protected)
  - Immediately invalidates the old token
  - Returns new token (one-time display, store securely)
  - Use when: token leaked, periodic rotation, revoke agent access
  - Response: `{"ingest_token": "new_token", "message": "..."}`

### Key Request/Response Schemas

**RunCreate**:
```python
{
  "instance_id": "string",
  "gpu_model": "string (optional)",
  "gpu_count": "integer (optional)",
  "tags": {"key": "value"} (optional),
  "notes": "string (optional)"
}
```

**DeploymentRequest**:
```python
{
  "run_id": "uuid",
  "ssh_host": "string (optional for agent, required for SSH)",
  "ssh_user": "string (optional for agent, required for SSH)",
  "ssh_key": "string (optional for agent, required for SSH)",
  "backend_url": "string (URL backend is accessible from remote)",
  "poll_interval": "integer (default: 5, seconds)",
  "enable_profiling": "boolean (default: false)"
}
```

**Note**: When `deployment_type="agent"`, SSH fields (`ssh_host`, `ssh_user`, `ssh_key`) are optional and ignored. Only `run_id`, `backend_url`, `poll_interval`, and `enable_profiling` are used.

**MetricSample** (from remote_write):
```python
{
  "time": "ISO 8601 datetime",
  "gpu_id": "integer",
  "gpu_utilization": "float (0-100)",
  "sm_utilization": "float (0-100, profiling only)",
  "power_draw_watts": "float",
  "temperature_celsius": "float",
  # ... 50+ more fields
}
```

---

## Database Schema

### Mermaid ER Diagram

```mermaid
erDiagram
    User ||--o{ Run : "creates"
    User ||--o{ StoredCredential : "owns"
    User ||--o{ ProvisioningAPIKey : "creates"
    Run ||--o{ GpuMetric : "has many"
    Run ||--o| RunSummary : "has one"
    Run ||--o{ GpuPolicyEvent : "generates"
    Run ||--o| GpuTopology : "has one"
    Run ||--o{ SMProfilingSession : "has many"
    Run ||--o{ DeploymentJob : "has many"
    SMProfilingSession ||--o{ SMMetric : "has many"
    DeploymentJob ||--o| ProvisioningManifest : "has one"
    ProvisioningManifest ||--o{ AgentHeartbeat : "receives"
    
    User {
        uuid user_id PK
        string email UK
        string hashed_password
        boolean is_active
        datetime created_at
        datetime last_login
    }
    
    Run {
        uuid run_id PK
        uuid user_id FK
        string instance_id
        string provider
        string gpu_model
        int gpu_count
        datetime start_time
        datetime end_time
        string status
        json tags
        text notes
        datetime created_at
    }
    
    GpuMetric {
        datetime time PK
        uuid run_id PK FK
        int gpu_id PK
        float gpu_utilization
        float sm_utilization
        float power_draw_watts
        float temperature_celsius
        float memory_used_mb
        float pcie_rx_mb_per_sec
        float nvlink_tx_mb_per_sec
        int ecc_sbe_errors
        int ecc_dbe_errors
    }
    
    RunSummary {
        uuid run_id PK FK
        float duration_seconds
        int total_samples
        float avg_gpu_utilization
        float max_gpu_utilization
        float total_energy_wh
    }
    
    GpuPolicyEvent {
        uuid event_id PK
        uuid run_id FK
        int gpu_id
        datetime event_time
        string event_type
        string severity
        text message
        float metric_value
    }
    
    GpuTopology {
        uuid topology_id PK
        uuid run_id FK
        json topology_data
        datetime captured_at
    }
    
    StoredCredential {
        uuid credential_id PK
        uuid user_id FK
        string provider
        string name
        string credential_type
        text secret_ciphertext
        datetime last_used_at
    }
    
    SMProfilingSession {
        uuid session_id PK
        uuid run_id FK
        string instance_id
        int gpu_id
        json metric_names
        string status
    }
    
    SMMetric {
        int id PK
        uuid session_id FK
        int sm_id
        string metric_name
        float value
    }
    
    DeploymentJob {
        uuid job_id PK
        uuid run_id FK
        string instance_id
        string deployment_type
        string status
        int priority
        int attempt_count
        int max_attempts
        json payload
        text error_message
        text error_log
        string locked_by
        datetime locked_at
        datetime started_at
        datetime completed_at
    }
    
    ProvisioningAPIKey {
        uuid key_id PK
        uuid user_id FK
        string key_hash UK
        string name
        text description
        datetime created_at
        datetime last_used_at
        datetime revoked_at
    }
    
    AgentHeartbeat {
        uuid heartbeat_id PK
        uuid manifest_id FK
        string instance_id
        string agent_version
        string phase
        string status
        text message
        json metadata
        datetime timestamp
    }
    
    ProvisioningManifest {
        uuid manifest_id PK
        uuid deployment_job_id FK
        string instance_id
        string token_hash
        json manifest_data
        datetime expires_at
    }
    Note: ProvisioningManifest is legacy/deprecated. New deployments use API key-based authentication.
    
    InstanceOrchestration {
        uuid orchestration_id PK
        string instance_id
        string status
        string current_phase
        int progress
        string ip_address
        string ssh_user
        string ssh_key_name
        string model_deployed
        json vllm_config
        text error_message
        datetime started_at
        datetime completed_at
    }
```

### Key Tables

#### `users`
- Primary key: `user_id` (UUID)
- Unique constraint: `email`
- Purpose: User accounts for API authentication
- Fields: `email`, `hashed_password`, `is_active`, `created_at`, `last_login`
- Relationships: One-to-many with `runs`, `stored_credentials`, `provisioning_api_keys`

#### `runs`
- Primary key: `run_id` (UUID)
- Foreign key: `user_id` → `users.user_id`
- Indexes: `instance_id`, `provider`, `start_time DESC`, `status`
- Purpose: Tracks monitoring sessions
- Relationships: One-to-many with `gpu_metrics`, one-to-one with `run_summaries`, one-to-many with `deployment_jobs`

#### `gpu_metrics`
- Primary key: `(time, run_id, gpu_id)` - Composite key for time-series
- Indexes: `(run_id, time DESC)`, `(run_id, gpu_id, time DESC)`
- Purpose: Stores individual metric samples (50+ fields)
- TimescaleDB: Configured as hypertable for time-series optimization
- Fields include:
  - Utilization: `gpu_utilization`, `sm_utilization`, `sm_occupancy`, `hbm_utilization`
  - Pipeline: `tensor_active`, `fp64_active`, `fp32_active`, `fp16_active`
  - Memory: `memory_used_mb`, `memory_total_mb`, `memory_utilization`
  - Power: `power_draw_watts`, `power_limit_watts`, `total_energy_joules`
  - Thermal: `temperature_celsius`, `memory_temperature_celsius`
  - Bandwidth: `pcie_rx_mb_per_sec`, `pcie_tx_mb_per_sec`, `nvlink_rx_mb_per_sec`, `nvlink_tx_mb_per_sec`
  - Errors: `ecc_sbe_errors`, `ecc_dbe_errors`, `pcie_replay_errors`, `xid_errors`
  - Configuration: `compute_mode`, `persistence_mode`, `ecc_mode`, clock frequencies

#### `run_summaries`
- Primary key: `run_id` (FK to `runs`)
- Purpose: Aggregated statistics for completed runs
- Computed fields: Averages, maximums, totals for key metrics

#### `gpu_policy_events`
- Primary key: `event_id` (UUID)
- Indexes: `(run_id, event_time DESC)`, `(run_id, severity, event_time DESC)`
- Purpose: Policy violation events (thermal, power, ECC errors)
- Fields: `event_type`, `severity`, `message`, `metric_value`, `threshold_value`

#### `credential_store`
- Primary key: `credential_id` (UUID)
- Foreign key: `user_id` → `users.user_id`
- Unique constraint: `(provider, name, credential_type, user_id)`
- Purpose: Encrypted storage for SSH keys and API credentials
- Security: `secret_ciphertext` is encrypted using Fernet (symmetric encryption)
- Fields: `provider`, `name`, `credential_type`, `secret_ciphertext`, `description`, `last_used_at`

#### `sm_profiling_sessions`
- Primary key: `session_id` (UUID)
- Purpose: Tracks SM-level profiling sessions
- Status: `pending`, `running`, `completed`, `failed`

#### `sm_metrics`
- Primary key: `id` (auto-increment)
- Foreign key: `session_id` → `sm_profiling_sessions.session_id`
- Purpose: Per-SM metric values from profiling
- Fields: `session_id`, `sm_id` (0-107 for H100), `metric_name`, `value`, `timestamp`
- Indexes: `session_id`, `sm_id`

#### `deployment_jobs`
- Primary key: `job_id` (UUID)
- Foreign key: `run_id` → `runs.run_id`
- Purpose: Deployment job queue with retry logic and per-instance locking
- Fields: `instance_id`, `deployment_type` (ssh/agent), `status`, `priority`, `attempt_count`, `max_attempts`, `payload` (JSON), `error_message`, `error_log`, `locked_by`, `locked_at`, `started_at`, `completed_at`
- Indexes: `instance_id`, `status`, `created_at DESC`, `(instance_id, status)`

#### `provisioning_api_keys`
- Primary key: `key_id` (UUID)
- Foreign key: `user_id` → `users.user_id`
- Unique constraint: `key_hash` (SHA256 hash of API key)
- Purpose: API keys for agent-based provisioning (long-lived, revocable)
- Fields: `key_hash`, `name`, `description`, `created_at`, `last_used_at`, `revoked_at`
- Indexes: `key_hash`, `revoked_at`

#### `agent_heartbeats`
- Primary key: `heartbeat_id` (UUID)
- Foreign key: `manifest_id` → `provisioning_manifests.manifest_id` (nullable for API key-based)
- Purpose: Agent heartbeat and status updates
- Fields: `instance_id`, `agent_version`, `phase` (installing/deploying/running), `status` (healthy/error/warning), `message`, `metadata` (JSON), `timestamp`
- Indexes: `instance_id`, `manifest_id`, `timestamp DESC`

#### `provisioning_manifests`
- Primary key: `manifest_id` (UUID)
- Foreign key: `deployment_job_id` → `deployment_jobs.job_id`
- Purpose: Legacy manifest-driven provisioning (deprecated, use API keys)
- Fields: `instance_id`, `token_hash` (SHA256), `manifest_data` (JSON), `expires_at`
- Indexes: `deployment_job_id`, `token_hash`, `expires_at`

#### `instance_orchestrations`
- Primary key: `orchestration_id` (UUID)
- Purpose: Instance launch and setup orchestration tracking
- Fields: `instance_id`, `status` (launching/waiting_ip/setting_up/deploying_model/ready/failed), `current_phase`, `progress` (0-100), `ip_address`, `ssh_user`, `ssh_key_name`, `model_deployed`, `vllm_config` (JSON), `error_message`, `logs`, `config` (JSON), `started_at`, `completed_at`, `last_updated`
- Indexes: `instance_id`, `status`

#### `gpu_topology`
- Primary key: `topology_id` (UUID)
- Foreign key: `run_id` → `runs.run_id`
- Unique constraint: `run_id` (one topology per run)
- Purpose: GPU topology and connectivity information
- Fields: `topology_data` (JSON), `captured_at`

### TimescaleDB Hypertables

The `gpu_metrics` table is configured as a TimescaleDB hypertable:

```sql
SELECT create_hypertable('gpu_metrics', 'time');
```

Benefits:
- Automatic time-based partitioning
- Efficient time-range queries
- Compression policies for old data
- Retention policies for data cleanup

### Indexes

- **Time-series queries**: `(run_id, time DESC)` - Fast time-range queries
- **Per-GPU queries**: `(run_id, gpu_id, time DESC)` - Filter by GPU
- **Run lookups**: `instance_id`, `status` - Fast run filtering
- **Policy events**: `(run_id, severity, event_time DESC)` - Alert queries

---

## Security Considerations

### SSH Key Management

- **Storage**: SSH private keys are encrypted before storage in database
- **Encryption**: Fernet symmetric encryption (AES-128 in CBC mode)
- **Key Derivation**: Encryption key derived from `TELEMETRY_CREDENTIAL_SECRET_KEY` environment variable
- **Transmission**: Keys sent over HTTPS only (never HTTP)
- **Frontend Display**: Keys masked by default in UI (user can toggle visibility)

**Implementation** (`backend/telemetry/crypto.py`):
- `encrypt_secret()`: Encrypts plaintext secrets
- `decrypt_secret()`: Decrypts ciphertext for use
- Uses `cryptography.fernet.Fernet` for encryption

### Credential Storage

- **Database**: `credential_store` table stores encrypted credentials
- **Fields**: `secret_ciphertext` contains encrypted data
- **Access Control**: Credentials are scoped by `provider` and `name`
- **Last Used**: Tracks `last_used_at` for audit purposes

### API Authentication

- **JWT-Based Authentication**: Most endpoints require JWT Bearer token authentication
  - **Auth Endpoints**: `/api/auth/register`, `/api/auth/login`, `/api/auth/me`
  - **Protected Endpoints**: All `/api/runs`, `/api/instances`, `/api/credentials`, `/api/telemetry/provision` endpoints require authentication
  - **Implementation**: FastAPI HTTPBearer with JWT tokens, user-scoped data access
  - **User Model**: `users` table stores email, hashed password, active status
  - **Data Isolation**: All user-facing endpoints filter by `user_id` to ensure data isolation

- **Token-Based Authentication**: Telemetry ingestion endpoints use per-run ingest tokens
  - **Remote Write**: `X-Ingest-Token` header required for `/api/telemetry/remote-write`
  - **WebSocket**: `?token=` query parameter required for `/ws/runs/{run_id}/live`
  - **Token Format**: 256-bit cryptographically secure random string (`secrets.token_urlsafe(32)`)
  - **Storage**: SHA256 hash stored in `ingest_token_hash` column (never plaintext)
  - **Lifecycle**: Token generated at run creation, can be regenerated via `/api/runs/{run_id}/regenerate-token`
  - **Tracking**: `token_created_at` timestamp tracks when token was created/rotated

- **Recommendation**: For production, also deploy behind reverse proxy (Nginx) with additional rate limiting

### Ingest Token Security

**Token Design**:
```python
# Generation (256-bit, cryptographically secure)
import secrets
ingest_token = secrets.token_urlsafe(32)  # e.g., "dQw4w9WgXcQ..."

# Storage (SHA256 hash, never plaintext)
import hashlib
token_hash = hashlib.sha256(ingest_token.encode()).hexdigest()

# Database storage
runs.ingest_token_hash = token_hash  # 64 chars hex
runs.token_created_at = now()  # Track rotation
```

**Token Validation Flow**:
1. Client sends token in `X-Ingest-Token` header (remote_write) or `?token=` query param (WebSocket)
2. Server computes SHA256 hash of provided token
3. Compare with stored `ingest_token_hash`
4. If mismatch: 401 Unauthorized (HTTP) or 1008 close code (WebSocket)

**Token Rotation**:
- `POST /api/runs/{run_id}/regenerate-token` invalidates old token immediately
- New token returned once (store securely)
- Use when: token leaked, periodic rotation, revoke agent access

### Network Security

- **SSH**: Uses standard SSH protocol (port 22) with key-based authentication
- **HTTPS/WSS**: All API and WebSocket traffic should use TLS in production
- **Remote Write**: Backend endpoint must be accessible from remote instances
  - Use HTTPS with valid certificate
  - Consider VPN for private networks
  - Firewall rules to restrict access

### Data Privacy

- **Metric Data**: Contains no personally identifiable information
- **Instance IDs**: May contain cloud provider instance identifiers
- **Retention**: Configure TimescaleDB retention policies to auto-delete old data
- **Encryption at Rest**: Database should use encrypted volumes in production

### Best Practices

1. **Environment Variables**: Store secrets in environment variables, not code
2. **Secret Rotation**: Rotate `TELEMETRY_CREDENTIAL_SECRET_KEY` periodically
3. **Network Isolation**: Use private networks/VPNs when possible
4. **Access Logging**: Log all credential access for audit
5. **Principle of Least Privilege**: SSH user should have minimal required permissions

---

## Performance & Scalability

### High-Throughput Ingestion Architecture

The telemetry ingestion system is optimized to handle 1,000+ GPUs with 5-second scrape intervals (200+ req/s). The following optimizations ensure low latency and high reliability:

#### 1. Chunked Batch Insertion

**Problem**: Inserting thousands of samples in a single transaction causes:
- Long-running transactions with lock contention
- Memory spikes from large INSERT statements
- Timeout risks under load

**Solution**: `TelemetryRepository.insert_metrics()` processes samples in chunks of 100 per transaction:

```python
async def insert_metrics(
    self,
    run_id: UUID,
    samples: Sequence[MetricSample],
    batch_size: int = 100,  # Configurable chunk size
) -> int:
    for i in range(0, len(samples), batch_size):
        chunk = samples[i:i + batch_size]
        # Insert chunk in separate transaction
        await self.session.execute(stmt)
```

**Benefits**:
- Shorter transactions reduce lock contention
- Lower memory footprint per operation
- Better TimescaleDB hypertable partitioning

#### 2. Async Protobuf Parsing

**Problem**: Python's protobuf parsing holds the GIL, blocking the event loop at high request rates.

**Solution**: Offload CPU-bound parsing to a thread pool executor:

```python
_parse_executor = ThreadPoolExecutor(max_workers=4)

async def parse_remote_write_async(body: bytes, ...) -> List[MetricSample]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _parse_executor,
        partial(parse_remote_write, body, ...),
    )
```

**Benefits**:
- Event loop remains responsive during parsing
- Parallel parsing of concurrent requests
- Maintains low latency at 200+ req/s

#### 3. Circuit Breaker Protection

**Problem**: Database failures can cascade, causing all requests to fail and overwhelming the system.

**Solution**: Circuit breaker pattern with three states:

- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Failure threshold exceeded (5 consecutive failures), requests blocked
- **HALF_OPEN**: Testing recovery after 30s timeout

```python
async with db_write_breaker:
    inserted = await repo.insert_metrics(run_id, samples)
# Raises CircuitBreakerOpen if circuit is open
```

**Configuration**:
- Failure threshold: 5 consecutive failures
- Recovery timeout: 30 seconds
- Success threshold: 2 successes to close circuit
- Response: 503 Service Unavailable with `Retry-After` header

#### 4. Rate Limiting

**Problem**: At scale (1,000 GPUs), request bursts can overwhelm the backend.

**Solution**: Per-run_id sliding window rate limiter:

```python
remote_write_limiter = RateLimiter(
    requests_per_second=200.0,
    burst=400,  # 2 seconds worth
    window_size=1.0,
)
```

**Algorithm**: Sliding window interpolation between current and previous window for smooth limiting.

**Response**: 429 Too Many Requests with `Retry-After` header when limit exceeded.

#### 5. Redis-Backed LiveMetricsBroker

**Problem**: In-memory broker loses state on restart and doesn't scale horizontally.

**Solution**: Optional Redis pub/sub broker:

- **InMemoryBroker** (default): Single-instance deployments, bounded queues (maxsize=500)
- **RedisBroker** (when `TELEMETRY_REDIS_URL` configured): Multi-instance deployments with cross-instance message distribution

**Features**:
- Survives backend restarts
- Horizontal scaling across multiple backend instances
- Automatic broker selection based on configuration
- **Note**: Requires `redis` Python package (added to `requirements.txt` in January 2025)

### Performance Benchmarks

| Metric | Before Optimizations | After Optimizations |
|--------|---------------------|---------------------|
| Max sustainable req/s | ~150-200 | 400+ |
| p99 latency at 200 req/s | 1000ms+ | <300ms |
| Database failure cascade | Yes | Circuit breaker prevents |
| Cross-instance WebSocket | No | Yes (with Redis) |
| Memory under load | Unbounded queue growth | Bounded with backpressure |

### Scalability Targets

- **1,000 GPUs**: 200 req/s (5s scrape interval) ✅ Supported
- **2,000 GPUs**: 400 req/s (5s scrape interval) ✅ Supported with headroom
- **5,000 GPUs**: 1,000 req/s (5s scrape interval) ⚠️ Requires horizontal scaling (multiple backend instances + Redis)

### Configuration

**Environment Variables**:
```bash
# Required: Database connection
TELEMETRY_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/omniference

# Required: JWT secret key (change in production!)
JWT_SECRET_KEY=your-secret-key-here

# Required: Credential encryption key (change in production!)
TELEMETRY_CREDENTIAL_SECRET_KEY=your-32-char-secret-key

# Optional: Enable Redis for multi-instance deployments
TELEMETRY_REDIS_URL=redis://localhost:6379/0

# Optional: Metrics retention (default: 30 days)
TELEMETRY_METRICS_RETENTION_DAYS=30
```

### Redis Setup (Recommended for Production)

Redis is **optional for single-instance deployments** but **recommended for production** to enable:

1. **Horizontal Scaling**: Multiple backend instances can share WebSocket connections
2. **Connection Persistence**: WebSocket clients survive backend restarts
3. **Cross-Instance Broadcasting**: Live metrics are distributed to all instances

**Quick Start with Docker**:
```bash
# Start Redis container
docker run -d --name omniference-redis \
  -p 6379:6379 \
  redis:7-alpine

# Set environment variable
export TELEMETRY_REDIS_URL=redis://localhost:6379/0
```

**Redis Configuration**:
```bash
# Basic connection
TELEMETRY_REDIS_URL=redis://localhost:6379/0

# With password
TELEMETRY_REDIS_URL=redis://:password@localhost:6379/0

# With SSL (production)
TELEMETRY_REDIS_URL=rediss://:password@redis.example.com:6379/0
```

**Behavior**:
- If `TELEMETRY_REDIS_URL` is set: Uses `RedisBroker` for WebSocket pub/sub
- If `TELEMETRY_REDIS_URL` is not set: Uses `InMemoryBroker` (single-instance only)

**Verification**:
```bash
# Check if Redis is being used (in backend logs)
grep "Connected to Redis" /var/log/omniference/backend.log
```

**Circuit Breaker Tuning** (in `circuit_breaker.py`):
```python
db_write_breaker = CircuitBreaker(
    failure_threshold=5,      # Adjust based on failure patterns
    recovery_timeout=30.0,     # Time before testing recovery
    success_threshold=2,       # Successes needed to close
)
```

**Rate Limiter Tuning** (in `rate_limiter.py`):
```python
remote_write_limiter = RateLimiter(
    requests_per_second=200.0,  # Base rate per run_id
    burst=400,                   # Burst allowance
)
```

---

## Monitoring and Observability

### Component Health Checks

#### Backend Health

- **Endpoint**: `GET /health`
- **Checks**: Database connectivity, Redis connectivity
- **Response**: `{"status": "healthy", "database": "ok", "redis": "ok"}`

#### Remote Stack Health

- **Endpoint**: `GET /api/instances/{instance_id}/component-status`
- **Checks**: Each exporter (DCGM, NVIDIA-SMI, Token) HTTP health endpoints
- **Response**: Status for each component (healthy/error/not_found)

**Component Status Codes**:
- **Green (✓)**: Component is healthy and responding
- **Red (✗)**: Component has errors or is not running
- **White/Gray (○)**: Component not found/not installed

### Deployment Status Tracking

- **States**: `pending`, `queued`, `running`, `completed`, `failed`, `cancelled`
- **Tracking**: Persistent `DeploymentJob` records in database
- **Persistence**: All job state persisted in `deployment_jobs` table
- **Recovery**: Jobs survive backend restarts; worker resumes processing on startup
- **Per-Instance Locking**: Only one deployment job per instance can run at a time
- **Retry Logic**: Failed jobs automatically retry up to `max_attempts` with exponential backoff
- **Job Management**: Users can retry failed jobs or cancel pending jobs via UI

### Error Handling and Logging

#### Logging Levels

- **INFO**: Deployment start/stop, metric ingestion counts
- **WARNING**: Prerequisite failures, component health issues
- **ERROR**: SSH connection failures, deployment errors, metric parsing errors
- **DEBUG**: Detailed metric processing, WebSocket message flow

#### Error Categories

1. **Deployment Errors**:
   - SSH connection failures
   - Prerequisite validation failures
   - Docker Compose errors
   - Health check timeouts

2. **Metric Ingestion Errors**:
   - Invalid remote_write payloads
   - Missing run_id
   - Database insertion failures
   - Policy evaluation exceptions

3. **WebSocket Errors**:
   - Connection drops
   - Queue full (backpressure)
   - JSON serialization errors (NaN/Infinity)

#### Error Recovery

- **Deployment**: Retry logic for transient SSH failures
- **Metrics**: Invalid samples are logged but don't fail ingestion
- **WebSocket**: Automatic reconnection on frontend
- **Database**: Transaction rollback on errors

### Policy Monitoring

The system includes automatic policy monitoring that evaluates metrics against thresholds:

#### Policy Rules (`backend/telemetry/services/policy_monitor.py`)

**Thermal Monitoring**:
- Warning: Temperature > 80°C
- Critical: Temperature > 85°C

**Power Monitoring**:
- Warning: Power draw > 90% of power limit
- Critical: Power draw > 95% of power limit

**ECC Error Monitoring**:
- Warning: Single-bit errors > 10
- Critical: Any double-bit error (DBE is always critical)

**Throttle Detection**:
- Hardware thermal slowdown
- Hardware power brake
- Software power cap

#### Policy Events

- **Storage**: Events stored in `gpu_policy_events` table
- **Query**: `GET /api/runs/{run_id}/policy-events`
- **Frontend**: Can display alerts for policy violations
- **Severity Levels**: `info`, `warning`, `critical`

### Observability Features

1. **Metric Counts**: Log total samples ingested per run
2. **Deployment Timing**: Track deployment duration
3. **WebSocket Connections**: Monitor active WebSocket subscriptions
4. **Database Performance**: Query execution time logging (optional)
5. **Remote Write Volume**: Track remote_write request frequency and size

### Monitoring Recommendations

1. **Backend Metrics**: Export FastAPI metrics to Prometheus (not yet implemented)
2. **Database Monitoring**: Monitor TimescaleDB query performance
3. **WebSocket Monitoring**: Track connection count and message rate
4. **Deployment Success Rate**: Track deployment success/failure rates
5. **Alerting**: Set up alerts for policy violations (critical events)

---

## Conclusion

The Omniference telemetry monitoring system provides a comprehensive solution for remote GPU monitoring with real-time and historical analysis capabilities. The architecture is designed for scalability, reliability, and ease of deployment, with clear separation of concerns between frontend, backend, and remote monitoring components.

Key architectural strengths:
- **Modular Design**: Clear separation between layers and components
- **Async Processing**: Efficient handling of concurrent operations
- **Time-Series Optimization**: TimescaleDB for efficient metric storage
- **Real-Time Streaming**: WebSocket-based live updates
- **Hybrid Deployment**: Both SSH push and Agent pull deployment models
- **Deployment Queue**: Persistent job queue with retry logic and per-instance locking
- **Simplified Agent Provisioning**: API key-based authentication with single-command installation
- **Agent Distribution**: Install script hosted at `https://omniference.com/install` with automatic prerequisite installation
- **Security**: Encrypted credential storage, API key-based agent authentication (SHA256 hashed), secure communication

For questions or contributions, please refer to the main repository documentation.

**Note**: The platform has been rebranded from "Omniference" to "DIO". All user-facing text displays "DIO", while internal URLs and service names may still reference "omniference" for backward compatibility.

---

## Recent Updates

### Performance & Scalability Optimizations (January 2025)

#### High-Throughput Ingestion Improvements
- ✅ **Chunked Batch Insertion**: Metrics inserted in batches of 100 samples per transaction
  - Prevents long-running transactions and lock contention
  - Reduces memory spikes from large INSERT statements
  - Optimized for TimescaleDB hypertable partitioning
- ✅ **Async Protobuf Parsing**: CPU-bound protobuf parsing offloaded to thread pool (4 workers)
  - Prevents GIL from blocking event loop at 200+ req/s
  - Maintains low latency under high load
- ✅ **Circuit Breaker Protection**: Database write circuit breaker prevents cascading failures
  - Opens after 5 consecutive failures
  - 30s recovery timeout with half-open state testing
  - Returns 503 with `Retry-After` header when open
- ✅ **Rate Limiting**: Per-run_id rate limiting (200 req/s with 400 burst)
  - Sliding window algorithm for accurate limiting
  - Prevents overwhelming backend at scale (1,000+ GPUs)
  - Returns 429 with `Retry-After` header when exceeded
- ✅ **Redis-Backed LiveMetricsBroker**: Optional Redis pub/sub for multi-instance deployments
  - InMemoryBroker for single-instance (default)
  - RedisBroker for horizontal scaling (when `TELEMETRY_REDIS_URL` configured)
  - Survives backend restarts and enables cross-instance message distribution

#### Performance Characteristics
- **Before**: ~150-200 req/s sustainable, p99 latency 1000ms+ at 200 req/s
- **After**: 400+ req/s sustainable, p99 latency <300ms at 200 req/s
- **Scalability**: Handles 1,000 GPUs × 5s interval = 200 req/s with headroom

### Backend Improvements (December 2024)
- ✅ Fixed missing `get_session` imports in `instance_orchestration.py` and `instance_orchestrator.py`
- ✅ Nebius cloud provider integration fully implemented
- ✅ Instance orchestration endpoints working correctly
- ✅ Provisioning agent deployment fully functional

### Frontend Improvements (December 2024)
- ✅ Region filtering fixed for Lambda instance launch (regions filtered by instance type capacity)
- ✅ Success/error messages added to instance launch dialog
- ✅ Better error handling and user feedback

### Architecture Updates
- **Cloud Providers**: Now supports 5 providers (Lambda, AWS, GCP, Scaleway, Nebius)
- **Deployment Methods**: Both SSH push and Agent pull methods are fully operational
- **Instance Management**: 4,790-line `ManageInstances.js` component (increased complexity)
- **Agent Distribution**: Install script hosted at `https://omniference.com/install` with automatic prerequisite installation
- **Scalability**: System optimized for 1,000+ GPU deployments with production-grade fault tolerance

