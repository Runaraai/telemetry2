import axios from 'axios';

const deriveDefaultBaseUrl = () => {
  // If REACT_APP_API_URL is explicitly set (even if empty), use it
  if (process.env.REACT_APP_API_URL !== undefined) {
    // Empty string means use relative URLs (current origin)
    if (process.env.REACT_APP_API_URL === '') {
      return '';
    }
    return process.env.REACT_APP_API_URL;
  }

  // Always use relative URLs when behind nginx proxy (which proxies /api/ to backend)
  // This ensures API calls work regardless of the origin (IP, domain, localhost, etc.)
  // The nginx proxy handles routing /api/ requests to the backend
  if (typeof window !== 'undefined') {
    // Use relative URLs so requests go through nginx proxy
    return '';
  }

  // Fallback to empty string for relative URLs if not set
  return '';
};

const API_BASE_URL = deriveDefaultBaseUrl();
const BASE = API_BASE_URL; // For the postJSON function

const stripTrail = (value) => value.replace(/\/+$/, '');

const buildWsUrl = (path) => {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  // When API_BASE_URL is relative (empty string), derive websocket host from the page origin.
  if (!API_BASE_URL && typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}${normalizedPath}`;
  }

  try {
    const url = new URL(API_BASE_URL);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = normalizedPath;
    url.search = '';
    url.hash = '';
    return url.toString();
  } catch (error) {
    const normalized = stripTrail(API_BASE_URL);
    const host = normalized.replace(/^https?:\/\//, '').replace(/\/.*$/, '');
    const protocol = normalized.startsWith('https://') ? 'wss://' : 'ws://';
    return `${protocol}${host}${normalizedPath}`;
  }
};

export const telemetryUtils = {
  buildWsUrl,
  parseTimestamp: (iso) => {
    if (!iso) return null;
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? null : date;
  },
};

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 90000, // 90 second timeout to prevent hanging requests (increased for Lambda API calls)
});

// Add request interceptor for authentication and debugging
api.interceptors.request.use(
  (config) => {
    // Add auth token if available
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    
    console.log(`[API Request] ${config.method?.toUpperCase()} ${config.url}`, {
      baseURL: config.baseURL,
      headers: config.headers,
    });
    return config;
  },
  (error) => {
    console.error('[API Request Error]', error);
    return Promise.reject(error);
  }
);

// Add response interceptor for debugging and auth error handling
api.interceptors.response.use(
  (response) => {
    console.log(`[API Response] ${response.config.method?.toUpperCase()} ${response.config.url}`, {
      status: response.status,
      statusText: response.statusText,
    });
    return response;
  },
  async (error) => {
    console.error(`[API Error] ${error.config?.method?.toUpperCase()} ${error.config?.url}`);
    console.error('Error status:', error.response?.status);
    console.error('Error statusText:', error.response?.statusText);
    console.error('Error message:', error.message);
    console.error('Error response data:', error.response?.data);
    console.error('Error response data (stringified):', JSON.stringify(error.response?.data, null, 2));
    if (error.response?.data?.detail) {
      console.error('Error detail:', error.response.data.detail);
    }
    console.error('Full error object:', {
      status: error.response?.status,
      statusText: error.response?.statusText,
      message: error.message,
      data: error.response?.data,
    });
    
    // Handle 401 Unauthorized - clear token and redirect to login
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      // Don't redirect here, let components handle it
    }

    // Retry transient gateway errors for idempotent GETs (Cloudflare/nginx can return 502 during restarts).
    const status = error.response?.status;
    const method = (error.config?.method || '').toLowerCase();
    if (method === 'get' && (status === 502 || status === 503 || status === 504)) {
      const config = error.config || {};
      config.__retryCount = config.__retryCount || 0;
      if (config.__retryCount < 2) {
        config.__retryCount += 1;
        const delayMs = 500 * Math.pow(2, config.__retryCount - 1);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        return api.request(config);
      }
    }
    
    return Promise.reject(error);
  }
);

async function postJSON(path, body) {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export const apiService = {
  // Health check
  healthCheck: async () => {
    const response = await api.get('/health');
    return response.data;
  },

  // Analyze workload
  analyzeWorkload: async (request) => {
    const response = await api.post('/api/v1/analysis/analyze-simple', request);
    return response.data;
  },

  // Interactive analysis
  analyzeInteractive: async (request) => {
    console.log('Sending analysis request:', request);
    try {
      const response = await api.post('/api/v1/analysis/analyze-interactive', request);
      console.log('Analysis response received:', response.data);
      return response.data;
    } catch (error) {
      console.error('API call failed:', error);
      console.error('Error response:', error.response?.data);
      throw error;
    }
  },

  // Cross-platform metrics
  crossPlatformMetrics: async (request) => {
    // request: { model: string, hardware_list: string[], ...optional overrides }
    const response = await api.post('/api/v1/analysis/cross-platform-metrics', request);
    return response.data;
  },

  // Hierarchy API endpoints
  getClusterOverview: async () => {
    const response = await api.get('/api/v1/hierarchy/cluster');
    return response.data;
  },

  getRackDetails: async (rackId) => {
    const response = await api.get(`/api/v1/hierarchy/rack/${rackId}`);
    return response.data;
  },

  getPodAnalysis: async (podId) => {
    const response = await api.get(`/api/v1/hierarchy/pod/${podId}`);
    return response.data;
  },

  getDeviceMetrics: async (deviceId) => {
    const response = await api.get(`/api/v1/hierarchy/device/${deviceId}`);
    return response.data;
  },

  getOperatorProfiling: async (modelId, layerId) => {
    const response = await api.get(`/api/v1/hierarchy/operator/${modelId}/${layerId}`);
    return response.data;
  },

  buildHierarchy: async (config) => {
    const response = await api.post('/api/v1/hierarchy/build', config);
    return response.data;
  },

  // Get models
  getModels: async () => {
    const response = await api.get('/api/v1/data/models');
    return response.data;
  },

  // Get hardware configurations
  getHardware: async () => {
    const response = await api.get('/api/v1/data/hardware');
    return response.data;
  },

  // Get example workloads
  getExampleWorkloads: async () => {
    const response = await api.get('/examples/workloads');
    return response.data;
  },

  // Get example hardware configurations
  getExampleHardware: async () => {
    const response = await api.get('/examples/hardware');
    return response.data;
  },

  // Get specific example workload
  getExampleWorkload: async (workloadName) => {
    const response = await api.get(`/examples/workloads/${workloadName}`);
    return response.data;
  },

  // Get specific example hardware configuration
  getExampleHardwareConfig: async (hardwareName) => {
    const response = await api.get(`/examples/hardware/${hardwareName}`);
    return response.data;
  },

  // Get hardware details for specific category and file
  getHardwareDetails: async (category, fileName) => {
    const response = await api.get(`/examples/hardware/${category}/${fileName}`);
    return response.data;
  },

  // Get complete hierarchical hardware (A100/H100/B100)
  getHierarchicalHardware: async (hardwareName) => {
    const response = await api.get(`/examples/hierarchical/${hardwareName}`);
    return response.data;
  },

  // Datacentre structure API endpoints
  getDatacentreStructure: async (datacentreName) => {
    const response = await api.get(`/examples/datacentre/${datacentreName}`);
    return response.data;
  },

  getClusterData: async (datacentreName, clusterType) => {
    const response = await api.get(`/examples/datacentre/${datacentreName}/cluster/${clusterType}`);
    return response.data;
  },

  getRackData: async (datacentreName, clusterType) => {
    const response = await api.get(`/examples/datacentre/${datacentreName}/cluster/${clusterType}/rack`);
    return response.data;
  },

  getNodeData: async (datacentreName, clusterType) => {
    const response = await api.get(`/examples/datacentre/${datacentreName}/cluster/${clusterType}/node`);
    return response.data;
  },

  getDeviceData: async (datacentreName, clusterType) => {
    const response = await api.get(`/examples/datacentre/${datacentreName}/cluster/${clusterType}/device`);
    return response.data;
  },

  getSmData: async (datacentreName, clusterType) => {
    const response = await api.get(`/examples/datacentre/${datacentreName}/cluster/${clusterType}/sm`);
    return response.data;
  },

  getTensorCoreData: async (datacentreName, clusterType) => {
    const response = await api.get(`/examples/datacentre/${datacentreName}/cluster/${clusterType}/tensor_core`);
    return response.data;
  },

  // Telemetry Runs
  createTelemetryRun: async (payload) => {
    const response = await api.post('/api/runs', payload);
    return response.data;
  },

  listTelemetryRuns: async (params = {}) => {
    const searchParams = new URLSearchParams();
    if (params.instance_id) searchParams.append('instance_id', params.instance_id);
    if (params.status) searchParams.append('status', params.status);
    if (params.limit) searchParams.append('limit', params.limit);
    const query = searchParams.toString();
    const response = await api.get(`/api/runs${query ? `?${query}` : ''}`);
    return response.data;
  },

  getTelemetryRun: async (runId) => {
    const response = await api.get(`/api/runs/${runId}`);
    return response.data;
  },

  getTelemetryRunProfile: async (runId) => {
    const response = await api.get(`/api/telemetry/profiling/runs/${runId}`);
    return response.data;
  },

  updateTelemetryRun: async (runId, payload) => {
    const response = await api.patch(`/api/runs/${runId}`, payload);
    return response.data;
  },

  deleteTelemetryRun: async (runId) => {
    await api.delete(`/api/runs/${runId}`);
    return { success: true };
  },

  // Telemetry History
  listAllTelemetryRuns: async (params = {}) => {
    const searchParams = new URLSearchParams();
    if (params.limit) searchParams.append('limit', params.limit);
    const query = searchParams.toString();
    const response = await api.get(`/api/runs/history/all${query ? `?${query}` : ''}`);
    return response.data;
  },

  listRunsWithNoData: async () => {
    const response = await api.get('/api/runs/history/no-data');
    return response.data;
  },

  cleanupRunsWithNoData: async () => {
    const response = await api.delete('/api/runs/cleanup/no-data');
    return response.data;
  },

  bulkUpdateRunsStatus: async (status, instanceId = null) => {
    const searchParams = new URLSearchParams();
    searchParams.append('status', status);
    if (instanceId) searchParams.append('instance_id', instanceId);
    const response = await api.patch(`/api/runs/bulk/status?${searchParams.toString()}`);
    return response.data;
  },

  // Telemetry Metrics
  getTelemetryMetrics: async (runId, params = {}) => {
    const searchParams = new URLSearchParams();
    if (params.start_time) searchParams.append('start_time', params.start_time);
    if (params.end_time) searchParams.append('end_time', params.end_time);
    if (params.gpu_id !== undefined && params.gpu_id !== null) {
      searchParams.append('gpu_id', params.gpu_id);
    }
    if (params.limit) searchParams.append('limit', params.limit);
    const query = searchParams.toString();
    const response = await api.get(`/api/runs/${runId}/metrics${query ? `?${query}` : ''}`);
    return response.data;
  },

  // Telemetry Deployment
  deployTelemetryStack: async (instanceId, payload, deploymentType = 'ssh') => {
    const url = `/api/instances/${instanceId}/deploy${deploymentType ? `?deployment_type=${deploymentType}` : ''}`;
    const response = await api.post(url, payload);
    return response.data;
  },

  getTelemetryDeploymentStatus: async (instanceId, deploymentId) => {
    const response = await api.get(`/api/instances/${instanceId}/deployments/${deploymentId}`);
    return response.data;
  },

  getTelemetryPrerequisites: async () => {
    const response = await api.get(`/api/instances/prerequisites`);
    return response.data;
  },

  getTelemetryComponentStatus: async (instanceId, runId = null) => {
    const params = runId ? { run_id: runId } : {};
    const response = await api.get(`/api/instances/${instanceId}/component-status`, { params });
    return response.data;
  },

  teardownTelemetryStack: async (instanceId, payload) => {
    const response = await api.post(`/api/instances/${instanceId}/teardown`, payload);
    return response.data;
  },

  getTelemetryWebSocketUrl: (runId) => {
    const baseUrl = buildWsUrl(`/ws/runs/${runId}/live`);
    // Add JWT token if available for authenticated access
    const token = localStorage.getItem('auth_token');
    if (token) {
      // URL encode the Bearer token
      const authParam = encodeURIComponent(`Bearer ${token}`);
      const separator = baseUrl.includes('?') ? '&' : '?';
      return `${baseUrl}${separator}authorization=${authParam}`;
    }
    return baseUrl;
  },

  // Get decoder graph for a model - THIS IS THE KEY MISSING METHOD
  getDecoderGraph: async (modelBase) => {
    const response = await api.get(`/api/examples/decoder/${modelBase}`);
    return response.data;
  },

  // List all available decoder files
  listDecoders: async () => {
    const response = await api.get('/api/examples/decoder');
    return response.data;
  },

  // System-Based Benchmark APIs
  getSystemSummary: async (system) => {
    const response = await api.get(`/api/benchmarks/${system}`);
    return response.data;
  },

  getBenchmarkSystems: async () => {
    const response = await api.get('/api/benchmarks/systems');
    return response.data;
  },

  getDashboardSystemData: async (system) => {
    const response = await api.get(`/api/dashboard/${system}/data`);
    return response.data;
  },

  getDashboardGpuMetrics: async (system) => {
    const response = await api.get(`/api/dashboard/${system}/gpu-metrics`);
    return response.data;
  },

  getSystemBenchmarks: async (system) => {
    const response = await api.get(`/api/benchmarks/${system}/benchmarks`);
    return response.data;
  },

  getBenchmarkData: async (system, filename) => {
    const response = await api.get(`/api/benchmarks/${system}/${filename}`);
    return response.data;
  },

  getBenchmarkSummary: async (system, filename) => {
    const response = await api.get(`/api/benchmarks/${system}/${filename}/summary`);
    return response.data;
  },

  getBenchmarkMetrics: async (system, filename) => {
    const response = await api.get(`/api/benchmarks/${system}/${filename}/metrics`);
    return response.data;
  },

  compareSystems: async (systems) => {
    const response = await api.get(`/api/benchmarks/compare?systems=${systems.join(',')}`);
    return response.data;
  },

  // New System-Based Dashboard APIs
  getDashboardSystems: async () => {
    const response = await api.get('/api/dashboard/systems', {
      timeout: 60000, // 60 second timeout for dashboard systems
    });
    return response.data;
  },

  getSystemOverview: async (system) => {
    const response = await api.get(`/api/dashboard/${system}/overview`);
    return response.data;
  },

  getSystemThroughput: async (system) => {
    const response = await api.get(`/api/dashboard/${system}/throughput`);
    return response.data;
  },

  getSystemUtilization: async (system) => {
    const response = await api.get(`/api/dashboard/${system}/utilization`);
    return response.data;
  },

  getSystemBandwidth: async (system) => {
    const response = await api.get(`/api/dashboard/${system}/bandwidth`);
    return response.data;
  },

  getSystemPower: async (system) => {
    const response = await api.get(`/api/dashboard/${system}/power`);
    return response.data;
  },

  compareSystemsDashboard: async (systems) => {
    const response = await api.get(`/api/dashboard/compare?systems=${systems.join(',')}`);
    return response.data;
  },

  // Legacy Profiling Dashboard APIs (for backward compatibility)
  getProfilingDashboardList: async () => {
    const response = await api.get('/api/profiling/dashboard/list');
    return response.data;
  },

  getProfilingDashboardData: async (filename) => {
    const response = await api.get(`/api/profiling/dashboard/${filename}`);
    return response.data;
  },

  getProfilingDashboardSummary: async (filename) => {
    const response = await api.get(`/api/profiling/dashboard/${filename}/summary`);
    return response.data;
  },

  getProfilingMetrics: async (filename) => {
    const response = await api.get(`/api/profiling/dashboard/${filename}/metrics`);
    return response.data;
  },

  // Tensor operations
  tensorInventory: async (hardwareYaml) => {
    return postJSON("/tensor-inventory", { hardware_yaml: hardwareYaml });
  },

  tensorCoreCapability: async (hardwareYaml, dtype, includeMemTiming=false) => {
    return postJSON("/tensor-core/capability", { 
      hardware_yaml: hardwareYaml, 
      dtype, 
      include_mem_timing: includeMemTiming 
    });
  },

  analyzeGemm: async (hardwareYaml, dtype, M, N, K, bytesMoved=null) => {
    return postJSON("/tensor-core/analyze-gemm", { 
      hardware_yaml: hardwareYaml, 
      dtype, 
      M, 
      N, 
      K, 
      bytes_moved: bytesMoved 
    });
  },

  // File upload analysis
  analyzeWorkloadUpload: async (workloadFile, hardwareFile, pricingFile, slosFile) => {
    const formData = new FormData();
    formData.append('workload_file', workloadFile);
    formData.append('hardware_file', hardwareFile);
    formData.append('pricing_file', pricingFile);
    formData.append('slos_file', slosFile);
    
    const response = await api.post('/analyze/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  // Dual-view workload visualization

  // Benchmark data endpoints
  getBenchmarkData: async () => {
    const response = await api.get('/benchmark/data');
    return response.data;
  },

  getBenchmarkModels: async () => {
    const response = await api.get('/benchmark/models');
    return response.data;
  },

  getBenchmarkResults: async (modelName) => {
    const response = await api.get(`/benchmark/results/${modelName}`);
    return response.data;
  },

  // New comprehensive dashboard endpoints
  getDashboardMetadata: async () => {
    const response = await api.get('/benchmark/dashboard/metadata');
    return response.data;
  },

  getDetailedMetrics: async (filters = {}) => {
    const params = new URLSearchParams();
    if (filters.model) params.append('model', filters.model);
    if (filters.batch_size) params.append('batch_size', filters.batch_size);
    if (filters.min_input_length) params.append('min_input_length', filters.min_input_length);
    if (filters.max_input_length) params.append('max_input_length', filters.max_input_length);
    const response = await api.get(`/benchmark/dashboard/detailed-metrics?${params.toString()}`);
    return response.data;
  },

  getTimeSeriesData: async (metric) => {
    const response = await api.get(`/benchmark/dashboard/time-series?metric=${metric}`);
    return response.data;
  },

  getComparisonData: async (models = null, batchSizes = null) => {
    const params = new URLSearchParams();
    if (models) params.append('models', models);
    if (batchSizes) params.append('batch_sizes', batchSizes);
    const response = await api.get(`/benchmark/dashboard/comparison?${params.toString()}`);
    return response.data;
  },

  getSummaryTable: async () => {
    const response = await api.get('/benchmark/dashboard/summary-table');
    return response.data;
  },

  // Instance management endpoints
  getAllInstancesStatus: async () => {
    const response = await api.get('/api/status');
    return response.data;
  },

  // Lambda Cloud API endpoints
  getLambdaCloudInstances: async (apiKey) => {
    const response = await api.get('/api/v1/lambda-cloud/instances', {
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {},
      timeout: 60000, // 60 second timeout for Lambda API calls (may need retries)
    });
    console.log('[API] getLambdaCloudInstances response:', response.data);
    return response.data;
  },

  getLambdaCloudInstanceDetails: async (instanceId, apiKey) => {
    const response = await api.get(`/api/v1/lambda-cloud/instances/${instanceId}`, {
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {},
      timeout: 60000, // 60 second timeout for Lambda API calls
    });
    return response.data;
  },

  getLambdaCloudInstanceTypes: async (apiKey) => {
    const response = await api.get('/api/v1/lambda-cloud/instance-types', {
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {},
      timeout: 90000, // 90 second timeout for Lambda API calls (may need retries)
    });
    return response.data;
  },

  getLambdaCloudRegions: async (apiKey) => {
    const response = await api.get('/api/v1/lambda-cloud/regions', {
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {},
      timeout: 90000, // 90 second timeout for Lambda API calls (may need retries)
    });
    return response.data;
  },

  checkLambdaCloudHealth: async (apiKey) => {
    const response = await api.get('/api/v1/lambda-cloud/health', {
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {}
    });
    return response.data;
  },

  getLambdaCloudConfig: async () => {
    const response = await api.get('/api/v1/lambda-cloud/config');
    return response.data;
  },

  // Config: persist Lambda key to backend
  saveLambdaKeyToBackend: async (apiKey) => {
    const response = await api.post('/api/v1/config/lambda-key', { api_key: apiKey });
    return response.data;
  },

  launchLambdaInstance: async (apiKey, payload) => {
    const response = await api.post('/api/v1/lambda-cloud/instance-operations/launch', payload, {
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {}
    });
    return response.data;
  },

  getLambdaSshKeys: async (apiKey) => {
    const response = await api.get('/api/v1/lambda-cloud/ssh-keys', {
      timeout: 90000, // 90 second timeout for Lambda API calls (may need retries)
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {}
    });
    return response.data;
  },

  createLambdaSshKey: async (apiKey, name, publicKey) => {
    const response = await api.post('/api/v1/lambda-cloud/ssh-keys', { name, public_key: publicKey }, {
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {}
    });
    return response.data;
  },

  deleteLambdaSshKey: async (apiKey, keyId) => {
    const response = await api.delete(`/api/v1/lambda-cloud/ssh-keys/${keyId}`, {
      headers: apiKey ? { 'x-lambda-api-key': apiKey } : {}
    });
    return response.data;
  },

  // Scaleway API (proxied through backend)
  getScalewayRegions: async () => {
    const response = await api.get('/api/scaleway/regions');
    return response.data;
  },

  getScalewayProducts: async ({ zone, secretKey, accessKey = null, projectId = null, gpuOnly = true }) => {
    const response = await api.post('/api/scaleway/products', {
      zone,
      secret_key: secretKey,
      access_key: accessKey,
      project_id: projectId,
      gpu_only: gpuOnly,
      availability: true
    });
    return response.data;
  },

  getScalewayInstances: async ({ zone, secretKey, projectId = null, page = 1, perPage = 50 }) => {
    const response = await api.post('/api/scaleway/instances', {
      zone,
      secret_key: secretKey,
      project_id: projectId,
      page,
      per_page: perPage,
    });
    return response.data;
  },

  launchScalewayInstance: async ({
    zone,
    secretKey,
    projectId,
    commercialType,
    publicKey,
    sshKeyName = null,
    image = 'ubuntu_jammy',
    name = null,
    rootVolumeSize = null, // in bytes, null means use default
    rootVolumeType = null, // 'l_ssd' or 'sbs_volume', null means use default
  }) => {
    const payload = {
      zone,
      secret_key: secretKey,
      project_id: projectId,
      commercial_type: commercialType,
      public_key: publicKey,
      ssh_key_name: sshKeyName,
      image,
      name,
    };
    // Only include volume parameters if explicitly provided
    if (rootVolumeSize !== null && rootVolumeSize !== undefined) {
      payload.root_volume_size = rootVolumeSize;
    }
    if (rootVolumeType !== null && rootVolumeType !== undefined) {
      payload.root_volume_type = rootVolumeType;
    }
    const response = await api.post('/api/scaleway/launch', payload, {
      timeout: 180000, // 3 minutes timeout - launch can take time with flexible IP creation/attachment
    });
    return response.data;
  },

  deleteScalewayInstance: async ({ zone, serverId, secretKey, projectId }) => {
    const response = await api.post('/api/scaleway/delete', {
      zone,
      server_id: serverId,
      secret_key: secretKey,
      project_id: projectId,
    });
    return response.data;
  },

  getScalewayServerStatus: async ({ zone, serverId, secretKey, projectId }) => {
    const response = await api.post('/api/scaleway/server-status', {
      zone,
      server_id: serverId,
      secret_key: secretKey,
      project_id: projectId,
    });
    return response.data;
  },

  // Nebius API (proxied through backend)
  getNebiusRegions: async () => {
    const response = await api.get('/api/nebius/regions');
    return response.data;
  },

  getNebiusPlatforms: async (payload) => {
    const response = await api.post('/api/nebius/platforms', payload);
    return response.data;
  },

  // Nebius Instance Management API (Direct API pattern)
  getNebiusInstances: async (credentials, projectId) => {
    const response = await api.post('/api/v1/nebius/instances', {
      credentials,
      project_id: projectId,
    });
    return response.data;
  },

  getNebiusPresets: async (credentials, projectId, region = null) => {
    const payload = {
      credentials,
      project_id: projectId,
    };
    if (region) {
      payload.region = region;
    }
    const response = await api.post('/api/v1/nebius/presets', payload);
    return response.data;
  },

  launchNebiusInstance: async (credentials, projectId, presetId, sshPublicKey, zoneId = null, sshKeyName = null) => {
    const response = await api.post('/api/v1/nebius/launch', {
      credentials,
      project_id: projectId,
      preset_id: presetId,
      ssh_public_key: sshPublicKey,
      zone_id: zoneId,
      ssh_key_name: sshKeyName,
    });
    return response.data;
  },

  deleteNebiusInstance: async (credentials, projectId, instanceId) => {
    const response = await api.post('/api/v1/nebius/delete', {
      credentials,
      project_id: projectId,
      instance_id: instanceId,
    });
    return response.data;
  },

  // Aggregated instances endpoint
  getAggregatedInstances: async () => {
    const response = await api.get('/api/instances/aggregated', {
      timeout: 90000, // 90 second timeout to allow all providers to respond
    });
    return response.data;
  },

  // Aggregated catalog endpoint (available instance types across providers)
  getAggregatedCatalog: async () => {
    const response = await api.get('/api/instances/aggregated-catalog', {
      timeout: 90000,
    });
    return response.data;
  },

  migrateInstance: async ({ sourceProvider, sourceInstanceId, targetProvider, targetPayload }, lambdaApiKey = null) => {
    const response = await api.post(
      '/api/instances/migrate',
      {
        source_provider: sourceProvider,
        source_instance_id: sourceInstanceId,
        target_provider: targetProvider,
        target_payload: targetPayload,
      },
      {
        headers: lambdaApiKey ? { 'X-Lambda-API-Key': lambdaApiKey } : {},
        timeout: 180000,
      }
    );
    return response.data;
  },

  getInstanceStatus: async (instanceName = 'default') => {
    const response = await api.get(`/api/status/${instanceName}`);
    return response.data;
  },

  testInstanceConnection: async (instanceName = 'default') => {
    const response = await api.get(`/api/test-connection/${instanceName}`);
    return response.data;
  },

  getInstanceLogs: async (instanceName = 'default', logType = 'benchmark', full = false, lines = 100) => {
    const params = new URLSearchParams();
    params.append('full', full);
    params.append('lines', lines);
    const response = await api.get(`/api/logs/${instanceName}/${logType}?${params.toString()}`);
    return response.data;
  },

  listBenchmarkFiles: async (instanceName = 'default', directory = '/home/ubuntu/models') => {
    const params = new URLSearchParams();
    params.append('directory', directory);
    const response = await api.get(`/api/files/${instanceName}?${params.toString()}`);
    return response.data;
  },

  downloadBenchmarkFile: async (instanceName = 'default', filename, directory = '/home/ubuntu/models') => {
    const params = new URLSearchParams();
    params.append('directory', directory);
    const response = await api.get(`/api/files/${instanceName}/${filename}?${params.toString()}`);
    return response.data;
  },

  runBenchmark: async (instanceName = 'default', config) => {
    const response = await api.post(`/api/run-benchmark/${instanceName}`, config);
    return response.data;
  },

  // New benchmark endpoint
  runBenchmarkV2: async (params) => {
    const response = await api.post('/run-benchmark', params);
    return response.data;
  },

  // vLLM benchmark endpoint
  runVLLMBenchmark: async (params) => {
    const response = await api.post('/api/run-vllm-benchmark', params);
    return response.data;
  },

  // Set GPU clock via SSH
  setGpuClock: async (params) => {
    const response = await api.post('/api/set-gpu-clock', params);
    return response.data;
  },

  // OpenTofu instance management
  createTofuInstance: async (params) => {
    const response = await api.post('/api/tofu/instance/create', params);
    return response.data;
  },

  destroyTofuInstance: async (workspaceId, credentials) => {
    const response = await api.post(`/api/tofu/instance/destroy/${workspaceId}`, credentials);
    return response.data;
  },

  listTofuInstances: async () => {
    const response = await api.get('/api/tofu/instance/list');
    return response.data;
  },

  // Instance setup (run h100_fp8.sh script)
  setupInstance: async (params) => {
    // First, save PEM file if pem_base64 is provided
    if (params.pem_base64) {
      try {
        await api.post('/api/setup-instance/save-pem', {
          ip: params.ip,
          ssh_user: params.ssh_user,
          pem_base64: params.pem_base64
        });
        console.log('PEM file saved to backend');
      } catch (e) {
        console.warn('Failed to save PEM file (will try to use directly):', e);
      }
    }
    const response = await api.post('/api/setup-instance', params);
    return response.data;
  },

  // Save PEM file to backend
  savePemFile: async (ip, sshUser, pemBase64) => {
    console.log('📤 API: Saving PEM file to backend', {
      ip,
      sshUser,
      pemBase64Length: pemBase64?.length,
      pemBase64Preview: pemBase64?.substring(0, 50) + '...'
    });
    const response = await api.post('/api/setup-instance/save-pem', {
      ip,
      ssh_user: sshUser,
      pem_base64: pemBase64
    });
    console.log('✅ API: Save PEM response:', response.data);
    return response.data;
  },


  checkSetupComplete: async (ip, sshUser, pemPath, pemBase64) => {
    const params = new URLSearchParams();
    params.append('ip', ip);
    params.append('ssh_user', sshUser);
    if (pemPath) params.append('pem_path', pemPath);
    if (pemBase64) {
      params.append('pem_base64', pemBase64);
      console.log('Sending pem_base64 to backend, length:', pemBase64.length);
    } else {
      console.warn('No pem_base64 provided, only pem_path:', pemPath);
    }
    const response = await api.get(`/api/setup-instance/check?${params.toString()}`);
    return response.data;
  },

  getSetupStatus: async (ip, sshUser, pemPath, pid, pemBase64) => {
    const params = new URLSearchParams();
    params.append('ip', ip);
    params.append('ssh_user', sshUser);
    if (pemPath) params.append('pem_path', pemPath);
    if (pemBase64) params.append('pem_base64', pemBase64);
    if (pid) params.append('pid', pid);
    const response = await api.get(`/api/setup-instance/status?${params.toString()}`);
    return response.data;
  },

  // Get all available models
  getAvailableModels: async () => {
    const response = await api.get('/api/models');
    return response.data;
  },

  // Workflow endpoints (step-by-step)
  workflowSetupInstance: async (params) => {
    const response = await api.post('/api/workflow/setup-instance', params);
    return response.data;
  },

  workflowCheckInstance: async (params) => {
    const response = await api.post('/api/workflow/check-instance', params);
    return response.data;
  },

  workflowDeployVLLM: async (params) => {
    const response = await api.post('/api/workflow/deploy-vllm', params);
    return response.data;
  },

  workflowRunBenchmark: async (params) => {
    const response = await api.post('/api/workflow/run-benchmark', params);
    return response.data;
  },

  getWorkflowLogs: async (workflowId, phase = null) => {
    const params = phase ? `?phase=${phase}` : '';
    const response = await api.get(`/api/workflow/logs/${workflowId}${params}`);
    return response.data;
  },

  // Model architecture data
  getModelData: async (modelId) => {
    const response = await api.get(`/api/models/${modelId}`);
    return response.data;
  },

  // Prefill DAG data
  getPrefillLayerData: async (modelName, layerIndex) => {
    const response = await api.get(`/api/prefill_dag/${modelName}/${layerIndex}`);
    return response.data;
  },

  // AI Telemetry Insights
  getAITelemetryInsights: async (payload) => {
    const response = await api.post('/api/ai-insights', payload);
    return response.data;
  },

  // SM-Level Profiling
  triggerSMProfiling: async (payload) => {
    const response = await api.post('/api/sm-profiling/trigger', payload);
    return response.data;
  },

  getSMProfilingStatus: async (sessionId) => {
    const response = await api.get(`/api/sm-profiling/sessions/${sessionId}/status`);
    return response.data;
  },

  getSMMetrics: async (sessionId, metricName = null) => {
    const params = metricName ? { metric_name: metricName } : {};
    const response = await api.get(`/api/sm-profiling/sessions/${sessionId}/results`, { params });
    return response.data;
  },

  // Instance Orchestration
  startInstanceOrchestration: async (apiKey, request) => {
    const response = await api.post('/api/telemetry/instances/orchestrate', request, {
      headers: {
        'X-Lambda-API-Key': apiKey
      }
    });
    return response.data;
  },

  getOrchestrationStatus: async (orchestrationId) => {
    const response = await api.get(`/api/telemetry/instances/orchestrate/${orchestrationId}/status`);
    return response.data;
  },
  getOrchestrationByInstance: async (instanceId) => {
    const response = await api.get(`/api/telemetry/instances/orchestrate/by-instance/${instanceId}`);
    return response.data;
  },

  deployModel: async (orchestrationId, request) => {
    const response = await api.post(`/api/telemetry/instances/orchestrate/${orchestrationId}/deploy-model`, request);
    return response.data;
  },

  // Deployment Queue
  listDeploymentJobs: async (instanceId = null, status = null, deploymentType = null, limit = 100) => {
    const params = new URLSearchParams();
    if (instanceId) params.append('instance_id', instanceId);
    if (status) params.append('status', status);
    if (deploymentType) params.append('deployment_type', deploymentType);
    params.append('limit', limit);
    const response = await api.get(`/api/instances/jobs?${params.toString()}`);
    return response.data;
  },

  getDeploymentJob: async (jobId) => {
    const response = await api.get(`/api/instances/jobs/${jobId}`);
    return response.data;
  },

  runProfiling: async (instanceId, runId, mode = 'kernel', numRequests = 20, concurrency = 4) => {
    const params = new URLSearchParams();
    params.append('run_id', runId);
    params.append('mode', mode);
    params.append('num_requests', numRequests);
    params.append('concurrency', concurrency);
    const response = await api.post(`/api/instances/${instanceId}/run-profiling?${params.toString()}`);
    return response.data;
  },

  retryDeploymentJob: async (jobId) => {
    const response = await api.post(`/api/instances/jobs/${jobId}/retry`);
    return response.data;
  },

  cancelDeploymentJob: async (jobId) => {
    const response = await api.post(`/api/instances/jobs/${jobId}/cancel`);
    return response.data;
  },

  // Provisioning (Agent-based)
  createProvisioningManifest: async (deploymentJobId) => {
    const response = await api.post(`/api/telemetry/provision/manifests/${deploymentJobId}`);
    return response.data;
  },

  getProvisioningManifest: async (manifestId, token) => {
    const response = await api.get(`/api/telemetry/provision/manifests/${manifestId}?token=${token}`);
    return response.data;
  },

  sendAgentHeartbeat: async (heartbeatPayload) => {
    const response = await api.post(`/api/telemetry/provision/callbacks`, heartbeatPayload);
    return response.data;
  },

  getAgentHeartbeats: async (manifestId, limit = 50) => {
    const response = await api.get(`/api/telemetry/provision/callbacks/${manifestId}/heartbeats?limit=${limit}`);
    return response.data;
  },

  getAgentStatus: async (instanceId) => {
    try {
      const response = await api.get(`/api/telemetry/provision/instances/${instanceId}/status`);
      return response.data;
    } catch (error) {
      if (error?.response?.status === 404) {
        // Backward-compatible fallback for older backend route shape.
        try {
          const legacy = await api.get(`/api/telemetry/provision/callbacks/${instanceId}/status`);
          return legacy.data;
        } catch (legacyError) {
          if (legacyError?.response?.status === 404) {
            return null;
          }
          throw legacyError;
        }
      }
      if (error?.response?.status === 404) {
        return null;
      }
      throw error;
    }
  },

  // API Key Management
  createAPIKey: async (name, description) => {
    const response = await api.post(`/api/telemetry/provision/api-keys`, {
      name,
      description,
    });
    return response.data;
  },

  listAPIKeys: async (includeRevoked = false) => {
    const response = await api.get(`/api/telemetry/provision/api-keys?include_revoked=${includeRevoked}`);
    return response.data;
  },

  revokeAPIKey: async (keyId) => {
    const response = await api.post(`/api/telemetry/provision/api-keys/${keyId}/revoke`);
    return response.data;
  },

  getAgentStatusByInstance: async (instanceId) => {
    const response = await api.get(`/api/telemetry/provision/instances/${instanceId}/status`);
    return response.data;
  },

  stopAgent: async (instanceId, runId) => {
    const response = await api.post(`/api/telemetry/provision/instances/${instanceId}/stop?run_id=${runId}`);
    return response.data;
  },
  // Proxy inference requests to avoid Mixed Content errors
  proxyInference: async (ipAddress, requestBody) => {
    const response = await api.post('/api/telemetry/instances/orchestrate/proxy-inference', {
      ip_address: ipAddress,
      ...requestBody
    });
    return response.data;
  },

  // Authentication
  login: async (email, password) => {
    const response = await api.post('/api/auth/login', {
      email,
      password,
    });
    return response.data;
  },

  register: async (email, password) => {
    const response = await api.post('/api/auth/register', {
      email,
      password,
    });
    return response.data;
  },

  getCurrentUser: async (token) => {
    const response = await api.get('/api/auth/me', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    return response.data;
  },

  // Credentials Management
  listCredentials: async (provider = null, credentialType = null) => {
    const params = new URLSearchParams();
    if (provider) params.append('provider', provider);
    if (credentialType) params.append('credential_type', credentialType);
    const response = await api.get(`/api/credentials?${params.toString()}`);
    return response.data;
  },

  listCredentialsWithSecrets: async (provider = null, credentialType = null) => {
    const params = new URLSearchParams();
    if (provider) params.append('provider', provider);
    if (credentialType) params.append('credential_type', credentialType);
    const response = await api.get(`/api/credentials/with-secret?${params.toString()}`);
    return response.data;
  },

  getCredential: async (credentialId) => {
    const response = await api.get(`/api/credentials/${credentialId}`);
    return response.data;
  },

  saveCredential: async (provider, name, credentialType, secret, description = null, metadata = null) => {
    const response = await api.post('/api/credentials', {
      provider,
      name,
      credential_type: credentialType,
      secret,
      description,
      metadata,
    });
    return response.data;
  },

  updateCredential: async (credentialId, name = null, description = null, metadata = null, secret = null) => {
    const response = await api.patch(`/api/credentials/${credentialId}`, {
      name,
      description,
      metadata,
      secret,
    });
    return response.data;
  },

  deleteCredential: async (credentialId) => {
    await api.delete(`/api/credentials/${credentialId}`);
  },
};

export default apiService;
