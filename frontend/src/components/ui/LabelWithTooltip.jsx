import React from 'react';
import { Stack, Tooltip, Typography, IconButton } from '@mui/material';
import { InfoOutlined as InfoIcon } from '@mui/icons-material';

export default function LabelWithTooltip({ label, tooltip }) {
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" component="span">
      <Typography variant="body2" fontWeight={600}>
        {label}
      </Typography>
      {tooltip ? (
        <Tooltip title={tooltip} arrow>
          <IconButton size="small" sx={{ p: 0.25 }}>
            <InfoIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      ) : null}
    </Stack>
  );
}
