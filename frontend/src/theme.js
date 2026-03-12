import { createTheme } from '@mui/material/styles';

// ─── Design System Tokens ────────────────────────────────────────────────────
// Based on the "Coached" Design System v1.0

// Color Palette
export const colors = {
  // Brand & Accent
  accentPrimary: { light: '#667eea', dark: '#818cf8' },
  accentHover: { light: '#5a67d8', dark: '#6366f1' },

  // Backgrounds
  bgPrimary: { light: '#f5f2ed', dark: '#1a1a18' },
  bgContent: { light: '#ebe8e2', dark: '#0f0f0e' },
  bgElevated: { light: '#ffffff', dark: '#2d2d2a' },
  surface: { light: '#ffffff', dark: '#1a1a18' },

  // Text
  textPrimary: { light: '#1a1d2e', dark: '#fafaf8' },
  textMuted: { light: '#6b7280', dark: '#a8a8a0' },
  textSubtle: { light: '#8a8a84', dark: '#6b7280' },

  // Borders
  border: { light: '#e5e7eb', dark: '#3d3d3a' },

  // Semantic
  success: { light: '#10b981', dark: '#34d399' },
  error: { light: '#ef4444', dark: '#f87171' },
  warning: { light: '#f59e0b', dark: '#fbbf24' },
  info: '#2563eb',

  // Status badge backgrounds (light mode)
  statusActive: { bg: '#dcfce7', text: '#16a34a', border: '#bbf7d0' },
  statusInactive: { bg: '#fee2e2', text: '#dc2626', border: '#fecaca' },
  statusPending: { bg: '#fef3c7', text: '#d97706', border: '#fde68a' },
  statusInfo: { bg: '#dbeafe', text: '#1d4ed8', border: '#bfdbfe' },
  statusNeutral: { bg: '#f3f4f6', text: '#6b7280', border: '#e5e7eb' },

  // Tag colors
  tagPurple: { bg: '#ede9fe', text: '#7c3aed', border: '#ddd6fe' },
  tagGreen: { bg: '#dcfce7', text: '#16a34a', border: '#bbf7d0' },
  tagBlue: { bg: '#dbeafe', text: '#1d4ed8', border: '#bfdbfe' },
  tagYellow: { bg: '#fef3c7', text: '#d97706', border: '#fde68a' },

  // Button colors
  btnPrimary: '#161616',
  btnSecondary: '#f2f2f2',
  btnDestructive: '#ef4444',
  btnSuccess: '#10b981',
};

// Spacing Scale (4px base unit)
export const spacing = {
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
};

// Border Radius
export const radii = {
  sm: 5,
  md: 8,
  lg: 12,
  pill: 999,
};

// Typography
export const fontFamily = {
  sans: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  mono: '"DM Mono", "Fira Code", monospace',
};

export const typeScale = {
  display: { fontSize: 96, fontWeight: 800, letterSpacing: -3 },
  h1: { fontSize: 48, fontWeight: 700, letterSpacing: -1 },
  h2: { fontSize: 32, fontWeight: 700, letterSpacing: -0.5 },
  h3: { fontSize: 24, fontWeight: 600 },
  h4: { fontSize: 20, fontWeight: 600 },
  body: { fontSize: 14, fontWeight: 400, lineHeight: 1.5 },
  small: { fontSize: 12, fontWeight: 400 },
  caption: { fontSize: 11, fontWeight: 600, letterSpacing: 2, textTransform: 'uppercase' },
};

// Elevation / Shadows
export const shadows = {
  none: 'none',
  sm: '0 1px 2px rgba(0,0,0,0.05)',
  md: '0 4px 6px rgba(0,0,0,0.1)',
  lg: '0 10px 15px rgba(0,0,0,0.1)',
};

// ─── MUI Theme (Dark Mode — Primary App Theme) ──────────────────────────────

// Create a base palette first so we can use augmentColor
const basePalette = {
  mode: 'dark',
  primary: { main: colors.accentPrimary.dark },
  secondary: { main: colors.accentHover.dark },
  error: { main: colors.error.dark },
  warning: { main: colors.warning.dark },
  info: { main: '#60a5fa' },
  success: { main: colors.success.dark },
};

const { palette: muiPalette } = createTheme({ palette: basePalette });

