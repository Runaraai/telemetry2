# GPU Profiling Setup Guide for Omniference

## The Problem

DCGM profiling metrics (SM Occupancy, Tensor Core Activity, etc.) require hardware performance counters that must be initialized **before** any CUDA workload starts. This creates a timing challenge.

## The Solution: Install DCGM as a System Service

By installing DCGM as a system service that starts at boot, we reserve the profiling counters **before** any workloads can run.

### ✅ One-Time Setup (Recommended for Production)

**On your GPU instance, run:**

```bash
curl -fsSL https://raw.githubusercontent.com/your-org/Omniference/main/install-dcgm-profiling.sh | sudo bash
```

**Or manually:**

```bash
# Download the script
wget https://raw.githubusercontent.com/your-org/Omniference/main/install-dcgm-profiling.sh

# Make it executable
chmod +x install-dcgm-profiling.sh

# Run it
sudo ./install-dcgm-profiling.sh
```

**What this does:**
1. ✅ Installs DCGM (if not already installed)
2. ✅ Configures it to start at boot with profiling enabled
3. ✅ Enables GPU persistence mode
4. ✅ Starts the service immediately

**Then reboot:**
```bash
sudo reboot
```

**After reboot:**
- ✅ DCGM daemon starts automatically before any workloads
- ✅ Profiling counters are reserved
- ✅ Start your workloads normally
- ✅ Deploy Omniference monitoring anytime - profiling will work!

### Verification

Check that DCGM service is running:

```bash
systemctl status nv-hostengine
```

Should show:
```
● nv-hostengine.service - NVIDIA DCGM Host Engine
   Loaded: loaded (/lib/systemd/system/nv-hostengine.service; enabled)
   Active: active (running)
```

Check GPUs are visible:

```bash
dcgmi discovery -l
```

Should list all your GPUs.

## How Omniference Uses This

When you deploy monitoring from Omniference:

**If DCGM service is running:**
- ✅ DCGM exporter connects to the system daemon
- ✅ Profiling metrics work even with active workloads
- ✅ No timing requirements

**If DCGM service is NOT running:**
- ⚠️ DCGM exporter starts its own instance
- ⚠️ Profiling fails if workloads are running
- ⚠️ Falls back to standard metrics (still useful!)

## Alternatives

### Option 1: Manual Timing (No Installation Required)

For quick tests without installing the service:

1. Ensure no workloads are running
2. Start Omniference monitoring with profiling enabled
3. Wait for "Stack deployed successfully"
4. NOW start your workload

**Pros:** No installation needed
**Cons:** Must carefully time workload start

### Option 2: Standard Metrics Only (Simplest)

For production monitoring without profiling overhead:

1. Deploy monitoring with profiling **disabled**
2. Get GPU util, power, temp, memory, clocks
3. Works anytime, no special setup

**Pros:** Simple, always works
**Cons:** No advanced profiling metrics

### Option 3: MIG Mode (Advanced)

For A100/H100 only:

```bash
sudo nvidia-smi -mig 1
sudo nvidia-smi mig -cgi 9,9,9,9,9,9,9 -C
```

**Pros:** Isolates monitoring from workloads
**Cons:** Reduces per-instance performance, requires reboot

## Comparison Matrix

| Setup | Profiling Works? | Workload Timing | Installation | Best For |
|-------|-----------------|-----------------|--------------|----------|
| **DCGM Service** | ✅ Always | ✅ Anytime | One-time | Production |
| **Manual Timing** | ✅ Yes | ⚠️ Must start after monitoring | None | Quick tests |
| **Standard Metrics** | ❌ No profiling | ✅ Anytime | None | Simple monitoring |
| **MIG Mode** | ✅ Always | ✅ Anytime | Per workload | Multi-tenant |

## Troubleshooting

### DCGM service won't start

```bash
# Check logs
sudo journalctl -u nv-hostengine -n 50

# Common issues:
# - NVIDIA driver not loaded: nvidia-smi should work
# - Permission issues: check /var/run/dcgm/ permissions
# - Port conflict: check if port 5555 is in use
```

### Profiling still not working

```bash
# Verify service is running
systemctl is-active nv-hostengine

# Check if profiling is enabled
sudo grep PROFILING /etc/systemd/system/nv-hostengine.service.d/profiling.conf

# Restart service
sudo systemctl restart nv-hostengine
```

### Want to disable the service

```bash
sudo systemctl stop nv-hostengine
sudo systemctl disable nv-hostengine
```

## Technical Details

### Why This Works

The DCGM service (`nv-hostengine`):
1. Starts at boot via systemd
2. Runs before any user workloads
3. Initializes CUPTI profiling API early
4. Reserves hardware performance counters
5. Keeps them available for the entire boot session

When Omniference deploys monitoring:
- DCGM exporter connects to the running daemon (via port 5555)
- No new profiling initialization needed
- Profiling counters are already set up
- Works regardless of what workloads are running

### DCGM Service vs. Container

**System Service (Recommended for Profiling):**
- ✅ Starts at boot before workloads
- ✅ Profiling always works
- ✅ One-time setup
- ❌ Requires installation

**Container (Current Default):**
- ✅ No installation needed
- ✅ Isolated environment
- ❌ Starts after workloads might be running
- ❌ Profiling fails if workloads are active

## Security Considerations

The DCGM service:
- Runs as root (required for GPU access)
- Listens on localhost:5555 by default
- Only accepts connections from localhost
- No external network exposure

To restrict further:
```bash
# Edit service file
sudo systemctl edit nv-hostengine

# Add:
[Service]
RestrictAddressFamilies=AF_UNIX AF_INET
PrivateTmp=yes
```

## Performance Impact

DCGM daemon overhead:
- CPU: < 0.1% per GPU
- Memory: ~50 MB total
- GPU: Negligible (monitoring only)
- Profiling overhead: < 1% performance impact

## Summary

**For production deployments where you want profiling metrics:**
→ Install DCGM service (one-time, ~5 minutes)

**For quick testing:**
→ Use manual timing (start monitoring before workload)

**For simple monitoring:**
→ Disable profiling (standard metrics are usually enough)

The DCGM service approach is the industry-standard way to enable continuous GPU profiling in production environments.







