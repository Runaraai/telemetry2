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
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  InputLabel,
  LinearProgress,
  Link,
  MenuItem,
  Paper,
  Select,
  Stack,
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
  VpnKey as VpnKeyIcon,
  ArrowForward as ArrowForwardIcon,
  ArrowBack as ArrowBackIcon,
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
import apiService, { telemetryUtils, friendlyError } from '../services/api';
import AIInsightsBox from './AIInsightsBox';

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
  '#818cf8',
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
  // ── Essential metrics ──────────────────────────────────────────────
  {
    id: 'gpu-util',
    metricKey: 'util',
    title: 'GPU Utilization',
    historicalTitle: 'GPU Utilization',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    category: 'essential',
    description:
      'Overall GPU utilization from nvidia-smi. Available on all GPUs without profiling mode. This represents the percentage of time the GPU was actively executing kernels.',
  },
  {
    id: 'memory-util',
    metricKey: 'mem_util',
    title: 'Memory Utilization',
    historicalTitle: 'Memory Utilization',
    unit: '%',
    domain: [0, 100],
    icon: MemoryIcon,
    category: 'essential',
    description: 'GPU memory usage as a percentage of total available memory. Shows how much VRAM is allocated.',
  },
  {
    id: 'power-draw',
    metricKey: 'power',
    title: 'Power Draw',
    historicalTitle: 'Power Draw',
    unit: 'Watts',
    icon: BoltIcon,
    category: 'essential',
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
    category: 'essential',
    description: 'GPU temperature in Celsius. High temperatures may trigger thermal throttling.',
  },
  {
    id: 'tokens-per-second',
    metricKey: 'tokens_per_second',
    title: 'Tokens per Second',
    historicalTitle: 'Tokens per Second',
    unit: 'tokens/s',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    category: 'essential',
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
    category: 'essential',
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
    category: 'essential',
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
    category: 'essential',
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
    category: 'essential',
    description: 'Performance efficiency metric: tokens generated per second per watt of power consumed. Higher values indicate better energy efficiency.',
  },
  // ── Advanced metrics ───────────────────────────────────────────────
  {
    id: 'sm-util',
    metricKey: 'sm_util',
    title: 'Compute Utilization',
    historicalTitle: 'Compute Utilization',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    category: 'advanced',
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
    category: 'advanced',
    description:
      'Average percentage of active warps per SM. Highlights how effectively workloads fill the GPU pipelines.',
  },
  {
    id: 'hbm-util',
    metricKey: 'hbm_util',
    title: 'HBM Utilization',
    historicalTitle: 'HBM Utilization',
    unit: '%',
    domain: [0, 100],
    icon: MemoryIcon,
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
    description: 'PCIe transmit throughput per GPU. Indicates host-to-device traffic pressure.',
  },
  {
    id: 'pcie-rx',
    metricKey: 'pcie_rx',
    title: 'PCIe RX Throughput',
    historicalTitle: 'PCIe RX Throughput',
    unit: 'MB/s',
    icon: TimelineIcon,
    category: 'advanced',
    description: 'PCIe receive throughput per GPU. Indicates device-to-host traffic pressure.',
  },
  {
    id: 'nvlink-tx',
    metricKey: 'nvlink_tx',
    title: 'NVLink TX Throughput',
    historicalTitle: 'NVLink TX Throughput',
    unit: 'MB/s',
    icon: TimelineIcon,
    category: 'advanced',
    description: 'NVLink transmit throughput (per GPU). Useful for multi-GPU communication diagnostics.',
  },
  {
    id: 'nvlink-rx',
    metricKey: 'nvlink_rx',
    title: 'NVLink RX Throughput',
    historicalTitle: 'NVLink RX Throughput',
    unit: 'MB/s',
    icon: TimelineIcon,
    category: 'advanced',
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
    category: 'advanced',
    description: 'HBM temperature reported by DCGM. Complements core temperature monitoring.',
  },
  {
    id: 'power-limit',
    metricKey: 'power_limit',
    title: 'Power Limit',
    historicalTitle: 'Power Limit',
    unit: 'Watts',
    icon: BoltIcon,
    category: 'advanced',
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
    category: 'advanced',
    description: 'Total energy consumption per GPU (converted from DCGM Joule counter). Useful for cost tracking.',
  },
  {
    id: 'encoder-util',
    metricKey: 'encoder_util',
    title: 'Encoder Utilization',
    historicalTitle: 'Encoder Utilization',
    unit: '%',
    domain: [0, 100],
    icon: BoltIcon,
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
    category: 'advanced',
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
  const isTokenMetric = ['tokens_per_second', 'requests_per_second', 'ttft_p50_ms', 'ttft_p95_ms', 'cost_per_watt'].includes(metricKey);
  const theme = useTheme();
  const [expanded, setExpanded] = React.useState(false);
  const cardRef = React.useRef(null);

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

  // Compute current value, previous value, and trend
  const { currentValue, trendPercent, trendDirection, sparklineData } = React.useMemo(() => {
    if (!data.length) return { currentValue: null, trendPercent: 0, trendDirection: 'flat', sparklineData: [] };

    // Get the last N points for sparkline
    const sparkPoints = data.slice(-20);

    // Extract values
    const getVal = (point) => {
      if (isTokenMetric) return point[metricKey];
      if (gpuIds.length > 0) return point[`gpu_${gpuIds[0]}_${metricKey}`];
      return null;
    };

    const values = data.map(getVal).filter((v) => v != null && !isNaN(v));
    const current = values.length > 0 ? values[values.length - 1] : null;

    // Compute trend: compare last value to value ~25% back in the series
    let trend = 0;
    let direction = 'flat';
    if (values.length >= 2) {
      const compareIdx = Math.max(0, Math.floor(values.length * 0.75));
      const prev = values[compareIdx];
      if (prev !== 0) {
        trend = ((current - prev) / Math.abs(prev)) * 100;
        direction = trend > 1 ? 'up' : trend < -1 ? 'down' : 'flat';
      }
    }

    return {
      currentValue: current,
      trendPercent: Math.abs(trend),
      trendDirection: direction,
      sparklineData: sparkPoints,
    };
  }, [data, metricKey, isTokenMetric, gpuIds]);

  const formatValue = (val) => {
    if (val == null) return '--';
    if (val >= 1000000) return `${(val / 1000000).toFixed(1)}M`;
    if (val >= 1000) return `${(val / 1000).toFixed(1)}k`;
    if (val >= 100) return Math.round(val).toString();
    if (val >= 10) return val.toFixed(1);
    return val.toFixed(2);
  };

  const trendColor =
    trendDirection === 'up' ? theme.palette.success.main :
    trendDirection === 'down' ? theme.palette.error.main :
    theme.palette.text.secondary;

  const sparklineColor = trendDirection === 'up' ? '#4caf50' : trendDirection === 'down' ? '#ef5350' : '#818cf8';

  // Unique gradient ID to avoid SVG conflicts
  const gradientId = `spark-${metricKey}-${gpuIds?.[0] ?? 'token'}`;

  const handleClick = React.useCallback((e) => {
    e.stopPropagation();
    setExpanded((prev) => !prev);
  }, []);

  const hasData = data.length > 0;

  return (
    <Card
      ref={cardRef}
      sx={{
        borderRadius: '16px',
        border: `1px solid ${alpha(theme.palette.divider, 0.08)}`,
        transition: 'all 0.45s cubic-bezier(0.4, 0, 0.2, 1)',
        '&:hover': expanded ? {} : {
          boxShadow: `0 8px 32px ${alpha(theme.palette.primary.main, 0.12)}`,
          transform: 'translateY(-2px)',
          borderColor: alpha(theme.palette.primary.main, 0.2),
        },
        overflow: 'hidden',
      }}
    >
      {/* Stat Card Header — always visible, clickable */}
      <CardContent
        onClick={handleClick}
        sx={{
          p: 2.5,
          pb: expanded ? 1.5 : 2.5,
          '&:last-child': { pb: expanded ? 1.5 : 2.5 },
          cursor: 'pointer',
          transition: 'padding 0.3s ease',
          userSelect: 'none',
        }}
      >
        <Stack direction="row" alignItems="flex-start" justifyContent="space-between">
          <Box sx={{ flex: 1 }}>
            <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 1.5 }}>
              <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.secondary', fontSize: '0.8rem' }}>
                {title}
                {unit && <Typography component="span" variant="caption" sx={{ ml: 0.5, opacity: 0.6 }}>/ {unit}</Typography>}
              </Typography>
              {description && (
                <Tooltip title={description} arrow placement="top">
                  <InfoIcon sx={{ fontSize: 14, color: 'text.disabled', cursor: 'help' }} onClick={(e) => e.stopPropagation()} />
                </Tooltip>
              )}
            </Stack>
            <Stack direction="row" alignItems="baseline" spacing={1.5}>
              <Typography
                variant="h4"
                sx={{
                  fontWeight: 800,
                  lineHeight: 1.1,
                  transition: 'all 0.3s ease',
                  fontSize: expanded ? '1.75rem' : '2.125rem',
                }}
              >
                {hasData ? formatValue(currentValue) : '--'}
              </Typography>
              {hasData && trendDirection !== 'flat' && (
                <Chip
                  size="small"
                  label={`${trendDirection === 'up' ? '+' : '-'}${trendPercent.toFixed(0)}%`}
                  sx={{
                    height: 22,
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    backgroundColor: alpha(trendColor, 0.1),
                    color: trendColor,
                    borderRadius: '6px',
                    '& .MuiChip-label': { px: 0.75 },
                  }}
                />
              )}
              {!hasData && (
                <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                  No data yet
                </Typography>
              )}
            </Stack>
          </Box>

          {/* Mini sparkline in stat view */}
          {!expanded && hasData && (
            <Box
              sx={{
                width: 100,
                height: 48,
                opacity: 1,
                transition: 'opacity 0.3s ease',
                flexShrink: 0,
                mt: 1,
                pointerEvents: 'none',
              }}
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={sparklineData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
                  <defs>
                    <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={sparklineColor} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={sparklineColor} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone"
                    dataKey={isTokenMetric ? metricKey : `gpu_${gpuIds[0]}_${metricKey}`}
                    stroke={sparklineColor}
                    fill={`url(#${gradientId})`}
                    strokeWidth={2}
                    fillOpacity={1}
                    connectNulls
                    isAnimationActive={false}
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          )}
        </Stack>
      </CardContent>

      {/* Expanded chart section — animates in/out */}
      <Box
        sx={{
          maxHeight: expanded ? 600 : 0,
          opacity: expanded ? 1 : 0,
          overflow: 'hidden',
          transition: 'max-height 0.45s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.35s ease',
        }}
      >
        {hasData ? (
          <>
            <CardContent sx={{ pt: 0, px: 2.5, height: 320 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data} margin={{ top: 12, right: 20, bottom: 12, left: 8 }}>
                  <defs>
                    {isTokenMetric ? (
                      <linearGradient key="gradient-token" id={`gradient-token-${metricKey}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={theme.palette.primary.main} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={theme.palette.primary.main} stopOpacity={0.05} />
                      </linearGradient>
                    ) : (
                      gpuIds.map((id, index) => {
                        const colors = getGradientColors(COLOR_PALETTE[index % COLOR_PALETTE.length], index);
                        return (
                          <linearGradient key={`gradient-${id}-${metricKey}`} id={`gradient-${id}-${metricKey}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor={colors.start} stopOpacity={0.3} />
                            <stop offset="95%" stopColor={colors.end} stopOpacity={0.05} />
                          </linearGradient>
                        );
                      })
                    )}
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={alpha(theme.palette.divider, 0.3)} vertical={false} />
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
                    labelStyle={{ color: theme.palette.text.primary, fontWeight: 600, marginBottom: 4 }}
                    itemStyle={{ color: theme.palette.text.secondary, padding: '2px 0' }}
                    cursor={{ stroke: alpha(theme.palette.primary.main, 0.3), strokeWidth: 1 }}
                  />
                  <Legend wrapperStyle={{ paddingTop: 8 }} iconType="line" iconSize={12} />
                  {isTokenMetric ? (
                    <Area
                      key="token-metric"
                      type="monotone"
                      dataKey={metricKey}
                      name={title}
                      stroke={theme.palette.primary.main}
                      fill={`url(#gradient-token-${metricKey})`}
                      strokeWidth={2.5}
                      fillOpacity={1}
                      connectNulls
                      isAnimationActive={true}
                      animationDuration={500}
                      activeDot={{ r: 5, fill: theme.palette.primary.main, strokeWidth: 2, stroke: theme.palette.background.paper }}
                    />
                  ) : (
                    gpuIds.map((id, index) => {
                      const colors = getGradientColors(COLOR_PALETTE[index % COLOR_PALETTE.length], index);
                      return (
                        <Area
                          key={`gpu-${id}`}
                          type="monotone"
                          dataKey={`gpu_${id}_${metricKey}`}
                          name={`GPU ${id}`}
                          stroke={colors.start}
                          fill={`url(#gradient-${id}-${metricKey})`}
                          strokeWidth={2.5}
                          fillOpacity={1}
                          connectNulls
                          isAnimationActive={true}
                          animationDuration={500}
                          activeDot={{ r: 5, fill: colors.start, strokeWidth: 2, stroke: theme.palette.background.paper }}
                        />
                      );
                    })
                  )}
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>

            <CardContent sx={{ pt: 0, pb: 2, px: 2.5 }}>
              <AIInsightsBox metricName={title} metricKey={metricKey} unit={unit} data={data} gpuIds={gpuIds} />
            </CardContent>
          </>
        ) : (
          <CardContent sx={{ pt: 0, px: 2.5 }}>
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                py: 6,
                borderTop: `1px solid ${alpha(theme.palette.divider, 0.08)}`,
              }}
            >
              <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                No data available yet. Start monitoring to see the time-series chart.
              </Typography>
            </Box>
          </CardContent>
        )}
      </Box>

      {/* Collapse bar when expanded */}
      {expanded && (
        <Box
          onClick={handleClick}
          sx={{
            display: 'flex',
            justifyContent: 'center',
            py: 1,
            cursor: 'pointer',
            '&:hover': { backgroundColor: alpha(theme.palette.primary.main, 0.04) },
            transition: 'background-color 0.2s ease',
          }}
        >
          <Box
            sx={{
              width: 40,
              height: 4,
              borderRadius: 2,
              backgroundColor: alpha(theme.palette.text.secondary, 0.2),
              transition: 'background-color 0.2s ease',
              '&:hover': { backgroundColor: alpha(theme.palette.text.secondary, 0.4) },
            }}
          />
        </Box>
      )}
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
  const [telemetryStep, setTelemetryStep] = useState(0);
  const [metricsTab, setMetricsTab] = useState(0);
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
  const [metricView] = useState('infra');
  const [activityLog, setActivityLog] = useState([]);
  const [profilingResult, setProfilingResult] = useState(null);
  const [profilingResultRunId, setProfilingResultRunId] = useState(null);
  const [kernelRunLoading, setKernelRunLoading] = useState(false);

  // Workload benchmark state
  const [benchmarkConfig, setBenchmarkConfig] = useState({
    vllmServer: 'http://localhost:8000',
    model: '',
    numRequests: 50,
    concurrency: 4,
    maxTokens: 256,
  });
  const [benchmarkLoading, setBenchmarkLoading] = useState(false);
  const [benchmarkResult, setBenchmarkResult] = useState(null);

  // Kernel profiling state (separate run)
  const [kernelProfileLoading, setKernelProfileLoading] = useState(false);
  const [kernelProfileResult, setKernelProfileResult] = useState(null);
  const [kernelProfileRunId, setKernelProfileRunId] = useState(null);

  // Inference (vLLM) start/stop control
  const [inferenceStatus, setInferenceStatus] = useState(null); // null | 'starting' | 'running' | 'stopping' | 'stopped' | 'error'
  const [inferenceModel, setInferenceModel] = useState('');
  const inferenceStatusPollRef = useRef(null);
  const inferenceStatusCheckingRef = useRef(false);

  // Progress elapsed timers for long-running operations
  const [benchmarkElapsed, setBenchmarkElapsed] = useState(0);
  const [kernelElapsed, setKernelElapsed] = useState(0);
  const benchmarkTimerRef = useRef(null);
  const kernelTimerRef = useRef(null);

  // Preflight check state
  const [kernelProfilingReady, setKernelProfilingReady] = useState(null); // null | {ready, reason, fix}
  const [profilingModeReady, setProfilingModeReady] = useState(null);

  // WebSocket reconnect state
  const [wsReconnecting, setWsReconnecting] = useState(false);
  const wsReconnectAttemptRef = useRef(0);

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
    return METRIC_DEFINITIONS.filter((m) => metricToggles[m.id] !== false);
  }, [metricToggles]);

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

  // Auto-populate SSH private key from backend config
  useEffect(() => {
    apiService.getSSHPrivateKey()
      .then((key) => { if (key && !sshKey) setSshKey(key); })
      .catch(() => {}); // silently ignore if not configured
  }, []); // eslint-disable-line

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
      setError(friendlyError(err, 'Failed to retry job'));
    }
  }, [fetchDeploymentJobs]);

  const handleCancelJob = useCallback(async (jobId) => {
    try {
      await apiService.cancelDeploymentJob(jobId);
      fetchDeploymentJobs();
    } catch (err) {
      setError(friendlyError(err, 'Failed to cancel job'));
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
          setWsReconnecting(false);
          wsReconnectAttemptRef.current = 0; // Reset on successful connect
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
          // Exponential backoff reconnect: 2s, 4s, 8s, 16s, max 30s
          if (event.code !== 1000 && event.code !== 1005 && monitoringState === 'running' && activeRun && activeRun.status === 'active') {
            const attempt = wsReconnectAttemptRef.current;
            const delay = Math.min(30000, 2000 * Math.pow(2, attempt));
            wsReconnectAttemptRef.current = attempt + 1;
            console.log(`WebSocket reconnect attempt ${attempt + 1} in ${delay}ms...`);
            setWsReconnecting(true);
            setTimeout(() => {
              if (monitoringState === 'running' && activeRun && activeRun.status === 'active') {
                connectWebSocket(activeRun.run_id);
              } else {
                setWsReconnecting(false);
              }
            }, delay);
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
      appendLog('error', `Start failed: ${friendlyError(err, 'Unknown error')}`);
      setMonitoringState('idle');
      setError(friendlyError(err, 'Failed to start telemetry'));
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
      appendLog('error', `Stop failed: ${friendlyError(err, 'Unknown error')}`);
      setError(friendlyError(err, 'Failed to stop telemetry'));
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
      const msg = friendlyError(err, 'Kernel analysis failed');
      appendLog('error', msg);
      setError(msg);
    } finally {
      setKernelRunLoading(false);
    }
  }, [instanceId, profilingResultRunId, appendLog]);

  const handleRunWorkloadBenchmark = useCallback(async () => {
    if (!instanceId) return;
    setBenchmarkLoading(true);
    setBenchmarkResult(null);
    setBenchmarkElapsed(0);
    benchmarkTimerRef.current = setInterval(() => setBenchmarkElapsed((s) => s + 1), 1000);
    appendLog('info', `Starting workload benchmark (${benchmarkConfig.numRequests} requests, concurrency ${benchmarkConfig.concurrency})...`);
    setError('');
    try {
      const result = await apiService.runProfiling(
        instanceId,
        activeRun?.run_id || null,
        'standard',
        benchmarkConfig.numRequests,
        benchmarkConfig.concurrency,
        {
          maxTokens: benchmarkConfig.maxTokens,
          vllmServer: benchmarkConfig.vllmServer || undefined,
          modelName: benchmarkConfig.model || undefined,
          createNewRun: !activeRun,
        }
      );
      appendLog(
        result.status === 'completed' ? 'info' : 'error',
        `Workload benchmark ${result.status}: exit_code=${result.exit_code ?? '?'}`
      );
      if (result.status === 'completed') {
        const targetRunId = result.run_id || activeRun?.run_id;
        if (targetRunId) {
          const profile = await apiService.getTelemetryRunProfile(targetRunId);
          setBenchmarkResult(profile);
          if (!profilingResultRunId) {
            setProfilingResultRunId(targetRunId);
          }
          appendLog('info', 'Workload metrics loaded.');
        }
      } else {
        setError(result.output_tail || `Benchmark failed (exit ${result.exit_code})`);
      }
    } catch (err) {
      const msg = friendlyError(err, 'Workload benchmark failed');
      appendLog('error', msg);
      setError(msg);
    } finally {
      setBenchmarkLoading(false);
      if (benchmarkTimerRef.current) { clearInterval(benchmarkTimerRef.current); benchmarkTimerRef.current = null; }
    }
  }, [instanceId, activeRun, benchmarkConfig, appendLog, profilingResultRunId]);

  const handleRunKernelProfile = useCallback(async () => {
    if (!instanceId) return;
    setKernelProfileLoading(true);
    setKernelProfileResult(null);
    setKernelElapsed(0);
    kernelTimerRef.current = setInterval(() => setKernelElapsed((s) => s + 1), 1000);
    appendLog('info', 'Starting kernel profiling run (separate run, expect 5–10% overhead)...');
    setError('');
    try {
      const result = await apiService.runProfiling(
        instanceId,
        null,
        'kernel',
        benchmarkConfig.numRequests,
        benchmarkConfig.concurrency,
        {
          maxTokens: benchmarkConfig.maxTokens,
          vllmServer: benchmarkConfig.vllmServer || undefined,
          modelName: benchmarkConfig.model || undefined,
          createNewRun: true,
        }
      );
      appendLog(
        result.status === 'completed' ? 'info' : 'error',
        `Kernel profiling ${result.status}: run ${result.run_id?.substring(0, 8)}... exit_code=${result.exit_code ?? '?'}`
      );
      if (result.status === 'completed' && result.run_id) {
        setKernelProfileRunId(result.run_id);
        const profile = await apiService.getTelemetryRunProfile(result.run_id);
        setKernelProfileResult(profile);
        appendLog('info', 'Kernel profile loaded.');
      } else {
        setError(result.output_tail || `Kernel profiling failed (exit ${result.exit_code})`);
      }
    } catch (err) {
      const msg = friendlyError(err, 'Kernel profiling failed');
      appendLog('error', msg);
      setError(msg);
    } finally {
      setKernelProfileLoading(false);
      if (kernelTimerRef.current) { clearInterval(kernelTimerRef.current); kernelTimerRef.current = null; }
    }
  }, [instanceId, benchmarkConfig, appendLog]);

  const runPreflightChecks = useCallback(async () => {
    if (!instanceId) return;
    try {
      const [kernelCheck, modeCheck] = await Promise.allSettled([
        apiService.checkKernelProfilingReady(instanceId),
        apiService.checkProfilingModeReady(instanceId),
      ]);
      if (kernelCheck.status === 'fulfilled') setKernelProfilingReady(kernelCheck.value);
      if (modeCheck.status === 'fulfilled') setProfilingModeReady(modeCheck.value);
    } catch { /* non-critical */ }
  }, [instanceId]);

  const fetchInferenceStatus = useCallback(async () => {
    if (!sshHost || inferenceStatusCheckingRef.current) return;
    inferenceStatusCheckingRef.current = true;
    try {
      const result = await apiService.inferenceStatus({ ssh_host: sshHost, ssh_user: sshUser });
      if (result?.status === 'running') {
        setInferenceStatus('running');
      } else {
        setInferenceStatus('stopped');
      }
    } catch {
      setInferenceStatus(null);
    } finally {
      inferenceStatusCheckingRef.current = false;
    }
  }, [sshHost, sshUser]);

  const handleStartInference = useCallback(async () => {
    if (!sshHost) return;
    setInferenceStatus('starting');
    appendLog('info', `Starting inference server on ${sshHost}...`);
    try {
      const pemBase64 = sshKey ? btoa(sshKey) : undefined;
      await apiService.inferenceStart({
        ssh_host: sshHost,
        ssh_user: sshUser,
        pem_base64: pemBase64,
        model_path: inferenceModel || undefined,
        cloud_provider: instance?.provider || 'lambda',
      });
      appendLog('info', 'Inference server starting — this may take 1–2 minutes.');
      setTimeout(() => fetchInferenceStatus(), 5000);
    } catch (err) {
      const msg = friendlyError(err, 'Failed to start inference');
      appendLog('error', msg);
      setInferenceStatus('error');
    }
  }, [sshHost, sshUser, sshKey, inferenceModel, instance, appendLog, fetchInferenceStatus]);

  const handleStopInference = useCallback(async () => {
    if (!sshHost) return;
    setInferenceStatus('stopping');
    appendLog('info', `Stopping inference server on ${sshHost}...`);
    try {
      const pemBase64 = sshKey ? btoa(sshKey) : undefined;
      await apiService.inferenceStop({ ssh_host: sshHost, ssh_user: sshUser, pem_base64: pemBase64 });
      setInferenceStatus('stopped');
      appendLog('info', 'Inference server stopped.');
    } catch (err) {
      const msg = friendlyError(err, 'Failed to stop inference');
      appendLog('error', msg);
      setInferenceStatus('error');
    }
  }, [sshHost, sshUser, sshKey, appendLog]);

  // Poll inference status every 10s when sshHost is set
  useEffect(() => {
    if (!sshHost) return;
    fetchInferenceStatus();
    inferenceStatusPollRef.current = setInterval(fetchInferenceStatus, 10000);
    return () => {
      if (inferenceStatusPollRef.current) clearInterval(inferenceStatusPollRef.current);
    };
  }, [sshHost, fetchInferenceStatus]);

  // Run preflight checks once when an active deployment is detected
  useEffect(() => {
    if (instanceId && activeRun) runPreflightChecks();
  }, [instanceId, activeRun, runPreflightChecks]);

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
          <Typography variant="h1" sx={{ mb: 1.5, fontWeight: 800, fontSize: '3rem' }}>
            Telemetry
          </Typography>
        </Box>

        {/* Step Indicator */}
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
          {['Instance Connection', 'Inference Server', 'Workload Benchmark', 'Kernel Profiling', 'Telemetry'].map((label, idx) => (
            <Box
              key={label}
              onClick={() => setTelemetryStep(idx)}
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                cursor: 'pointer',
                opacity: telemetryStep === idx ? 1 : 0.5,
                transition: 'opacity 0.2s',
              }}
            >
              <Box
                sx={{
                  width: 28,
                  height: 28,
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.8rem',
                  fontWeight: 700,
                  backgroundColor: telemetryStep === idx ? '#16a34a' : alpha('#000', 0.1),
                  color: telemetryStep === idx ? '#fff' : 'text.secondary',
                }}
              >
                {idx + 1}
              </Box>
              <Typography
                variant="body2"
                sx={{
                  fontWeight: telemetryStep === idx ? 600 : 400,
                  display: { xs: 'none', sm: 'block' },
                }}
              >
                {label}
              </Typography>
              {idx < 4 && (
                <Box sx={{ width: 24, height: 1, backgroundColor: alpha('#000', 0.15), mx: 0.5 }} />
              )}
            </Box>
          ))}
        </Stack>

        {!instanceId && (
          <Alert
            severity="success"
            sx={{ alignItems: 'center', '& .MuiAlert-action': { pt: 0, alignItems: 'center' } }}
            action={
              onNavigateToInstances ? (
                <Button variant="outlined" color="secondary" size="small" sx={{ backgroundColor: '#fff', color: '#000' }} onClick={onNavigateToInstances}>
                  Running Instances
                </Button>
              ) : null
            }
          >
            Select a run from Running Instances to get started.
          </Alert>
        )}

        {/* Step 0: Instance Connection */}
        {telemetryStep === 0 && (<React.Fragment>
        <Card variant="outlined" sx={{ borderRadius: '8px' }}>
          <CardHeader
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
                    backgroundColor: alpha('#3d3d3a', 0.3),
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
                {sshKey ? (
                  <Box sx={{ mt: 1, p: 2, borderRadius: '8px', border: '1px solid #3d3d3a', backgroundColor: 'rgba(129, 140, 248, 0.06)' }}>
                    <Typography variant="body2" sx={{ color: '#34d399', fontWeight: 600, mb: 0.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                      <VpnKeyIcon sx={{ fontSize: 16 }} /> SSH Key Auto-configured
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#a8a8a0', fontFamily: '"DM Mono", monospace', wordBreak: 'break-all' }}>
                      {sshKey.substring(0, 80)}...
                    </Typography>
                  </Box>
                ) : (
                  <TextField
                    label="SSH Private Key (PEM)"
                    fullWidth
                    value={sshKey || ''}
                    onChange={(e) => setSshKey(e.target.value)}
                    multiline
                    rows={3}
                    placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                    helperText="Paste your SSH private key here. This will be used to securely access the instance."
                    sx={{
                      '& .MuiOutlinedInput-root': { borderRadius: '8px' },
                    }}
                  />
                )}
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

        {/* Next button for step 0 */}
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
          <Button
            variant="contained"
            endIcon={<ArrowForwardIcon />}
            onClick={() => setTelemetryStep(1)}
            sx={{
              backgroundColor: '#16a34a',
              color: '#fff',
              borderRadius: 2,
              fontWeight: 600,
              px: 4,
              '&:hover': { backgroundColor: '#15803d' },
            }}
          >
            Next
          </Button>
        </Box>
        </React.Fragment>)}

        {/* Step 1: Inference Server */}
        {telemetryStep === 1 && (<React.Fragment>

        {/* ── Inference (vLLM) Control Card ─────────────────────────────── */}
          <Card variant="outlined" sx={{ mb: 2 }}>
            <CardHeader
              title="Inference Server"
              subheader="Start or stop the vLLM inference server on the connected GPU instance"
              action={
                <Chip
                  label={
                    inferenceStatus === 'running' ? 'Running' :
                    inferenceStatus === 'starting' ? 'Starting…' :
                    inferenceStatus === 'stopping' ? 'Stopping…' :
                    inferenceStatus === 'stopped' ? 'Stopped' :
                    inferenceStatus === 'error' ? 'Error' :
                    'Unknown'
                  }
                  color={
                    inferenceStatus === 'running' ? 'success' :
                    inferenceStatus === 'error' ? 'error' :
                    inferenceStatus === 'starting' || inferenceStatus === 'stopping' ? 'warning' :
                    'default'
                  }
                  size="small"
                />
              }
            />
            <CardContent>
              <TextField
                label="Model path or HuggingFace ID"
                value={inferenceModel}
                onChange={(e) => setInferenceModel(e.target.value)}
                fullWidth
                size="small"
                placeholder="e.g. mistralai/Mistral-7B-Instruct-v0.2"
                helperText="Leave blank to use the default model configured during setup"
                sx={{ mb: 1 }}
              />
            </CardContent>
            <CardActions sx={{ px: 2, pb: 2 }}>
              <Button
                variant="contained"
                color="success"
                startIcon={inferenceStatus === 'starting' ? <CircularProgress size={14} /> : <PlayIcon />}
                onClick={handleStartInference}
                disabled={!sshHost || inferenceStatus === 'starting' || inferenceStatus === 'running' || inferenceStatus === 'stopping'}
              >
                {inferenceStatus === 'starting' ? 'Starting…' : 'Start Inference'}
              </Button>
              <Button
                variant="outlined"
                color="error"
                startIcon={inferenceStatus === 'stopping' ? <CircularProgress size={14} /> : <StopIcon />}
                onClick={handleStopInference}
                disabled={!sshHost || inferenceStatus !== 'running'}
              >
                {inferenceStatus === 'stopping' ? 'Stopping…' : 'Stop Inference'}
              </Button>
              <Button
                size="small"
                onClick={fetchInferenceStatus}
                disabled={!sshHost}
                sx={{ ml: 'auto' }}
              >
                Refresh Status
              </Button>
            </CardActions>
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

        {/* Nav buttons for step 1 */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
          <Button
            variant="outlined"
            startIcon={<ArrowBackIcon />}
            onClick={() => setTelemetryStep(0)}
            sx={{ borderRadius: 2, fontWeight: 600, px: 4 }}
          >
            Back
          </Button>
          <Button
            variant="contained"
            endIcon={<ArrowForwardIcon />}
            onClick={() => setTelemetryStep(2)}
            sx={{
              backgroundColor: '#16a34a',
              color: '#fff',
              borderRadius: 2,
              fontWeight: 600,
              px: 4,
              '&:hover': { backgroundColor: '#15803d' },
            }}
          >
            Next
          </Button>
        </Box>
        </React.Fragment>)}

        {/* Step 2: Workload Benchmark */}
        {telemetryStep === 2 && (<React.Fragment>

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

        {/* ================================================================ */}
        {/* Workload Benchmark Card                                         */}
        {/* ================================================================ */}
          <Card variant="outlined">
            <CardHeader
              title={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <SpeedIcon color="primary" fontSize="small" />
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>Workload Benchmark</Typography>
                </Box>
              }
              subheader="Collect TTFT, inter-token latency and throughput from vLLM via streaming API"
            />
            <CardContent>
              <Grid container spacing={2} sx={{ mb: 2 }}>
                <Grid item xs={12} md={5}>
                  <TextField
                    label="vLLM Server URL"
                    fullWidth
                    size="small"
                    value={benchmarkConfig.vllmServer}
                    onChange={(e) => setBenchmarkConfig((p) => ({ ...p, vllmServer: e.target.value }))}
                    placeholder="http://localhost:8000"
                    helperText="Accessible from the GPU instance"
                    disabled={benchmarkLoading}
                    sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                  />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    label="Model Name"
                    fullWidth
                    size="small"
                    value={benchmarkConfig.model}
                    onChange={(e) => setBenchmarkConfig((p) => ({ ...p, model: e.target.value }))}
                    placeholder="auto-detect"
                    helperText="Leave blank to auto-detect"
                    disabled={benchmarkLoading}
                    sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                  />
                </Grid>
                <Grid item xs={6} md={2}>
                  <TextField
                    label="Requests"
                    type="number"
                    fullWidth
                    size="small"
                    value={benchmarkConfig.numRequests}
                    onChange={(e) => setBenchmarkConfig((p) => ({ ...p, numRequests: parseInt(e.target.value) || 50 }))}
                    inputProps={{ min: 1, max: 500 }}
                    disabled={benchmarkLoading}
                    sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                  />
                </Grid>
                <Grid item xs={6} md={2}>
                  <TextField
                    label="Concurrency"
                    type="number"
                    fullWidth
                    size="small"
                    value={benchmarkConfig.concurrency}
                    onChange={(e) => setBenchmarkConfig((p) => ({ ...p, concurrency: parseInt(e.target.value) || 4 }))}
                    inputProps={{ min: 1, max: 32 }}
                    disabled={benchmarkLoading}
                    sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                  />
                </Grid>
              </Grid>

              {monitoringState === 'running' && activeRun && (
                <Alert severity="info" sx={{ mb: 2, borderRadius: '8px' }}>
                  Results will be attached to the active monitoring run <code>{activeRun.run_id?.substring(0, 8)}...</code>
                </Alert>
              )}
              {monitoringState !== 'running' && (
                <Alert severity="info" sx={{ mb: 2, borderRadius: '8px' }}>
                  GPU monitoring is not active. A standalone workload run will be created.
                </Alert>
              )}

              <Button
                variant="contained"
                onClick={handleRunWorkloadBenchmark}
                disabled={benchmarkLoading || !instanceId}
                startIcon={benchmarkLoading ? <CircularProgress size={16} /> : <PlayIcon />}
                sx={{ borderRadius: '8px', textTransform: 'none', fontWeight: 600 }}
              >
                {benchmarkLoading ? 'Benchmarking...' : 'Run Benchmark'}
              </Button>

              {benchmarkLoading && (
                <Box sx={{ mt: 2 }}>
                  <LinearProgress sx={{ borderRadius: 1, height: 6 }} />
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                    Running benchmark… {benchmarkElapsed}s elapsed (typically 30–120s)
                  </Typography>
                </Box>
              )}

              {/* Benchmark Results */}
              {benchmarkResult?.workload && (
                <Box sx={{ mt: 3 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1.5, fontWeight: 600 }}>Results</Typography>
                  <Grid container spacing={2}>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '8px', textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary" display="block">TTFT P50</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 700 }}>
                          {benchmarkResult.workload.ttft_p50_ms != null ? `${Number(benchmarkResult.workload.ttft_p50_ms).toFixed(1)} ms` : '—'}
                        </Typography>
                      </Paper>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '8px', textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary" display="block">TTFT P95</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 700 }}>
                          {benchmarkResult.workload.ttft_p95_ms != null ? `${Number(benchmarkResult.workload.ttft_p95_ms).toFixed(1)} ms` : '—'}
                        </Typography>
                      </Paper>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '8px', textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary" display="block">ITL P50</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 700 }}>
                          {benchmarkResult.workload.tpot_p50_ms != null ? `${Number(benchmarkResult.workload.tpot_p50_ms).toFixed(1)} ms` : '—'}
                        </Typography>
                      </Paper>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '8px', textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary" display="block">Throughput</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 700 }}>
                          {benchmarkResult.workload.throughput_tok_sec != null ? `${Number(benchmarkResult.workload.throughput_tok_sec).toFixed(1)} tok/s` : '—'}
                        </Typography>
                      </Paper>
                    </Grid>
                    {benchmarkResult.workload.tpot_p95_ms != null && (
                      <Grid item xs={6} sm={3}>
                        <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '8px', textAlign: 'center' }}>
                          <Typography variant="caption" color="text.secondary" display="block">ITL P95</Typography>
                          <Typography variant="h6" sx={{ fontWeight: 700 }}>
                            {Number(benchmarkResult.workload.tpot_p95_ms).toFixed(1)} ms
                          </Typography>
                        </Paper>
                      </Grid>
                    )}
                    {benchmarkResult.workload.throughput_req_sec != null && (
                      <Grid item xs={6} sm={3}>
                        <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '8px', textAlign: 'center' }}>
                          <Typography variant="caption" color="text.secondary" display="block">Req/s</Typography>
                          <Typography variant="h6" sx={{ fontWeight: 700 }}>
                            {Number(benchmarkResult.workload.throughput_req_sec).toFixed(2)}
                          </Typography>
                        </Paper>
                      </Grid>
                    )}
                    {benchmarkResult.workload.num_requests > 0 && (
                      <Grid item xs={6} sm={3}>
                        <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '8px', textAlign: 'center' }}>
                          <Typography variant="caption" color="text.secondary" display="block">Success</Typography>
                          <Typography variant="h6" sx={{ fontWeight: 700 }}>
                            {Math.round((benchmarkResult.workload.successful_requests / benchmarkResult.workload.num_requests) * 100)}%
                          </Typography>
                        </Paper>
                      </Grid>
                    )}
                  </Grid>
                  {benchmarkResult.bottleneck && (
                    <Box sx={{ mt: 1.5, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                      <Typography variant="caption" color="text.secondary">Bottleneck:</Typography>
                      <Chip label={benchmarkResult.bottleneck.primary_bottleneck || 'unknown'} size="small" color="warning" />
                      {benchmarkResult.bottleneck.mfu_pct != null && (
                        <Typography variant="body2">MFU: {Number(benchmarkResult.bottleneck.mfu_pct).toFixed(1)}%</Typography>
                      )}
                    </Box>
                  )}
                  {Array.isArray(benchmarkResult.bottleneck?.recommendations) && benchmarkResult.bottleneck.recommendations.length > 0 && (
                    <Box sx={{ mt: 1 }}>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>Recommendations</Typography>
                      {benchmarkResult.bottleneck.recommendations.map((r, i) => (
                        <Typography key={i} variant="body2" sx={{ color: 'text.secondary' }}>• {r}</Typography>
                      ))}
                    </Box>
                  )}
                </Box>
              )}
            </CardContent>
          </Card>

        {/* Nav buttons for step 2 */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
          <Button
            variant="outlined"
            startIcon={<ArrowBackIcon />}
            onClick={() => setTelemetryStep(1)}
            sx={{ borderRadius: 2, fontWeight: 600, px: 4 }}
          >
            Back
          </Button>
          <Button
            variant="contained"
            endIcon={<ArrowForwardIcon />}
            onClick={() => setTelemetryStep(3)}
            sx={{
              backgroundColor: '#16a34a',
              color: '#fff',
              borderRadius: 2,
              fontWeight: 600,
              px: 4,
              '&:hover': { backgroundColor: '#15803d' },
            }}
          >
            Next
          </Button>
        </Box>
        </React.Fragment>)}

        {/* Step 3: Kernel Profiling */}
        {telemetryStep === 3 && (<React.Fragment>

        {/* ================================================================ */}
        {/* Kernel Profiling Card (separate run, overhead warning)           */}
        {/* ================================================================ */}
          <Card variant="outlined" sx={{ borderColor: 'warning.main' }}>
            <CardHeader
              title={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <BoltIcon color="warning" fontSize="small" />
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>Kernel Profiling</Typography>
                  <Chip
                    label="Separate run • ~5–10% overhead"
                    size="small"
                    color="warning"
                    variant="outlined"
                    sx={{ fontSize: '0.7rem' }}
                  />
                </Box>
              }
              subheader="Uses Chrome trace from vLLM to break down kernel time by category (attention, matmul, layernorm, etc.)"
            />
            <CardContent>
              <Alert severity="warning" sx={{ mb: 2, borderRadius: '8px' }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>Prerequisites</Typography>
                <Typography variant="body2">
                  vLLM must be running with <code>--profiler-config</code>. This creates a <strong>new separate run</strong> — it does not share data with the active GPU monitoring run. Kernel profiling adds tracing overhead.
                </Typography>
              </Alert>

              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Uses the vLLM server and model settings from the Workload Benchmark config above.
              </Typography>

              {/* Preflight check results */}
              {kernelProfilingReady?.ready === false && (
                <Alert severity="error" sx={{ mb: 2, borderRadius: '8px' }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                    Kernel profiling not ready: {kernelProfilingReady.reason}
                  </Typography>
                  {kernelProfilingReady.fix && (
                    <Typography variant="caption" component="pre" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', mt: 0.5, p: 1, bgcolor: 'background.default', borderRadius: 1 }}>
                      {kernelProfilingReady.fix}
                    </Typography>
                  )}
                </Alert>
              )}
              {profilingModeReady?.ready === false && (
                <Alert severity="warning" sx={{ mb: 2, borderRadius: '8px' }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                    Profiling mode not enabled: {profilingModeReady.reason}
                  </Typography>
                  {profilingModeReady.fix && (
                    <Typography variant="caption" component="pre" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', mt: 0.5, p: 1, bgcolor: 'background.default', borderRadius: 1 }}>
                      {profilingModeReady.fix}
                    </Typography>
                  )}
                </Alert>
              )}

              <Button
                variant="outlined"
                color="warning"
                onClick={handleRunKernelProfile}
                disabled={kernelProfileLoading || !instanceId || kernelProfilingReady?.ready === false}
                startIcon={kernelProfileLoading ? <CircularProgress size={16} /> : <BoltIcon />}
                sx={{ borderRadius: '8px', textTransform: 'none', fontWeight: 600 }}
              >
                {kernelProfileLoading ? 'Profiling kernels...' : 'Run Kernel Profile'}
              </Button>

              {kernelProfileLoading && (
                <Box sx={{ mt: 2 }}>
                  <LinearProgress color="warning" sx={{ borderRadius: 1, height: 6 }} />
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                    Running kernel profiler… {kernelElapsed}s elapsed (typically 5–10 min)
                  </Typography>
                </Box>
              )}

              {kernelProfileRunId && !kernelProfileLoading && (
                <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
                  Run: {kernelProfileRunId.substring(0, 8)}...
                </Typography>
              )}

              {/* Kernel Results */}
              {kernelProfileResult && (
                <Box sx={{ mt: 3 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1.5, fontWeight: 600 }}>Kernel Breakdown</Typography>

                  {Array.isArray(kernelProfileResult.kernel_profiles) && kernelProfileResult.kernel_profiles.length > 0 &&
                   kernelProfileResult.kernel_profiles[0].categories?.length > 0 ? (
                    <Box>
                      {/* Bar chart using inline widths */}
                      <Stack spacing={0.75}>
                        {kernelProfileResult.kernel_profiles[0].categories
                          .slice()
                          .sort((a, b) => b.pct - a.pct)
                          .map((cat, i) => (
                            <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                              <Typography variant="caption" sx={{ width: 120, flexShrink: 0, textTransform: 'capitalize' }}>
                                {cat.category}
                              </Typography>
                              <Box sx={{ flex: 1, bgcolor: 'grey.100', borderRadius: 1, overflow: 'hidden', height: 18 }}>
                                <Box
                                  sx={{
                                    width: `${Math.min(100, Number(cat.pct))}%`,
                                    height: '100%',
                                    bgcolor: i === 0 ? 'primary.main' : i === 1 ? 'secondary.main' : 'grey.400',
                                    borderRadius: 1,
                                    transition: 'width 0.4s ease',
                                  }}
                                />
                              </Box>
                              <Typography variant="caption" sx={{ width: 48, textAlign: 'right', flexShrink: 0, fontWeight: 600 }}>
                                {Number(cat.pct).toFixed(1)}%
                              </Typography>
                            </Box>
                          ))}
                      </Stack>

                      {/* Chip summary */}
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 1.5 }}>
                        {kernelProfileResult.kernel_profiles[0].categories.map((c, i) => (
                          <Chip key={i} label={`${c.category}: ${Number(c.pct).toFixed(1)}%`} size="small" variant="outlined" />
                        ))}
                      </Box>
                    </Box>
                  ) : (
                    <Typography variant="body2" color="text.secondary">No kernel category data returned.</Typography>
                  )}

                  {kernelProfileResult.bottleneck && (
                    <Box sx={{ mt: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="caption" color="text.secondary">Bottleneck:</Typography>
                      <Chip label={kernelProfileResult.bottleneck.primary_bottleneck || 'unknown'} size="small" color="warning" />
                    </Box>
                  )}
                </Box>
              )}
            </CardContent>
          </Card>

        {/* Nav buttons for step 3 */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
          <Button
            variant="outlined"
            startIcon={<ArrowBackIcon />}
            onClick={() => setTelemetryStep(2)}
            sx={{
              borderRadius: 2,
              fontWeight: 600,
              px: 4,
            }}
          >
            Back
          </Button>
          <Button
            variant="contained"
            endIcon={<ArrowForwardIcon />}
            onClick={() => setTelemetryStep(4)}
            sx={{
              backgroundColor: '#16a34a',
              color: '#fff',
              borderRadius: 2,
              fontWeight: 600,
              px: 4,
              '&:hover': { backgroundColor: '#15803d' },
            }}
          >
            Next
          </Button>
        </Box>
        </React.Fragment>)}

        {/* Step 4: Telemetry */}
        {telemetryStep === 4 && (<React.Fragment>

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
                        return '#3d3d3a'; // white/gray for not_found
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

        {monitoringState === 'deploying' && (
          <Alert severity="info">Waiting for monitoring stack to become healthy...</Alert>
        )}
        {wsReconnecting && (
          <Alert severity="warning" icon={<CircularProgress size={16} />} sx={{ mb: 1 }}>
            WebSocket disconnected — reconnecting with exponential backoff (attempt {wsReconnectAttemptRef.current})...
          </Alert>
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

        {/* Metrics category tabs */}
        <Stack direction="row" spacing={3} sx={{ mb: 3 }}>
          {['Overview', 'Advanced Metrics', 'Bottleneck', 'Optimization'].map((label, idx) => (
            <Typography
              key={label}
              variant="subtitle1"
              onClick={() => setMetricsTab(idx)}
              sx={{
                fontWeight: 600,
                cursor: 'pointer',
                pb: 0.5,
                borderBottom: metricsTab === idx
                  ? '2px solid #16a34a'
                  : '2px solid transparent',
                color: metricsTab === idx
                  ? 'text.primary'
                  : 'text.secondary',
                '&:hover': { color: 'text.primary' },
              }}
            >
              {label}
            </Typography>
          ))}
        </Stack>

        {metricsTab === 0 && (
          <Grid container spacing={3}>
            {metricsToRender
              .filter((m) => m.category === 'essential')
              .map((metric) => (
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
              ))}
          </Grid>
        )}

        {metricsTab === 1 && (
          <Grid container spacing={3}>
            {metricsToRender
              .filter((m) => m.category === 'advanced')
              .map((metric) => (
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
              ))}
          </Grid>
        )}

        {metricsTab === 2 && (
          <Card variant="outlined" sx={{ borderRadius: '8px' }}>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>Bottleneck Analysis</Typography>
              <Typography variant="body2" color="text.secondary">
                Bottleneck detection results will appear here after running a workload benchmark or kernel profile.
              </Typography>
              {benchmarkResult?.bottleneck && (
                <Box sx={{ mt: 2 }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>Primary Bottleneck:</Typography>
                    <Chip label={benchmarkResult.bottleneck.primary_bottleneck || 'unknown'} size="small" color="warning" />
                    {benchmarkResult.bottleneck.mfu_pct != null && (
                      <Typography variant="body2">MFU: {Number(benchmarkResult.bottleneck.mfu_pct).toFixed(1)}%</Typography>
                    )}
                  </Stack>
                  {Array.isArray(benchmarkResult.bottleneck?.recommendations) && benchmarkResult.bottleneck.recommendations.length > 0 && (
                    <Box sx={{ mt: 1 }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>Recommendations</Typography>
                      {benchmarkResult.bottleneck.recommendations.map((r, i) => (
                        <Typography key={i} variant="body2" sx={{ color: 'text.secondary' }}>• {r}</Typography>
                      ))}
                    </Box>
                  )}
                </Box>
              )}
              {kernelProfileResult?.bottleneck && (
                <Box sx={{ mt: 2 }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>Kernel Bottleneck:</Typography>
                    <Chip label={kernelProfileResult.bottleneck.primary_bottleneck || 'unknown'} size="small" color="warning" />
                  </Stack>
                </Box>
              )}
              {!benchmarkResult?.bottleneck && !kernelProfileResult?.bottleneck && (
                <Alert severity="info" sx={{ mt: 2, borderRadius: '8px' }}>
                  Run a Workload Benchmark or Kernel Profile to see bottleneck analysis.
                </Alert>
              )}
            </CardContent>
          </Card>
        )}

        {metricsTab === 3 && (
          <Card variant="outlined" sx={{ borderRadius: '8px' }}>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>Optimization Suggestions</Typography>
              <Typography variant="body2" color="text.secondary">
                Optimization recommendations based on your telemetry data.
              </Typography>
              {benchmarkResult?.bottleneck?.recommendations?.length > 0 ? (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>Workload Recommendations</Typography>
                  {benchmarkResult.bottleneck.recommendations.map((r, i) => (
                    <Alert key={i} severity="info" sx={{ mb: 1, borderRadius: '8px' }}>
                      <Typography variant="body2">{r}</Typography>
                    </Alert>
                  ))}
                </Box>
              ) : (
                <Alert severity="info" sx={{ mt: 2, borderRadius: '8px' }}>
                  Run a Workload Benchmark or Kernel Profile to receive optimization suggestions.
                </Alert>
              )}
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
                    backgroundColor: alpha('#3d3d3a', 0.3),
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
                        </Stack>
                      </CardContent>
                    </Card>
                    <Grid container spacing={3}>
                      {metricsToRender
                        .filter((m) => m.category === (metricsTab === 1 ? 'advanced' : 'essential'))
                        .map((metric) => (
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
                        ))}
                    </Grid>
                  </>
                )}
              </Stack>
            </CardContent>
          </Card>
        )}

        {/* Nav buttons for step 4 */}
        <Box sx={{ display: 'flex', justifyContent: 'flex-start', mt: 2 }}>
          <Button
            variant="outlined"
            startIcon={<ArrowBackIcon />}
            onClick={() => setTelemetryStep(3)}
            sx={{
              borderRadius: 2,
              fontWeight: 600,
              px: 4,
            }}
          >
            Back
          </Button>
        </Box>
        </React.Fragment>)}
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