const theme = createTheme({
  palette: {
    ...basePalette,
    default: muiPalette.augmentColor({
      color: { main: colors.accentHover.dark, contrastText: '#fff' },
      name: 'default',
    }),
    background: {
      default: colors.bgElevated.dark,
      paper: colors.bgPrimary.dark,
    },
    text: {
      primary: colors.textPrimary.dark,
      secondary: colors.textMuted.dark,
    },
    divider: colors.border.dark,
  },
  shape: { borderRadius: radii.md },
  typography: {
    fontFamily: fontFamily.sans,
    h1: {
      fontFamily: fontFamily.sans,
      fontWeight: typeScale.h1.fontWeight,
      fontSize: '24px',
      color: colors.textPrimary.dark,
    },
    h2: {
      fontFamily: fontFamily.sans,
      fontWeight: 600,
      fontSize: '20px',
      color: colors.textPrimary.dark,
    },
    h3: {
      fontFamily: fontFamily.sans,
      fontWeight: 600,
      fontSize: '18px',
      color: colors.textPrimary.dark,
    },
    h4: {
      fontFamily: fontFamily.sans,
      fontWeight: 600,
      fontSize: '16px',
      color: colors.textPrimary.dark,
    },
    h5: {
      fontFamily: fontFamily.sans,
      fontWeight: 600,
      fontSize: '16px',
      color: colors.textPrimary.dark,
    },
    h6: {
      fontFamily: fontFamily.sans,
      fontWeight: 600,
      fontSize: '16px',
      color: colors.textPrimary.dark,
    },
    body1: {
      fontFamily: fontFamily.sans,
      fontSize: '14px',
      color: colors.textPrimary.dark,
      fontWeight: 400,
    },
    body2: {
      fontFamily: fontFamily.sans,
      fontSize: '12px',
      color: colors.textPrimary.dark,
      fontWeight: 400,
    },
    button: {
      fontFamily: fontFamily.sans,
      fontWeight: 500,
      fontSize: '14px',
      textTransform: 'none',
    },
    caption: {
      fontFamily: fontFamily.sans,
      fontSize: '12px',
      color: colors.textMuted.dark,
      fontWeight: 400,
    },
    subtitle1: {
      fontFamily: fontFamily.sans,
      fontSize: '14px',
      color: colors.textPrimary.dark,
    },
    subtitle2: {
      fontFamily: fontFamily.sans,
      fontSize: '12px',
      color: colors.textPrimary.dark,
    },
    overline: {
      fontFamily: fontFamily.sans,
      fontSize: '11px',
      fontWeight: 600,
      letterSpacing: '0.15em',
      textTransform: 'uppercase',
      color: colors.textMuted.dark,
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: colors.bgElevated.dark,
          color: colors.textPrimary.dark,
          WebkitFontSmoothing: 'antialiased',
        },
        '::-webkit-scrollbar': { width: '6px', height: '6px' },
        '::-webkit-scrollbar-track': { background: colors.bgElevated.dark },
        '::-webkit-scrollbar-thumb': { background: '#5a5a56', borderRadius: '3px' },
      },
    },
    // ── Buttons ──────────────────────────────────────────────────────────
    MuiButton: {
      defaultProps: { color: 'primary', disableElevation: true },
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontFamily: fontFamily.sans,
          fontWeight: 500,
          borderRadius: radii.md,
          fontSize: '14px',
          gap: '8px',
        },
        contained: {
          backgroundColor: colors.btnPrimary,
          color: '#ffffff',
          '&:hover': { backgroundColor: '#2a2a2a' },
        },
        containedError: {
          backgroundColor: colors.btnDestructive,
          color: '#ffffff',
          '&:hover': { backgroundColor: '#dc2626' },
        },
        containedSuccess: {
          backgroundColor: colors.btnSuccess,
          color: '#ffffff',
          '&:hover': { backgroundColor: '#059669' },
        },
        outlined: {
          borderColor: colors.border.dark,
          color: colors.textMuted.dark,
          '&:hover': {
            borderColor: colors.accentPrimary.dark,
            backgroundColor: 'rgba(129, 140, 248, 0.08)',
          },
        },
        text: {
          color: colors.textMuted.dark,
          '&:hover': {
            backgroundColor: 'rgba(255, 255, 255, 0.06)',
          },
        },
        sizeSmall: {
          fontSize: '13px',
          padding: '6px 12px',
          borderRadius: `${radii.sm}px`,
        },
        sizeMedium: {
          fontSize: '14px',
          padding: '10px 16px',
        },
        sizeLarge: {
          fontSize: '14px',
          padding: '12px 32px',
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          borderRadius: radii.md,
          color: colors.textMuted.dark,
          '&:hover': { backgroundColor: 'rgba(255, 255, 255, 0.06)' },
        },
        sizeMedium: { padding: 10 },
      },
    },
    // ── Cards & Surfaces ─────────────────────────────────────────────────
    MuiCard: {
      styleOverrides: {
        root: {
          boxShadow: 'none',
          borderRadius: radii.lg,
          backgroundColor: colors.bgPrimary.dark,
          border: `1px solid ${colors.border.dark}`,
        },
      },
    },
    MuiCardHeader: {
      styleOverrides: {
        root: {
          padding: '24px',
          borderBottom: `1px solid ${colors.border.dark}`,
        },
        title: {
          fontFamily: fontFamily.sans,
          fontWeight: 600,
          fontSize: '16px',
        },
        subheader: {
          fontFamily: fontFamily.sans,
          fontSize: '13px',
          color: colors.textMuted.dark,
        },
      },
    },
    MuiCardContent: {
      styleOverrides: {
        root: { padding: '24px', '&:last-child': { paddingBottom: '24px' } },
      },
    },
    MuiCardActions: {
      styleOverrides: {
        root: {
          padding: '24px',
          borderTop: `1px solid ${colors.border.dark}`,
          justifyContent: 'flex-end',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: radii.lg,
          border: `1px solid ${colors.border.dark}`,
          backgroundColor: colors.bgPrimary.dark,
          backgroundImage: 'none',
        },
        elevation0: { boxShadow: 'none' },
        elevation1: { boxShadow: 'none' },
        elevation2: { boxShadow: 'none' },
        elevation3: { boxShadow: 'none' },
      },
    },
    // ── Form Inputs ──────────────────────────────────────────────────────
    MuiTextField: {
      defaultProps: { variant: 'outlined', size: 'medium' },
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: radii.md,
            fontSize: '14px',
            fontFamily: fontFamily.sans,
            backgroundColor: colors.bgElevated.dark,
            color: colors.textPrimary.dark,
            height: 42,
            '& fieldset': { borderColor: colors.border.dark, borderWidth: 2 },
            '&:hover fieldset': { borderColor: colors.accentHover.dark },
            '&.Mui-focused fieldset': { borderColor: colors.accentPrimary.dark },
            '&.Mui-error fieldset': { borderColor: colors.error.dark },
            '&.Mui-disabled': {
              opacity: 0.6,
              backgroundColor: colors.bgPrimary.dark,
            },
          },
          '& .MuiInputLabel-root': {
            color: colors.textMuted.dark,
            fontSize: '13px',
            fontWeight: 500,
          },
          '& .MuiInputLabel-root.Mui-focused': {
            color: colors.accentPrimary.dark,
          },
          '& .MuiFormHelperText-root.Mui-error': {
            color: colors.error.dark,
            fontSize: '12px',
            marginLeft: 0,
            marginTop: '6px',
          },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: radii.md,
          '& fieldset': { borderColor: colors.border.dark, borderWidth: 2 },
          '&:hover fieldset': { borderColor: colors.accentHover.dark },
          '&.Mui-focused fieldset': { borderColor: colors.accentPrimary.dark },
        },
        input: { padding: '10px 14px' },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          fontFamily: fontFamily.sans,
          fontSize: '13px',
          fontWeight: 500,
          color: colors.textMuted.dark,
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          fontFamily: fontFamily.sans,
          fontSize: '14px',
          borderRadius: radii.md,
        },
      },
    },
    MuiFormControlLabel: {
      styleOverrides: {
        label: { fontFamily: fontFamily.sans, fontSize: '14px' },
      },
    },
    // ── Chips / Tags ─────────────────────────────────────────────────────
    MuiChip: {
      styleOverrides: {
        root: {
          fontFamily: fontFamily.sans,
          fontSize: '11px',
          fontWeight: 500,
          borderRadius: radii.sm,
          height: 'auto',
        },
        sizeSmall: { padding: '2px 8px', fontSize: '11px' },
        sizeMedium: { padding: '4px 12px', fontSize: '11.5px' },
        deleteIcon: { fontSize: '14px', marginRight: '-2px' },
      },
    },
    // ── Tables ───────────────────────────────────────────────────────────
    MuiTable: {
      styleOverrides: {
        root: { fontFamily: fontFamily.sans },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          fontFamily: fontFamily.sans,
          fontSize: '13.5px',
          borderBottomColor: colors.border.dark,
          color: colors.textPrimary.dark,
          padding: '13px 16px',
        },
        head: {
          fontFamily: fontFamily.sans,
          fontSize: '11px',
          fontWeight: 600,
          color: colors.textMuted.dark,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          padding: '10px 16px',
          backgroundColor: 'rgba(255,255,255,0.02)',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          transition: 'background-color 0.15s ease',
          '&:hover': { backgroundColor: 'rgba(129, 140, 248, 0.05)' },
        },
      },
    },
    // ── Tabs ─────────────────────────────────────────────────────────────
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: fontFamily.sans,
          fontSize: '13px',
          fontWeight: 500,
          textTransform: 'none',
          minHeight: 'auto',
          padding: '8px 16px',
          color: colors.textMuted.dark,
          '&.Mui-selected': { color: colors.accentPrimary.dark },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: { backgroundColor: colors.accentPrimary.dark },
      },
    },
    // ── Typography ───────────────────────────────────────────────────────
    MuiTypography: {
      styleOverrides: {
        root: { fontFamily: fontFamily.sans },
      },
    },
    // ── Alerts ───────────────────────────────────────────────────────────
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: radii.md,
          fontFamily: fontFamily.sans,
          fontSize: '14px',
        },
        standardError: {
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
          border: `1px solid ${colors.error.light}`,
          color: colors.error.dark,
        },
        standardSuccess: {
          backgroundColor: 'rgba(16, 185, 129, 0.15)',
          border: `1px solid ${colors.success.dark}`,
          color: colors.success.dark,
        },
        standardWarning: {
          backgroundColor: 'rgba(245, 158, 11, 0.15)',
          border: `1px solid ${colors.warning.light}`,
          color: colors.warning.dark,
        },
        standardInfo: {
          backgroundColor: 'rgba(59, 130, 246, 0.15)',
          border: '1px solid #3b82f6',
          color: '#60a5fa',
        },
      },
    },
    // ── Dialogs ──────────────────────────────────────────────────────────
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: radii.lg,
          border: `1px solid ${colors.border.dark}`,
          backgroundColor: colors.bgPrimary.dark,
          backgroundImage: 'none',
        },
      },
    },
    // ── Accordion ────────────────────────────────────────────────────────
    MuiAccordion: {
      styleOverrides: {
        root: {
          borderRadius: `${radii.lg}px`,
          border: `1px solid ${colors.border.dark}`,
          backgroundColor: colors.bgPrimary.dark,
          backgroundImage: 'none',
          '&:before': { display: 'none' },
        },
      },
    },
    // ── Menu ─────────────────────────────────────────────────────────────
    MuiMenu: {
      styleOverrides: {
        paper: {
          backgroundColor: colors.bgPrimary.dark,
          border: `1px solid ${colors.border.dark}`,
          backgroundImage: 'none',
        },
      },
    },
    MuiMenuItem: {
      styleOverrides: {
        root: {
          fontSize: '14px',
          color: colors.textPrimary.dark,
          '&:hover': { backgroundColor: 'rgba(129, 140, 248, 0.1)' },
        },
      },
    },
    // ── Divider ──────────────────────────────────────────────────────────
    MuiDivider: {
      styleOverrides: {
        root: { borderColor: colors.border.dark },
      },
    },
    // ── Tooltip ──────────────────────────────────────────────────────────
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          fontFamily: fontFamily.sans,
          fontSize: '12px',
          backgroundColor: colors.btnPrimary,
          borderRadius: radii.sm,
          padding: '6px 12px',
        },
      },
    },
  },
});

export default theme;
