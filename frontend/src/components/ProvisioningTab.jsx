import React, { useCallback, useEffect, useState, useMemo } from 'react';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Grid,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Stack,
  Step,
  StepContent,
  StepLabel,
  Stepper,
  TextField,
  Typography,
  Link as MuiLink,
  Tooltip,
  Skeleton,
  Paper,
  alpha,
  useTheme,
} from '@mui/material';
import {
  ContentCopy as CopyIcon,
  Add as AddIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Info as InfoIcon,
  Stop as StopIcon,
  OpenInNew as OpenInNewIcon,
  Refresh as RefreshIcon,
  Cloud as CloudIcon,
  Security as SecurityIcon,
  Terminal as TerminalIcon,
  PlayArrow as PlayIcon,
  Warning as WarningIcon,
} from '@mui/icons-material';
import apiService from '../services/api';

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

const CodeBlock = React.memo(({ code, onCopy, sx = {} }) => {
  const theme = useTheme();
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    onCopy(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Box
      sx={{
        bgcolor: '#1e1e1e',
        color: '#d4d4d4',
        p: 2.5,
        pr: 6, // Extra padding on right for copy button
        borderRadius: 2,
        fontFamily: 'monospace',
        fontSize: '0.875rem',
        position: 'relative',
        wordBreak: 'break-all',
        border: `1px solid ${alpha('#3e3e3e', 0.5)}`,
        transition: 'all 0.2s ease',
        '&:hover': {
          borderColor: alpha(theme.palette.primary.main, 0.5),
        },
        ...sx,
      }}
    >
      <code style={{ color: '#d4d4d4', display: 'block', wordBreak: 'break-all' }}>{code}</code>
      <Tooltip title={copied ? 'Copied!' : 'Copy to clipboard'} arrow>
        <IconButton
          size="small"
          onClick={handleCopy}
          sx={{
            position: 'absolute',
            right: 8,
            top: 8,
            color: '#d4d4d4',
            '&:hover': {
              bgcolor: alpha('#3e3e3e', 0.8),
              color: theme.palette.primary.main,
            },
          }}
        >
          <CopyIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Box>
  );
});

CodeBlock.displayName = 'CodeBlock';

const StatusChip = React.memo(({ status, phase, loading }) => {
  const getStatusColor = (status) => {
    switch (status) {
      case 'healthy': return 'success';
      case 'error': return 'error';
      case 'warning': return 'warning';
      default: return 'default';
    }
  };

  const getPhaseLabel = (phase) => {
    switch (phase) {
      case 'installing': return 'Installing Prerequisites';
      case 'deploying': return 'Deploying Stack';
      case 'running': return 'Running';
      default: return phase || 'Unknown';
    }
  };

  if (loading) {
    return <CircularProgress size={16} />;
  }

  if (!status) {
    return <Chip label="Not Running" color="default" size="small" />;
  }

  return (
    <Chip
      label={getPhaseLabel(phase)}
      color={getStatusColor(status)}
      size="small"
      icon={status === 'healthy' ? <CheckCircleIcon /> : <ErrorIcon />}
    />
  );
});

StatusChip.displayName = 'StatusChip';

