# Omniference — AWS Hosting Plan

Date: 2026-03-10

## Architecture Overview

```
Users → CloudFront (CDN) → S3 (React SPA)
                        ↘ ALB → EC2 (Backend API)
                                  ↕
                          RDS PostgreSQL (TimescaleDB)
                          ElastiCache Redis (optional)

GPU Instances (any cloud) → remote_write → ALB → Backend
```

The control plane (backend, frontend, database) runs on AWS.
GPU workloads stay on cheaper providers (Scaleway, Nebius, Lambda Labs) and connect back via the agent or SSH deployment model.

---

## Tier 1: Cheapest Viable Production (~$50-55/month)

| Component | AWS Service | Spec | Est. Cost/mo |
|---|---|---|---|
| Frontend | Served from EC2 via Nginx | Static React build | $0 (shared) |
| Backend | EC2 `t3.medium` | 2 vCPU, 4GB RAM | ~$30 (Reserved) |
| Database | RDS PostgreSQL `db.t3.micro` | 1 vCPU, 1GB, 20GB SSD | ~$15 (Reserved) |
| Redis | Skip — use in-memory broker | Already supported in code | $0 |
| Reverse Proxy | Nginx on same EC2 | Reuse existing config | $0 |
| SSL | Let's Encrypt (certbot) | Auto-renewing certs | $0 |
| DNS | Route 53 | Hosted zone | ~$0.50 |
| Storage | EBS gp3 30GB | Backend EC2 root vol | ~$2.40 |
| **Total** | | | **~$50-55** |

Best for: solo/small team, <10 concurrent users, early production.

## Tier 2: Standard Production (~$100-120/month)

| Upgrade over Tier 1 | Why | Added Cost |
|---|---|---|
| RDS `db.t3.small` (2GB RAM) | More headroom for TimescaleDB queries | +$15 |
| ElastiCache Redis `cache.t3.micro` | Real pub/sub for WebSocket scaling | +$12 |
| S3 + CloudFront for frontend | Offload static traffic from EC2 | +$3 |
| ACM certificate | Managed SSL, auto-renewing | $0 |

Best for: small team production, moderate telemetry ingest volume.

## Tier 3: High Availability (~$180-220/month)

| Upgrade over Tier 2 | Why | Added Cost |
|---|---|---|
| ALB | Health checks, SSL termination, path routing | +$20 |
| EC2 in Auto Scaling Group (min=1, max=2) | Auto-recovery on instance failure | +$0 (same instance) |
| RDS Multi-AZ | Automatic database failover | +$30 |
| CloudWatch enhanced monitoring | Detailed OS-level metrics | +$5 |

Best for: production with uptime requirements, multiple users, continuous telemetry ingest.

---

## Step-by-Step Implementation

### Phase 1: Foundation (Day 1)

#### 1.1 VPC Setup

- Create VPC with CIDR `10.0.0.0/16`
- 2 public subnets: `10.0.1.0/24` (AZ-a), `10.0.2.0/24` (AZ-b)
- 2 private subnets: `10.0.3.0/24` (AZ-a), `10.0.4.0/24` (AZ-b)
- Internet Gateway attached to VPC
- NAT Gateway in one public subnet (only needed if backend is in private subnet)

#### 1.2 Security Groups

```
sg-alb:
  Inbound: 80/443 from 0.0.0.0/0

sg-backend:
  Inbound: 8000 from sg-alb (or 80/443 if no ALB)
  Inbound: 22 from your IP only

sg-db:
  Inbound: 5432 from sg-backend only

sg-redis:
  Inbound: 6379 from sg-backend only
```

### Phase 2: Database (Day 1)

#### 2.1 RDS PostgreSQL

- Engine: PostgreSQL 15 or 16
- Instance: `db.t3.micro` (Tier 1) or `db.t3.small` (Tier 2+)
- Storage: 20GB gp3, auto-scaling up to 100GB
- Subnet group: private subnets
- Enable automated backups (7-day retention, included free)
- Enable TimescaleDB extension via `shared_preload_libraries` parameter group

**Alternative:** If TimescaleDB on RDS is too limiting (some features require self-managed), use a `t3.small` EC2 in a private subnet with self-managed TimescaleDB. More control, similar cost.

#### 2.2 Database Initialization

The app handles schema creation on startup via `init_telemetry()` in `backend/main.py`. No manual migration needed — just ensure the database exists and is reachable.

