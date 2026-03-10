import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { Box, Toolbar, Button, Avatar, Typography, Drawer, List, ListItem, ListItemButton, ListItemIcon, ListItemText, IconButton, Menu, MenuItem, CircularProgress } from '@mui/material';
import { Dashboard as DashboardIcon, Assessment as AssessmentIcon, Cloud, History as HistoryIcon, Logout, Person } from '@mui/icons-material';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { UIProvider } from './components/ui/UIProvider';
import CommandPalette from './components/ui/CommandPalette';
import Benchmarking from './pages/Benchmarking';
import ManageInstances from './pages/ManageInstances';
import TelemetryHistory from './components/TelemetryHistory';
import LoginPage from './pages/Login';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#0879f4',
    },
    secondary: {
      main: '#dc004e',
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
      main: '#616161',
      contrastText: '#fff',
    },
    background: {
      default: '#f6f7f9',
      paper: '#ffffff',
    },
    text: {
      primary: '#373737',
      secondary: '#919191',
    },
  },
  typography: {
    fontFamily: '"Open Sans", "Roboto", "Helvetica", "Arial", sans-serif',
    h1: {
      fontFamily: '"Open Sans", sans-serif',
      fontWeight: 600,
      fontSize: '24px',
      color: '#373737',
    },
    h2: {
      fontFamily: '"Open Sans", sans-serif',
      fontWeight: 600,
      fontSize: '20px',
      color: '#373737',
    },
    h3: {
      fontFamily: '"Open Sans", sans-serif',
      fontWeight: 600,
      fontSize: '18px',
      color: '#373737',
    },
    h4: {
      fontFamily: '"Open Sans", sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#373737',
    },
    h5: {
      fontFamily: '"Open Sans", sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#373737',
    },
    h6: {
      fontFamily: '"Open Sans", sans-serif',
      fontWeight: 600,
      fontSize: '16px',
      color: '#373737',
    },
    body1: {
      fontFamily: '"Open Sans", sans-serif',
      fontSize: '14px',
      color: '#373737',
      fontWeight: 400,
    },
    body2: {
      fontFamily: '"Open Sans", sans-serif',
      fontSize: '12px',
      color: '#373737',
      fontWeight: 400,
    },
    button: {
      fontFamily: '"Inter", "Open Sans", sans-serif',
      fontWeight: 500,
      fontSize: '14px',
      textTransform: 'none',
    },
    caption: {
      fontFamily: '"Open Sans", sans-serif',
      fontSize: '12px',
      color: '#919191',
      fontWeight: 400,
    },
    subtitle1: {
      fontFamily: '"Open Sans", sans-serif',
      fontSize: '14px',
      color: '#373737',
    },
    subtitle2: {
      fontFamily: '"Open Sans", sans-serif',
      fontSize: '12px',
      color: '#373737',
    },
  },
  components: {
    MuiButton: {
      defaultProps: {
        color: 'primary',
      },
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontFamily: '"Inter", "Open Sans", sans-serif',
          fontWeight: 500,
          borderRadius: '8px',
          fontSize: '14px',
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
          boxShadow: '0.5px 0.5px 1px 0px rgba(0,0,0,0.1)',
          borderRadius: '8px',
          backgroundColor: '#ffffff',
          border: '1px solid rgba(0,0,0,0.1)',
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: '8px',
            fontSize: '14px',
            fontFamily: '"Open Sans", sans-serif',
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontFamily: '"Open Sans", sans-serif',
          fontSize: '12px',
          borderRadius: '4px',
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: '"Open Sans", sans-serif',
          fontSize: '10px',
          fontWeight: 400,
          textTransform: 'none',
          minHeight: 'auto',
          padding: '3px 10px',
        },
      },
    },
    MuiTypography: {
      styleOverrides: {
        root: {
          fontFamily: '"Open Sans", sans-serif',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: '8px',
          border: '1px solid rgba(0,0,0,0.1)',
        },
        elevation1: {
          boxShadow: '0.5px 0.5px 1px 0px rgba(0,0,0,0.1)',
        },
        elevation2: {
          boxShadow: '0.5px 0.5px 1px 0px rgba(0,0,0,0.1)',
        },
        elevation3: {
          boxShadow: '0.5px 0.5px 1px 0px rgba(0,0,0,0.1)',
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: '8px',
          fontFamily: '"Open Sans", sans-serif',
          fontSize: '14px',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: '8px',
          border: '1px solid #d7d7d7',
        },
      },
    },
    MuiTable: {
      styleOverrides: {
        root: {
          fontFamily: '"Open Sans", sans-serif',
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          fontFamily: '"Open Sans", sans-serif',
          fontSize: '14px',
        },
        head: {
          fontFamily: '"Open Sans", sans-serif',
          fontSize: '12px',
          fontWeight: 600,
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          fontFamily: '"Open Sans", sans-serif',
          fontSize: '14px',
          borderRadius: '8px',
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          fontFamily: '"Open Sans", sans-serif',
          fontSize: '14px',
        },
      },
    },
    MuiFormControlLabel: {
      styleOverrides: {
        label: {
          fontFamily: '"Open Sans", sans-serif',
          fontSize: '14px',
        },
      },
    },
    MuiAccordion: {
      styleOverrides: {
        root: {
          borderRadius: '8px',
          border: '1px solid rgba(0,0,0,0.1)',
          '&:before': {
            display: 'none',
          },
        },
      },
    },
  },
});

