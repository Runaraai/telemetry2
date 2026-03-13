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
  BugReport as BugReportIcon,
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
  // Explicit backend URL for telemetry (GPU must reach this for remote_write)
  if (process.env.REACT_APP_BACKEND_URL) {
    return process.env.REACT_APP_BACKEND_URL.replace(/\/$/, '');
  }
  // Fallback to API URL if set
  if (process.env.REACT_APP_API_URL && process.env.REACT_APP_API_URL !== '') {
    return process.env.REACT_APP_API_URL.replace(/\/$/, '');
  }
  if (typeof window !== 'undefined') {
    const origin = window.location.origin;
    if (origin.includes('localhost') || origin.includes('127.0.0.1')) {
      return '';
    }
    return origin;
  }
  return '';
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
    // vLLM inference server metrics (scraped from vLLM /metrics endpoint via Prometheus)
    if (sample.prompt_tokens_per_second != null) {
      existing.prompt_tokens_per_second = Number(sample.prompt_tokens_per_second);
    }
    if (sample.vllm_requests_running != null) {
      existing.vllm_requests_running = Number(sample.vllm_requests_running);
    }
    if (sample.vllm_requests_waiting != null) {
      existing.vllm_requests_waiting = Number(sample.vllm_requests_waiting);
    }
    if (sample.vllm_gpu_cache_usage != null) {
      existing.vllm_gpu_cache_usage = Number(sample.vllm_gpu_cache_usage);
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
  // ── Inference metrics (vLLM / token exporter) ─────────────────────
  {
    id: 'tokens-per-second',
    metricKey: 'tokens_per_second',
    title: 'Generation Throughput',
    historicalTitle: 'Generation Throughput',
    unit: 'tokens/s',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    category: 'inference',
    description: 'Token generation throughput from vLLM (avg_generation_throughput_toks_per_s). Rate at which tokens are being generated.',
  },
  {
    id: 'prompt-tokens-per-second',
    metricKey: 'prompt_tokens_per_second',
    title: 'Prompt Throughput',
    historicalTitle: 'Prompt Throughput',
    unit: 'tokens/s',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    category: 'inference',
    description: 'Prompt token processing throughput from vLLM (avg_prompt_throughput_toks_per_s). Rate at which input prompt tokens are being processed.',
  },
  {
    id: 'requests-per-second',
    metricKey: 'requests_per_second',
    title: 'Requests per Second',
    historicalTitle: 'Requests per Second',
    unit: 'req/s',
    domain: [0, 'auto'],
    icon: SpeedIcon,
    category: 'inference',
    description: 'Request throughput. Shows the rate at which inference requests are being processed.',
  },
  {
    id: 'vllm-requests-running',
    metricKey: 'vllm_requests_running',
    title: 'Requests Running',
    historicalTitle: 'Requests Running',
    unit: 'reqs',
    domain: [0, 'auto'],
    icon: SpeedIcon,
    category: 'inference',
    description: 'Number of requests currently being processed by vLLM (num_requests_running). Shows active concurrency.',
  },
  {
    id: 'vllm-requests-waiting',
    metricKey: 'vllm_requests_waiting',
    title: 'Requests Queued',
    historicalTitle: 'Requests Queued',
    unit: 'reqs',
    domain: [0, 'auto'],
    icon: SpeedIcon,
    category: 'inference',
    lowerIsBetter: true,
    description: 'Number of requests waiting in the queue (num_requests_waiting). A sustained non-zero value indicates the server is at capacity.',
  },
  {
    id: 'vllm-gpu-cache',
    metricKey: 'vllm_gpu_cache_usage',
    title: 'KV Cache Usage',
    historicalTitle: 'KV Cache Usage',
    unit: '%',
    domain: [0, 100],
    icon: MemoryIcon,
    category: 'inference',
    description: 'GPU KV cache utilization percentage (gpu_cache_usage_perc). High values mean the cache is nearly full; may cause requests to queue.',
  },
  {
    id: 'ttft-p50',
    metricKey: 'ttft_p50_ms',
    title: 'Time to First Token (P50)',
    historicalTitle: 'Time to First Token (P50)',
    unit: 'ms',
    domain: [0, 'auto'],
    icon: TimelineIcon,
    category: 'inference',
    lowerIsBetter: true,
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
    category: 'inference',
    lowerIsBetter: true,
    description: 'P95 time to first token in milliseconds. 95th percentile latency — useful for catching tail latency spikes.',
  },
  {
    id: 'cost-per-watt',
    metricKey: 'cost_per_watt',
    title: 'Performance per Watt',
    historicalTitle: 'Performance per Watt',
    unit: 'tokens/s/W',
    domain: [0, 'auto'],
    icon: AttachMoneyIcon,
    category: 'inference',
    description: 'Performance efficiency: tokens generated per second per watt of power consumed. Higher values indicate better energy efficiency.',
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
];

const ENTERPRISE_METRIC_IDS = new Set([
  'gpu-util',
  'sm-util',
  'sm-occupancy',
  'memory-util',
]);

const MetricChartComponent = ({ title, metricKey, unit, domain, data, gpuIds, icon: IconComponent, description, activeRun, sshHost, sshUser, sshKey, lowerIsBetter }) => {
  const isTokenMetric = ['tokens_per_second', 'prompt_tokens_per_second', 'requests_per_second',
    'ttft_p50_ms', 'ttft_p95_ms', 'cost_per_watt',
    'vllm_requests_running', 'vllm_requests_waiting', 'vllm_gpu_cache_usage'].includes(metricKey);
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
    trendDirection === 'flat' ? theme.palette.text.secondary :
    (trendDirection === 'up') !== lowerIsBetter ? theme.palette.success.main :
    theme.palette.error.main;

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
  const [sshUser, setSshUser] = useState('root');
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
  const [deploymentJobs, setDeploymentJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [queueStats, setQueueStats] = useState(null);
  const [metricView] = useState('infra');
  const [activityLog, setActivityLog] = useState([]);
  const [profilingResult, setProfilingResult] = useState(null);
  const [profilingResultRunId, setProfilingResultRunId] = useState(null);
  const [kernelRunLoading, setKernelRunLoading] = useState(false);
  const [logsDialogOpen, setLogsDialogOpen] = useState(false);
  const [logsContent, setLogsContent] = useState(null);
  const [logsLoading, setLogsLoading] = useState(false);

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
      if (data.sshUser && data.sshUser !== 'ubuntu') {
        setSshUser(data.sshUser);
      }
      // ubuntu is normalized to root (root is default for GPU instances)
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
        // vLLM inference server metrics
        if (sample.prompt_tokens_per_second != null) {
          existing.prompt_tokens_per_second = Number(sample.prompt_tokens_per_second);
        }
        if (sample.vllm_requests_running != null) {
          existing.vllm_requests_running = Number(sample.vllm_requests_running);
        }
        if (sample.vllm_requests_waiting != null) {
          existing.vllm_requests_waiting = Number(sample.vllm_requests_waiting);
        }
        if (sample.vllm_gpu_cache_usage != null) {
          existing.vllm_gpu_cache_usage = Number(sample.vllm_gpu_cache_usage);
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
      // Eagerly fetch recent metrics from API so charts render instantly
      // instead of waiting for WebSocket data (which can take 30s+)
      (async () => {
        try {
          const metricsResp = await apiService.getTelemetryMetrics(activeRun.run_id, { limit: 300 });
          const samples = metricsResp?.metrics || [];
          if (samples.length > 0) {
            enqueueRealtimeSamples(samples);
            setLastDataReceivedAt(Date.now());
          }
        } catch (err) {
          console.warn('Eager metric fetch failed (non-fatal)', err);
        }
      })();

      // Close any existing connection before connecting to new run_id
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
      connectWebSocket(activeRun.run_id);
    }
  }, [activeRun, monitoringState, connectWebSocket, enqueueRealtimeSamples]);

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
    if (!backendUrl || !backendUrl.startsWith('http')) {
      setError('Backend URL required. Set a routable URL (e.g. http://your-server:8000) that the GPU instance can reach for metrics.');
      appendLog('error', 'Backend URL must be a valid http:// or https:// URL reachable from the GPU.');
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
        const payload = {
          run_id: run.run_id,
          preserve_data: preserveData,
          ssh_host: sshHost || undefined,
          ssh_user: sshUser || undefined,
          pem_base64: sshKey ? btoa(sshKey) : undefined,
        };
        await apiService.teardownTelemetryStack(instanceId, payload);
      } catch (err) {
        console.warn('Failed to teardown telemetry stack', err);
      }
    },
    [instanceId, preserveData, sshHost, sshUser, sshKey]
  );

  const handleViewLogs = useCallback(async () => {
    if (!instanceId || !activeRun || !sshHost || !sshUser || !sshKey) return;
    setLogsDialogOpen(true);
    setLogsLoading(true);
    setLogsContent(null);
    try {
      const data = await apiService.fetchTelemetryLogs(instanceId, {
        run_id: activeRun.run_id,
        ssh_host: sshHost,
        ssh_user: sshUser,
        pem_base64: btoa(sshKey),
        service: 'all',
        tail: 100,
      });
      setLogsContent(data.logs || {});
    } catch (err) {
      setLogsContent({ _error: friendlyError(err, 'Failed to fetch logs') });
    } finally {
      setLogsLoading(false);
    }
  }, [instanceId, activeRun, sshHost, sshUser, sshKey]);

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
          {['Instance Connection', 'Telemetry'].map((label, idx) => (
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
              {idx < 1 && (
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
            <Grid container spacing={3} sx={{ mt: 2 }}>
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
                  placeholder="root"
                  helperText="SSH username (usually 'root' or 'ubuntu')"
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
                  helperText="URL the GPU instance can reach (e.g. http://your-server-ip:8000). Required for metrics."
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
            <Tooltip title="View exporter logs (for debugging GPU metrics)">
              <span>
                <Button
                  variant="outlined"
                  startIcon={<BugReportIcon />}
                  onClick={handleViewLogs}
                  disabled={!activeRun || !sshHost || !sshKey}
                >
                  View Logs
                </Button>
              </span>
            </Tooltip>
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

        {/* Step 1: Telemetry */}
        {telemetryStep === 1 && (<React.Fragment>
        {monitoringState === 'deploying' && (
          <Alert severity="info">Waiting for monitoring stack to become healthy...</Alert>
        )}
        {wsReconnecting && (
          <Alert severity="warning" icon={<CircularProgress size={16} />} sx={{ mb: 1 }}>
            WebSocket disconnected — reconnecting with exponential backoff (attempt {wsReconnectAttemptRef.current})...
          </Alert>
        )}
        {monitoringState === 'running' && realtimeChart.data.length === 0 && (
          <Box sx={{
            mb: 2,
            p: 2,
            borderRadius: 2,
            border: '1px solid #3d3d3a',
            bgcolor: 'rgba(26, 26, 24, 0.6)',
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
          }}>
            <CircularProgress size={16} sx={{ color: '#a8a8a0' }} />
            <Typography variant="body2" sx={{ color: '#a8a8a0' }}>
              Loading metrics for run <code style={{ fontSize: '0.85em', color: '#d4d4d4' }}>{activeRun?.run_id?.substring(0, 8)}</code>...
              {' '}If this persists, try stopping and restarting monitoring.
            </Typography>
          </Box>
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
          {['Overview', 'Inference', 'Advanced Metrics', 'Bottleneck', 'Optimization'].map((label, idx) => (
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
                    lowerIsBetter={metric.lowerIsBetter}
                  />
                </Grid>
              ))}
          </Grid>
        )}

        {metricsTab === 1 && (
          <Box>
            {realtimeChart.data.length > 0 && !realtimeChart.data.some(d =>
              d.tokens_per_second != null || d.prompt_tokens_per_second != null ||
              d.vllm_requests_running != null || d.vllm_gpu_cache_usage != null
            ) && (
              <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
                <Typography variant="body2">
                  No inference metrics yet. vLLM must be running on the instance and Prometheus must be scraping port 8000.
                  Start your inference server, then click <strong>Stop Monitoring → Start Monitoring</strong> to redeploy Prometheus with vLLM scraping enabled.
                </Typography>
              </Alert>
            )}
            <Grid container spacing={3}>
              {metricsToRender
                .filter((m) => m.category === 'inference')
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
                      lowerIsBetter={metric.lowerIsBetter}
                    />
                  </Grid>
                ))}
            </Grid>
          </Box>
        )}

        {metricsTab === 2 && (
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
                    lowerIsBetter={metric.lowerIsBetter}
                  />
                </Grid>
              ))}
          </Grid>
        )}

        {metricsTab === 3 && (
          <Card variant="outlined" sx={{ borderRadius: '8px' }}>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>Bottleneck Analysis</Typography>
              <Typography variant="body2" color="text.secondary">
                Bottleneck detection results appear here when integrated with workflow runs.
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
                  Bottleneck analysis is available when integrated with workflow runs.
                </Alert>
              )}
            </CardContent>
          </Card>
        )}

        {metricsTab === 4 && (
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
                  Optimization suggestions are available when integrated with workflow runs.
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
                              lowerIsBetter={metric.lowerIsBetter}
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

        {/* Nav buttons for step 1 */}
        <Box sx={{ display: 'flex', justifyContent: 'flex-start', mt: 2 }}>
          <Button
            variant="outlined"
            startIcon={<ArrowBackIcon />}
            onClick={() => setTelemetryStep(0)}
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

      {/* Exporter Logs Dialog */}
      <Dialog
        open={logsDialogOpen}
        onClose={() => setLogsDialogOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{ sx: { minHeight: '60vh' } }}
      >
        <DialogTitle>Telemetry Exporter Logs</DialogTitle>
        <DialogContent>
          {logsLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : logsContent ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {Object.entries(logsContent).map(([service, log]) => (
                <Paper key={service} variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1, fontFamily: 'monospace' }}>
                    {service}
                  </Typography>
                  <Box
                    component="pre"
                    sx={{
                      fontSize: '0.7rem',
                      fontFamily: 'monospace',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                      maxHeight: 200,
                      overflow: 'auto',
                      m: 0,
                    }}
                  >
                    {log}
                  </Box>
                </Paper>
              ))}
            </Box>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLogsDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TelemetryTab;
