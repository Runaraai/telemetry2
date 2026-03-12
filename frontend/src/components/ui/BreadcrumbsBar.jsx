import React from 'react';
import { Breadcrumbs, Link, Typography, Box } from '@mui/material';
import { useLocation, useNavigate } from 'react-router-dom';

const LABELS = {
  '/': 'Benchmarking',
  '/profiling': 'Run Workload',
  '/telemetry': 'Telemetry',
  '/instances': 'Manage Instances',
};

export default function BreadcrumbsBar() {
  const location = useLocation();
  const navigate = useNavigate();

  const parts = location.pathname.split('/').filter(Boolean);
  const paths = parts.map((_, idx) => `/${parts.slice(0, idx + 1).join('/')}`);
  const items = paths.length === 0 ? ['/'] : paths;

  return (
    <Box sx={{ px: 3, py: 2 }}>
      <Breadcrumbs aria-label="breadcrumb">
        {items.map((path, idx) => {
          const isLast = idx === items.length - 1;
          const label = LABELS[path] || path.replace('/', '') || 'Home';
          return isLast ? (
            <Typography key={path} color="text.primary" fontWeight={600}>
              {label}
            </Typography>
          ) : (
            <Link
              key={path}
              underline="hover"
              color="inherit"
              onClick={() => navigate(path)}
              sx={{ cursor: 'pointer' }}
            >
              {label}
            </Link>
          );
        })}
      </Breadcrumbs>
    </Box>
  );
}
