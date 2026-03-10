import React from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  Chip,
  Alert,
  Divider,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper
} from '@mui/material';
import {
  Warning,
  Speed,
  Memory,
  NetworkCheck,
  Build,
  Info
} from '@mui/icons-material';

const BottleneckAnalysis = ({ bottleneckData, level, hardwareName }) => {
  console.log('BottleneckAnalysis received:', { bottleneckData, level, hardwareName });
  
  if (!bottleneckData) {
    console.log('No bottleneck data provided');
    return (
      <Card sx={{ mb: 2, maxWidth: 400 }}>
        <CardContent>
          <Typography variant="body2" color="text.secondary">
            No bottleneck analysis data available for this hardware component.
          </Typography>
        </CardContent>
      </Card>
    );
  }

  const getBottleneckIcon = (type) => {
    switch (type?.toLowerCase()) {
      case 'network':
        return <NetworkCheck color="warning" />;
      case 'memory':
        return <Memory color="error" />;
      case 'compute':
        return <Speed color="info" />;
      case 'i/o':
        return <Build color="secondary" />;
      case 'compute_precision':
        return <Build color="secondary" />;
      default:
        return <Warning color="warning" />;
    }
  };

  const getBottleneckColor = (type) => {
    switch (type?.toLowerCase()) {
      case 'network':
        return 'warning';
      case 'memory':
        return 'error';
      case 'compute':
        return 'info';
      case 'i/o':
        return 'secondary';
      case 'compute_precision':
        return 'secondary';
      default:
        return 'warning';
    }
  };

  const getLevelDescription = (level) => {
    switch (level) {
      case 0:
        return 'Cluster Level';
      case 1:
        return 'Rack Level';
      case 2:
        return 'Node Level';
      case 3:
        return 'Device Level';
      case 4:
        return 'SM Level';
      case 5:
        return 'Tensor Core Level';
      default:
        return 'Hardware Level';
    }
  };

  return (
    <Card sx={{ mb: 2, maxWidth: 400 }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
          <Warning color="warning" sx={{ mr: 1 }} />
          <Typography variant="h6" component="h3">
            Bottleneck Analysis
          </Typography>
        </Box>
        
        <Box sx={{ mb: 2 }}>
          <Chip
            label={getLevelDescription(level)}
            size="small"
            color="primary"
            variant="outlined"
            sx={{ mb: 1 }}
          />
          {hardwareName && (
            <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
              {hardwareName}
            </Typography>
          )}
        </Box>

        <Divider sx={{ mb: 2 }} />

        {/* Bottleneck Type */}
        <Box sx={{ mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
            {getBottleneckIcon(bottleneckData.bottleneck_type)}
            <Typography variant="subtitle2" sx={{ ml: 1, fontWeight: 'bold' }}>
              Bottleneck Type
            </Typography>
          </Box>
          <Chip
            label={bottleneckData.bottleneck_type || 'Unknown'}
            color={getBottleneckColor(bottleneckData.bottleneck_type)}
            size="small"
          />
        </Box>

        {/* Bottleneck Description */}
        <Box sx={{ mb: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
            Bottleneck
          </Typography>
          <Alert severity="warning" sx={{ mb: 1 }}>
            <Typography variant="body2">
              {bottleneckData.bottleneck || 'No bottleneck information available'}
            </Typography>
          </Alert>
        </Box>

        {/* Description */}
        {bottleneckData.description && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
              Description
            </Typography>
            <Paper sx={{ p: 2, backgroundColor: 'grey.50' }}>
              <Typography variant="body2" color="text.secondary">
                {bottleneckData.description}
              </Typography>
            </Paper>
          </Box>
        )}

        {/* Workload Characteristic */}
        {bottleneckData.workload_characteristic && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
              Workload Characteristic
            </Typography>
            <Paper sx={{ p: 2, backgroundColor: 'info.light', color: 'info.contrastText' }}>
              <Typography variant="body2">
                {bottleneckData.workload_characteristic}
              </Typography>
            </Paper>
          </Box>
        )}

        {/* Sources */}
        {bottleneckData.sources && bottleneckData.sources.length > 0 && (
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
              Sources
            </Typography>
            <List dense>
              {bottleneckData.sources.map((source, index) => (
                <ListItem key={index} sx={{ py: 0.5 }}>
                  <ListItemIcon>
                    <Info color="action" fontSize="small" />
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Typography variant="caption" color="text.secondary">
                        {source}
                      </Typography>
                    }
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}
      </CardContent>
    </Card>
  );
};

export default BottleneckAnalysis;
