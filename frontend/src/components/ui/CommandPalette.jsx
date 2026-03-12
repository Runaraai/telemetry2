import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  List,
  ListItemButton,
  ListItemText,
  TextField,
  Stack,
  Chip,
} from '@mui/material';
import { Search as SearchIcon } from '@mui/icons-material';

const QUICK_ACTIONS = [
  { label: 'Go to Benchmarking', path: '/' },
  { label: 'Go to Run Workload', path: '/profiling' },
  { label: 'Telemetry', path: '/telemetry' },
  { label: 'Manage Instances', path: '/instances' },
  { label: 'Telemetry History', path: '/telemetry-history' },
  { label: 'Refresh page', action: 'refresh' },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const location = useLocation();

  // Handle keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      const isCmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
      if (isCmdK) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const actions = useMemo(() => {
    const q = query.toLowerCase();
    return QUICK_ACTIONS.filter((a) => a.label.toLowerCase().includes(q));
  }, [query]);

  const handleAction = (action) => {
    if (action.path) {
      if (location.pathname !== action.path) {
        navigate(action.path);
      }
      setOpen(false);
      return;
    }
    if (action.action === 'refresh') {
      window.location.reload();
    }
    setOpen(false);
  };

  return (
    <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
      <DialogTitle>Quick actions (Cmd/Ctrl + K)</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <TextField
            autoFocus
            placeholder="Search actions..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            InputProps={{
              startAdornment: <SearchIcon sx={{ mr: 1, color: 'text.secondary' }} />,
            }}
          />
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Chip size="small" label="Jump" />
            <Chip size="small" label="Refresh" />
            <Chip size="small" label="Instances" />
            <Chip size="small" label="Benchmark" />
          </Stack>
          <List>
            {actions.map((action) => (
              <ListItemButton key={action.label} onClick={() => handleAction(action)}>
                <ListItemText primary={action.label} />
              </ListItemButton>
            ))}
          </List>
        </Stack>
      </DialogContent>
    </Dialog>
  );
}