const drawerWidth = 260;

function SidebarNavigation() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const menuItems = [
    { text: 'Profiling', icon: <AssessmentIcon />, path: '/profiling' },
    { text: 'Manage Instances', icon: <Cloud />, path: '/instances' },
    { text: 'Telemetry History', icon: <HistoryIcon />, path: '/telemetry-history' }
  ];

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: drawerWidth,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: drawerWidth,
          boxSizing: 'border-box',
          backgroundColor: '#FFFFFF',
          borderRight: '1px solid #E0E0E0',
          position: 'fixed',
          height: '100vh',
          top: 0,
          left: 0,
          zIndex: 1200,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column'
        },
      }}
    >
      <Box sx={{ 
        height: '100%', 
        display: 'flex', 
        flexDirection: 'column',
        backgroundColor: '#FFFFFF'
      }}>
        {/* Header */}
        <Box sx={{ p: 3, pb: 2.5, borderBottom: '1px solid #E0E0E0' }}>
          <Box sx={{ 
            height: '40px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-start'
          }}>
            <img 
              src="/runara-logo.png?v=2"
              alt="Runara Logo" 
              style={{ 
                height: '100%', 
                width: 'auto',
                objectFit: 'contain',
                display: 'block'
              }}
            />
          </Box>
        </Box>

        {/* Navigation Items */}
        <List sx={{ flex: 1, py: 3, px: 2, overflowY: 'auto' }}>
          {menuItems.map((item) => (
            <ListItem key={item.text} disablePadding sx={{ mb: 0.5 }}>
              <ListItemButton
                onClick={() => navigate(item.path)}
                sx={{
                  borderRadius: 2,
                  py: 1.5,
                  px: 2,
                  backgroundColor: location.pathname === item.path ? '#E8F0FE' : 'transparent',
                  '&:hover': {
                    backgroundColor: location.pathname === item.path ? '#D2E3FC' : '#F5F5F5'
                  },
                  transition: 'all 0.2s ease'
                }}
              >
                <ListItemIcon sx={{ 
                  color: location.pathname === item.path ? '#1976d2' : '#616161', 
                  minWidth: 44 
                }}>
                  {item.icon}
                </ListItemIcon>
                <ListItemText 
                  primary={item.text}
                  primaryTypographyProps={{
                    sx: { 
                      color: '#373737',
                      fontWeight: 400,
                      fontSize: '14px'
                    }
                  }} 
                />
              </ListItemButton>
            </ListItem>
          ))}
        </List>

        {/* User Actions - Account Button */}
        <Box sx={{ 
          borderTop: 'none', 
          pt: 0, 
          pb: 0,
          mt: 'auto',
          flexShrink: 0,
          px: '7px',
          mb: '40px'
        }}>
          <Button
            onClick={() => {
              // Show user info in alert for now
              alert(`Profile\nEmail: ${user?.email || 'N/A'}\nUser ID: ${user?.user_id || 'N/A'}`);
            }}
            sx={{
              borderRadius: '8px',
              py: '15px',
              px: '34px',
              gap: '15px',
              backgroundColor: '#f1efef',
              border: '1px solid #d9d9d9',
              width: '100%',
              justifyContent: 'flex-start',
              textTransform: 'none',
              height: '49px',
              '&:hover': {
                backgroundColor: '#e8e8e8'
              },
              transition: 'all 0.2s ease'
            }}
          >
            <Avatar 
              sx={{ 
                width: 20, 
                height: 20,
                bgcolor: '#FFFFFF',
                borderRadius: '100px',
                flexShrink: 0
              }}
            >
              {/* Profile image placeholder */}
            </Avatar>
            <Typography
              sx={{ 
                color: '#373737',
                fontWeight: 400,
                fontSize: '14px'
              }}
            >
              Account
            </Typography>
          </Button>
          
          {/* Logout Button - Matching style */}
          <Button
            onClick={handleLogout}
            sx={{
              borderRadius: '8px',
              py: '15px',
              px: '34px',
              gap: '15px',
              backgroundColor: '#f1efef',
              border: '1px solid #d9d9d9',
              width: '100%',
              justifyContent: 'flex-start',
              textTransform: 'none',
              height: '49px',
              mt: '8px',
              '&:hover': {
                backgroundColor: '#ffebee',
                borderColor: '#d32f2f'
              },
              transition: 'all 0.2s ease'
            }}
          >
            <ListItemIcon sx={{ 
              color: '#d32f2f', 
              minWidth: '20px',
              width: '20px',
              height: '20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Logout sx={{ fontSize: '20px' }} />
            </ListItemIcon>
            <Typography
              sx={{ 
                color: '#d32f2f',
                fontWeight: 400,
                fontSize: '14px'
              }}
            >
              Logout
            </Typography>
          </Button>
        </Box>

        {/* Footer */}
        <Box sx={{ 
          p: 0, 
          pt: 0, 
          textAlign: 'center', 
          borderTop: 'none',
          position: 'absolute',
          bottom: '8px',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '100%'
        }}>
          <Typography variant="caption" sx={{ 
            color: '#919191', 
            fontSize: '12px',
            display: 'block'
          }}>
            Product of Runara
          </Typography>
        </Box>
      </Box>
    </Drawer>
  );
}