```sql
CREATE DATABASE omniference;
```

#### 2.3 Secrets Management

Store all secrets in AWS SSM Parameter Store (free) or Secrets Manager ($0.40/secret/month):

| Secret | SSM Path |
|---|---|
| `TELEMETRY_DATABASE_URL` | `/omniference/prod/database-url` |
| `JWT_SECRET_KEY` | `/omniference/prod/jwt-secret` |
| `TELEMETRY_CREDENTIAL_SECRET_KEY` | `/omniference/prod/credential-secret` |
| `OPENROUTER_API_KEY` | `/omniference/prod/openrouter-key` |
| `LAMBDA_API_KEY` | `/omniference/prod/lambda-key` |

Load at boot via a wrapper script or use `aws ssm get-parameter` in the systemd `ExecStartPre`.

### Phase 3: Backend EC2 (Day 2)

#### 3.1 Launch EC2

- AMI: Amazon Linux 2023
- Instance type: `t3.medium` (2 vCPU, 4GB RAM)
- Subnet: public (Tier 1) or private behind ALB (Tier 2+)
- Elastic IP (Tier 1) or ALB target (Tier 2+)
- IAM role with SSM Parameter Store read access
- User data or manual setup (see below)

#### 3.2 Server Setup

```bash
# System packages
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip nginx git

# App user
sudo useradd -r -m -d /opt/omniference omniference

# Clone and install
sudo -u omniference git clone <repo-url> /opt/omniference/app
cd /opt/omniference/app/backend
sudo -u omniference python3.11 -m venv .venv
sudo -u omniference .venv/bin/pip install -r requirements.txt
```

#### 3.3 Systemd Service

```ini
# /etc/systemd/system/omniference-backend.service
[Unit]
Description=Omniference Backend
After=network.target

[Service]
User=omniference
WorkingDirectory=/opt/omniference/app/backend
Environment=PYTHONPATH=.
EnvironmentFile=/opt/omniference/.env
ExecStart=/opt/omniference/app/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable omniference-backend
sudo systemctl start omniference-backend
```

#### 3.4 Nginx Configuration

Adapt the existing `nginx-omniference.conf`:

```nginx
server {
    listen 80;
    server_name omniference.com www.omniference.com;

    # Frontend (static build)
    location / {
        root /opt/omniference/app/frontend/build;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
        proxy_buffering off;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
    }

    # Agent downloads
    location /downloads/ {
        alias /opt/omniference/downloads/;
    }
}
```

Then add SSL with certbot:

```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d omniference.com -d www.omniference.com
```

### Phase 4: Frontend Build & Deploy (Day 2)

#### Option A: Serve from EC2 (Tier 1 — cheapest)

```bash
cd /opt/omniference/app/frontend
npm install
npm run build
# Nginx serves from /opt/omniference/app/frontend/build/
```

#### Option B: S3 + CloudFront (Tier 2+)

```bash
# Build
cd frontend
npm run build

# Create S3 bucket
aws s3 mb s3://omniference-frontend

# Upload
aws s3 sync build/ s3://omniference-frontend/ --delete

# Create CloudFront distribution
# - Default origin: S3 bucket (OAI)
# - Behavior /api/*: Custom origin → ALB/EC2
# - Behavior /ws/*: Custom origin → ALB/EC2 (with WebSocket)
# - Error pages: 403/404 → /index.html (SPA routing)
# - ACM certificate attached
# - Route 53 alias record pointing to CloudFront
```

### Phase 5: Agent Distribution (Day 2)

```bash
# Upload Go binary and install script to S3 or EC2 local path
mkdir -p /opt/omniference/downloads
cp provisioning-agent/omniference-agent /opt/omniference/downloads/
cp provisioning-agent/install-agent.sh /opt/omniference/downloads/

# Update install script URL to point to your AWS domain
# Agents will connect to: https://omniference.com/api/provisioning/heartbeat
```

### Phase 6: DNS & SSL (Day 2)

1. Create Route 53 hosted zone for `omniference.com`
2. Update domain registrar nameservers to Route 53
3. A record → EC2 Elastic IP (Tier 1) or CloudFront/ALB (Tier 2+)
4. Route 53 health check on `/health` endpoint (free, 1 check)

### Phase 7: Monitoring & Reliability (Day 3)

