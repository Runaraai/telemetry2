import React from 'react';
import { Box, Typography, IconButton } from '@mui/material';
import { Close } from '@mui/icons-material';

/**
 * Design System Tags & Pills.
 *
 * Status Pills: active | inactive | pending | info | neutral | paid | sent | draft
 * Icon Tags: with leading icon
 * Dismissible Tags: with close button (pill shape)
 * Meal Type Tags: compact neutral
 */

// ── Color presets ────────────────────────────────────────────────────────────
const statusPresets = {
  active: { bg: '#dcfce7', text: '#16a34a', border: '#bbf7d0' },
  inactive: { bg: '#fee2e2', text: '#dc2626', border: '#fecaca' },
  pending: { bg: '#fef3c7', text: '#d97706', border: '#fde68a' },
  paused: { bg: '#fef3c7', text: '#d97706', border: '#fde68a' },
  info: { bg: '#dbeafe', text: '#1d4ed8', border: '#bfdbfe' },
  neutral: { bg: '#f3f4f6', text: '#6b7280', border: '#e5e7eb' },
  paid: { bg: '#dcfce7', text: '#16a34a', border: '#bbf7d0' },
  sent: { bg: '#dbeafe', text: '#1d4ed8', border: '#bfdbfe' },
  draft: { bg: '#f3f4f6', text: '#6b7280', border: '#e5e7eb' },
  success: { bg: '#dcfce7', text: '#16a34a', border: '#bbf7d0' },
  error: { bg: '#fee2e2', text: '#dc2626', border: '#fecaca' },
  warning: { bg: '#fef3c7', text: '#d97706', border: '#fde68a' },
  purple: { bg: '#ede9fe', text: '#7c3aed', border: '#ddd6fe' },
  blue: { bg: '#dbeafe', text: '#1d4ed8', border: '#bfdbfe' },
  green: { bg: '#dcfce7', text: '#16a34a', border: '#bbf7d0' },
  yellow: { bg: '#fef3c7', text: '#d97706', border: '#fde68a' },
};

// Dark mode overrides
const darkStatusPresets = {
  active: { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' },
  inactive: { bg: 'rgba(239, 68, 68, 0.15)', text: '#f87171', border: 'rgba(239, 68, 68, 0.3)' },
  pending: { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' },
  paused: { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' },
  info: { bg: 'rgba(37, 99, 235, 0.15)', text: '#60a5fa', border: 'rgba(37, 99, 235, 0.3)' },
  neutral: { bg: 'rgba(255, 255, 255, 0.06)', text: '#a8a8a0', border: '#3d3d3a' },
  paid: { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' },
  sent: { bg: 'rgba(37, 99, 235, 0.15)', text: '#60a5fa', border: 'rgba(37, 99, 235, 0.3)' },
  draft: { bg: 'rgba(255, 255, 255, 0.06)', text: '#a8a8a0', border: '#3d3d3a' },
  success: { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' },
  error: { bg: 'rgba(239, 68, 68, 0.15)', text: '#f87171', border: 'rgba(239, 68, 68, 0.3)' },
  warning: { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' },
  purple: { bg: 'rgba(124, 58, 237, 0.15)', text: '#a78bfa', border: 'rgba(124, 58, 237, 0.3)' },
  blue: { bg: 'rgba(37, 99, 235, 0.15)', text: '#60a5fa', border: 'rgba(37, 99, 235, 0.3)' },
  green: { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' },
  yellow: { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' },
};

/**
 * Status Pill — compact colored badge.
 */
export function DSStatusPill({ status = 'neutral', children, darkMode = true, sx = {} }) {
  const presets = darkMode ? darkStatusPresets : statusPresets;
  const preset = presets[status] || presets.neutral;

  return (
    <Box
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        borderRadius: '5px',
        padding: '4px 12px',
        backgroundColor: preset.bg,
        border: `1px solid ${preset.border}`,
        ...sx,
      }}
    >
      <Typography
        sx={{
          fontSize: '11.5px',
          fontWeight: 600,
          color: preset.text,
          fontFamily: '"Geist", sans-serif',
          lineHeight: 1,
        }}
      >
        {children}
      </Typography>
    </Box>
  );
}

/**
 * Meal Type Tag — compact neutral style.
 */
export function DSMealTag({ children, darkMode = true, sx = {} }) {
  return (
    <Box
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        borderRadius: '5px',
        padding: '2px 8px',
        backgroundColor: darkMode ? 'rgba(255,255,255,0.06)' : '#f3f4f6',
        border: `1px solid ${darkMode ? '#3d3d3a' : '#e5e7eb'}`,
        ...sx,
      }}
    >
      <Typography
        sx={{
          fontSize: '11px',
          fontWeight: 500,
          color: darkMode ? '#a8a8a0' : '#6b7280',
          fontFamily: '"Geist", sans-serif',
          lineHeight: 1.2,
        }}
      >
        {children}
      </Typography>
    </Box>
  );
}

/**
 * Icon Tag — with leading icon and colored tint.
 */
export function DSIconTag({ icon, color = 'neutral', children, darkMode = true, sx = {} }) {
  const presets = darkMode ? darkStatusPresets : statusPresets;
  const preset = presets[color] || presets.neutral;

  return (
    <Box
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        borderRadius: '5px',
        padding: '4px 10px',
        backgroundColor: preset.bg,
        border: `1px solid ${preset.border}`,
        ...sx,
      }}
    >
      {icon &&
        React.cloneElement(icon, {
          sx: { fontSize: 12, color: preset.text, ...(icon.props.sx || {}) },
        })}
      <Typography
        sx={{
          fontSize: '11px',
          fontWeight: 500,
          color: preset.text,
          fontFamily: '"Geist", sans-serif',
          lineHeight: 1,
        }}
      >
        {children}
      </Typography>
    </Box>
  );
}

/**
 * Dismissible Tag — pill shape with close button.
 */
export function DSDismissibleTag({
  color = 'neutral',
  children,
  onDismiss,
  darkMode = true,
  sx = {},
}) {
  const presets = darkMode ? darkStatusPresets : statusPresets;
  const preset = presets[color] || presets.neutral;

  return (
    <Box
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        borderRadius: '999px',
        padding: '4px 8px',
        backgroundColor: preset.bg,
        border: `1px solid ${preset.border}`,
        ...sx,
      }}
    >
      <Typography
        sx={{
          fontSize: '11px',
          fontWeight: 500,
          color: preset.text,
          fontFamily: '"Geist", sans-serif',
          lineHeight: 1,
        }}
      >
        {children}
      </Typography>
      {onDismiss && (
        <Close
          onClick={onDismiss}
          sx={{
            fontSize: 10,
            color: preset.text,
            cursor: 'pointer',
            '&:hover': { opacity: 0.7 },
          }}
        />
      )}
    </Box>
  );
}
