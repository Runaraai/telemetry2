import React from 'react';
import { Box, Typography } from '@mui/material';

/**
 * Design System Table — flexbox-based data table.
 *
 * Specs: 52px row height, 11px uppercase headers, 13.5px cell text,
 * 1px borders, 8px corner radius on wrapper.
 *
 * Compact variant: 44px row height, 36px header.
 */

export default function DSTable({ children, compact, sx = {} }) {
  return (
    <Box
      sx={{
        borderRadius: '8px',
        border: '1px solid #3d3d3a',
        backgroundColor: '#1a1a18',
        overflow: 'hidden',
        ...sx,
      }}
    >
      {children}
    </Box>
  );
}

/**
 * Table Header Row
 */
export function DSTableHead({ children, compact, sx = {} }) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        height: compact ? 36 : 40,
        padding: compact ? '0 12px' : '0 16px',
        backgroundColor: 'rgba(255,255,255,0.02)',
        borderBottom: '1px solid #3d3d3a',
        ...sx,
      }}
    >
      {children}
    </Box>
  );
}

/**
 * Table Header Cell
 */
export function DSTableHeaderCell({ children, width, align = 'left', sx = {} }) {
  return (
    <Typography
      sx={{
        fontSize: '11px',
        fontWeight: 600,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        color: '#a8a8a0',
        fontFamily: '"Geist", sans-serif',
        flex: width ? `0 0 ${width}` : 1,
        textAlign: align,
        ...sx,
      }}
    >
      {children}
    </Typography>
  );
}

/**
 * Table Row
 */
export function DSTableRow({ children, compact, onClick, sx = {} }) {
  return (
    <>
      <Box
        onClick={onClick}
        sx={{
          display: 'flex',
          alignItems: 'center',
          height: compact ? 44 : 52,
          padding: compact ? '0 12px' : '0 16px',
          transition: 'background-color 0.15s ease',
          cursor: onClick ? 'pointer' : 'default',
          '&:hover': {
            backgroundColor: 'rgba(129, 140, 248, 0.05)',
          },
          ...sx,
        }}
      >
        {children}
      </Box>
      <Box sx={{ height: '1px', backgroundColor: '#3d3d3a' }} />
    </>
  );
}

/**
 * Table Cell
 */
export function DSTableCell({
  children,
  width,
  align = 'left',
  emphasis,
  mono,
  muted,
  sx = {},
}) {
  return (
    <Typography
      component="div"
      sx={{
        fontSize: '13.5px',
        fontWeight: emphasis ? 600 : 400,
        color: muted ? '#a8a8a0' : '#fafaf8',
        fontFamily: mono
          ? '"DM Mono", monospace'
          : '"Geist", sans-serif',
        flex: width ? `0 0 ${width}` : 1,
        textAlign: align,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        ...sx,
      }}
    >
      {children}
    </Typography>
  );
}

/**
 * Table Pagination footer
 */
export function DSTablePagination({
  info,
  children,
  sx = {},
}) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: 48,
        padding: '0 16px',
        ...sx,
      }}
    >
      <Typography
        sx={{
          fontSize: '13px',
          fontWeight: 400,
          color: '#a8a8a0',
          fontFamily: '"Geist", sans-serif',
        }}
      >
        {info}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {children}
      </Box>
    </Box>
  );
}
