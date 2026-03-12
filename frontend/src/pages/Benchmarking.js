import React, { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Grid,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  CircularProgress,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Button,
  Stack,
  TableSortLabel,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  Checkbox,
  FormControlLabel,
  DialogActions,
  Slider,
  TextField,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  LinearProgress,
  Tooltip,
  AlertTitle,
} from '@mui/material';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer,
  BarChart,
  Bar,
  ComposedChart,
  Area,
  ErrorBar,
  ScatterChart,
  Scatter,
  ZAxis
} from 'recharts';
import { 
  Memory as MemoryIcon, 
  Refresh as RefreshIcon,
  AttachMoney as AttachMoneyIcon,
  PowerSettingsNew as PowerIcon,
  Storage as StorageIcon,
  Computer as ComputerIcon,
  ShowChart as ShowChartIcon,
  GetApp as GetAppIcon,
  FilterList as FilterListIcon,
  Cloud as CloudIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Info as InfoIcon,
  PlayArrow as PlayArrowIcon,
  Description as DescriptionIcon,
  Timeline as TimelineIcon,
  Dashboard as DashboardIcon,
  CloudDownload as CloudDownloadIcon,
  ExpandMore as ExpandMoreIcon,
  Terminal as TerminalIcon,
  Settings as SettingsIcon,
  CheckCircleOutline as CheckCircleOutlineIcon,
  RocketLaunch as RocketLaunchIcon,
  Speed as SpeedIcon,
  VpnKey as VpnKeyIcon,
} from '@mui/icons-material';
import apiService, { friendlyError } from '../services/api';
import SystemBenchmarkDashboard from '../components/SystemBenchmarkDashboard';
import ProvisioningTab from '../components/ProvisioningTab';
import WorkflowStepper from '../components/WorkflowStepper';
import { alpha, useTheme } from '@mui/material';
import { useUI } from '../components/ui/UIProvider';

