# Omniference Backend API

FastAPI backend for hardware performance modeling and TCO analysis of AI/ML workloads.

## Features

- **Workload Analysis**: Analyze performance of AI workloads on different hardware configurations
- **Bottleneck Detection**: Identify performance bottlenecks and optimization opportunities
- **Cost Analysis**: Calculate TCO including compute, energy, and infrastructure costs
- **Optimization Suggestions**: Get prioritized recommendations for performance improvements
- **Example Data**: Access to pre-configured workloads and hardware configurations

## Installation

```bash
cd backend
pip install -r requirements.txt
```

## OpenTofu Setup for AWS Instance Management

To enable AWS instance management via OpenTofu, see [SETUP_OPENTOFU.md](./SETUP_OPENTOFU.md) for detailed installation and configuration instructions.

Quick setup:
- Install OpenTofu (or Terraform as fallback)
- Configure AWS CLI or set AWS credentials
- Set environment variables for credentials

## Running the API

```bash
# Development server
python main.py

# Or with uvicorn directly
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## GPU Telemetry Backend

Phase 1 introduces a GPU telemetry stack for run tracking, high-frequency metric ingestion, and real-time dashboards.

### Prerequisites

- TimescaleDB/PostgreSQL 15+ with the TimescaleDB extension. Quick start:

  ```bash
  docker run -d --name timescaledb \
    -p 5432:5432 \
    -e POSTGRES_PASSWORD=password \
    timescale/timescaledb:latest-pg15
  ```

- Optional (for multi-instance deployments): Redis for WebSocket fan-out.

Set the following environment variables before starting the backend:

```
export TELEMETRY_DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/omniference"
export TELEMETRY_REDIS_URL="redis://localhost:6379"  # optional
```

The FastAPI app automatically bootstraps the telemetry schema (Timescale hypertables, retention policies) on startup.

### Core Endpoints

- `POST /api/runs` – create a monitoring run (returns `run_id`).
- `GET /api/runs?instance_id=…` – list recent runs with summaries.
- `POST /api/metrics/batch` – ingest GPU metrics in batches.
- `GET /api/runs/{run_id}/metrics` – fetch historical samples for charts.
- `WS /ws/runs/{run_id}/live` – stream live metrics for dashboards.
- `POST /api/instances/{instance_id}/deploy` – SSH deploy of the monitoring stack.
- `POST /api/instances/{instance_id}/teardown` – stop monitoring and optionally remove volumes.

Example metric ingestion request:

```bash
curl -X POST http://localhost:8000/api/metrics/batch \
  -H "Content-Type: application/json" \
  -d '{
        "run_id": "<uuid>",
        "metrics": [
          {
            "time": "2025-11-07T10:30:05Z",
            "gpu_id": 0,
            "gpu_utilization": 85.5,
            "memory_used_mb": 45000
          }
        ]
      }'
```

### Tests

Telemetry-specific tests live in `backend/tests/telemetry/`:

```bash
pytest backend/tests/telemetry/test_routes.py
```

## API Documentation

Once running, visit:
- **Interactive API docs**: `http://localhost:8000/docs`
- **ReDoc documentation**: `http://localhost:8000/redoc`

## Key Endpoints

### Analysis
- `POST /analyze` - Analyze workload with JSON payload
- `POST /analyze/upload` - Analyze workload with file uploads

### Examples
- `GET /examples/workloads` - List available example workloads
- `GET /examples/hardware` - List available hardware configurations
- `GET /examples/workloads/{name}` - Get specific workload
- `GET /examples/hardware/{name}` - Get specific hardware config

### Health
- `GET /health` - Health check endpoint

## Example Usage

### Using JSON payload:
```python
import requests

response = requests.post("http://localhost:8000/analyze", json={
    "workload": {...},
    "hardware": {...},
    "pricing": {...},
    "slos": {...}
})
```

### Using file uploads:
```python
import requests

files = {
    'workload_file': open('workload.json', 'rb'),
    'hardware_file': open('hardware.yaml', 'rb'),
    'pricing_file': open('pricing.json', 'rb'),
    'slos_file': open('slos.json', 'rb')
}

response = requests.post("http://localhost:8000/analyze/upload", files=files)
```

## Response Format

```json
{
  "perf": {
    "makespan_s": 0.0056,
    "tokens_per_sec": 365244.7,
    "tokens_per_hour": 1314880867.5
  },
  "energy": {
    "it_power_w": 5850,
    "pue": 1.25,
    "joules_per_token": 0.00011
  },
  "cost": {
    "hourly_cost_usd": 109.09,
    "cost_per_token_usd": 8.3e-8
  },
  "bottlenecks": {
    "hbm_bound": false,
    "collective_share": 0.536,
    "compute_bound": true,
    "memory_time_s": 0.002,
    "compute_time_s": 0.0026,
    "collective_time_s": 0.003
  },
  "suggestions": [
    {
      "change": "increase_batch_size",
      "impact": {"throughput": 3.0, "cost_per_token": -0.7},
      "reason": "Batch size of 1 severely underutilizes 8x GPU setup",
      "priority": "high"
    }
  ]
}
```

## Development

The backend is completely self-contained with all necessary modules:
- `hardware_builder/` - Hardware modeling
- `tco_mapper/` - Performance and cost analysis
- `workload_analyzer/` - Workload processing
- `engine/` - Core analysis logic
- `examples/` - Sample workloads and hardware configurations

## Deployment Options

### Local Development
```bash
cd backend
pip install -r requirements.txt
python start.py
```

## Project Structure
```
backend/
├── main.py              # FastAPI application
├── start.py             # Startup script
├── requirements.txt     # Python dependencies
├── test_api.py         # API test script
├── hardware_builder/   # Hardware modeling (copied)
├── tco_mapper/         # Performance analysis (copied)
├── engine/             # Core logic (copied)
├── workload_analyzer/  # Workload processing (copied)
└── examples/           # Sample data (copied)
```
