import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  alpha,
  useTheme,
} from '@mui/material';
import {
  History as HistoryIcon,
  Delete as DeleteIcon,
  Replay as ReplayIcon,
  Warning as WarningIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  DataUsage as DataUsageIcon,
  ExpandMore as ExpandMoreIcon,
  Cloud as CloudIcon,
  Bolt as BoltIcon,
  Memory as MemoryIcon,
  Whatshot as WhatshotIcon,
  Timeline as TimelineIcon,
  Info as InfoIcon,
  Close as CloseIcon,
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  Speed as SpeedIcon,
  AttachMoney as AttachMoneyIcon,
} from '@mui/icons-material';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  Legend,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';
import apiService, { telemetryUtils } from '../services/api';
import AIInsightsBox from './AIInsightsBox';
import SMMetricsOverlay from './SMMetricsOverlay';

const COLOR_PALETTE = [
  '#818cf8',
  '#ef5350',
  '#26a69a',
  '#ffa726',
  '#ab47bc',
  '#66bb6a',
  '#ff7043',
  '#8d6e63',
];
const HISTORY_TARGET_POINTS = 1200;
const HISTORY_MAX_POINTS = 6000;

const downsampleTimeSeries = (data, targetPoints = HISTORY_TARGET_POINTS, hardLimit = HISTORY_MAX_POINTS) => {
  if (!Array.isArray(data) || data.length === 0) {
    return data || [];
  }
  const limited = hardLimit ? data.slice(-hardLimit) : data;
  if (limited.length <= targetPoints) {
    return limited;
  }
  const bucketSize = Math.ceil(limited.length / targetPoints);
  const downsampled = [];
  for (let i = 0; i < limited.length; i += bucketSize) {
    const bucketEnd = Math.min(limited.length - 1, i + bucketSize - 1);
    downsampled.push(limited[bucketEnd]);
  }
  return downsampled;
};

const transformSamplesToSeries = (samples, maxPoints = null) => {
  const map = new Map();
  const gpuIds = new Set();

  samples.forEach((sample) => {
    if (!sample || !sample.time) {
      return;
    }
    const timestamp = sample.time;
    const timeValue = telemetryUtils.parseTimestamp(timestamp);
    const key = timestamp;
    const existing = map.get(key) || {
      timestamp,
      epoch: timeValue ? timeValue.getTime() : Date.now(),
      timeLabel: timeValue ? timeValue.toLocaleTimeString() : timestamp,
    };

    const gpuKey = `gpu_${sample.gpu_id}`;
    gpuIds.add(sample.gpu_id);

    existing[`${gpuKey}_util`] =
      sample.gpu_utilization != null ? Number(sample.gpu_utilization) : null;
    existing[`${gpuKey}_mem_util`] =
      sample.memory_utilization != null ? Number(sample.memory_utilization) : null;
    existing[`${gpuKey}_power`] =
      sample.power_draw_watts != null ? Number(sample.power_draw_watts) : null;
    existing[`${gpuKey}_temp`] =
      sample.temperature_celsius != null ? Number(sample.temperature_celsius) : null;
    existing[`${gpuKey}_sm_util`] =
      sample.sm_utilization != null ? Number(sample.sm_utilization) : null;
    existing[`${gpuKey}_hbm_util`] =
      sample.hbm_utilization != null ? Number(sample.hbm_utilization) : null;
    existing[`${gpuKey}_sm_occupancy`] =
      sample.sm_occupancy != null ? Number(sample.sm_occupancy) : null;
    existing[`${gpuKey}_tensor_active`] =
      sample.tensor_active != null ? Number(sample.tensor_active) : null;
    existing[`${gpuKey}_fp64_active`] =
      sample.fp64_active != null ? Number(sample.fp64_active) : null;
    existing[`${gpuKey}_fp32_active`] =
      sample.fp32_active != null ? Number(sample.fp32_active) : null;
    existing[`${gpuKey}_fp16_active`] =
      sample.fp16_active != null ? Number(sample.fp16_active) : null;
    existing[`${gpuKey}_gr_engine_active`] =
      sample.gr_engine_active != null ? Number(sample.gr_engine_active) : null;
    existing[`${gpuKey}_mem_temp`] =
      sample.memory_temperature_celsius != null ? Number(sample.memory_temperature_celsius) : null;
    existing[`${gpuKey}_pcie_tx`] =
      sample.pcie_tx_mb_per_sec != null ? Number(sample.pcie_tx_mb_per_sec) : null;
    existing[`${gpuKey}_pcie_rx`] =
      sample.pcie_rx_mb_per_sec != null ? Number(sample.pcie_rx_mb_per_sec) : null;
    existing[`${gpuKey}_nvlink_tx`] =
      sample.nvlink_tx_mb_per_sec != null ? Number(sample.nvlink_tx_mb_per_sec) : null;
    existing[`${gpuKey}_nvlink_rx`] =
      sample.nvlink_rx_mb_per_sec != null ? Number(sample.nvlink_rx_mb_per_sec) : null;
    // Token metrics are application-level, not per-GPU - aggregate from any GPU
    if (sample.tokens_per_second != null) {
      existing.tokens_per_second = Number(sample.tokens_per_second);
    }
    if (sample.requests_per_second != null) {
      existing.requests_per_second = Number(sample.requests_per_second);
    }
    if (sample.ttft_p50_ms != null) {
      existing.ttft_p50_ms = Number(sample.ttft_p50_ms);
    }
    if (sample.ttft_p95_ms != null) {
      existing.ttft_p95_ms = Number(sample.ttft_p95_ms);
    }
    if (sample.cost_per_watt != null) {
      existing.cost_per_watt = Number(sample.cost_per_watt);
    }
    existing[`${gpuKey}_energy_wh`] =
      sample.total_energy_joules != null ? Number(sample.total_energy_joules) / 3600.0 : null;
    existing[`${gpuKey}_encoder_util`] =
      sample.encoder_utilization != null ? Number(sample.encoder_utilization) : null;
    existing[`${gpuKey}_decoder_util`] =
      sample.decoder_utilization != null ? Number(sample.decoder_utilization) : null;
    existing[`${gpuKey}_fan_speed`] =
      sample.fan_speed_percent != null ? Number(sample.fan_speed_percent) : null;
    existing[`${gpuKey}_pstate`] =
      sample.pstate != null ? Number(sample.pstate) : null;
    existing[`${gpuKey}_slowdown_temp`] =
      sample.slowdown_temperature_celsius != null ? Number(sample.slowdown_temperature_celsius) : null;
    existing[`${gpuKey}_sm_clock_mhz`] =
      sample.sm_clock_mhz != null ? Number(sample.sm_clock_mhz) : null;
    existing[`${gpuKey}_memory_clock_mhz`] =
      sample.memory_clock_mhz != null ? Number(sample.memory_clock_mhz) : null;

    map.set(key, existing);
  });

  const sorted = Array.from(map.values()).sort((a, b) => a.epoch - b.epoch);
  const trimmed = maxPoints ? sorted.slice(-maxPoints) : downsampleTimeSeries(sorted);

  return {
    data: trimmed,
    gpuIds: Array.from(gpuIds).sort((a, b) => a - b),
  };
};

