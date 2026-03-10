import React from 'react';
import { Stack, Typography, Button, Tooltip } from '@mui/material';
import { Refresh as RefreshIcon, AccessTime as TimeIcon } from '@mui/icons-material';

export default function RefreshControl({ lastUpdated, loading, onRefresh }) {
  return (
    <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <TimeIcon fontSize="small" color="action" />
        <Typography variant="body2" color="text.secondary">
          Last updated: {lastUpdated ? new Date(lastUpdated).toLocaleString() : '—'}
        </Typography>
      </Stack>
      <Tooltip title="Refresh data">
        <span>
          <Button
            size="small"
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={onRefresh}
            disabled={loading}
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </Button>
        </span>
      </Tooltip>
    </Stack>
  );
}
