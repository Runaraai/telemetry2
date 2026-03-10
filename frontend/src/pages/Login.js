import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Box,
  Container,
  Paper,
  TextField,
  Button,
  Typography,
  Alert,
  Tab,
  Tabs,
} from '@mui/material';
import { useAuth } from '../contexts/AuthContext';

function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState(0); // 0 = login, 1 = signup
  const { login, signup } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      let result;
      if (tab === 0) {
        // Login
        result = await login(email, password);
      } else {
        // Signup
        result = await signup(email, password);
      }

      if (result.success) {
        navigate('/');
      } else {
        setError(result.error || 'Authentication failed');
      }
    } catch (err) {
      setError(err.message || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#0D1B13',
        px: 2,
      }}
    >
      <Box sx={{ width: '100%', maxWidth: '400px' }}>
        {/* Logo */}
        <Box sx={{ display: 'flex', justifyContent: 'center', mb: 4 }}>
          <img src="/logo.png" alt="Runara" style={{ height: '32px' }} />
        </Box>

        <Paper
          elevation={0}
          sx={{
            p: 4,
            borderRadius: '12px',
            border: '1px solid #1E4530',
            backgroundColor: '#142B1D',
          }}
        >
          <Typography variant="h5" component="h1" sx={{ mb: 3, fontWeight: 600, color: '#ffffff' }}>
            {tab === 0 ? 'Sign in' : 'Create account'}
          </Typography>

          <Tabs
            value={tab}
            onChange={(e, newValue) => {
              setTab(newValue);
              setError('');
            }}
            sx={{
              mb: 3,
              '& .MuiTabs-indicator': {
                backgroundColor: '#3DA866',
              },
            }}
          >
            <Tab label="Login" sx={{ color: '#94a3b8', '&.Mui-selected': { color: '#3DA866' } }} />
            <Tab label="Sign Up" sx={{ color: '#94a3b8', '&.Mui-selected': { color: '#3DA866' } }} />
          </Tabs>

          {error && (
            <Alert severity="error" sx={{
              mb: 2,
              backgroundColor: 'rgba(153, 27, 27, 0.3)',
              border: '1px solid #991b1b',
              color: '#f87171',
              '& .MuiAlert-icon': { color: '#f87171' }
            }}>
              {error}
            </Alert>
          )}

          <form onSubmit={handleSubmit}>
            <TextField
              fullWidth
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              margin="normal"
              autoComplete="email"
              placeholder="you@example.com"
            />
            <TextField
              fullWidth
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              margin="normal"
              autoComplete={tab === 0 ? 'current-password' : 'new-password'}
              placeholder="••••••••"
              helperText={tab === 1 ? 'Password must be at least 6 characters' : ''}
            />
            <Button
              type="submit"
              fullWidth
              variant="contained"
              sx={{
                mt: 3,
                mb: 2,
                py: 1.5,
                backgroundColor: '#3DA866',
                '&:hover': { backgroundColor: '#22c55e' },
              }}
              disabled={loading}
            >
              {loading ? 'Please wait...' : tab === 0 ? 'Sign In' : 'Sign Up'}
            </Button>
          </form>
        </Paper>
      </Box>
    </Box>
  );
}

export default LoginPage;