const METRIC_DEFINITIONS = [
  {
    id: 'gpu-util',
    metricKey: 'util',
    title: 'GPU Utilization',
    historicalTitle: 'GPU Utilization',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Overall GPU utilization from nvidia-smi. Available on all GPUs without profiling mode.',
  },
  {
    id: 'sm-util',
    metricKey: 'sm_util',
    title: 'SM Utilization',
    historicalTitle: 'SM Utilization',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description: 'Hardware counter-based Streaming Multiprocessor activity. Requires profiling mode.',
  },
  {
    id: 'sm-occupancy',
    metricKey: 'sm_occupancy',
    title: 'SM Occupancy',
    historicalTitle: 'SM Occupancy',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Streaming Multiprocessor occupancy percentage. Indicates how many warps are active relative to hardware capacity.',
  },
  {
    id: 'memory-util',
    metricKey: 'mem_util',
    title: 'Memory Utilization',
    historicalTitle: 'Memory Utilization',
    unit: '%',
    domain: [0, 100],
    icon: MemoryIcon,
    description: 'GPU memory usage as a percentage of total available memory.',
  },
  {
    id: 'power-draw',
    metricKey: 'power',
    title: 'Power Draw',
    historicalTitle: 'Power Draw',
    unit: 'Watts',
    icon: BoltIcon,
    description: 'Current power consumption in watts.',
  },
  {
    id: 'temperature',
    metricKey: 'temp',
    title: 'Temperature',
    historicalTitle: 'Temperature',
    unit: '°C',
    domain: [0, 120],
    icon: WhatshotIcon,
    description: 'GPU temperature in Celsius.',
  },
  {
    id: 'hbm-util',
    metricKey: 'hbm_util',
    title: 'HBM Utilization (Profiling)',
    historicalTitle: 'HBM Utilization',
    unit: '%',
    domain: [0, 100],
    icon: MemoryIcon,
    description: 'Memory bandwidth utilization (DRAM active). Requires profiling mode.',
  },
  {
    id: 'tensor-active',
    metricKey: 'tensor_active',
    title: 'Tensor Core Activity',
    historicalTitle: 'Tensor Core Activity',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Tensor Core pipeline utilization (requires DCGM profiling). High values indicate tensor operations (matrix multiply).',
  },
  {
    id: 'fp64-active',
    metricKey: 'fp64_active',
    title: 'FP64 Pipeline Activity',
    historicalTitle: 'FP64 Pipeline Activity',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Double-precision floating point pipeline utilization (FP64). Important for HPC scientific workloads.',
  },
  {
    id: 'fp32-active',
    metricKey: 'fp32_active',
    title: 'FP32 Pipeline Activity',
    historicalTitle: 'FP32 Pipeline Activity',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Single-precision floating point pipeline utilization (FP32). Standard for many compute workloads.',
  },
  {
    id: 'fp16-active',
    metricKey: 'fp16_active',
    title: 'FP16 Pipeline Activity',
    historicalTitle: 'FP16 Pipeline Activity',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Half-precision floating point pipeline utilization (FP16/BF16). Helps identify mixed-precision workloads.',
  },
  {
    id: 'gr-engine-active',
    metricKey: 'gr_engine_active',
    title: 'Graphics Engine Activity',
    historicalTitle: 'Graphics Engine Activity',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Graphics engine activity from DCGM profiling (gr_engine_active). Useful for visualization or compute overlaps.',
  },
  {
    id: 'pcie-tx',
    metricKey: 'pcie_tx',
    title: 'PCIe TX Throughput',
    historicalTitle: 'PCIe TX Throughput',
    unit: 'MB/s',
    icon: TimelineIcon,
    description: 'PCIe transmit throughput per GPU. Indicates host-to-device traffic pressure.',
  },
  {
    id: 'pcie-rx',
    metricKey: 'pcie_rx',
    title: 'PCIe RX Throughput',
    historicalTitle: 'PCIe RX Throughput',
    unit: 'MB/s',
    icon: TimelineIcon,
    description: 'PCIe receive throughput per GPU. Indicates device-to-host traffic pressure.',
  },
  {
    id: 'nvlink-tx',
    metricKey: 'nvlink_tx',
    title: 'NVLink TX Throughput (Profiling)',
    historicalTitle: 'NVLink TX Throughput',
    unit: 'MB/s',
    icon: TimelineIcon,
    description: 'NVLink transmit throughput (per GPU). Useful for multi-GPU communication diagnostics.',
  },
  {
    id: 'nvlink-rx',
    metricKey: 'nvlink_rx',
    title: 'NVLink RX Throughput',
    historicalTitle: 'NVLink RX Throughput',
    unit: 'MB/s',
    icon: TimelineIcon,
    description: 'NVLink receive throughput (per GPU).',
  },
  {
    id: 'mem-temp',
    metricKey: 'mem_temp',
    title: 'Memory Temperature',
    historicalTitle: 'Memory Temperature',
    unit: '°C',
    domain: [0, 120],
    icon: WhatshotIcon,
    description: 'HBM temperature reported by DCGM. Complements core temperature monitoring.',
  },
  {
    id: 'energy',
    metricKey: 'energy_wh',
    title: 'Cumulative Energy',
    historicalTitle: 'Cumulative Energy',
    unit: 'Wh',
    domain: [0, 'auto'],
    icon: BoltIcon,
    description: 'Total energy consumption per GPU (converted from DCGM Joule counter). Useful for cost tracking.',
  },
  {
    id: 'tokens-per-second',
    metricKey: 'tokens_per_second',
    title: 'Tokens per Second',
    historicalTitle: 'Tokens per Second',
    unit: 'tokens/s',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    description: 'Token throughput for LLM inference workloads. Requires application-level integration to collect.',
  },
  {
    id: 'requests-per-second',
    metricKey: 'requests_per_second',
    title: 'Requests per Second',
    historicalTitle: 'Requests per Second',
    unit: 'req/s',
    domain: [0, 'auto'],
    icon: SpeedIcon,
    description: 'Request throughput for LLM inference workloads. Shows the rate at which requests are being processed.',
  },
  {
    id: 'ttft-p50',
    metricKey: 'ttft_p50_ms',
    title: 'Time to First Token (P50)',
    historicalTitle: 'Time to First Token (P50)',
    unit: 'ms',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    description: 'P50 (median) time to first token in milliseconds. Measures the latency from request start to first token generation.',
  },
  {
    id: 'ttft-p95',
    metricKey: 'ttft_p95_ms',
    title: 'Time to First Token (P95)',
    historicalTitle: 'Time to First Token (P95)',
    unit: 'ms',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    description: 'P95 time to first token in milliseconds. Measures the 95th percentile latency from request start to first token generation.',
  },
  {
    id: 'cost-per-watt',
    metricKey: 'cost_per_watt',
    title: 'Performance per Watt',
    historicalTitle: 'Performance per Watt',
    unit: 'tokens/s/W',
    domain: [0, 'auto'],
    icon: AttachMoneyIcon,
    description: 'Performance efficiency metric: tokens generated per second per watt of power consumed. Higher values indicate better energy efficiency.',
  },
  {
    id: 'sm-clock',
    metricKey: 'sm_clock_mhz',
    title: 'SM Clock',
    historicalTitle: 'SM Clock',
    unit: 'MHz',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    description: 'Streaming Multiprocessor clock frequency in MHz. Helps correlate workload behavior with clock changes.',
  },
];

