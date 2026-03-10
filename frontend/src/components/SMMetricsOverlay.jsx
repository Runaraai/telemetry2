import React, { useMemo } from 'react';
import {
  Box,
  Chip,
  Stack,
  Typography,
  Paper,
  Alert,
} from '@mui/material';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  Legend,
  CartesianGrid,
  ReferenceLine,
  Scatter,
  ScatterChart,
  ZAxis,
} from 'recharts';
import { Warning as WarningIcon } from '@mui/icons-material';

const COLOR_PALETTE = {
  gpuLine: '#1976d2',
  smMinBand: '#26a69a',
  smMaxBand: '#ef5350',
  outlier: '#ff7043',
};

const SMMetricsOverlay = ({ gpuData, smData, unit, domain }) => {
  // Calculate SM statistics and prepare chart data
  const chartData = useMemo(() => {
    if (!smData || !smData.metrics || !smData.statistics) {
      return null;
    }

    const metrics = smData.metrics;
    const statistics = smData.statistics;

    // Extract SM values
    const smValues = Object.entries(metrics)
      .filter(([key]) => key.startsWith('sm_'))
      .map(([key, value]) => ({
        sm_id: parseInt(key.replace('sm_', '')),
        value: value,
      }));

    if (smValues.length === 0) {
      return null;
    }

    // For each timestamp in gpuData, add SM min/max as constant horizontal bands
    const enhancedData = gpuData.map((point) => ({
      ...point,
      sm_min: statistics.min,
      sm_max: statistics.max,
      sm_avg: statistics.avg,
    }));

    return {
      chartData: enhancedData,
      statistics: statistics,
      smValues: smValues,
      outliers: statistics.outliers || [],
    };
  }, [gpuData, smData]);

  if (!chartData) {
    return (
      <Alert severity="info" sx={{ mt: 2 }}>
        No SM-level data available for visualization.
      </Alert>
    );
  }

  const { chartData: data, statistics, smValues, outliers } = chartData;

  // Create outlier markers (display at specific timestamps)
  const outlierMarkers = outliers.map((outlier, index) => ({
    timeLabel: data[Math.floor((index / outliers.length) * data.length)]?.timeLabel || '',
    value: outlier.value,
    sm_id: outlier.sm_id,
  }));

  return (
    <Box sx={{ mt: 2 }}>
      {/* Statistics Summary */}
      <Paper sx={{ p: 2, mb: 2, bgcolor: 'rgba(25, 118, 210, 0.05)' }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
          SM-Level Analysis ({smValues.length} Streaming Multiprocessors)
        </Typography>
        <Stack direction="row" flexWrap="wrap" sx={{ gap: 1, alignItems: 'center' }}>
          <Chip
            size="small"
            label={`Min: ${statistics.min.toFixed(1)}${unit || ''}`}
            sx={{
              bgcolor: COLOR_PALETTE.smMinBand,
              color: 'white',
              fontWeight: 600,
              height: 28,
              borderRadius: '999px',
              minWidth: 90,
              justifyContent: 'center',
            }}
          />
          <Chip
            size="small"
            label={`Max: ${statistics.max.toFixed(1)}${unit || ''}`}
            sx={{
              bgcolor: COLOR_PALETTE.smMaxBand,
              color: 'white',
              fontWeight: 600,
              height: 28,
              borderRadius: '999px',
              minWidth: 90,
              justifyContent: 'center',
            }}
          />
          <Chip
            size="small"
            label={`Avg: ${statistics.avg.toFixed(1)}${unit || ''}`}
            color="primary"
            variant="outlined"
            sx={{
              fontWeight: 600,
              height: 28,
              borderRadius: '999px',
              minWidth: 90,
              justifyContent: 'center',
            }}
          />
          {outliers.length > 0 && (
            <Chip
              size="small"
              icon={<WarningIcon />}
              label={`${outliers.length} Outlier${outliers.length > 1 ? 's' : ''}`}
              sx={{
                bgcolor: COLOR_PALETTE.outlier,
                color: 'white',
                fontWeight: 600,
                height: 28,
                borderRadius: '999px',
                minWidth: 110,
                justifyContent: 'center',
              }}
            />
          )}
        </Stack>

        {/* Outlier Details */}
        {outliers.length > 0 && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
              Outlier SMs (beyond 2σ from mean):
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ gap: 0.5 }}>
              {outliers.slice(0, 10).map((outlier) => (
                <Chip
                  key={outlier.sm_id}
                  size="small"
                  label={`SM${outlier.sm_id}: ${outlier.value.toFixed(1)}${unit || ''}`}
                  variant="outlined"
                  sx={{ fontSize: '0.7rem', height: 20 }}
                />
              ))}
              {outliers.length > 10 && (
                <Typography variant="caption" color="text.secondary">
                  ...and {outliers.length - 10} more
                </Typography>
              )}
            </Stack>
          </Box>
        )}
      </Paper>

      {/* Enhanced Chart with SM Bands */}
      <Box sx={{ width: '100%', height: 350 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 16, right: 24, bottom: 16, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
            <XAxis
              dataKey="timeLabel"
              minTickGap={30}
              tick={{ fontSize: 11 }}
              stroke="#666"
            />
            <YAxis
              domain={domain || ['auto', 'auto']}
              tick={{ fontSize: 11 }}
              stroke="#666"
              label={{ value: unit || '', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle' } }}
            />

            {/* SM Min/Max Bands (shaded area) */}
            <Area
              type="monotone"
              dataKey="sm_min"
              stroke={COLOR_PALETTE.smMinBand}
              fill={COLOR_PALETTE.smMinBand}
              fillOpacity={0.15}
              strokeWidth={1.5}
              strokeDasharray="5 5"
              name="SM Min"
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="sm_max"
              stroke={COLOR_PALETTE.smMaxBand}
              fill={COLOR_PALETTE.smMaxBand}
              fillOpacity={0.15}
              strokeWidth={1.5}
              strokeDasharray="5 5"
              name="SM Max"
              isAnimationActive={false}
            />

            {/* SM Average Line (dashed) */}
            <Line
              type="monotone"
              dataKey="sm_avg"
              stroke="#9c27b0"
              strokeWidth={2}
              strokeDasharray="3 3"
              dot={false}
              name="SM Avg"
              isAnimationActive={false}
            />

            {/* Original GPU-level line (solid, prominent) */}
            {Object.keys(data[0] || {}).filter(key => key.startsWith('gpu_') && key.includes('_')).map((key, index) => {
              const gpuId = key.match(/gpu_(\d+)_/)?.[1];
              return (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={`GPU ${gpuId} (Aggregate)`}
                  stroke={COLOR_PALETTE.gpuLine}
                  strokeWidth={3}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls
                />
              );
            })}

            <RechartsTooltip
              contentStyle={{
                backgroundColor: 'rgba(255, 255, 255, 0.97)',
                border: '1px solid #ccc',
                borderRadius: 4,
                fontSize: 12,
              }}
              formatter={(value, name) => [value?.toFixed(1) + (unit || ''), name]}
            />
            <Legend
              wrapperStyle={{ paddingTop: 8, fontSize: 11 }}
              iconType="line"
            />

            {/* Reference lines for statistics */}
            <ReferenceLine
              y={statistics.avg}
              stroke="#9c27b0"
              strokeDasharray="3 3"
              strokeWidth={1}
              label={{
                value: `SM Avg: ${statistics.avg.toFixed(1)}${unit || ''}`,
                position: 'right',
                fill: '#9c27b0',
                fontSize: 10,
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      </Box>

      {/* Distribution Histogram (optional, for future enhancement) */}
      <Box sx={{ mt: 2 }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          Per-SM Distribution: {smValues.length} SMs profiled
        </Typography>
        <Stack direction="row" spacing={0.5}>
          {/* Simple visual representation of distribution */}
          {[0, 20, 40, 60, 80, 100].map((bucket, index) => {
            const count = smValues.filter(
              (sm) => sm.value >= bucket && sm.value < (bucket + 20)
            ).length;
            const barHeight = Math.max((count / smValues.length) * 100, 2);

            return (
              <Box
                key={bucket}
                sx={{
                  flex: 1,
                  height: 40,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'flex-end',
                  alignItems: 'center',
                  bgcolor: 'rgba(0,0,0,0.03)',
                  borderRadius: 1,
                  position: 'relative',
                }}
              >
                <Box
                  sx={{
                    width: '100%',
                    height: `${barHeight}%`,
                    bgcolor: COLOR_PALETTE.gpuLine,
                    borderRadius: '4px 4px 0 0',
                    opacity: 0.7,
                  }}
                />
                <Typography
                  variant="caption"
                  sx={{
                    position: 'absolute',
                    bottom: -18,
                    fontSize: '0.65rem',
                    color: 'text.secondary',
                  }}
                >
                  {bucket}
                </Typography>
              </Box>
            );
          })}
        </Stack>
      </Box>
    </Box>
  );
};

export default SMMetricsOverlay;



