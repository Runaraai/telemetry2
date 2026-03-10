# Quick Deploy Guide

## Answer: No Docker Copy Needed!

**The provisioning agent is NOT in Docker.** It's served by nginx on your host server.

### What Happens When You Rebuild Docker?

✅ **Docker rebuild affects:**
- Backend API container
- Frontend container  
- Database container

❌ **Docker rebuild does NOT affect:**
- Provisioning agent binary (served by nginx, not Docker)

### How to Deploy Updated Agent

```bash
# 1. Build the new binary
cd /home/madhur/Omniference/provisioning-agent
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o omniference-agent-linux-amd64 .

# 2. Upload to server (not Docker!)
cd ..
./upload-provisioning-agent.sh YOUR_SERVER_IP

# 3. Done! No Docker rebuild needed.
```

The binary goes to `/var/www/omniference/downloads/` on your server, which nginx serves at `https://omniference.com/downloads/`.

### File Flow

```
Local Machine                    Server (Host)                    GPU Instances
─────────────────               ──────────────                   ──────────────
1. Build binary  ────────────>  2. Upload to      ────────────>  3. Download via
   (Go build)                     /var/www/...                      curl install
                                    (nginx serves)                     script
```

**No Docker involved!** The agent runs directly on GPU instances, not in containers.
