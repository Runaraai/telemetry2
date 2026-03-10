import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Button, Chip, CircularProgress,
  Alert, IconButton, Tooltip, Stack
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  PlayArrow as PlayIcon,
  Pause as PauseIcon,
  Delete as DeleteIcon,
  Assessment as ProfileIcon,
  Dns as DnsIcon
} from '@mui/icons-material';

const BASE = 'https://api.scaleway.com/instance/v1/zones';
const SECRET_KEY = process.env.REACT_APP_SCW_SECRET_KEY || '';

const STATE_COLORS = {
  running: 'success',
  starting: 'info',
  stopped: 'error',
  stopping: 'warning',
  locked: 'warning',
};

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

async function fetchServerDetails(zone, serverId) {
  const res = await fetch(`${BASE}/${zone}/servers/${serverId}`, {
    headers: { 'X-Auth-Token': SECRET_KEY },
  });
  if (!res.ok) {
    if (res.status === 404) return null; // server was deleted
    throw new Error(`${zone}/${serverId}: ${res.status}`);
  }
  const data = await res.json();
  return { ...data.server, zone };
}

async function serverAction(zone, serverId, action) {
  const res = await fetch(`${BASE}/${zone}/servers/${serverId}/action`, {
    method: 'POST',
    headers: {
      'X-Auth-Token': SECRET_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ action }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || `Failed to ${action}: ${res.status}`);
  }
}

