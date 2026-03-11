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

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#3DA866',
    },
    secondary: {
      main: '#3A6B4E',
    },
    error: {
      main: '#d32f2f',
    },
    warning: {
      main: '#ed6c02',
    },
    info: {
      main: '#0288d1',
    },
    success: {
      main: '#2e7d32',
    },
    default: {
      main: '#3A6B4E',
      contrastText: '#fff',
    },
    background: {
      default: '#0D1B13',
      paper: '#142B1D',
    },
    text: {
      primary: '#e2e8f0',
      secondary: '#94a3b8',
    },
    divider: '#1E4530',
  },
  typography: {
    fontFamily: '"Inter", system-ui, sans-serif',
    h1: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontWeight: 600,
      fontSize: '24px',
      color: '#e2e8f0',
    },
    h2: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontWeight: 600,
      fontSize: '20px',
      color: '#e2e8f0',
    },
    h3: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontWeight: 600,
      fontSize: '18px',
      color: '#e2e8f0',
    },
    h4: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#e2e8f0',
    },
    h5: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#e2e8f0',
    },
    h6: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#e2e8f0',
    },
    body1: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontSize: '14px',
      color: '#e2e8f0',
      fontWeight: 400,
    },
    body2: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontSize: '12px',
      color: '#e2e8f0',
      fontWeight: 400,
    },
    button: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontWeight: 500,
      fontSize: '14px',
      textTransform: 'none',
    },
    caption: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontSize: '12px',
      color: '#94a3b8',
      fontWeight: 400,
    },
    subtitle1: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontSize: '14px',
      color: '#e2e8f0',
    },
    subtitle2: {
      fontFamily: '"Inter", system-ui, sans-serif',
      fontSize: '12px',
      color: '#e2e8f0',
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: '#0D1B13',
          color: '#e2e8f0',
          WebkitFontSmoothing: 'antialiased',
        },
        '::-webkit-scrollbar': {
          width: '6px',
          height: '6px',
        },
        '::-webkit-scrollbar-track': {
          background: '#142B1D',
        },
        '::-webkit-scrollbar-thumb': {
          background: '#1E4530',
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
          fontFamily: '"Inter", system-ui, sans-serif',
          fontWeight: 500,
          borderRadius: '8px',
          fontSize: '14px',
        },
        contained: {
          backgroundColor: '#3DA866',
          color: '#ffffff',
          '&:hover': {
            backgroundColor: '#22c55e',
          },
        },
        outlined: {
          borderColor: '#1E4530',
          color: '#94a3b8',
          '&:hover': {
            borderColor: '#3DA866',
            backgroundColor: 'rgba(61, 168, 102, 0.08)',
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
          backgroundColor: '#142B1D',
          border: '1px solid #1E4530',
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: '8px',
            fontSize: '14px',
            fontFamily: '"Inter", system-ui, sans-serif',
            backgroundColor: '#0D1B13',
            color: '#e2e8f0',
            '& fieldset': {
              borderColor: '#1E4530',
            },
            '&:hover fieldset': {
              borderColor: '#3A6B4E',
            },
            '&.Mui-focused fieldset': {
              borderColor: '#3DA866',
            },
          },
          '& .MuiInputLabel-root': {
            color: '#94a3b8',
          },
          '& .MuiInputLabel-root.Mui-focused': {
            color: '#3DA866',
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontFamily: '"Inter", system-ui, sans-serif',
          fontSize: '12px',
          borderRadius: '4px',
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: '"Inter", system-ui, sans-serif',
          fontSize: '10px',
          fontWeight: 400,
          textTransform: 'none',
          minHeight: 'auto',
          padding: '3px 10px',
          color: '#94a3b8',
          '&.Mui-selected': {
            color: '#3DA866',
          },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: {
          backgroundColor: '#3DA866',
        },
      },
    },
    MuiTypography: {
      styleOverrides: {
        root: {
          fontFamily: '"Inter", system-ui, sans-serif',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: '12px',
          border: '1px solid #1E4530',
          backgroundColor: '#142B1D',
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
          fontFamily: '"Inter", system-ui, sans-serif',
          fontSize: '14px',
        },
        standardError: {
          backgroundColor: 'rgba(153, 27, 27, 0.3)',
          border: '1px solid #991b1b',
          color: '#f87171',
        },
        standardSuccess: {
          backgroundColor: 'rgba(22, 101, 52, 0.3)',
          border: '1px solid #166534',
          color: '#4ade80',
        },
        standardWarning: {
          backgroundColor: 'rgba(146, 64, 14, 0.3)',
          border: '1px solid #92400e',
          color: '#fbbf24',
        },
        standardInfo: {
          backgroundColor: 'rgba(30, 58, 138, 0.3)',
          border: '1px solid #1e3a8a',
          color: '#60a5fa',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: '12px',
          border: '1px solid #1E4530',
          backgroundColor: '#142B1D',
          backgroundImage: 'none',
        },
      },
    },
    MuiTable: {
      styleOverrides: {
        root: {
          fontFamily: '"Inter", system-ui, sans-serif',
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          fontFamily: '"Inter", system-ui, sans-serif',
          fontSize: '14px',
          borderBottomColor: '#1E4530',
          color: '#e2e8f0',
        },
        head: {
          fontFamily: '"Inter", system-ui, sans-serif',
          fontSize: '12px',
          fontWeight: 600,
          color: '#94a3b8',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          '&:hover': {
            backgroundColor: 'rgba(61, 168, 102, 0.05)',
          },
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          fontFamily: '"Inter", system-ui, sans-serif',
          fontSize: '14px',
          borderRadius: '8px',
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          fontFamily: '"Inter", system-ui, sans-serif',
          fontSize: '14px',
          color: '#94a3b8',
        },
      },
    },
    MuiFormControlLabel: {
      styleOverrides: {
        label: {
          fontFamily: '"Inter", system-ui, sans-serif',
          fontSize: '14px',
        },
      },
    },
    MuiAccordion: {
      styleOverrides: {
        root: {
          borderRadius: '12px',
          border: '1px solid #1E4530',
          backgroundColor: '#142B1D',
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
          backgroundColor: '#142B1D',
          border: '1px solid #1E4530',
          backgroundImage: 'none',
        },
      },
    },
    MuiMenuItem: {
      styleOverrides: {
        root: {
          color: '#e2e8f0',
          '&:hover': {
            backgroundColor: 'rgba(61, 168, 102, 0.1)',
          },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          '& fieldset': {
            borderColor: '#1E4530',
          },
          '&:hover fieldset': {
            borderColor: '#3A6B4E',
          },
          '&.Mui-focused fieldset': {
            borderColor: '#3DA866',
          },
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: '#1E4530',
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
        borderRight: '1px solid #1E4530',
        backgroundColor: 'rgba(20, 43, 29, 0.5)',
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
          borderBottom: '1px solid #1E4530',
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
                    backgroundColor: 'rgba(61, 168, 102, 0.15)',
                    color: '#3DA866',
                  }
                : {
                    color: '#94a3b8',
                    '&:hover': {
                      color: '#e2e8f0',
                      backgroundColor: 'rgba(255, 255, 255, 0.04)',
                    },
                  }),
            }}
          >
            {item.text}
          </Box>
        ))}
      </Box>

      {/* Sign out at bottom */}
      <Box sx={{ borderTop: '1px solid #1E4530', px: 1.5, py: 1.5 }}>
        <Button
          onClick={handleLogout}
          fullWidth
          sx={{
            justifyContent: 'flex-start',
            fontSize: '14px',
            color: '#94a3b8',
            '&:hover': {
              color: '#e2e8f0',
              backgroundColor: 'rgba(255, 255, 255, 0.04)',
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
    <Box sx={{ minHeight: '100vh', backgroundColor: '#0D1B13', display: 'flex' }}>
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