const MetricChart = ({ title, metricKey, unit, domain, data, gpuIds, icon: IconComponent, description, timeRange = 'all' }) => {
  // Token metrics are application-level, not per-GPU
  const isTokenMetric = ['tokens_per_second', 'requests_per_second', 'ttft_p50_ms', 'ttft_p95_ms', 'cost_per_watt'].includes(metricKey);
  const theme = useTheme();
  
  // State for SM view toggle
  const [smViewEnabled, setSmViewEnabled] = React.useState(false);
  const [smSession, setSmSession] = React.useState(null);
  const [smData, setSmData] = React.useState(null);
  const [smLoading, setSmLoading] = React.useState(false);
  const [smError, setSmError] = React.useState('');
  
  // Enhanced color palette with gradients
  const getGradientColors = (baseColor, index) => {
    const gradients = [
      { start: '#818cf8', end: '#a5b4fc' },
      { start: '#ef5350', end: '#e57373' },
      { start: '#26a69a', end: '#4db6ac' },
      { start: '#ffa726', end: '#ffb74d' },
      { start: '#ab47bc', end: '#ba68c8' },
      { start: '#66bb6a', end: '#81c784' },
      { start: '#ff7043', end: '#ff8a65' },
      { start: '#8d6e63', end: '#a1887f' },
    ];
    return gradients[index % gradients.length];
  };

  // Calculate statistics for all GPUs
  const calculateStats = () => {
    const allValues = [];
    if (isTokenMetric) {
      // Token metrics are application-level - use direct metric key
      data.forEach((point) => {
        const value = point[metricKey];
        if (value !== null && value !== undefined && !isNaN(value)) {
          allValues.push(value);
        }
      });
    } else {
      // GPU metrics - aggregate across all GPUs
    gpuIds.forEach((id) => {
      data.forEach((point) => {
        const value = point[`gpu_${id}_${metricKey}`];
        if (value !== null && value !== undefined && !isNaN(value)) {
          allValues.push(value);
        }
      });
    });
    }

    if (allValues.length === 0) {
      return { min: null, max: null, avg: null };
    }

    const min = Math.min(...allValues);
    const max = Math.max(...allValues);
    const avg = allValues.reduce((sum, val) => sum + val, 0) / allValues.length;

    return { min, max, avg };
  };

  const stats = calculateStats();

  // Poll for SM profiling results
  const pollForSMResults = React.useCallback(async (sessionId) => {
    const maxPolls = 60; // 5 minutes max (60 polls * 5 seconds)
    for (let i = 0; i < maxPolls; i++) {
      try {
        const status = await apiService.getSMProfilingStatus(sessionId);
        
        if (status.status === 'completed') {
          const results = await apiService.getSMMetrics(sessionId, metricKey);
          setSmData(results);
          setSmLoading(false);
          return;
        } else if (status.status === 'failed') {
          setSmError(status.error_message || 'Profiling failed');
          setSmLoading(false);
          return;
        }
        
        // Still running, wait and poll again
        await new Promise(r => setTimeout(r, 5000)); // Poll every 5 seconds
      } catch (err) {
        console.error('Error polling SM profiling status:', err);
        setSmError('Failed to poll profiling status: ' + err.message);
        setSmLoading(false);
        return;
      }
    }
    
    // Timeout
    setSmError('Profiling timeout - please try again');
    setSmLoading(false);
  }, [metricKey]);

  // Handle toggle SM view
  const handleToggleSMView = React.useCallback(async () => {
    if (!smViewEnabled) {
      // Enabling SM view - trigger profiling
      setSmLoading(true);
      setSmError('');
      setSmData(null);
      
      try {
        // Note: In a real implementation, you'd get these SSH credentials from:
        // 1. User configuration/settings
        // 2. Stored credentials for the instance
        // 3. Deployment metadata from the run
        // For now, we'll show an error indicating credentials are needed
        
        // Placeholder: Get run details to extract SSH info
        // In production, this would come from a proper credential store
        const runId = data[0]?.run_id; // Assuming run_id is available in data
        
        if (!runId) {
          throw new Error('Run ID not available - cannot trigger profiling');
        }

        // TODO: Retrieve SSH credentials from secure storage
        // For demo, show that feature is available but needs configuration
        const mockSSHConfig = {
          ssh_host: 'example.com',
          ssh_user: 'ubuntu',
          ssh_key: 'placeholder_key',
        };

        const session = await apiService.triggerSMProfiling({
          run_id: runId,
          gpu_id: gpuIds[0] || 0,
          metric_name: metricKey,
          ...mockSSHConfig,
        });
        
        setSmSession(session);
        setSmViewEnabled(true);
        
        // Start polling for results
        pollForSMResults(session.session_id);
      } catch (err) {
        console.error('Failed to trigger SM profiling:', err);
        setSmError('SM profiling requires SSH configuration. Feature available in enterprise mode.');
        setSmLoading(false);
      }
    } else {
      // Disabling SM view
      setSmViewEnabled(false);
      setSmData(null);
      setSmError('');
    }
  }, [smViewEnabled, metricKey, gpuIds, pollForSMResults, data]);

  // Calculate thresholds (80% and 20% of domain range, or based on stats)
  const getThresholds = () => {
    if (domain && Array.isArray(domain) && domain.length === 2) {
      const [minDomain, maxDomain] = domain;
      if (typeof minDomain === 'number' && typeof maxDomain === 'number') {
        const range = maxDomain - minDomain;
        return {
          top: minDomain + range * 0.8,
          bottom: minDomain + range * 0.2,
        };
      }
    }
    // Use stats-based thresholds if domain is auto
    if (stats.max !== null && stats.min !== null) {
      const range = stats.max - stats.min;
      return {
        top: stats.min + range * 0.8,
        bottom: stats.min + range * 0.2,
      };
    }
    return null;
  };

  const thresholds = getThresholds();

  if (!data.length) {
    return (
      <Card 
        sx={{ 
          borderRadius: '8px',
          border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
        }}
      >
        <CardHeader
          avatar={
            IconComponent ? (
              <Box
                sx={{
                  p: 1,
                  borderRadius: '8px',
                  backgroundColor: alpha(theme.palette.primary.main, 0.1),
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <IconComponent sx={{ color: theme.palette.primary.main, fontSize: 20 }} />
              </Box>
            ) : null
          }
          title={
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              {title}
            </Typography>
          }
          action={
            description ? (
              <Tooltip title={description} arrow placement="top">
                <IconButton size="small" sx={{ borderRadius: 1 }}>
                  <InfoIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            ) : null
          }
          sx={{ pb: 1 }}
        />
        <CardContent>
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              py: 4,
              minHeight: 200,
            }}
          >
            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
            No data available.
          </Typography>
          </Box>
        </CardContent>
      </Card>
    );
  }

  // Calculate minimum width for horizontal scrolling (50px per data point, minimum 800px)
  const chartWidth = Math.max(800, data.length * 50);

  return (
    <Card 
      sx={{ 
        borderRadius: 3,
        border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
        display: 'flex',
        flexDirection: 'column',
        transition: 'all 0.3s ease',
        '&:hover': {
          boxShadow: theme.shadows[8],
        },
      }}
    >
      <CardHeader
        avatar={
          IconComponent ? (
            <Box
              sx={{
                p: 1,
                borderRadius: 2,
                backgroundColor: alpha(theme.palette.primary.main, 0.1),
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <IconComponent sx={{ color: theme.palette.primary.main, fontSize: 20 }} />
            </Box>
          ) : null
        }
        title={
          <Typography variant="h6" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
        }
        subheader={
          <Box>
            {unit && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5, fontWeight: 500 }}>
                Unit: {unit}
              </Typography>
            )}
            {stats.min !== null && stats.max !== null && stats.avg !== null && (
              <Stack
                direction="row"
                spacing={1}
                sx={{ mt: 1, flexWrap: 'wrap', alignItems: 'center', gap: 1 }}
              >
                <Chip
                  size="small"
                  label={`Min: ${stats.min.toFixed(1)}${unit || ''}`}
                  variant="outlined"
                  sx={{ fontSize: '12px', height: 28, borderRadius: '999px', minWidth: 90, justifyContent: 'center' }}
                />
                <Chip
                  size="small"
                  label={`Max: ${stats.max.toFixed(1)}${unit || ''}`}
                  variant="outlined"
                  color="primary"
                  sx={{ fontSize: '12px', height: 28, borderRadius: '999px', minWidth: 90, justifyContent: 'center' }}
                />
                <Chip
                  size="small"
                  label={`Avg: ${stats.avg.toFixed(1)}${unit || ''}`}
                  variant="outlined"
                  color="success"
                  sx={{ fontSize: '12px', height: 28, borderRadius: '999px', minWidth: 90, justifyContent: 'center' }}
                />
              </Stack>
            )}
          </Box>
        }
        action={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Tooltip title={smViewEnabled ? "Hide SM-level view" : "Show SM-level profiling (per-SM breakdown)"} arrow placement="top">
              <span>
                <Button
                  size="small"
                  variant={smViewEnabled ? "contained" : "outlined"}
                  color={smViewEnabled ? "primary" : "default"}
                  onClick={handleToggleSMView}
                  disabled={smLoading}
                  startIcon={smLoading ? <CircularProgress size={14} /> : null}
                  sx={{ 
                    fontSize: '0.75rem',
                    textTransform: 'none',
                    minWidth: 80,
                    height: 28,
                    borderRadius: '8px',
                  }}
                >
                  {smLoading ? 'Profiling...' : 'SM View'}
                </Button>
              </span>
            </Tooltip>
            {description && (
            <Tooltip title={description} arrow placement="top">
              <IconButton size="small" sx={{ borderRadius: 1 }}>
                <InfoIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            )}
          </Box>
        }
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ flex: 1, pt: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <Box
          sx={{
            flex: 1,
            overflowX: 'auto',
            overflowY: 'hidden',
            '&::-webkit-scrollbar': {
              height: 8,
            },
            '&::-webkit-scrollbar-track': {
              backgroundColor: alpha(theme.palette.divider, 0.1),
              borderRadius: '4px',
            },
            '&::-webkit-scrollbar-thumb': {
              backgroundColor: alpha(theme.palette.text.secondary, 0.3),
              borderRadius: '4px',
              '&:hover': {
                backgroundColor: alpha(theme.palette.text.secondary, 0.5),
              },
            },
          }}
        >
          <Box sx={{ width: chartWidth, height: 320 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ top: 12, right: 20, bottom: 12, left: 8 }}>
                <defs>
                  {isTokenMetric ? (
                    // Single gradient for token metrics
                    <linearGradient key="gradient-token" id="gradient-token" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={theme.palette.primary.main} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={theme.palette.primary.main} stopOpacity={0.05} />
                    </linearGradient>
                  ) : (
                    // Per-GPU gradients
                    gpuIds.map((id, index) => {
                      const colors = getGradientColors(COLOR_PALETTE[index % COLOR_PALETTE.length], index);
                      return (
                        <linearGradient key={`gradient-${id}`} id={`gradient-${id}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={colors.start} stopOpacity={0.3} />
                          <stop offset="95%" stopColor={colors.end} stopOpacity={0.05} />
                        </linearGradient>
                      );
                    })
                  )}
                </defs>
                <CartesianGrid 
                  strokeDasharray="3 3" 
                  stroke={alpha(theme.palette.divider, 0.3)}
                  vertical={false}
                />
                <XAxis
                  dataKey="timeLabel"
                  minTickGap={30}
                  tick={{ fontSize: 12, fill: theme.palette.text.secondary }}
                  stroke={theme.palette.text.secondary}
                  axisLine={{ stroke: alpha(theme.palette.divider, 0.5) }}
                  tickFormatter={(value, index) => {
                    // Find the corresponding data point
                    const dataPoint = data[index];
                    if (!dataPoint || !dataPoint.epoch) return value;
                    
                    const date = new Date(dataPoint.epoch);
                    if (isNaN(date.getTime())) return value;
                    
                    // Format based on time range
                    switch (timeRange) {
                      case 'minute':
                        // Show seconds: SS
                        return `${date.getSeconds()}s`;
                      case 'hour':
                        // Show minutes: MM:SS
                        return `${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`;
                      case 'day':
                        // Show hours: HH:MM
                        return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
                      default:
                        // Show full time for 'all'
                        return date.toLocaleTimeString();
                    }
                  }}
                />
                <YAxis
                  domain={domain || ['auto', 'auto']}
                  tick={{ fontSize: 12, fill: theme.palette.text.secondary }}
                  stroke={theme.palette.text.secondary}
                  axisLine={{ stroke: alpha(theme.palette.divider, 0.5) }}
                  label={{ value: unit || '', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: theme.palette.text.secondary } }}
                />
                {thresholds && (
                  <>
                    <ReferenceLine
                      y={thresholds.top}
                      stroke={theme.palette.error.main}
                      strokeDasharray="5 5"
                      strokeWidth={1.5}
                      label={{ value: `High: ${thresholds.top.toFixed(1)}${unit || ''}`, position: 'topRight', fill: theme.palette.error.main, fontSize: 10 }}
                    />
                    <ReferenceLine
                      y={thresholds.bottom}
                      stroke={theme.palette.success.main}
                      strokeDasharray="5 5"
                      strokeWidth={1.5}
                      label={{ value: `Low: ${thresholds.bottom.toFixed(1)}${unit || ''}`, position: 'bottomRight', fill: theme.palette.success.main, fontSize: 10 }}
                    />
                  </>
                )}
                <RechartsTooltip
                  contentStyle={{
                    backgroundColor: theme.palette.background.paper,
                    border: `1px solid ${alpha(theme.palette.divider, 0.2)}`,
                    borderRadius: 8,
                    boxShadow: theme.shadows[4],
                    padding: '8px 12px',
                  }}
                  labelStyle={{
                    color: theme.palette.text.primary,
                    fontWeight: 600,
                    marginBottom: 4,
                  }}
                  itemStyle={{
                    color: theme.palette.text.secondary,
                    padding: '2px 0',
                  }}
                  cursor={{ stroke: alpha(theme.palette.primary.main, 0.3), strokeWidth: 1 }}
                />
                <Legend
                  wrapperStyle={{ paddingTop: 8 }}
                  iconType="line"
                  iconSize={12}
                />
                {isTokenMetric ? (
                  // Token metrics are application-level - show as single line
                  <Area
                    key="token-metric"
                    type="monotone"
                    dataKey={metricKey}
                    name={title}
                    stroke={theme.palette.primary.main}
                    fill={`url(#gradient-token)`}
                    strokeWidth={2.5}
                    fillOpacity={1}
                    connectNulls
                    isAnimationActive={true}
                    animationDuration={300}
                    activeDot={{ r: 5, fill: theme.palette.primary.main, strokeWidth: 2, stroke: theme.palette.background.paper }}
                  />
                ) : (
                  // GPU metrics - show per-GPU
                  gpuIds.map((id, index) => {
                    const colors = getGradientColors(COLOR_PALETTE[index % COLOR_PALETTE.length], index);
                    return (
                      <Area
                        key={`gpu-${id}`}
                    type="monotone"
                    dataKey={`gpu_${id}_${metricKey}`}
                    name={`GPU ${id}`}
                        stroke={colors.start}
                        fill={`url(#gradient-${id})`}
                    strokeWidth={2.5}
                        fillOpacity={1}
                    connectNulls
                        isAnimationActive={true}
                        animationDuration={300}
                        activeDot={{ r: 5, fill: colors.start, strokeWidth: 2, stroke: theme.palette.background.paper }}
                  />
                    );
                  })
                )}
              </AreaChart>
            </ResponsiveContainer>
          </Box>
        </Box>
      </CardContent>
      
      {/* SM View Section - Only shown when toggle is ON */}
      {smViewEnabled && (
        <CardContent 
          sx={{ 
            pt: 0, 
            borderTop: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
            mt: 1,
          }}
        >
          {smLoading && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 3 }}>
              <CircularProgress size={24} />
              <Typography variant="body2" color="text.secondary">
                Running Nsight Compute profiling to collect per-SM metrics...
              </Typography>
            </Box>
          )}
          
          {smError && (
            <Alert 
              severity="warning" 
              sx={{ mb: 2, borderRadius: 2 }} 
              onClose={() => setSmError('')}
            >
              {smError}
            </Alert>
          )}
          
          {smData && !smLoading && (
            <SMMetricsOverlay
              gpuData={data}
              smData={smData}
              unit={unit}
              domain={domain}
            />
          )}
        </CardContent>
      )}
      
      <CardContent sx={{ pt: 0, pb: 2 }}>
        <AIInsightsBox
          metricName={title}
          metricKey={metricKey}
          unit={unit}
          data={data}
          gpuIds={gpuIds}
        />
      </CardContent>
    </Card>
  );
};

const TelemetryHistory = () => {
  const [allRuns, setAllRuns] = useState([]);
  const [runsWithNoData, setRunsWithNoData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [cleanupDialogOpen, setCleanupDialogOpen] = useState(false);
  const [cleanupInProgress, setCleanupInProgress] = useState(false);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runChartData, setRunChartData] = useState({ data: [], gpuIds: [] });
  const [runChartLoading, setRunChartLoading] = useState(false);
  const [markCompletedDialogOpen, setMarkCompletedDialogOpen] = useState(false);
  const [markCompletedInProgress, setMarkCompletedInProgress] = useState(false);
  const [timeRange, setTimeRange] = useState('all'); // 'all', 'minute', 'hour', 'day'

  // Metric visibility toggles with localStorage persistence
  const [metricToggles, setMetricToggles] = useState(() => {
    try {
      const stored = localStorage.getItem('telemetry_history_metric_toggles');
      if (stored) {
        return JSON.parse(stored);
      }
    } catch (e) {
      console.warn('Failed to load metric toggles from localStorage', e);
    }
    // Default: all metrics visible
    const defaultToggles = {};
    METRIC_DEFINITIONS.forEach((metric) => {
      defaultToggles[metric.id] = true;
    });
    return defaultToggles;
  });

  const handleToggleMetric = useCallback((metricId) => {
    setMetricToggles((prev) => {
      const newToggles = { ...prev, [metricId]: !prev[metricId] };
      try {
        localStorage.setItem('telemetry_history_metric_toggles', JSON.stringify(newToggles));
      } catch (e) {
        console.warn('Failed to save metric toggles to localStorage', e);
      }
      return newToggles;
    });
  }, []);

  const handleShowAllMetrics = useCallback(() => {
    const allVisible = {};
    METRIC_DEFINITIONS.forEach((metric) => {
      allVisible[metric.id] = true;
    });
    setMetricToggles(allVisible);
    try {
      localStorage.setItem('telemetry_history_metric_toggles', JSON.stringify(allVisible));
    } catch (e) {
      console.warn('Failed to save metric toggles to localStorage', e);
    }
  }, []);

  const handleHideAllMetrics = useCallback(() => {
    const allHidden = {};
    METRIC_DEFINITIONS.forEach((metric) => {
      allHidden[metric.id] = false;
    });
    setMetricToggles(allHidden);
    try {
      localStorage.setItem('telemetry_history_metric_toggles', JSON.stringify(allHidden));
    } catch (e) {
      console.warn('Failed to save metric toggles to localStorage', e);
    }
  }, []);

  const fetchAllRuns = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiService.listAllTelemetryRuns({ limit: 200 });
      console.log('✅ TelemetryHistory: Loaded runs', { count: response?.runs?.length || 0, runs: response?.runs });
      setAllRuns(response?.runs || []);
      if (!response?.runs || response.runs.length === 0) {
        console.warn('⚠️ TelemetryHistory: No runs returned from API. Check if user is authenticated and has runs.');
      }
    } catch (err) {
      console.error('❌ TelemetryHistory: Failed to load telemetry runs', err);
      console.error('❌ Error details:', {
        status: err.response?.status,
        statusText: err.response?.statusText,
        data: err.response?.data,
        message: err.message,
      });
      setError(err?.response?.data?.detail || err?.message || 'Failed to load telemetry runs. Please check your authentication.');
      // Don't set empty array on error - keep previous data if available
      // setAllRuns([]); // Removed - let user see previous data if request fails
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchRunsWithNoData = useCallback(async () => {
    setError('');
    try {
      const response = await apiService.listRunsWithNoData();
      setRunsWithNoData(response?.runs || []);
    } catch (err) {
      console.error('Failed to load runs with no data', err);
      setError(err?.message || 'Failed to identify runs with no data');
    }
  }, []);

  useEffect(() => {
    fetchAllRuns();
    fetchRunsWithNoData();
  }, [fetchAllRuns, fetchRunsWithNoData]);

  const handleRefresh = useCallback(() => {
    fetchAllRuns();
    fetchRunsWithNoData();
  }, [fetchAllRuns, fetchRunsWithNoData]);

  const handleCleanupDialogOpen = useCallback(() => {
    setCleanupDialogOpen(true);
  }, []);

  const handleCleanupDialogClose = useCallback(() => {
    setCleanupDialogOpen(false);
  }, []);

  const handleCleanupConfirm = useCallback(async () => {
    setCleanupInProgress(true);
    setError('');
    setMessage('');
    try {
      const result = await apiService.cleanupRunsWithNoData();
      setMessage(result.message || `Deleted ${result.deleted_count} runs with no data`);
      setCleanupDialogOpen(false);
      // Refresh the lists
      fetchAllRuns();
      fetchRunsWithNoData();
    } catch (err) {
      console.error('Failed to cleanup runs', err);
      setError(err?.response?.data?.detail || err?.message || 'Failed to cleanup runs');
    } finally {
      setCleanupInProgress(false);
    }
  }, [fetchAllRuns, fetchRunsWithNoData]);

  const handleRunSelect = useCallback(async (run, range = null) => {
    setSelectedRun(run);
    setRunChartData({ data: [], gpuIds: [] });
    if (!run) return;

    const selectedRange = range || timeRange;
    setRunChartLoading(true);
    try {
      // Calculate time range
      const startTime = telemetryUtils.parseTimestamp(run.start_time);
      const endTime = run.end_time ? telemetryUtils.parseTimestamp(run.end_time) : new Date();
      
      let queryParams = {};
      
      if (selectedRange !== 'all' && startTime) {
        let rangeStart = new Date(startTime);
        const now = endTime || new Date();
        
        switch (selectedRange) {
          case 'minute':
            rangeStart = new Date(now.getTime() - 60 * 1000); // Last minute
            break;
          case 'hour':
            rangeStart = new Date(now.getTime() - 60 * 60 * 1000); // Last hour
            break;
          case 'day':
            rangeStart = new Date(now.getTime() - 24 * 60 * 60 * 1000); // Last day
            break;
        }
        
        // Ensure we don't go before run start
        if (rangeStart < startTime) {
          rangeStart = startTime;
        }
        
        queryParams.start_time = rangeStart.toISOString();
        queryParams.end_time = (endTime || new Date()).toISOString();
      }
      
      // Fetch all data for the selected range (no limit for full range)
      const response = await apiService.getTelemetryMetrics(run.run_id, {
        ...queryParams,
        limit: selectedRange === 'all' ? 10000 : undefined, // Higher limit for 'all', no limit for time ranges
      });
      const samples = response?.metrics || [];
      const transformed = transformSamplesToSeries(samples, null);
      setRunChartData(transformed);
    } catch (err) {
      console.error('Failed to load run metrics', err);
      setError(err?.message || 'Failed to load run metrics');
    } finally {
      setRunChartLoading(false);
    }
  }, [timeRange]);

  const handleCloseRunDetail = useCallback(() => {
    setSelectedRun(null);
    setRunChartData({ data: [], gpuIds: [] });
  }, []);

  const handleMarkCompletedDialogOpen = useCallback(() => {
    setMarkCompletedDialogOpen(true);
  }, []);

  const handleMarkCompletedDialogClose = useCallback(() => {
    setMarkCompletedDialogOpen(false);
  }, []);

  const handleMarkCompletedConfirm = useCallback(async () => {
    setMarkCompletedInProgress(true);
    setError('');
    setMessage('');
    try {
      const result = await apiService.bulkUpdateRunsStatus('completed');
      setMessage(result.message || `Updated ${result.updated_count} runs to completed`);
      setMarkCompletedDialogOpen(false);
      // Refresh the lists
      fetchAllRuns();
      fetchRunsWithNoData();
    } catch (err) {
      console.error('Failed to mark runs as completed', err);
      setError(err?.response?.data?.detail || err?.message || 'Failed to mark runs as completed');
    } finally {
      setMarkCompletedInProgress(false);
    }
  }, [fetchAllRuns, fetchRunsWithNoData]);

  const getStatusColor = (status) => {
    switch (status?.toLowerCase()) {
      case 'active':
        return 'success';
      case 'completed':
        return 'default';
      case 'failed':
        return 'error';
      default:
        return 'default';
    }
  };

  const getStatusIcon = (status) => {
    switch (status?.toLowerCase()) {
      case 'active':
        return <CheckCircleIcon fontSize="small" />;
      case 'completed':
        return <CheckCircleIcon fontSize="small" />;
      case 'failed':
        return <ErrorIcon fontSize="small" />;
      default:
        return null;
    }
  };

  const isRunWithNoData = (runId) => {
    return runsWithNoData.some((run) => run.run_id === runId);
  };

  const formatDuration = (startTime, endTime) => {
    if (!startTime) return '—';
    
    const start = telemetryUtils.parseTimestamp(startTime);
    if (!start) return '—';
    
    if (!endTime) {
      // Calculate from start to now
      const now = new Date();
      const durationMs = now - start;
      const minutes = Math.floor(durationMs / 60000);
      return `${minutes}m (ongoing)`;
    }
    
    const end = telemetryUtils.parseTimestamp(endTime);
    if (!end) return '—';
    
    const durationMs = end - start;
    const minutes = Math.floor(durationMs / 60000);
    return `${minutes}m`;
  };

  const formatDateTime = (value) => {
    const date = telemetryUtils.parseTimestamp(value);
    if (!date) return '—';
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  // Group runs by instance_id
  const runsByInstance = useMemo(() => {
    const noDataRunIds = new Set(runsWithNoData.map((r) => r.run_id));
    const grouped = {};
    allRuns.forEach((run) => {
      const instanceId = run.instance_id || 'unknown';
      const tags = run.tags || {};
      const provider = run.provider || tags.provider || tags.cloud_provider || null;
      const instanceName = tags.instance_name || tags.name || null;
      const region = tags.region || tags.zone || tags.location || null;
      const ipAddress = tags.ip || tags.public_ip || tags.ip_address || null;
      const sshUser = tags.ssh_user || tags.user || null;
      const projectId = tags.project_id || tags.project || null;
      if (!grouped[instanceId]) {
        grouped[instanceId] = {
          instanceId,
          gpuModel: run.gpu_model,
          gpuCount: run.gpu_count,
          provider,
          instanceName,
          region,
          ipAddress,
          sshUser,
          projectId,
          runs: [],
          totalRuns: 0,
          completedRuns: 0,
          activeRuns: 0,
          runsWithNoData: 0,
        };
      } else {
        // Backfill metadata from newer runs if missing
        if (!grouped[instanceId].provider && provider) grouped[instanceId].provider = provider;
        if (!grouped[instanceId].instanceName && instanceName) grouped[instanceId].instanceName = instanceName;
        if (!grouped[instanceId].region && region) grouped[instanceId].region = region;
        if (!grouped[instanceId].ipAddress && ipAddress) grouped[instanceId].ipAddress = ipAddress;
        if (!grouped[instanceId].sshUser && sshUser) grouped[instanceId].sshUser = sshUser;
        if (!grouped[instanceId].projectId && projectId) grouped[instanceId].projectId = projectId;
      }
      grouped[instanceId].runs.push(run);
      grouped[instanceId].totalRuns++;
      if (run.status === 'completed') {
        grouped[instanceId].completedRuns++;
      }
      if (run.status === 'active') {
        grouped[instanceId].activeRuns++;
      }
      if (noDataRunIds.has(run.run_id)) {
        grouped[instanceId].runsWithNoData++;
      }
    });
    // Sort runs within each instance by start_time (newest first)
    Object.values(grouped).forEach((instance) => {
      instance.runs.sort((a, b) => {
        const timeA = telemetryUtils.parseTimestamp(a.start_time)?.getTime() || 0;
        const timeB = telemetryUtils.parseTimestamp(b.start_time)?.getTime() || 0;
        return timeB - timeA;
      });
    });
    // Sort instances by total runs (most active first)
    return Object.values(grouped).sort((a, b) => b.totalRuns - a.totalRuns);
  }, [allRuns, runsWithNoData]);

  return (
    <Box sx={{ p: 4, maxWidth: '1920px', mx: 'auto' }}>
      <Stack spacing={4}>
        {/* Header */}
        <Box>
          <Typography variant="h1" sx={{ mb: 1.5, fontWeight: 800, fontSize: '3rem' }}>
            Telemetry History
          </Typography>
        </Box>

        {/* Messages */}
        {message && <Alert severity="success" onClose={() => setMessage('')}>{message}</Alert>}
        {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}

        {/* Summary Cards */}
        <Grid container spacing={3}>
          <Grid item xs={12} md={4}>
            <Card variant="outlined" sx={{ borderRadius: 2.5, '&:hover': { boxShadow: 2, transition: 'box-shadow 0.2s ease' } }}>
              <CardContent sx={{ p: 3 }}>
                <Stack direction="row" alignItems="center" spacing={2.5}>
                  <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: 'rgba(25, 118, 210, 0.08)' }}>
                    <DataUsageIcon color="primary" sx={{ fontSize: '2.5rem' }} />
                  </Box>
                  <Box>
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 0.5, fontSize: '2.25rem' }}>{allRuns.length}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 500 }}>
                      Total Runs
                    </Typography>
                  </Box>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card variant="outlined" sx={{ borderRadius: 2.5, '&:hover': { boxShadow: 2, transition: 'box-shadow 0.2s ease' } }}>
              <CardContent sx={{ p: 3 }}>
                <Stack direction="row" alignItems="center" spacing={2.5}>
                  <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: 'rgba(76, 175, 80, 0.08)' }}>
                    <CheckCircleIcon color="success" sx={{ fontSize: '2.5rem' }} />
                  </Box>
                  <Box>
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 0.5, fontSize: '2.25rem' }}>
                      {allRuns.filter((r) => r.status === 'completed').length}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 500 }}>
                      Completed Runs
                    </Typography>
                  </Box>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card variant="outlined" sx={{ borderRadius: 2.5, '&:hover': { boxShadow: 2, transition: 'box-shadow 0.2s ease' } }}>
              <CardContent sx={{ p: 3 }}>
                <Stack direction="row" alignItems="center" spacing={2.5}>
                  <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: 'rgba(255, 152, 0, 0.08)' }}>
                    <WarningIcon color="warning" sx={{ fontSize: '2.5rem' }} />
                  </Box>
                  <Box>
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 0.5, fontSize: '2.25rem' }}>{runsWithNoData.length}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 500 }}>
                      Runs with No Data
                    </Typography>
                  </Box>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {/* Actions */}
        <Card variant="outlined" sx={{ borderRadius: 2.5 }}>
          <CardContent sx={{ p: 3 }}>
            <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
              <Button
                variant="contained"
                color="primary"
                startIcon={<ReplayIcon />}
                onClick={handleRefresh}
                disabled={loading}
                sx={{ borderRadius: 2, px: 3, py: 1.25, fontWeight: 500 }}
              >
                Refresh
              </Button>
              <Button
                variant="contained"
                color="success"
                startIcon={<CheckCircleIcon />}
                onClick={handleMarkCompletedDialogOpen}
                disabled={allRuns.length === 0 || loading}
                sx={{ borderRadius: 2, px: 3, py: 1.25, fontWeight: 500 }}
              >
                Mark All as Completed
              </Button>
              <Button
                variant="outlined"
                color="error"
                startIcon={<DeleteIcon />}
                onClick={handleCleanupDialogOpen}
                disabled={runsWithNoData.length === 0}
                sx={{ borderRadius: 2, px: 3, py: 1.25, fontWeight: 500 }}
              >
                Clean Up Runs with No Data ({runsWithNoData.length})
              </Button>
            </Stack>
          </CardContent>
        </Card>

        <Divider />

        {/* Instances with Runs */}
        <Card variant="outlined" sx={{ borderRadius: 2.5 }}>
          <CardHeader
            title={<Typography variant="h6" sx={{ fontWeight: 600 }}>Telemetry Runs by Instance</Typography>}
            subheader={`${runsByInstance.length} instances • ${allRuns.length} total runs`}
            sx={{ pb: 2 }}
          />
          <CardContent sx={{ pt: 0 }}>
            {loading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                <CircularProgress />
              </Box>
            ) : runsByInstance.length === 0 ? (
              <Alert severity="info">No telemetry runs found.</Alert>
            ) : (
              <Stack spacing={2}>
                {runsByInstance.map((instance) => (
                  <Accordion key={instance.instanceId} defaultExpanded={false} sx={{ borderRadius: '8px !important', '&:before': { display: 'none' } }}>
                    <AccordionSummary
                      expandIcon={<ExpandMoreIcon />}
                      sx={{
                        py: 1.5,
                        '&:hover': {
                          backgroundColor: 'rgba(0, 0, 0, 0.02)',
                        },
                      }}
                    >
                      <Stack
                        direction="row"
                        spacing={2}
                        alignItems="center"
                        sx={{ width: '100%', pr: 2 }}
                      >
                        <CloudIcon color="primary" />
                        <Box sx={{ flexGrow: 1 }}>
                          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                            {instance.instanceId}
                          </Typography>
                          <Stack direction="row" spacing={1} sx={{ mt: 0.5, flexWrap: 'wrap' }}>
                            {instance.instanceName && (
                              <Chip
                                label={instance.instanceName}
                                size="small"
                                variant="outlined"
                                sx={{ fontSize: '0.7rem', height: 20 }}
                              />
                            )}
                            {instance.provider && (
                              <Chip
                                label={instance.provider}
                                size="small"
                                variant="outlined"
                                sx={{ fontSize: '0.7rem', height: 20 }}
                              />
                            )}
                            {instance.region && (
                              <Chip
                                label={instance.region}
                                size="small"
                                variant="outlined"
                                sx={{ fontSize: '0.7rem', height: 20 }}
                              />
                            )}
                            {instance.ipAddress && (
                              <Chip
                                label={instance.ipAddress}
                                size="small"
                                variant="outlined"
                                sx={{ fontSize: '0.7rem', height: 20 }}
                              />
                            )}
                            {instance.sshUser && (
                              <Chip
                                label={`ssh: ${instance.sshUser}`}
                                size="small"
                                variant="outlined"
                                sx={{ fontSize: '0.7rem', height: 20 }}
                              />
                            )}
                            {instance.projectId && (
                              <Chip
                                label={`project: ${instance.projectId}`}
                                size="small"
                                variant="outlined"
                                sx={{ fontSize: '0.7rem', height: 20 }}
                              />
                            )}
                            {instance.runs?.length > 0 && (
                              <>
                                <Chip
                                  label={`last: ${formatDateTime(instance.runs[0].start_time)}`}
                                  size="small"
                                  variant="outlined"
                                  sx={{ fontSize: '0.7rem', height: 20 }}
                                />
                                <Chip
                                  label={`status: ${instance.runs[0].status}`}
                                  size="small"
                                  variant="outlined"
                                  sx={{ fontSize: '0.7rem', height: 20 }}
                                />
                              </>
                            )}
                            {instance.gpuModel && (
                              <Chip
                                label={instance.gpuModel}
                                size="small"
                                variant="outlined"
                                sx={{ fontSize: '0.7rem', height: 20 }}
                              />
                            )}
                            {instance.gpuCount && (
                              <Chip
                                label={`${instance.gpuCount} GPU${instance.gpuCount > 1 ? 's' : ''}`}
                                size="small"
                                variant="outlined"
                                sx={{ fontSize: '0.7rem', height: 20 }}
                              />
                            )}
                          </Stack>
                        </Box>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Tooltip title="Total runs">
                            <Chip
                              label={`${instance.totalRuns} run${instance.totalRuns !== 1 ? 's' : ''}`}
                              size="small"
                              color="primary"
                              variant="outlined"
                            />
                          </Tooltip>
                          {instance.activeRuns > 0 && (
                            <Tooltip title="Active runs">
                              <Chip
                                label={`${instance.activeRuns} active`}
                                size="small"
                                color="success"
                                variant="outlined"
                              />
                            </Tooltip>
                          )}
                          {instance.completedRuns > 0 && (
                            <Tooltip title="Completed runs">
                              <Chip
                                label={`${instance.completedRuns} completed`}
                                size="small"
                                color="default"
                                variant="outlined"
                              />
                            </Tooltip>
                          )}
                          {instance.runsWithNoData > 0 && (
                            <Tooltip title="Runs with no data">
                              <Chip
                                icon={<WarningIcon />}
                                label={instance.runsWithNoData}
                                size="small"
                                color="warning"
                              />
                            </Tooltip>
                          )}
                        </Stack>
                      </Stack>
                    </AccordionSummary>
                    <AccordionDetails sx={{ p: 0 }}>
                      <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
                        <Table size="medium">
                          <TableHead>
                            <TableRow sx={{ bgcolor: '#2d2d2a' }}>
                              <TableCell sx={{ fontWeight: 600, py: 2 }}>Run ID</TableCell>
                              <TableCell sx={{ fontWeight: 600, py: 2 }}>Status</TableCell>
                              <TableCell sx={{ fontWeight: 600, py: 2 }}>Start Time</TableCell>
                              <TableCell sx={{ fontWeight: 600, py: 2 }}>End Time</TableCell>
                              <TableCell sx={{ fontWeight: 600, py: 2 }}>Duration</TableCell>
                              <TableCell sx={{ fontWeight: 600, py: 2 }}>Data Status</TableCell>
                              <TableCell align="right" sx={{ fontWeight: 600, py: 2 }}>Avg Util</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {instance.runs.map((run) => {
                              const hasNoData = isRunWithNoData(run.run_id);
                              return (
                                <TableRow
                                  key={run.run_id}
                                  hover
                                  onClick={() => handleRunSelect(run)}
                                  sx={{
                                    backgroundColor: hasNoData
                                      ? 'rgba(255, 152, 0, 0.08)'
                                      : 'inherit',
                                    cursor: 'pointer',
                                    '&:hover': {
                                      backgroundColor: hasNoData
                                        ? 'rgba(255, 152, 0, 0.15)'
                                        : 'rgba(0, 0, 0, 0.04)',
                                    },
                                  }}
                                >
                                  <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                                    {run.run_id}
                                  </TableCell>
                                  <TableCell>
                                    <Chip
                                      icon={getStatusIcon(run.status)}
                                      label={run.status}
                                      color={getStatusColor(run.status)}
                                      size="small"
                                    />
                                  </TableCell>
                                  <TableCell>
                                    {telemetryUtils.parseTimestamp(run.start_time)?.toLocaleString() ||
                                      '—'}
                                  </TableCell>
                                  <TableCell>
                                    {run.end_time
                                      ? telemetryUtils.parseTimestamp(run.end_time)?.toLocaleString()
                                      : '—'}
                                  </TableCell>
                                  <TableCell>{formatDuration(run.start_time, run.end_time)}</TableCell>
                                  <TableCell>
                                    {hasNoData ? (
                                      <Tooltip title="This run has no metric data">
                                        <Chip
                                          icon={<WarningIcon />}
                                          label="No Data"
                                          color="warning"
                                          size="small"
                                        />
                                      </Tooltip>
                                    ) : (
                                      <Chip
                                        icon={<CheckCircleIcon />}
                                        label="Has Data"
                                        color="success"
                                        size="small"
                                        variant="outlined"
                                      />
                                    )}
                                  </TableCell>
                                  <TableCell align="right">
                                    {run.summary?.avg_gpu_utilization != null
                                      ? `${run.summary.avg_gpu_utilization.toFixed(1)}%`
                                      : '—'}
                                  </TableCell>
                                </TableRow>
                              );
                            })}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    </AccordionDetails>
                  </Accordion>
                ))}
              </Stack>
            )}
          </CardContent>
        </Card>

        {/* Run Detail View */}
        {selectedRun && (
          <Card variant="outlined" sx={{ borderRadius: 2.5 }}>
            <CardHeader
              sx={{ pb: 2 }}
              title={
                <Stack direction="row" spacing={2} alignItems="center">
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>Run Details</Typography>
                  <Chip
                    icon={getStatusIcon(selectedRun.status)}
                    label={selectedRun.status}
                    color={getStatusColor(selectedRun.status)}
                    size="small"
                  />
                  {isRunWithNoData(selectedRun.run_id) && (
                    <Chip
                      icon={<WarningIcon />}
                      label="No Data"
                      color="warning"
                      size="small"
                    />
                  )}
                </Stack>
              }
              subheader={
                <Typography variant="body2" sx={{ fontFamily: 'monospace', mt: 1 }}>
                  {selectedRun.run_id}
                </Typography>
              }
              action={
                <IconButton onClick={handleCloseRunDetail} size="small">
                  <CloseIcon />
                </IconButton>
              }
            />
            <CardContent sx={{ pt: 0, pr: { xs: 2, md: 3 } }}>
              <Stack spacing={4}>
                {/* Run Summary Info */}
                <Grid container spacing={3}>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      Instance ID
                    </Typography>
                    <Typography variant="body1">{selectedRun.instance_id}</Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      GPU Model
                    </Typography>
                    <Typography variant="body1">{selectedRun.gpu_model || '—'}</Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      GPU Count
                    </Typography>
                    <Typography variant="body1">
                      {selectedRun.gpu_count != null ? selectedRun.gpu_count : '—'}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      Provider
                    </Typography>
                    <Typography variant="body1">
                      {selectedRun.provider || selectedRun.tags?.provider || '—'}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      Start Time
                    </Typography>
                    <Typography variant="body1">
                      {telemetryUtils.parseTimestamp(selectedRun.start_time)?.toLocaleString() ||
                        '—'}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      End Time
                    </Typography>
                    <Typography variant="body1">
                      {selectedRun.end_time
                        ? telemetryUtils.parseTimestamp(selectedRun.end_time)?.toLocaleString()
                        : '—'}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      Duration
                    </Typography>
                    <Typography variant="body1">
                      {formatDuration(selectedRun.start_time, selectedRun.end_time)}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      Avg GPU Utilization
                    </Typography>
                    <Typography variant="body1">
                      {selectedRun.summary?.avg_gpu_utilization != null
                        ? `${selectedRun.summary.avg_gpu_utilization.toFixed(1)}%`
                        : '—'}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      Max Temperature
                    </Typography>
                    <Typography variant="body1">
                      {selectedRun.summary?.max_temperature != null
                        ? `${selectedRun.summary.max_temperature.toFixed(1)}°C`
                        : '—'}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Typography variant="subtitle2" color="text.secondary">
                      Energy Used
                    </Typography>
                    <Typography variant="body1">
                      {selectedRun.summary?.total_energy_wh != null
                        ? `${(selectedRun.summary.total_energy_wh / 1000).toFixed(2)} kWh`
                        : '—'}
                    </Typography>
                  </Grid>
                </Grid>

                <Divider />

                {/* Charts */}
                {runChartLoading ? (
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                    <CircularProgress />
                  </Box>
                ) : runChartData.data.length === 0 ? (
                  <Alert severity="info" sx={{ borderRadius: 2 }}>
                    No metric data available for this run. This run may have no data collected.
                  </Alert>
                ) : (
                  <>
                    <Card 
                      sx={{ 
                        mb: 3, 
                        borderRadius: '8px',
                        border: `1px solid ${alpha('#000', 0.1)}`,
                      }}
                    >
                      <CardContent sx={{ p: 3 }}>
                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'flex-start', sm: 'center' }} justifyContent="space-between">
                          <Box>
                            <Typography variant="h6" sx={{ fontWeight: 600, mb: 0.5 }}>
                              Historical Metrics
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              View past performance metrics for this run
                            </Typography>
                          </Box>
                          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
                            <FormControl size="small" sx={{ minWidth: 120 }}>
                              <InputLabel>Time Range</InputLabel>
                              <Select
                                value={timeRange}
                                label="Time Range"
                                onChange={(e) => {
                                  const newRange = e.target.value;
                                  setTimeRange(newRange);
                                  if (selectedRun) {
                                    handleRunSelect(selectedRun, newRange);
                                  }
                                }}
                                sx={{ borderRadius: 2 }}
                              >
                                <MenuItem value="all">All Time</MenuItem>
                                <MenuItem value="minute">Last Minute</MenuItem>
                                <MenuItem value="hour">Last Hour</MenuItem>
                                <MenuItem value="day">Last Day</MenuItem>
                              </Select>
                            </FormControl>
                            <Button 
                              size="small" 
                              variant="outlined"
                              onClick={handleShowAllMetrics}
                              sx={{ borderRadius: 2 }}
                            >
                          Show All
                        </Button>
                            <Button 
                              size="small" 
                              variant="outlined"
                              onClick={handleHideAllMetrics}
                              sx={{ borderRadius: 2 }}
                            >
                          Hide All
                        </Button>
                        <FormControl size="small" sx={{ minWidth: 200 }}>
                          <InputLabel>Toggle Metrics</InputLabel>
                          <Select
                            value=""
                            label="Toggle Metrics"
                            onChange={(e) => {
                              const metricId = e.target.value;
                              if (metricId) {
                                handleToggleMetric(metricId);
                                e.target.value = '';
                              }
                            }}
                                sx={{ borderRadius: 2 }}
                          >
                            {METRIC_DEFINITIONS.map((metric) => (
                              <MenuItem key={metric.id} value={metric.id}>
                                <FormControlLabel
                                  control={
                                    <Switch
                                      checked={metricToggles[metric.id] !== false}
                                      size="small"
                                      onChange={() => handleToggleMetric(metric.id)}
                                      onClick={(e) => e.stopPropagation()}
                                    />
                                  }
                                  label={metric.historicalTitle || metric.title}
                                  sx={{ m: 0 }}
                                />
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                          </Stack>
                        </Stack>
                      </CardContent>
                    </Card>
                    <Grid container spacing={3} sx={{ pr: { xs: 0, md: 2 } }}>
                      {METRIC_DEFINITIONS.map((metric) => {
                        if (metricToggles[metric.id] === false) {
                          return null;
                        }
                        return (
                          <Grid item xs={12} md={6} lg={4} key={`run-${selectedRun.run_id}-${metric.id}`}>
                            <MetricChart
                              title={metric.historicalTitle || `Historical ${metric.title}`}
                              metricKey={metric.metricKey}
                              unit={metric.unit}
                              domain={metric.domain}
                              data={runChartData.data}
                              gpuIds={runChartData.gpuIds}
                              icon={metric.icon}
                              description={metric.description}
                              timeRange={timeRange}
                            />
                          </Grid>
                        );
                      })}
                    </Grid>
                  </>
                )}
              </Stack>
            </CardContent>
          </Card>
        )}
      </Stack>

      {/* Mark All Completed Confirmation Dialog */}
      <Dialog
        open={markCompletedDialogOpen}
        onClose={handleMarkCompletedDialogClose}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Mark All Runs as Completed</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to mark <strong>all {allRuns.length} runs</strong> as completed?
          </DialogContentText>
          <DialogContentText sx={{ mt: 2 }}>
            This will update the status of all runs to "completed". This action can be useful for
            cleaning up old runs that are no longer active.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleMarkCompletedDialogClose} disabled={markCompletedInProgress}>
            Cancel
          </Button>
          <Button
            onClick={handleMarkCompletedConfirm}
            color="success"
            variant="contained"
            disabled={markCompletedInProgress}
            startIcon={markCompletedInProgress ? <CircularProgress size={20} /> : <CheckCircleIcon />}
          >
            {markCompletedInProgress ? 'Updating...' : 'Mark All as Completed'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Cleanup Confirmation Dialog */}
      <Dialog
        open={cleanupDialogOpen}
        onClose={handleCleanupDialogClose}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Confirm Cleanup</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to delete <strong>{runsWithNoData.length} runs</strong> that have
            no metric data?
          </DialogContentText>
          <DialogContentText sx={{ mt: 2 }}>
            This action cannot be undone. These runs will be permanently removed from the database.
          </DialogContentText>
          {runsWithNoData.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Runs to be deleted:
              </Typography>
              <Box sx={{ maxHeight: 200, overflow: 'auto', mt: 1 }}>
                {runsWithNoData.slice(0, 10).map((run) => (
                  <Typography
                    key={run.run_id}
                    variant="caption"
                    display="block"
                    sx={{ fontFamily: 'monospace' }}
                  >
                    {run.run_id} ({run.instance_id})
                  </Typography>
                ))}
                {runsWithNoData.length > 10 && (
                  <Typography variant="caption" color="text.secondary">
                    ... and {runsWithNoData.length - 10} more
                  </Typography>
                )}
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCleanupDialogClose} disabled={cleanupInProgress}>
            Cancel
          </Button>
          <Button
            onClick={handleCleanupConfirm}
            color="error"
            variant="contained"
            disabled={cleanupInProgress}
            startIcon={cleanupInProgress ? <CircularProgress size={20} /> : <DeleteIcon />}
          >
            {cleanupInProgress ? 'Deleting...' : 'Delete Runs'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TelemetryHistory;
