import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate, useLocation, Navigate, Link } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { Box, Toolbar, Button, Avatar, Typography, Drawer, List, ListItem, ListItemButton, ListItemIcon, ListItemText, IconButton, Menu, MenuItem, CircularProgress } from '@mui/material';
import { Dashboard as DashboardIcon, Assessment as AssessmentIcon, Cloud, History as HistoryIcon, Dns as DnsIcon, Logout, Person } from '@mui/icons-material';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { UIProvider } from './components/ui/UIProvider';
import CommandPalette from './components/ui/CommandPalette';
import Benchmarking from './pages/Benchmarking';
import ManageInstances from './pages/ManageInstances';
import RunningInstances from './pages/RunningInstances';
import TelemetryHistory from './components/TelemetryHistory';
import LoginPage from './pages/Login';
import Workload from './pages/Workload';
import OnboardingWizard from './components/OnboardingWizard';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#818cf8',
    },
    secondary: {
      main: '#6366f1',
    },
    error: {
      main: '#f87171',
    },
    warning: {
      main: '#fbbf24',
    },
    info: {
      main: '#60a5fa',
    },
    success: {
      main: '#34d399',
    },
    default: {
      main: '#6366f1',
      contrastText: '#fff',
    },
    background: {
      default: '#2d2d2a',
      paper: '#1a1a18',
    },
    text: {
      primary: '#fafaf8',
      secondary: '#a8a8a0',
    },
    divider: '#3d3d3a',
  },
  typography: {
    fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h1: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontWeight: 600,
      fontSize: '24px',
      color: '#fafaf8',
    },
    h2: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontWeight: 600,
      fontSize: '20px',
      color: '#fafaf8',
    },
    h3: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontWeight: 600,
      fontSize: '18px',
      color: '#fafaf8',
    },
    h4: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#fafaf8',
    },
    h5: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#fafaf8',
    },
    h6: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#fafaf8',
    },
    body1: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: '14px',
      color: '#fafaf8',
      fontWeight: 400,
    },
    body2: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: '12px',
      color: '#fafaf8',
      fontWeight: 400,
    },
    button: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontWeight: 500,
      fontSize: '14px',
      textTransform: 'none',
    },
    caption: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: '12px',
      color: '#a8a8a0',
      fontWeight: 400,
    },
    subtitle1: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: '14px',
      color: '#fafaf8',
    },
    subtitle2: {
      fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: '12px',
      color: '#fafaf8',
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: '#2d2d2a',
          color: '#fafaf8',
          WebkitFontSmoothing: 'antialiased',
        },
        '::-webkit-scrollbar': {
          width: '6px',
          height: '6px',
        },
        '::-webkit-scrollbar-track': {
          background: '#2d2d2a',
        },
        '::-webkit-scrollbar-thumb': {
          background: '#5a5a56',
          borderRadius: '3px',
        },
      },
    },
    MuiButton: {
      defaultProps: {
        color: 'primary',
      },
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontWeight: 500,
          borderRadius: '8px',
          fontSize: '14px',
        },
        contained: {
          backgroundColor: '#818cf8',
          color: '#ffffff',
          '&:hover': {
            backgroundColor: '#6366f1',
          },
        },
        outlined: {
          borderColor: '#3d3d3a',
          color: '#a8a8a0',
          '&:hover': {
            borderColor: '#818cf8',
            backgroundColor: 'rgba(129, 140, 248, 0.08)',
          },
        },
        sizeSmall: {
          fontSize: '10px',
          padding: '5px 10px',
          minHeight: '22px',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          boxShadow: 'none',
          borderRadius: '12px',
          backgroundColor: '#1a1a18',
          border: '1px solid #3d3d3a',
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: '8px',
            fontSize: '14px',
            fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
            backgroundColor: '#2d2d2a',
            color: '#fafaf8',
            '& fieldset': {
              borderColor: '#3d3d3a',
            },
            '&:hover fieldset': {
              borderColor: '#6366f1',
            },
            '&.Mui-focused fieldset': {
              borderColor: '#818cf8',
            },
          },
          '& .MuiInputLabel-root': {
            color: '#a8a8a0',
          },
          '& .MuiInputLabel-root.Mui-focused': {
            color: '#818cf8',
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: '12px',
          borderRadius: '4px',
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: '10px',
          fontWeight: 400,
          textTransform: 'none',
          minHeight: 'auto',
          padding: '3px 10px',
          color: '#a8a8a0',
          '&.Mui-selected': {
            color: '#818cf8',
          },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: {
          backgroundColor: '#818cf8',
        },
      },
    },
    MuiTypography: {
      styleOverrides: {
        root: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: '12px',
          border: '1px solid #3d3d3a',
          backgroundColor: '#1a1a18',
          backgroundImage: 'none',
        },
        elevation1: {
          boxShadow: 'none',
        },
        elevation2: {
          boxShadow: 'none',
        },
        elevation3: {
          boxShadow: 'none',
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: '8px',
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: '14px',
        },
        standardError: {
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid #ef4444',
          color: '#f87171',
        },
        standardSuccess: {
          backgroundColor: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid #34d399',
          color: '#34d399',
        },
        standardWarning: {
          backgroundColor: 'rgba(245, 158, 11, 0.15)',
          border: '1px solid #f59e0b',
          color: '#fbbf24',
        },
        standardInfo: {
          backgroundColor: 'rgba(59, 130, 246, 0.15)',
          border: '1px solid #3b82f6',
          color: '#60a5fa',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: '12px',
          border: '1px solid #3d3d3a',
          backgroundColor: '#1a1a18',
          backgroundImage: 'none',
        },
      },
    },
    MuiTable: {
      styleOverrides: {
        root: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: '14px',
          borderBottomColor: '#3d3d3a',
          color: '#fafaf8',
        },
        head: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: '12px',
          fontWeight: 600,
          color: '#a8a8a0',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          '&:hover': {
            backgroundColor: 'rgba(129, 140, 248, 0.05)',
          },
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: '14px',
          borderRadius: '8px',
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: '14px',
          color: '#a8a8a0',
        },
      },
    },
    MuiFormControlLabel: {
      styleOverrides: {
        label: {
          fontFamily: '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: '14px',
        },
      },
    },
    MuiAccordion: {
      styleOverrides: {
        root: {
          borderRadius: '12px',
          border: '1px solid #3d3d3a',
          backgroundColor: '#1a1a18',
          backgroundImage: 'none',
          '&:before': {
            display: 'none',
          },
        },
      },
    },
    MuiMenu: {
      styleOverrides: {
        paper: {
          backgroundColor: '#1a1a18',
          border: '1px solid #3d3d3a',
          backgroundImage: 'none',
        },
      },
    },
    MuiMenuItem: {
      styleOverrides: {
        root: {
          color: '#fafaf8',
          '&:hover': {
            backgroundColor: 'rgba(129, 140, 248, 0.1)',
          },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          '& fieldset': {
            borderColor: '#3d3d3a',
          },
          '&:hover fieldset': {
            borderColor: '#6366f1',
          },
          '&.Mui-focused fieldset': {
            borderColor: '#818cf8',
          },
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: '#3d3d3a',
        },
      },
    },
  },
});

const SIDEBAR_WIDTH = 220;

function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const menuItems = [
    { text: 'Run Workload', path: '/profiling' },
    { text: 'Manage Instances', path: '/instances' },
    { text: 'Running Instances', path: '/running-instances' },
    { text: 'Workload', path: '/workload' },
    { text: 'Telemetry History', path: '/telemetry-history' }
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
          <Route path="/running-instances" element={<ProtectedRoute><RunningInstances /></ProtectedRoute>} />
          <Route path="/workload" element={<ProtectedRoute><Workload /></ProtectedRoute>} />
          <Route path="/telemetry-history" element={<ProtectedRoute><TelemetryHistory /></ProtectedRoute>} />
          <Route path="/login" element={<Navigate to="/" replace />} />
        </Routes>
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
