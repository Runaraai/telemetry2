import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate, useLocation, Navigate, Link } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { Box, Toolbar, Button, Avatar, Typography, Drawer, List, ListItem, ListItemButton, ListItemIcon, ListItemText, IconButton, Menu, MenuItem, CircularProgress } from '@mui/material';
import { Dashboard as DashboardIcon, Assessment as AssessmentIcon, Cloud, History as HistoryIcon, Dns as DnsIcon, Logout, Person } from '@mui/icons-material';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { UIProvider } from './components/ui/UIProvider';
import CommandPalette from './components/ui/CommandPalette';
import Benchmarking from './pages/Benchmarking';
import ManageInstances from './pages/ManageInstances';
import RunningInstances from './pages/RunningInstances';
import Telemetry from './pages/Telemetry';
import LoginPage from './pages/Login';
import OnboardingWizard from './components/OnboardingWizard';
import theme from './theme';

const SIDEBAR_WIDTH = 220;

function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const menuItems = [
    { text: 'Instances', path: '/instances' },
    { text: 'Run Workload', path: '/profiling' },
    { text: 'Telemetry', path: '/telemetry' },
    { text: 'Running Instances', path: '/running-instances' },
  ];

  const isActive = (path) =>
    location.pathname === path || location.pathname.startsWith(path + '/');

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <Box
      component="nav"
      sx={{
        width: SIDEBAR_WIDTH,
        minWidth: SIDEBAR_WIDTH,
        height: '100vh',
        position: 'fixed',
        top: 0,
        left: 0,
        borderRight: '1px solid #3d3d3a',
        backgroundColor: 'rgba(26, 26, 24, 0.95)',
        backdropFilter: 'blur(12px)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 50,
      }}
    >
      {/* Logo */}
      <Box
        component={Link}
        to="/profiling"
        sx={{
          display: 'flex',
          alignItems: 'center',
          textDecoration: 'none',
          px: 2.5,
          py: 2.5,
          borderBottom: '1px solid #3d3d3a',
        }}
      >
        <img
          src="/logo.png"
          alt="Runara"
          style={{ height: '28px' }}
        />
      </Box>

      {/* Nav Links */}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, px: 1.5, py: 2, flex: 1 }}>
        {menuItems.map((item) => (
          <Box
            key={item.text}
            component={Link}
            to={item.path}
            sx={{
              px: 1.5,
              py: 1,
              borderRadius: '6px',
              fontSize: '14px',
              fontWeight: 500,
              textDecoration: 'none',
              transition: 'all 0.15s ease',
              ...(isActive(item.path)
                ? {
                    backgroundColor: '#fafaf8',
                    color: '#1a1a18',
                    fontWeight: 600,
                  }
                : {
                    color: '#a8a8a0',
                    '&:hover': {
                      color: '#fafaf8',
                      backgroundColor: 'rgba(255, 255, 255, 0.06)',
                    },
                  }),
            }}
          >
            {item.text}
          </Box>
        ))}
      </Box>

      {/* Sign out at bottom */}
      <Box sx={{ borderTop: '1px solid #3d3d3a', px: 1.5, py: 1.5 }}>
        <Button
          onClick={handleLogout}
          fullWidth
          sx={{
            justifyContent: 'flex-start',
            fontSize: '14px',
            color: '#a8a8a0',
            '&:hover': {
              color: '#fafaf8',
              backgroundColor: 'rgba(255, 255, 255, 0.06)',
            },
            textTransform: 'none',
            fontWeight: 400,
            px: 1.5,
          }}
        >
          Sign out
        </Button>
      </Box>
    </Box>
  );
}

function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

function AppContent() {
  const [sharedAnalysisState, setSharedAnalysisState] = useState(null);
  const location = useLocation();
  const { isAuthenticated, loading } = useAuth();

  // Update document title and force favicon refresh
  React.useEffect(() => {
    document.title = 'Runara';
    
    // Force favicon refresh to clear any cached Grafana icon
    const favicon = document.querySelector('link[rel="icon"]');
    if (favicon) {
      const newFavicon = document.createElement('link');
      newFavicon.rel = 'icon';
      newFavicon.href = '/favicon.svg?t=' + Date.now();
      newFavicon.type = 'image/svg+xml';
      document.head.appendChild(newFavicon);
      document.head.removeChild(favicon);
    }
  }, [location.pathname]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', backgroundColor: '#2d2d2a', display: 'flex' }}>
      <OnboardingWizard />
      <Sidebar />
      <Box
        component="main"
        sx={{
          flex: 1,
          marginLeft: `${SIDEBAR_WIDTH}px`,
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <Box
          sx={{
            maxWidth: `calc(1280px + 64px)`,
            width: '100%',
            px: { xs: 2, sm: 3, lg: 4 },
            py: 4,
          }}
        >
        <Routes>
          <Route path="/" element={<ProtectedRoute><Benchmarking /></ProtectedRoute>} />
          <Route path="/profiling" element={<ProtectedRoute><Benchmarking /></ProtectedRoute>} />
          <Route path="/instances" element={<ProtectedRoute><ManageInstances /></ProtectedRoute>} />
          <Route path="/telemetry" element={<ProtectedRoute><Telemetry /></ProtectedRoute>} />
          <Route path="/running-instances" element={<ProtectedRoute><RunningInstances /></ProtectedRoute>} />
          <Route path="/login" element={<Navigate to="/" replace />} />
        </Routes>
        </Box>
      </Box>
    </Box>
  );
}

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Router>
        <AuthProvider>
          <UIProvider>
            <CommandPalette />
            <AppContent />
          </UIProvider>
        </AuthProvider>
      </Router>
    </ThemeProvider>
  );
}

export default App;
