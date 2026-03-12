import React from 'react';
import { Box, Typography } from '@mui/material';

/**
 * Design System Card — primary container for grouping content.
 *
 * Elevation: flat | sm | md | lg
 * Uses header / content / footer pattern.
 */

const elevationStyles = {
  flat: { boxShadow: 'none' },
  sm: { boxShadow: '0 1px 2px rgba(0,0,0,0.05)' },
  md: { boxShadow: '0 4px 6px rgba(0,0,0,0.1)' },
  lg: { boxShadow: '0 10px 15px rgba(0,0,0,0.1)' },
};

export default function DSCard({
  elevation = 'sm',
  children,
  sx = {},
  ...props
}) {
  return (
    <Box
      sx={{
        borderRadius: '8px',
        border: '1px solid #3d3d3a',
        backgroundColor: '#1a1a18',
        overflow: 'hidden',
        ...elevationStyles[elevation],
        ...sx,
      }}
      {...props}
    >
      {children}
    </Box>
  );
}

/**
 * Card Header — with title, optional subtitle, separated by bottom border.
 */
export function DSCardHeader({ title, subtitle, action, sx = {} }) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '24px',
        borderBottom: '1px solid #3d3d3a',
        ...sx,
      }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <Typography
          sx={{
            fontSize: '16px',
            fontWeight: 600,
            color: '#fafaf8',
            fontFamily: '"Geist", sans-serif',
          }}
        >
          {title}
        </Typography>
        {subtitle && (
          <Typography
            sx={{
              fontSize: '13px',
              fontWeight: 400,
              color: '#a8a8a0',
              fontFamily: '"Geist", sans-serif',
            }}
          >
            {subtitle}
          </Typography>
        )}
      </Box>
      {action}
    </Box>
  );
}

/**
 * Card Content — padding with vertical layout.
 */
export function DSCardContent({ children, sx = {} }) {
  return (
    <Box
      sx={{
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        ...sx,
      }}
    >
      {children}
    </Box>
  );
}

/**
 * Card Footer — with top border, right-aligned actions.
 */
export function DSCardFooter({ children, sx = {} }) {
  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'flex-end',
        gap: '12px',
        padding: '24px',
        borderTop: '1px solid #3d3d3a',
        ...sx,
      }}
    >
      {children}
    </Box>
  );
}

/**
 * Stat Card — displays a metric value with label and optional trend.
 */
export function DSStatCard({
  title,
  value,
  trend,
  trendColor,
  sx = {},
}) {
  return (
    <DSCard elevation="sm" sx={sx}>
      <DSCardContent>
        <Typography
          sx={{
            fontSize: '13px',
            fontWeight: 500,
            color: '#a8a8a0',
            fontFamily: '"Geist", sans-serif',
          }}
        >
          {title}
        </Typography>
        <Typography
          sx={{
            fontSize: '32px',
            fontWeight: 700,
            color: '#fafaf8',
            fontFamily: '"Geist", sans-serif',
            letterSpacing: '-0.5px',
          }}
        >
          {value}
        </Typography>
        {trend && (
          <Typography
            sx={{
              fontSize: '13px',
              fontWeight: 500,
              color: trendColor || '#34d399',
              fontFamily: '"Geist", sans-serif',
            }}
          >
            {trend}
          </Typography>
        )}
      </DSCardContent>
    </DSCard>
  );
}
