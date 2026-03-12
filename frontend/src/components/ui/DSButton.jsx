import React from 'react';
import { Button as MuiButton, IconButton as MuiIconButton } from '@mui/material';

/**
 * Design System Button — wraps MUI Button with Coached variants.
 *
 * Variants: primary | secondary | outline | ghost | destructive | success
 * Sizes:    sm (36px) | md (40px) | lg (44px)
 */

const variantMap = {
  primary: {
    variant: 'contained',
    sx: {
      backgroundColor: '#161616',
      color: '#fff',
      '&:hover': { backgroundColor: '#2a2a2a' },
    },
  },
  secondary: {
    variant: 'contained',
    sx: {
      backgroundColor: '#f2f2f2',
      color: '#1a1d2e',
      '&:hover': { backgroundColor: '#e5e5e5' },
    },
  },
  outline: {
    variant: 'outlined',
    sx: {
      borderColor: '#3d3d3a',
      color: '#a8a8a0',
      backgroundColor: 'transparent',
      '&:hover': {
        borderColor: '#818cf8',
        backgroundColor: 'rgba(129, 140, 248, 0.08)',
      },
    },
  },
  ghost: {
    variant: 'text',
    sx: {
      color: '#a8a8a0',
      '&:hover': { backgroundColor: 'rgba(255, 255, 255, 0.06)' },
    },
  },
  destructive: {
    variant: 'contained',
    sx: {
      backgroundColor: '#ef4444',
      color: '#fff',
      '&:hover': { backgroundColor: '#dc2626' },
    },
  },
  success: {
    variant: 'contained',
    sx: {
      backgroundColor: '#10b981',
      color: '#fff',
      '&:hover': { backgroundColor: '#059669' },
    },
  },
};

const sizeMap = {
  sm: { padding: '6px 12px', fontSize: '13px', borderRadius: '6px', minHeight: 36 },
  md: { padding: '10px 16px', fontSize: '14px', borderRadius: '8px', minHeight: 40 },
  lg: { padding: '12px 32px', fontSize: '14px', borderRadius: '8px', minHeight: 44 },
};

export default function DSButton({
  dsVariant = 'primary',
  dsSize = 'md',
  startIcon,
  endIcon,
  children,
  sx = {},
  ...props
}) {
  const v = variantMap[dsVariant] || variantMap.primary;
  const s = sizeMap[dsSize] || sizeMap.md;

  return (
    <MuiButton
      variant={v.variant}
      disableElevation
      startIcon={startIcon}
      endIcon={endIcon}
      sx={{
        textTransform: 'none',
        fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        fontWeight: 500,
        gap: '8px',
        ...s,
        ...v.sx,
        ...sx,
      }}
      {...props}
    >
      {children}
    </MuiButton>
  );
}

/**
 * Icon-only button — 40×40 with 8px radius.
 */
export function DSIconButton({ children, sx = {}, ...props }) {
  return (
    <MuiIconButton
      sx={{
        borderRadius: '8px',
        width: 40,
        height: 40,
        backgroundColor: '#161616',
        color: '#fff',
        '&:hover': { backgroundColor: '#2a2a2a' },
        ...sx,
      }}
      {...props}
    >
      {children}
    </MuiIconButton>
  );
}