export default function RunningInstances() {
  const navigate = useNavigate();
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [actionLoading, setActionLoading] = useState({});
  const [actionError, setActionError] = useState({});

  const load = useCallback(async () => {
    const tracked = getTrackedInstances();
    if (tracked.length === 0) {
      setServers([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const results = await Promise.allSettled(
        tracked.map((t) => fetchServerDetails(t.zone, t.id))
      );
      const live = [];
      const deadIds = [];
      results.forEach((r, i) => {
        if (r.status === 'fulfilled' && r.value) {
          live.push(r.value);
        } else if (r.status === 'fulfilled' && r.value === null) {
          // Server no longer exists — clean up tracking
          deadIds.push(tracked[i].id);
        }
      });
      // Remove dead instances from localStorage
      if (deadIds.length > 0) {
        deadIds.forEach(removeTrackedInstance);
      }
      setServers(live);
    } catch (e) {
      setError(e.message || 'Failed to fetch instances');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh while any server is in a transitional state
  useEffect(() => {
    const hasTransitional = servers.some(
      (s) => s.state === 'starting' || s.state === 'stopping'
    );
    if (!hasTransitional) return;
    const id = setTimeout(load, 5000);
    return () => clearTimeout(id);
  }, [servers, load]);

  async function handleStart(server) {
    setActionLoading((prev) => ({ ...prev, [server.id]: 'start' }));
    setActionError((prev) => { const n = { ...prev }; delete n[server.id]; return n; });
    try {
      await serverAction(server.zone, server.id, 'poweron');
      setServers((prev) =>
        prev.map((s) => (s.id === server.id ? { ...s, state: 'starting' } : s))
      );
    } catch (e) {
      setActionError((prev) => ({ ...prev, [server.id]: e.message }));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[server.id]; return n; });
    }
  }

  async function handlePause(server) {
    setActionLoading((prev) => ({ ...prev, [server.id]: 'pause' }));
    setActionError((prev) => { const n = { ...prev }; delete n[server.id]; return n; });
    try {
      await serverAction(server.zone, server.id, 'poweroff');
      setServers((prev) =>
        prev.map((s) => (s.id === server.id ? { ...s, state: 'stopping' } : s))
      );
    } catch (e) {
      setActionError((prev) => ({ ...prev, [server.id]: e.message }));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[server.id]; return n; });
    }
  }

  async function handleTerminate(server) {
    if (!window.confirm(`Terminate "${server.name}"? This will permanently delete the server and its local volumes.`)) return;
    setActionLoading((prev) => ({ ...prev, [server.id]: 'terminate' }));
    setActionError((prev) => { const n = { ...prev }; delete n[server.id]; return n; });
    try {
      await serverAction(server.zone, server.id, 'terminate');
      removeTrackedInstance(server.id);
      setServers((prev) => prev.filter((s) => s.id !== server.id));
    } catch (e) {
      setActionError((prev) => ({ ...prev, [server.id]: e.message }));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[server.id]; return n; });
    }
  }

  function handleProfile(server) {
    const instanceData = {
      id: server.id,
      name: server.name,
      ip: server.public_ip?.address || '',
      zone: server.zone,
      commercial_type: server.commercial_type,
      provider: 'scaleway',
    };
    navigate('/profiling', { state: { openTelemetry: true, instanceData, allowMigration: true } });
  }

  if (!SECRET_KEY) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity="warning">
          Scaleway credentials not configured. Set REACT_APP_SCW_SECRET_KEY in your .env file.
        </Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 4, maxWidth: 1400 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <DnsIcon color="primary" />
          <Typography variant="h5" sx={{ fontWeight: 600 }}>
            Running Instances
          </Typography>
          <Chip
            label={`${servers.length} instance${servers.length !== 1 ? 's' : ''}`}
            size="small"
            variant="outlined"
          />
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

      {loading && servers.length === 0 && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 6, justifyContent: 'center' }}>
          <CircularProgress size={24} />
          <Typography color="text.secondary">Fetching instance status...</Typography>
        </Box>
      )}

      {!loading && servers.length === 0 && !error && (
        <Box sx={{ textAlign: 'center', py: 8 }}>
          <DnsIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />
          <Typography color="text.secondary">No instances launched yet</Typography>
          <Typography variant="caption" color="text.disabled">
            Launch an instance from Manage Instances to see it here
          </Typography>
        </Box>
      )}

      {servers.length > 0 && (
        <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ backgroundColor: '#fafafa' }}>
                <TableCell sx={{ fontWeight: 600 }}>Instance Name</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Region</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>IP Address</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Status</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="center">Terminate</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="center">Pause</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="center">Start</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="center">Profile</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {servers.map((server) => {
                const stateColor = STATE_COLORS[server.state] || 'default';
                const isTransitional = server.state === 'starting' || server.state === 'stopping';
                const isActioning = !!actionLoading[server.id];
                const canStart = server.state === 'stopped' && !isActioning;
                const canPause = server.state === 'running' && !isActioning;
                const canTerminate = !isActioning && !isTransitional;
                const canProfile = server.state === 'running' && server.public_ip?.address;

                return (
                  <React.Fragment key={server.id}>
                    <TableRow
                      sx={{
                        opacity: actionLoading[server.id] === 'terminate' ? 0.5 : 1,
                        transition: 'opacity 0.3s',
                        '&:hover': { backgroundColor: '#f5f5f5' },
                      }}
                    >
                      <TableCell>
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 500 }}>{server.name}</Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                            {server.commercial_type}
                          </Typography>
                        </Box>
                      </TableCell>
                      <TableCell>{server.zone}</TableCell>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>
                        {server.public_ip?.address || '—'}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={isTransitional ? server.state + '...' : server.state}
                          color={stateColor}
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
                            actionLoading[server.id] === 'terminate'
                              ? <CircularProgress size={14} />
                              : <DeleteIcon fontSize="small" />
                          }
                          onClick={() => handleTerminate(server)}
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
                            actionLoading[server.id] === 'pause'
                              ? <CircularProgress size={14} />
                              : <PauseIcon fontSize="small" />
                          }
                          onClick={() => handlePause(server)}
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
                          color="success"
                          startIcon={
                            actionLoading[server.id] === 'start'
                              ? <CircularProgress size={14} />
                              : <PlayIcon fontSize="small" />
                          }
                          onClick={() => handleStart(server)}
                          disabled={!canStart}
                          sx={{ textTransform: 'none', fontSize: '0.75rem', minWidth: 80 }}
                        >
                          Start
                        </Button>
                      </TableCell>
                      <TableCell align="center">
                        <Button
                          size="small"
                          variant="outlined"
                          color="primary"
                          startIcon={<ProfileIcon fontSize="small" />}
                          onClick={() => handleProfile(server)}
                          disabled={!canProfile}
                          sx={{ textTransform: 'none', fontSize: '0.75rem', minWidth: 80 }}
                        >
                          Profile
                        </Button>
                      </TableCell>
                    </TableRow>
                    {actionError[server.id] && (
                      <TableRow>
                        <TableCell colSpan={8}>
                          <Alert severity="error" sx={{ py: 0 }}>
                            {actionError[server.id]}
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

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </Box>
  );
}
