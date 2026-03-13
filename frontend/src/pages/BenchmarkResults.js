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
  Checkbox,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  useTheme,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  Speed as SpeedIcon,
  Timer as TimerIcon,
  TrendingUp as TrendingUpIcon,
  Memory as MemoryIcon,
  Compare as CompareIcon,
  Close as CloseIcon,
  CheckBox as CheckBoxIcon,
  CheckBoxOutlineBlank as CheckBoxOutlineBlankIcon,
} from '@mui/icons-material';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import apiService from '../services/api';

// ── GPU spec lookup ────────────────────────────────────────────────────────────
const GPU_SPECS = {
  'H100': { fp16_tflops: 1979, hbm_bw_gbs: 3350, hbm_gb: 80, arch: 'Hopper' },
  'H100 PCIe': { fp16_tflops: 756, hbm_bw_gbs: 2000, hbm_gb: 80, arch: 'Hopper' },
  'H100 SXM': { fp16_tflops: 1979, hbm_bw_gbs: 3350, hbm_gb: 80, arch: 'Hopper' },
  'A100': { fp16_tflops: 312, hbm_bw_gbs: 2000, hbm_gb: 80, arch: 'Ampere' },
  'A100 SXM': { fp16_tflops: 312, hbm_bw_gbs: 2000, hbm_gb: 80, arch: 'Ampere' },
  'A100 PCIe': { fp16_tflops: 312, hbm_bw_gbs: 1935, hbm_gb: 80, arch: 'Ampere' },
  'A10G': { fp16_tflops: 125, hbm_bw_gbs: 600, hbm_gb: 24, arch: 'Ampere' },
  'L40S': { fp16_tflops: 733, hbm_bw_gbs: 864, hbm_gb: 48, arch: 'Ada Lovelace' },
  'L40': { fp16_tflops: 362, hbm_bw_gbs: 864, hbm_gb: 48, arch: 'Ada Lovelace' },
  'RTX 4090': { fp16_tflops: 330, hbm_bw_gbs: 1008, hbm_gb: 24, arch: 'Ada Lovelace' },
  'RTX 3090': { fp16_tflops: 142, hbm_bw_gbs: 936, hbm_gb: 24, arch: 'Ampere' },
  'V100': { fp16_tflops: 125, hbm_bw_gbs: 900, hbm_gb: 32, arch: 'Volta' },
};

function getGpuSpecs(gpuModel) {
  if (!gpuModel) return null;
  const upper = gpuModel.toUpperCase();
  for (const [key, specs] of Object.entries(GPU_SPECS)) {
    if (upper.includes(key.toUpperCase())) return { ...specs, name: key };
  }
  return null;
}

// ── Small helpers ──────────────────────────────────────────────────────────────
function fmt(v, decimals = 1) {
  if (v == null || isNaN(Number(v))) return '--';
  return Number(v).toFixed(decimals);
}

function MetricCard({ label, value, unit, icon: Icon, color = '#16a34a' }) {
  return (
    <Box sx={{ p: 2, borderRadius: 2, border: '1px solid #3d3d3a', bgcolor: 'rgba(26,26,24,0.6)', flex: 1, minWidth: 140 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        {Icon && <Icon sx={{ fontSize: 16, color }} />}
        <Typography variant="caption" sx={{ color: '#a8a8a0', fontWeight: 500 }}>{label}</Typography>
      </Stack>
      <Typography variant="h5" sx={{ fontWeight: 700, color: '#fafaf8' }}>
        {fmt(value)}
        <Typography component="span" variant="body2" sx={{ color: '#a8a8a0', ml: 0.5 }}>{unit}</Typography>
      </Typography>
    </Box>
  );
}

function GpuInfoBadges({ gpuInfo }) {
  if (!gpuInfo || !gpuInfo.gpu_model) return null;
  const specs = getGpuSpecs(gpuInfo.gpu_model);
  const shortName = gpuInfo.gpu_model.replace('NVIDIA ', '').replace('Tesla ', '');

  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mt: 0.5 }}>
      <Chip
        icon={<MemoryIcon sx={{ fontSize: '14px !important' }} />}
        label={gpuInfo.gpu_count > 1 ? `${gpuInfo.gpu_count}× ${shortName}` : shortName}
        size="small"
        sx={{ fontSize: '0.7rem', height: 22, bgcolor: alpha('#818cf8', 0.12), color: '#818cf8', border: '1px solid', borderColor: alpha('#818cf8', 0.25) }}
      />
      {gpuInfo.vram_gb && (
        <Chip
          label={`${gpuInfo.vram_gb} GB VRAM`}
          size="small"
          sx={{ fontSize: '0.7rem', height: 22, bgcolor: alpha('#06b6d4', 0.1), color: '#06b6d4' }}
        />
      )}
      {specs && (
        <Chip
          label={specs.arch}
          size="small"
          sx={{ fontSize: '0.7rem', height: 22, bgcolor: alpha('#a8a8a0', 0.08), color: '#a8a8a0' }}
        />
      )}
    </Stack>
  );
}

