import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Card,
  CardContent,
  CircularProgress,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import apiService from '../services/api';

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toFixed(digits);
}

export default function Workload() {
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [profile, setProfile] = useState(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [error, setError] = useState('');

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true);
    setError('');
    try {
      const response = await apiService.listAllTelemetryRuns({ limit: 100 });
      const nextRuns = Array.isArray(response?.runs) ? response.runs : [];
      setRuns(nextRuns);
      if (nextRuns.length > 0) {
        setSelectedRunId((prev) => prev || nextRuns[0].run_id);
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to load telemetry runs.');
    } finally {
      setLoadingRuns(false);
    }
  }, []);

  const loadProfile = useCallback(async (runId) => {
    if (!runId) {
      setProfile(null);
      return;
    }
    setLoadingProfile(true);
    setError('');
    try {
      const data = await apiService.getTelemetryRunProfile(runId);
      setProfile(data);
    } catch (e) {
      if (e?.response?.status === 404) {
        setProfile(null);
      } else {
        setError(e?.response?.data?.detail || e.message || 'Failed to load workload profile.');
      }
    } finally {
      setLoadingProfile(false);
    }
  }, []);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (selectedRunId) {
      loadProfile(selectedRunId);
    }
  }, [selectedRunId, loadProfile]);

  const latestKernel = useMemo(() => {
    if (!Array.isArray(profile?.kernel_profiles) || profile.kernel_profiles.length === 0) return null;
    return profile.kernel_profiles[0];
  }, [profile]);

  const workload = profile?.workload;
  const bottleneck = profile?.bottleneck;

  return (
    <Box sx={{ p: 4 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ xs: 'stretch', md: 'center' }} sx={{ mb: 3 }}>
        <Typography variant="h5" sx={{ fontWeight: 600 }}>
          Workload Profiling
        </Typography>
        <FormControl size="small" sx={{ minWidth: 380, maxWidth: '100%' }}>
          <InputLabel>Run</InputLabel>
          <Select
            label="Run"
            value={selectedRunId}
            onChange={(e) => setSelectedRunId(e.target.value)}
            disabled={loadingRuns || runs.length === 0}
          >
            {runs.map((run) => (
              <MenuItem key={run.run_id} value={run.run_id}>
                {run.instance_id} | {run.gpu_model || 'Unknown GPU'} | {new Date(run.start_time).toLocaleString()}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {(loadingRuns || loadingProfile) && (
        <Box sx={{ py: 6, display: 'flex', justifyContent: 'center' }}>
          <CircularProgress />
        </Box>
      )}

      {!loadingRuns && runs.length === 0 && (
        <Alert severity="info">No telemetry runs found for this account yet.</Alert>
      )}

      {!loadingProfile && runs.length > 0 && !profile && (
        <Alert severity="info">Selected run has no workload/kernel/bottleneck profile yet.</Alert>
      )}

      {profile && (
        <Stack spacing={3}>
          <Grid container spacing={2}>
            <Grid item xs={12} md={3}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="caption" color="text.secondary">TTFT P95</Typography>
                  <Typography variant="h5">{fmt(workload?.ttft_p95_ms)} ms</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="caption" color="text.secondary">TPOT P95</Typography>
                  <Typography variant="h5">{fmt(workload?.tpot_p95_ms)} ms</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="caption" color="text.secondary">Throughput (tokens/s)</Typography>
                  <Typography variant="h5">{fmt(workload?.throughput_tok_sec)}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="caption" color="text.secondary">Primary Bottleneck</Typography>
                  <Typography variant="h5" sx={{ textTransform: 'capitalize' }}>
                    {bottleneck?.primary_bottleneck || '-'}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Card variant="outlined">
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>Kernel Breakdown</Typography>
              {!latestKernel || !Array.isArray(latestKernel.categories) || latestKernel.categories.length === 0 ? (
                <Typography color="text.secondary">No kernel category data available.</Typography>
              ) : (
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Category</TableCell>
                        <TableCell align="right">Total ms</TableCell>
                        <TableCell align="right">Percent</TableCell>
                        <TableCell align="right">Kernel Count</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {latestKernel.categories.map((cat, idx) => (
                        <TableRow key={`${cat.category}-${idx}`}>
                          <TableCell>{cat.category}</TableCell>
                          <TableCell align="right">{fmt(cat.total_ms)}</TableCell>
                          <TableCell align="right">{fmt(cat.pct)}%</TableCell>
                          <TableCell align="right">{cat.kernel_count ?? '-'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>Recommendations</Typography>
              {Array.isArray(bottleneck?.recommendations) && bottleneck.recommendations.length > 0 ? (
                <Stack spacing={0.75}>
                  {bottleneck.recommendations.map((item, idx) => (
                    <Typography key={idx}>- {item}</Typography>
                  ))}
                </Stack>
              ) : (
                <Typography color="text.secondary">No recommendations available.</Typography>
              )}
            </CardContent>
          </Card>
        </Stack>
      )}
    </Box>
  );
}
