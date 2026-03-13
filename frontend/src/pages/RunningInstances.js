import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Button, Chip, CircularProgress,
  Alert, IconButton, Tooltip, Stack, Dialog, DialogTitle, DialogContent,
  DialogActions, Slider, Divider
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  Pause as PauseIcon,
  Stop as StopIcon,
  Delete as DeleteIcon,
  Assessment as ProfileIcon,
  Dns as DnsIcon,
  RocketLaunch as RocketLaunchIcon,
  Tune as TuneIcon,
} from '@mui/icons-material';
import { apiService, friendlyError } from '../services/api';

const SCW_BASE = 'https://api.scaleway.com/instance/v1/zones';

const STATUS_COLORS = {
  running: 'success',
  active: 'success',
  starting: 'info',
  pending: 'info',
  stopped: 'error',
  stopped_in_place: 'error',
  stopping: 'warning',
  locked: 'warning',
  terminated: 'default',
  deleting: 'warning',
};

function parseScalewayCredential(secret) {
  if (!secret) return null;
  try {
    const data = typeof secret === 'string' ? JSON.parse(secret) : secret;
    const secretKey = data?.secretKey || data?.secret_key || '';
    const projectId = data?.projectId || data?.project_id || '';
    if (!secretKey) return null;
    return { secretKey, projectId };
  } catch {
    return null;
  }
}

function getLocalScalewayCredential() {
  const envSecret = process.env.REACT_APP_SCW_SECRET_KEY || '';
  const envProject = process.env.REACT_APP_SCW_PROJECT_ID || '';
  if (envSecret) return { secretKey: envSecret, projectId: envProject };

  try {
    const legacy = JSON.parse(localStorage.getItem('cloudCreds_scaleway') || '{}');
    const secretKey = legacy.secretKey || legacy.SCALEWAY_SECRET_KEY || '';
    const projectId = legacy.projectId || legacy.SCALEWAY_PROJECT_ID || '';
    if (secretKey) return { secretKey, projectId };
  } catch {}
  return null;
}

function getTrackedInstances() {
  try {
    return JSON.parse(localStorage.getItem('runara_launched_instances') || '[]');
  } catch {
    return [];
  }
}

function removeTrackedInstance(id) {
  try {
    const tracked = getTrackedInstances().filter((t) => t.id !== id);
    localStorage.setItem('runara_launched_instances', JSON.stringify(tracked));
  } catch {}
}

async function fetchScwServerDetails(zone, serverId, secretKey) {
  const res = await fetch(`${SCW_BASE}/${zone}/servers/${serverId}`, {
    headers: { 'X-Auth-Token': secretKey },
  });
  if (!res.ok) {
    if (res.status === 404) return null;
    throw new Error(`${zone}/${serverId}: ${res.status}`);
  }
  const data = await res.json();
  return { ...data.server, zone };
}

// Normalize a Scaleway server object (from direct API) into the unified shape
function normalizeScwServer(server) {
  return {
    id: server.id,
    name: server.name,
    provider: 'scaleway',
    instance_type: server.commercial_type || '',
    status: server.state || 'unknown',
    public_ip: server.public_ip?.address || '',
    region: server.zone || '',
    zone: server.zone || '',
    raw: server,
  };
}

