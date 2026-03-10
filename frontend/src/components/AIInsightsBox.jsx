import React, { useState, useCallback, useMemo } from 'react';
import {
  Box,
  Button,
  CircularProgress,
  Collapse,
  IconButton,
  Typography,
  Alert,
  Paper,
  Divider,
} from '@mui/material';
import {
  SmartToy as AIIcon,
  ExpandMore as ExpandMoreIcon,
  Refresh as RefreshIcon,
  Psychology as AnalyzeIcon,
} from '@mui/icons-material';
import ReactMarkdown from 'react-markdown';
import apiService from '../services/api';

const AIInsightsBox = ({ metricName, metricKey, unit, data, gpuIds }) => {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [insights, setInsights] = useState(null);
  const [error, setError] = useState('');
  const [cached, setCached] = useState(false);

  // Precompute quick stats so users get instant value even if AI fails.
  const quickStats = useMemo(() => {
    if (!data || data.length === 0 || !gpuIds || gpuIds.length === 0) return null;
    const gpuStats = {};
    const overallValues = [];

    const compute = (vals) => {
      if (!vals.length) return null;
      const sorted = [...vals].sort((a, b) => a - b);
      const avg = sorted.reduce((s, v) => s + v, 0) / sorted.length;
      const pick = (p) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];
      return {
        min: sorted[0],
        max: sorted[sorted.length - 1],
        avg,
        p50: pick(0.5),
        p95: pick(0.95),
        p99: pick(0.99),
      };
    };

    gpuIds.forEach((gpuId) => {
      const gpuKey = `gpu_${gpuId}_${metricKey}`;
      const vals = data
        .map((point) => point[gpuKey])
        .filter((v) => v !== null && v !== undefined && !isNaN(v))
        .map((v) => Number(v));
      const stats = compute(vals);
      if (stats) {
        gpuStats[gpuId] = stats;
        overallValues.push(...vals);
      }
    });

    const overall = compute(overallValues);
    return { overall, gpuStats };
  }, [data, gpuIds, metricKey]);

  const generateInsights = useCallback(async () => {
    if (!data || data.length === 0) {
      setError('No data available for analysis');
      return;
    }

    setLoading(true);
    setError('');
    
    try {
      // Calculate accurate statistics from FULL dataset
      const fullStatistics = {};
      const allValues = [];
      
      gpuIds.forEach(gpuId => {
        const gpuKey = `gpu_${gpuId}_${metricKey}`;
        const values = [];
        
        data.forEach(point => {
          const val = point[gpuKey];
          if (val !== null && val !== undefined && !isNaN(val)) {
            values.push(Number(val));
            allValues.push(Number(val));
          }
        });
        
        if (values.length > 0) {
          values.sort((a, b) => a - b);
          fullStatistics[`gpu_${gpuId}`] = {
            min: Math.min(...values),
            max: Math.max(...values),
            avg: values.reduce((sum, v) => sum + v, 0) / values.length,
            median: values[Math.floor(values.length / 2)],
            p95: values[Math.floor(values.length * 0.95)],
            p99: values[Math.floor(values.length * 0.99)],
            stddev: values.length > 1 ? Math.sqrt(values.reduce((sum, v) => sum + Math.pow(v - (values.reduce((s, x) => s + x, 0) / values.length), 2), 0) / values.length) : 0,
            count: values.length
          };
        }
      });
      
      // Calculate overall statistics from ALL values
      if (allValues.length > 0) {
        allValues.sort((a, b) => a - b);
        const avg = allValues.reduce((sum, v) => sum + v, 0) / allValues.length;
        fullStatistics.overall = {
          min: Math.min(...allValues),
          max: Math.max(...allValues),
          avg: avg,
          median: allValues[Math.floor(allValues.length / 2)],
          p95: allValues[Math.floor(allValues.length * 0.95)],
          p99: allValues[Math.floor(allValues.length * 0.99)],
          stddev: allValues.length > 1 ? Math.sqrt(allValues.reduce((sum, v) => sum + Math.pow(v - avg, 2), 0) / allValues.length) : 0,
          count: allValues.length
        };
      }
      
      // Sample data for trend analysis only (much smaller sample needed)
      let sampledData = data;
      if (data.length > 50) {
        const step = Math.floor(data.length / 50);
        sampledData = data.filter((_, idx) => idx % step === 0).slice(0, 50);
        // Always include first and last
        if (!sampledData.includes(data[0])) sampledData.unshift(data[0]);
        if (!sampledData.includes(data[data.length - 1])) sampledData.push(data[data.length - 1]);
      }
      
      const payload = {
        metric_name: metricName,
        metric_key: metricKey,
        unit: unit,
        data: sampledData,
        gpu_ids: gpuIds || [0],
        // Send pre-calculated statistics from FULL dataset
        precalculated_statistics: fullStatistics,
      };

      // Debug: Check what statistics we're sending
      console.log('AI Insights Payload:', {
        metric_name: metricName,
        metric_key: metricKey,
        full_data_count: data.length,
        sampled_data_count: sampledData.length,
        statistics: fullStatistics.overall,
        gpu_ids: gpuIds,
      });

      const response = await apiService.getAITelemetryInsights(payload);
      setInsights(response.insights);
      setCached(response.cached || false);
      setError('');
    } catch (err) {
      console.error('Failed to generate AI insights:', err);
      console.error('Error details:', {
        response: err.response,
        message: err.message,
        status: err.response?.status,
        data: err.response?.data
      });
      
      let errorMessage = 'Failed to generate insights. Please try again.';
      
      if (err.response?.data?.detail) {
        errorMessage = err.response.data.detail;
      } else if (err.response?.data?.message) {
        errorMessage = err.response.data.message;
      } else if (err.message) {
        errorMessage = err.message;
      } else if (err.response?.statusText) {
        errorMessage = `Error ${err.response.status}: ${err.response.statusText}`;
      }
      
      setError(errorMessage);
      setInsights(null);
    } finally {
      setLoading(false);
    }
  }, [metricName, metricKey, unit, data, gpuIds]);

  const handleToggle = () => {
    if (!expanded && !insights && !loading) {
      // Auto-generate when expanding for the first time
      setExpanded(true);
      generateInsights();
    } else {
      setExpanded(!expanded);
    }
  };

  const handleRefresh = () => {
    generateInsights();
  };

  return (
    <Box sx={{ mt: 2, borderTop: '1px solid', borderColor: 'divider', pt: 2 }}>
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          '&:hover': {
            backgroundColor: 'action.hover',
          },
          borderRadius: 1,
          p: 1,
          transition: 'background-color 0.2s',
        }}
        onClick={handleToggle}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <AIIcon color="action" fontSize="small" />
          <Typography variant="subtitle2" sx={{ fontWeight: 600, color: 'text.secondary' }}>
            AI Insights
          </Typography>
          {cached && (
            <Typography variant="caption" sx={{ color: 'text.disabled', ml: 1 }}>
              (cached)
            </Typography>
          )}
        </Box>
        <IconButton
          size="small"
          sx={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.3s',
          }}
        >
          <ExpandMoreIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Expandable Content */}
      <Collapse in={expanded} timeout="auto">
        <Box sx={{ pt: 2 }}>
          {/* Action Buttons */}
          {!loading && (
            <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
              {!insights && (
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<AnalyzeIcon />}
                  onClick={(e) => {
                    e.stopPropagation();
                    generateInsights();
                  }}
                  sx={{
                    textTransform: 'none',
                    borderRadius: 1,
                  }}
                >
                  Analyze with AI
                </Button>
              )}
              {insights && (
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<RefreshIcon />}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRefresh();
                  }}
                  sx={{
                    textTransform: 'none',
                    borderRadius: 1,
                  }}
                >
                  Refresh
                </Button>
              )}
            </Box>
          )}

          {/* Loading State */}
          {loading && (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 2,
                p: 3,
                backgroundColor: 'action.hover',
                borderRadius: 2,
              }}
            >
              <CircularProgress size={20} />
              <Typography variant="body2" color="text.secondary">
                Analyzing metrics with AI...
              </Typography>
            </Box>
          )}

          {/* Error State */}
          {error && !loading && (
            <Alert
              severity="error"
              sx={{ borderRadius: 2 }}
              action={
                <Button
                  size="small"
                  color="inherit"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRefresh();
                  }}
                >
                  Retry
                </Button>
              }
            >
              {error}
            </Alert>
          )}

          {/* Quick Stats */}
          {quickStats && quickStats.overall && !loading && (
            <Paper
              variant="outlined"
              sx={{
                p: 1.5,
                mb: 1.5,
                borderRadius: 2,
                backgroundColor: 'background.paper',
              }}
            >
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
                Quick Stats (overall)
              </Typography>
              <Typography variant="body2" color="text.secondary">
                min {quickStats.overall.min?.toFixed(1) ?? '—'} • avg {quickStats.overall.avg?.toFixed(1) ?? '—'} • p95 {quickStats.overall.p95?.toFixed(1) ?? '—'} • max {quickStats.overall.max?.toFixed(1) ?? '—'} {unit}
              </Typography>
              {quickStats.gpuStats && Object.keys(quickStats.gpuStats).length > 1 && (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 0.75 }}>
                  {Object.entries(quickStats.gpuStats).map(([gpuId, stats]) => (
                    <Paper
                      key={gpuId}
                      variant="outlined"
                      sx={{ px: 1, py: 0.5, borderRadius: 1, backgroundColor: 'action.hover', minWidth: 140 }}
                    >
                      <Typography variant="caption" sx={{ fontWeight: 700 }}>
                        GPU {gpuId}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        avg {stats.avg?.toFixed(1) ?? '—'}, p95 {stats.p95?.toFixed(1) ?? '—'}
                      </Typography>
                    </Paper>
                  ))}
                </Box>
              )}
            </Paper>
          )}

          {/* Insights Display */}
          {insights && !loading && (
            <Paper
              variant="outlined"
              sx={{
                p: 2,
                borderRadius: 2,
                backgroundColor: 'background.default',
              }}
            >
              <Box
                sx={{
                  '& h1': {
                    fontSize: '1.25rem',
                    fontWeight: 600,
                    mt: 2,
                    mb: 1,
                  },
                  '& h2': {
                    fontSize: '1.1rem',
                    fontWeight: 600,
                    mt: 2,
                    mb: 1,
                  },
                  '& h3': {
                    fontSize: '1rem',
                    fontWeight: 600,
                    mt: 1.5,
                    mb: 0.5,
                  },
                  '& p': {
                    fontSize: '0.875rem',
                    lineHeight: 1.6,
                    mb: 1,
                  },
                  '& ul, & ol': {
                    fontSize: '0.875rem',
                    pl: 2,
                    mb: 1,
                  },
                  '& li': {
                    mb: 0.5,
                  },
                  '& strong': {
                    fontWeight: 600,
                    color: 'text.primary',
                  },
                  '& code': {
                    backgroundColor: 'action.hover',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    fontSize: '0.85rem',
                    fontFamily: 'monospace',
                  },
                  '& pre': {
                    backgroundColor: 'action.hover',
                    padding: '12px',
                    borderRadius: '8px',
                    overflow: 'auto',
                    fontSize: '0.85rem',
                    fontFamily: 'monospace',
                  },
                }}
              >
                <ReactMarkdown>{insights}</ReactMarkdown>
              </Box>
            </Paper>
          )}

          {/* Empty State */}
          {!insights && !loading && !error && (
            <Box
              sx={{
                p: 3,
                textAlign: 'center',
                color: 'text.secondary',
                backgroundColor: 'action.hover',
                borderRadius: 2,
              }}
            >
              <AIIcon sx={{ fontSize: 40, mb: 1, opacity: 0.5 }} />
              <Typography variant="body2">
                Click "Analyze with AI" to get intelligent insights about this metric
              </Typography>
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  );
};

export default AIInsightsBox;