const InfoCard = React.memo(({ icon: Icon, title, subtitle, children, color = 'primary', sx = {} }) => {
  const theme = useTheme();
  
  return (
    <Card
      sx={{
        borderRadius: 3,
        border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
        transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
        '&:hover': {
          boxShadow: theme.shadows[4],
        },
        ...sx,
      }}
    >
      <CardHeader
        avatar={
          <Box
            sx={{
              p: 1.5,
              borderRadius: 2,
              backgroundColor: alpha(theme.palette[color].main, 0.1),
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon sx={{ color: theme.palette[color].main, fontSize: 24 }} />
          </Box>
        }
        title={
          <Typography variant="h6" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
        }
        subheader={subtitle && (
          <Typography variant="body2" color="text.secondary">
            {subtitle}
          </Typography>
        )}
      />
      {children && <CardContent sx={{ pt: 0 }}>{children}</CardContent>}
    </Card>
  );
});

InfoCard.displayName = 'InfoCard';

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const ProvisioningTab = ({ instanceData, onNavigateToInstances, onNavigateToTelemetry }) => {
  const theme = useTheme();
  const [instance, setInstance] = useState(instanceData || null);
  const [apiKeys, setApiKeys] = useState([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [createKeyDialogOpen, setCreateKeyDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyDescription, setNewKeyDescription] = useState('');
  const [creatingKey, setCreatingKey] = useState(false);
  const [newKey, setNewKey] = useState(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [agentStatus, setAgentStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [runs, setRuns] = useState([]);
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [selectedApiKey, setSelectedApiKey] = useState(null);
  const [prerequisites, setPrerequisites] = useState([]);
  const [prerequisitesLoading, setPrerequisitesLoading] = useState(false);

  const instanceId = instance?.id || instance?.instanceId || instance?.instance_id || instance?.name || '';
  const INSTALL_URL = 'https://omniference.com/install';

  // Keep instance in sync when navigating from Manage Instances
  useEffect(() => {
    if (instanceData) {
      setInstance(instanceData);
    }
  }, [instanceData]);

  // Poll agent status
  useEffect(() => {
    if (instanceId) {
      fetchAgentStatus();
      fetchRuns();
      const interval = setInterval(() => {
        fetchAgentStatus();
        fetchRuns();
      }, 10000);
      return () => clearInterval(interval);
    }
  }, [instanceId]);

  const fetchAgentStatus = useCallback(async () => {
    if (!instanceId) return;
    setLoadingStatus(true);
    try {
      const response = await apiService.getAgentStatusByInstance(instanceId);
      setAgentStatus(response);
    } catch (err) {
      if (err?.response?.status !== 404) {
        console.error('Failed to fetch agent status', err);
      }
      setAgentStatus(null);
    } finally {
      setLoadingStatus(false);
    }
  }, [instanceId]);

  const fetchRuns = useCallback(async () => {
    if (!instanceId) return;
    try {
      const response = await apiService.listTelemetryRuns({ instance_id: instanceId, limit: 5 });
      // listTelemetryRuns returns {runs: [...]}, not just an array
      const fetchedRuns = response?.runs || response || [];
      setRuns(fetchedRuns);
    } catch (err) {
      console.error('Failed to fetch runs', err);
    }
  }, [instanceId]);

  const fetchAPIKeys = useCallback(async () => {
    setKeysLoading(true);
    try {
      const response = await apiService.listAPIKeys(false);
      setApiKeys(response || []);
      if (response && response.length > 0 && !selectedApiKey) {
        setSelectedApiKey(response[0]);
      }
    } catch (err) {
      console.error('Failed to fetch API keys', err);
      setError(err?.response?.data?.detail || err?.message || 'Failed to fetch API keys');
    } finally {
      setKeysLoading(false);
    }
  }, [selectedApiKey]);

  useEffect(() => {
    fetchAPIKeys();
  }, [fetchAPIKeys]);

  useEffect(() => {
    const fetchPrerequisites = async () => {
      setPrerequisitesLoading(true);
      try {
        const response = await apiService.getTelemetryPrerequisites();
        const prereqs = response?.prerequisites || [];
        setPrerequisites(prereqs);
      } catch (err) {
        console.error('Failed to load prerequisites', err);
        setPrerequisites([]);
      } finally {
        setPrerequisitesLoading(false);
      }
    };
    fetchPrerequisites();
  }, []);

  const handleCreateAPIKey = useCallback(async () => {
    if (!newKeyName.trim()) {
      setError('API key name is required');
      return;
    }

    setCreatingKey(true);
    setError('');
    setMessage('');

    try {
      const response = await apiService.createAPIKey(newKeyName, newKeyDescription || null);
      setNewKey(response);
      setSelectedApiKey(response);
      setCreateKeyDialogOpen(false);
      setNewKeyName('');
      setNewKeyDescription('');
      await fetchAPIKeys();
    } catch (err) {
      console.error('Failed to create API key', err);
      setError(err?.response?.data?.detail || err?.message || 'Failed to create API key');
    } finally {
      setCreatingKey(false);
    }
  }, [newKeyName, newKeyDescription, fetchAPIKeys]);

  const handleRevokeAPIKey = useCallback(async (keyId) => {
    if (!window.confirm('Are you sure you want to revoke this API key? It will no longer work.')) {
      return;
    }

    try {
      await apiService.revokeAPIKey(keyId);
      setMessage('API key revoked successfully');
      if (selectedApiKey?.key_id === keyId) {
        setSelectedApiKey(null);
      }
      await fetchAPIKeys();
    } catch (err) {
      console.error('Failed to revoke API key', err);
      setError(err?.response?.data?.detail || err?.message || 'Failed to revoke API key');
    }
  }, [fetchAPIKeys, selectedApiKey]);

  const handleStopAgent = useCallback(async () => {
    if (!agentStatus?.run_id) {
      setError('No active run found to stop');
      return;
    }

    setStopping(true);
    setError('');
    try {
      const response = await apiService.stopAgent(instanceId, agentStatus.run_id);
      setMessage(response.message || 'Run marked as stopped. See instructions below to stop the agent service on the GPU instance.');
      setStopDialogOpen(false);
      
      if (response.instructions) {
        const instructions = `To stop the agent service and containers on your GPU instance, SSH into it and run:\n\n${response.instructions.stop_agent}\n${response.instructions.stop_containers}`;
        setTimeout(() => {
          alert(instructions);
        }, 500);
      }
      
      setTimeout(() => {
        fetchAgentStatus();
        fetchRuns();
      }, 2000);
    } catch (err) {
      console.error('Failed to stop agent', err);
      setError(err?.response?.data?.detail || err?.message || 'Failed to stop agent');
    } finally {
      setStopping(false);
    }
  }, [agentStatus, instanceId, fetchAgentStatus, fetchRuns]);

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    setMessage('Copied to clipboard!');
    setTimeout(() => setMessage(''), 3000);
  };

  const activeRun = runs.find(r => r.status === 'active');
  const hasMetrics = activeRun && agentStatus?.phase === 'running' && agentStatus?.status === 'healthy';
  const apiKeyToUse = selectedApiKey?.api_key || newKey?.api_key || 'YOUR_API_KEY';
  const installCommand = `curl -fsSL ${INSTALL_URL} | sudo bash -s -- --api-key=${apiKeyToUse} --instance-id=${instanceId}`;

  const activeStep = useMemo(() => {
    if (hasMetrics) return 3;
    if (agentStatus) return 2;
    if (apiKeys.length > 0) return 1;
    return 0;
  }, [hasMetrics, agentStatus, apiKeys.length]);

  return (
    <Box sx={{ p: { xs: 2, sm: 3, md: 4 } }}>
      {/* Header */}
      {instance && (
        <Card
          sx={{
            mb: 4,
            borderRadius: 3,
            border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
            background: `linear-gradient(135deg, ${alpha(theme.palette.primary.main, 0.05)} 0%, ${alpha(theme.palette.primary.main, 0.02)} 100%)`,
          }}
        >
          <CardContent sx={{ p: 3 }}>
            <Stack 
              direction={{ xs: 'column', sm: 'row' }} 
              justifyContent="space-between" 
              alignItems={{ xs: 'flex-start', sm: 'center' }}
              spacing={2}
              sx={{ mb: 3 }}
            >
              <Stack direction="row" spacing={2} alignItems="center">
                <Box
                  sx={{
                    p: 1.5,
            borderRadius: 2,
                    backgroundColor: alpha(theme.palette.primary.main, 0.1),
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <CloudIcon sx={{ color: theme.palette.primary.main, fontSize: 28 }} />
                </Box>
                <Box>
                  <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>
                    Agent Provisioning
            </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Set up monitoring and profiling for your GPU instance
                  </Typography>
                </Box>
              </Stack>
              <Stack direction="row" spacing={1.5}>
              {onNavigateToTelemetry && hasMetrics && (
                <Button
                  variant="contained"
                  color="primary"
                  startIcon={<OpenInNewIcon />}
                  onClick={() => onNavigateToTelemetry(instanceId, activeRun?.run_id)}
                    sx={{ borderRadius: 2 }}
                >
                  View Metrics
                </Button>
              )}
              {onNavigateToInstances && (
                  <Button 
                    variant="outlined"
                    onClick={onNavigateToInstances}
                    sx={{ borderRadius: 2 }}
                  >
                  Back to Instances
                </Button>
              )}
            </Stack>
          </Stack>
            
            <Grid container spacing={3}>
              <Grid item xs={12} sm={6} md={3}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Instance ID
              </Typography>
                  <Typography variant="body1" sx={{ fontFamily: 'monospace', fontSize: '0.9rem', mt: 0.5, fontWeight: 500 }}>
                {instance.id || instance.instanceId || instance.instance_id || 'N/A'}
              </Typography>
                </Box>
            </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Name
              </Typography>
                  <Typography variant="body1" sx={{ mt: 0.5, fontWeight: 500 }}>
                {instance.name || instance.displayName || 'Unnamed'}
              </Typography>
                </Box>
            </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                IP / Host
              </Typography>
                  <Typography variant="body1" sx={{ fontFamily: 'monospace', mt: 0.5, fontWeight: 500 }}>
                {instance.ipAddress || instance.ip || 'N/A'}
              </Typography>
                </Box>
            </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Agent Status
              </Typography>
                  <Box sx={{ mt: 0.5 }}>
                    <StatusChip 
                      status={agentStatus?.status} 
                      phase={agentStatus?.phase} 
                      loading={loadingStatus}
                />
                  </Box>
                </Box>
            </Grid>
          </Grid>
          </CardContent>
        </Card>
      )}

      {/* Alerts */}
      {message && (
        <Alert 
          severity="success" 
          sx={{ mb: 3, borderRadius: 2 }} 
          onClose={() => setMessage('')}
          icon={<CheckCircleIcon />}
        >
          {message}
        </Alert>
      )}
      {error && (
        <Alert 
          severity="error" 
          sx={{ mb: 3, borderRadius: 2 }} 
          onClose={() => setError('')}
          icon={<ErrorIcon />}
        >
          {error}
        </Alert>
      )}

      {/* Prerequisites Card */}
      {(prerequisitesLoading || prerequisites.length > 0) && (
        <InfoCard
          icon={InfoIcon}
          title="Prerequisites"
          subtitle="Required before starting agent provisioning"
          color="info"
          sx={{ mb: 3 }}
        >
            {prerequisitesLoading ? (
            <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 2 }}>
                <CircularProgress size={20} />
                <Typography variant="body2" color="text.secondary">
                  Loading prerequisites...
                </Typography>
            </Stack>
            ) : (
              <>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                  The following must be set up on your GPU instance before using agent provisioning. 
                  The agent will automatically install Docker, NVIDIA Container Toolkit, DCGM, and Fabric Manager during installation.
                </Typography>
              <Stack spacing={2}>
                  {prerequisites.map((prereq) => (
                  <Paper
                    key={prereq.id}
                    sx={{
                      p: 2,
                      borderRadius: 2,
                      border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
                      backgroundColor: alpha(theme.palette.background.paper, 0.5),
                    }}
                  >
                    <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                        {prereq.title}
                      </Typography>
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                        {prereq.description}
                      </Typography>
                      {prereq.install_hint && (
                      <CodeBlock
                        code={prereq.install_hint}
                        onCopy={copyToClipboard}
                        sx={{ mt: 1, fontSize: '0.75rem', p: 1.5 }}
                      />
                      )}
                      {prereq.docs_link && (
                        <MuiLink
                          href={prereq.docs_link}
                          target="_blank"
                          rel="noopener noreferrer"
                          variant="caption"
                        sx={{ 
                          display: 'inline-flex', 
                          alignItems: 'center', 
                          mt: 1,
                          fontWeight: 500,
                        }}
                        >
                        View Documentation <OpenInNewIcon sx={{ fontSize: 14, ml: 0.5 }} />
                        </MuiLink>
                      )}
                  </Paper>
                  ))}
              </Stack>
              <Alert severity="info" sx={{ mt: 3, borderRadius: 2 }}>
                  <Typography variant="body2">
                    <strong>What the agent installs automatically:</strong> Docker, NVIDIA Container Toolkit, DCGM, Fabric Manager
                  </Typography>
                </Alert>
              </>
            )}
        </InfoCard>
      )}

      {/* Agent Status Card */}
      {agentStatus && (
        <Card
          sx={{
            mb: 3,
            borderRadius: 3,
            border: `2px solid ${agentStatus.status === 'healthy' ? theme.palette.success.main : alpha(theme.palette.divider, 0.1)}`,
            transition: 'all 0.3s ease',
          }}
        >
          <CardHeader
            title={
              <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                <Typography variant="h6" sx={{ fontWeight: 600 }}>
                  Agent Status
                </Typography>
                <Chip
                  label={agentStatus.status}
                  color={agentStatus.status === 'healthy' ? 'success' : agentStatus.status === 'error' ? 'error' : 'warning'}
                  size="small"
                  icon={agentStatus.status === 'healthy' ? <CheckCircleIcon /> : <ErrorIcon />}
                />
                {agentStatus.phase === 'running' && (
                  <Button
                    variant="outlined"
                    color="error"
                    size="small"
                    startIcon={<StopIcon />}
                    onClick={() => setStopDialogOpen(true)}
                    sx={{ borderRadius: 2 }}
                  >
                    Stop Agent
                  </Button>
                )}
              </Stack>
            }
            action={
              <Tooltip title="Refresh status" arrow>
                <IconButton 
                  onClick={fetchAgentStatus} 
                  size="small"
                  sx={{
                    '&:hover': {
                      backgroundColor: alpha(theme.palette.primary.main, 0.1),
                    },
                  }}
                >
                <RefreshIcon />
              </IconButton>
              </Tooltip>
            }
          />
          <CardContent>
            <Grid container spacing={3}>
              <Grid item xs={12} md={4}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    Phase
                  </Typography>
                  <Typography variant="body1" sx={{ mt: 0.5, fontWeight: 500 }}>
                    {agentStatus.phase === 'installing' ? 'Installing Prerequisites' :
                     agentStatus.phase === 'deploying' ? 'Deploying Stack' :
                     agentStatus.phase === 'running' ? 'Running' : agentStatus.phase}
                  </Typography>
                </Box>
              </Grid>
              <Grid item xs={12} md={4}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    Message
                  </Typography>
                  <Typography variant="body1" sx={{ mt: 0.5, fontWeight: 500 }}>
                    {agentStatus.message || 'No message'}
                  </Typography>
                </Box>
              </Grid>
              <Grid item xs={12} md={4}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    Last Heartbeat
                  </Typography>
                  <Typography variant="body1" sx={{ mt: 0.5, fontWeight: 500 }}>
                  {agentStatus.timestamp ? new Date(agentStatus.timestamp).toLocaleString() : 'Never'}
                </Typography>
                </Box>
              </Grid>
            </Grid>
            {hasMetrics && (
              <Alert 
                severity="success" 
                sx={{ mt: 3, borderRadius: 2 }}
                icon={<CheckCircleIcon />}
              >
                <AlertTitle sx={{ fontWeight: 600 }}>Metrics Available!</AlertTitle>
                <Typography variant="body2">
                  Your telemetry stack is running and sending metrics. 
                  {onNavigateToTelemetry && (
                    <>
                      {' '}
                      <MuiLink
                        component="button"
                        variant="body2"
                        onClick={() => onNavigateToTelemetry(instanceId, activeRun?.run_id)}
                        sx={{ 
                          textDecoration: 'underline', 
                          cursor: 'pointer',
                          fontWeight: 600,
                        }}
                      >
                        View charts in Telemetry tab →
                      </MuiLink>
                    </>
                  )}
                </Typography>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step-by-Step Installation Guide */}
      <Card
        sx={{
          mb: 3,
          borderRadius: 3,
          border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
        }}
      >
        <CardHeader 
          title={
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              Step-by-Step Installation Guide
            </Typography>
          }
          subheader="Follow these steps in order to set up agent provisioning"
        />
        <CardContent>
          <Stepper 
            orientation="vertical" 
            activeStep={activeStep}
            sx={{
              '& .MuiStepLabel-root': {
                '& .MuiStepLabel-label': {
                  fontWeight: 600,
                },
              },
            }}
          >
            {/* Step 1: Create API Key */}
            <Step>
              <StepLabel 
                optional={
                  apiKeys.length > 0 ? (
                    <Chip label="Complete" color="success" size="small" />
                  ) : (
                    <Typography variant="caption" color="text.secondary">Required</Typography>
                  )
                }
              >
                Step 1: Create API Key
              </StepLabel>
              <StepContent>
                <Typography variant="body2" sx={{ mb: 3, color: 'text.secondary' }}>
                  API keys are long-lived credentials for agent authentication. You only need to create one API key and can use it for all your instances.
                </Typography>
                {apiKeys.length === 0 ? (
                  <Button
                    variant="contained"
                    startIcon={<AddIcon />}
                    onClick={() => setCreateKeyDialogOpen(true)}
                    sx={{ borderRadius: 2, mb: 2 }}
                  >
                    Create Your First API Key
                  </Button>
                ) : (
                  <Alert severity="success" sx={{ mb: 2, borderRadius: 2 }}>
                    You have {apiKeys.length} API key{apiKeys.length > 1 ? 's' : ''} available. Select one to use in the next step.
                  </Alert>
                )}
              </StepContent>
            </Step>

            {/* Step 2: Install Agent */}
            <Step>
              <StepLabel 
                optional={
                  agentStatus ? (
                    <Chip label="Complete" color="success" size="small" />
                  ) : (
                    <Typography variant="caption" color="text.secondary">Required</Typography>
                  )
                }
              >
                Step 2: Install Agent on GPU Instance
              </StepLabel>
              <StepContent>
                <Typography variant="body2" sx={{ mb: 2, fontWeight: 600 }}>
                  Run this command on your GPU instance (SSH into it first):
                </Typography>
                
                {apiKeys.length === 0 ? (
                  <Alert severity="warning" sx={{ mb: 2, borderRadius: 2 }}>
                    Please create an API key first (Step 1).
                  </Alert>
                ) : (
                  <>
                    {!newKey && !selectedApiKey && (
                      <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
                        Select an API key below or create a new one to see the install command.
                      </Alert>
                    )}
                    
                    <CodeBlock
                      code={installCommand}
                      onCopy={copyToClipboard}
                      sx={{ mb: 3 }}
                    />

                    <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
                      <AlertTitle sx={{ fontWeight: 600 }}>What this command does:</AlertTitle>
                        <Box component="ul" sx={{ mt: 1, mb: 0, pl: 2 }}>
                          <li>Checks for NVIDIA driver (nvidia-smi)</li>
                          <li>Installs Docker if not present</li>
                          <li>Installs NVIDIA Container Toolkit</li>
                          <li>Downloads and installs the agent binary</li>
                          <li>Registers the instance with the backend</li>
                          <li>Deploys the monitoring stack (Prometheus, exporters)</li>
                          <li>Creates and starts the agent service</li>
                        </Box>
                    </Alert>

                    <Alert severity="warning" sx={{ borderRadius: 2 }}>
                      <AlertTitle sx={{ fontWeight: 600 }}>Important:</AlertTitle>
                      <Typography variant="body2">
                        You must run this command on the GPU instance itself (via SSH). 
                        Replace <code style={{ 
                          fontFamily: 'monospace', 
                          bgcolor: alpha(theme.palette.warning.main, 0.1), 
                          padding: '2px 6px', 
                          borderRadius: '4px',
                          fontWeight: 600,
                        }}>YOUR_API_KEY</code> with the actual API key you created.
                      </Typography>
                    </Alert>
                  </>
                )}
              </StepContent>
            </Step>

            {/* Step 3: Start Agent Service */}
            <Step>
              <StepLabel 
                optional={
                  agentStatus?.phase === 'running' ? (
                    <Chip label="Complete" color="success" size="small" />
                  ) : (
                    <Typography variant="caption" color="text.secondary">If needed</Typography>
                  )
                }
              >
                Step 3: Start Agent Service (if not auto-started)
              </StepLabel>
              <StepContent>
                <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
                  After installation, the agent service should start automatically. If it doesn't, run this command on your GPU instance:
                </Typography>
                
                <CodeBlock
                  code="sudo systemctl start omniference-agent"
                  onCopy={copyToClipboard}
                  sx={{ mb: 3 }}
                />

                <Alert severity="info" sx={{ borderRadius: 2 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                    To enable auto-start on boot:
                  </Typography>
                  <CodeBlock
                    code="sudo systemctl enable omniference-agent"
                    onCopy={copyToClipboard}
                    sx={{ fontSize: '0.85rem', p: 1.5 }}
                  />
                </Alert>
              </StepContent>
            </Step>

            {/* Step 4: View Metrics */}
            <Step>
              <StepLabel 
                optional={
                  hasMetrics ? (
                    <Chip label="Complete" color="success" size="small" />
                  ) : (
                    <Typography variant="caption" color="text.secondary">Automatic</Typography>
                  )
                }
              >
                Step 4: View Metrics
              </StepLabel>
              <StepContent>
                {hasMetrics ? (
                  <Alert severity="success" sx={{ borderRadius: 2 }}>
                    <AlertTitle sx={{ fontWeight: 600 }}>Metrics are flowing!</AlertTitle>
                    <Typography variant="body2">
                      Your telemetry stack is running and collecting GPU metrics. 
                      {onNavigateToTelemetry && (
                        <>
                          {' '}
                          <MuiLink
                            component="button"
                            variant="body2"
                            onClick={() => onNavigateToTelemetry(instanceId, activeRun?.run_id)}
                            sx={{ 
                              textDecoration: 'underline', 
                              cursor: 'pointer', 
                              fontWeight: 600,
                            }}
                          >
                            View charts in Telemetry tab →
                          </MuiLink>
                        </>
                      )}
                    </Typography>
                  </Alert>
                ) : agentStatus ? (
                  <Alert severity="info" sx={{ borderRadius: 2 }}>
                    <Typography variant="body2">
                      Agent is {agentStatus.phase === 'deploying' ? 'deploying' : 'starting'}. 
                      Metrics will appear here once the stack is running (usually within 1-2 minutes).
                    </Typography>
                  </Alert>
                ) : (
                  <Alert severity="info" sx={{ borderRadius: 2 }}>
                    <Typography variant="body2">
                      After installation and starting the agent, metrics will appear here automatically. 
                      The agent deploys Prometheus and exporters that collect GPU metrics (utilization, memory, power, temperature, SM activity, HBM bandwidth, NVLink throughput, etc.).
                    </Typography>
                  </Alert>
                )}
              </StepContent>
            </Step>
          </Stepper>
        </CardContent>
      </Card>

      {/* API Key Management */}
      <InfoCard
        icon={SecurityIcon}
          title="API Key Management"
        color="primary"
        sx={{ mb: 3 }}
      >
        <Stack direction="row" justifyContent="flex-end" sx={{ mb: 2 }}>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setCreateKeyDialogOpen(true)}
            sx={{ borderRadius: 2 }}
            >
              Create API Key
            </Button>
        </Stack>
          {keysLoading ? (
          <Box display="flex" justifyContent="center" p={3}>
              <CircularProgress size={24} />
            </Box>
          ) : apiKeys.length === 0 ? (
          <Alert severity="info" sx={{ borderRadius: 2 }}>
              No API keys found. Create one to get started with agent provisioning.
            </Alert>
          ) : (
          <Stack spacing={1.5}>
              {apiKeys.map((key) => (
              <Paper
                  key={key.key_id}
                  onClick={() => setSelectedApiKey(key)}
                  sx={{
                  p: 2,
                    cursor: 'pointer',
                  borderRadius: 2,
                  border: selectedApiKey?.key_id === key.key_id 
                    ? `2px solid ${theme.palette.primary.main}` 
                    : `1px solid ${alpha(theme.palette.divider, 0.1)}`,
                  backgroundColor: selectedApiKey?.key_id === key.key_id
                    ? alpha(theme.palette.primary.main, 0.05)
                    : 'transparent',
                  transition: 'all 0.2s ease',
                  '&:hover': {
                    backgroundColor: alpha(theme.palette.action.hover, 0.05),
                    borderColor: theme.palette.primary.main,
                  },
                  position: 'relative',
                }}
                    >
                <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between">
                  <Box sx={{ flex: 1 }}>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                      <Typography variant="body1" sx={{ fontWeight: 600 }}>
                          {key.name}
                        </Typography>
                        {selectedApiKey?.key_id === key.key_id && (
                          <Chip label="Selected" color="primary" size="small" />
                        )}
                      </Stack>
                    <Typography variant="caption" color="text.secondary">
                        Created: {new Date(key.created_at).toLocaleString()}
                        {key.last_used_at && (
                          <> • Last used: {new Date(key.last_used_at).toLocaleString()}</>
                        )}
                    </Typography>
                  </Box>
                  <IconButton
                    edge="end"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRevokeAPIKey(key.key_id);
                    }}
                    color="error"
                    size="small"
                    sx={{
                      '&:hover': {
                        backgroundColor: alpha(theme.palette.error.main, 0.1),
                      },
                    }}
                  >
                    <DeleteIcon />
                  </IconButton>
                </Stack>
              </Paper>
              ))}
          </Stack>
          )}
          {selectedApiKey && !newKey && (
          <Alert severity="info" sx={{ mt: 3, borderRadius: 2 }}>
              <Typography variant="body2">
                <strong>Selected API Key:</strong> {selectedApiKey.name}
                <br />
                Use this key in the install command above. If you need to see the key value again, you'll need to create a new key (keys are only shown once when created).
              </Typography>
            </Alert>
          )}
      </InfoCard>

      {/* Troubleshooting */}
      <InfoCard
        icon={TerminalIcon}
        title="Troubleshooting & Documentation"
        color="warning"
      >
        <Stack spacing={2.5}>
          <Alert severity="warning" sx={{ borderRadius: 2 }}>
            <AlertTitle sx={{ fontWeight: 600 }}>nvidia-smi not found</AlertTitle>
              <Typography variant="body2">
                Install the NVIDIA driver first:
              </Typography>
            <CodeBlock
              code="sudo apt update && sudo ubuntu-drivers install && sudo reboot"
              onCopy={copyToClipboard}
              sx={{ mt: 1.5, fontSize: '0.85rem', p: 1.5 }}
            />
            </Alert>

          <Alert severity="info" sx={{ borderRadius: 2 }}>
            <AlertTitle sx={{ fontWeight: 600 }}>Missing SM Utilization, HBM, and NVLink Metrics?</AlertTitle>
              <Typography variant="body2" component="div">
                These advanced metrics require DCGM (NVIDIA Data Center GPU Manager). Follow these steps on your GPU instance:
              <CodeBlock
                code={`cd /tmp && wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb && sudo dpkg -i cuda-keyring_1.1-1_all.deb && sudo apt update && sudo apt install -y datacenter-gpu-manager && sudo systemctl start dcgm && sudo systemctl enable dcgm && sudo curl -fsSL -o /usr/local/bin/provisioning-agent https://omniference.com/downloads/provisioning-agent-linux-amd64 && sudo chmod +x /usr/local/bin/provisioning-agent && sudo systemctl restart omniference-agent`}
                onCopy={copyToClipboard}
                sx={{ mt: 1.5, fontSize: '0.75rem', p: 1.5 }}
              />
              <Alert severity="warning" sx={{ mt: 1.5, borderRadius: 2 }}>
                  <Typography variant="body2">
                    <strong>Note:</strong> For Ubuntu 22.04, use <code>ubuntu2204</code> instead of <code>ubuntu2404</code> in the keyring URL.
                    For other distributions, check the <MuiLink href="https://developer.nvidia.com/cuda-downloads" target="_blank" rel="noopener">NVIDIA CUDA repository</MuiLink>.
                  </Typography>
                </Alert>
              <Typography variant="body2" sx={{ mt: 1.5 }}>
                  After installing DCGM and updating the agent binary, restart the agent. It will automatically detect DCGM and deploy the DCGM exporter, 
                  enabling SM utilization, HBM bandwidth, NVLink throughput, and other profiling metrics.
                </Typography>
              </Typography>
            </Alert>

          <Alert severity="info" sx={{ borderRadius: 2 }}>
            <AlertTitle sx={{ fontWeight: 600 }}>Check agent status</AlertTitle>
            <CodeBlock
              code="sudo systemctl status omniference-agent"
              onCopy={copyToClipboard}
              sx={{ mt: 1.5, fontSize: '0.85rem', p: 1.5 }}
            />
            </Alert>

          <Alert severity="info" sx={{ borderRadius: 2 }}>
            <AlertTitle sx={{ fontWeight: 600 }}>View agent logs</AlertTitle>
            <CodeBlock
              code="sudo journalctl -u omniference-agent -f"
              onCopy={copyToClipboard}
              sx={{ mt: 1.5, fontSize: '0.85rem', p: 1.5 }}
            />
            </Alert>

          <Alert severity="info" sx={{ borderRadius: 2 }}>
            <AlertTitle sx={{ fontWeight: 600 }}>Stop agent manually</AlertTitle>
              <Typography variant="body2">
                To stop the agent and remove all containers:
              </Typography>
            <CodeBlock
              code={`sudo systemctl stop omniference-agent\nsudo docker compose -f /tmp/gpu-telemetry-${instanceId}/docker-compose.yml down`}
              onCopy={copyToClipboard}
              sx={{ mt: 1.5, fontSize: '0.85rem', p: 1.5, whiteSpace: 'pre' }}
            />
            </Alert>
          </Stack>
      </InfoCard>

      {/* Create API Key Dialog */}
      <Dialog 
        open={createKeyDialogOpen} 
        onClose={() => setCreateKeyDialogOpen(false)} 
        maxWidth="sm" 
        fullWidth
        PaperProps={{
          sx: { borderRadius: 3 }
        }}
      >
        <DialogTitle sx={{ fontWeight: 600 }}>Create API Key</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 3 }}>
            Create a new API key for agent authentication. The key will be shown only once - make sure to copy it!
          </DialogContentText>
          <TextField
            autoFocus
            margin="dense"
            label="Name"
            fullWidth
            variant="outlined"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            sx={{ mb: 2 }}
            required
            placeholder="e.g., Production Key, Development Key"
          />
          <TextField
            margin="dense"
            label="Description (optional)"
            fullWidth
            variant="outlined"
            multiline
            rows={3}
            value={newKeyDescription}
            onChange={(e) => setNewKeyDescription(e.target.value)}
            placeholder="Optional description for this API key"
          />
        </DialogContent>
        <DialogActions sx={{ p: 2.5 }}>
          <Button 
            onClick={() => setCreateKeyDialogOpen(false)}
            sx={{ borderRadius: 2 }}
          >
            Cancel
          </Button>
          <Button 
            onClick={handleCreateAPIKey} 
            variant="contained" 
            disabled={creatingKey || !newKeyName.trim()}
            sx={{ borderRadius: 2 }}
          >
            {creatingKey ? 'Creating...' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Show API Key Dialog (after creation) */}
      <Dialog 
        open={!!newKey} 
        onClose={() => setNewKey(null)} 
        maxWidth="sm" 
        fullWidth
        PaperProps={{
          sx: { borderRadius: 3 }
        }}
      >
        <DialogTitle sx={{ fontWeight: 600 }}>API Key Created Successfully!</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 3, borderRadius: 2 }}>
            <AlertTitle sx={{ fontWeight: 600 }}>Important: Copy This Key Now</AlertTitle>
            This API key will only be shown once. Copy it now and store it securely. You'll need it for the install command.
          </Alert>
          <Typography variant="subtitle2" sx={{ mb: 1.5, fontWeight: 600 }}>
            API Key:
          </Typography>
          <CodeBlock
            code={newKey?.api_key || ''}
            onCopy={copyToClipboard}
            sx={{ mb: 2 }}
          />
          <Alert severity="info" sx={{ borderRadius: 2 }}>
            <Typography variant="body2">
              This key has been automatically selected for use in the install command. You can use it in Step 2 above.
            </Typography>
          </Alert>
        </DialogContent>
        <DialogActions sx={{ p: 2.5 }}>
          <Button 
            onClick={() => setNewKey(null)} 
            variant="contained" 
            fullWidth
            sx={{ borderRadius: 2 }}
          >
            I've Copied It - Continue to Step 2
          </Button>
        </DialogActions>
      </Dialog>

      {/* Stop Agent Dialog */}
      <Dialog 
        open={stopDialogOpen} 
        onClose={() => setStopDialogOpen(false)} 
        maxWidth="sm" 
        fullWidth
        PaperProps={{
          sx: { borderRadius: 3 }
        }}
      >
        <DialogTitle sx={{ fontWeight: 600 }}>Stop Agent Monitoring</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 3 }}>
            This will mark the run as stopped in the database. However, to actually stop the agent service 
            and containers on your GPU instance, you need to SSH into the instance and run the commands below.
          </DialogContentText>
          <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
            <AlertTitle sx={{ fontWeight: 600 }}>Manual Steps Required</AlertTitle>
            <Typography variant="body2" component="div">
              After clicking "Mark as Stopped", SSH into your GPU instance and run:
              <CodeBlock
                code={`sudo systemctl stop omniference-agent\nsudo docker compose -f /tmp/gpu-telemetry-${instanceId}/docker-compose.yml down`}
                onCopy={copyToClipboard}
                sx={{ mt: 1.5, fontSize: '0.85rem', p: 1.5, whiteSpace: 'pre' }}
              />
            </Typography>
          </Alert>
          <Alert severity="warning" sx={{ borderRadius: 2 }}>
            <AlertTitle sx={{ fontWeight: 600 }}>Note</AlertTitle>
            You can restart monitoring by running the install command again. The agent is idempotent and safe to reinstall.
          </Alert>
        </DialogContent>
        <DialogActions sx={{ p: 2.5 }}>
          <Button 
            onClick={() => setStopDialogOpen(false)}
            sx={{ borderRadius: 2 }}
          >
            Cancel
          </Button>
          <Button 
            onClick={handleStopAgent} 
            variant="contained" 
            color="error" 
            disabled={stopping}
            sx={{ borderRadius: 2 }}
          >
            {stopping ? 'Marking as Stopped...' : 'Mark as Stopped'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default ProvisioningTab;