function GpuInfoPanel({ gpuInfo }) {
  if (!gpuInfo || !gpuInfo.gpu_model) return null;
  const specs = getGpuSpecs(gpuInfo.gpu_model);

  return (
    <Box sx={{ mt: 2, p: 1.5, borderRadius: 1.5, bgcolor: alpha('#818cf8', 0.05), border: '1px solid', borderColor: alpha('#818cf8', 0.15) }}>
      <Typography variant="caption" sx={{ color: '#818cf8', fontWeight: 600, mb: 1, display: 'block' }}>
        GPU Hardware
      </Typography>
      <Stack direction="row" spacing={3} flexWrap="wrap">
        <Box>
          <Typography variant="caption" sx={{ color: '#6b6b63' }}>Model</Typography>
          <Typography variant="body2" sx={{ fontWeight: 600, color: '#fafaf8' }}>
            {gpuInfo.gpu_count > 1 ? `${gpuInfo.gpu_count}×` : ''} {gpuInfo.gpu_model}
          </Typography>
        </Box>
        {gpuInfo.vram_gb && (
          <Box>
            <Typography variant="caption" sx={{ color: '#6b6b63' }}>VRAM</Typography>
            <Typography variant="body2" sx={{ fontWeight: 600, color: '#fafaf8' }}>{gpuInfo.vram_gb} GB</Typography>
          </Box>
        )}
        {specs && (
          <>
            <Box>
              <Typography variant="caption" sx={{ color: '#6b6b63' }}>Architecture</Typography>
              <Typography variant="body2" sx={{ fontWeight: 600, color: '#fafaf8' }}>{specs.arch}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" sx={{ color: '#6b6b63' }}>FP16 Peak</Typography>
              <Typography variant="body2" sx={{ fontWeight: 600, color: '#fafaf8' }}>{specs.fp16_tflops} TFLOPS</Typography>
            </Box>
            <Box>
              <Typography variant="caption" sx={{ color: '#6b6b63' }}>HBM BW</Typography>
              <Typography variant="body2" sx={{ fontWeight: 600, color: '#fafaf8' }}>{specs.hbm_bw_gbs} GB/s</Typography>
            </Box>
          </>
        )}
        {gpuInfo.driver_version && (
          <Box>
            <Typography variant="caption" sx={{ color: '#6b6b63' }}>Driver</Typography>
            <Typography variant="body2" sx={{ fontWeight: 600, color: '#fafaf8' }}>{gpuInfo.driver_version}</Typography>
          </Box>
        )}
      </Stack>
    </Box>
  );
}

// ── Compare Dialog ─────────────────────────────────────────────────────────────
const COMPARE_METRICS = [
  { key: 'total_throughput_tok_s', label: 'Total Throughput', unit: 'tok/s', higherBetter: true, color: '#16a34a' },
  { key: 'output_throughput_tok_s', label: 'Output Throughput', unit: 'tok/s', higherBetter: true, color: '#3b82f6' },
  { key: 'request_throughput_req_s', label: 'Request Throughput', unit: 'req/s', higherBetter: true, color: '#8b5cf6' },
  { key: 'mean_ttft_ms', label: 'Mean TTFT', unit: 'ms', higherBetter: false, color: '#f59e0b' },
  { key: 'mean_tpot_ms', label: 'Mean TPOT', unit: 'ms', higherBetter: false, color: '#ef4444' },
  { key: 'mean_itl_ms', label: 'Mean ITL', unit: 'ms', higherBetter: false, color: '#06b6d4' },
];

