# Omniference GPU Telemetry Agent

A production-hardened Go-based agent for deploying GPU telemetry monitoring stacks on remote instances.

## Version 2.0.0 - Security & Reliability Update

This version includes significant security hardening and reliability improvements:

### Security Features
- **No shell injection vulnerabilities**: All exec.Command calls use direct execution without shell
- **Input validation**: Instance IDs validated against strict regex pattern
- **Secrets in environment variables**: API keys read from env vars first (not just config files)
- **Root enforcement**: Agent validates it's running as root via systemd
- **Singleton instance**: File locking prevents multiple agent instances

### Reliability Features
- **Graceful shutdown**: SIGINT/SIGTERM handling with proper cleanup
- **HTTP client with timeouts**: Connection pooling and configurable timeouts
- **Exponential backoff retries**: Automatic retry with backoff for transient failures
- **Atomic file operations**: Backup and rollback support for deployments
- **State persistence**: Agent state saved to disk for recovery
- **Deployment verification**: Health checks after container deployment

### Observability
- **Structured logging**: JSON logging via zap for production environments
- **Context propagation**: Proper context support throughout the codebase

## Distribution

The agent is available via **two distribution methods** with automatic fallback:

1. **Domain Hosting** (Primary): `https://omniference.com/downloads/`
2. **GitHub Releases** (Fallback): `https://github.com/omniference/provisioning-agent/releases`

## Quick Install

```bash
curl -fsSL https://omniference.com/downloads/install-agent.sh | sudo bash
```

Or via GitHub:
```bash
curl -fsSL https://raw.githubusercontent.com/omniference/provisioning-agent/main/install-agent.sh | sudo bash
```

## Configuration

### Option 1: Environment Variables (Recommended for Production)

```bash
# Set in /etc/omniference/agent.env
OMNIFERENCE_API_KEY=your-api-key-here
OMNIFERENCE_INSTANCE_ID=your-instance-id
# OMNIFERENCE_API_URL=https://omniference.com  # Optional
```

### Option 2: Config File (Development)

```bash
# /etc/omniference/config.env
API_KEY=your-api-key-here
INSTANCE_ID=your-instance-id
API_BASE_URL=https://omniference.com
```

## Usage

### Systemd Service (Recommended)

```bash
# Configure credentials
sudo nano /etc/omniference/agent.env

# Start and enable
sudo systemctl start omniference-agent
sudo systemctl enable omniference-agent

# Check status
sudo systemctl status omniference-agent

# View logs (JSON formatted)
sudo journalctl -u omniference-agent -f
```

### Direct Execution

```bash
# Must run as root
export OMNIFERENCE_API_KEY='your-api-key'
export OMNIFERENCE_INSTANCE_ID='your-instance-id'
sudo -E /usr/local/bin/omniference-agent
```

## Building from Source

```bash
# Requires Go 1.21+
cd provisioning-agent
go mod tidy
go build -o omniference-agent .

# For release builds
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o omniference-agent-linux-amd64 .
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    GPU Instance                      │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │            Omniference Agent (v2.0.0)           │ │
│  │                                                 │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │ │
│  │  │ Config   │  │ HTTP     │  │ State        │  │ │
│  │  │ Validator│  │ Client   │  │ Persistence  │  │ │
│  │  └──────────┘  │ (Retry)  │  └──────────────┘  │ │
│  │                └──────────┘                    │ │
│  │                     │                          │ │
│  │                     │ HTTPS (TLS)              │ │
│  │                     ▼                          │ │
│  │  ┌──────────────────────────────────────────┐  │ │
│  │  │         Docker Compose Stack             │  │ │
│  │  │                                          │  │ │
│  │  │  ┌──────────┐  ┌───────────┐  ┌───────┐  │  │ │
│  │  │  │ DCGM     │  │ nvidia-smi│  │Prom   │  │  │ │
│  │  │  │ Exporter │  │ Exporter  │  │       │  │  │ │
│  │  │  └──────────┘  └───────────┘  └───────┘  │  │ │
│  │  └──────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
└──────────────────────────────────────────────────────┘
                         │
                         │ HTTPS Heartbeats & Metrics
                         ▼
              ┌──────────────────────┐
              │  Omniference Backend │
              │                      │
              │  ┌────────────────┐  │
              │  │ /provision/    │  │
              │  │   config       │  │
              │  │   callbacks    │  │
              │  └────────────────┘  │
              └──────────────────────┘
```

## Data Storage

| Path | Purpose |
|------|---------|
| `/etc/omniference/agent.env` | Credentials (env file for systemd) |
| `/etc/omniference/config.env` | Legacy config file |
| `/var/lib/omniference/deployments/{instance_id}/` | Docker Compose deployment |
| `/var/lib/omniference/agent-state.json` | Agent state persistence |
| `/var/lock/omniference-agent.lock` | Singleton lock file |

## Security Best Practices

1. **Never commit API keys** - Use environment variables or secure secret management
2. **Restrict config file permissions** - `chmod 600 /etc/omniference/agent.env`
3. **Use systemd** - Provides isolation and automatic restart
4. **Monitor logs** - `journalctl -u omniference-agent -f`

## Troubleshooting

### Agent won't start

```bash
# Check if another instance is running
ps aux | grep omniference-agent

# Check lock file
ls -la /var/lock/omniference-agent.lock

# Check systemd status
sudo systemctl status omniference-agent
sudo journalctl -u omniference-agent --no-pager -n 50
```

### Deployment fails

```bash
# Check Docker
sudo docker ps
sudo docker compose -f /var/lib/omniference/deployments/*/docker-compose.yml ps

# Check NVIDIA
nvidia-smi

# Check DCGM (if installed)
dcgmi discovery -l
```

### Network issues

```bash
# Test backend connectivity
curl -v https://omniference.com/health

# Check DNS
nslookup omniference.com
```

## Development

### Running Tests

```bash
go test -v ./...
```

### Linting

```bash
go vet ./...
golangci-lint run
```

### Building Release

```bash
# Linux amd64
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o omniference-agent-linux-amd64 .

# Linux arm64
GOOS=linux GOARCH=arm64 go build -ldflags="-s -w" -o omniference-agent-linux-arm64 .
```

## License

Same as Omniference main project.