export default function RunningInstances() {
  const navigate = useNavigate();
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [actionLoading, setActionLoading] = useState({});
  const [actionError, setActionError] = useState({});
  const [scwCredential, setScwCredential] = useState(() => getLocalScalewayCredential());

  // Tune Instance dialog
  const [tuneOpen, setTuneOpen] = useState(false);
  const [tuneInstance, setTuneInstance] = useState(null);
  const [tuneSshKey, setTuneSshKey] = useState('');
  const [tuneLoading, setTuneLoading] = useState(false);
  const [tuneError, setTuneError] = useState('');
  const [tuneSupportedClocks, setTuneSupportedClocks] = useState([]);
  const [tuneCurrentClock, setTuneCurrentClock] = useState(null);
  const [tuneClockIndex, setTuneClockIndex] = useState(0); // index into supported clocks (0 = max freq)
  const [tunePowerCurrent, setTunePowerCurrent] = useState(null);
  const [tunePowerMax, setTunePowerMax] = useState(null);
  const [tunePowerMin, setTunePowerMin] = useState(null);
  const [tunePowerSlider, setTunePowerSlider] = useState(0);
  const [tuneAction, setTuneAction] = useState(''); // 'clock' | 'reset' | 'power' | ''

  // Load Scaleway credential from backend on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const creds = await apiService.listCredentialsWithSecrets('scaleway');
        const first = Array.isArray(creds) ? creds[0] : null;
        const parsed = parseScalewayCredential(first?.secret);
        if (!cancelled && parsed?.secretKey) setScwCredential(parsed);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    let aggregated = [];
    let usedAggregated = false;

    // Try the aggregated API first (multi-provider)
    try {
      const data = await apiService.getAggregatedInstances();
      if (Array.isArray(data) && data.length > 0) {
        aggregated = data;
        usedAggregated = true;
      }
    } catch {
      // Aggregated endpoint failed (401, network, etc.) — fall back below
    }

    // Fallback: fetch Scaleway instances from localStorage tracking + direct API
    if (!usedAggregated && scwCredential?.secretKey) {
      const tracked = getTrackedInstances();
      if (tracked.length > 0) {
        try {
          const results = await Promise.allSettled(
            tracked.map((t) => fetchScwServerDetails(t.zone, t.id, scwCredential.secretKey))
          );
          const deadIds = [];
          results.forEach((r, i) => {
            if (r.status === 'fulfilled' && r.value) {
              aggregated.push(normalizeScwServer(r.value));
            } else if (r.status === 'fulfilled' && r.value === null) {
              deadIds.push(tracked[i].id);
            }
          });
          if (deadIds.length > 0) deadIds.forEach(removeTrackedInstance);
        } catch (e) {
          setError(e.message || 'Failed to fetch instances');
        }
      }
    }

    setInstances(aggregated);
    setLoading(false);
  }, [scwCredential]);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh while any instance is in a transitional state
  useEffect(() => {
    const hasTransitional = instances.some((inst) =>
      ['starting', 'stopping', 'pending', 'deleting'].includes(inst.status)
    );
    if (!hasTransitional) return;
    const id = setTimeout(load, 5000);
    return () => clearTimeout(id);
  }, [instances, load]);

  // --- Action handlers ---

  async function scwAction(inst, action) {
    if (!scwCredential?.secretKey) throw new Error('Scaleway credentials not configured');
    const zone = inst.zone || inst.region;
    const res = await fetch(`${SCW_BASE}/${zone}/servers/${inst.id}/action`, {
      method: 'POST',
      headers: { 'X-Auth-Token': scwCredential.secretKey, 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || `Failed to ${action}: ${res.status}`);
    }
  }

  async function handleTerminate(inst) {
    const name = inst.name || inst.id;
    if (!window.confirm(`Terminate "${name}"? This will permanently delete the instance.`)) return;

    setActionLoading((prev) => ({ ...prev, [inst.id]: 'terminate' }));
    setActionError((prev) => { const n = { ...prev }; delete n[inst.id]; return n; });
    try {
      if (inst.provider === 'scaleway') {
        await scwAction(inst, 'terminate');
        removeTrackedInstance(inst.id);
      } else if (inst.provider === 'lambda') {
        await apiService.terminateLambdaInstance(inst.id);
      } else if (inst.provider === 'nebius') {
        await apiService.deleteNebiusInstance(null, null, inst.id);
      }
      setInstances((prev) => prev.filter((i) => i.id !== inst.id));
    } catch (e) {
      setActionError((prev) => ({ ...prev, [inst.id]: e.message }));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[inst.id]; return n; });
    }
  }

  async function handlePause(inst) {
    setActionLoading((prev) => ({ ...prev, [inst.id]: 'pause' }));
    setActionError((prev) => { const n = { ...prev }; delete n[inst.id]; return n; });
    try {
      if (inst.provider === 'scaleway') {
        await scwAction(inst, 'poweroff');
      } else {
        throw new Error(`Pause not supported for ${inst.provider}`);
      }
      setInstances((prev) =>
        prev.map((i) => (i.id === inst.id ? { ...i, status: 'stopping' } : i))
      );
    } catch (e) {
      setActionError((prev) => ({ ...prev, [inst.id]: e.message }));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[inst.id]; return n; });
    }
  }

  async function handleStop(inst) {
    setActionLoading((prev) => ({ ...prev, [inst.id]: 'stop' }));
    setActionError((prev) => { const n = { ...prev }; delete n[inst.id]; return n; });
    try {
      if (inst.provider === 'scaleway') {
        await scwAction(inst, 'poweroff');
      } else if (inst.provider === 'lambda') {
        await apiService.terminateLambdaInstance(inst.id);
      } else if (inst.provider === 'nebius') {
        await apiService.deleteNebiusInstance(null, null, inst.id);
      }
      setInstances((prev) =>
        prev.map((i) => (i.id === inst.id ? { ...i, status: 'stopping' } : i))
      );
    } catch (e) {
      setActionError((prev) => ({ ...prev, [inst.id]: e.message }));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[inst.id]; return n; });
    }
  }

  function handleProfile(inst) {
    const instanceData = {
      id: inst.id,
      name: inst.name || inst.id,
      ip: inst.public_ip || '',
      zone: inst.zone || inst.region || '',
      commercial_type: inst.instance_type || '',
      provider: inst.provider,
    };
    navigate('/telemetry', { state: { instanceData } });
  }

  function handleRunWorkload(inst) {
    const provider = inst.provider || 'scaleway';
    const defaultUser = provider === 'scaleway' ? 'root' : 'ubuntu';
    navigate('/profiling', {
      state: {
        fromInstance: {
          id: inst.id,
          name: inst.name || inst.id,
          ip: inst.public_ip || '',
          zone: inst.zone || inst.region || '',
          instance_type: inst.instance_type || '',
          provider,
          ssh_user: defaultUser,
        },
      },
    });
  }

  const handleTuneOpen = useCallback(async (inst) => {
    const provider = inst.provider || 'scaleway';
    const sshUser = provider === 'scaleway' ? 'root' : 'ubuntu';
    setTuneInstance({ ...inst, sshUser });
    setTuneOpen(true);
    setTuneError('');
    setTuneSupportedClocks([]);
    setTuneCurrentClock(null);
    setTunePowerCurrent(null);
    setTunePowerMax(null);
    setTunePowerMin(null);
    setTuneLoading(true);
    try {
      const key = await apiService.getSSHPrivateKey();
      if (!key) {
        setTuneError('SSH private key not configured. Set SSH_PRIVATE_KEY in backend .env or add key in credentials.');
        setTuneLoading(false);
        return;
      }
      setTuneSshKey(key);
      const base = {
        ssh_host: inst.public_ip,
        ssh_user: sshUser,
        pem_base64: btoa(key),
      };
      const [clocksRes, powerRes, currentRes] = await Promise.all([
        apiService.tuneFetchSupportedClocks(base),
        apiService.tuneFetchPowerLimits(base),
        apiService.tuneFetchCurrentClock(base),
      ]);
      const clocks = clocksRes?.supported_clocks_mhz || [];
      setTuneSupportedClocks(clocks);
      setTuneCurrentClock(currentRes?.current_graphics_mhz ?? null);
      // Find index of current clock, or default to 0 (max freq)
      const curr = currentRes?.current_graphics_mhz;
      const idx = curr != null && clocks.length > 0
        ? clocks.indexOf(curr)
        : 0;
      setTuneClockIndex(idx >= 0 ? idx : 0);
      setTunePowerCurrent(powerRes?.current_power_limit_w ?? null);
      setTunePowerMax(powerRes?.max_power_limit_w ?? null);
      setTunePowerMin(powerRes?.min_power_limit_w ?? null);
      setTunePowerSlider(powerRes?.current_power_limit_w ?? powerRes?.max_power_limit_w ?? 0);
    } catch (e) {
      setTuneError(friendlyError(e, 'Failed to fetch GPU tune data. Check SSH key and instance connectivity.'));
    } finally {
      setTuneLoading(false);
    }
  }, []);

  const handleTuneClose = useCallback(() => {
    setTuneOpen(false);
    setTuneInstance(null);
    setTuneAction('');
  }, []);

  const handleTuneSetClock = useCallback(async () => {
    if (!tuneInstance || !tuneSshKey || tuneSupportedClocks.length === 0) return;
    const freq = tuneSupportedClocks[tuneClockIndex];
    setTuneAction('clock');
    setTuneError('');
    try {
      await apiService.tuneSetClock({
        ssh_host: tuneInstance.public_ip,
        ssh_user: tuneInstance.sshUser,
        pem_base64: btoa(tuneSshKey),
        frequency_mhz: freq,
      });
      setTuneCurrentClock(freq);
    } catch (e) {
      setTuneError(friendlyError(e, 'Failed to set GPU clock.'));
    } finally {
      setTuneAction('');
    }
  }, [tuneInstance, tuneSshKey, tuneSupportedClocks, tuneClockIndex]);

  const handleTuneResetClock = useCallback(async () => {
    if (!tuneInstance || !tuneSshKey) return;
    setTuneAction('reset');
    setTuneError('');
    try {
      await apiService.tuneResetClock({
        ssh_host: tuneInstance.public_ip,
        ssh_user: tuneInstance.sshUser,
        pem_base64: btoa(tuneSshKey),
      });
      setTuneCurrentClock(null);
      if (tuneSupportedClocks.length > 0) setTuneClockIndex(0);
    } catch (e) {
      setTuneError(friendlyError(e, 'Failed to reset GPU clock.'));
    } finally {
      setTuneAction('');
    }
  }, [tuneInstance, tuneSshKey, tuneSupportedClocks]);

  const handleTuneSetPower = useCallback(async () => {
    if (!tuneInstance || !tuneSshKey || tunePowerMax == null) return;
    setTuneAction('power');
    setTuneError('');
    try {
      await apiService.tuneSetPowerLimit({
        ssh_host: tuneInstance.public_ip,
        ssh_user: tuneInstance.sshUser,
        pem_base64: btoa(tuneSshKey),
        watts: tunePowerSlider,
      });
      setTunePowerCurrent(tunePowerSlider);
    } catch (e) {
      setTuneError(friendlyError(e, 'Failed to set power limit.'));
    } finally {
      setTuneAction('');
    }
  }, [tuneInstance, tuneSshKey, tunePowerMax, tunePowerSlider]);

  const providerLabel = (provider) => {
    const labels = { scaleway: 'Scaleway', lambda: 'Lambda', nebius: 'Nebius' };
    return labels[provider] || provider;
  };

  return (
    <Box sx={{ p: 4, maxWidth: 1400 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Typography variant="h1" sx={{ fontWeight: 800, fontSize: '3rem' }}>
            Running Instances
          </Typography>
        </Stack>
        <Tooltip title="Refresh">
          <IconButton onClick={load} disabled={loading}>
            <RefreshIcon sx={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </IconButton>
        </Tooltip>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {loading && instances.length === 0 && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 6, justifyContent: 'center' }}>
          <CircularProgress size={24} />
          <Typography color="text.secondary">Fetching instances from all providers...</Typography>
        </Box>
      )}

      {!loading && instances.length === 0 && !error && (
        <Box sx={{ textAlign: 'center', py: 8 }}>
          <DnsIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />
          <Typography color="text.secondary">No instances launched yet</Typography>
          <Typography variant="caption" color="text.disabled">
            Launch an instance from Manage Instances to see it here
          </Typography>
        </Box>
      )}

      {instances.length > 0 && (
        <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ backgroundColor: '#2d2d2a' }}>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }}>Instance Name</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }}>Provider</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }}>IP Address</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }}>Status</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }} align="center">Terminate</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }} align="center">Pause</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }} align="center">Stop</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }} align="center">Profile</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }} align="center">Run Workload</TableCell>
                <TableCell sx={{ fontWeight: 600, color: '#fff' }} align="center">Tune</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {instances.map((inst) => {
                const statusColor = STATUS_COLORS[inst.status] || 'default';
                const isTransitional = ['starting', 'stopping', 'pending', 'deleting'].includes(inst.status);
                const isActioning = !!actionLoading[inst.id];
                const canPause = inst.status === 'running' && !isActioning && inst.provider === 'scaleway';
                const canStop = (inst.status === 'running' || inst.status === 'active') && !isActioning;
                const canTerminate = !isActioning && !isTransitional;
                const canProfile = (inst.status === 'running' || inst.status === 'active') && inst.public_ip;

                return (
                  <React.Fragment key={inst.id}>
                    <TableRow
                      sx={{
                        opacity: actionLoading[inst.id] === 'terminate' ? 0.5 : 1,
                        transition: 'opacity 0.3s',
                        '&:hover': { backgroundColor: 'rgba(129, 140, 248, 0.05)' },
                      }}
                    >
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {inst.name || inst.id}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                          {inst.instance_type}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={providerLabel(inst.provider)}
                          size="small"
                          variant="outlined"
                          sx={{ fontSize: '0.75rem' }}
                        />
                      </TableCell>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>
                        {inst.public_ip || '—'}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={isTransitional ? inst.status + '...' : inst.status}
                          color={statusColor}
                          size="small"
                          variant="outlined"
                          icon={isTransitional ? <CircularProgress size={12} /> : undefined}
                        />
                      </TableCell>
                      <TableCell align="center">
                        <Button
                          size="small"
                          variant="outlined"
                          color="error"
                          startIcon={
                            actionLoading[inst.id] === 'terminate'
                              ? <CircularProgress size={14} />
                              : <DeleteIcon fontSize="small" />
                          }
                          onClick={() => handleTerminate(inst)}
                          disabled={!canTerminate}
                          sx={{ textTransform: 'none', fontSize: '0.75rem', minWidth: 100 }}
                        >
                          Terminate
                        </Button>
                      </TableCell>
                      <TableCell align="center">
                        <Button
                          size="small"
                          variant="outlined"
                          color="warning"
                          startIcon={
                            actionLoading[inst.id] === 'pause'
                              ? <CircularProgress size={14} />
                              : <PauseIcon fontSize="small" />
                          }
                          onClick={() => handlePause(inst)}
                          disabled={!canPause}
                          sx={{ textTransform: 'none', fontSize: '0.75rem', minWidth: 80 }}
                        >
                          Pause
                        </Button>
                      </TableCell>
                      <TableCell align="center">
                        <Button
                          size="small"
                          variant="outlined"
                          color="warning"
                          startIcon={
                            actionLoading[inst.id] === 'stop'
                              ? <CircularProgress size={14} />
                              : <StopIcon fontSize="small" />
                          }
                          onClick={() => handleStop(inst)}
                          disabled={!canStop}
                          sx={{ textTransform: 'none', fontSize: '0.75rem', minWidth: 80 }}
                        >
                          Stop
                        </Button>
                      </TableCell>
                      <TableCell align="center">
                        <Button
                          size="small"
                          variant="outlined"
                          color="primary"
                          startIcon={<ProfileIcon fontSize="small" />}
                          onClick={() => handleProfile(inst)}
                          disabled={!canProfile}
                          sx={{ textTransform: 'none', fontSize: '0.75rem', minWidth: 80 }}
                        >
                          Profile
                        </Button>
                      </TableCell>
                      <TableCell align="center">
                        <Button
                          size="small"
                          variant="outlined"
                          color="secondary"
                          startIcon={<RocketLaunchIcon fontSize="small" />}
                          onClick={() => handleRunWorkload(inst)}
                          disabled={!canProfile}
                          sx={{ textTransform: 'none', fontSize: '0.75rem', minWidth: 110 }}
                        >
                          Run Workload
                        </Button>
                      </TableCell>
                      <TableCell align="center">
                        <Button
                          size="small"
                          variant="outlined"
                          color="primary"
                          startIcon={<TuneIcon fontSize="small" />}
                          onClick={() => handleTuneOpen(inst)}
                          disabled={!canProfile}
                          sx={{ textTransform: 'none', fontSize: '0.75rem', minWidth: 70 }}
                        >
                          Tune
                        </Button>
                      </TableCell>
                    </TableRow>
                    {actionError[inst.id] && (
                      <TableRow>
                        <TableCell colSpan={10}>
                          <Alert severity="error" sx={{ py: 0 }}>
                            {actionError[inst.id]}
                          </Alert>
                        </TableCell>

                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Tune Instance Dialog */}
      <Dialog open={tuneOpen} onClose={handleTuneClose} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 600 }}>
          Tune GPU — {tuneInstance?.name || tuneInstance?.id || 'Instance'}
        </DialogTitle>
        <DialogContent dividers>
          {tuneLoading && (
            <Box sx={{ py: 4, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 2 }}>
              <CircularProgress size={24} />
              <Typography color="text.secondary">Fetching GPU data...</Typography>
            </Box>
          )}
          {tuneError && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setTuneError('')}>
              {tuneError}
            </Alert>
          )}
          {!tuneLoading && tuneInstance && (
            <Stack spacing={3}>
              <Box>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  GPU Clock (Graphics)
                </Typography>
                {tuneSupportedClocks.length > 0 ? (
                  <>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      Current: {tuneCurrentClock != null ? `${tuneCurrentClock} MHz` : '—'} / Max: {tuneSupportedClocks[0]} MHz
                    </Typography>
                    <Slider
                      value={tuneClockIndex}
                      onChange={(_, v) => setTuneClockIndex(v)}
                      min={0}
                      max={Math.max(0, tuneSupportedClocks.length - 1)}
                      step={1}
                      valueLabelDisplay="auto"
                      valueLabelFormat={(v) => `${tuneSupportedClocks[v] ?? 0} MHz`}
                      disabled={!!tuneAction}
                    />
                    <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                      <Button
                        size="small"
                        variant="contained"
                        onClick={handleTuneSetClock}
                        disabled={!!tuneAction}
                      >
                        {tuneAction === 'clock' ? <CircularProgress size={16} /> : 'Apply'}
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={handleTuneResetClock}
                        disabled={!!tuneAction}
                      >
                        {tuneAction === 'reset' ? <CircularProgress size={16} /> : 'Reset to Default'}
                      </Button>
                    </Stack>
                  </>
                ) : (
                  <Typography variant="body2" color="text.secondary">No supported clocks available</Typography>
                )}
              </Box>
              <Divider />
              <Box>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Power Limit
                </Typography>
                {tunePowerMax != null ? (
                  <>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      Current: {tunePowerCurrent != null ? `${tunePowerCurrent} W` : '—'} / Max: {tunePowerMax} W
                      {tunePowerMin != null && ` (min: ${tunePowerMin} W)`}
                    </Typography>
                    <Slider
                      value={tunePowerSlider}
                      onChange={(_, v) => setTunePowerSlider(v)}
                      min={tunePowerMin ?? 0}
                      max={tunePowerMax}
                      step={1}
                      valueLabelDisplay="auto"
                      valueLabelFormat={(v) => `${v} W`}
                      disabled={!!tuneAction}
                    />
                    <Button
                      size="small"
                      variant="contained"
                      onClick={handleTuneSetPower}
                      disabled={!!tuneAction}
                      sx={{ mt: 1 }}
                    >
                      {tuneAction === 'power' ? <CircularProgress size={16} /> : 'Apply Power Limit'}
                    </Button>
                  </>
                ) : (
                  <Typography variant="body2" color="text.secondary">Power limit info not available</Typography>
                )}
              </Box>
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ p: 2, pt: 1 }}>
          <Button onClick={handleTuneClose} sx={{ textTransform: 'none' }}>
            Close
          </Button>
        </DialogActions>
      </Dialog>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </Box>
  );
}
