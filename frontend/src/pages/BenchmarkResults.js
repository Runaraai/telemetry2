import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  alpha,
  IconButton,
  Tooltip,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  Speed as SpeedIcon,
  Timer as TimerIcon,
  TrendingUp as TrendingUpIcon,
} from '@mui/icons-material';
import apiService from '../services/api';

function MetricCard({ label, value, unit, icon: Icon, color = '#16a34a' }) {
  return (
    <Box
      sx={{
        p: 2,
        borderRadius: 2,
        border: '1px solid #3d3d3a',
        bgcolor: 'rgba(26, 26, 24, 0.6)',
        flex: 1,
        minWidth: 140,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        {Icon && <Icon sx={{ fontSize: 16, color }} />}
        <Typography variant="caption" sx={{ color: '#a8a8a0', fontWeight: 500 }}>
          {label}
        </Typography>
      </Stack>
      <Typography variant="h5" sx={{ fontWeight: 700, color: '#fafaf8' }}>
        {value != null ? Number(value).toFixed(2) : '--'}
        <Typography component="span" variant="body2" sx={{ color: '#a8a8a0', ml: 0.5 }}>
          {unit}
        </Typography>
      </Typography>
    </Box>
  );
}

export default function BenchmarkResults() {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState(null);

  const fetchResults = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiService.listBenchmarkResults(null, 50);
      setResults(data.results || []);
    } catch (err) {
      console.error('Failed to fetch benchmark results', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchResults();
  }, [fetchResults]);

  return (
    <Box sx={{ p: 4, maxWidth: '1920px', mx: 'auto' }}>
      <Stack spacing={3}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography variant="h1" sx={{ fontWeight: 800, fontSize: '3rem' }}>
            Benchmark Results
          </Typography>
          <Tooltip title="Refresh">
            <IconButton onClick={fetchResults} disabled={loading}>
              <RefreshIcon />
            </IconButton>
          </Tooltip>
        </Box>

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
            <CircularProgress size={32} />
          </Box>
        ) : results.length === 0 ? (
          <Card variant="outlined" sx={{ borderRadius: 2 }}>
            <CardContent sx={{ textAlign: 'center', py: 8 }}>
              <SpeedIcon sx={{ fontSize: 48, color: '#a8a8a0', mb: 2 }} />
              <Typography variant="h6" sx={{ color: '#a8a8a0', mb: 1 }}>
                No benchmark results yet
              </Typography>
              <Typography variant="body2" sx={{ color: '#6b6b63' }}>
                Run a benchmark from the Run Workload page to see results here.
              </Typography>
            </CardContent>
          </Card>
        ) : (
          <Stack spacing={2}>
            {results.map((result) => {
              const m = result.metrics || {};
              const isExpanded = expandedId === result.id;
              const ts = new Date(result.timestamp);
              const timeStr = ts.toLocaleDateString() + ' ' + ts.toLocaleTimeString();

              return (
                <Card
                  key={result.id}
                  variant="outlined"
                  onClick={() => setExpandedId(isExpanded ? null : result.id)}
                  sx={{
                    borderRadius: 2,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    border: isExpanded ? '1px solid #16a34a' : '1px solid #3d3d3a',
                    '&:hover': {
                      borderColor: '#16a34a',
                      bgcolor: alpha('#16a34a', 0.02),
                    },
                  }}
                >
                  <CardContent sx={{ pb: isExpanded ? 2 : '16px !important' }}>
                    {/* Header row */}
                    <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: isExpanded ? 2 : 0 }}>
                      <Box sx={{ flex: 1 }}>
                        <Stack direction="row" alignItems="center" spacing={1.5}>
                          <Typography variant="body1" sx={{ fontWeight: 600 }}>
                            {result.model_name || 'Unknown Model'}
                          </Typography>
                          <Chip
                            label={result.ssh_host}
                            size="small"
                            sx={{
                              fontSize: '0.7rem',
                              height: 22,
                              bgcolor: alpha('#a8a8a0', 0.1),
                              color: '#a8a8a0',
                            }}
                          />
                          {result.telemetry_run_id && (
                            <Chip
                              label="GPU Linked"
                              size="small"
                              sx={{
                                fontSize: '0.7rem',
                                height: 22,
                                bgcolor: alpha('#16a34a', 0.15),
                                color: '#16a34a',
                              }}
                            />
                          )}
                        </Stack>
                        <Typography variant="caption" sx={{ color: '#6b6b63' }}>
                          {timeStr}
                        </Typography>
                      </Box>

                      {/* Summary metrics inline */}
                      <Stack direction="row" spacing={3} sx={{ display: { xs: 'none', md: 'flex' } }}>
                        {m.total_throughput_tok_s != null && (
                          <Box sx={{ textAlign: 'right' }}>
                            <Typography variant="caption" sx={{ color: '#a8a8a0' }}>Throughput</Typography>
                            <Typography variant="body2" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                              {Number(m.total_throughput_tok_s).toFixed(1)} tok/s
                            </Typography>
                          </Box>
                        )}
                        {m.mean_ttft_ms != null && (
                          <Box sx={{ textAlign: 'right' }}>
                            <Typography variant="caption" sx={{ color: '#a8a8a0' }}>TTFT</Typography>
                            <Typography variant="body2" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                              {Number(m.mean_ttft_ms).toFixed(1)} ms
                            </Typography>
                          </Box>
                        )}
                        {m.mean_tpot_ms != null && (
                          <Box sx={{ textAlign: 'right' }}>
                            <Typography variant="caption" sx={{ color: '#a8a8a0' }}>TPOT</Typography>
                            <Typography variant="body2" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                              {Number(m.mean_tpot_ms).toFixed(1)} ms
                            </Typography>
                          </Box>
                        )}
                      </Stack>
                    </Stack>

                    {/* Expanded details */}
                    {isExpanded && (
                      <Box sx={{ mt: 2 }}>
                        <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', gap: 2 }}>
                          <MetricCard
                            label="Total Throughput"
                            value={m.total_throughput_tok_s}
                            unit="tok/s"
                            icon={TrendingUpIcon}
                          />
                          <MetricCard
                            label="Output Throughput"
                            value={m.output_throughput_tok_s}
                            unit="tok/s"
                            icon={TrendingUpIcon}
                            color="#3b82f6"
                          />
                          <MetricCard
                            label="Request Throughput"
                            value={m.request_throughput_req_s}
                            unit="req/s"
                            icon={SpeedIcon}
                            color="#8b5cf6"
                          />
                        </Stack>
                        <Stack direction="row" spacing={2} sx={{ mt: 2, flexWrap: 'wrap', gap: 2 }}>
                          <MetricCard
                            label="Mean TTFT"
                            value={m.mean_ttft_ms}
                            unit="ms"
                            icon={TimerIcon}
                            color="#f59e0b"
                          />
                          <MetricCard
                            label="Mean TPOT"
                            value={m.mean_tpot_ms}
                            unit="ms"
                            icon={TimerIcon}
                            color="#ef4444"
                          />
                          <MetricCard
                            label="Mean ITL"
                            value={m.mean_itl_ms}
                            unit="ms"
                            icon={TimerIcon}
                            color="#06b6d4"
                          />
                        </Stack>

                        {/* Config */}
                        {result.config && (
                          <Box sx={{ mt: 2, p: 1.5, borderRadius: 1.5, bgcolor: alpha('#3d3d3a', 0.3) }}>
                            <Typography variant="caption" sx={{ color: '#a8a8a0', fontWeight: 600, mb: 0.5, display: 'block' }}>
                              Configuration
                            </Typography>
                            <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
                              {Object.entries(result.config).filter(([, v]) => v != null).map(([k, v]) => (
                                <Typography key={k} variant="caption" sx={{ color: '#6b6b63', fontFamily: 'monospace' }}>
                                  {k.replace(/_/g, ' ')}: <span style={{ color: '#d4d4d4' }}>{v}</span>
                                </Typography>
                              ))}
                            </Stack>
                          </Box>
                        )}
                      </Box>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </Stack>
        )}
      </Stack>
    </Box>
  );
}
