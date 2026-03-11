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
  Tabs,
  Tab,
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
  Assessment as AssessmentIcon,
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
} from '@mui/icons-material';
import apiService from '../services/api';
import SystemBenchmarkDashboard from '../components/SystemBenchmarkDashboard';
import TelemetryTab from '../components/TelemetryTab';
import ProvisioningTab from '../components/ProvisioningTab';
import WorkflowStepper from '../components/WorkflowStepper';
import { alpha, useTheme } from '@mui/material';
import { useUI } from '../components/ui/UIProvider';
import RefreshControl from '../components/ui/RefreshControl';

const Benchmarking = () => {
  const theme = useTheme();
  
  // State management
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const location = useLocation();
  const navigate = useNavigate();
  
  // Tabs
  const [selectedTab, setSelectedTab] = useState(0);
  
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
  const [rwCloudProvider, setRwCloudProvider] = useState('lambda'); // 'lambda' or 'scaleway'
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
  const [setupComplete, setSetupComplete] = useState(false);
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
  const [workflowBenchmarkStatus, setWorkflowBenchmarkStatus] = useState({ loading: false, status: null, message: null, workflowId: null, logs: '', errorDetails: null });
  const [workflowEvents, setWorkflowEvents] = useState([]);
  const workflowProgressRef = useRef({
    setup: '',
    check: '',
    deploy: '',
    benchmark: '',
  });
  
  // Benchmark parameters for workflow
  const [workflowInputSeqLen, setWorkflowInputSeqLen] = useState(1000);
  const [workflowOutputSeqLen, setWorkflowOutputSeqLen] = useState(1000);
  const [workflowNumRequests, setWorkflowNumRequests] = useState(10000);
  const [workflowRequestRate, setWorkflowRequestRate] = useState(25.0);
  const [workflowMaxConcurrency, setWorkflowMaxConcurrency] = useState(256);
  const [lastUpdated, setLastUpdated] = useState(null);
  const { showToast } = useUI();

  const getWorkflowModelPath = (modelName = selectedModel) => (
    rwCloudProvider === 'scaleway'
      ? `/scratch/BM/models/${modelName.split('/').pop()}`
      : `/home/ubuntu/BM/models/${modelName.split('/').pop()}`
  );

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

  const handleRefresh = () => {
    // Simple page reload until APIs are reorganized
    window.location.reload();
  };
  
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
    setLastUpdated(Date.now());
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

    if (state.openTelemetry) {
      setSelectedTab(0); // Telemetry tab is index 0
    } else if (state.openRunWorkload) {
      setSelectedTab(2); // Run Workload tab is index 2
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
    // Only update fields if we're on the Run Workload tab
    if (selectedTab !== 2) return;

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
  }, [instanceData, selectedTab]);

  useEffect(() => {
    if (selectedSystem) {
      loadSystemData(selectedSystem);
    }
  }, [selectedSystem]);

  // Load instances when tab 3 is selected
  useEffect(() => {
    // Removed: Tab 4 (Instance Management) no longer exists
    // if (selectedTab === 4) {
    //   loadLambdaInstances();
    // }
  }, [selectedTab]);

  // Load GPU metrics when tab 2 is selected
  useEffect(() => {
    // Removed: Tab 2 (GPU Metrics) no longer exists
    // if (selectedTab === 2 && selectedSystem) {
    //   loadGpuMetrics(selectedSystem);
    // }
  }, [selectedTab, selectedSystem]);

  return (
    <Box sx={{ p: 4, maxWidth: '1920px', mx: 'auto' }}>
      {/* Header Section */}
      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <AssessmentIcon color="primary" sx={{ fontSize: '2rem' }} />
            Profiling Dashboard
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            View benchmarking results, GPU metrics, and manage your instances
          </Typography>
        </Box>
        <RefreshControl lastUpdated={lastUpdated} loading={loading} onRefresh={handleRefresh} />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 4 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Tabs Section */}
      <Card sx={{ mb: 4, borderRadius: 3 }}>
        <Tabs 
          value={selectedTab} 
          onChange={(e, newValue) => setSelectedTab(newValue)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ 
            borderBottom: 1, 
            borderColor: 'divider',
            px: 2,
            '& .MuiTab-root': {
              py: 2.5,
              fontSize: '0.9375rem',
              fontWeight: 500
            }
          }}
        >
          <Tab label="Telemetry" icon={<TimelineIcon />} iconPosition="start" />
          <Tab label="Agent Provisioning" icon={<CloudDownloadIcon />} iconPosition="start" />
          <Tab label="Run Workload" icon={<PlayArrowIcon />} iconPosition="start" />
        </Tabs>

        {/* Tab 0: Telemetry */}
        {selectedTab === 0 && (
          <TelemetryTab
            instanceData={instanceData}
            onNavigateToInstances={() => navigate('/instances')}
          />
        )}

        {/* Tab 1: Agent Provisioning */}
        {selectedTab === 1 && (
          <ProvisioningTab
            instanceData={instanceData}
            onNavigateToInstances={() => navigate('/instances')}
            onNavigateToTelemetry={(instanceId, runId) => {
              setSelectedTab(0); // Switch to Telemetry tab
              // TelemetryTab will pick up the instance from location state or we can set it
              if (runId) {
                // Store runId in location state for TelemetryTab to use
                navigate(`/benchmarking?instance=${instanceId}&run=${runId}`, { replace: true });
              }
            }}
          />
        )}

        {/* Tab 2: Run Workload */}
        {selectedTab === 2 && (
          <Box sx={{ p: { xs: 2, sm: 3, md: 4 } }}>
            <Stack spacing={4}>
              {/* Header */}
              <Box>
                <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1, justifyContent: 'space-between' }}>
                  <Box
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      backgroundColor: alpha('#3DA866', 0.1),
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <PlayArrowIcon sx={{ color: 'primary.main', fontSize: 28 }} />
                  </Box>
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="h4" sx={{ fontWeight: 700, mb: 0.5 }}>
                      Run Workload
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Execute the complete workflow: Setup → Check → Deploy → Benchmark
                    </Typography>
                  </Box>
                  <Tooltip
                    title={
                      migrationEnabled
                        ? 'Compare and migrate workload'
                        : 'Available only from Manage Instance on a running instance.'
                    }
                  >
                    <span>
                      <Button
                        variant="outlined"
                        startIcon={<RocketLaunchIcon />}
                        disabled={!migrationEnabled || !instanceData}
                        onClick={handleOpenMigrateDialog}
                        sx={{ textTransform: 'none' }}
                      >
                        Migrate Workload
                      </Button>
                    </span>
                  </Tooltip>
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
                    <TextField
                        label="SSH Private Key (PEM)" 
                      fullWidth
                        value={rwSshKey} 
                        onChange={(e) => setRwSshKey(e.target.value)}
                        multiline
                        minRows={4}
                        placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...&#10;-----END OPENSSH PRIVATE KEY-----"
                        helperText="Paste your SSH private key here. This will be used to securely access the instance."
                        required
                        sx={{ 
                          '& .MuiOutlinedInput-root': { borderRadius: '8px' },
                          '& textarea': { WebkitTextSecurity: 'disc' }
                        }}
                    />
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

              <Card sx={{ borderRadius: 3, border: `1px solid ${alpha('#000', 0.1)}` }}>
                <CardContent sx={{ p: 3 }}>
                  <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      <TerminalIcon sx={{ color: 'primary.main' }} />
                      <Typography variant="h6" sx={{ fontWeight: 600 }}>
                        Workflow Activity Log
                      </Typography>
                    </Stack>
                    <Button
                      variant="text"
                      size="small"
                      onClick={() => {
                        workflowProgressRef.current = { setup: '', check: '', deploy: '', benchmark: '' };
                        setWorkflowEvents([]);
                      }}
                      disabled={workflowEvents.length === 0}
                    >
                      Clear
                    </Button>
                  </Stack>
                  {workflowEvents.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      No events yet. Start a phase to see live workflow status transitions.
                    </Typography>
                  ) : (
                    <Paper
                      sx={{
                        p: 2,
                        maxHeight: 280,
                        overflow: 'auto',
                        backgroundColor: alpha('#1E4530', 0.35),
                        borderRadius: 2,
                      }}
                    >
                      <Stack spacing={1}>
                        {workflowEvents.map((event) => (
                          <Stack
                            key={event.id}
                            direction={{ xs: 'column', sm: 'row' }}
                            spacing={1}
                            alignItems={{ xs: 'flex-start', sm: 'center' }}
                          >
                            <Chip size="small" color={getEventColor(event.level)} label={event.phase} />
                            <Typography variant="caption" color="text.secondary" sx={{ minWidth: 90 }}>
                              {new Date(event.ts).toLocaleTimeString()}
                            </Typography>
                            <Typography variant="body2">{event.message}</Typography>
                          </Stack>
                        ))}
                      </Stack>
                    </Paper>
                  )}
                </CardContent>
              </Card>

              {/* Cloud Provider Tabs */}
              <Card sx={{ borderRadius: 3, border: `1px solid ${alpha('#000', 0.1)}`, mb: 3 }}>
                <CardContent sx={{ p: 2 }}>
                  <Tabs 
                    value={rwCloudProvider === 'lambda' ? 0 : 1} 
                    onChange={(e, newValue) => {
                      setRwCloudProvider(newValue === 0 ? 'lambda' : 'scaleway');
                      // Update SSH user based on provider
                      setRwSshUser(newValue === 0 ? 'ubuntu' : 'root');
                      // Reset workflow statuses when switching providers
                      setWorkflowSetupStatus({ loading: false, status: null, message: null, workflowId: null, logs: '' });
                      setWorkflowCheckStatus({ loading: false, status: null, message: null, workflowId: null, logs: '' });
                      setWorkflowDeployStatus({ loading: false, status: null, message: null, workflowId: null, logs: '' });
                      setWorkflowBenchmarkStatus({ loading: false, status: null, message: null, workflowId: null, logs: '', errorDetails: null });
                      workflowProgressRef.current = { setup: '', check: '', deploy: '', benchmark: '' };
                      setWorkflowEvents([]);
                    }}
                    sx={{ borderBottom: 1, borderColor: 'divider' }}
                  >
                    <Tab label="Lambda" icon={<CloudIcon />} iconPosition="start" />
                    <Tab label="Scaleway" icon={<CloudIcon />} iconPosition="start" />
                  </Tabs>
                </CardContent>
              </Card>

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
                                  : workflowSetupStatus.status === 'started'
                                  ? 'Starting...'
                                  : 'Not Started'
                              }
                              color={
                                workflowSetupStatus.status === 'completed'
                                  ? 'success'
                                  : workflowSetupStatus.status === 'failed'
                                  ? 'error'
                                  : workflowSetupStatus.status === 'running' || workflowSetupStatus.status === 'started'
                                  ? 'info'
                                  : 'default'
                              }
                          size="small"
                              sx={{ fontWeight: 500 }}
                            />
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
                                
                                if (result.status === 'completed' || result.status === 'failed') {
                                  appendWorkflowEvent(
                                    'setup',
                                    result.status === 'completed' ? 'success' : 'error',
                                    result.message || `Setup ${result.status}`
                                  );
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
                                backgroundColor: alpha('#1E4530', 0.5),
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
                          </Stack>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            Verify nvidia-smi and restart DCGM service.
                          </Typography>
                        </Box>
                      </Stack>

                      {workflowSetupStatus.status !== 'completed' && (
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
                        disabled={workflowCheckStatus.loading || !rwSshHost || !rwSshKey || workflowSetupStatus.status !== 'completed'}
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
                                backgroundColor: alpha('#1E4530', 0.5),
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
                          </Stack>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            Start inference server with adaptive GPU parameters.
                          </Typography>
                        </Box>
                      </Stack>

                      {workflowCheckStatus.status !== 'completed' && (
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
                        disabled={workflowDeployStatus.loading || !rwSshHost || !rwSshKey || workflowCheckStatus.status !== 'completed'}
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
                                backgroundColor: alpha('#1E4530', 0.5),
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

                      {workflowDeployStatus.status !== 'completed' && (
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
                          backgroundColor: alpha('#1E4530', 0.3),
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

                      {(workflowBenchmarkStatus.status === 'running' || workflowBenchmarkStatus.status === 'started' || workflowBenchmarkStatus.loading) && (
                        <Box sx={{ mb: 2 }}>
                          <LinearProgress sx={{ borderRadius: 1, height: 6 }} />
                          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                            {workflowBenchmarkStatus.loading ? 'Initializing...' : 'Processing...'}
                          </Typography>
                        </Box>
                )}

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
                                  errorDetails: result.error_details || prev.errorDetails
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
                        disabled={workflowBenchmarkStatus.loading || !rwSshHost || !rwSshKey || workflowDeployStatus.status !== 'completed'}
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
                                backgroundColor: alpha('#1E4530', 0.5),
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
                </CardContent>
              </Card>
            </Stack>
          </Box>
        )}

        {/* Removed tabs: Overview, Detailed Profiling Results, GPU Metrics, Instance Management */}
      </Card>

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
