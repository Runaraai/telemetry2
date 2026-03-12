import React from 'react';
import { Box, Skeleton, Stack } from '@mui/material';

export function CardSkeleton({ rows = 3 }) {
  return (
    <Box sx={{ borderRadius: 2, border: '1px solid #3d3d3a', p: 2, bgcolor: '#1a1a18' }}>
      <Skeleton variant="text" width="50%" height={28} />
      <Stack spacing={1} sx={{ mt: 1 }}>
        {Array.from({ length: rows }).map((_, idx) => (
          <Skeleton key={idx} variant="rectangular" height={16} />
        ))}
      </Stack>
    </Box>
  );
}

export function ListSkeleton({ items = 3 }) {
  return (
    <Stack spacing={2}>
      {Array.from({ length: items }).map((_, idx) => (
        <CardSkeleton key={idx} rows={2} />
      ))}
    </Stack>
  );
}
