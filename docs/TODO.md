# Omniference Development Roadmap & TODO

**Last Updated:** January 2025

This document tracks planned improvements, technical debt, and future features for the Omniference GPU telemetry monitoring platform.

---

## Table of Contents

1. [Completed (January 2025)](#completed-january-2025)
2. [Immediate Fixes (High Priority)](#immediate-fixes-high-priority)
3. [Medium-Term Improvements](#medium-term-improvements)
4. [Long-Term / Future Features](#long-term--future-features)
5. [Technical Debt](#technical-debt)
6. [Security Hardening](#security-hardening)
7. [Performance Optimization](#performance-optimization)
8. [Infrastructure](#infrastructure)

---

## Completed (January 2025)

### Performance & Scalability
- [x] **Composite index for runs**: Added `idx_runs_instance_status` index for common query pattern
- [x] **Token auth for remote_write**: Per-run ingest tokens with SHA256 hash storage
- [x] **Rate limiting**: Sliding window limiter (200 req/s per run_id, 400 burst) - prevents overload at scale
- [x] **Circuit breaker**: DB write protection with automatic recovery (5 failures → open, 30s recovery)
- [x] **Async protobuf parsing**: ThreadPoolExecutor (4 workers) to prevent GIL blocking at 200+ req/s
- [x] **Chunked batch insertion**: 100 samples per transaction - avoids long-running transactions
- [x] **Redis-backed broker**: Optional Redis pub/sub for multi-instance deployments and persistence
- [x] **Redis package**: Added `redis` Python package to requirements.txt

### Security
- [x] **WebSocket token authentication**: Token-based auth via `?token=` query parameter + JWT support
- [x] **Token regeneration endpoint**: `POST /api/runs/{run_id}/regenerate-token` - invalidates old token
- [x] **Token creation tracking**: `token_created_at` column for rotation auditing
- [x] **Secure token storage**: SHA256 hash (not plaintext), 256-bit secure random tokens (`secrets.token_urlsafe(32)`)
- [x] **JWT WebSocket auth**: Frontend automatically includes JWT token for authenticated users

### Documentation
- [x] **Redis setup instructions**: Added to ARCHITECTURE.md and ONBOARDING.md
- [x] **Token auth documentation**: Updated remote_write and WebSocket endpoint docs
- [x] **Token security design**: Documented token format, storage, validation flow
- [x] **Deep dive document**: Created TECHNICAL_ARCHITECTURE_DEEP_DIVE.md
- [x] **Performance optimizations**: Documented GIL fix, rate limiting, circuit breaker in ARCHITECTURE.md

---

## Immediate Fixes (High Priority)

### Database Optimization
- [x] **Add missing indexes**:
  ```sql
  -- For instance orchestration queries
  CREATE INDEX idx_orchestration_instance_status
  ON instance_orchestrations(instance_id, status);
  
  -- For deployment job queries
  CREATE INDEX idx_deployment_jobs_run_status 
  ON deployment_jobs(run_id, status);
  ```

### Security
- [ ] **Add endpoint for token regeneration**:
  - Expose `POST /api/runs/{run_id}/regenerate-token`
  - Return new token, invalidate old one
  - Add audit logging for token regeneration

### Error Handling
- [ ] **Improve error responses**:
  - Add structured error codes
  - Include request IDs for tracing
  - Standardize error response format

---

## Medium-Term Improvements

### Infrastructure (Ingestion Layer)
- [ ] **Add Vector/Telegraf layer** (Priority: High for 5,000+ GPUs):
  ```
  Prometheus → Vector (Rust) → FastAPI/TimescaleDB
  ```
  - Deploy Vector as ingestion proxy
  - Configure Prometheus → Vector → FastAPI/TimescaleDB
  - Decouples ingestion from API layer
  - Handles 10k+ req/s without GIL bottleneck
  
  **Implementation Steps**:
  1. Create Vector configuration for Prometheus remote_write
  2. Add Vector container to docker-compose
  3. Configure Vector to forward to FastAPI or directly to TimescaleDB
  4. Document deployment options

### Security Improvements
- [ ] **Automatic token rotation**:
  - Implement scheduled token rotation (e.g., every 30 days)
  - Warn users via email/notification when rotation is due
  - Support overlapping validity period during rotation (grace period)

- [ ] **IP allowlisting for remote_write**:
  - Add `allowed_ips` JSON column to runs table
  - Validate client IP against allowlist (if configured)
  - Support CIDR notation
  - Optional: fetch from cloud provider metadata

- [ ] **Argon2 for token hashing** (optional enhancement):
  - Replace SHA256 with Argon2 for memory-hard hashing
  - Slower brute force attacks on database breach
  - Trade-off: slightly higher validation latency

- [ ] **Audit logging**:
  - Log all authentication events (success/failure)
  - Log failed remote_write attempts with client IP
  - Log token regeneration events
  - Consider separate audit log table with retention policy

### WebSocket Improvements
- [x] **WebSocket authentication**: ✅ Token-based via query parameter (completed)

- [ ] **WebSocket rate limiting**:
  - Limit messages per connection per minute
  - Limit concurrent connections per run_id
  - Graceful degradation under load

- [ ] **Connection health monitoring**:
  - Track active WebSocket connections per run
  - Alert on connection drops
  - Add connection metrics to health endpoint

- [ ] **Reconnection with exponential backoff**:
  - Frontend: automatic reconnection on disconnect
  - Configurable max retries and backoff multiplier

### API Improvements
- [ ] **Batch operations**:
  - `POST /api/runs/bulk/stop` - Stop multiple runs
  - `DELETE /api/runs/bulk` - Delete multiple runs
  - Add pagination to all list endpoints

- [ ] **Filtering and search**:
  - Add full-text search for run notes/tags
  - Add date range filtering to all list endpoints
  - Add status filtering

---

## Long-Term / Future Features

### Multi-Tenancy
- [ ] **Organization support**:
  - Add organizations table
  - Support multiple users per organization
  - Role-based access control (admin, viewer, operator)
  - Organization-level quotas

### Advanced Monitoring
- [ ] **Alerting system**:
  - Define alert rules (threshold, anomaly detection)
  - Multiple notification channels (email, Slack, webhook)
  - Alert history and acknowledgment
  - Integration with PagerDuty/OpsGenie

- [ ] **Dashboard templates**:
  - Pre-built dashboards for common workloads
  - Custom dashboard builder
  - Dashboard sharing and export

### Machine Learning
- [ ] **Anomaly detection**:
  - Baseline workload patterns
  - Detect unusual GPU behavior
  - Predict potential failures

- [ ] **Cost optimization recommendations**:
  - Analyze utilization patterns
  - Suggest right-sizing
  - Predict workload completion time

### Data Management
- [ ] **Data export**:
  - Export metrics to CSV/Parquet
  - Integration with data lakes (S3, GCS)
  - Scheduled exports

- [ ] **Retention policies**:
  - Configurable per-run retention
  - Tiered storage (hot/warm/cold)
  - Automatic archival

---

## Technical Debt

### Code Quality
- [ ] **Increase test coverage**:
  - Add integration tests for remote_write flow
  - Add load tests for rate limiter/circuit breaker
  - Add WebSocket connection tests
  - Target: 80%+ coverage

- [ ] **Type annotations**:
  - Add missing type hints in services/
  - Validate with mypy strict mode
  - Add type stubs for external libraries

### Refactoring
- [ ] **Split large files**:
  - `main.py` (8800+ lines) → modular routers
  - `repository.py` → separate repositories per domain

- [ ] **Configuration cleanup**:
  - Centralize all config in settings.py
  - Use Pydantic Settings for validation
  - Support .env.local overrides

### Documentation
- [ ] **API documentation**:
  - Add request/response examples to OpenAPI
  - Document error codes
  - Add rate limiting headers documentation

- [ ] **Developer guide**:
  - Contributing guidelines
  - Code style guide
  - Release process

---

## Security Hardening

### Authentication
- [ ] **Multi-factor authentication (MFA)**:
  - TOTP support
  - Recovery codes
  - Remember device

- [ ] **API key authentication**:
  - Alternative to JWT for server-to-server
  - Scoped permissions
  - Usage tracking

### Authorization
- [ ] **Fine-grained permissions**:
  - Per-run access control
  - Read-only access for metrics
  - Separate provisioning permissions

### Infrastructure Security
- [ ] **Secret management**:
  - Integrate with HashiCorp Vault
  - Automatic secret rotation
  - Audit access to secrets

- [ ] **Network security**:
  - mTLS between services
  - Private networking for database
  - WAF for external endpoints

---

## Performance Optimization

### Database
- [ ] **Query optimization**:
  - Analyze slow query logs
  - Add missing covering indexes
  - Optimize aggregate queries

- [ ] **Connection pooling**:
  - Tune pool size based on workload
  - Add connection pool metrics
  - Consider PgBouncer for high connection counts

### Caching
- [ ] **Add caching layer**:
  - Cache run summaries
  - Cache user sessions
  - Cache credential lookups

### Memory
- [ ] **Memory profiling**:
  - Identify memory leaks
  - Optimize large payload handling
  - Stream large responses

---

## Infrastructure

### Deployment
- [ ] **Kubernetes manifests**:
  - Create Helm charts
  - Add horizontal pod autoscaling
  - Configure resource limits

- [ ] **CI/CD improvements**:
  - Add staging environment
  - Automated database migrations
  - Blue-green deployments

### Monitoring
- [ ] **Self-monitoring**:
  - Export application metrics (Prometheus format)
  - Grafana dashboards for backend health
  - Alerting on backend issues

- [ ] **Distributed tracing**:
  - Add OpenTelemetry integration
  - Trace requests across services
  - Visualize in Jaeger/Zipkin

### Reliability
- [ ] **Database backups**:
  - Automated daily backups
  - Point-in-time recovery
  - Cross-region replication

- [ ] **Disaster recovery**:
  - Document recovery procedures
  - Regular recovery testing
  - Multi-region deployment option

---

## Priority Matrix

| Priority | Timeline | Items |
|----------|----------|-------|
| P0 (Critical) | ✅ Done | Token regeneration endpoint, WebSocket auth, Missing indexes |
| P1 (High) | 1 month | Vector ingestion layer, Automatic token rotation, IP allowlisting |
| P2 (Medium) | 1-3 months | Audit logging, Test coverage, WebSocket rate limiting |
| P3 (Low) | 3-6 months | Multi-tenancy, Alerting, Kubernetes |
| P4 (Future) | 6+ months | ML features, Data export, Multi-region |

---

## Notes

- This document should be reviewed and updated monthly
- Items should be moved to issue tracker when work begins
- Completed items should be dated and documented

---

*For architecture details, see [ARCHITECTURE.md](./ARCHITECTURE.md)*
*For setup instructions, see [ONBOARDING.md](./ONBOARDING.md)*
*For technical deep dive, see [TECHNICAL_ARCHITECTURE_DEEP_DIVE.md](./TECHNICAL_ARCHITECTURE_DEEP_DIVE.md)*