#### CloudWatch Alarms (free tier covers basic)

| Alarm | Threshold | Action |
|---|---|---|
| EC2 CPU | > 80% for 5 min | SNS email notification |
| EC2 StatusCheck | Failed | Auto-recover instance |
| RDS FreeStorageSpace | < 2GB | SNS email notification |
| RDS CPUUtilization | > 80% for 5 min | SNS email notification |
| Route 53 HealthCheck | `/health` fails 3x | SNS email notification |

#### Backup Strategy

| What | How | Retention |
|---|---|---|
| Database | RDS automated snapshots | 7 days (free) |
| EC2 AMI | Weekly via AWS Backup | 4 weeks |
| Frontend build | S3 versioning | 30 days |
| Config/env | SSM Parameter Store | Versioned automatically |

---

## Required Code Changes Before Deployment

### Critical

| Change | Files | Description |
|---|---|---|
| Remove secrets from git | `.env`, `.gitignore` | Add `.env` to `.gitignore`, rotate all exposed credentials |
| Set production env vars | `.env` on EC2 | `API_BASE_URL`, `CORS_ORIGINS`, `TELEMETRY_DATABASE_URL` |

### Recommended

| Change | Files | Description |
|---|---|---|
| Replace hardcoded domains | `backend/telemetry/routes/provisioning.py` | Use `API_BASE_URL` env var instead of hardcoded `omniference.com` |
| Replace hardcoded emails | `backend/telemetry/startup.py`, `backend/telemetry/migrations/bootstrap.py` | Make demo account email configurable |
| Update CORS origins | `.env` | Set to your production domain |
| Fix test signatures | `backend/tests/telemetry/test_routes.py` | Update `create_run()` to match current API |

---

## Environment Variables (.env on EC2)

```env
# Core
API_BASE_URL=https://omniference.com
CORS_ORIGINS=https://omniference.com,https://www.omniference.com

# Database
TELEMETRY_DATABASE_URL=postgresql+asyncpg://omniference:PASSWORD@RDS_ENDPOINT:5432/omniference

# Auth
JWT_SECRET_KEY=<generate-with-openssl-rand-hex-32>
TELEMETRY_CREDENTIAL_SECRET_KEY=<generate-with-openssl-rand-hex-32>

# Redis (Tier 2+ only, omit for in-memory broker)
TELEMETRY_REDIS_URL=redis://ELASTICACHE_ENDPOINT:6379/0

# Optional API keys
OPENROUTER_API_KEY=
LAMBDA_API_KEY=
```

---

## GPU Instances — Separate from AWS

The platform manages GPU instances on other providers. These connect back to the AWS-hosted control plane:

- **Agent model:** GPU host runs `omniference-agent`, polls `POST /api/provisioning/heartbeat`
- **SSH model:** Backend pushes deployment config via SSH to GPU host
- **Metrics flow:** Prometheus on GPU host → `POST /api/telemetry/remote-write` → Backend → TimescaleDB

GPU instances can be on Scaleway, Nebius, Lambda Labs, or any provider with NVIDIA GPUs. The backend URL (`API_BASE_URL`) must be publicly reachable from these instances.

---

## Scaling Path

When you outgrow Tier 1:

1. **Database bottleneck** → Upgrade RDS instance class (vertical) or add read replicas
2. **Backend CPU/memory** → Upgrade EC2 instance type, then add ALB + ASG for horizontal scale
3. **WebSocket connections** → Add Redis (ElastiCache) for pub/sub broker, enables multi-worker
4. **Frontend latency** → Move to S3 + CloudFront
5. **High ingest volume** → Consider RDS → self-managed TimescaleDB on dedicated EC2 for compression features
6. **Multi-region** → CloudFront already global; replicate backend in second region if needed

---

## Cost Optimization Tips

1. **Reserved Instances (1-year, no upfront):** ~35% savings on EC2 and RDS
2. **Savings Plans:** Alternative to RIs, more flexible
3. **Skip Redis:** Your codebase already falls back to in-memory pub/sub (`backend/telemetry/realtime.py`)
4. **gp3 storage:** 20% cheaper than gp2 with better baseline performance
5. **Spot instances:** NOT recommended for the backend (interruptions), but fine for batch/CI workloads
6. **Right-size:** Start with `t3.medium`, monitor CloudWatch, downsize to `t3.small` if CPU stays under 20%