const CHART_COLORS = ['#16a34a', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899'];

function runLabel(r, idx) {
  const gpu = r.gpu_info?.gpu_model ? r.gpu_info.gpu_model.replace('NVIDIA ', '') : r.ssh_host;
  const model = (r.model_name || '').split('/').pop().split(' ')[0];
  const date = new Date(r.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `${model} · ${gpu} · ${date}`;
}

function CompareDialog({ open, onClose, runs }) {
  const theme = useTheme();
  const [activeMetric, setActiveMetric] = useState(COMPARE_METRICS[0].key);
  const metric = COMPARE_METRICS.find(m => m.key === activeMetric);

  const chartData = runs.map((r, i) => ({
    name: runLabel(r, i),
    value: r.metrics?.[activeMetric] != null ? Number(r.metrics[activeMetric]) : null,
    color: CHART_COLORS[i % CHART_COLORS.length],
  })).filter(d => d.value != null);

  const best = metric?.higherBetter
    ? Math.max(...chartData.map(d => d.value))
    : Math.min(...chartData.map(d => d.value));

  const CustomBar = (props) => {
    const { x, y, width, height, value } = props;
    const isBest = value === best;
    return <rect x={x} y={y} width={width} height={height} rx={4} fill={isBest ? '#16a34a' : '#3b82f6'} opacity={isBest ? 1 : 0.65} />;
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth
      PaperProps={{ sx: { bgcolor: '#1a1a18', border: '1px solid #3d3d3a', borderRadius: 2 } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #3d3d3a' }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <CompareIcon sx={{ color: '#16a34a' }} />
          <Typography variant="h6" sx={{ fontWeight: 700 }}>Compare Runs</Typography>
          <Chip label={`${runs.length} runs`} size="small" sx={{ bgcolor: alpha('#16a34a', 0.15), color: '#16a34a' }} />
        </Stack>
        <IconButton onClick={onClose} size="small"><CloseIcon /></IconButton>
      </DialogTitle>

      <DialogContent sx={{ pt: 3 }}>
        {/* Metric selector */}
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 3 }}>
          {COMPARE_METRICS.map(m => (
            <Chip
              key={m.key}
              label={m.label}
              onClick={() => setActiveMetric(m.key)}
              size="small"
              sx={{
                cursor: 'pointer',
                bgcolor: activeMetric === m.key ? alpha('#16a34a', 0.2) : alpha('#3d3d3a', 0.5),
                color: activeMetric === m.key ? '#16a34a' : '#a8a8a0',
                border: '1px solid',
                borderColor: activeMetric === m.key ? '#16a34a' : 'transparent',
                '&:hover': { bgcolor: alpha('#16a34a', 0.1) },
              }}
            />
          ))}
        </Stack>

        {/* Bar chart */}
        {chartData.length > 0 && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="caption" sx={{ color: '#a8a8a0', mb: 1, display: 'block' }}>
              {metric?.label} ({metric?.unit}) — {metric?.higherBetter ? 'higher is better' : 'lower is better'}
            </Typography>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 60 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a28" />
                <XAxis dataKey="name" tick={{ fill: '#6b6b63', fontSize: 11 }} angle={-25} textAnchor="end" interval={0} />
                <YAxis tick={{ fill: '#6b6b63', fontSize: 11 }} />
                <RechartsTooltip
                  contentStyle={{ bgcolor: '#2a2a28', border: '1px solid #3d3d3a', borderRadius: 8 }}
                  formatter={(v) => [`${fmt(v)} ${metric?.unit}`, metric?.label]}
                />
                <Bar dataKey="value" shape={<CustomBar />} />
              </BarChart>
            </ResponsiveContainer>
          </Box>
        )}

        {/* Summary table */}
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ '& th': { borderColor: '#3d3d3a', color: '#6b6b63', fontSize: '0.72rem', fontWeight: 600, py: 1 } }}>
                <TableCell sx={{ minWidth: 180 }}>Run</TableCell>
                <TableCell>GPU</TableCell>
                {COMPARE_METRICS.map(m => (
                  <TableCell key={m.key} align="right" sx={{ color: activeMetric === m.key ? '#16a34a !important' : undefined }}>
                    {m.label}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {runs.map((r, i) => {
                const m = r.metrics || {};
                const gpu = r.gpu_info?.gpu_model ? r.gpu_info.gpu_model.replace('NVIDIA ', '') : r.ssh_host;
                const vram = r.gpu_info?.vram_gb ? ` · ${r.gpu_info.vram_gb}GB` : '';
                const date = new Date(r.timestamp).toLocaleDateString();
                return (
                  <TableRow key={r.id} sx={{ '& td': { borderColor: '#2a2a28', py: 1 } }}>
                    <TableCell>
                      <Typography variant="body2" sx={{ fontWeight: 600, color: '#fafaf8', fontSize: '0.8rem' }}>
                        {(r.model_name || '').split('/').pop()}
                      </Typography>
                      <Typography variant="caption" sx={{ color: '#6b6b63' }}>{date}</Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" sx={{ color: '#818cf8' }}>{gpu}{vram}</Typography>
                    </TableCell>
                    {COMPARE_METRICS.map(cm => {
                      const val = m[cm.key];
                      const allVals = runs.map(rr => rr.metrics?.[cm.key]).filter(v => v != null).map(Number);
                      const isBest = allVals.length > 1 && val != null && (
                        cm.higherBetter ? Number(val) === Math.max(...allVals) : Number(val) === Math.min(...allVals)
                      );
                      return (
                        <TableCell key={cm.key} align="right">
                          <Typography variant="body2" sx={{
                            fontFamily: 'monospace',
                            fontWeight: isBest ? 700 : 400,
                            color: isBest ? '#16a34a' : cm.key === activeMetric ? '#fafaf8' : '#a8a8a0',
                            fontSize: '0.8rem',
                          }}>
                            {fmt(val)}
                          </Typography>
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Box>

        {/* Config comparison */}
        {runs.some(r => r.config) && (
          <Box sx={{ mt: 3 }}>
            <Typography variant="caption" sx={{ color: '#a8a8a0', fontWeight: 600, mb: 1, display: 'block' }}>
              Benchmark Configuration
            </Typography>
            <Table size="small">
              <TableHead>
                <TableRow sx={{ '& th': { borderColor: '#3d3d3a', color: '#6b6b63', fontSize: '0.72rem', py: 0.5 } }}>
                  <TableCell>Parameter</TableCell>
                  {runs.map((r, i) => (
                    <TableCell key={r.id} align="right">
                      {(r.model_name || '').split('/').pop().slice(0, 16)}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {['input_seq_len', 'output_seq_len', 'num_requests', 'max_concurrency'].map(key => (
                  <TableRow key={key} sx={{ '& td': { borderColor: '#2a2a28', py: 0.5 } }}>
                    <TableCell><Typography variant="caption" sx={{ color: '#6b6b63' }}>{key.replace(/_/g, ' ')}</Typography></TableCell>
                    {runs.map(r => (
                      <TableCell key={r.id} align="right">
                        <Typography variant="caption" sx={{ fontFamily: 'monospace', color: '#d4d4d4' }}>
                          {r.config?.[key] ?? '--'}
                        </Typography>
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ borderTop: '1px solid #3d3d3a', px: 3, py: 2 }}>
        <Button onClick={onClose} size="small" sx={{ color: '#a8a8a0' }}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function BenchmarkResults() {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [compareOpen, setCompareOpen] = useState(false);

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

  useEffect(() => { fetchResults(); }, [fetchResults]);

  const toggleSelect = (id, e) => {
    e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectedRuns = results.filter(r => selectedIds.has(r.id));

  return (
    <Box sx={{ p: 4, maxWidth: '1920px', mx: 'auto' }}>
      <Stack spacing={3}>
        {/* Header */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
          <Typography variant="h1" sx={{ fontWeight: 800, fontSize: '3rem' }}>
            Benchmark Results
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            {selectedIds.size >= 2 && (
              <Button
                variant="contained"
                startIcon={<CompareIcon />}
                onClick={() => setCompareOpen(true)}
                sx={{ bgcolor: '#16a34a', '&:hover': { bgcolor: '#15803d' }, borderRadius: 2, textTransform: 'none', fontWeight: 600 }}
              >
                Compare {selectedIds.size} Runs
              </Button>
            )}
            {selectedIds.size > 0 && (
              <Button
                size="small"
                onClick={() => setSelectedIds(new Set())}
                sx={{ color: '#a8a8a0', textTransform: 'none' }}
              >
                Clear
              </Button>
            )}
            <Tooltip title="Refresh">
              <IconButton onClick={fetchResults} disabled={loading}><RefreshIcon /></IconButton>
            </Tooltip>
          </Stack>
        </Box>

        {selectedIds.size > 0 && selectedIds.size < 2 && (
          <Typography variant="caption" sx={{ color: '#6b6b63' }}>
            Select at least 2 runs to compare
          </Typography>
        )}

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
            <CircularProgress size={32} />
          </Box>
        ) : results.length === 0 ? (
          <Card variant="outlined" sx={{ borderRadius: 2 }}>
            <CardContent sx={{ textAlign: 'center', py: 8 }}>
              <SpeedIcon sx={{ fontSize: 48, color: '#a8a8a0', mb: 2 }} />
              <Typography variant="h6" sx={{ color: '#a8a8a0', mb: 1 }}>No benchmark results yet</Typography>
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
              const isSelected = selectedIds.has(result.id);
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
                    border: isSelected
                      ? '1px solid #3b82f6'
                      : isExpanded
                      ? '1px solid #16a34a'
                      : '1px solid #3d3d3a',
                    bgcolor: isSelected ? alpha('#3b82f6', 0.03) : undefined,
                    '&:hover': {
                      borderColor: isSelected ? '#3b82f6' : '#16a34a',
                      bgcolor: isSelected ? alpha('#3b82f6', 0.05) : alpha('#16a34a', 0.02),
                    },
                  }}
                >
                  <CardContent sx={{ pb: isExpanded ? 2 : '16px !important' }}>
                    {/* Header row */}
                    <Stack direction="row" alignItems="flex-start" spacing={2}>
                      {/* Checkbox */}
                      <Tooltip title={isSelected ? 'Deselect' : 'Select to compare'}>
                        <IconButton
                          size="small"
                          onClick={(e) => toggleSelect(result.id, e)}
                          sx={{ mt: -0.5, color: isSelected ? '#3b82f6' : '#3d3d3a', '&:hover': { color: '#3b82f6' } }}
                        >
                          {isSelected ? <CheckBoxIcon fontSize="small" /> : <CheckBoxOutlineBlankIcon fontSize="small" />}
                        </IconButton>
                      </Tooltip>

                      <Box sx={{ flex: 1 }}>
                        <Stack direction="row" alignItems="center" spacing={1.5} flexWrap="wrap">
                          <Typography variant="body1" sx={{ fontWeight: 600 }}>
                            {result.model_name || 'Unknown Model'}
                          </Typography>
                          {result.telemetry_run_id && (
                            <Chip
                              label="GPU Linked"
                              size="small"
                              sx={{ fontSize: '0.7rem', height: 22, bgcolor: alpha('#16a34a', 0.15), color: '#16a34a' }}
                            />
                          )}
                        </Stack>
                        <Typography variant="caption" sx={{ color: '#6b6b63' }}>{timeStr} · {result.ssh_host}</Typography>
                        {result.gpu_info?.gpu_model ? (
                          <GpuInfoBadges gpuInfo={result.gpu_info} />
                        ) : (
                          <Typography variant="caption" sx={{ color: '#4b4b43', fontStyle: 'italic', mt: 0.5, display: 'block' }}>
                            GPU info not recorded
                          </Typography>
                        )}
                      </Box>

                      {/* Summary metrics inline */}
                      <Stack direction="row" spacing={3} sx={{ display: { xs: 'none', md: 'flex' }, alignItems: 'center' }}>
                        {m.total_throughput_tok_s != null && (
                          <Box sx={{ textAlign: 'right' }}>
                            <Typography variant="caption" sx={{ color: '#a8a8a0' }}>Throughput</Typography>
                            <Typography variant="body2" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                              {fmt(m.total_throughput_tok_s)} tok/s
                            </Typography>
                          </Box>
                        )}
                        {m.mean_ttft_ms != null && (
                          <Box sx={{ textAlign: 'right' }}>
                            <Typography variant="caption" sx={{ color: '#a8a8a0' }}>TTFT</Typography>
                            <Typography variant="body2" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                              {fmt(m.mean_ttft_ms)} ms
                            </Typography>
                          </Box>
                        )}
                        {m.mean_tpot_ms != null && (
                          <Box sx={{ textAlign: 'right' }}>
                            <Typography variant="caption" sx={{ color: '#a8a8a0' }}>TPOT</Typography>
                            <Typography variant="body2" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                              {fmt(m.mean_tpot_ms)} ms
                            </Typography>
                          </Box>
                        )}
                      </Stack>
                    </Stack>

                    {/* Expanded details */}
                    {isExpanded && (
                      <Box sx={{ mt: 2 }}>
                        <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', gap: 2 }}>
                          <MetricCard label="Total Throughput" value={m.total_throughput_tok_s} unit="tok/s" icon={TrendingUpIcon} />
                          <MetricCard label="Output Throughput" value={m.output_throughput_tok_s} unit="tok/s" icon={TrendingUpIcon} color="#3b82f6" />
                          <MetricCard label="Request Throughput" value={m.request_throughput_req_s} unit="req/s" icon={SpeedIcon} color="#8b5cf6" />
                        </Stack>
                        <Stack direction="row" spacing={2} sx={{ mt: 2, flexWrap: 'wrap', gap: 2 }}>
                          <MetricCard label="Mean TTFT" value={m.mean_ttft_ms} unit="ms" icon={TimerIcon} color="#f59e0b" />
                          <MetricCard label="Mean TPOT" value={m.mean_tpot_ms} unit="ms" icon={TimerIcon} color="#ef4444" />
                          <MetricCard label="Mean ITL" value={m.mean_itl_ms} unit="ms" icon={TimerIcon} color="#06b6d4" />
                        </Stack>

                        <GpuInfoPanel gpuInfo={result.gpu_info} />

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

      <CompareDialog
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        runs={selectedRuns}
      />
    </Box>
  );
}