function NavigationBar() {
  const { user, logout } = useAuth();
  const [anchorEl, setAnchorEl] = useState(null);
  const navigate = useNavigate();

  const handleAccountClick = (event) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
    handleClose();
  };

  const getInitials = (email) => {
    if (!email) return 'U';
    return email.charAt(0).toUpperCase();
  };

  if (!user) {
    return null; // Don't render if user is not loaded
  }

  return (
    <Box sx={{ 
      backgroundColor: '#FFFFFF',
      borderBottom: '1px solid #d7d7d7',
      borderTop: 'none',
      borderLeft: 'none',
      borderRight: 'none',
      boxShadow: 'none',
      position: 'fixed',
      top: 0,
      left: `${drawerWidth}px`,
      right: 0,
      zIndex: 1100,
      width: `calc(100% - ${drawerWidth}px)`,
      height: '65px'
    }}>
      <Toolbar sx={{ 
        py: 0, 
        px: '30px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        minHeight: '65px',
        height: '65px'
      }}>
        {/* Left Section - Logo and Company Name */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* Runara Logo */}
          <Box sx={{ 
            height: '36px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            position: 'relative',
            flexShrink: 0
          }}>
            <img 
              src="/runara-logo.png?v=2"
              alt="Runara Logo" 
              style={{ 
                height: '100%', 
                width: 'auto',
                objectFit: 'contain',
                display: 'block'
              }}
            />
          </Box>
          
          {/* DIO Text */}
          <Box sx={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '2px' }}>
            <Typography variant="h6" sx={{ 
              color: '#373737', 
              fontWeight: 600,
              fontSize: '16px',
              letterSpacing: '0',
              lineHeight: 1.2,
              margin: 0
            }}>
              DIO
            </Typography>
            <Typography variant="caption" sx={{ 
              color: 'rgba(55, 55, 55, 0.7)', 
              fontWeight: 400,
              fontSize: '11px',
              letterSpacing: '0',
              lineHeight: 1.2,
              margin: 0
            }}>
              deep inference optimization
            </Typography>
          </Box>
        </Box>

        {/* Right Section - Account Button */}
        <Box>
          <Button
            variant="outlined"
            onClick={handleAccountClick}
            startIcon={
              <Avatar 
                sx={{ 
                  width: 28, 
                  height: 28,
                  bgcolor: '#8D6E63',
                  fontSize: '0.75rem',
                  fontWeight: 600
                }}
              >
                {getInitials(user?.email)}
              </Avatar>
            }
            sx={{
              color: '#424242',
              borderColor: '#E0E0E0',
              backgroundColor: '#FFFFFF',
              borderRadius: '10px',
              px: 2.5,
              py: 1.25,
              textTransform: 'none',
              fontWeight: 500,
              fontSize: '0.9375rem',
              '&:hover': {
                backgroundColor: '#F5F5F5',
                borderColor: '#BDBDBD'
              }
            }}
          >
            {user?.email || 'Account'}
          </Button>
          <Menu
            anchorEl={anchorEl}
            open={Boolean(anchorEl)}
            onClose={handleClose}
          >
            <MenuItem onClick={handleLogout}>
              <Logout sx={{ mr: 1 }} />
              Logout
            </MenuItem>
          </Menu>
        </Box>
      </Toolbar>
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
    document.title = 'DIO';
    
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
    <Box sx={{ minHeight: '100vh', position: 'relative' }}>
      <SidebarNavigation />
      <Box
        component="main"
        sx={{
          position: 'absolute',
          top: 0,
          left: `${drawerWidth}px`,
          right: 0,
          bottom: 0,
          p: 0,
          m: 0,
          backgroundColor: '#FFFFFF',
          overflowY: 'auto'
        }}
      >
        <Routes>
          <Route path="/" element={<ProtectedRoute><Benchmarking /></ProtectedRoute>} />
          <Route path="/profiling" element={<ProtectedRoute><Benchmarking /></ProtectedRoute>} />
          <Route path="/instances" element={<ProtectedRoute><ManageInstances /></ProtectedRoute>} />
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
