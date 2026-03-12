import React, { useState } from 'react';
import {
  TextField,
  InputAdornment,
  IconButton,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Box,
  Typography,
} from '@mui/material';
import { Search, Visibility, VisibilityOff, ChevronRight } from '@mui/icons-material';

/**
 * Design System Text Input — 42px height, 8px radius, 2px borders.
 *
 * States: default | focused | error | disabled
 */
export default function DSInput({
  label,
  placeholder,
  error,
  helperText,
  disabled,
  sx = {},
  ...props
}) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: '6px', ...sx }}>
      {label && (
        <Typography
          sx={{
            fontSize: '13px',
            fontWeight: 500,
            color: '#fafaf8',
            fontFamily: '"Geist", sans-serif',
          }}
        >
          {label}
        </Typography>
      )}
      <TextField
        placeholder={placeholder}
        error={error}
        helperText={error ? helperText : undefined}
        disabled={disabled}
        variant="outlined"
        size="small"
        sx={{
          '& .MuiOutlinedInput-root': {
            height: 42,
            borderRadius: '8px',
            fontSize: '14px',
            backgroundColor: disabled ? '#2d2d2a' : '#2d2d2a',
            opacity: disabled ? 0.6 : 1,
            '& fieldset': {
              borderWidth: 2,
              borderColor: error ? '#f87171' : '#3d3d3a',
            },
            '&:hover fieldset': {
              borderColor: error ? '#f87171' : '#6366f1',
            },
            '&.Mui-focused fieldset': {
              borderColor: error ? '#f87171' : '#818cf8',
              boxShadow: error ? 'none' : '0 2px 8px rgba(102,126,234,0.13)',
            },
          },
          '& .MuiFormHelperText-root': {
            color: '#f87171',
            fontSize: '12px',
            marginLeft: 0,
            marginTop: '6px',
            fontFamily: '"Geist", sans-serif',
          },
        }}
        {...props}
      />
    </Box>
  );
}

/**
 * Search Input with magnifying glass icon.
 */
export function DSSearchInput({ placeholder = 'Search...', sx = {}, ...props }) {
  return (
    <DSInput
      placeholder={placeholder}
      InputProps={{
        startAdornment: (
          <InputAdornment position="start">
            <Search sx={{ fontSize: 18, color: '#a8a8a0' }} />
          </InputAdornment>
        ),
      }}
      sx={sx}
      {...props}
    />
  );
}

/**
 * Password Input with visibility toggle.
 */
export function DSPasswordInput({ label = 'Password', sx = {}, ...props }) {
  const [show, setShow] = useState(false);

  return (
    <DSInput
      label={label}
      type={show ? 'text' : 'password'}
      placeholder="••••••••"
      InputProps={{
        endAdornment: (
          <InputAdornment position="end">
            <IconButton
              onClick={() => setShow(!show)}
              edge="end"
              size="small"
              sx={{ color: '#a8a8a0' }}
            >
              {show ? <VisibilityOff sx={{ fontSize: 18 }} /> : <Visibility sx={{ fontSize: 18 }} />}
            </IconButton>
          </InputAdornment>
        ),
      }}
      sx={sx}
      {...props}
    />
  );
}

/**
 * Select Dropdown — styled to match design system.
 */
export function DSSelect({
  label,
  options = [],
  value,
  onChange,
  placeholder = 'Select an option',
  sx = {},
  ...props
}) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: '6px', ...sx }}>
      {label && (
        <Typography
          sx={{
            fontSize: '13px',
            fontWeight: 500,
            color: '#fafaf8',
            fontFamily: '"Geist", sans-serif',
          }}
        >
          {label}
        </Typography>
      )}
      <FormControl size="small">
        <Select
          value={value}
          onChange={onChange}
          displayEmpty
          sx={{
            height: 42,
            borderRadius: '8px',
            fontSize: '14px',
            backgroundColor: '#2d2d2a',
            '& .MuiOutlinedInput-notchedOutline': {
              borderWidth: 2,
              borderColor: '#3d3d3a',
            },
            '&:hover .MuiOutlinedInput-notchedOutline': {
              borderColor: '#6366f1',
            },
            '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
              borderColor: '#818cf8',
            },
          }}
          {...props}
        >
          <MenuItem value="" disabled>
            <Typography sx={{ color: '#6b7280', fontSize: '14px' }}>{placeholder}</Typography>
          </MenuItem>
          {options.map((opt) => (
            <MenuItem key={opt.value} value={opt.value}>
              {opt.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Box>
  );
}