// Inline results card for benchmark (workload metrics)
const BenchmarkResultsCard = ({ runId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const fetchResults = async () => {
      try {
        setLoading(true);
        const result = await apiService.getTelemetryRunProfile(runId);
        if (!cancelled) setData(result);
      } catch (e) {
        if (!cancelled) setError(e.message || 'Failed to load results');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchResults();
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) return <Box sx={{ mt: 2, textAlign: 'center' }}><CircularProgress size={24} /><Typography variant="body2" sx={{ mt: 1 }}>Loading benchmark results...</Typography></Box>;
  if (error) return <Alert severity="error" sx={{ mt: 2, borderRadius: 2 }}>{error}</Alert>;
  if (!data) return null;

  const wm = data.workload_metrics || {};
  const metrics = [
    { label: 'TTFT (avg)', value: wm.ttft_avg_ms != null ? `${Number(wm.ttft_avg_ms).toFixed(1)} ms` : 'N/A' },
    { label: 'TTFT (p99)', value: wm.ttft_p99_ms != null ? `${Number(wm.ttft_p99_ms).toFixed(1)} ms` : 'N/A' },
    { label: 'TPOT (avg)', value: wm.tpot_avg_ms != null ? `${Number(wm.tpot_avg_ms).toFixed(1)} ms` : 'N/A' },
    { label: 'TPOT (p99)', value: wm.tpot_p99_ms != null ? `${Number(wm.tpot_p99_ms).toFixed(1)} ms` : 'N/A' },
    { label: 'Throughput (req/s)', value: wm.throughput_req_sec != null ? Number(wm.throughput_req_sec).toFixed(2) : 'N/A' },
    { label: 'Throughput (tok/s)', value: wm.throughput_tok_sec != null ? Number(wm.throughput_tok_sec).toFixed(1) : 'N/A' },
    { label: 'Requests', value: wm.successful_requests != null ? `${wm.successful_requests}/${wm.num_requests || '?'}` : 'N/A' },
    { label: 'E2E Latency (avg)', value: wm.e2e_latency_avg_ms != null ? `${Number(wm.e2e_latency_avg_ms).toFixed(0)} ms` : 'N/A' },
  ];

  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1.5 }}>Benchmark Results</Typography>
      <Grid container spacing={1.5}>
        {metrics.map((m) => (
          <Grid item xs={6} sm={3} key={m.label}>
            <Paper sx={{ p: 1.5, borderRadius: 2, textAlign: 'center', backgroundColor: 'rgba(30, 69, 48, 0.3)' }}>
              <Typography variant="caption" color="text.secondary">{m.label}</Typography>
              <Typography variant="h6" fontWeight={700} sx={{ fontSize: '1.1rem' }}>{m.value}</Typography>
            </Paper>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
};

// Inline results card for kernel profiling
const KernelResultsCard = ({ runId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const fetchResults = async () => {
      try {
        setLoading(true);
        const result = await apiService.getTelemetryRunProfile(runId);
        if (!cancelled) setData(result);
      } catch (e) {
        if (!cancelled) setError(e.message || 'Failed to load results');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchResults();
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) return <Box sx={{ mt: 2, textAlign: 'center' }}><CircularProgress size={24} /><Typography variant="body2" sx={{ mt: 1 }}>Loading kernel results...</Typography></Box>;
  if (error) return <Alert severity="error" sx={{ mt: 2, borderRadius: 2 }}>{error}</Alert>;
  if (!data) return null;

  const kp = data.kernel_profile || {};
  const ba = data.bottleneck_analysis || {};
  const categories = kp.categories || [];

  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1.5 }}>Kernel Profile Results</Typography>
      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        <Grid item xs={6} sm={3}>
          <Paper sx={{ p: 1.5, borderRadius: 2, textAlign: 'center', backgroundColor: 'rgba(46, 26, 74, 0.3)' }}>
            <Typography variant="caption" color="text.secondary">Total CUDA Time</Typography>
            <Typography variant="h6" fontWeight={700} sx={{ fontSize: '1.1rem' }}>{kp.total_cuda_time_ms != null ? `${Number(kp.total_cuda_time_ms).toFixed(1)} ms` : 'N/A'}</Typography>
          </Paper>
        </Grid>
        <Grid item xs={6} sm={3}>
          <Paper sx={{ p: 1.5, borderRadius: 2, textAlign: 'center', backgroundColor: 'rgba(46, 26, 74, 0.3)' }}>
            <Typography variant="caption" color="text.secondary">Est. TFLOPS</Typography>
            <Typography variant="h6" fontWeight={700} sx={{ fontSize: '1.1rem' }}>{kp.estimated_tflops != null ? Number(kp.estimated_tflops).toFixed(1) : 'N/A'}</Typography>
          </Paper>
        </Grid>
        <Grid item xs={6} sm={3}>
          <Paper sx={{ p: 1.5, borderRadius: 2, textAlign: 'center', backgroundColor: 'rgba(46, 26, 74, 0.3)' }}>
            <Typography variant="caption" color="text.secondary">Primary Bottleneck</Typography>
            <Typography variant="h6" fontWeight={700} sx={{ fontSize: '1.1rem' }}>{ba.primary_bottleneck || 'N/A'}</Typography>
          </Paper>
        </Grid>
        <Grid item xs={6} sm={3}>
          <Paper sx={{ p: 1.5, borderRadius: 2, textAlign: 'center', backgroundColor: 'rgba(46, 26, 74, 0.3)' }}>
            <Typography variant="caption" color="text.secondary">Compute Util</Typography>
            <Typography variant="h6" fontWeight={700} sx={{ fontSize: '1.1rem' }}>{ba.compute_utilization_pct != null ? `${Number(ba.compute_utilization_pct).toFixed(1)}%` : 'N/A'}</Typography>
          </Paper>
        </Grid>
      </Grid>

      {categories.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Kernel Categories</Typography>
          <TableContainer component={Paper} sx={{ borderRadius: 2, backgroundColor: 'rgba(46, 26, 74, 0.15)' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Category</TableCell>
                  <TableCell align="right">Count</TableCell>
                  <TableCell align="right">Total (ms)</TableCell>
                  <TableCell align="right">% of Total</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {categories.map((cat, idx) => (
                  <TableRow key={idx}>
                    <TableCell>{cat.category_name}</TableCell>
                    <TableCell align="right">{cat.kernel_count ?? cat.count ?? 'N/A'}</TableCell>
                    <TableCell align="right">{cat.total_time_ms != null ? Number(cat.total_time_ms).toFixed(2) : 'N/A'}</TableCell>
                    <TableCell align="right">{cat.percentage != null ? `${Number(cat.percentage).toFixed(1)}%` : 'N/A'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}
    </Box>
  );
};

const Benchmarking = () => {
  const theme = useTheme();
  
  // State management
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const location = useLocation();
  const navigate = useNavigate();
  
  // System selection
  const [availableSystems, setAvailableSystems] = useState([]);
  const [selectedSystem, setSelectedSystem] = useState('');
  const [systemData, setSystemData] = useState(null);
  const [systemLoading, setSystemLoading] = useState(false);
  const [systemLastUpdated, setSystemLastUpdated] = useState(null);
  
  // GPU metrics
  const [gpuMetrics, setGpuMetrics] = useState(null);
  const [gpuMetricsLoading, setGpuMetricsLoading] = useState(false);
  const [gpuLastUpdated, setGpuLastUpdated] = useState(null);
  
  // Sorting and grouping
  const [sortBy, setSortBy] = useState('timestamp');
  const [sortDirection, setSortDirection] = useState('desc');
  const [groupBy, setGroupBy] = useState('batch_size');
  
  // Export
  const [exportDialog, setExportDialog] = useState(false);
  
  // Run Workload tab state
  const [rwCloudProvider, setRwCloudProvider] = useState('scaleway'); // 'scaleway'
  const [rwModel, setRwModel] = useState('Llama4-Scout');
  const [rwSystem, setRwSystem] = useState('8xH100');
  const [rwVendor, setRwVendor] = useState('Lambda');
  const [rwInputLen, setRwInputLen] = useState(1);
  const [rwOutputLen, setRwOutputLen] = useState(16384);
  const [rwBatchSize, setRwBatchSize] = useState(64);
  const [rwDataType, setRwDataType] = useState('FP16');
  const [rwCoreClock, setRwCoreClock] = useState(100);
  const [rwHbmClock, setRwHbmClock] = useState(100);
  const [rwNvlinkClock, setRwNvlinkClock] = useState(100);
  const [rwIterations, setRwIterations] = useState(1);
  const [instanceData, setInstanceData] = useState(null);
  const [rwSshHost, setRwSshHost] = useState('');
  const [rwSshUser, setRwSshUser] = useState('ubuntu');
  const [rwSshKey, setRwSshKey] = useState('');
  const [runStatus, setRunStatus] = useState(null);
  const [clockSettingStatus, setClockSettingStatus] = useState({ core: null, hbm: null, nvlink: null });
  const [clockSettingLoading, setClockSettingLoading] = useState({ core: false, hbm: false, nvlink: false });
  
  // Setup state
  const [setupStatus, setSetupStatus] = useState({ loading: false, status: null, message: null, pid: null });
  const [setupCheckLoading, setSetupCheckLoading] = useState(false);
  
  // vLLM benchmark state
  const [vllmModelName, setVllmModelName] = useState('RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic');
  const [vllmModelPath, setVllmModelPath] = useState('/home/ubuntu/BM/models/scout17b-fp8dyn');
  const [vllmMaxTokens, setVllmMaxTokens] = useState('');
  const [vllmMaxModelLen, setVllmMaxModelLen] = useState('');
  const [vllmMaxNumSeqs, setVllmMaxNumSeqs] = useState('');
  const [vllmGpuMemUtil, setVllmGpuMemUtil] = useState('');
  const [vllmTensorParallel, setVllmTensorParallel] = useState('');
  const [vllmNumRequests, setVllmNumRequests] = useState(10);
  const [vllmBatchSize, setVllmBatchSize] = useState(1);
  const [vllmInputSeqLen, setVllmInputSeqLen] = useState(100);
  const [vllmOutputSeqLen, setVllmOutputSeqLen] = useState(100);
  const [vllmPrompt, setVllmPrompt] = useState('What is the capital of France?');
  const [vllmBenchmarkRunning, setVllmBenchmarkRunning] = useState(false);
  const [vllmDownloadModel, setVllmDownloadModel] = useState(true);
  const [allowMigration, setAllowMigration] = useState(false);
  const [migrateDialogOpen, setMigrateDialogOpen] = useState(false);
  const [aggregatedCatalog, setAggregatedCatalog] = useState([]);
  const [aggregatedCatalogLoading, setAggregatedCatalogLoading] = useState(false);
  const [selectedTarget, setSelectedTarget] = useState(null);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  
  // Workflow state (step-by-step)
  const [selectedModel, setSelectedModel] = useState('Qwen/Qwen3.5-9B');
  const [workflowSetupStatus, setWorkflowSetupStatus] = useState({ loading: false, status: null, message: null, workflowId: null, logs: '' });
  const [workflowCheckStatus, setWorkflowCheckStatus] = useState({ loading: false, status: null, message: null, workflowId: null, logs: '' });
  const [workflowDeployStatus, setWorkflowDeployStatus] = useState({ loading: false, status: null, message: null, workflowId: null, logs: '' });
  const [workflowBenchmarkStatus, setWorkflowBenchmarkStatus] = useState({ loading: false, status: null, message: null, workflowId: null, logs: '', errorDetails: null, runId: null });
  const [workflowKernelStatus, setWorkflowKernelStatus] = useState({ loading: false, status: null, message: null, workflowId: null, logs: '', errorDetails: null, runId: null });
  const [workflowEvents, setWorkflowEvents] = useState([]);
  const workflowProgressRef = useRef({
    setup: '',
    check: '',
    deploy: '',
    benchmark: '',
    kernel_profile: '',
  });
  
  // Benchmark parameters for workflow
  const [workflowInputSeqLen, setWorkflowInputSeqLen] = useState(256);
  const [workflowOutputSeqLen, setWorkflowOutputSeqLen] = useState(128);
  const [workflowNumRequests, setWorkflowNumRequests] = useState(50);
  const [workflowRequestRate, setWorkflowRequestRate] = useState(10.0);
  const [workflowMaxConcurrency, setWorkflowMaxConcurrency] = useState(4);
  const [workflowKernelRequests, setWorkflowKernelRequests] = useState(20);
  const { showToast } = useUI();

  // Environment check state
  const [envState, setEnvState] = useState(null); // null = not checked yet
  const [envLoading, setEnvLoading] = useState(false);

  // Inference server state
  const [inferenceStatus, setInferenceStatus] = useState({ running: false, model: null, url: null, uptime: null, error: null });
  const [inferenceLoading, setInferenceLoading] = useState(false);
  const [inferenceAdvanced, setInferenceAdvanced] = useState(false);
  const [infTensorParallel, setInfTensorParallel] = useState('');
  const [infMaxModelLen, setInfMaxModelLen] = useState('');
  const [infMaxNumSeqs, setInfMaxNumSeqs] = useState('');
  const [infGpuMemUtil, setInfGpuMemUtil] = useState('');

  // Saved connections
  const [savedConnections, setSavedConnections] = useState([]);
  const [selectedConnection, setSelectedConnection] = useState('new');
  const [connectionName, setConnectionName] = useState('');

  const getWorkflowModelPath = (modelName = selectedModel) => (
    rwCloudProvider === 'scaleway'
      ? `/scratch/BM/models/${modelName.split('/').pop()}`
      : `/home/ubuntu/BM/models/${modelName.split('/').pop()}`
  );

  // Persisted workflow completion state from backend (setup_completed_at, etc.)
  const [persistedWorkflowState, setPersistedWorkflowState] = useState(null);

  // Phase "complete" = runtime status completed OR persisted state shows it was done (unlocks later phases without re-running)
  const setupComplete = workflowSetupStatus.status === 'completed' || workflowSetupStatus.status === 'reboot_required' || !!persistedWorkflowState?.setup_completed_at;
  const checkComplete = workflowCheckStatus.status === 'completed' || !!persistedWorkflowState?.check_completed_at;
  const deployComplete = workflowDeployStatus.status === 'completed' || !!persistedWorkflowState?.vllm_deployed_at;

  // Load saved connections on mount
  useEffect(() => {
    apiService.listConnections().then(setSavedConnections).catch(() => {});
  }, []);

  // Auto-populate SSH private key from backend config
  useEffect(() => {
    apiService.getSSHPrivateKey()
      .then((key) => { if (key && !rwSshKey) setRwSshKey(key); })
      .catch(() => {}); // silently ignore if not configured
  }, []); // eslint-disable-line

  // Hydrate persisted workflow state whenever ssh host changes
  useEffect(() => {
    if (!rwSshHost) { setPersistedWorkflowState(null); return; }
    apiService.getWorkflowState(rwSshHost).then(setPersistedWorkflowState).catch(() => {});
  }, [rwSshHost]);

  const handleSelectConnection = async (connId) => {
    setSelectedConnection(connId);
    if (connId === 'new') {
      setRwSshHost(''); setRwSshUser('ubuntu'); setRwSshKey('');
      setEnvState(null); setInferenceStatus({ running: false, model: null, url: null, uptime: null, error: null });
      return;
    }
    try {
      const conn = await apiService.getConnection(connId);
      setRwSshHost(conn.ssh_host || '');
      setRwSshUser(conn.ssh_user || 'ubuntu');
      setRwCloudProvider(conn.cloud_provider || 'lambda');
      if (conn.pem_base64) {
        try { setRwSshKey(window.atob(conn.pem_base64)); } catch { setRwSshKey(conn.pem_base64); }
      }
      setConnectionName(conn.name || '');
      // Auto-check environment
      handleCheckEnvironment(conn.ssh_host, conn.ssh_user, conn.pem_base64, conn.cloud_provider);
    } catch (e) {
      console.error('Failed to load connection:', e);
    }
  };

  const handleSaveConnection = async () => {
    if (!rwSshHost || !connectionName) return;
    try {
      const pemBase64 = encodePemToBase64(rwSshKey);
      await apiService.saveConnection({
        name: connectionName || rwSshHost,
        ssh_host: rwSshHost,
        ssh_user: rwSshUser,
        pem_base64: pemBase64,
        cloud_provider: rwCloudProvider,
      });
      const updated = await apiService.listConnections();
      setSavedConnections(updated);
      appendWorkflowEvent('connection', 'success', `Connection "${connectionName || rwSshHost}" saved`);
    } catch (e) {
      appendWorkflowEvent('connection', 'error', `Failed to save: ${e.message}`);
    }
  };

  const handleCheckEnvironment = async (host, user, pemB64, provider) => {
    const sshHost = host || rwSshHost;
    const sshUser = user || rwSshUser;
    const cloudProvider = provider || rwCloudProvider;
    const pemBase64 = pemB64 || encodePemToBase64(rwSshKey);
    if (!sshHost || !pemBase64) return;

    setEnvLoading(true);
    setEnvState(null);
    try {
      const result = await apiService.checkEnvironmentState({
        ssh_host: sshHost,
        ssh_user: sshUser,
        pem_base64: pemBase64,
        cloud_provider: cloudProvider,
        model_path: getWorkflowModelPath(selectedModel),
      });
      setEnvState(result);
      if (result.vllm_running) {
        setInferenceStatus({ running: true, model: result.vllm_model, url: `http://${sshHost}:8000`, uptime: null, error: null });
      }
      appendWorkflowEvent('environment', 'info', `Environment check: driver=${result.driver} docker=${result.docker} model=${result.model} vllm=${result.vllm_running}`);
    } catch (e) {
      setEnvState({ error: e.message });
      appendWorkflowEvent('environment', 'error', `Environment check failed: ${e.message}`);
    } finally {
      setEnvLoading(false);
    }
  };

  const handleInferenceStart = async () => {
    if (!rwSshHost || !rwSshKey) return;
    setInferenceLoading(true);
    appendWorkflowEvent('inference', 'info', 'Starting inference server...');
    try {
      const pemBase64 = encodePemToBase64(rwSshKey);
      const modelPath = getWorkflowModelPath(selectedModel);
      const response = await apiService.inferenceStart({
        ssh_host: rwSshHost,
        ssh_user: rwSshUser,
        pem_base64: pemBase64,
        model_path: modelPath,
        cloud_provider: rwCloudProvider,
        tensor_parallel_size: infTensorParallel ? Number(infTensorParallel) : null,
        max_model_len: infMaxModelLen ? Number(infMaxModelLen) : null,
        max_num_seqs: infMaxNumSeqs ? Number(infMaxNumSeqs) : null,
        gpu_memory_utilization: infGpuMemUtil ? Number(infGpuMemUtil) : null,
      });
      // Also update deploy status so existing benchmark buttons work
      setWorkflowDeployStatus({ loading: false, status: 'started', message: response.message, workflowId: response.workflow_id, logs: '' });
      appendWorkflowEvent('inference', 'info', `Starting: ${response.workflow_id}`);

      // Poll for completion
      const pollLogs = setInterval(async () => {
        try {
          const result = await apiService.getWorkflowLogs(response.workflow_id, 'deploy');
          trackWorkflowProgress('deploy', result.status, result.message);
          setWorkflowDeployStatus(prev => ({
            ...prev,
            logs: result.logs || '',
            status: result.status || prev.status,
            message: result.message || prev.message,
          }));
          if (result.status === 'completed') {
            clearInterval(pollLogs);
            setInferenceStatus({ running: true, model: modelPath, url: `http://${rwSshHost}:8000`, uptime: null, error: null });
            setInferenceLoading(false);
            appendWorkflowEvent('inference', 'success', 'Inference server is running');
          } else if (result.status === 'failed') {
            clearInterval(pollLogs);
            setInferenceLoading(false);
            appendWorkflowEvent('inference', 'error', result.message || 'Failed to start');
          }
        } catch (e) {
          console.error('Poll inference logs failed:', e);
        }
      }, 3000);
      setTimeout(() => { clearInterval(pollLogs); setInferenceLoading(false); }, 600000);
    } catch (e) {
      setInferenceLoading(false);
      appendWorkflowEvent('inference', 'error', e.response?.data?.detail || e.message);
    }
  };

  const handleInferenceStop = async () => {
    if (!rwSshHost || !rwSshKey) return;
    setInferenceLoading(true);
    try {
      const pemBase64 = encodePemToBase64(rwSshKey);
      await apiService.inferenceStop({ ssh_host: rwSshHost, ssh_user: rwSshUser, pem_base64: pemBase64 });
      setInferenceStatus({ running: false, model: null, url: null, uptime: null, error: null });
      setWorkflowDeployStatus({ loading: false, status: null, message: null, workflowId: null, logs: '' });
      appendWorkflowEvent('inference', 'info', 'Inference server stopped');
    } catch (e) {
      appendWorkflowEvent('inference', 'error', `Stop failed: ${e.message}`);
    } finally {
      setInferenceLoading(false);
    }
  };

  const appendWorkflowEvent = (phase, level, message) => {
    const entry = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      ts: new Date().toISOString(),
      phase,
      level,
      message,
    };
    setWorkflowEvents((prev) => [entry, ...prev].slice(0, 250));
  };

  const trackWorkflowProgress = (phase, statusValue, messageValue) => {
    const statusText = (statusValue || '').toString().toLowerCase();
    const messageText = (messageValue || '').toString().trim();
    if (!statusText && !messageText) return;

    const signature = `${statusText}|${messageText}`;
    if (workflowProgressRef.current[phase] === signature) return;
    workflowProgressRef.current[phase] = signature;

    let level = 'info';
    if (statusText === 'failed' || statusText === 'error') {
      level = 'error';
    } else if (statusText === 'completed') {
      level = 'success';
    }

    appendWorkflowEvent(phase, level, messageText || `Status: ${statusText}`);
  };

  const getEventColor = (level) => {
    if (level === 'error') return 'error';
    if (level === 'success') return 'success';
    if (level === 'warning') return 'warning';
    return 'info';
  };
  
  // Helper function to safely format numbers
  const safeToFixed = (value, decimals = 2) => {
    if (value === null || value === undefined || isNaN(value)) {
      return 'N/A';
    }
    return Number(value).toFixed(decimals);
  };

  const getCurrentInstanceCost = () => {
    const data = instanceData;
    if (!data) return null;
    if (typeof data.priceCentsPerHour === 'number') return data.priceCentsPerHour / 100;
    if (typeof data.cost_per_hour_usd === 'number') return data.cost_per_hour_usd;
    if (typeof data.priceEurHour === 'number') return data.priceEurHour * 1.1;
    if (typeof data.hourly_price === 'number') return data.hourly_price;
    if (typeof data.costPerHour === 'number') return data.costPerHour;
    return null;
  };

  const currentInstanceCost = getCurrentInstanceCost();

  const handleOpenMigrateDialog = async () => {
    if (!allowMigration) return;
    setMigrateDialogOpen(true);
    if (aggregatedCatalog.length > 0) return;
    try {
      setAggregatedCatalogLoading(true);
      const items = await apiService.getAggregatedCatalog();
      setAggregatedCatalog(items || []);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to load catalog for migration');
    } finally {
      setAggregatedCatalogLoading(false);
    }
  };

  const getCostDelta = (targetCost) => {
    if (!currentInstanceCost || !targetCost) return null;
    const delta = targetCost - currentInstanceCost;
    return (delta / currentInstanceCost) * 100;
  };

  const migrationEnabled = allowMigration && (instanceData?.status || '').toLowerCase() === 'running';

  // Helper function to get display config type (show prefill for unknown H100)
  const getDisplayConfigType = (configType, system) => {
    if (configType === 'unknown' && system === 'H100') {
      return 'prefill';
    }
    return configType;
  };

  // Helper function to calculate file-specific metrics
  const getFileMetrics = (filename) => {
    if (!systemData?.results) return null;
    
    const fileResults = systemData.results.filter(r => r.filename === filename);
    if (fileResults.length === 0) return null;
    
    const metrics = ['throughput_tokens_per_second', 'sm_active_percent', 'power_draw_watts', 'performance_per_watt'];
    const fileMetrics = {};
    
    metrics.forEach(metric => {
      const values = fileResults.map(r => r[metric]).filter(v => v !== null && v !== undefined);
      if (values.length > 0) {
        fileMetrics[metric] = {
          avg: values.reduce((sum, val) => sum + val, 0) / values.length,
          min: Math.min(...values),
          max: Math.max(...values),
          count: values.length
        };
      } else {
        fileMetrics[metric] = { avg: 0, min: 0, max: 0, count: 0 };
      }
    });
    
    return fileMetrics;
  };

  // Helper to read core clock percent from result rows (supports multiple possible keys)
  const getCoreClockPercent = (row) => {
    const v = row?.core_clock_percent ?? row?.gpu_core_clock_percent ?? row?.core_clock_utilization_percent;
    return typeof v === 'number' ? v : (v ? Number(v) : null);
  };

  
  // Load available systems
  const loadAvailableSystems = async () => {
    setLoading(true);
    try {
      console.log('Loading available systems...');
      const response = await apiService.getDashboardSystems();
      console.log('Available systems response:', response);
      setAvailableSystems(response.systems || []);
      if (response.systems && response.systems.length > 0 && !selectedSystem) {
        setSelectedSystem(response.systems[0].name);
        console.log('Set selected system to:', response.systems[0].name);
      }
    } catch (error) {
      console.error('Failed to load available systems:', error);
    } finally {
      setLoading(false);
    }
  };

  // Load system data
  const loadSystemData = async (system) => {
    try {
      console.log('Loading system data for:', system);
      setSystemLoading(true);
      setError(null);

      const response = await apiService.getDashboardSystemData(system);
      console.log('System data response:', response);
      
      setSystemData(response);
    } catch (err) {
      console.error('Failed to load system data:', err);
      setError(`Failed to load data for system ${system}. Please try again.`);
    } finally {
      setSystemLoading(false);
    }
  };

  // Load GPU metrics
  const loadGpuMetrics = async (system) => {
    try {
      console.log('Loading GPU metrics for:', system);
      setGpuMetricsLoading(true);
      setError(null);

      const response = await apiService.getDashboardGpuMetrics(system);
      console.log('GPU metrics response:', response);
      
      setGpuMetrics(response);
    } catch (err) {
      console.error('Failed to load GPU metrics:', err);
      setError(`Failed to load GPU metrics for system ${system}. Please try again.`);
    } finally {
      setGpuMetricsLoading(false);
    }
  };

  // Handle clock setting
  const handleSetClock = async (clockType) => {
    if (!rwSshHost || !rwSshKey) {
      setClockSettingStatus(prev => ({ ...prev, [clockType]: 'Error: IP address and PEM path are required' }));
      return;
    }

    const clockValue = clockType === 'core' ? rwCoreClock : clockType === 'hbm' ? rwHbmClock : rwNvlinkClock;
    
    setClockSettingLoading(prev => ({ ...prev, [clockType]: true }));
    setClockSettingStatus(prev => ({ ...prev, [clockType]: null }));

    try {
      const params = {
        ip: rwSshHost,
        ssh_user: rwSshUser,
        pem_base64: encodePemToBase64(rwSshKey),
        clock_type: clockType,
        clock_percent: clockValue
      };
      const response = await apiService.setGpuClock(params);
      
      // Build detailed status message
      let statusMsg = response.message;
      if (response.gpu_type) {
        statusMsg += ` (${response.gpu_type})`;
      }
      if (response.warnings && response.warnings.length > 0) {
        statusMsg += ` - Warnings: ${response.warnings.length} command(s) had issues`;
      }
      if (response.diagnostics) {
        const diag = response.diagnostics;
        if (diag.gpu_name) {
          statusMsg += ` [GPU: ${diag.gpu_name}]`;
        }
        if (diag.throttle_reasons && diag.throttle_reasons.includes('Active')) {
          statusMsg += ' - ⚠ Throttling detected';
        }
      }
      
      setClockSettingStatus(prev => ({ ...prev, [clockType]: statusMsg }));
      
      // Show detailed output in console for debugging
      if (response.output) {
        console.log(`Clock setting output for ${clockType}:`, response.output);
      }
      if (response.diagnostics) {
        console.log(`Clock setting diagnostics for ${clockType}:`, response.diagnostics);
      }
      
      // Clear status after 8 seconds (longer to show detailed info)
      setTimeout(() => {
        setClockSettingStatus(prev => ({ ...prev, [clockType]: null }));
      }, 8000);
    } catch (error) {
      const errorDetail = error.response?.data?.detail || error.message;
      let errorMsg = `Error: ${errorDetail}`;
      
      // Provide helpful suggestions based on error
      if (errorDetail.includes('not support')) {
        errorMsg += '\n\nThis GPU may not support clock adjustments. Try a professional-grade GPU (A100, H100, Quadro, Tesla).';
      } else if (errorDetail.includes('permission') || errorDetail.includes('sudo')) {
        errorMsg += '\n\nEnsure SSH user has sudo permissions and nvidia-smi is accessible.';
      } else if (errorDetail.includes('SSH')) {
        errorMsg += '\n\nCheck SSH connection, IP address, and PEM file path.';
      }
      
      setClockSettingStatus(prev => ({ ...prev, [clockType]: errorMsg }));
      
      // Keep error message longer
      setTimeout(() => {
        setClockSettingStatus(prev => ({ ...prev, [clockType]: null }));
      }, 10000);
    } finally {
      setClockSettingLoading(prev => ({ ...prev, [clockType]: false }));
    }
  };

  // Handle sort
  const handleSort = (field) => {
    const isAsc = sortBy === field && sortDirection === 'asc';
    setSortDirection(isAsc ? 'desc' : 'asc');
    setSortBy(field);
  };

  // Get sorted data
  const getSortedData = (data) => {
    if (!sortBy) return data;
    
    return [...data].sort((a, b) => {
      const aVal = a[sortBy] || 0;
      const bVal = b[sortBy] || 0;
      
      if (sortDirection === 'asc') {
        return aVal > bVal ? 1 : -1;
      } else {
        return aVal < bVal ? 1 : -1;
      }
    });
  };

  // Get grouped data
  const getGroupedData = (data) => {
    console.log('getGroupedData called with data:', data);
    console.log('Data length:', data ? data.length : 'undefined');
    const grouped = {};
    
    data.forEach(row => {
      const groupKey = groupBy === 'batch_size' ? row.batch_size : 
                     groupBy === 'input_length' ? row.input_length : 
                     row.config_type;
      if (!grouped[groupKey]) {
        grouped[groupKey] = [];
      }
      grouped[groupKey].push(row);
    });
    
    // Sort groups and within each group
    const sortedGroups = Object.keys(grouped).sort((a, b) => {
      const aNum = parseFloat(a);
      const bNum = parseFloat(b);
      return aNum - bNum;
    });
    
    const result = sortedGroups.map(groupKey => ({
      groupKey,
      data: getSortedData(grouped[groupKey])
    }));
    console.log('getGroupedData result:', result);
    return result;
  };

  // Export functions
  const exportToJSON = () => {
    const dataToExport = {
      system: selectedSystem,
      systemData: systemData,
      exported_at: new Date().toISOString()
    };
    
    const blob = new Blob([JSON.stringify(dataToExport, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `benchmark_export_${selectedSystem}_${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    setExportDialog(false);
  };

  const exportToCSV = () => {
    if (!systemData || !systemData.results) return;
    
    // Create CSV headers
      const headers = [
      'Timestamp', 'Config Type', 'File', 'Batch Size', 'Input Length', 'Output Length',
      'Total Tokens', 'Total Requests', 'Duration (s)', 'Throughput (t/s)', 'Req/s',
      'Latency P50 (ms)', 'Latency P95 (ms)', 'TTFT P50 (ms)', 'TTFT P95 (ms)',
      'TBT P50 (ms)', 'TBT P95 (ms)', 'Prefill Lat (ms)', 'Decode Lat (ms)', 'Decode Thruput (t/s)',
      'GPU Util (%)', 'SM Active (%)', 'HBM BW Util (%)', 'HBM BW Raw (Gbps)',
      'NVLink Util (%)', 'NVLink BW Raw (Gbps)', 'Power Draw (W)', 
      'Perf/W (t/s/W)', 'Cost ($)', 'Perf/$ (t/s/$)'
    ];
    
    // Create CSV rows
    const rows = systemData.results.map(row => [
        row.timestamp,
      row.config_type,
      row.filename,
        row.batch_size,
        row.input_length,
        row.output_length,
        safeToFixed(row.total_tokens_generated, 0),
        safeToFixed(row.total_requests, 0),
        safeToFixed(row.duration_seconds, 2),
        safeToFixed(row.throughput_tokens_per_second, 2),
        safeToFixed(row.throughput_requests_per_second, 4),
        safeToFixed(row.latency_p50_ms, 2),
        safeToFixed(row.latency_p95_ms, 2),
        safeToFixed(row.ttft_p50_ms, 2),
        safeToFixed(row.ttft_p95_ms, 2),
        safeToFixed(row.tbt_p50_ms, 2),
        safeToFixed(row.tbt_p95_ms, 2),
        safeToFixed(row.prefill_latency_ms, 2),
        safeToFixed(row.decode_latency_ms, 2),
        safeToFixed(row.decode_throughput_tokens_per_second, 2),
        safeToFixed(row.gpu_utilization_percent, 2),
        safeToFixed(row.sm_active_percent, 2),
        safeToFixed(row.hbm_bandwidth_utilization_percent, 2),
        safeToFixed(row.hbm_bandwidth_raw_gbps, 2),
        safeToFixed(row.nvlink_bandwidth_utilization_percent, 4),
        safeToFixed(row.nvlink_bandwidth_raw_gbps, 2),
        safeToFixed(row.power_draw_watts, 2),
        safeToFixed(row.performance_per_watt, 4),
        safeToFixed(row.cost_usd, 4),
        safeToFixed(row.performance_per_dollar, 2)
    ]);
      
    // Combine headers and rows
      const csvContent = [
        headers.join(','),
        ...rows.map(row => row.join(','))
      ].join('\n');
      
      const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `benchmark_export_${selectedSystem}_${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    setExportDialog(false);
  };

  // Effects
  useEffect(() => {
    loadAvailableSystems();
  }, []);

  // Helper function to get PEM from localStorage
  // Helper function to encode SSH key to base64
  const encodePemToBase64 = (pemText) => {
    if (!pemText || !pemText.trim()) return null;
    try {
      const normalizedPem = pemText.replace(/\r\n/g, '\n').trim();

      // If the pasted value is already base64 (from stored creds), keep it as-is.
      const compact = normalizedPem.replace(/\s+/g, '');
      const base64Like = /^[A-Za-z0-9+/=]+$/.test(compact);
      if (base64Like && !normalizedPem.includes('BEGIN')) {
        try {
          const decoded = (typeof window !== 'undefined' && window.atob)
            ? window.atob(compact)
            : Buffer.from(compact, 'base64').toString('utf-8');
          if (decoded.includes('PRIVATE KEY')) {
            return compact;
          }
        } catch (e) {
          // Not valid base64 PEM, fall through and encode as plain text.
        }
      }

      if (typeof window !== 'undefined' && window.btoa) {
        if (typeof window.TextEncoder !== 'undefined') {
          const bytes = new window.TextEncoder().encode(normalizedPem);
          let binary = '';
          bytes.forEach((b) => {
            binary += String.fromCharCode(b);
          });
          return window.btoa(binary);
        }
        return window.btoa(normalizedPem);
      }
      // Fallback for Node.js environment (if needed)
      return Buffer.from(normalizedPem, 'utf-8').toString('base64');
    } catch (error) {
      console.error('Failed to encode PEM to base64:', error);
      return null;
    }
  };

  const getPemFromLocalStorage = () => {
    console.log('🔍 Starting PEM retrieval from localStorage...');
    
    // Try all possible provider keys
    const possibleKeys = [
      `cloudCreds_${rwVendor?.toLowerCase() || 'lambda'}`,
      'cloudCreds_lambda',
      'cloudCreds_aws'
    ];
    
    // Remove duplicates
    const uniqueKeys = [...new Set(possibleKeys)];
    
    console.log('🔍 Looking for PEM in localStorage keys:', uniqueKeys);
    console.log('🔍 Current vendor:', rwVendor);
    
    // First, let's see ALL localStorage keys
    const allLocalStorageKeys = Object.keys(localStorage);
    console.log('📋 All localStorage keys:', allLocalStorageKeys);
    
    // Try each key until we find a PEM
    for (const key of uniqueKeys) {
      try {
        const stored = localStorage.getItem(key);
        console.log(`🔍 Checking key "${key}":`, stored ? 'EXISTS' : 'NOT FOUND');
        
        if (stored) {
          const parsed = JSON.parse(stored);
          console.log(`📦 Found localStorage key "${key}":`, {
            hasPemBase64: !!parsed.pemBase64,
            pemName: parsed.pemName,
            pemBase64Length: parsed.pemBase64?.length,
            pemBase64Preview: parsed.pemBase64?.substring(0, 50) + '...',
            allKeys: Object.keys(parsed) // Debug: show all keys in the object
          });
          
          // Check for pemBase64 (case-insensitive, check all possible field names)
          let pemContent = parsed.pemBase64 || parsed.pem_base64 || parsed.pem || parsed.key;
          
          // If still no content, check if it's an empty string or undefined
          if (!pemContent) {
            console.warn(`⚠️ Key "${key}" exists but pemBase64 is:`, typeof parsed.pemBase64, parsed.pemBase64);
            console.warn(`⚠️ Full parsed object:`, parsed);
            continue;
          }
          
          // Handle data URL format (data:application/octet-stream;base64,<content>)
          if (pemContent.startsWith('data:')) {
            // Extract base64 part from data URL
            const base64Index = pemContent.indexOf(',');
            if (base64Index !== -1) {
              pemContent = pemContent.substring(base64Index + 1);
              console.log(`📝 Extracted base64 from data URL (removed ${base64Index + 1} chars of prefix)`);
            }
          }
          
          if (pemContent && pemContent.length > 0) {
            console.log(`✅ Found PEM file: "${parsed.pemName || 'unknown'}" from key "${key}" (${pemContent.length} chars)`);
            return pemContent;
          } else {
            console.warn(`⚠️ Key "${key}" exists but extracted pemContent is empty. Length:`, pemContent?.length);
          }
        }
      } catch (parseError) {
        console.error(`❌ Failed to parse localStorage key "${key}":`, parseError);
        console.error(`❌ Raw content:`, localStorage.getItem(key));
      }
    }
    
    // Check what keys actually exist in localStorage
    const allKeys = Object.keys(localStorage);
    const cloudCredsKeys = allKeys.filter(k => k.startsWith('cloudCreds_'));
    console.error('❌ No PEM base64 found in localStorage. Available cloudCreds keys:', cloudCredsKeys);
    
    // Try to inspect what's in those keys
    for (const key of cloudCredsKeys) {
      try {
        const content = localStorage.getItem(key);
        const parsed = JSON.parse(content);
        console.error(`🔍 Inspecting "${key}":`, {
          hasApiKey: !!parsed.apiKey,
          hasPemName: !!parsed.pemName,
          hasPemBase64: !!parsed.pemBase64,
          pemBase64Type: typeof parsed.pemBase64,
          pemBase64Length: parsed.pemBase64?.length,
          keys: Object.keys(parsed)
        });
      } catch (e) {
        console.error(`❌ Failed to inspect "${key}":`, e);
      }
    }
    
    console.error('💡 Make sure you have uploaded and saved a PEM file on the "Manage Instances" page');
    console.error('💡 Steps: 1) Upload PEM file, 2) Click "Save / Update" button');
    
    return null;
  };

  // If navigated with state from ManageInstances, open appropriate tab
  useEffect(() => {
    const state = location.state;
    if (!state) {
      // If no state, clear instance data and reset fields when navigating directly
      setInstanceData(null);
      setRwSshHost('');
      setRwSshUser('ubuntu');
      setRwSshKey('');
      return;
    }

    if (state.instanceData) {
      setInstanceData(state.instanceData);
    }
    setAllowMigration(Boolean(state.allowMigration));

    if (state.openRunWorkload) {
      if (state.instanceData) {
        const data = state.instanceData;
        if (data.gpuDescription) {
          const gpuMatch = data.gpuDescription.match(/(H100|A100|B100)/i);
          if (gpuMatch) {
            const gpuType = gpuMatch[1].toUpperCase();
            setRwSystem(`8x${gpuType}`);
          }
        }
        if (data.vendor) {
          setRwVendor(data.vendor);
        } else if (data.region) {
          setRwVendor('Lambda');
        }
        if (data.ipAddress) {
          setRwSshHost(data.ipAddress);
        }
        if (data.sshUser) {
          setRwSshUser(data.sshUser);
        }
        // Handle PEM key from instanceData
        if (data.pemBase64) {
          // Decode PEM if needed
          try {
            if (typeof window !== 'undefined' && window.atob) {
              setRwSshKey(window.atob(data.pemBase64));
            } else {
              setRwSshKey(data.pemBase64);
            }
          } catch (e) {
            setRwSshKey(data.pemBase64);
          }
        }
      }
    }
  }, [location.state]);

  // Update SSH fields when instanceData changes (e.g., when navigating from Manage Instances)
  // This ensures fields are pre-filled when coming from Manage Instances, but empty when navigating directly
  useEffect(() => {
    if (instanceData) {
      // Pre-fill IP address if available
      if (instanceData.ipAddress) {
        setRwSshHost(instanceData.ipAddress);
      }
      // Pre-fill SSH user if available
      if (instanceData.sshUser) {
        setRwSshUser(instanceData.sshUser);
      }
      // Pre-fill SSH key if available
      if (instanceData.pemBase64) {
        try {
          if (typeof window !== 'undefined' && window.atob) {
            setRwSshKey(window.atob(instanceData.pemBase64));
          } else {
            setRwSshKey(instanceData.pemBase64);
          }
        } catch (e) {
          setRwSshKey(instanceData.pemBase64);
        }
      }
    }
    // Note: We don't clear fields when instanceData is null to avoid clearing user input
    // Fields will be empty by default when navigating directly (no state)
  }, [instanceData]);

  useEffect(() => {
    if (selectedSystem) {
      loadSystemData(selectedSystem);
    }
  }, [selectedSystem]);


  return (
    <Box sx={{ p: 4, maxWidth: '1920px', mx: 'auto' }}>
      {error && (
        <Alert severity="error" sx={{ mb: 4 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Run Workload Section */}
            <Stack spacing={4}>
              {/* Header */}
              <Box>
                <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1, justifyContent: 'space-between' }}>
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="h1" sx={{ fontWeight: 800, fontSize: '3rem', mb: 0.5 }}>
                      Run Workload
                    </Typography>
                  </Box>
                </Stack>
              </Box>

              {/* SSH Credentials */}
              <Card sx={{ borderRadius: 3, border: `1px solid ${alpha('#000', 0.1)}` }}>
                <CardContent sx={{ p: 3 }}>
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 3 }}>
                    <CloudIcon sx={{ color: 'primary.main' }} />
                    <Typography variant="h6" sx={{ fontWeight: 600 }}>
                      SSH Connection Configuration
                    </Typography>
                  </Stack>
                  <Grid container spacing={3}>
                  <Grid item xs={12} md={4}>
                    <TextField
                        label="IP Address" 
                      fullWidth
                        value={rwSshHost} 
                        onChange={(e) => setRwSshHost(e.target.value)} 
                        placeholder="203.0.113.10"
                        helperText="Public IP address of your GPU instance"
                        required
                        sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                    />
                  </Grid>
                    <Grid item xs={12} md={3}>
                    <TextField
                        label="SSH User" 
                      fullWidth
                        value={rwSshUser} 
                        onChange={(e) => setRwSshUser(e.target.value)}
                        placeholder="ubuntu"
                        helperText="SSH username (usually 'ubuntu' or 'root')"
                        sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                    />
                  </Grid>
                    <Grid item xs={12}>
                    {rwSshKey ? (
                      <Box sx={{ mt: 1, p: 2, borderRadius: '8px', border: '1px solid #3d3d3a', backgroundColor: 'rgba(129, 140, 248, 0.06)' }}>
                        <Typography variant="body2" sx={{ color: '#34d399', fontWeight: 600, mb: 0.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                          <VpnKeyIcon sx={{ fontSize: 16 }} /> SSH Key Auto-configured
                        </Typography>
                        <Typography variant="caption" sx={{ color: '#a8a8a0', fontFamily: '"DM Mono", monospace', wordBreak: 'break-all' }}>
                          {rwSshKey.substring(0, 80)}...
                        </Typography>
                      </Box>
                    ) : (
                      <TextField
                        label="SSH Private Key (PEM)"
                        fullWidth
                        value={rwSshKey}
                        onChange={(e) => setRwSshKey(e.target.value)}
                        multiline
                        rows={3}
                        placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...&#10;-----END OPENSSH PRIVATE KEY-----"
                        helperText="Paste your SSH private key here. This will be used to securely access the instance."
                        required
                        sx={{
                          '& .MuiOutlinedInput-root': { borderRadius: '8px' },
                        }}
                      />
                    )}
                  </Grid>
                  </Grid>
                </CardContent>
              </Card>

              {runStatus && (
                <Alert 
                  severity={
                    /✅|completed successfully/i.test(runStatus)
                      ? 'success'
                      : /❌|failed|error/i.test(runStatus)
                        ? 'error'
                        : 'info'
                  } 
                  sx={{ borderRadius: 2 }}
                  icon={
                    /✅|completed successfully/i.test(runStatus)
                      ? <CheckCircleIcon />
                      : /❌|failed|error/i.test(runStatus)
                        ? <ErrorIcon />
                        : <InfoIcon />
                  }
                >
                  {runStatus}
                </Alert>
              )}

              {/* Cloud Provider Tabs */}

              {/* Model Selection */}
              <Card sx={{ borderRadius: 3, border: `1px solid ${alpha('#000', 0.1)}` }}>
                <CardContent sx={{ p: 3 }}>
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 3 }}>
                    <CloudDownloadIcon sx={{ color: 'primary.main' }} />
                    <Typography variant="h6" sx={{ fontWeight: 600 }}>
                      Model Selection
                    </Typography>
                  </Stack>
                  <Grid container spacing={3}>
                    <Grid item xs={12} md={6}>
                    <FormControl fullWidth>
                        <InputLabel>Select Model</InputLabel>
                      <Select 
                          value={selectedModel}
                          onChange={(e) => setSelectedModel(e.target.value)}
                          label="Select Model"
                          sx={{ borderRadius: 2 }}
                      >
                          <MenuItem value="Qwen/Qwen3.5-9B">
                            Qwen/Qwen3.5-9B
                          </MenuItem>
                          <MenuItem value="RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic">
                            RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic
                          </MenuItem>
                          <MenuItem value="Qwen/Qwen2.5-32B-Instruct">
                            Qwen/Qwen2.5-32B-Instruct
                          </MenuItem>
                          <MenuItem value="meta-llama/Llama-3.1-8B-Instruct">
                            meta-llama/Llama-3.1-8B-Instruct
                          </MenuItem>
                          <MenuItem value="meta-llama/Llama-3.1-70B-Instruct">
                            meta-llama/Llama-3.1-70B-Instruct
                          </MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                    <Grid item xs={12} md={6}>
                    <TextField
                        label="Model Path (on remote instance)"
                      fullWidth
                        value={getWorkflowModelPath(selectedModel)}
                        InputProps={{ readOnly: true }}
                        helperText={`This path will be used on the remote instance (${rwCloudProvider === 'scaleway' ? 'Scaleway uses /scratch' : 'Lambda uses /home/ubuntu'})`}
                        sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                    />
                  </Grid>
                </Grid>
                </CardContent>
              </Card>

              {/* Workflow Stepper */}
              <Card sx={{ borderRadius: 3, border: `1px solid ${alpha('#000', 0.1)}` }}>
                <CardContent sx={{ p: 3 }}>
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 4 }}>
                    <TimelineIcon sx={{ color: 'primary.main' }} />
                    <Typography variant="h6" sx={{ fontWeight: 600 }}>
                      Step-by-Step Workflow
                            </Typography>
                      </Stack>

                  {/* Phase 1: Setup */}
                  <Card
                    sx={{
                      mb: 3,
                      borderRadius: 3,
                      border: `2px solid ${
                        workflowSetupStatus.status === 'completed'
                          ? theme.palette.success.main
                          : workflowSetupStatus.status === 'failed'
                          ? theme.palette.error.main
                          : workflowSetupStatus.status === 'running' || workflowSetupStatus.status === 'started'
                          ? theme.palette.info.main
                          : alpha('#000', 0.1)
                      }`,
                      backgroundColor:
                        workflowSetupStatus.status === 'running' || workflowSetupStatus.status === 'started'
                          ? alpha('#0288d1', 0.05)
                          : workflowSetupStatus.status === 'completed'
                          ? alpha('#2e7d32', 0.02)
                          : 'background.paper',
                      transition: 'all 0.3s ease',
                    }}
                  >
                    <CardContent sx={{ p: 3 }}>
                      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
                        <Box
                          sx={{
                            p: 1.5,
                            borderRadius: 2,
                            backgroundColor: alpha(
                              workflowSetupStatus.status === 'completed'
                                ? theme.palette.success.main
                                : workflowSetupStatus.status === 'running' || workflowSetupStatus.status === 'started'
                                ? theme.palette.info.main
                                : theme.palette.primary.main,
                              0.1
                            ),
                          }}
                        >
                          <CloudDownloadIcon
                            sx={{
                              color:
                                workflowSetupStatus.status === 'completed'
                                  ? 'success.main'
                                  : workflowSetupStatus.status === 'running' || workflowSetupStatus.status === 'started'
                                  ? 'info.main'
                                  : 'primary.main',
                              fontSize: 24,
                            }}
                          />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                          <Stack direction="row" spacing={2} alignItems="center">
                            <Typography variant="h6" sx={{ fontWeight: 600 }}>
                              Phase 1: Setup
                            </Typography>
                            <Chip
                              icon={
                                workflowSetupStatus.status === 'completed' ? (
                                  <CheckCircleIcon />
                                ) : workflowSetupStatus.status === 'failed' ? (
                                  <ErrorIcon />
                                ) : null
                              }
                              label={
                                workflowSetupStatus.loading
                                  ? 'Running...'
                                  : workflowSetupStatus.status === 'running'
                                  ? 'Running...'
                                  : workflowSetupStatus.status === 'completed'
                                  ? 'Complete'
                                  : workflowSetupStatus.status === 'failed'
                                  ? 'Failed'
                                  : workflowSetupStatus.status === 'reboot_required'
                                  ? 'Reboot Required'
                                  : workflowSetupStatus.status === 'started'
                                  ? 'Starting...'
                                  : 'Not Started'
                              }
                              color={
                                workflowSetupStatus.status === 'completed'
                                  ? 'success'
                                  : workflowSetupStatus.status === 'reboot_required'
                                  ? 'warning'
                                  : workflowSetupStatus.status === 'failed'
                                  ? 'error'
                                  : workflowSetupStatus.status === 'running' || workflowSetupStatus.status === 'started'
                                  ? 'info'
                                  : 'default'
                              }
                            />
                            {persistedWorkflowState?.setup_completed_at && workflowSetupStatus.status !== 'completed' && (
                              <Chip
                                size="small"
                                icon={<CheckCircleIcon />}
                                label={`Done ${new Date(persistedWorkflowState.setup_completed_at + 'Z').toLocaleDateString()}`}
                                color="success"
                                variant="outlined"
                                sx={{ fontWeight: 500 }}
                              />
                            )}
                          </Stack>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            Install NVIDIA drivers, CUDA, DCGM, Python environment, and download the selected model.
                            </Typography>
                        </Box>
                      </Stack>

                      {(workflowSetupStatus.status === 'running' || workflowSetupStatus.status === 'started' || workflowSetupStatus.loading) && (
                        <Box sx={{ mb: 2 }}>
                          <LinearProgress sx={{ borderRadius: 1, height: 6 }} />
                          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                            {workflowSetupStatus.loading ? 'Initializing...' : 'Processing...'}
                          </Typography>
                        </Box>
                      )}

                      {workflowSetupStatus.status === 'reboot_required' && (
                        <Alert severity="warning" sx={{ mb: 2 }}>
                          {workflowSetupStatus.message || 'A system reboot is required for the NVIDIA driver to take effect. SSH into the instance and run: sudo reboot — then click Check once it is back up.'}
                        </Alert>
                      )}

                    <Button
                        variant="contained"
                        color="primary"
                        startIcon={workflowSetupStatus.loading ? <CircularProgress size={16} /> : <PlayArrowIcon />}
                      onClick={async () => {
                          if (!rwSshHost || !rwSshKey) {
                            setRunStatus('Error: IP address and SSH key are required');
                            appendWorkflowEvent('setup', 'error', 'Cannot start setup: missing SSH host or key.');
                          return;
                        }
                          setWorkflowSetupStatus({ ...workflowSetupStatus, loading: true, status: null, message: 'Starting setup...' });
                          appendWorkflowEvent('setup', 'info', 'Starting setup phase...');
                          try {
                            const pemBase64 = encodePemToBase64(rwSshKey);
                            if (!pemBase64) {
                              const errMsg = 'Error: SSH key encoding failed. Paste the full PEM contents (BEGIN/END lines).';
                              setWorkflowSetupStatus({ ...workflowSetupStatus, loading: false, status: 'error', message: errMsg });
                              setRunStatus(errMsg);
                              appendWorkflowEvent('setup', 'error', errMsg);
                              return;
                            }
                            const modelPath = getWorkflowModelPath(selectedModel);
                            const response = await apiService.workflowSetupInstance({
                              ssh_host: rwSshHost,
                              ssh_user: rwSshUser,
                              pem_base64: pemBase64,
                              model_name: selectedModel,
                              model_path: modelPath,
                              cloud_provider: rwCloudProvider
                            });
                            setWorkflowSetupStatus({
                              loading: false,
                              status: 'started',
                              message: response.message,
                              workflowId: response.workflow_id,
                              logs: ''
                            });
                            setRunStatus(`✅ Setup started. Workflow ID: ${response.workflow_id}`);
                            appendWorkflowEvent('setup', 'info', `Workflow started: ${response.workflow_id}`);
                            
                            const pollLogs = setInterval(async () => {
                              try {
                                const result = await apiService.getWorkflowLogs(response.workflow_id, 'setup');
                                trackWorkflowProgress('setup', result.status, result.message);
                                setWorkflowSetupStatus(prev => ({ 
                                  ...prev, 
                                  logs: result.logs || '',
                                  status: result.status || prev.status,
                                  message: result.message || prev.message
                                }));
                                
                                if (result.status === 'completed' || result.status === 'failed' || result.status === 'reboot_required') {
                                  const evtType = result.status === 'completed' ? 'success'
                                    : result.status === 'reboot_required' ? 'warning'
                                    : 'error';
                                  appendWorkflowEvent('setup', evtType, result.message || `Setup ${result.status}`);
                                  clearInterval(pollLogs);
                                }
                              } catch (e) {
                                console.error('Failed to fetch logs:', e);
                              }
                            }, 2000);
                            
                            setTimeout(() => clearInterval(pollLogs), 1800000);
                          } catch (e) {
                            setWorkflowSetupStatus({ ...workflowSetupStatus, loading: false, status: 'error', message: e.response?.data?.detail || e.message });
                            setRunStatus(`Setup failed: ${e.response?.data?.detail || e.message}`);
                            appendWorkflowEvent('setup', 'error', e.response?.data?.detail || e.message);
                        }
                      }}
                        disabled={workflowSetupStatus.loading || !rwSshHost || !rwSshKey}
                        sx={{ borderRadius: 2, minWidth: 140 }}
                      >
                        {workflowSetupStatus.loading ? 'Running...' : 'Run Setup'}
                    </Button>

                      {workflowSetupStatus.logs && (
                        <Box sx={{ mt: 3 }}>
                          <Accordion sx={{ borderRadius: 2, '&:before': { display: 'none' } }}>
                            <AccordionSummary
                              expandIcon={<ExpandMoreIcon />}
                              sx={{
                                backgroundColor: alpha('#3d3d3a', 0.5),
                                borderRadius: '8px',
                              }}
                            >
                              <Stack direction="row" spacing={1.5} alignItems="center">
                                <TerminalIcon sx={{ fontSize: 20, color: 'text.secondary' }} />
                                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                                  View Logs ({workflowSetupStatus.logs.split('\n').length} lines)
                                </Typography>
                  </Stack>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0 }}>
                              <Paper
                                sx={{
                                  p: 2,
                                  backgroundColor: '#1e1e1e',
                                  color: '#d4d4d4',
                                  fontFamily: 'monospace',
                                  fontSize: '0.75rem',
                                  maxHeight: 400,
                                  overflow: 'auto',
                                  borderRadius: '8px',
                                }}
                              >
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                  {workflowSetupStatus.logs}
                                </pre>
                              </Paper>
                            </AccordionDetails>
                          </Accordion>
                        </Box>
                      )}
                    </CardContent>
                  </Card>

                  {/* Phase 2: Check */}
                  <Card
                    sx={{
                      mb: 3,
                      borderRadius: 3,
                      border: `2px solid ${
                        workflowCheckStatus.status === 'completed'
                          ? theme.palette.success.main
                          : workflowCheckStatus.status === 'failed'
                          ? theme.palette.error.main
                          : workflowCheckStatus.status === 'running' || workflowCheckStatus.status === 'started'
                          ? theme.palette.info.main
                          : alpha('#000', 0.1)
                      }`,
                      backgroundColor:
                        workflowCheckStatus.status === 'running' || workflowCheckStatus.status === 'started'
                          ? alpha('#0288d1', 0.05)
                          : workflowCheckStatus.status === 'completed'
                          ? alpha('#2e7d32', 0.02)
                          : 'background.paper',
                      transition: 'all 0.3s ease',
                    }}
                  >
                    <CardContent sx={{ p: 3 }}>
                      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
                        <Box
                          sx={{
                            p: 1.5,
                            borderRadius: 2,
                            backgroundColor: alpha(
                              workflowCheckStatus.status === 'completed'
                                ? theme.palette.success.main
                                : workflowCheckStatus.status === 'running' || workflowCheckStatus.status === 'started'
                                ? theme.palette.info.main
                                : theme.palette.primary.main,
                              0.1
                            ),
                          }}
                        >
                          <CheckCircleOutlineIcon
                            sx={{
                              color:
                                workflowCheckStatus.status === 'completed'
                                  ? 'success.main'
                                  : workflowCheckStatus.status === 'running' || workflowCheckStatus.status === 'started'
                                  ? 'info.main'
                                  : 'primary.main',
                              fontSize: 24,
                            }}
                          />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                          <Stack direction="row" spacing={2} alignItems="center">
                            <Typography variant="h6" sx={{ fontWeight: 600 }}>
                              Phase 2: Check
                            </Typography>
                            <Chip
                              icon={
                                workflowCheckStatus.status === 'completed' ? (
                                  <CheckCircleIcon />
                                ) : workflowCheckStatus.status === 'failed' ? (
                                  <ErrorIcon />
                                ) : null
                              }
                              label={
                                workflowCheckStatus.loading
                                  ? 'Running...'
                                  : workflowCheckStatus.status === 'running'
                                  ? 'Running...'
                                  : workflowCheckStatus.status === 'completed'
                                  ? 'Complete'
                                  : workflowCheckStatus.status === 'failed'
                                  ? 'Failed'
                                  : workflowCheckStatus.status === 'started'
                                  ? 'Starting...'
                                  : 'Not Started'
                              }
                              color={
                                workflowCheckStatus.status === 'completed'
                                  ? 'success'
                                  : workflowCheckStatus.status === 'failed'
                                  ? 'error'
                                  : workflowCheckStatus.status === 'running' || workflowCheckStatus.status === 'started'
                                  ? 'info'
                                  : 'default'
                              }
                              size="small"
                              sx={{ fontWeight: 500 }}
                            />
                            {persistedWorkflowState?.check_completed_at && workflowCheckStatus.status !== 'completed' && (
                              <Chip
                                size="small"
                                icon={<CheckCircleIcon />}
                                label={`Verified ${new Date(persistedWorkflowState.check_completed_at + 'Z').toLocaleDateString()}`}
                                color="success"
                                variant="outlined"
                                sx={{ fontWeight: 500 }}
                              />
                            )}
                          </Stack>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            Verify nvidia-smi and restart DCGM service.
                          </Typography>
                        </Box>
                      </Stack>

                      {!setupComplete && (
                        <Alert severity="warning" sx={{ mb: 2, borderRadius: 2 }}>
                          <Typography variant="body2">
                            <strong>Prerequisite:</strong> Phase 1 (Setup) must be completed first.
                          </Typography>
                        </Alert>
                      )}

                      {(workflowCheckStatus.status === 'running' || workflowCheckStatus.status === 'started' || workflowCheckStatus.loading) && (
                        <Box sx={{ mb: 2 }}>
                          <LinearProgress sx={{ borderRadius: 1, height: 6 }} />
                          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                            {workflowCheckStatus.loading ? 'Initializing...' : 'Processing...'}
                          </Typography>
                        </Box>
                      )}

                      <Button
                        variant="contained"
                        color="primary"
                        startIcon={workflowCheckStatus.loading ? <CircularProgress size={16} /> : <PlayArrowIcon />}
                        onClick={async () => {
                          if (!rwSshHost || !rwSshKey) {
                            setRunStatus('Error: IP address and SSH key are required');
                            appendWorkflowEvent('check', 'error', 'Cannot start check: missing SSH host or key.');
                            return;
                          }
                          setWorkflowCheckStatus({ ...workflowCheckStatus, loading: true, status: null, message: 'Starting check...' });
                          appendWorkflowEvent('check', 'info', 'Starting check phase...');
                          try {
                            const pemBase64 = encodePemToBase64(rwSshKey);
                            if (!pemBase64) {
                              const errMsg = 'Error: SSH key encoding failed. Paste the full PEM contents (BEGIN/END lines).';
                              setWorkflowCheckStatus({ ...workflowCheckStatus, loading: false, status: 'error', message: errMsg });
                              setRunStatus(errMsg);
                              appendWorkflowEvent('check', 'error', errMsg);
                              return;
                            }
                            const response = await apiService.workflowCheckInstance({
                              ssh_host: rwSshHost,
                          ssh_user: rwSshUser,
                              pem_base64: pemBase64,
                              cloud_provider: rwCloudProvider
                            });
                            setWorkflowCheckStatus({
                          loading: false, 
                              status: 'started',
                          message: response.message,
                              workflowId: response.workflow_id,
                              logs: ''
                        });
                            setRunStatus(`Check started. Workflow ID: ${response.workflow_id}`);
                            appendWorkflowEvent('check', 'info', `Workflow started: ${response.workflow_id}`);
                        
                            const pollLogs = setInterval(async () => {
                            try {
                                const result = await apiService.getWorkflowLogs(response.workflow_id, 'check');
                                trackWorkflowProgress('check', result.status, result.message);
                                setWorkflowCheckStatus(prev => ({ 
                                ...prev, 
                                  logs: result.logs || '',
                                  status: result.status || prev.status,
                                  message: result.message || prev.message
                                }));
                                
                                if (result.status === 'completed' || result.status === 'failed') {
                                  appendWorkflowEvent(
                                    'check',
                                    result.status === 'completed' ? 'success' : 'error',
                                    result.message || `Check ${result.status}`
                                  );
                                  clearInterval(pollLogs);
                              }
                            } catch (e) {
                                console.error('Failed to fetch logs:', e);
                            }
                            }, 2000);
                            setTimeout(() => clearInterval(pollLogs), 1800000);
                      } catch (e) {
                            setWorkflowCheckStatus({ ...workflowCheckStatus, loading: false, status: 'error', message: e.response?.data?.detail || e.message });
                            setRunStatus(`Check failed: ${e.response?.data?.detail || e.message}`);
                            appendWorkflowEvent('check', 'error', e.response?.data?.detail || e.message);
                      }
                    }}
                        disabled={workflowCheckStatus.loading || !rwSshHost || !rwSshKey || !setupComplete}
                        sx={{ borderRadius: 2, minWidth: 140 }}
                  >
                        {workflowCheckStatus.loading ? 'Running...' : 'Run Check'}
                  </Button>

                      {workflowCheckStatus.logs && (
                        <Box sx={{ mt: 3 }}>
                          <Accordion sx={{ borderRadius: 2, '&:before': { display: 'none' } }}>
                            <AccordionSummary
                              expandIcon={<ExpandMoreIcon />}
                              sx={{
                                backgroundColor: alpha('#3d3d3a', 0.5),
                                borderRadius: '8px',
                              }}
                            >
                              <Stack direction="row" spacing={1.5} alignItems="center">
                                <TerminalIcon sx={{ fontSize: 20, color: 'text.secondary' }} />
                                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                                  View Logs ({workflowCheckStatus.logs.split('\n').length} lines)
                                </Typography>
                              </Stack>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0 }}>
                              <Paper
                                sx={{
                                  p: 2,
                                  backgroundColor: '#1e1e1e',
                                  color: '#d4d4d4',
                                  fontFamily: 'monospace',
                                  fontSize: '0.75rem',
                                  maxHeight: 400,
                                  overflow: 'auto',
                                  borderRadius: '8px',
                                }}
                              >
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                  {workflowCheckStatus.logs}
                                </pre>
                              </Paper>
                            </AccordionDetails>
                          </Accordion>
                        </Box>
                      )}
                    </CardContent>
                  </Card>

                  {/* Phase 3: Deploy */}
                  <Card
                    sx={{
                      mb: 3,
                      borderRadius: 3,
                      border: `2px solid ${
                        workflowDeployStatus.status === 'completed'
                          ? theme.palette.success.main
                          : workflowDeployStatus.status === 'failed'
                          ? theme.palette.error.main
                          : workflowDeployStatus.status === 'running' || workflowDeployStatus.status === 'started'
                          ? theme.palette.info.main
                          : alpha('#000', 0.1)
                      }`,
                      backgroundColor:
                        workflowDeployStatus.status === 'running' || workflowDeployStatus.status === 'started'
                          ? alpha('#0288d1', 0.05)
                          : workflowDeployStatus.status === 'completed'
                          ? alpha('#2e7d32', 0.02)
                          : 'background.paper',
                      transition: 'all 0.3s ease',
                    }}
                  >
                    <CardContent sx={{ p: 3 }}>
                      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
                        <Box
                          sx={{
                            p: 1.5,
                            borderRadius: 2,
                            backgroundColor: alpha(
                              workflowDeployStatus.status === 'completed'
                                ? theme.palette.success.main
                                : workflowDeployStatus.status === 'running' || workflowDeployStatus.status === 'started'
                                ? theme.palette.info.main
                                : theme.palette.primary.main,
                              0.1
                            ),
                          }}
                        >
                          <RocketLaunchIcon
                            sx={{
                              color:
                                workflowDeployStatus.status === 'completed'
                                  ? 'success.main'
                                  : workflowDeployStatus.status === 'running' || workflowDeployStatus.status === 'started'
                                  ? 'info.main'
                                  : 'primary.main',
                              fontSize: 24,
                            }}
                          />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                          <Stack direction="row" spacing={2} alignItems="center">
                            <Typography variant="h6" sx={{ fontWeight: 600 }}>
                              Phase 3: Deploy Inference
                            </Typography>
                            <Chip
                              icon={
                                workflowDeployStatus.status === 'completed' ? (
                                  <CheckCircleIcon />
                                ) : workflowDeployStatus.status === 'failed' ? (
                                  <ErrorIcon />
                                ) : null
                              }
                              label={
                                workflowDeployStatus.loading
                                  ? 'Running...'
                                  : workflowDeployStatus.status === 'running'
                                  ? 'Running...'
                                  : workflowDeployStatus.status === 'completed'
                                  ? 'Complete'
                                  : workflowDeployStatus.status === 'failed'
                                  ? 'Failed'
                                  : workflowDeployStatus.status === 'started'
                                  ? 'Starting...'
                                  : 'Not Started'
                              }
                              color={
                                workflowDeployStatus.status === 'completed'
                                  ? 'success'
                                  : workflowDeployStatus.status === 'failed'
                                  ? 'error'
                                  : workflowDeployStatus.status === 'running' || workflowDeployStatus.status === 'started'
                                  ? 'info'
                                  : 'default'
                              }
                              size="small"
                              sx={{ fontWeight: 500 }}
                            />
                            {persistedWorkflowState?.vllm_deployed_at && workflowDeployStatus.status !== 'completed' && (
                              <Chip
                                size="small"
                                icon={<CheckCircleIcon />}
                                label={`Deployed ${new Date(persistedWorkflowState.vllm_deployed_at + 'Z').toLocaleDateString()}${persistedWorkflowState.vllm_model ? ` — ${persistedWorkflowState.vllm_model.split('/').pop()}` : ''}`}
                                color="success"
                                variant="outlined"
                                sx={{ fontWeight: 500 }}
                              />
                            )}
                          </Stack>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            Start inference server with adaptive GPU parameters.
                          </Typography>
                        </Box>
                      </Stack>

                      {!checkComplete && (
                        <Alert severity="warning" sx={{ mb: 2, borderRadius: 2 }}>
                          <Typography variant="body2">
                            <strong>Prerequisite:</strong> Phase 2 (Check) must be completed first.
                          </Typography>
                        </Alert>
                      )}

                      {(workflowDeployStatus.status === 'running' || workflowDeployStatus.status === 'started' || workflowDeployStatus.loading) && (
                        <Box sx={{ mb: 2 }}>
                          <LinearProgress sx={{ borderRadius: 1, height: 6 }} />
                          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                            {workflowDeployStatus.loading ? 'Initializing...' : 'Processing...'}
                          </Typography>
                        </Box>
                      )}
                  
                  <Button
                        variant="contained"
                        color="primary"
                        startIcon={workflowDeployStatus.loading ? <CircularProgress size={16} /> : <PlayArrowIcon />}
                    onClick={async () => {
                          if (!rwSshHost || !rwSshKey) {
                            setRunStatus('Error: IP address and SSH key are required');
                            appendWorkflowEvent('deploy', 'error', 'Cannot start deploy: missing SSH host or key.');
                        return;
                      }
                          setWorkflowDeployStatus({ ...workflowDeployStatus, loading: true, status: null, message: 'Starting deploy...' });
                          appendWorkflowEvent('deploy', 'info', 'Starting deploy phase...');
                      try {
                            const pemBase64 = encodePemToBase64(rwSshKey);
                            if (!pemBase64) {
                              const errMsg = 'Error: SSH key encoding failed. Paste the full PEM contents (BEGIN/END lines).';
                              setWorkflowDeployStatus({ ...workflowDeployStatus, loading: false, status: 'error', message: errMsg });
                              setRunStatus(errMsg);
                              appendWorkflowEvent('deploy', 'error', errMsg);
                              return;
                            }
                            const modelPath = getWorkflowModelPath(selectedModel);
                            const response = await apiService.workflowDeployVLLM({
                              cloud_provider: rwCloudProvider,
                              ssh_host: rwSshHost,
                              ssh_user: rwSshUser,
                              pem_base64: pemBase64,
                              model_path: modelPath,
                              max_model_len: vllmMaxModelLen ? Number(vllmMaxModelLen) : null,
                              max_num_seqs: vllmMaxNumSeqs ? Number(vllmMaxNumSeqs) : null,
                              gpu_memory_utilization: vllmGpuMemUtil ? Number(vllmGpuMemUtil) : null,
                              tensor_parallel_size: vllmTensorParallel ? Number(vllmTensorParallel) : null
                            });
                            setWorkflowDeployStatus({
                              loading: false,
                              status: 'started',
                              message: response.message,
                              workflowId: response.workflow_id,
                              logs: ''
                            });
                            setRunStatus(`Deploy started. Workflow ID: ${response.workflow_id}`);
                            appendWorkflowEvent('deploy', 'info', `Workflow started: ${response.workflow_id}`);
                            
                            const pollLogs = setInterval(async () => {
                              try {
                                const result = await apiService.getWorkflowLogs(response.workflow_id, 'deploy');
                                trackWorkflowProgress('deploy', result.status, result.message);
                                let combinedLogs = result.logs || '';
                                if (result.container_logs) {
                                  combinedLogs += '\n\n=== Inference Container Logs ===\n' + result.container_logs;
                                }
                                setWorkflowDeployStatus(prev => ({ 
                                  ...prev, 
                                  logs: combinedLogs,
                                  status: result.status || prev.status,
                                  message: result.message || prev.message
                                }));
                                
                                if (result.status === 'completed' || result.status === 'failed') {
                                  appendWorkflowEvent(
                                    'deploy',
                                    result.status === 'completed' ? 'success' : 'error',
                                    result.message || `Deploy ${result.status}`
                                  );
                                  clearInterval(pollLogs);
                                }
                              } catch (e) {
                                console.error('Failed to fetch logs:', e);
                          }
                            }, 2000);
                            setTimeout(() => clearInterval(pollLogs), 1800000);
                      } catch (e) {
                            setWorkflowDeployStatus({ ...workflowDeployStatus, loading: false, status: 'error', message: e.response?.data?.detail || e.message });
                            setRunStatus(`Deploy failed: ${e.response?.data?.detail || e.message}`);
                            appendWorkflowEvent('deploy', 'error', e.response?.data?.detail || e.message);
                      }
                    }}
                        disabled={workflowDeployStatus.loading || !rwSshHost || !rwSshKey || !checkComplete}
                        sx={{ borderRadius: 2, minWidth: 140 }}
                  >
                        {workflowDeployStatus.loading ? 'Running...' : 'Run Deploy'}
                  </Button>
                  
                      {workflowDeployStatus.logs && (
                        <Box sx={{ mt: 3 }}>
                          <Accordion sx={{ borderRadius: 2, '&:before': { display: 'none' } }}>
                            <AccordionSummary
                              expandIcon={<ExpandMoreIcon />}
                              sx={{
                                backgroundColor: alpha('#3d3d3a', 0.5),
                                borderRadius: '8px',
                              }}
                            >
                              <Stack direction="row" spacing={1.5} alignItems="center">
                                <TerminalIcon sx={{ fontSize: 20, color: 'text.secondary' }} />
                                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                                  View Logs ({workflowDeployStatus.logs.split('\n').length} lines)
                      </Typography>
                              </Stack>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0 }}>
                              <Paper
                                sx={{
                                  p: 2,
                            backgroundColor: '#1e1e1e',
                            color: '#d4d4d4',
                              fontFamily: 'monospace',
                              fontSize: '0.75rem',
                                  maxHeight: 400,
                                  overflow: 'auto',
                                  borderRadius: '8px',
                                }}
                              >
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                  {workflowDeployStatus.logs}
                                </pre>
                              </Paper>
                            </AccordionDetails>
                          </Accordion>
                        </Box>
                      )}
                    </CardContent>
                  </Card>

                  {/* Phase 4: Benchmark */}
                  <Card
                        sx={{
                      mb: 3,
                      borderRadius: 3,
                      border: `2px solid ${
                        workflowBenchmarkStatus.status === 'completed'
                          ? theme.palette.success.main
                          : workflowBenchmarkStatus.status === 'failed'
                          ? theme.palette.error.main
                          : workflowBenchmarkStatus.status === 'running' || workflowBenchmarkStatus.status === 'started'
                          ? theme.palette.info.main
                          : alpha('#000', 0.1)
                      }`,
                      backgroundColor:
                        workflowBenchmarkStatus.status === 'running' || workflowBenchmarkStatus.status === 'started'
                          ? alpha('#0288d1', 0.05)
                          : workflowBenchmarkStatus.status === 'completed'
                          ? alpha('#2e7d32', 0.02)
                          : 'background.paper',
                      transition: 'all 0.3s ease',
                    }}
                  >
                    <CardContent sx={{ p: 3 }}>
                      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 3 }}>
                        <Box
                          sx={{
                            p: 1.5,
                            borderRadius: 2,
                            backgroundColor: alpha(
                              workflowBenchmarkStatus.status === 'completed'
                                ? theme.palette.success.main
                                : workflowBenchmarkStatus.status === 'running' || workflowBenchmarkStatus.status === 'started'
                                ? theme.palette.info.main
                                : theme.palette.primary.main,
                              0.1
                            ),
                          }}
                        >
                          <SpeedIcon
                            sx={{
                              color:
                                workflowBenchmarkStatus.status === 'completed'
                                  ? 'success.main'
                                  : workflowBenchmarkStatus.status === 'running' || workflowBenchmarkStatus.status === 'started'
                                  ? 'info.main'
                                  : 'primary.main',
                              fontSize: 24,
                            }}
                          />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                          <Stack direction="row" spacing={2} alignItems="center">
                            <Typography variant="h6" sx={{ fontWeight: 600 }}>
                              Phase 4: Benchmark
                        </Typography>
                            <Chip
                              icon={
                                workflowBenchmarkStatus.status === 'completed' ? (
                                  <CheckCircleIcon />
                                ) : workflowBenchmarkStatus.status === 'failed' ? (
                                  <ErrorIcon />
                                ) : null
                              }
                              label={
                                workflowBenchmarkStatus.loading
                                  ? 'Running...'
                                  : workflowBenchmarkStatus.status === 'running'
                                  ? 'Running...'
                                  : workflowBenchmarkStatus.status === 'completed'
                                  ? 'Complete'
                                  : workflowBenchmarkStatus.status === 'failed'
                                  ? 'Failed'
                                  : workflowBenchmarkStatus.status === 'started'
                                  ? 'Starting...'
                                  : 'Not Started'
                              }
                              color={
                                workflowBenchmarkStatus.status === 'completed'
                                  ? 'success'
                                  : workflowBenchmarkStatus.status === 'failed'
                                  ? 'error'
                                  : workflowBenchmarkStatus.status === 'running' || workflowBenchmarkStatus.status === 'started'
                                  ? 'info'
                                  : 'default'
                              }
                              size="small"
                              sx={{ fontWeight: 500 }}
                            />
                          </Stack>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            Run benchmark with GPU monitoring using user-defined parameters.
                          </Typography>
                    </Box>
                      </Stack>

                      {!deployComplete && (
                        <Alert severity="warning" sx={{ mb: 3, borderRadius: 2 }}>
                          <Typography variant="body2">
                            <strong>Prerequisite:</strong> Phase 3 (Deploy) must be completed first.
                          </Typography>
                        </Alert>
                      )}

                      {workflowBenchmarkStatus.status === 'failed' && (
                        <Alert 
                          severity="error" 
                          sx={{ mb: 3, borderRadius: 2 }}
                          onClose={() => setWorkflowBenchmarkStatus(prev => ({ ...prev, status: null, message: null }))}
                        >
                          <AlertTitle sx={{ fontWeight: 600 }}>Benchmark Failed</AlertTitle>
                          <Typography variant="body2" sx={{ mb: 1 }}>
                            {workflowBenchmarkStatus.message || 'Unknown error occurred'}
                          </Typography>
                          {workflowBenchmarkStatus.errorDetails && (
                            <Typography 
                              variant="caption" 
                              component="pre" 
                              sx={{ 
                                mt: 1, 
                                p: 1, 
                                backgroundColor: alpha('#000', 0.1), 
                                borderRadius: 1,
                                fontFamily: 'monospace',
                                fontSize: '0.7rem',
                                overflow: 'auto',
                                maxHeight: 200
                              }}
                            >
                              {workflowBenchmarkStatus.errorDetails}
                            </Typography>
                          )}
                        </Alert>
                      )}

                      <Paper
                        variant="outlined"
                        sx={{
                          p: 3,
                          mb: 3,
                          borderRadius: 2,
                          backgroundColor: alpha('#3d3d3a', 0.3),
                        }}
                      >
                        <Typography variant="subtitle2" sx={{ mb: 2, fontWeight: 600, color: 'text.secondary' }}>
                          Benchmark Parameters
                        </Typography>
                        <Grid container spacing={3}>
                          <Grid item xs={12} sm={6} md={4}>
                            <Tooltip title="Length of input prompt tokens" arrow>
                              <TextField
                                label="Input Sequence Length"
                                type="number"
                                fullWidth
                                value={workflowInputSeqLen}
                                onChange={(e) => setWorkflowInputSeqLen(Number(e.target.value))}
                                inputProps={{ min: 1 }}
                                helperText="Tokens in input prompt"
                                sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                              />
                            </Tooltip>
                          </Grid>
                          <Grid item xs={12} sm={6} md={4}>
                            <Tooltip title="Maximum tokens to generate per request" arrow>
                              <TextField
                                label="Output Sequence Length"
                                type="number"
                                fullWidth
                                value={workflowOutputSeqLen}
                                onChange={(e) => setWorkflowOutputSeqLen(Number(e.target.value))}
                                inputProps={{ min: 1 }}
                                helperText="Max tokens to generate"
                                sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                              />
                            </Tooltip>
                          </Grid>
                          <Grid item xs={12} sm={6} md={4}>
                            <Tooltip title="Total number of requests to send" arrow>
                              <TextField
                                label="Number of Requests"
                                type="number"
                                fullWidth
                                value={workflowNumRequests}
                                onChange={(e) => setWorkflowNumRequests(Number(e.target.value))}
                                inputProps={{ min: 1 }}
                                helperText="Total requests to process"
                                sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                              />
                            </Tooltip>
                          </Grid>
                          <Grid item xs={12} sm={6} md={4}>
                            <Tooltip title="Requests per second to send" arrow>
                              <TextField
                                label="Request Rate"
                                type="number"
                                fullWidth
                                value={workflowRequestRate}
                                onChange={(e) => setWorkflowRequestRate(Number(e.target.value))}
                                inputProps={{ step: 0.1, min: 0.1 }}
                                helperText="Requests per second"
                                sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                              />
                            </Tooltip>
                          </Grid>
                          <Grid item xs={12} sm={6} md={4}>
                            <Tooltip title="Maximum concurrent requests" arrow>
                              <TextField
                                label="Max Concurrency"
                                type="number"
                                fullWidth
                                value={workflowMaxConcurrency}
                                onChange={(e) => setWorkflowMaxConcurrency(Number(e.target.value))}
                                inputProps={{ min: 1 }}
                                helperText="Max concurrent requests"
                                sx={{ '& .MuiOutlinedInput-root': { borderRadius: '8px' } }}
                              />
                            </Tooltip>
                          </Grid>
                        </Grid>
                </Paper>

                      {(workflowBenchmarkStatus.status === 'running' || workflowBenchmarkStatus.status === 'started' || workflowBenchmarkStatus.loading) && (() => {
                        // Parse "Completed X/Y" or "X/Y requests" from logs to show determinate progress
                        let progressValue = null;
                        if (workflowBenchmarkStatus.logs) {
                          const matches = workflowBenchmarkStatus.logs.match(/(\d+)\s*\/\s*(\d+)\s*(requests?)?/gi);
                          if (matches && matches.length > 0) {
                            const lastMatch = matches[matches.length - 1].match(/(\d+)\s*\/\s*(\d+)/);
                            if (lastMatch) {
                              const done = parseInt(lastMatch[1], 10);
                              const total = parseInt(lastMatch[2], 10);
                              if (total > 0 && done <= total) progressValue = Math.round((done / total) * 100);
                            }
                          }
                        }
                        return (
                          <Box sx={{ mb: 2 }}>
                            <LinearProgress
                              variant={progressValue != null ? 'determinate' : 'indeterminate'}
                              value={progressValue}
                              sx={{ borderRadius: 1, height: 6 }}
                            />
                            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                              {workflowBenchmarkStatus.loading ? 'Initializing…' : progressValue != null ? `${progressValue}% complete` : 'Running…'}
                            </Typography>
                          </Box>
                        );
                      })()}

                <Button
                  variant="contained"
                        color="primary"
                        startIcon={workflowBenchmarkStatus.loading ? <CircularProgress size={16} /> : <PlayArrowIcon />}
                  onClick={async () => {
                          if (!rwSshHost || !rwSshKey) {
                            setRunStatus('Error: IP address and SSH key are required');
                            appendWorkflowEvent('benchmark', 'error', 'Cannot start benchmark: missing SSH host or key.');
                            return;
                          }
                          setWorkflowBenchmarkStatus({ ...workflowBenchmarkStatus, loading: true, status: null, message: 'Starting benchmark...' });
                          appendWorkflowEvent('benchmark', 'info', 'Starting benchmark phase...');
                          try {
                            const pemBase64 = encodePemToBase64(rwSshKey);
                            if (!pemBase64) {
                              const errMsg = 'Error: SSH key encoding failed. Paste the full PEM contents (BEGIN/END lines).';
                              setWorkflowBenchmarkStatus({ ...workflowBenchmarkStatus, loading: false, status: 'error', message: errMsg });
                              setRunStatus(errMsg);
                              appendWorkflowEvent('benchmark', 'error', errMsg);
                              return;
                            }
                            const modelPath = getWorkflowModelPath(selectedModel);
                            const response = await apiService.workflowRunBenchmark({
                              cloud_provider: rwCloudProvider,
                              ssh_host: rwSshHost,
                              ssh_user: rwSshUser,
                              pem_base64: pemBase64,
                              model_path: modelPath,
                              model_name: selectedModel,
                              input_seq_len: workflowInputSeqLen,
                              output_seq_len: workflowOutputSeqLen,
                              num_requests: workflowNumRequests,
                              request_rate: workflowRequestRate,
                              max_concurrency: workflowMaxConcurrency
                            });
                            setWorkflowBenchmarkStatus({
                              loading: false,
                              status: 'started',
                              message: response.message,
                              workflowId: response.workflow_id,
                              logs: ''
                            });
                            setRunStatus(`Benchmark started. Workflow ID: ${response.workflow_id}`);
                            appendWorkflowEvent('benchmark', 'info', `Workflow started: ${response.workflow_id}`);
                            
                            const pollLogs = setInterval(async () => {
                              try {
                                const result = await apiService.getWorkflowLogs(response.workflow_id, 'benchmark');
                                trackWorkflowProgress('benchmark', result.status, result.message);
                                setWorkflowBenchmarkStatus(prev => ({
                                  ...prev,
                                  logs: result.logs || '',
                                  status: result.status || prev.status,
                                  message: result.message || prev.message,
                                  errorDetails: result.error_details || prev.errorDetails,
                                  runId: result.run_id || prev.runId,
                                  metrics: result.metrics || prev.metrics
                                }));
                                
                                // Show error alert if failed
                                if (result.status === 'failed') {
                                  clearInterval(pollLogs);
                                  setRunStatus(`Benchmark failed: ${result.message || 'Unknown error'}`);
                                  appendWorkflowEvent('benchmark', 'error', result.message || 'Unknown error');
                                  if (result.error_details) {
                                    console.error('Benchmark error details:', result.error_details);
                                  }
                                } else if (result.status === 'completed') {
                                  clearInterval(pollLogs);
                                  setRunStatus(`Benchmark completed successfully`);
                                  appendWorkflowEvent('benchmark', 'success', 'Benchmark completed successfully.');
                                }
                              } catch (e) {
                                console.error('Failed to fetch logs:', e);
                              }
                            }, 2000);
                            setTimeout(() => clearInterval(pollLogs), 1800000);
                          } catch (e) {
                            setWorkflowBenchmarkStatus({ ...workflowBenchmarkStatus, loading: false, status: 'error', message: e.response?.data?.detail || e.message });
                            setRunStatus(`Benchmark failed: ${e.response?.data?.detail || e.message}`);
                            appendWorkflowEvent('benchmark', 'error', e.response?.data?.detail || e.message);
                    }
                  }}
                        disabled={workflowBenchmarkStatus.loading || !rwSshHost || !rwSshKey || !deployComplete}
                        sx={{ borderRadius: 2, minWidth: 140 }}
                      >
                        {workflowBenchmarkStatus.loading ? 'Running...' : 'Run Benchmark'}
                </Button>

                      {workflowBenchmarkStatus.logs && (
                        <Box sx={{ mt: 3 }}>
                          <Accordion sx={{ borderRadius: 2, '&:before': { display: 'none' } }}>
                            <AccordionSummary
                              expandIcon={<ExpandMoreIcon />}
                              sx={{
                                backgroundColor: alpha('#3d3d3a', 0.5),
                                borderRadius: '8px',
                              }}
                            >
                              <Stack direction="row" spacing={1.5} alignItems="center">
                                <TerminalIcon sx={{ fontSize: 20, color: 'text.secondary' }} />
                                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                                  View Logs ({workflowBenchmarkStatus.logs.split('\n').length} lines)
                                </Typography>
                              </Stack>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0 }}>
                              <Paper
                                sx={{
                                  p: 2,
                                  backgroundColor: '#1e1e1e',
                                  color: '#d4d4d4',
                                  fontFamily: 'monospace',
                                  fontSize: '0.75rem',
                                  maxHeight: 500,
                                  overflow: 'auto',
                                  borderRadius: '8px',
                                }}
                              >
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                  {workflowBenchmarkStatus.logs}
                                </pre>
                              </Paper>
                            </AccordionDetails>
                          </Accordion>
                        </Box>
                      )}
                    </CardContent>
                  </Card>

                  {/* Benchmark Results — vLLM official metrics (throughput, TTFT, ITL) */}
                  {workflowBenchmarkStatus.status === 'completed' && workflowBenchmarkStatus.metrics && (
                    <Card sx={{ mt: 2, borderRadius: 2, border: `1px solid ${alpha(theme.palette.success.main, 0.3)}` }}>
                      <CardContent>
                        <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
                          Benchmark Results
                        </Typography>
                        <Grid container spacing={2}>
                          {workflowBenchmarkStatus.metrics.output_throughput_tok_s != null && (
                            <Grid item xs={6} sm={4}>
                              <Typography variant="caption" color="text.secondary">Output Throughput</Typography>
                              <Typography variant="h6" color="success.main">
                                {workflowBenchmarkStatus.metrics.output_throughput_tok_s.toFixed(1)} tok/s
                              </Typography>
                            </Grid>
                          )}
                          {workflowBenchmarkStatus.metrics.mean_ttft_ms != null && (
                            <Grid item xs={6} sm={4}>
                              <Typography variant="caption" color="text.secondary">Time to First Token</Typography>
                              <Typography variant="h6">
                                {workflowBenchmarkStatus.metrics.mean_ttft_ms.toFixed(1)} ms
                              </Typography>
                            </Grid>
                          )}
                          {workflowBenchmarkStatus.metrics.mean_itl_ms != null && (
                            <Grid item xs={6} sm={4}>
                              <Typography variant="caption" color="text.secondary">Inter-token Latency</Typography>
                              <Typography variant="h6">
                                {workflowBenchmarkStatus.metrics.mean_itl_ms.toFixed(1)} ms
                              </Typography>
                            </Grid>
                          )}
                          {workflowBenchmarkStatus.metrics.request_throughput_req_s != null && (
                            <Grid item xs={6} sm={4}>
                              <Typography variant="caption" color="text.secondary">Request Throughput</Typography>
                              <Typography variant="body1">
                                {workflowBenchmarkStatus.metrics.request_throughput_req_s.toFixed(2)} req/s
                              </Typography>
                            </Grid>
                          )}
                        </Grid>
                      </CardContent>
                    </Card>
                  )}
                  {workflowBenchmarkStatus.status === 'completed' && workflowBenchmarkStatus.runId && !workflowBenchmarkStatus.metrics && (
                    <BenchmarkResultsCard runId={workflowBenchmarkStatus.runId} />
                  )}
                </CardContent>
              </Card>

              {/* Phase 5: Kernel Profile */}
              <Card sx={{ borderRadius: 3, backgroundColor: alpha(theme.palette.background.paper, 0.6) }}>
                <CardContent>
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
                    <Chip label="Phase 5" size="small" color="secondary" />
                    <Typography variant="h6" fontWeight={600}>Kernel Profile</Typography>
                    {workflowKernelStatus.status === 'completed' && <CheckCircleIcon color="success" fontSize="small" />}
                    {workflowKernelStatus.status === 'failed' && <ErrorIcon color="error" fontSize="small" />}
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    Run kernel-level profiling to get CUDA kernel breakdown, compute/memory utilization, and bottleneck analysis.
                    This is a separate run from the benchmark.
                  </Typography>

                  <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
                    <TextField
                      label="Kernel Requests"
                      type="number"
                      size="small"
                      value={workflowKernelRequests}
                      onChange={(e) => setWorkflowKernelRequests(Number(e.target.value))}
                      sx={{ width: 160 }}
                      inputProps={{ min: 1, max: 100 }}
                    />
                  </Stack>

                  {workflowKernelStatus.message && (
                    <Alert
                      severity={workflowKernelStatus.status === 'failed' ? 'error' : workflowKernelStatus.status === 'completed' ? 'success' : 'info'}
                      sx={{ mb: 2, borderRadius: 2 }}
                    >
                      {workflowKernelStatus.message}
                    </Alert>
                  )}

                  <Card variant="outlined" sx={{ borderRadius: 2, p: 2 }}>
                    <CardContent sx={{ p: '0 !important' }}>
                      <Button
                        variant="contained"
                        color="secondary"
                        startIcon={workflowKernelStatus.loading ? <CircularProgress size={18} color="inherit" /> : <SpeedIcon />}
                        onClick={async () => {
                          try {
                            setWorkflowKernelStatus({ loading: true, status: 'running', message: 'Starting kernel profiling...', workflowId: null, logs: '', errorDetails: null, runId: null });
                            const pemBase64 = rwSshKey ? btoa(rwSshKey) : null;
                            const modelPath = getWorkflowModelPath(selectedModel);
                            const response = await apiService.workflowKernelProfile({
                              cloud_provider: rwCloudProvider,
                              ssh_host: rwSshHost,
                              ssh_user: rwSshUser,
                              pem_base64: pemBase64,
                              model_path: modelPath,
                              kernel_requests: workflowKernelRequests
                            });
                            setWorkflowKernelStatus({
                              loading: false,
                              status: 'started',
                              message: response.message,
                              workflowId: response.workflow_id,
                              logs: '',
                              errorDetails: null,
                              runId: null
                            });
                            appendWorkflowEvent('kernel_profile', 'info', `Kernel profiling started: ${response.workflow_id}`);

                            const pollLogs = setInterval(async () => {
                              try {
                                const result = await apiService.getWorkflowLogs(response.workflow_id, 'kernel_profile');
                                trackWorkflowProgress('kernel_profile', result.status, result.message);
                                setWorkflowKernelStatus(prev => ({
                                  ...prev,
                                  logs: result.logs || '',
                                  status: result.status || prev.status,
                                  message: result.message || prev.message,
                                  errorDetails: result.error_details || prev.errorDetails,
                                  runId: result.run_id || prev.runId
                                }));

                                if (result.status === 'failed') {
                                  clearInterval(pollLogs);
                                  appendWorkflowEvent('kernel_profile', 'error', result.message || 'Kernel profiling failed');
                                } else if (result.status === 'completed') {
                                  clearInterval(pollLogs);
                                  appendWorkflowEvent('kernel_profile', 'success', 'Kernel profiling completed');
                                }
                              } catch (e) {
                                console.error('Failed to fetch kernel profile logs:', e);
                              }
                            }, 2000);
                            setTimeout(() => clearInterval(pollLogs), 1800000);
                          } catch (e) {
                            setWorkflowKernelStatus({ loading: false, status: 'error', message: e.response?.data?.detail || e.message, workflowId: null, logs: '', errorDetails: null, runId: null });
                            appendWorkflowEvent('kernel_profile', 'error', e.response?.data?.detail || e.message);
                          }
                        }}
                        disabled={workflowKernelStatus.loading || !rwSshHost || !rwSshKey || !deployComplete}
                        sx={{ borderRadius: 2, minWidth: 160 }}
                      >
                        {workflowKernelStatus.loading ? 'Profiling...' : 'Run Kernel Profile'}
                      </Button>

                      {workflowKernelStatus.logs && (
                        <Box sx={{ mt: 3 }}>
                          <Accordion sx={{ borderRadius: 2, '&:before': { display: 'none' } }}>
                            <AccordionSummary
                              expandIcon={<ExpandMoreIcon />}
                              sx={{ backgroundColor: alpha('#2E1A4A', 0.5), borderRadius: '8px' }}
                            >
                              <Stack direction="row" spacing={1.5} alignItems="center">
                                <TerminalIcon sx={{ fontSize: 20, color: 'text.secondary' }} />
                                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                                  View Logs ({workflowKernelStatus.logs.split('\n').length} lines)
                                </Typography>
                              </Stack>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0 }}>
                              <Paper
                                sx={{
                                  p: 2,
                                  backgroundColor: '#1e1e1e',
                                  color: '#d4d4d4',
                                  fontFamily: 'monospace',
                                  fontSize: '0.75rem',
                                  maxHeight: 500,
                                  overflow: 'auto',
                                  borderRadius: '8px',
                                }}
                              >
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                  {workflowKernelStatus.logs}
                                </pre>
                              </Paper>
                            </AccordionDetails>
                          </Accordion>
                        </Box>
                      )}

                      {/* Kernel Results (inline after completion) */}
                      {workflowKernelStatus.status === 'completed' && workflowKernelStatus.runId && (
                        <KernelResultsCard runId={workflowKernelStatus.runId} />
                      )}
                    </CardContent>
                  </Card>
                </CardContent>
              </Card>
            </Stack>

      {/* Migrate Workload Dialog */}
      <Dialog open={migrateDialogOpen} onClose={() => setMigrateDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Migrate Workload</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            {!allowMigration && (
              <Alert severity="warning" sx={{ borderRadius: 2 }}>
                Migration is only available when opened from a running instance via Manage Instances.
              </Alert>
            )}
            {instanceData && (
              <Typography variant="body2" color="text.secondary">
                Current instance: <strong>{instanceData.name || instanceData.id || 'Unknown'}</strong>{' '}
                ({instanceData.provider || 'N/A'}) · Status: {instanceData.status || 'unknown'} ·{' '}
                {instanceData.region || instanceData.zone || 'Unknown region'} ·{' '}
                {instanceData.gpuModel || instanceData.gpuDescription || 'GPU N/A'}{' '}
                {instanceData.gpuCount ? `× ${instanceData.gpuCount}` : ''}
                {currentInstanceCost ? ` · ≈ $${safeToFixed(currentInstanceCost, 2)}/hr` : ''}
              </Typography>
            )}
            <Alert severity="info" sx={{ borderRadius: 2 }}>
              Selecting a target will take you to Manage Instances to launch it. Remember to delete the current
              instance after launching the new one.
            </Alert>
            {aggregatedCatalogLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                <CircularProgress />
              </Box>
            ) : (
              <Stack spacing={2} sx={{ mt: 1 }}>
                {(aggregatedCatalog || []).map((item) => {
                  const cost = item.cost_per_hour_usd || null;
                  const delta = getCostDelta(cost);
                  const deltaLabel =
                    delta === null ? 'N/A' : `${delta > 0 ? '+' : ''}${safeToFixed(delta, 1)}%`;
                  const deltaColor = delta === null ? 'default' : delta <= 0 ? 'success' : 'error';
                  const regionsLabel = item.regions?.length
                    ? `${item.regions.length} region${item.regions.length === 1 ? '' : 's'} available`
                    : 'No regions listed';
                  const selectionDisabled = !migrationEnabled || !cost;
                  return (
                    <Paper key={`${item.provider}-${item.id}`} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2} alignItems="flex-start">
                        <Stack spacing={0.5}>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Chip
                              label={
                                item.provider === 'lambda'
                                  ? 'Lambda'
                                  : item.provider === 'scaleway'
                                  ? 'Scaleway'
                                  : item.provider === 'nebius'
                                  ? 'Nebius'
                                  : item.provider
                              }
                              size="small"
                            />
                            <Chip label={regionsLabel} size="small" variant="outlined" />
                          </Stack>
                          <Typography variant="h6" sx={{ fontWeight: 600 }}>
                            {item.name}
                          </Typography>
                          {item.gpu_model && (
                            <Typography variant="body2" color="text.secondary">
                              {item.gpu_model} {item.num_gpus ? `× ${item.num_gpus}` : ''}
                            </Typography>
                          )}
                          <Typography variant="body2" color="text.secondary">
                            vCPUs: {item.vcpus ?? 'N/A'} · Memory: {item.memory_gb ? `${safeToFixed(item.memory_gb, 0)} GB` : 'N/A'}
                          </Typography>
                          {item.availability && (
                            <Chip
                              label={String(item.availability).toLowerCase()}
                              size="small"
                              color={String(item.availability).toLowerCase() === 'available' ? 'success' : 'default'}
                              sx={{ alignSelf: 'flex-start' }}
                            />
                          )}
                        </Stack>
                        <Stack spacing={1} alignItems="flex-end">
                          <Typography variant="h6" sx={{ fontWeight: 700 }}>
                            {cost ? `$${safeToFixed(cost, 2)}/hr` : 'N/A'}
                          </Typography>
                          <Chip label={deltaLabel} size="small" color={deltaColor} />
                          <Tooltip
                            title={
                              migrationEnabled
                                ? cost
                                  ? 'Review and launch migration'
                                  : 'Cost data unavailable; cannot migrate.'
                                : 'Available only from Manage Instance on a running instance.'
                            }
                          >
                            <span>
                              <Button
                                variant="contained"
                                size="small"
                                disabled={selectionDisabled}
                                onClick={() => {
                                  setSelectedTarget(item);
                                  setConfirmDialogOpen(true);
                                }}
                                sx={{ textTransform: 'none' }}
                              >
                                Choose
                              </Button>
                            </span>
                          </Tooltip>
                        </Stack>
                      </Stack>
                    </Paper>
                  );
                })}
                {!aggregatedCatalogLoading && aggregatedCatalog.length === 0 && (
                  <Alert severity="info" sx={{ borderRadius: 2 }}>
                    No target instances available. Refresh later or adjust provider filters in Manage Instances.
                  </Alert>
                )}
              </Stack>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMigrateDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Confirm Migration Dialog */}
      <Dialog open={confirmDialogOpen} onClose={() => setConfirmDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Confirm Migration</DialogTitle>
        <DialogContent dividers>
          {instanceData && selectedTarget ? (
            <Stack spacing={2}>
              <Typography variant="body2">
                Source: <strong>{instanceData.name || instanceData.id || 'Unknown'}</strong> ({instanceData.provider || 'N/A'}) ·{' '}
                {instanceData.region || instanceData.zone || 'Region N/A'}
              </Typography>
              <Typography variant="body2">
                Target: <strong>{selectedTarget.name}</strong> ({selectedTarget.provider}) ·{' '}
                {(selectedTarget.regions && selectedTarget.regions[0]) || selectedTarget.region || selectedTarget.zone || 'Region N/A'}
              </Typography>
              <Typography variant="body2">
                GPUs: {selectedTarget.gpu_model || 'N/A'} {selectedTarget.num_gpus ? `× ${selectedTarget.num_gpus}` : ''}
              </Typography>
              <Typography variant="body2">
                Cost/hour: {currentInstanceCost ? `$${safeToFixed(currentInstanceCost, 2)}/hr` : 'N/A'} →{' '}
                {selectedTarget.cost_per_hour_usd ? `$${safeToFixed(selectedTarget.cost_per_hour_usd, 2)}/hr` : 'N/A'}
              </Typography>
              <Typography variant="body2">
                Delta: {(() => {
                  const delta = getCostDelta(selectedTarget.cost_per_hour_usd);
                  if (delta === null) return '—';
                  const prefix = delta > 0 ? '+' : '';
                  return `${prefix}${safeToFixed(delta, 1)}%`;
                })()}
              </Typography>
              {!migrationEnabled && (
                <Alert severity="warning" sx={{ borderRadius: 2 }}>
                  Migration available only from Manage Instance on a running instance.
                </Alert>
              )}
              {!selectedTarget.cost_per_hour_usd && (
                <Alert severity="info" sx={{ borderRadius: 2 }}>
                  Target cost unavailable; migration is disabled.
                </Alert>
              )}
            </Stack>
          ) : (
            <Typography variant="body2">No target selected.</Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={
              !migrationEnabled ||
              !selectedTarget ||
              !selectedTarget.cost_per_hour_usd
            }
            onClick={() => {
              // Hand off to Manage Instances to reuse launch/delete flow.
              navigate('/instances', { state: { migrateTarget: selectedTarget, sourceInstance: instanceData } });
            }}
          >
            Continue to Launch
          </Button>
        </DialogActions>
      </Dialog>

      {/* Export Dialog */}
      <Dialog open={exportDialog} onClose={() => setExportDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Export Data</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Choose the format for exporting your benchmark data:
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setExportDialog(false)}>Cancel</Button>
          <Button onClick={exportToJSON} variant="outlined">
            Export as JSON
          </Button>
          <Button onClick={exportToCSV} variant="contained">
            Export as CSV
          </Button>
        </DialogActions>
      </Dialog>
        </Box>
  );
};

export default Benchmarking;
