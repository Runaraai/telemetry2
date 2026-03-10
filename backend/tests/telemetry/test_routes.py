from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from telemetry.routes import metrics, runs


class DummyTelemetryRepository:
    def __init__(self) -> None:
        self.created_payload = None
        self.updated_payload = None
        self.metrics_payload = None
        self._run = None

    async def create_run(self, payload):
        self.created_payload = payload
        self._run = SimpleNamespace(
            run_id=uuid4(),
            instance_id=payload.instance_id,
            gpu_model=payload.gpu_model,
            gpu_count=payload.gpu_count,
            start_time=payload.start_time,
            end_time=None,
            status=payload.status,
            tags=payload.tags,
            notes=payload.notes,
            created_at=datetime.now(timezone.utc),
            summary=None,
        )
        return self._run

    async def list_runs(self, **_kwargs):
        return [self._run]

    async def get_run(self, run_id: UUID):
        if self._run and self._run.run_id == run_id:
            return self._run
        return None

    async def update_run(self, run_id: UUID, payload):
        self.updated_payload = payload
        if not self._run or self._run.run_id != run_id:
            raise ValueError("Run not found")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(self._run, key, value)
        return self._run

    async def compute_run_summary(self, run_id: UUID):  # pragma: no cover - not exercised
        return None

    async def delete_run(self, run_id: UUID):  # pragma: no cover - not exercised
        if not self._run or self._run.run_id != run_id:
            raise ValueError("Run not found")
        self._run = None

    async def insert_metrics(self, run_id: UUID, metrics):
        self.metrics_payload = (run_id, metrics)
        return len(metrics)

    async def fetch_metrics(self, run_id: UUID, **_kwargs):
        if not self._run or self._run.run_id != run_id:
            return []
        # Return a simple namespace compatible with MetricSample.model_validate
        sample = SimpleNamespace(
            time=datetime.now(timezone.utc),
            gpu_id=0,
            gpu_utilization=80.0,
            memory_used_mb=40000.0,
            memory_total_mb=80000.0,
            memory_utilization=50.0,
            sm_utilization=70.0,
            sm_clock_mhz=1200.0,
            memory_clock_mhz=1600.0,
            power_draw_watts=300.0,
            power_limit_watts=400.0,
            temperature_celsius=70.0,
            pcie_rx_mb_per_sec=5000.0,
            pcie_tx_mb_per_sec=4500.0,
            nvlink_rx_mb_per_sec=None,
            nvlink_tx_mb_per_sec=None,
            ecc_errors=0,
        )
        return [sample]


@pytest.fixture()
def telemetry_app(monkeypatch):
    repo = DummyTelemetryRepository()
    app = FastAPI()
    app.include_router(runs.router, prefix="/api")
    app.include_router(metrics.router, prefix="/api")

    async def override_repo():
        yield repo

    app.dependency_overrides[runs.get_repository] = override_repo
    app.dependency_overrides[metrics.get_repository] = override_repo

    with TestClient(app) as client:
        yield client, repo


def test_create_run_returns_run_detail(telemetry_app):
    client, repo = telemetry_app
    payload = {
        "instance_id": "lambda-xyz",
        "gpu_model": "A100-80GB",
        "gpu_count": 2,
        "tags": {"experiment": "baseline"},
        "notes": "integration test",
    }

    response = client.post("/api/runs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "run_id" in data
    assert data["instance_id"] == payload["instance_id"]
    assert repo.created_payload is not None


def test_metrics_batch_ingestion_publishes(telemetry_app, monkeypatch):
    client, repo = telemetry_app

    # Ensure a run exists
    create_payload = {
        "instance_id": "lambda-xyz",
        "gpu_model": "A100-80GB",
        "gpu_count": 1,
    }
    create_resp = client.post("/api/runs", json=create_payload)
    run_id = create_resp.json()["run_id"]

    publish_mock = AsyncMock()
    monkeypatch.setattr(metrics.live_broker, "publish", publish_mock)

    batch = {
        "run_id": run_id,
        "metrics": [
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "gpu_id": 0,
                "gpu_utilization": 85.5,
            }
        ],
    }

    response = client.post("/api/metrics/batch", json=batch)
    assert response.status_code == 202
    assert response.json()["inserted"] == 1
    assert repo.metrics_payload is not None
    publish_mock.assert_awaited()

