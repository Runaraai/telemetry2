import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardActions,
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
  Link,
  MenuItem,
  Paper,
  Select,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Switch,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
  Link as MuiLink,
} from '@mui/material';
import {
  PlayArrow as PlayIcon,
  Stop as StopIcon,
  Replay as ReplayIcon,
  Bolt as BoltIcon,
  Memory as MemoryIcon,
  Whatshot as WhatshotIcon,
  Timeline as TimelineIcon,
  Cloud as CloudIcon,
  Info as InfoIcon,
  WarningAmber as WarningIcon,
  Speed as SpeedIcon,
  AttachMoney as AttachMoneyIcon,
  ContentCopy as CopyIcon,
  OpenInNew as OpenInNewIcon,
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

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

const CodeBlock = React.memo(({ code, onCopy, sx = {} }) => {
  const theme = useTheme();
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    onCopy(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Box
      sx={{
        bgcolor: '#1e1e1e',
        color: '#d4d4d4',
        p: 2.5,
        pr: 6, // Extra padding on right for copy button
        borderRadius: '8px',
        fontFamily: 'monospace',
        fontSize: '0.875rem',
        position: 'relative',
        wordBreak: 'break-all',
        border: `1px solid ${alpha('#3e3e3e', 0.5)}`,
        transition: 'all 0.2s ease',
        '&:hover': {
          borderColor: alpha(theme.palette.primary.main, 0.5),
        },
        ...sx,
      }}
    >
      <code style={{ color: '#d4d4d4', display: 'block', wordBreak: 'break-all' }}>{code}</code>
      <Tooltip title={copied ? 'Copied!' : 'Copy to clipboard'} arrow>
        <IconButton
          size="small"
          onClick={handleCopy}
          sx={{
            position: 'absolute',
            right: 8,
            top: 8,
            color: '#d4d4d4',
            '&:hover': {
              bgcolor: alpha('#3e3e3e', 0.8),
              color: theme.palette.primary.main,
            },
          }}
        >
          <CopyIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Box>
  );
});

CodeBlock.displayName = 'CodeBlock';

const InfoCard = React.memo(({ icon: Icon, title, subtitle, children, color = 'primary', sx = {} }) => {
  const theme = useTheme();
  
  return (
    <Card
      sx={{
        borderRadius: '8px',
        border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
        transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
        '&:hover': {
          boxShadow: theme.shadows[4],
        },
        ...sx,
      }}
    >
      <CardHeader
        avatar={
          <Box
            sx={{
              p: 1.5,
              borderRadius: '8px',
              backgroundColor: alpha(theme.palette[color].main, 0.1),
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon sx={{ color: theme.palette[color].main, fontSize: 24 }} />
          </Box>
        }
        title={
          <Typography variant="h6" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
        }
        subheader={subtitle && (
          <Typography variant="body2" color="text.secondary">
            {subtitle}
          </Typography>
        )}
      />
      {children && <CardContent sx={{ pt: 0 }}>{children}</CardContent>}
    </Card>
  );
});

InfoCard.displayName = 'InfoCard';

const deriveDefaultBackendUrl = () => {
  // If REACT_APP_API_URL is explicitly set (even if empty), use it
  if (process.env.REACT_APP_API_URL !== undefined) {
    // Empty string means use relative URLs (current origin)
    if (process.env.REACT_APP_API_URL === '') {
      return '';
    }
    return process.env.REACT_APP_API_URL;
  }

  if (typeof window !== 'undefined') {
    const origin = window.location.origin;
    // For telemetry deployment, we need a routable URL (not localhost)
    // If accessing via localhost, use the external IP for deployment
    if (origin.includes('localhost') || origin.includes('127.0.0.1')) {
      // Default to hosted API domain that remote instances can reach
      // Fallback to environment variable or empty string for relative URLs
      return process.env.REACT_APP_API_URL || '';
    }
    // Otherwise use the same origin
    return origin;
  }

  // Fallback to environment variable or empty string for relative URLs
  return process.env.REACT_APP_API_URL || '';
};

const DEFAULT_BACKEND_URL = deriveDefaultBackendUrl();
const PREFERRED_POLL_INTERVALS = [1, 2, 5, 10];
const COLOR_PALETTE = [
  '#3DA866',
  '#ef5350',
  '#26a69a',
  '#ffa726',
  '#ab47bc',
  '#66bb6a',
  '#ff7043',
  '#8d6e63',
];
const REALTIME_TARGET_POINTS = 600;
const REALTIME_MAX_POINTS = 2000;

// Downsample large timeseries so Recharts isn't overloaded with points on long sessions
const downsampleTimeSeries = (data, targetPoints = REALTIME_TARGET_POINTS, hardLimit = REALTIME_MAX_POINTS) => {
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

const requestAnimationFrameSafe = (callback) => {
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    return window.requestAnimationFrame(callback);
  }
  return setTimeout(callback, 16);
};

const cancelAnimationFrameSafe = (handle) => {
  if (!handle) return;
  if (typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(handle);
  } else {
    clearTimeout(handle);
  }
};

const decodePem = (value) => {
  if (!value) return '';
  try {
    if (typeof window !== 'undefined' && window.atob) {
      return window.atob(value);
    }
    return value;
  } catch (error) {
    console.warn('Failed to decode PEM base64, returning original string', error);
    return value;
  }
};

const deriveInstanceId = (instance) => {
  if (!instance) return '';
  return (
    instance.id ||
    instance.instanceId ||
    instance.instance_id ||
    instance.name ||
    instance.instanceName ||
    ''
  );
};

const extractGpuInfo = (instance) => {
  const gpuModel =
    instance?.gpuModel ||
    instance?.gpu_model ||
    instance?.instanceType?.gpu_description ||
    instance?.gpuDescription ||
    null;

  const gpuCount =
    instance?.gpu_count ||
    instance?.gpuCount ||
    instance?.instanceType?.specs?.gpus ||
    instance?.instanceType?.resources?.gpus ||
    null;

  return {
    gpuModel,
    gpuCount: gpuCount != null ? Number(gpuCount) : null,
  };
};

const collectStoredCredentials = (providerId) => {
  if (!providerId) {
    return null;
  }
  try {
    const key = `cloudCreds_${providerId}`;
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (error) {
    console.warn('Unable to parse stored credentials', error);
    return null;
  }
};

const transformSamplesToSeries = (samples, maxPoints = 300) => {
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
    existing[`${gpuKey}_power_limit`] =
      sample.power_limit_watts != null ? Number(sample.power_limit_watts) : null;
    existing[`${gpuKey}_power_min`] =
      sample.power_min_limit != null ? Number(sample.power_min_limit) : null;
    existing[`${gpuKey}_power_max`] =
      sample.power_max_limit != null ? Number(sample.power_max_limit) : null;
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
    existing[`${gpuKey}_energy_wh`] =
      sample.total_energy_joules != null ? Number(sample.total_energy_joules) / 3600.0 : null;
    // Token metrics are application-level, not per-GPU - aggregate from any GPU
    // Use the first non-null value from any GPU (they should all be the same)
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
  const trimmed = maxPoints ? sorted.slice(-maxPoints) : sorted;

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
      'Overall GPU utilization from nvidia-smi. Available on all GPUs without profiling mode. This represents the percentage of time the GPU was actively executing kernels.',
  },
  {
    id: 'sm-util',
    metricKey: 'sm_util',
    title: 'Compute Utilization',
    historicalTitle: 'Compute Utilization',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Hardware counter-based Streaming Multiprocessor activity. Requires profiling mode to be enabled. Provides more detailed SM-level insights than standard GPU utilization.',
  },
  {
    id: 'sm-occupancy',
    metricKey: 'sm_occupancy',
    title: 'SM Occupancy',
    historicalTitle: 'Historical SM Occupancy',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description:
      'Average percentage of active warps per SM. Highlights how effectively workloads fill the GPU pipelines.',
  },
  {
    id: 'memory-util',
    metricKey: 'mem_util',
    title: 'Memory Utilization',
    historicalTitle: 'Memory Utilization',
    unit: '%',
    domain: [0, 100],
    icon: MemoryIcon,
    description: 'GPU memory usage as a percentage of total available memory. Shows how much VRAM is allocated.',
  },
  {
    id: 'power-draw',
    metricKey: 'power',
    title: 'Power Draw',
    historicalTitle: 'Power Draw',
    unit: 'Watts',
    icon: BoltIcon,
    description: 'Current power consumption in watts. Useful for monitoring energy efficiency and thermal management.',
  },
  {
    id: 'temperature',
    metricKey: 'temp',
    title: 'Temperature',
    historicalTitle: 'Temperature',
    unit: '°C',
    domain: [0, 120],
    icon: WhatshotIcon,
    description: 'GPU temperature in Celsius. High temperatures may trigger thermal throttling.',
  },
  {
    id: 'hbm-util',
    metricKey: 'hbm_util',
    title: 'HBM Utilization',
    historicalTitle: 'HBM Utilization',
    unit: '%',
    domain: [0, 100],
    icon: MemoryIcon,
    description:
      'Memory bandwidth utilization (DRAM active). Requires profiling mode to be enabled. Shows how effectively the GPU is using its memory bandwidth.',
  },
  {
    id: 'tensor-active',
    metricKey: 'tensor_active',
    title: 'Tensor Core Activity',
    historicalTitle: 'Tensor Core Activity',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description: 'Tensor Core utilization derived from DCGM profiling counters.',
  },
  {
    id: 'fp64-active',
    metricKey: 'fp64_active',
    title: 'FP64 Active',
    historicalTitle: 'FP64 Active',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description: 'Percentage of time FP64 (double-precision) units are active. Requires profiling mode. Relevant for scientific computing.',
  },
  {
    id: 'fp32-active',
    metricKey: 'fp32_active',
    title: 'FP32 Active',
    historicalTitle: 'FP32 Active',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description: 'Single-precision floating point pipeline activity from DCGM profiling metrics.',
  },
  {
    id: 'fp16-active',
    metricKey: 'fp16_active',
    title: 'FP16 / BF16 Pipeline Activity',
    historicalTitle: 'FP16 / BF16 Pipeline Activity',
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
    title: 'NVLink TX Throughput',
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
    id: 'power-limit',
    metricKey: 'power_limit',
    title: 'Power Limit',
    historicalTitle: 'Power Limit',
    unit: 'Watts',
    icon: BoltIcon,
    description: 'Configured power limit per GPU (from DCGM). Compare against actual power draw to identify headroom.',
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
    description: 'Token throughput for LLM inference workloads. Shows the rate at which tokens are being generated by the model.',
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
    id: 'encoder-util',
    metricKey: 'encoder_util',
    title: 'Encoder Utilization',
    historicalTitle: 'Encoder Utilization',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description: 'Video encoder utilization percentage. Shows how much the GPU encoder is being used.',
  },
  {
    id: 'decoder-util',
    metricKey: 'decoder_util',
    title: 'Decoder Utilization',
    historicalTitle: 'Decoder Utilization',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    description: 'Video decoder utilization percentage. Shows how much the GPU decoder is being used.',
  },
  {
    id: 'fan-speed',
    metricKey: 'fan_speed',
    title: 'Fan Speed',
    historicalTitle: 'Fan Speed',
    unit: '%',
    domain: [0, 100],
    icon: WhatshotIcon,
    description: 'GPU fan speed as a percentage (0-100). Higher values indicate more aggressive cooling.',
  },
  {
    id: 'pstate',
    metricKey: 'pstate',
    title: 'Performance State (P-State)',
    historicalTitle: 'Performance State (P-State)',
    unit: '',
    domain: [0, 15],
    icon: BoltIcon,
    description: 'GPU performance state (0-15). 0 is the highest performance state. Lower numbers indicate higher performance.',
  },
  {
    id: 'sm-clock',
    metricKey: 'sm_clock_mhz',
    title: 'SM Clock',
    historicalTitle: 'SM Clock',
    unit: 'MHz',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    description: 'Streaming Multiprocessor clock frequency in MHz. Helps correlate performance and potential throttling.',
  },
  {
    id: 'mem-clock',
    metricKey: 'memory_clock_mhz',
    title: 'Memory Clock',
    historicalTitle: 'Memory Clock',
    unit: 'MHz',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    description: 'HBM/DRAM clock frequency in MHz. Useful to spot memory clock caps or throttling under load.',
  },
  {
    id: 'slowdown-temp',
    metricKey: 'slowdown_temp',
    title: 'Slowdown Temperature',
    historicalTitle: 'Slowdown Temperature',
    unit: '°C',
    domain: [0, 120],
    icon: WhatshotIcon,
    description: 'Temperature threshold at which the GPU will begin to throttle performance to prevent overheating.',
  },
];

const ENTERPRISE_METRIC_IDS = new Set([
  'gpu-util',
  'sm-util',
  'sm-occupancy',
  'memory-util',
]);

const MetricChartComponent = ({ title, metricKey, unit, domain, data, gpuIds, icon: IconComponent, description, activeRun, sshHost, sshUser, sshKey }) => {
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
      { start: '#3DA866', end: '#6ee7b7' },
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
        if (!activeRun || !activeRun.run_id) {
          throw new Error('No active run available - cannot trigger profiling');
        }

        if (!sshHost || !sshKey) {
          throw new Error('SSH credentials not configured. Please configure SSH host and key in the deployment settings.');
        }

        const session = await apiService.triggerSMProfiling({
          run_id: activeRun.run_id,
          gpu_id: gpuIds[0] || 0,
          metric_name: metricKey,
          ssh_host: sshHost,
          ssh_user: sshUser || 'ubuntu',
          ssh_key: sshKey,
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
  }, [smViewEnabled, metricKey, gpuIds, pollForSMResults, activeRun]);

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
          subheader={
            unit ? (
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500 }}>
                Unit: {unit}
              </Typography>
            ) : undefined
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
                    disabled={smLoading || !activeRun}
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
                <IconButton size="small" sx={{ borderRadius: '4px' }}>
                  <InfoIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              )}
            </Box>
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
              No data available yet. Start monitoring to see metrics.
          </Typography>
          </Box>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card 
      sx={{ 
        borderRadius: '8px',
        border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
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
        subheader={
          unit ? (
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500 }}>
              Unit: {unit}
            </Typography>
          ) : undefined
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
                  disabled={smLoading || !activeRun}
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
      <CardContent sx={{ height: 320, pt: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart 
            data={data} 
            margin={{ top: 12, right: 20, bottom: 12, left: 8 }}
          >
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
              minTickGap={24}
              stroke={theme.palette.text.secondary}
              tick={{ fontSize: 12, fill: theme.palette.text.secondary }}
              axisLine={{ stroke: alpha(theme.palette.divider, 0.5) }}
            />
            <YAxis 
              domain={domain || ['auto', 'auto']}
              stroke={theme.palette.text.secondary}
              tick={{ fontSize: 12, fill: theme.palette.text.secondary }}
              axisLine={{ stroke: alpha(theme.palette.divider, 0.5) }}
            />
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
              sx={{ mb: 2, borderRadius: '8px' }} 
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

const MetricChart = React.memo(
  MetricChartComponent,
  (prev, next) =>
    prev.data === next.data &&
    prev.gpuIds === next.gpuIds &&
    prev.metricKey === next.metricKey &&
    prev.activeRun === next.activeRun &&
    prev.sshHost === next.sshHost &&
    prev.sshUser === next.sshUser &&
    prev.sshKey === next.sshKey &&
    prev.title === next.title &&
    prev.unit === next.unit &&
    prev.domain === next.domain &&
    prev.description === next.description &&
    prev.icon === next.icon
);

MetricChart.displayName = 'MetricChart';

const TelemetryTab = ({ instanceData, onNavigateToInstances }) => {
  const theme = useTheme();
  const [instance, setInstance] = useState(instanceData || null);
  const [sshUser, setSshUser] = useState(instanceData?.sshUser || 'ubuntu');
  const [sshHost, setSshHost] = useState(instanceData?.ipAddress || '');
  const [sshKey, setSshKey] = useState(() => decodePem(instanceData?.pemBase64));
  const [pollInterval, setPollInterval] = useState(5);
  const [backendUrl, setBackendUrl] = useState(DEFAULT_BACKEND_URL);
  const [enableProfiling, setEnableProfiling] = useState(false);
  const [showProfilingDialog, setShowProfilingDialog] = useState(false);
  const [activeRun, setActiveRun] = useState(null);
  const [deploymentId, setDeploymentId] = useState(null);
  const [deploymentStatus, setDeploymentStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [agentStatus, setAgentStatus] = useState(null);
  const [agentSuggestedRunId, setAgentSuggestedRunId] = useState(null);
  const [prerequisites, setPrerequisites] = useState([]);
  const [prerequisitesLoading, setPrerequisitesLoading] = useState(false);
  const [historicalLoading, setHistoricalLoading] = useState(false);
  const [historicalChart, setHistoricalChart] = useState({ data: [], gpuIds: [] });
  const [selectedHistoricalRun, setSelectedHistoricalRun] = useState(null);
  const [monitoringState, setMonitoringState] = useState('idle');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [preserveData, setPreserveData] = useState(true);
  const [realtimeChart, setRealtimeChart] = useState({ data: [], gpuIds: [] });
  const [hasProfilingData, setHasProfilingData] = useState(false);
  const [websocketConnectedAt, setWebsocketConnectedAt] = useState(null);
  const [lastDataReceivedAt, setLastDataReceivedAt] = useState(null);
  const [componentStatus, setComponentStatus] = useState(null);
  const [componentStatusLoading, setComponentStatusLoading] = useState(false);
  const [deploymentJobs, setDeploymentJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [queueStats, setQueueStats] = useState(null);
  const [metricView, setMetricView] = useState('enterprise'); // 'enterprise' | 'infra'
  const [activityLog, setActivityLog] = useState([]);
  const [profilingResult, setProfilingResult] = useState(null);
  const [profilingResultRunId, setProfilingResultRunId] = useState(null);
  const [kernelRunLoading, setKernelRunLoading] = useState(false);

  const appendLog = useCallback((level, msg) => {
    const ts = new Date().toLocaleTimeString();
    setActivityLog((prev) => {
      const next = [{ ts, level, msg }, ...prev];
      return next.slice(0, 100);
    });
  }, []);

  // Metric visibility toggles with localStorage persistence
  const [metricToggles, setMetricToggles] = useState(() => {
    try {
      const stored = localStorage.getItem('telemetry_metric_toggles');
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
        localStorage.setItem('telemetry_metric_toggles', JSON.stringify(newToggles));
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
      localStorage.setItem('telemetry_metric_toggles', JSON.stringify(allVisible));
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
      localStorage.setItem('telemetry_metric_toggles', JSON.stringify(allHidden));
    } catch (e) {
      console.warn('Failed to save metric toggles to localStorage', e);
    }
  }, []);

  const metricsToRender = useMemo(() => {
    const base =
      metricView === 'enterprise'
        ? METRIC_DEFINITIONS.filter((m) => ENTERPRISE_METRIC_IDS.has(m.id))
        : METRIC_DEFINITIONS;
    return base.filter((m) => metricToggles[m.id] !== false);
  }, [metricView, metricToggles]);

  const websocketRef = useRef(null);
  const deploymentPollRef = useRef(null);
  const dataTimeoutRef = useRef(null);
  const realtimeBufferRef = useRef([]);
  const realtimeRafRef = useRef(null);
  const fallbackPollRef = useRef(null);

  const instanceId = useMemo(() => deriveInstanceId(instance), [instance]);

  const refreshInstanceCredentials = useCallback(
    (data) => {
      if (!data) return;

      const providerId = data.provider || data.providerId || data.vendorId;
      if (data.pemBase64) {
        setSshKey(decodePem(data.pemBase64));
      } else if (data.sshKey) {
        setSshKey(data.sshKey);
      } else {
        const stored = collectStoredCredentials(providerId);
        if (stored?.pemBase64) {
          setSshKey(decodePem(stored.pemBase64));
        }
      }
      if (data.sshUser) {
        setSshUser(data.sshUser);
      }
      if (data.ipAddress || data.ip) {
        setSshHost(data.ipAddress || data.ip);
      }
    },
    []
  );

  useEffect(() => {
    if (instanceData) {
      setInstance(instanceData);
      refreshInstanceCredentials(instanceData);
      const { gpuModel, gpuCount } = extractGpuInfo(instanceData);
      if (gpuModel) {
        setInstance((prev) => ({ ...prev, gpuModel }));
      }
      if (gpuCount != null) {
        setInstance((prev) => ({ ...prev, gpuCount }));
      }
    }
  }, [instanceData, refreshInstanceCredentials]);

  useEffect(() => {
    return () => {
      if (websocketRef.current) {
        websocketRef.current.close();
      }
      if (deploymentPollRef.current) {
        clearInterval(deploymentPollRef.current);
      }
      if (dataTimeoutRef.current) {
        clearTimeout(dataTimeoutRef.current);
      }
      if (fallbackPollRef.current) {
        clearInterval(fallbackPollRef.current);
        fallbackPollRef.current = null;
      }
      if (realtimeRafRef.current) {
        cancelAnimationFrameSafe(realtimeRafRef.current);
        realtimeRafRef.current = null;
      }
      realtimeBufferRef.current = [];
    };
  }, []);

  const fetchRuns = useCallback(
    async (targetInstanceId = instanceId) => {
      if (!targetInstanceId) {
        setRuns([]);
        return;
      }
      setRunsLoading(true);
      setError('');
      try {
        const response = await apiService.listTelemetryRuns({
          instance_id: targetInstanceId,
          limit: 50,
        });
        const fetchedRuns = response?.runs || [];
        setRuns(fetchedRuns);

        const active = fetchedRuns.find((run) => run.status === 'active');
        if (active) {
          setActiveRun(active);
        }

        // Best-effort: if a provisioning agent is installed, fetch latest heartbeat.
        // This helps explain "no data" cases when the remote Prometheus is sending to a different run_id.
        try {
          const latest = await apiService.getAgentStatus(targetInstanceId);
          setAgentStatus(latest || null);
        } catch (agentErr) {
          // 404 means no agent heartbeat for this instance (SSH deployment); ignore.
          setAgentStatus(null);
        }
      } catch (err) {
        console.error('Failed to load telemetry runs', err);
        setError(err?.message || 'Failed to load telemetry runs');
      } finally {
        setRunsLoading(false);
      }
    },
    [instanceId]
  );

  useEffect(() => {
    fetchRuns();
    // Auto-refresh runs every 10 seconds to catch new agent deployments
    const interval = setInterval(() => {
      fetchRuns();
    }, 10000);
    return () => clearInterval(interval);
  }, [fetchRuns]);

  useEffect(() => {
    const fetchPrerequisites = async () => {
      setPrerequisitesLoading(true);
      try {
        const response = await apiService.getTelemetryPrerequisites();
        console.log('Prerequisites API response:', response);
        const prereqs = response?.prerequisites || [];
        console.log('Setting prerequisites:', prereqs.length);
        setPrerequisites(prereqs);
      } catch (err) {
        console.error('Failed to load prerequisites', err);
        // Set empty array on error so UI doesn't break
        setPrerequisites([]);
      } finally {
        setPrerequisitesLoading(false);
      }
    };
    fetchPrerequisites();
  }, []);

  // Fetch component status when active run exists
  const fetchDeploymentJobs = useCallback(async () => {
    if (!instanceId) return;
    setJobsLoading(true);
    try {
      const response = await apiService.listDeploymentJobs(instanceId);
      setDeploymentJobs(response.jobs || []);
      setQueueStats({
        pending: response.pending || 0,
        running: response.running || 0,
        total: response.total || 0,
      });
    } catch (err) {
      console.error('Failed to fetch deployment jobs', err);
    } finally {
      setJobsLoading(false);
    }
  }, [instanceId]);

  const handleRetryJob = useCallback(async (jobId) => {
    try {
      await apiService.retryDeploymentJob(jobId);
      fetchDeploymentJobs();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to retry job');
    }
  }, [fetchDeploymentJobs]);

  const handleCancelJob = useCallback(async (jobId) => {
    try {
      await apiService.cancelDeploymentJob(jobId);
      fetchDeploymentJobs();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to cancel job');
    }
  }, [fetchDeploymentJobs]);

  const fetchComponentStatus = useCallback(async () => {
    if (!activeRun || !instanceId) return;
    
    setComponentStatusLoading(true);
    try {
      const response = await apiService.getTelemetryComponentStatus(instanceId, activeRun.run_id);
      setComponentStatus(response);
    } catch (err) {
      console.error('Failed to load component status', err);
      setComponentStatus(null);
    } finally {
      setComponentStatusLoading(false);
    }
  }, [activeRun, instanceId]);

  useEffect(() => {
    if (activeRun && monitoringState === 'running') {
      fetchComponentStatus();
      // Poll component status every 30 seconds
      const interval = setInterval(fetchComponentStatus, 30000);
      return () => clearInterval(interval);
    } else {
      setComponentStatus(null);
    }
  }, [activeRun, monitoringState, fetchComponentStatus]);

  const appendRealtimeSamples = useCallback((samples) => {
    if (!samples || samples.length === 0) {
      return;
    }
    setRealtimeChart((prev) => {
      const map = new Map();
      prev.data.forEach((entry) => {
        map.set(entry.timestamp, { ...entry });
      });
      const gpuSet = new Set(prev.gpuIds);

      samples.forEach((sample) => {
        if (!sample || !sample.time) {
          return;
        }
        const timestamp = sample.time;
        const timeValue = telemetryUtils.parseTimestamp(timestamp);
        const existing = map.get(timestamp) || {
          timestamp,
          epoch: timeValue ? timeValue.getTime() : Date.now(),
          timeLabel: timeValue ? timeValue.toLocaleTimeString() : timestamp,
        };
        const gpuKey = `gpu_${sample.gpu_id}`;
        gpuSet.add(sample.gpu_id);
        existing[`${gpuKey}_util`] =
          sample.gpu_utilization != null ? Number(sample.gpu_utilization) : null;
        existing[`${gpuKey}_mem_util`] =
          sample.memory_utilization != null ? Number(sample.memory_utilization) : null;
        existing[`${gpuKey}_power`] =
          sample.power_draw_watts != null ? Number(sample.power_draw_watts) : null;
        
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
        existing[`${gpuKey}_energy_wh`] =
          sample.total_energy_joules != null ? Number(sample.total_energy_joules) / 3600.0 : null;
        map.set(timestamp, existing);
      });

      const sorted = Array.from(map.values()).sort((a, b) => a.epoch - b.epoch);
      const downsampled = downsampleTimeSeries(sorted, REALTIME_TARGET_POINTS, REALTIME_MAX_POINTS);
      return {
        data: downsampled,
        gpuIds: Array.from(gpuSet).sort((a, b) => a - b),
      };
    });
  }, []);

  const flushRealtimeBuffer = useCallback(() => {
    realtimeRafRef.current = null;
    if (!realtimeBufferRef.current.length) {
      return;
    }
    const batch = realtimeBufferRef.current;
    realtimeBufferRef.current = [];
    appendRealtimeSamples(batch);
  }, [appendRealtimeSamples]);

  const enqueueRealtimeSamples = useCallback(
    (samples) => {
      if (!samples || samples.length === 0) {
        return;
      }
      realtimeBufferRef.current.push(...samples);
      // Prevent unbounded growth if the UI lags behind the stream
      const maxBuffer = REALTIME_MAX_POINTS * 2;
      if (realtimeBufferRef.current.length > maxBuffer) {
        realtimeBufferRef.current.splice(0, realtimeBufferRef.current.length - maxBuffer);
      }
      if (!realtimeRafRef.current) {
        realtimeRafRef.current = requestAnimationFrameSafe(flushRealtimeBuffer);
      }
    },
    [flushRealtimeBuffer]
  );

  const startPollingFallback = useCallback(
    async (runId, reason = 'Live stream unavailable. Falling back to polling every 5 seconds.') => {
      if (!runId || fallbackPollRef.current) {
        return;
      }
      appendLog('warn', reason);
      setError(reason);

      const pollOnce = async () => {
        try {
          const response = await apiService.getTelemetryMetrics(runId, { limit: 200 });
          const samples = response?.metrics || [];
          if (samples.length > 0) {
            enqueueRealtimeSamples(samples);
            setLastDataReceivedAt(Date.now());
          }
        } catch (pollErr) {
          console.warn('Telemetry polling fallback failed', pollErr);
        }
      };

      await pollOnce();
      fallbackPollRef.current = setInterval(pollOnce, 5000);
    },
    [appendLog, enqueueRealtimeSamples]
  );

  const connectWebSocket = useCallback(
    (runId) => {
      if (!runId) return;

      if (websocketRef.current) {
        websocketRef.current.close();
      }
      realtimeBufferRef.current = [];
      if (realtimeRafRef.current) {
        cancelAnimationFrameSafe(realtimeRafRef.current);
        realtimeRafRef.current = null;
      }

      try {
        const wsUrl = apiService.getTelemetryWebSocketUrl(runId);
        const socket = new WebSocket(wsUrl);
        websocketRef.current = socket;

        socket.onopen = () => {
          appendLog('info', `WebSocket connected to live telemetry stream (run ${runId.substring(0, 8)}...)`);
          setMonitoringState('running');
          setMessage(`Connected to live telemetry stream for run ${runId.substring(0, 8)}...`);
          setHasProfilingData(false); // Reset when connecting
          setWebsocketConnectedAt(Date.now());
          setLastDataReceivedAt(null);
          console.log('WebSocket connected to run:', runId);
          setAgentSuggestedRunId(null);
          if (fallbackPollRef.current) {
            clearInterval(fallbackPollRef.current);
            fallbackPollRef.current = null;
          }
          
          // Set a timeout to detect if no data is received within 30 seconds
          if (dataTimeoutRef.current) {
            clearTimeout(dataTimeoutRef.current);
          }
          dataTimeoutRef.current = setTimeout(() => {
            // Note: This checks state at timeout time - if data arrived, timeout was cleared.
            (async () => {
              console.warn('WebSocket connected but no data received after 30 seconds');

              // If metrics exist in DB but aren't arriving over WS, fall back to polling so charts still render.
              try {
                const metricsResp = await apiService.getTelemetryMetrics(runId, { limit: 200 });
                const samples = metricsResp?.metrics || [];
                if (samples.length > 0) {
                  enqueueRealtimeSamples(samples);
                  setLastDataReceivedAt(Date.now());
                  await startPollingFallback(
                    runId,
                    'Live stream connected but no messages received; showing metrics via polling. If this persists, enable Redis broker or restart backend workers.'
                  );
                  return;
                }
              } catch (pollErr) {
                console.warn('Telemetry initial polling check failed', pollErr);
              }

              // If an agent is running, it may still be configured for a different run_id.
              const agentRunId = agentStatus?.metadata?.run_id;
              if (agentRunId && agentRunId !== runId) {
                setAgentSuggestedRunId(agentRunId);
                setError(
                  `No metrics received for run ${runId.substring(0, 8)}... The instance agent appears to be sending to a different run_id (${agentRunId.substring(0, 8)}...).`
                );
                return;
              }

              await startPollingFallback(
                runId,
                'WebSocket connected but no metrics received yet. Showing polling fallback while waiting for metrics.'
              );
            })();
          }, 30000);
        };

        socket.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            if (payload.type === 'metrics' && Array.isArray(payload.data)) {
              console.log(`Received ${payload.data.length} metric samples for run ${runId.substring(0, 8)}...`);
              
              // Clear the no-data timeout since we're receiving data
              if (dataTimeoutRef.current) {
                clearTimeout(dataTimeoutRef.current);
                dataTimeoutRef.current = null;
              }
              if (fallbackPollRef.current) {
                clearInterval(fallbackPollRef.current);
                fallbackPollRef.current = null;
              }
              setLastDataReceivedAt(Date.now());
              setError(''); // Clear any previous "no data" errors
              setAgentSuggestedRunId(null);
              
              // Check if SM/profiling data is present in samples
              const hasSmData = payload.data.some(sample => 
                sample.sm_utilization != null || 
                sample.sm_occupancy != null || 
                sample.tensor_active != null ||
                sample.hbm_utilization != null
              );
              if (hasSmData) {
                setHasProfilingData(true);
              }
              if (enableProfiling && !hasSmData && payload.data.length > 0) {
                console.warn('Profiling mode enabled but no SM/profiling metrics received. Sample keys:', 
                  payload.data[0] ? Object.keys(payload.data[0]) : 'no samples');
              }
              enqueueRealtimeSamples(payload.data);
            } else {
              console.log('Received WebSocket message:', payload.type, payload);
            }
          } catch (err) {
            console.error('Failed to parse telemetry WebSocket payload', err, event.data);
          }
        };

        socket.onclose = (event) => {
          console.log('WebSocket closed:', event.code, event.reason);
          websocketRef.current = null;
          realtimeBufferRef.current = [];
          if (realtimeRafRef.current) {
            cancelAnimationFrameSafe(realtimeRafRef.current);
            realtimeRafRef.current = null;
          }
          
          // Clear timeout on close
          if (dataTimeoutRef.current) {
            clearTimeout(dataTimeoutRef.current);
            dataTimeoutRef.current = null;
          }
          if ((event.code === 1000 || event.code === 1005 || monitoringState === 'stopping') && fallbackPollRef.current) {
            clearInterval(fallbackPollRef.current);
            fallbackPollRef.current = null;
          }
          
          // Code 1000 = normal closure, 1005 = no status received (browser close)
          // Don't show error for normal closures or if we're stopping monitoring
          if (event.code !== 1000 && event.code !== 1005 && monitoringState !== 'stopping') {
            setError(`WebSocket connection closed unexpectedly (code: ${event.code}${event.reason ? ': ' + event.reason : ''})`);
            startPollingFallback(
              runId,
              'WebSocket disconnected unexpectedly. Showing polling fallback while attempting to reconnect.'
            );
          }
          // If monitoring is still supposed to be running, try to reconnect after a delay
          if (monitoringState === 'running' && activeRun && activeRun.status === 'active' && event.code !== 1000) {
            console.log('Attempting to reconnect WebSocket in 3 seconds...');
            setTimeout(() => {
              if (monitoringState === 'running' && activeRun && activeRun.status === 'active') {
                connectWebSocket(activeRun.run_id);
              }
            }, 3000);
          }
        };

        socket.onerror = (event) => {
          console.error('Telemetry WebSocket error', event);
          setError(`Telemetry stream error: ${event.message || 'Connection error'}`);
          startPollingFallback(
            runId,
            'Telemetry stream connection failed. Showing polling fallback while keeping metrics live.'
          );
        };
      } catch (err) {
        console.error('Unable to connect to telemetry WebSocket', err);
        setError('Failed to connect to telemetry stream');
        startPollingFallback(
          runId,
          'Unable to connect to telemetry stream. Showing polling fallback while monitoring continues.'
        );
      }
    },
    [appendLog, enqueueRealtimeSamples, startPollingFallback, monitoringState, activeRun, enableProfiling, agentStatus]
  );

  useEffect(() => {
    if (monitoringState === 'idle' && activeRun && activeRun.status === 'active') {
      // Close any existing connection before connecting to new run_id
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
      connectWebSocket(activeRun.run_id);
    }
  }, [activeRun, monitoringState, connectWebSocket]);

  const stopDeploymentPolling = useCallback(() => {
    if (deploymentPollRef.current) {
      clearInterval(deploymentPollRef.current);
      deploymentPollRef.current = null;
    }
  }, []);

  const pollDeploymentStatus = useCallback(
    (instanceIdValue, deployment, runId) => {
      stopDeploymentPolling();
      if (!instanceIdValue || !deployment) {
        return;
      }
      deploymentPollRef.current = setInterval(async () => {
        try {
          const status = await apiService.getTelemetryDeploymentStatus(
            instanceIdValue,
            deployment.deployment_id
          );
          setDeploymentStatus(status);
          if (status.status === 'running') {
            setMonitoringState('running');
            setMessage('Monitoring stack is running');
            appendLog('info', 'Deployment complete. Connecting to live telemetry stream...');
            stopDeploymentPolling();
            connectWebSocket(runId);
          } else if (status.status === 'failed') {
            setMonitoringState('failed');
            setError(status.message || 'Deployment failed');
            appendLog('error', `Deployment failed: ${status.message || 'Unknown'}`);
            stopDeploymentPolling();
          }
        } catch (err) {
          console.error('Failed to poll deployment status', err);
        }
      }, 5000);
    },
    [appendLog, connectWebSocket, stopDeploymentPolling]
  );

  const handleStartMonitoring = useCallback(async () => {
    setError('');
    setMessage('');
    appendLog('info', 'Creating run and starting monitoring...');

    if (!instanceId) {
      setError('Select an instance before starting telemetry.');
      appendLog('error', 'Select an instance before starting.');
      return;
    }

    if (!sshHost) {
      setError('Instance IP address required.');
      return;
    }
    if (!sshUser) {
      setError('SSH user required.');
      return;
    }
    if (!sshKey) {
      setError('SSH private key required. Upload a PEM file from Manage Instances.');
      return;
    }

    const { gpuModel, gpuCount } = extractGpuInfo(instance || {});

    const runPayload = {
      instance_id: instanceId,
      gpu_model: gpuModel || null,
      gpu_count: gpuCount,
      tags: instance?.tags || null,
      notes: instance?.notes || null,
    };

    setProfilingResult(null);
    setProfilingResultRunId(null);
    setMonitoringState('creating');
    appendLog('info', 'Creating telemetry run...');
    try {
      const run = await apiService.createTelemetryRun(runPayload);
      setActiveRun(run);
      setRealtimeChart({ data: [], gpuIds: [] });
      setMonitoringState('deploying');
      setMessage('Deploying monitoring stack...');
      appendLog('info', 'Deploying monitoring stack (this may take ~60s)...');

      const deployment = await apiService.deployTelemetryStack(instanceId, {
        run_id: run.run_id,
        ssh_host: sshHost,
        ssh_user: sshUser,
        ssh_key: sshKey,
        backend_url: backendUrl,
        poll_interval: pollInterval,
        enable_profiling: enableProfiling,
      });
      setDeploymentId(deployment.deployment_id);
      pollDeploymentStatus(instanceId, deployment, run.run_id);
      fetchRuns(instanceId);
    } catch (err) {
      console.error('Failed to start telemetry monitoring', err);
      appendLog('error', `Start failed: ${err?.response?.data?.detail || err?.message || 'Unknown error'}`);
      setMonitoringState('idle');
      setError(err?.response?.data?.detail || err?.message || 'Failed to start telemetry');
    }
  }, [
    appendLog,
    instanceId,
    sshHost,
    sshUser,
    sshKey,
    backendUrl,
    pollInterval,
    instance,
    enableProfiling,
    fetchRuns,
    pollDeploymentStatus,
  ]);

  const teardownMonitoringStack = useCallback(
    async (run) => {
      if (!run || !instanceId) return;
      try {
        await apiService.teardownTelemetryStack(instanceId, {
          run_id: run.run_id,
          preserve_data: preserveData,
        });
      } catch (err) {
        console.warn('Failed to teardown telemetry stack', err);
      }
    },
    [instanceId, preserveData]
  );

  const handleStopMonitoring = useCallback(async () => {
    if (!activeRun) return;
    setMonitoringState('stopping');
    appendLog('info', 'Stopping monitoring and tearing down stack...');
    setError('');
    setMessage('');
    try {
      await teardownMonitoringStack(activeRun);
      await apiService.updateTelemetryRun(activeRun.run_id, {
        status: 'completed',
        end_time: new Date().toISOString(),
      });
      setMessage('Monitoring stopped. Run marked as completed.');
      appendLog('info', 'Monitoring stopped. Run marked as completed.');
      const runId = activeRun.run_id;
      try {
        const profile = await apiService.getTelemetryRunProfile(runId);
        setProfilingResult(profile);
        setProfilingResultRunId(runId);
        appendLog('info', 'Loaded run profile (workload/kernel/bottleneck).');
      } catch (profileErr) {
        setProfilingResult(null);
        setProfilingResultRunId(null);
      }
    } catch (err) {
      console.error('Failed to stop telemetry', err);
      appendLog('error', `Stop failed: ${err?.response?.data?.detail || err?.message || 'Unknown error'}`);
      setError(err?.response?.data?.detail || err?.message || 'Failed to stop telemetry');
    } finally {
      setMonitoringState('idle');
      setActiveRun(null);
      setDeploymentId(null);
      setDeploymentStatus(null);
      setRealtimeChart({ data: [], gpuIds: [] });
      setWebsocketConnectedAt(null);
      setLastDataReceivedAt(null);
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
      if (dataTimeoutRef.current) {
        clearTimeout(dataTimeoutRef.current);
        dataTimeoutRef.current = null;
      }
      fetchRuns();
    }
  }, [activeRun, appendLog, teardownMonitoringStack, fetchRuns]);

  const handleRefreshRuns = useCallback(() => {
    fetchRuns();
  }, [fetchRuns]);

  const handleRunKernelAnalysis = useCallback(async () => {
    if (!instanceId || !profilingResultRunId) return;
    setKernelRunLoading(true);
    appendLog('info', 'Starting kernel analysis run (this may take a few minutes)...');
    setError('');
    try {
      const result = await apiService.runProfiling(instanceId, profilingResultRunId, 'kernel', 20, 4);
      appendLog(
        result.status === 'completed' ? 'info' : 'error',
        `Kernel analysis ${result.status}: exit_code=${result.exit_code || '?'}`
      );
      if (result.status === 'completed') {
        const profile = await apiService.getTelemetryRunProfile(profilingResultRunId);
        setProfilingResult(profile);
        appendLog('info', 'Refreshed run profile with kernel breakdown.');
      } else {
        setError(result.output_tail || `Kernel analysis failed (exit ${result.exit_code})`);
      }
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || 'Kernel analysis failed';
      appendLog('error', msg);
      setError(msg);
    } finally {
      setKernelRunLoading(false);
    }
  }, [instanceId, profilingResultRunId, appendLog]);

  const selectHistoricalRun = useCallback(
    async (run) => {
      setSelectedHistoricalRun(run);
      setHistoricalChart({ data: [], gpuIds: [] });
      if (!run) return;

      setHistoricalLoading(true);
      try {
        const response = await apiService.getTelemetryMetrics(run.run_id, {
          limit: 5000,
        });
        const samples = response?.metrics || [];
        const transformed = transformSamplesToSeries(samples, null);
        setHistoricalChart(transformed);
      } catch (err) {
        console.error('Failed to load historical metrics', err);
        setError(err?.message || 'Failed to load historical metrics');
      } finally {
        setHistoricalLoading(false);
      }
    },
    []
  );

  const activeStatusChip = useMemo(() => {
    if (!activeRun) return null;
    const color =
      activeRun.status === 'active'
        ? 'success'
        : activeRun.status === 'failed'
        ? 'error'
        : 'default';
    return <Chip label={activeRun.status} color={color} size="small" />;
  }, [activeRun]);

  const instructionsNeeded = !instanceId || !sshHost || !sshKey;

  return (
    <Box sx={{ p: 4, maxWidth: '1920px', mx: 'auto' }}>
      <Stack spacing={4}>
        <Box>
          <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1.5, fontWeight: 600, fontSize: '1.75rem', color: '#1a1a1a' }}>
            <TimelineIcon color="primary" sx={{ fontSize: '2rem' }} />
            GPU Telemetry Monitoring
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9375rem', lineHeight: 1.6 }}>
            Deploy lightweight monitoring stack on your GPU instance to stream real-time metrics
            into dio.
          </Typography>
        </Box>

        {!instanceId && (
          <Alert
            severity="info"
            action={
              onNavigateToInstances ? (
                <Button color="inherit" size="small" onClick={onNavigateToInstances}>
                  Manage Instances
                </Button>
              ) : null
            }
          >
            Select an instance from Manage Instances to get started.
          </Alert>
        )}

        {(prerequisitesLoading || prerequisites.length > 0) && (
          <InfoCard
            icon={InfoIcon}
            title="Prerequisites"
            subtitle="Required before starting monitoring"
            color="info"
            sx={{ mb: 3 }}
          >
              {prerequisitesLoading ? (
              <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 2 }}>
                  <CircularProgress size={20} />
                  <Typography variant="body2" color="text.secondary">
                    Loading prerequisites...
                  </Typography>
              </Stack>
              ) : (
                <>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                    The following must be set up on your GPU instance before using "Start Monitoring". 
                  dio will automatically install Docker, NVIDIA Container Toolkit, DCGM, and Fabric Manager.
                  </Typography>
                <Stack spacing={2}>
                    {prerequisites.map((prereq) => (
                    <Paper
                      key={prereq.id}
                      sx={{
                        p: 2,
                        borderRadius: '8px',
                        border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
                        backgroundColor: alpha(theme.palette.background.paper, 0.5),
                      }}
                    >
                      <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                          {prereq.title}
                        </Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                          {prereq.description}
                        </Typography>
                        {prereq.install_hint && (
                        <CodeBlock
                          code={prereq.install_hint}
                          onCopy={(text) => {
                            navigator.clipboard.writeText(text);
                          }}
                          sx={{ mt: 1, fontSize: '0.75rem', p: 1.5 }}
                        />
                        )}
                        {prereq.docs_link && (
                        <MuiLink
                            href={prereq.docs_link}
                            target="_blank"
                            rel="noopener noreferrer"
                            variant="caption"
                          sx={{ 
                            display: 'inline-flex', 
                            alignItems: 'center', 
                            mt: 1,
                            fontWeight: 500,
                          }}
                          >
                          View Documentation <OpenInNewIcon sx={{ fontSize: 14, ml: 0.5 }} />
                        </MuiLink>
                        )}
                    </Paper>
                    ))}
                </Stack>
                <Alert severity="info" sx={{ mt: 3, borderRadius: '8px' }}>
                    <Typography variant="body2">
                    <strong>What dio installs automatically:</strong> Docker, NVIDIA Container Toolkit, DCGM, Fabric Manager
                    </Typography>
                  </Alert>
                </>
              )}
          </InfoCard>
        )}

        <Card variant="outlined" sx={{ borderRadius: '8px' }}>
          <CardHeader
            avatar={<CloudIcon color="primary" />}
            title={<Typography variant="h6" sx={{ fontWeight: 600 }}>Instance Connection</Typography>}
            subheader={instanceId || 'No instance selected'}
            action={activeStatusChip}
            sx={{ pb: 2 }}
          />
          <CardContent sx={{ pt: 0 }}>
            <Grid container spacing={3}>
              <Grid item xs={12} md={4}>
                <TextField
                  label="Instance ID"
                  fullWidth
                  value={instanceId}
                  disabled
                  helperText="Set from Manage Instances"
                  sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                />
              </Grid>
              <Grid item xs={12} md={4}>
                <TextField
                  label="SSH Host"
                  fullWidth
                  value={sshHost}
                  onChange={(e) => setSshHost(e.target.value)}
                  placeholder="123.45.67.89"
                  helperText="Public IP address of your GPU instance"
                  sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                />
              </Grid>
              <Grid item xs={12} md={4}>
                <TextField
                  label="SSH User"
                  fullWidth
                  value={sshUser}
                  onChange={(e) => setSshUser(e.target.value)}
                  placeholder="ubuntu"
                  helperText="SSH username (usually 'ubuntu' or 'root')"
                  sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                />
              </Grid>
              <Grid item xs={12} md={4}>
                <FormControl fullWidth>
                  <InputLabel>Polling Interval (s)</InputLabel>
                  <Select
                    label="Polling Interval (s)"
                    value={pollInterval}
                    onChange={(e) => setPollInterval(Number(e.target.value))}
                    sx={{ borderRadius: '8px' }}
                  >
                    {PREFERRED_POLL_INTERVALS.map((interval) => (
                      <MenuItem key={interval} value={interval}>
                        {interval}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} md={8}>
                <TextField
                  label="Backend URL"
                  fullWidth
                  value={backendUrl}
                  onChange={(e) => setBackendUrl(e.target.value)}
                  helperText="Reachable URL for this dio backend"
                  sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                />
              </Grid>
              <Grid item xs={12}>
                <Paper
                  variant="outlined"
                  sx={{
                    p: 2,
                    borderRadius: '8px',
                    backgroundColor: alpha('#1E4530', 0.3),
                  }}
                >
                <FormControlLabel
                  control={
                    <Switch
                      checked={enableProfiling}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setShowProfilingDialog(true);
                        } else {
                          setEnableProfiling(false);
                        }
                      }}
                      color="primary"
                    />
                  }
                  label={
                    <Box>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        Enable DCGM Profiling Mode (Advanced)
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Captures detailed SM/Tensor/DRAM metrics. Requires elevated privileges and adds slight overhead.
                      </Typography>
                    </Box>
                  }
                />
                </Paper>
              </Grid>
              <Grid item xs={12}>
                <TextField
                  label="SSH Private Key (PEM)"
                  fullWidth
                  value={sshKey || ''}
                  onChange={(e) => setSshKey(e.target.value)}
                  multiline
                  minRows={4}
                  placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                  helperText="Paste your SSH private key here. This will be used to securely access the instance."
                  sx={{ 
                    '& .MuiOutlinedInput-root': { borderRadius: '8px' },
                    '& textarea': { WebkitTextSecurity: 'disc' }
                  }}
                />
              </Grid>
            </Grid>
          </CardContent>
          <CardActions sx={{ px: 2, pb: 2 }}>
            <Button
              variant="contained"
              color="primary"
              startIcon={<PlayIcon />}
              onClick={handleStartMonitoring}
              disabled={monitoringState === 'creating' || monitoringState === 'deploying'}
            >
              {monitoringState === 'deploying' ? 'Deploying...' : 'Start Monitoring'}
            </Button>
            <Button
              variant="outlined"
              color="error"
              startIcon={<StopIcon />}
              onClick={handleStopMonitoring}
              disabled={!activeRun}
            >
              Stop Monitoring
            </Button>
            <FormControlLabel
              control={
                <Switch
                  checked={preserveData}
                  onChange={(e) => setPreserveData(e.target.checked)}
                  color="primary"
                />
              }
              label="Preserve Prometheus data on teardown"
            />
            <Box sx={{ flexGrow: 1 }} />
            <Button startIcon={<ReplayIcon />} onClick={handleRefreshRuns}>
              Refresh Runs
            </Button>
          </CardActions>
          {activityLog.length > 0 && (
            <Box
              sx={{
                px: 2,
                pb: 2,
                maxHeight: 150,
                overflow: 'auto',
                fontFamily: 'monospace',
                fontSize: '0.75rem',
                bgcolor: (t) => alpha(t.palette.background.default, 0.5),
                borderRadius: 1,
                border: (t) => `1px solid ${t.palette.divider}`,
              }}
            >
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                Activity log
              </Typography>
              {activityLog.slice(0, 10).map((entry, i) => (
                <Box
                  key={i}
                  sx={{
                    display: 'flex',
                    gap: 1,
                    alignItems: 'center',
                    py: 0.25,
                  }}
                >
                  <Chip
                    label={entry.level}
                    size="small"
                    sx={{
                      width: 48,
                      height: 18,
                      fontSize: '0.65rem',
                      bgcolor:
                        entry.level === 'error'
                          ? (t) => alpha(t.palette.error.main, 0.2)
                          : entry.level === 'warn'
                          ? (t) => alpha(t.palette.warning.main, 0.2)
                          : (t) => alpha(t.palette.info.main, 0.2),
                      color:
                        entry.level === 'error'
                          ? 'error.main'
                          : entry.level === 'warn'
                          ? 'warning.main'
                          : 'info.main',
                    }}
                  />
                  <Typography component="span" sx={{ fontSize: '0.7rem', color: 'text.secondary' }}>
                    {entry.ts}
                  </Typography>
                  <Typography component="span" sx={{ fontSize: '0.75rem', wordBreak: 'break-word' }}>
                    {entry.msg}
                  </Typography>
                </Box>
              ))}
            </Box>
          )}
        </Card>

        {message && <Alert severity="success">{message}</Alert>}
        {error && <Alert severity="error">{error}</Alert>}

        {deploymentId && (
          <Alert severity="info">
            Deployment ID: {deploymentId}
            {deploymentStatus?.status ? ` • Status: ${deploymentStatus.status}` : ''}
            {deploymentStatus?.message ? ` • ${deploymentStatus.message}` : ''}
          </Alert>
        )}

        {/* Run Summary - workload, bottleneck, kernel, GPU aggregates */}
        {profilingResult && (
          <Card variant="outlined" sx={{ mb: 2 }}>
            <CardHeader
              title="Run Summary"
              subheader={profilingResultRunId ? `Run ${profilingResultRunId.substring(0, 8)}...` : null}
              action={
                instanceId && profilingResultRunId && (
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={handleRunKernelAnalysis}
                    disabled={kernelRunLoading}
                    startIcon={kernelRunLoading ? <CircularProgress size={14} /> : null}
                  >
                    {kernelRunLoading ? 'Running...' : 'Run Kernel Analysis'}
                  </Button>
                )
              }
            />
            <CardContent>
              <Grid container spacing={2}>
                {profilingResult.workload && (
                  <>
                    <Grid item xs={6} sm={3}>
                      <Typography variant="caption" color="text.secondary">TTFT P50</Typography>
                      <Typography variant="h6">{profilingResult.workload.ttft_p50_ms != null ? Number(profilingResult.workload.ttft_p50_ms).toFixed(2) : '-'} ms</Typography>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Typography variant="caption" color="text.secondary">TTFT P95</Typography>
                      <Typography variant="h6">{profilingResult.workload.ttft_p95_ms != null ? Number(profilingResult.workload.ttft_p95_ms).toFixed(2) : '-'} ms</Typography>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Typography variant="caption" color="text.secondary">Throughput</Typography>
                      <Typography variant="h6">{profilingResult.workload.throughput_tok_sec != null ? Number(profilingResult.workload.throughput_tok_sec).toFixed(1) : '-'} tok/s</Typography>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Typography variant="caption" color="text.secondary">Success rate</Typography>
                      <Typography variant="h6">
                        {profilingResult.workload.num_requests > 0
                          ? `${Math.round((profilingResult.workload.successful_requests / profilingResult.workload.num_requests) * 100)}%`
                          : '-'}
                      </Typography>
                    </Grid>
                  </>
                )}
                {profilingResult.bottleneck && (
                  <Grid item xs={12}>
                    <Typography variant="caption" color="text.secondary">Bottleneck: </Typography>
                    <Chip label={profilingResult.bottleneck.primary_bottleneck || 'unknown'} size="small" sx={{ ml: 0.5 }} />
                    {profilingResult.bottleneck.mfu_pct != null && (
                      <Typography component="span" variant="body2" sx={{ ml: 1 }}>
                        MFU: {Number(profilingResult.bottleneck.mfu_pct).toFixed(1)}%
                      </Typography>
                    )}
                  </Grid>
                )}
                {profilingResult.gpu && (
                  <Grid item xs={12}>
                    <Typography variant="caption" color="text.secondary">GPU aggregates: </Typography>
                    <Typography component="span" variant="body2">
                      util {profilingResult.gpu.util_mean_pct != null ? Number(profilingResult.gpu.util_mean_pct).toFixed(1) : '-'}% |
                      SM active {profilingResult.gpu.sm_active_mean_pct != null ? Number(profilingResult.gpu.sm_active_mean_pct).toFixed(1) : '-'}% |
                      power {profilingResult.gpu.power_mean_w != null ? Number(profilingResult.gpu.power_mean_w).toFixed(0) : '-'} W |
                      temp {profilingResult.gpu.temp_mean_c != null ? Number(profilingResult.gpu.temp_mean_c).toFixed(0) : '-'} °C
                    </Typography>
                  </Grid>
                )}
                {Array.isArray(profilingResult.kernel_profiles) && profilingResult.kernel_profiles.length > 0 && profilingResult.kernel_profiles[0].categories?.length > 0 && (
                  <Grid item xs={12}>
                    <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Kernel breakdown</Typography>
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                      {profilingResult.kernel_profiles[0].categories.map((c, i) => (
                        <Chip key={i} label={`${c.category}: ${Number(c.pct).toFixed(1)}%`} size="small" variant="outlined" />
                      ))}
                    </Box>
                  </Grid>
                )}
                {Array.isArray(profilingResult.bottleneck?.recommendations) && profilingResult.bottleneck.recommendations.length > 0 && (
                  <Grid item xs={12}>
                    <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Recommendations</Typography>
                    <Stack spacing={0.25}>
                      {profilingResult.bottleneck.recommendations.map((r, i) => (
                        <Typography key={i} variant="body2">• {r}</Typography>
                      ))}
                    </Stack>
                  </Grid>
                )}
              </Grid>
            </CardContent>
          </Card>
        )}

        <Divider />

        {/* Component Status Indicators */}
        {activeRun && (monitoringState === 'running' || monitoringState === 'deploying') && (
          <Card sx={{ mb: 2 }}>
            <CardHeader 
              title="Component Status" 
              action={
                <IconButton size="small" onClick={fetchComponentStatus} disabled={componentStatusLoading}>
                  <ReplayIcon fontSize="small" />
                </IconButton>
              }
            />
            <CardContent>
              {componentStatusLoading ? (
                <Box display="flex" justifyContent="center" p={2}>
                  <CircularProgress size={24} />
                </Box>
              ) : componentStatus?.components ? (
                <Grid container spacing={1}>
                  {Object.entries(componentStatus.components)
                    .sort(([a], [b]) => {
                      // Sort: containers first, then prerequisites
                      const aIsPrereq = a.startsWith('prereq_');
                      const bIsPrereq = b.startsWith('prereq_');
                      if (aIsPrereq && !bIsPrereq) return 1;
                      if (!aIsPrereq && bIsPrereq) return -1;
                      return a.localeCompare(b);
                    })
                    .map(([name, status]) => {
                      const getStatusColor = (status) => {
                        if (status.status === 'healthy') return '#4caf50'; // green
                        if (status.status === 'error') return '#f44336'; // red
                        return '#1E4530'; // white/gray for not_found
                      };
                      const getStatusLabel = (status) => {
                        if (status.status === 'healthy') return '✓';
                        if (status.status === 'error') return '✗';
                        return '○';
                      };
                      // Clean up name for display
                      let displayName = name.replace(/_/g, ' ');
                      if (displayName.startsWith('prereq ')) {
                        displayName = displayName.replace('prereq ', '');
                      }
                      return (
                        <Grid item key={name}>
                          <Tooltip title={status.message || status.status} arrow>
                            <Chip
                              label={`${getStatusLabel(status)} ${displayName}`}
                              size="small"
                              sx={{
                                bgcolor: getStatusColor(status),
                                color: status.status === 'not_found' ? '#666' : 'white',
                                fontWeight: 500,
                                fontSize: '0.75rem',
                                minWidth: 120,
                                '&:hover': {
                                  opacity: 0.8,
                                },
                              }}
                            />
                          </Tooltip>
                        </Grid>
                      );
                    })}
                </Grid>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Component status not available. {monitoringState === 'deploying' && 'Waiting for deployment...'}
                </Typography>
              )}
            </CardContent>
          </Card>
        )}

        <Divider sx={{ mb: 2 }} />

        {/* Deployment Queue */}
        {instanceId && (
          <Card variant="outlined" sx={{ mb: 2 }}>
            <CardHeader
              title="Deployment Queue"
              action={
                <IconButton size="small" onClick={fetchDeploymentJobs} disabled={jobsLoading}>
                  <ReplayIcon fontSize="small" />
                </IconButton>
              }
            />
            <CardContent>
              {queueStats && (
                <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
                  <Chip label={`Pending: ${queueStats.pending}`} color="warning" size="small" />
                  <Chip label={`Running: ${queueStats.running}`} color="info" size="small" />
                  <Chip label={`Total: ${queueStats.total}`} size="small" />
                </Stack>
              )}
              {jobsLoading ? (
                <Box display="flex" justifyContent="center" p={2}>
                  <CircularProgress size={24} />
                </Box>
              ) : deploymentJobs.length === 0 ? (
                <Alert severity="info">No deployment jobs found</Alert>
              ) : (
                <Box>
                  {deploymentJobs.map((job) => {
                    const statusColor = {
                      pending: 'warning',
                      queued: 'info',
                      running: 'info',
                      completed: 'success',
                      failed: 'error',
                      cancelled: 'default',
                    }[job.status] || 'default';

                    return (
                      <Card key={job.job_id} variant="outlined" sx={{ mb: 1 }}>
                        <CardContent>
                          <Stack direction="row" spacing={2} alignItems="center">
                            <Chip label={job.status} color={statusColor} size="small" />
                            <Typography variant="body2" sx={{ fontFamily: 'monospace', flex: 1 }}>
                              {job.job_id.substring(0, 8)}...
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              Attempt {job.attempt_count}/{job.max_attempts}
                            </Typography>
                            {job.error_message && (
                              <Tooltip title={job.error_message}>
                                <WarningIcon color="error" fontSize="small" />
                              </Tooltip>
                            )}
                            <Stack direction="row" spacing={1}>
                              {job.status === 'failed' && (
                                <Button
                                  size="small"
                                  startIcon={<ReplayIcon />}
                                  onClick={() => handleRetryJob(job.job_id)}
                                >
                                  Retry
                                </Button>
                              )}
                              {(job.status === 'pending' || job.status === 'queued') && (
                                <Button
                                  size="small"
                                  color="error"
                                  onClick={() => handleCancelJob(job.job_id)}
                                >
                                  Cancel
                                </Button>
                              )}
                            </Stack>
                          </Stack>
                          {job.error_message && (
                            <Alert severity="error" sx={{ mt: 1 }}>
                              {job.error_message}
                            </Alert>
                          )}
                        </CardContent>
                      </Card>
                    );
                  })}
                </Box>
              )}
            </CardContent>
          </Card>
        )}

        <Divider sx={{ mb: 2 }} />

        <Card sx={{ mb: 3, borderRadius: '8px', border: `1px solid ${alpha('#000', 0.1)}` }}>
          <CardContent sx={{ p: 3 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'flex-start', sm: 'center' }} justifyContent="space-between">
              <Box>
                <Typography variant="h6" sx={{ fontWeight: 600, mb: 0.5 }}>
                  Real-time Metrics
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Monitor GPU performance metrics in real-time
                </Typography>
              </Box>
              <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
                <ToggleButtonGroup
                  size="small"
                  value={metricView}
                  exclusive
                  onChange={(e, val) => val && setMetricView(val)}
                  sx={{ borderRadius: 2 }}
                >
                  <ToggleButton value="enterprise" sx={{ textTransform: 'none', px: 1.5 }}>
                    Executive View
                  </ToggleButton>
                  <ToggleButton value="infra" sx={{ textTransform: 'none', px: 1.5 }}>
                    Deep Infra View
                  </ToggleButton>
                </ToggleButtonGroup>
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
                    sx={{ borderRadius: '8px' }}
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
                      label={metric.title}
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
        {monitoringState === 'deploying' && (
          <Alert severity="info">Waiting for monitoring stack to become healthy...</Alert>
        )}
        {monitoringState === 'running' && realtimeChart.data.length === 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
              Connected but No Data Received
            </Typography>
            <Typography variant="body2">
              WebSocket is connected for run <code>{activeRun?.run_id?.substring(0, 8)}...</code>, 
              but no metrics are being received.
              {websocketConnectedAt && (
                <span> (Connected {Math.floor((Date.now() - websocketConnectedAt) / 1000)}s ago)</span>
              )}
            </Typography>
            <Typography variant="body2" sx={{ mt: 1, fontWeight: 600 }}>
              Most likely cause:
            </Typography>
            <Box component="ul" sx={{ mt: 0.5, mb: 1, pl: 2 }}>
              <li><strong>The remote Prometheus instance is still configured with an old run_id</strong> - The Prometheus remote_write configuration needs to be updated with the new run_id</li>
              <li>Metrics are being sent to a different (completed) run_id than the one you're viewing</li>
              <li>The remote instance may not be sending metrics yet - check that Prometheus is scraping the exporters</li>
            </Box>
            {activeRun && (
              <Box sx={{ mt: 2, p: 1.5, bgcolor: 'error.light', borderRadius: '4px', border: '1px solid', borderColor: 'error.main' }}>
                <Typography variant="body2" sx={{ fontWeight: 600, mb: 1, color: 'error.dark' }}>
                  🔧 Solution:
                </Typography>
                {agentStatus ? (
                  <>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      This instance appears to have the provisioning agent running. Restart it to refresh Prometheus remote_write config:
                      <br />
                      <code style={{ fontSize: '0.85em' }}>sudo systemctl restart omniference-agent</code>
                    </Typography>
                    {agentSuggestedRunId && (
                      <Typography variant="body2" sx={{ mb: 1 }}>
                        Agent-reported run_id: <code style={{ fontSize: '0.85em' }}>{agentSuggestedRunId}</code>
                      </Typography>
                    )}
                  </>
                ) : (
                  <Typography variant="body2" sx={{ mb: 1 }}>
                    Click "Stop Monitoring" then "Start Monitoring" again to redeploy Prometheus with the correct run_id: <code style={{ fontSize: '0.85em' }}>{activeRun.run_id}</code>
                  </Typography>
                )}
                <Typography variant="caption" sx={{ display: 'block', mt: 1, fontFamily: 'monospace', color: 'text.secondary' }}>
                  Current Active Run: {activeRun.run_id}
                </Typography>
              </Box>
            )}
          </Alert>
        )}
        {monitoringState === 'running' && enableProfiling && realtimeChart.data.length > 10 && !hasProfilingData && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
              Profiling Mode Enabled but No SM Data Received
            </Typography>
            <Typography variant="body2">
              Profiling mode is enabled, but no SM utilization, SM occupancy, or Tensor Core metrics are being received. 
              This may indicate:
            </Typography>
            <Box component="ul" sx={{ mt: 1, mb: 0, pl: 2 }}>
              <li>The monitoring stack was started before profiling mode was enabled - please stop and restart monitoring</li>
              <li>DCGM profiling requires elevated privileges - check backend logs for permission errors</li>
              <li>The GPU may not support DCGM profiling metrics</li>
            </Box>
          </Alert>
        )}

        <Grid container spacing={3}>
          {metricsToRender.map((metric) => {
            return (
              <Grid item xs={12} md={6} lg={4} key={`realtime-${metric.id}`}>
                <MetricChart
                  title={metric.title}
                  metricKey={metric.metricKey}
                  unit={metric.unit}
                  domain={metric.domain}
                  data={realtimeChart.data}
                  gpuIds={realtimeChart.gpuIds}
                  icon={metric.icon}
                  description={metric.description}
                  activeRun={activeRun}
                  sshHost={sshHost}
                  sshUser={sshUser}
                  sshKey={sshKey}
                />
              </Grid>
            );
          })}
        </Grid>

        <Divider />

        {/* Deployment Queue */}
        <Card variant="outlined" sx={{ mt: 2 }}>
          <CardHeader
            title="Deployment Queue"
            action={
              <IconButton size="small" onClick={fetchDeploymentJobs} disabled={jobsLoading}>
                <ReplayIcon fontSize="small" />
              </IconButton>
            }
          />
          <CardContent>
            {queueStats && (
              <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
                <Chip label={`Pending: ${queueStats.pending}`} color="warning" size="small" />
                <Chip label={`Running: ${queueStats.running}`} color="info" size="small" />
                <Chip label={`Total: ${queueStats.total}`} size="small" />
              </Stack>
            )}
            {jobsLoading ? (
              <Box display="flex" justifyContent="center" p={2}>
                <CircularProgress size={24} />
              </Box>
            ) : deploymentJobs.length === 0 ? (
              <Alert severity="info">No deployment jobs found</Alert>
            ) : (
              <Box>
                {deploymentJobs.map((job) => {
                  const statusColor = {
                    pending: 'warning',
                    queued: 'info',
                    running: 'info',
                    completed: 'success',
                    failed: 'error',
                    cancelled: 'default',
                  }[job.status] || 'default';

                  return (
                    <Card key={job.job_id} variant="outlined" sx={{ mb: 1 }}>
                      <CardContent>
                        <Stack direction="row" spacing={2} alignItems="center">
                          <Chip label={job.status} color={statusColor} size="small" />
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', flex: 1 }}>
                            {job.job_id.substring(0, 8)}...
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            Attempt {job.attempt_count}/{job.max_attempts}
                          </Typography>
                          {job.error_message && (
                            <Tooltip title={job.error_message}>
                              <WarningIcon color="error" fontSize="small" />
                            </Tooltip>
                          )}
                          <Stack direction="row" spacing={1}>
                            {job.status === 'failed' && (
                              <Button
                                size="small"
                                startIcon={<ReplayIcon />}
                                onClick={() => handleRetryJob(job.job_id)}
                              >
                                Retry
                              </Button>
                            )}
                            {(job.status === 'pending' || job.status === 'queued') && (
                              <Button
                                size="small"
                                color="error"
                                onClick={() => handleCancelJob(job.job_id)}
                              >
                                Cancel
                              </Button>
                            )}
                          </Stack>
                        </Stack>
                        {job.error_message && (
                          <Alert severity="error" sx={{ mt: 1 }}>
                            {job.error_message}
                          </Alert>
                        )}
                      </CardContent>
                    </Card>
                  );
                })}
              </Box>
            )}
          </CardContent>
        </Card>

        <Divider />

        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Typography variant="h6">Historical Runs</Typography>
          {runsLoading && <CircularProgress size={20} />}
        </Stack>

        {runs.length === 0 && !runsLoading ? (
          <Alert severity="info">No telemetry runs recorded for this instance yet.</Alert>
        ) : (
          <Card variant="outlined">
            <CardContent>
              <Box
                sx={{
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
                <Grid container spacing={2} sx={{ minWidth: 'max-content' }}>
                  {runs.map((run) => (
                    <Grid item xs={12} md={6} lg={4} key={run.run_id} sx={{ minWidth: 280 }}>
                    <Card
                      variant={selectedHistoricalRun?.run_id === run.run_id ? 'outlined' : 'elevation'}
                      sx={{ height: '100%' }}
                    >
                      <CardContent>
                        <Stack spacing={1}>
                          <Typography variant="subtitle2" sx={{ fontFamily: 'monospace' }}>
                            {run.run_id}
                          </Typography>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Chip
                              size="small"
                              color={
                                run.status === 'active'
                                  ? 'success'
                                  : run.status === 'failed'
                                  ? 'error'
                                  : 'default'
                              }
                              label={run.status}
                            />
                            {run.summary?.avg_gpu_utilization != null && (
                              <Chip
                                size="small"
                                color="primary"
                                label={`Avg Util: ${run.summary.avg_gpu_utilization.toFixed(1)}%`}
                              />
                            )}
                          </Stack>
                          <Typography variant="body2" color="text.secondary">
                            Started: {telemetryUtils.parseTimestamp(run.start_time)?.toLocaleString()}
                          </Typography>
                          {run.end_time && (
                            <Typography variant="body2" color="text.secondary">
                              Ended: {telemetryUtils.parseTimestamp(run.end_time)?.toLocaleString()}
                            </Typography>
                          )}
                        </Stack>
                      </CardContent>
                      <CardActions>
                        <Button size="small" onClick={() => selectHistoricalRun(run)}>
                          View Metrics
                        </Button>
                      </CardActions>
                    </Card>
                  </Grid>
                ))}
                </Grid>
              </Box>
            </CardContent>
          </Card>
        )}

        {selectedHistoricalRun && (
          <Card 
            sx={{ 
              borderRadius: '8px',
              border: `1px solid ${alpha('#000', 0.1)}`,
              mb: 3,
            }}
          >
            <CardHeader
              title={
                <Typography variant="h6" sx={{ fontWeight: 600 }}>
                  Run {selectedHistoricalRun.run_id.substring(0, 8)}...
                </Typography>
              }
              subheader={
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
                  <Chip
                    label={selectedHistoricalRun.status}
                    size="small"
                    color={
                      selectedHistoricalRun.status === 'active'
                        ? 'success'
                        : selectedHistoricalRun.status === 'failed'
                        ? 'error'
                        : 'default'
                    }
                    sx={{ fontWeight: 500 }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    {telemetryUtils.parseTimestamp(selectedHistoricalRun.start_time)?.toLocaleString()}
                  </Typography>
                </Stack>
              }
              sx={{ pb: 2 }}
            />
            <CardContent>
              <Stack spacing={3}>
                <Paper
                  variant="outlined"
                  sx={{
                    p: 3,
                    borderRadius: '8px',
                    backgroundColor: alpha('#1E4530', 0.3),
                  }}
                >
                  <Grid container spacing={3}>
                    <Grid item xs={12} sm={6} md={3}>
                      <Box>
                        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, display: 'block', mb: 0.5 }}>
                      Duration
                    </Typography>
                        <Typography variant="h6" sx={{ fontWeight: 600 }}>
                      {selectedHistoricalRun.summary?.duration_seconds
                        ? `${(selectedHistoricalRun.summary.duration_seconds / 60).toFixed(1)} min`
                        : '—'}
                    </Typography>
                      </Box>
                  </Grid>
                    <Grid item xs={12} sm={6} md={3}>
                      <Box>
                        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, display: 'block', mb: 0.5 }}>
                      Avg Utilization
                    </Typography>
                        <Typography variant="h6" sx={{ fontWeight: 600, color: 'primary.main' }}>
                      {selectedHistoricalRun.summary?.avg_gpu_utilization != null
                        ? `${selectedHistoricalRun.summary.avg_gpu_utilization.toFixed(1)}%`
                        : '—'}
                    </Typography>
                      </Box>
                  </Grid>
                    <Grid item xs={12} sm={6} md={3}>
                      <Box>
                        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, display: 'block', mb: 0.5 }}>
                      Max Temperature
                    </Typography>
                        <Typography variant="h6" sx={{ fontWeight: 600, color: 'warning.main' }}>
                      {selectedHistoricalRun.summary?.max_temperature != null
                        ? `${selectedHistoricalRun.summary.max_temperature.toFixed(1)}°C`
                        : '—'}
                    </Typography>
                      </Box>
                  </Grid>
                    <Grid item xs={12} sm={6} md={3}>
                      <Box>
                        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, display: 'block', mb: 0.5 }}>
                      Energy Used
                    </Typography>
                        <Typography variant="h6" sx={{ fontWeight: 600, color: 'info.main' }}>
                      {selectedHistoricalRun.summary?.total_energy_wh != null
                        ? `${(selectedHistoricalRun.summary.total_energy_wh / 1000).toFixed(2)} kWh`
                        : '—'}
                    </Typography>
                      </Box>
                  </Grid>
                </Grid>
                </Paper>
                {historicalLoading ? (
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
                    <CircularProgress size={40} />
                  </Box>
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
                            <ToggleButtonGroup
                              size="small"
                              value={metricView}
                              exclusive
                              onChange={(e, val) => val && setMetricView(val)}
                              sx={{ borderRadius: 2 }}
                            >
                              <ToggleButton value="enterprise" sx={{ textTransform: 'none', px: 1.5 }}>
                                Executive View
                              </ToggleButton>
                              <ToggleButton value="infra" sx={{ textTransform: 'none', px: 1.5 }}>
                                Deep Infra View
                              </ToggleButton>
                            </ToggleButtonGroup>
                            <Button 
                              size="small" 
                              variant="outlined"
                              onClick={handleShowAllMetrics}
                              sx={{ borderRadius: '8px' }}
                            >
                          Show All
                        </Button>
                            <Button 
                              size="small" 
                              variant="outlined"
                              onClick={handleHideAllMetrics}
                              sx={{ borderRadius: '8px' }}
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
                                sx={{ borderRadius: '8px' }}
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
                    <Grid container spacing={3}>
                      {metricsToRender.map((metric) => {
                        return (
                          <Grid item xs={12} md={6} lg={4} key={`historical-${metric.id}`}>
                            <MetricChart
                              title={metric.historicalTitle || `Historical ${metric.title}`}
                              metricKey={metric.metricKey}
                              unit={metric.unit}
                              domain={metric.domain}
                              data={historicalChart.data}
                              gpuIds={historicalChart.gpuIds}
                              icon={metric.icon}
                              description={metric.description}
                              activeRun={selectedHistoricalRun}
                              sshHost={sshHost}
                              sshUser={sshUser}
                              sshKey={sshKey}
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

      {/* Profiling Mode Consent Dialog */}
      <Dialog
        open={showProfilingDialog}
        onClose={() => setShowProfilingDialog(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Enable DCGM Profiling Mode</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">
            <Alert severity="info" sx={{ mb: 2 }}>
              <Typography variant="body2" gutterBottom>
                <strong>Note:</strong> Standard monitoring already provides GPU utilization from nvidia-smi (shown in "GPU Utilization (Standard)" chart). 
                Profiling mode adds <em>additional</em> hardware counter-based metrics for deeper analysis.
              </Typography>
            </Alert>

            <Typography variant="body1" gutterBottom>
              <strong>Additional Profiling Metrics:</strong>
            </Typography>
            <Box component="ul" sx={{ mt: 1, mb: 2 }}>
              <li><strong>SM Utilization (Profiling)</strong> - Hardware counter-based SM activity (more detailed than standard GPU util)</li>
              <li><strong>SM Occupancy</strong> - How full the streaming multiprocessors are</li>
              <li><strong>Tensor Core Utilization</strong> - AI/ML tensor core activity</li>
              <li><strong>HBM Utilization (Profiling)</strong> - Memory bandwidth utilization (DRAM active)</li>
              <li><strong>Pipeline Activity</strong> - FP64/FP32/FP16 operation tracking</li>
            </Box>
            
            <Typography variant="body1" color="warning.main" gutterBottom>
              <strong>Important Considerations:</strong>
            </Typography>
            <Box component="ul" sx={{ mt: 1, mb: 2 }}>
              <li><strong>Performance Overhead:</strong> Profiling adds 1-3% overhead to GPU workloads</li>
              <li><strong>Elevated Privileges:</strong> Requires sudo/root access on the target instance</li>
              <li><strong>Exclusive Access:</strong> May conflict with other profiling tools (nsight, nvprof)</li>
              <li><strong>GPU Compatibility:</strong> Works best on Volta architecture and newer (V100, A100, H100)</li>
            </Box>

            <Typography variant="body2" color="text.secondary">
              Standard monitoring (without profiling) already provides GPU utilization, memory usage, power, temperature, 
              and other metrics without any performance impact. Enable profiling only when you need hardware-level SM and memory bandwidth insights.
            </Typography>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button 
            onClick={() => {
              setShowProfilingDialog(false);
              setEnableProfiling(false);
            }}
          >
            Cancel
          </Button>
          <Button 
            onClick={() => {
              setShowProfilingDialog(false);
              setEnableProfiling(true);
            }}
            variant="contained"
            color="primary"
          >
            I Understand, Enable Profiling
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TelemetryTab;
