# Local (Non-Docker) Runbook

Date: 2026-03-10
Target: Run Omniference backend + frontend directly on host machine (no Docker)

## 0) What must be true

- Python 3.10+ (tested with 3.13)
- Node.js + npm (project tested on modern versions)
- PostgreSQL running locally (required for backend startup)
- Enough free disk space for frontend dependencies (recommend >= 6 GB)

Important: backend startup currently requires DB connectivity because telemetry bootstrap runs during startup.

## 1) Backend setup (Windows PowerShell)

From repo root:

```powershell
py -3.13 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install --upgrade pip
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-local.txt
```

Note: `aiohttp` is required by code and now included in requirements files.

## 2) Install PostgreSQL locally (non-Docker)

### Option A: Windows (winget)

```powershell
winget install -e --id PostgreSQL.PostgreSQL.16
```

After install, ensure service is running and create DB/user:

```sql
CREATE DATABASE omniference;
CREATE USER omniference_user WITH ENCRYPTED PASSWORD 'omniference_pass';
GRANT ALL PRIVILEGES ON DATABASE omniference TO omniference_user;
```

If you are using the default `postgres` user/password, you can skip creating a new user and use that in env config.

### Option B: Linux/macOS

Install native PostgreSQL packages (`apt`, `dnf`, `brew`, etc.), then run the same SQL.

## 3) Backend environment variables

Create/adjust env (root `.env` or shell env vars). Minimum for local:

```env
TELEMETRY_DATABASE_URL=postgresql+asyncpg://omniference_user:omniference_pass@localhost:5432/omniference
TELEMETRY_CREDENTIAL_SECRET_KEY=replace-with-long-random-string
JWT_SECRET_KEY=replace-with-long-random-string
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
API_BASE_URL=http://localhost:8000
```

Optional:

```env
TELEMETRY_REDIS_URL=
OPENROUTER_API_KEY=
LAMBDA_API_KEY=
```

## 4) Start backend

```powershell
Set-Location backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Expected healthy startup logs:

- "Initializing telemetry schema ..."
- "Application startup complete"

If DB is not reachable, startup fails with connection refused.

## 5) Frontend setup

From repo root:

```powershell
Set-Location frontend
npm install
npm start
```

Frontend default API behavior:

- Uses relative API URLs unless `REACT_APP_API_URL` is set.
- For local direct backend, default works with backend on `http://localhost:8000`.

## 6) Login and first use

The backend startup creates a demo account if missing:

- Email: `demo@allyin.ai`
- Password: `demo`

Then open `http://localhost:3000` and sign in.

## 7) Telemetry-specific note for remote GPU hosts

When deploying telemetry to remote hosts, `backend_url` must be routable from that host.

- `localhost` is rejected by validation in deployment schema.
- If backend runs only on your laptop, use a public tunnel/domain (for example, reverse proxy or secure tunnel) and set that URL in UI.

## 8) Troubleshooting

### Backend fails at startup with DB connection refused

- Confirm PostgreSQL service is running.
- Confirm DB/user/password in `TELEMETRY_DATABASE_URL`.
- Confirm port 5432 is open locally.

### Frontend `npm install` fails with `ENOSPC`

- Free disk space first (recommended >= 6 GB free).
- Clear npm cache:

```powershell
npm cache clean --force
```

- Retry install.

### Auth or credential encryption errors

- Ensure `JWT_SECRET_KEY` and `TELEMETRY_CREDENTIAL_SECRET_KEY` are set and not default placeholders.

## 9) Verified blockers seen during validation

- Missing dependency (`aiohttp`) was a real startup blocker and has been fixed in requirements files.
- Backend starts only until DB bootstrap when local Postgres is absent.
- Frontend install fails on very low disk availability.
