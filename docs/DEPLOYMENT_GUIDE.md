# Omniference Deployment Guide

This guide explains how to deploy application changes to the production server at `http://3.19.87.64`.

## EC2 Details

| Resource | Value |
|----------|-------|
| Instance | i-0d3bb2002c040644e (t3.medium, us-east-2a) |
| Elastic IP | 3.19.87.64 |
| SSH | `ssh -i omniference-key.pem ec2-user@3.19.87.64` |
| Security Group | sg-0d61f51991cd715df (omniference-backend-sg) |

## If SSH Suddenly Stops Working

The security group restricts SSH to specific IPs. If your IP changed (new network, VPN, ISP change), SSH will fail.

**Fix via AWS CLI:**
```bash
# Add your current IP to the security group
MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id sg-0d61f51991cd715df --region us-east-2 \
  --protocol tcp --port 22 --cidr "${MY_IP}/32"
```

**Or use the script:**
```bash
./scripts/fix-ssh-and-deploy.sh           # Fix SSH only
./scripts/fix-ssh-and-deploy.sh deploy    # Fix SSH + deploy
```

## Prerequisites

- SSH access to the server (PEM key at `omniference-key.pem`)
- Server user: `ec2-user` (Amazon Linux)

## Server Layout (from AWS Hosting Plan)

The app is typically deployed to:

| Path | Purpose |
|------|---------|
| `/opt/omniference/app` | Application root |
| `/opt/omniference/app/backend` | FastAPI backend |
| `/opt/omniference/app/frontend` | React frontend |
| `/opt/omniference/app/frontend/build` | Built static files (served by Nginx) |

Backend runs as a systemd service (`omniference-backend`). Nginx serves the frontend and proxies `/api/` and `/ws/` to the backend.

## Quick Deploy (using deploy script)

```bash
# From project root
./deploy-to-server.sh 3.19.87.64

# Or with custom PEM key
PEM_FILE=path/to/your-key.pem ./deploy-to-server.sh 3.19.87.64
```

This will:
1. Sync backend and frontend code to the server
2. Rebuild the frontend
3. Restart the backend
4. Run migrations (via app startup)
5. Reload Nginx if needed

## Manual Deploy

### Option A: Git pull on server (if code is in git)

```bash
ssh ubuntu@3.19.87.64

cd /opt/omniference/app
git pull

# Backend: restart to pick up Python changes
sudo systemctl restart omniference-backend

# Frontend: rebuild and serve
cd frontend
npm install   # if package.json changed
npm run build

# Reload Nginx (if serving frontend)
sudo systemctl reload nginx
```

### Option B: Rsync from local machine

```bash
# From project root on your machine
rsync -avz --exclude node_modules --exclude .venv --exclude __pycache__ \
  -e "ssh -i your-key.pem" \
  ./backend/ ubuntu@3.19.87.64:/opt/omniference/app/backend/

rsync -avz --exclude node_modules --exclude build \
  -e "ssh -i your-key.pem" \
  ./frontend/ ubuntu@3.19.87.64:/opt/omniference/app/frontend/

# Then SSH in and rebuild + restart
ssh -i your-key.pem ubuntu@3.19.87.64 << 'EOF'
cd /opt/omniference/app/frontend
npm install
npm run build
sudo systemctl restart omniference-backend
sudo systemctl reload nginx
EOF
```

## Alternative: Docker-Based Deployment

If the server uses Docker (e.g. `docker-compose`):

```bash
# After syncing code
ssh ubuntu@3.19.87.64
cd /opt/omniference/app  # or wherever docker-compose.yml lives
docker compose build backend frontend
docker compose up -d backend frontend
```

The `deploy-to-server.sh` script restarts `omniference-backend` via systemd; if you use Docker, run the commands above manually after syncing.

## What Gets Deployed

| Change location | Deploy step |
|-----------------|-------------|
| `backend/**` (Python) | Restart backend: `sudo systemctl restart omniference-backend` |
| `frontend/**` (React) | `npm run build` then reload Nginx |
| `backend/scripts/scripts/**` (agent, upload, telemetry) | These are used by the agent on GPU instances; also sync to backend so run-profiling can upload them |
| Database migrations | Run automatically on backend startup via `init_telemetry()` bootstrap |

## Agent / Telemetry Scripts

The profiling telemetry changes (agent.py, upload.py, telemetry/*, run.sh) are used in two places:

1. **On the Omniference server** — when "Run Profiling" or "Run Kernel Analysis" is triggered, the backend copies these scripts to the GPU instance via SSH and runs them.
2. **On GPU instances** — when the provisioning agent or manual run executes agent.py.

To have the updated scripts used for run-profiling:
- Deploy the backend changes (sync `backend/scripts/scripts/` to the server)
- Restart the backend

## Environment Variables

Ensure the server has correct `.env` at `/opt/omniference/.env` or wherever the backend reads it. Key variables:
- `TELEMETRY_DATABASE_URL`
- `API_BASE_URL` (e.g. `http://3.19.87.64` or `https://omniference.com`)
- `CORS_ORIGINS`

## Troubleshooting

### Backend not restarting
```bash
sudo journalctl -u omniference-backend -f
```

### Frontend not updating
- Clear browser cache or hard refresh (Ctrl+Shift+R)
- Verify `frontend/build` was updated: `ls -la /opt/omniference/app/frontend/build`

### Database migration issues
Bootstrap runs on app startup. Check backend logs for migration errors. The new `gpu_summary` column is added by `_migrate_runs_gpu_summary` in bootstrap.
