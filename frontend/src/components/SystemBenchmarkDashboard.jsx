import React, { useState, useEffect } from 'react';
import {
  Box, Card, CardContent, Typography, Grid, FormControl, InputLabel, Select, MenuItem,
  Chip, LinearProgress, Alert, Paper, Divider, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, CircularProgress, Accordion, AccordionSummary, AccordionDetails,
  List, ListItem, ListItemText, ListItemIcon, IconButton, Tooltip, Tabs, Tab,
  Badge, Stack, Avatar, Button, Switch, FormControlLabel
} from '@mui/material';
import {
  Speed, Memory, AttachMoney, TrendingUp, Hardware, ExpandMore, 
  ShowChart, Assessment, Storage, Power, Timeline, Info, TableChart,
  Analytics, Dashboard as DashboardIcon, DataObject, Compare, Radar
} from '@mui/icons-material';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, 
  ResponsiveContainer, BarChart, Bar, AreaChart, Area, ScatterChart, Scatter,
  PieChart, Pie, Cell, Legend, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis
} from 'recharts';
import apiService from '../services/api';

const SystemBenchmarkDashboard = () => {
  const [availableSystems, setAvailableSystems] = useState([]);
  const [selectedSystem, setSelectedSystem] = useState('');
  const [systemSummary, setSystemSummary] = useState(null);
  const [systemBenchmarks, setSystemBenchmarks] = useState([]);
  const [selectedBenchmark, setSelectedBenchmark] = useState('');
  const [benchmarkData, setBenchmarkData] = useState(null);
  const [metricsData, setMetricsData] = useState(null);
  const [summaryData, setSummaryData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState(0);
  const [comparisonMode, setComparisonMode] = useState(false);
  const [selectedSystemsForComparison, setSelectedSystemsForComparison] = useState([]);
  const [comparisonData, setComparisonData] = useState(null);

  // Load available systems on component mount
  useEffect(() => {
    loadAvailableSystems();
  }, []);

  // Load system data when system changes
  useEffect(() => {
    if (selectedSystem) {
      loadSystemData();
    }
  }, [selectedSystem]);

  // Load benchmark data when benchmark changes
  useEffect(() => {
    if (selectedSystem && selectedBenchmark) {
      loadBenchmarkData();
    }
  }, [selectedSystem, selectedBenchmark]);

  const loadAvailableSystems = async () => {
    try {
      setLoading(true);
      const response = await apiService.getAvailableSystems();
      setAvailableSystems(response.systems);
      if (response.systems.length > 0) {
        setSelectedSystem(response.systems[0].system_name);
      }
    } catch (error) {
      console.error('Error loading systems:', error);
      setError('Failed to load available systems');
    } finally {
      setLoading(false);
    }
  };

  const loadSystemData = async () => {
    try {
      setLoading(true);
      const [summaryResponse, benchmarksResponse] = await Promise.all([
        apiService.getSystemSummary(selectedSystem),
        apiService.getSystemBenchmarks(selectedSystem)
      ]);
      setSystemSummary(summaryResponse);
      setSystemBenchmarks(benchmarksResponse.benchmarks);
      if (benchmarksResponse.benchmarks.length > 0) {
        setSelectedBenchmark(benchmarksResponse.benchmarks[0].filename);
      }
    } catch (error) {
      console.error('Error loading system data:', error);
      setError('Failed to load system data');
    } finally {
      setLoading(false);
    }
  };

  const loadBenchmarkData = async () => {
    try {
      setLoading(true);
      const [dataResponse, summaryResponse, metricsResponse] = await Promise.all([
        apiService.getBenchmarkData(selectedSystem, selectedBenchmark),
        apiService.getBenchmarkSummary(selectedSystem, selectedBenchmark),
        apiService.getBenchmarkMetrics(selectedSystem, selectedBenchmark)
      ]);
      setBenchmarkData(dataResponse);
      setSummaryData(summaryResponse);
      setMetricsData(metricsResponse);
    } catch (error) {
      console.error('Error loading benchmark data:', error);
      setError('Failed to load benchmark data');
    } finally {
      setLoading(false);
    }
  };

  const loadComparisonData = async () => {
    if (selectedSystemsForComparison.length < 2) return;
    
    try {
      setLoading(true);
      const response = await apiService.compareSystems(selectedSystemsForComparison);
      setComparisonData(response);
    } catch (error) {
      console.error('Error loading comparison data:', error);
      setError('Failed to load comparison data');
    } finally {
      setLoading(false);
    }
  };

  const formatValue = (value, type = 'number') => {
    if (value === null || value === undefined) return 'N/A';
    
    switch (type) {
      case 'percentage':
        return `${value.toFixed(1)}%`;
      case 'currency':
        return `$${value.toFixed(4)}`;
      case 'bytes':
        return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
      case 'bandwidth':
        return `${value.toFixed(2)} GB/s`;
      case 'time':
        return `${value.toFixed(2)} ms`;
      case 'temperature':
        return `${value.toFixed(1)}°C`;
      case 'throughput':
        return `${value.toFixed(1)} t/s`;
      case 'power':
        return `${value.toFixed(0)} W`;
      case 'efficiency':
        return `${value.toFixed(4)} t/s/W`;
      default:
        return typeof value === 'number' ? value.toFixed(2) : value.toString();
    }
  };

  const renderMetricCard = (title, value, unit, icon, color = '#818cf8', subtitle = '') => (
    <Card sx={{ height: '100%', background: 'linear-gradient(135deg, #1a1a18 0%, #3d3d3a 100%)', borderRadius: '8px', '&:hover': { boxShadow: 3, transition: 'box-shadow 0.2s ease' } }}>
      <CardContent sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
          {icon}
          <Typography variant="h6" sx={{ ml: 1.5, fontWeight: 600 }}>
            {title}
          </Typography>
        </Box>
        <Typography variant="h4" sx={{ color, fontWeight: 700, mb: 0.5 }}>
          {value} {unit}
        </Typography>
        {subtitle && (
          <Typography variant="body2" sx={{ color: 'text.secondary', mt: 1.5, lineHeight: 1.6 }}>
            {subtitle}
          </Typography>
        )}
      </CardContent>
    </Card>
  );

  const renderSystemSpecs = (systemSummary) => {
    if (!systemSummary || !systemSummary.system_specs) return null;

    return (
      <Card sx={{ borderRadius: '8px' }}>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 3, fontWeight: 600, display: 'flex', alignItems: 'center' }}>
            <Hardware sx={{ mr: 1.5 }} />
            System Specifications
          </Typography>
          <Grid container spacing={3}>
            {Object.entries(systemSummary.system_specs).map(([key, value]) => (
              <Grid item xs={12} sm={6} md={4} key={key}>
                <Box sx={{ p: 2, backgroundColor: '#2d2d2a', borderRadius: '8px', border: '1px solid #3d3d3a' }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600, color: 'text.secondary', mb: 0.5 }}>
                    {key.replace(/_/g, ' ').toUpperCase()}
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 700, color: '#818cf8' }}>
                    {value}
                  </Typography>
                </Box>
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>
    );
  };

  const renderDetailedBenchmarkResults = (benchmarkData) => {
    if (!benchmarkData || !benchmarkData.results || benchmarkData.results.length === 0) return null;

    // Get all possible fields from all results
    const allFields = new Set();
    benchmarkData.results.forEach(result => {
      Object.keys(result).forEach(key => allFields.add(key));
    });

    // Filter out fields that are all null
    const nonNullFields = Array.from(allFields).filter(field => {
      return benchmarkData.results.some(result => result[field] !== null && result[field] !== undefined);
    });

    if (nonNullFields.length === 0) return null;

    const getFieldLabel = (field) => {
      const labelMap = {
        'timestamp': 'Timestamp',
        'engine': 'Engine',
        'model_name': 'Model Name',
        'batch_size': 'Batch Size',
        'input_length': 'Input Length',
        'output_length': 'Output Length',
        'total_tokens_generated': 'Total Tokens',
        'total_requests': 'Total Requests',
        'duration_seconds': 'Duration (s)',
        'throughput_tokens_per_second': 'Throughput (t/s)',
        'throughput_requests_per_second': 'Requests/s',
        'latency_p50_ms': 'Latency P50 (ms)',
        'latency_p95_ms': 'Latency P95 (ms)',
        'ttft_p50_ms': 'TTFT P50 (ms)',
        'ttft_p95_ms': 'TTFT P95 (ms)',
        'tbt_p50_ms': 'TBT P50 (ms)',
        'tbt_p95_ms': 'TBT P95 (ms)',
        'prefill_latency_ms': 'Prefill Latency (ms)',
        'decode_latency_ms': 'Decode Latency (ms)',
        'decode_throughput_tokens_per_second': 'Decode Throughput (t/s)',
        'gpu_utilization_percent': 'GPU Utilization %',
        'sm_active_percent': 'SM Active %',
        'hbm_bandwidth_utilization_percent': 'HBM Utilization %',
        'hbm_bandwidth_raw_gbps': 'HBM Raw (GB/s)',
        'nvlink_bandwidth_utilization_percent': 'NVLink Utilization %',
        'nvlink_bandwidth_raw_gbps': 'NVLink Raw (GB/s)',
        'power_draw_watts': 'Power (W)',
        'performance_per_watt': 'Performance/Watt',
        'cost_usd': 'Cost (USD)',
        'performance_per_dollar': 'Performance/Dollar',
        'success': 'Success',
        'iteration_number': 'Iteration',
        'total_iterations': 'Total Iterations'
      };
      return labelMap[field] || field.replace(/_/g, ' ').toUpperCase();
    };

    const getFieldType = (field) => {
      if (field.includes('percent') || field.includes('utilization')) return 'percentage';
      if (field.includes('cost') || field.includes('dollar')) return 'currency';
      if (field.includes('gbps')) return 'bandwidth';
      if (field.includes('latency') || field.includes('ms')) return 'time';
      if (field.includes('throughput') && field.includes('tokens')) return 'throughput';
      if (field.includes('power') || field.includes('watts')) return 'power';
      if (field.includes('performance_per_watt')) return 'efficiency';
      if (field.includes('duration')) return 'time';
      if (field.includes('success')) return 'boolean';
      return 'number';
    };

    return (
      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2, fontWeight: 'bold', display: 'flex', alignItems: 'center' }}>
            <DataObject sx={{ mr: 1 }} />
            Detailed Benchmark Results
            <Chip 
              label={`${nonNullFields.length} fields`} 
              size="small" 
              color="primary" 
              sx={{ ml: 2 }} 
            />
          </Typography>
          <TableContainer sx={{ maxHeight: 600 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  {nonNullFields.map(field => (
                    <TableCell key={field} sx={{ fontWeight: 'bold', backgroundColor: '#2d2d2a' }}>
                      {getFieldLabel(field)}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {benchmarkData.results.map((result, index) => (
                  <TableRow key={index} hover>
                    {nonNullFields.map(field => (
                      <TableCell key={field}>
                        {formatValue(result[field], getFieldType(field))}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    );
  };

  const renderComparisonRadarChart = (comparisonData) => {
    if (!comparisonData || !comparisonData.systems) return null;

    const radarData = Object.entries(comparisonData.systems).map(([systemName, systemData]) => {
      const specs = systemData.system_specs || {};
      return {
        system: systemName,
        peak_tflops: parseFloat(specs.peak_tflops || 0),
        memory_bandwidth: parseFloat(specs.memory_bandwidth?.replace(' GB/s', '') || 0),
        tensor_cores: parseFloat(specs.tensor_cores || 0),
        cuda_cores: parseFloat(specs.cuda_cores || 0),
        base_clock: parseFloat(specs.base_clock?.replace(' MHz', '') || 0),
        boost_clock: parseFloat(specs.boost_clock?.replace(' MHz', '') || 0)
      };
    });

    return (
      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2, fontWeight: 'bold', display: 'flex', alignItems: 'center' }}>
            <Radar sx={{ mr: 1 }} />
            System Comparison - Performance Specs
          </Typography>
          <ResponsiveContainer width="100%" height={400}>
            <RadarChart data={radarData}>
              <PolarGrid />
              <PolarAngleAxis dataKey="system" />
              <PolarRadiusAxis />
              <RechartsTooltip />
              <Radar name="Peak TFLOPS" dataKey="peak_tflops" stroke="#8884d8" fill="#8884d8" fillOpacity={0.6} />
              <Radar name="Memory Bandwidth" dataKey="memory_bandwidth" stroke="#82ca9d" fill="#82ca9d" fillOpacity={0.6} />
              <Radar name="Tensor Cores" dataKey="tensor_cores" stroke="#ffc658" fill="#ffc658" fillOpacity={0.6} />
              <Radar name="CUDA Cores" dataKey="cuda_cores" stroke="#ff7300" fill="#ff7300" fillOpacity={0.6} />
            </RadarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    );
  };

  if (loading && !availableSystems.length) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ m: 2 }}>
        {error}
      </Alert>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom sx={{ fontWeight: 'bold', mb: 3, display: 'flex', alignItems: 'center' }}>
        <DashboardIcon sx={{ mr: 2 }} />
        System Benchmark Dashboard
        {selectedSystem && (
          <Chip 
            label={selectedSystem} 
            color="primary" 
            sx={{ ml: 2 }} 
            icon={<Hardware />}
          />
        )}
      </Typography>

      {/* System Selection */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={12} md={6}>
              <FormControl fullWidth>
                <InputLabel>Select System</InputLabel>
                <Select
                  value={selectedSystem}
                  label="Select System"
                  onChange={(e) => setSelectedSystem(e.target.value)}
                >
                  {availableSystems.map((system) => (
                    <MenuItem key={system.system_name} value={system.system_name}>
                      <Box sx={{ display: 'flex', alignItems: 'center', width: '100%' }}>
                        <Hardware sx={{ mr: 1 }} />
                        <Box>
                          <Typography variant="body1">{system.system_name}</Typography>
                          <Typography variant="caption" color="text.secondary">
                            {system.gpu_model} - {system.available_benchmarks} benchmarks
                          </Typography>
                        </Box>
                      </Box>
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={6}>
              <FormControlLabel
                control={
                  <Switch
                    checked={comparisonMode}
                    onChange={(e) => setComparisonMode(e.target.checked)}
                  />
                }
                label="Comparison Mode"
              />
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {loading && (
        <Box sx={{ mb: 3 }}>
          <LinearProgress />
          <Typography variant="body2" sx={{ mt: 1, textAlign: 'center' }}>
            Loading benchmark data...
          </Typography>
        </Box>
      )}

      {comparisonMode ? (
        <Box>
          <Typography variant="h5" sx={{ mb: 3, fontWeight: 'bold' }}>
            System Comparison
          </Typography>
          {renderComparisonRadarChart(comparisonData)}
        </Box>
      ) : benchmarkData && metricsData && summaryData && (
        <>
          {/* Tab Navigation */}
          <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
            <Tabs value={activeTab} onChange={(e, newValue) => setActiveTab(newValue)}>
              <Tab 
                icon={<Analytics />} 
                label="Overview" 
                iconPosition="start"
                sx={{ textTransform: 'none', fontWeight: 'bold' }}
              />
              <Tab 
                icon={<TableChart />} 
                label="Detailed Results" 
                iconPosition="start"
                sx={{ textTransform: 'none', fontWeight: 'bold' }}
              />
              <Tab 
                icon={<Hardware />} 
                label="System Specs" 
                iconPosition="start"
                sx={{ textTransform: 'none', fontWeight: 'bold' }}
              />
            </Tabs>
          </Box>

          {/* Overview Tab */}
          {activeTab === 0 && (
            <>
              {/* Summary Cards */}
              <Grid container spacing={3} sx={{ mb: 4 }}>
                <Grid item xs={12} md={3}>
                  {renderMetricCard(
                    "Total Iterations",
                    summaryData.total_results,
                    "iterations",
                    <Assessment />,
                    '#818cf8',
                    `Non-null: ${summaryData.non_null_results}`
                  )}
                </Grid>
                <Grid item xs={12} md={3}>
                  {renderMetricCard(
                    "Data Availability",
                    `${Object.values(metricsData.summary).filter(Boolean).length}/6`,
                    "metrics",
                    <ShowChart />,
                    '#388e3c',
                    "Available metrics"
                  )}
                </Grid>
                <Grid item xs={12} md={3}>
                  {renderMetricCard(
                    "GPU Count",
                    systemSummary?.gpu_count || 0,
                    "GPUs",
                    <Hardware />,
                    '#f57c00',
                    systemSummary?.gpu_model || 'Unknown'
                  )}
                </Grid>
                <Grid item xs={12} md={3}>
                  {renderMetricCard(
                    "Memory per GPU",
                    systemSummary?.gpu_memory_per_card || 'N/A',
                    "",
                    <Memory />,
                    '#7b1fa2',
                    "GPU Memory"
                  )}
                </Grid>
              </Grid>

              {/* Performance Charts */}
              <Grid container spacing={3} sx={{ mb: 4 }}>
                {metricsData.summary.has_throughput && (
                  <Grid item xs={12} md={6}>
                    <Card>
                      <CardContent>
                        <Typography variant="h6" sx={{ mb: 2, fontWeight: 'bold', display: 'flex', alignItems: 'center' }}>
                          <Speed sx={{ mr: 1 }} />
                          Throughput Analysis
                        </Typography>
                        <ResponsiveContainer width="100%" height={300}>
                          <LineChart data={metricsData.metrics.throughput}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="iteration" />
                            <YAxis />
                            <RechartsTooltip />
                            <Line type="monotone" dataKey="tokens_per_second" stroke="#8884d8" strokeWidth={2} />
                            <Line type="monotone" dataKey="requests_per_second" stroke="#82ca9d" strokeWidth={2} />
                          </LineChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  </Grid>
                )}

                {metricsData.summary.has_gpu_metrics && metricsData.metrics.gpu_utilization.length > 0 && (
                  <Grid item xs={12} md={6}>
                    <Card>
                      <CardContent>
                        <Typography variant="h6" sx={{ mb: 2, fontWeight: 'bold', display: 'flex', alignItems: 'center' }}>
                          <Hardware sx={{ mr: 1 }} />
                          GPU Utilization
                        </Typography>
                        <ResponsiveContainer width="100%" height={300}>
                          <AreaChart data={metricsData.metrics.gpu_utilization}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="iteration" />
                            <YAxis />
                            <RechartsTooltip />
                            <Area type="monotone" dataKey="utilization_percent" stackId="1" stroke="#8884d8" fill="#8884d8" />
                            <Area type="monotone" dataKey="sm_active_percent" stackId="2" stroke="#82ca9d" fill="#82ca9d" />
                          </AreaChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  </Grid>
                )}

                {metricsData.summary.has_power_data && (
                  <Grid item xs={12} md={6}>
                    <Card>
                      <CardContent>
                        <Typography variant="h6" sx={{ mb: 2, fontWeight: 'bold', display: 'flex', alignItems: 'center' }}>
                          <Power sx={{ mr: 1 }} />
                          Power Consumption
                        </Typography>
                        <ResponsiveContainer width="100%" height={300}>
                          <BarChart data={metricsData.metrics.power_consumption}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="iteration" />
                            <YAxis />
                            <RechartsTooltip />
                            <Bar dataKey="power_watts" fill="#8884d8" />
                          </BarChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  </Grid>
                )}

                {metricsData.summary.has_cost_data && (
                  <Grid item xs={12} md={6}>
                    <Card>
                      <CardContent>
                        <Typography variant="h6" sx={{ mb: 2, fontWeight: 'bold', display: 'flex', alignItems: 'center' }}>
                          <AttachMoney sx={{ mr: 1 }} />
                          Cost Analysis
                        </Typography>
                        <ResponsiveContainer width="100%" height={300}>
                          <BarChart data={metricsData.metrics.cost_analysis}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="iteration" />
                            <YAxis />
                            <RechartsTooltip />
                            <Bar dataKey="cost_usd" fill="#82ca9d" />
                          </BarChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  </Grid>
                )}
              </Grid>
            </>
          )}

          {/* Detailed Results Tab */}
          {activeTab === 1 && (
            <Box>
              {renderDetailedBenchmarkResults(benchmarkData)}
            </Box>
          )}

          {/* System Specs Tab */}
          {activeTab === 2 && (
            <Box>
              {renderSystemSpecs(systemSummary)}
            </Box>
          )}
        </>
      )}
    </Box>
  );
};

export default SystemBenchmarkDashboard;
