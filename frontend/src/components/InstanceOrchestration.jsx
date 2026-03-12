import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  Box,
  Typography,
  LinearProgress,
  Stack,
  Chip,
  Paper,
  IconButton,
  Alert,
  Button,
  TextField,
  Grid,
  CircularProgress,
  Switch,
  FormControlLabel,
  Select,
  MenuItem,
  InputLabel,
  FormControl
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  RadioButtonUnchecked as RadioButtonUncheckedIcon,
  Close as CloseIcon,
  Refresh as RefreshIcon,
  Dashboard as DashboardIcon,
  Send as SendIcon
} from '@mui/icons-material';
import apiService from '../services/api';
import ModelSelector from './ModelSelector';

const PHASES = [
  { id: 'launch', label: 'Launching Instance', progress: 5 },
  { id: 'waiting_ip', label: 'Waiting for IP Address', progress: 15 },
  { id: 'setup', label: 'System Setup', progress: 20 },
  { id: 'model_deploy', label: 'Model Deployment', progress: 90 },
  { id: 'ready', label: 'Ready', progress: 100 }
];

export default function InstanceOrchestration({ open, onClose, orchestrationId, onStatusUpdate }) {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showModelSelector, setShowModelSelector] = useState(false);
  const intervalRef = useRef(null);
  const navigationTimeoutRef = useRef(null);
  
  // Test inference inputs
  const [testPrompt, setTestPrompt] = useState('');
  const [testResponse, setTestResponse] = useState(null);
  const [testLoading, setTestLoading] = useState(false);
  const [testError, setTestError] = useState(null);
  const [throughputMetrics, setThroughputMetrics] = useState(null);
  const [continuousRequests, setContinuousRequests] = useState(false);
  const [continuousInterval, setContinuousInterval] = useState(5); // seconds
  const continuousRequestRef = useRef(null);
  
  // Model configuration before navigation
  const [showConfigBeforeNavigate, setShowConfigBeforeNavigate] = useState(false);
  const [modelConfig, setModelConfig] = useState({
    inputTokens: 1024,
    maxTokens: 2048,
    temperature: 0.7
  });
  const [autoNavigateEnabled, setAutoNavigateEnabled] = useState(false);

  useEffect(() => {
    if (!open || !orchestrationId) {
      // Clear interval if dialog is closed
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      if (navigationTimeoutRef.current) {
        clearTimeout(navigationTimeoutRef.current);
        navigationTimeoutRef.current = null;
      }
      return;
    }

    const pollStatus = async () => {
      try {
        const data = await apiService.getOrchestrationStatus(orchestrationId);
        setStatus(data);
        setError(null);

        // Notify parent of status updates for full-screen loading
        if (onStatusUpdate) {
          onStatusUpdate(data);
        }

        // Auto-navigate to Run Workload when IP is available
        if (data.ip_address) {
          // Stop polling immediately
          if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
          // Small delay to show the success message
          navigationTimeoutRef.current = setTimeout(() => {
            const instanceData = {
              id: data.instance_id,
              instance_id: data.instance_id,
              ipAddress: data.ip_address,
              ip_address: data.ip_address,
              sshUser: data.ssh_user || 'ubuntu',
              ssh_user: data.ssh_user || 'ubuntu',
            };
            navigate('/profiling', {
              state: {
                openRunWorkload: true,
                instanceData
              }
            });
            onClose();
          }, 2000);
          return;
        }

        // Stop polling if failed
        if (data.status === 'failed') {
          if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
          return;
        }

        // Continue polling for: launching, waiting_ip, setting_up, deploying_model, or ready (no model yet)
      } catch (e) {
        console.error('Failed to fetch orchestration status:', e);
        setError(e.message || 'Failed to fetch status');
      }
    };

    // Clear any existing interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    // Poll immediately
    pollStatus();

    // Poll every 2 seconds
    intervalRef.current = setInterval(pollStatus, 2000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      if (navigationTimeoutRef.current) {
        clearTimeout(navigationTimeoutRef.current);
        navigationTimeoutRef.current = null;
      }
    };
  }, [open, orchestrationId, navigate, onClose, onStatusUpdate]);

  const getPhaseStatus = (phaseId) => {
    if (!status) return 'pending';
    
    const currentPhase = status.current_phase;
    const phaseIndex = PHASES.findIndex(p => p.id === phaseId);
    const currentIndex = PHASES.findIndex(p => p.id === currentPhase);
    
    if (phaseIndex < currentIndex) return 'completed';
    if (phaseIndex === currentIndex) return 'active';
    return 'pending';
  };

  const handleRefresh = async () => {
    if (!orchestrationId) return;
    setLoading(true);
    try {
      const data = await apiService.getOrchestrationStatus(orchestrationId);
      setStatus(data);
      setError(null);
    } catch (e) {
      setError(e.message || 'Failed to refresh status');
    } finally {
      setLoading(false);
    }
  };

  const handleTestInference = useCallback(async () => {
    if (!testPrompt.trim() || !status?.ip_address || !status?.model_deployed) {
      setTestError('Please enter a prompt and ensure model is deployed');
      return;
    }

    setTestLoading(true);
    setTestError(null);
    setTestResponse(null);
    setThroughputMetrics(null);

    try {
      const startTime = Date.now();
      
      // Use proxy endpoint to avoid Mixed Content errors (HTTPS -> HTTP)
      const data = await apiService.proxyInference(status.ip_address, {
        model: status.model_deployed,
        messages: [{ role: 'user', content: testPrompt }],
        max_tokens: modelConfig.inputTokens || 100,
        temperature: modelConfig.temperature || 0.7
      });

      const endTime = Date.now();
      const latency = (endTime - startTime) / 1000; // seconds
      const usage = data.usage || {};
      const tokensGenerated = usage.completion_tokens || 0;
      const tokensPerSecond = tokensGenerated > 0 ? (tokensGenerated / latency).toFixed(2) : '0.00';

      setTestResponse({
        content: data.choices?.[0]?.message?.content || 'No response',
        usage: usage
      });

      setThroughputMetrics({
        latency: latency.toFixed(3),
        tokensPerSecond,
        promptTokens: usage.prompt_tokens || 0,
        completionTokens: usage.completion_tokens || 0,
        totalTokens: usage.total_tokens || 0
      });
    } catch (e) {
      console.error('Test inference error:', e);
      setTestError(e.message || 'Failed to send inference request');
    } finally {
      setTestLoading(false);
    }
  }, [testPrompt, status?.ip_address, status?.model_deployed, modelConfig.inputTokens, modelConfig.temperature]);

  // Continuous request handling
  useEffect(() => {
    if (continuousRequests && status?.ip_address && status?.model_deployed && testPrompt.trim()) {
      // Send initial request immediately
      handleTestInference();
      
      // Set up interval for continuous requests
      continuousRequestRef.current = setInterval(() => {
        handleTestInference();
      }, continuousInterval * 1000);
      
      return () => {
        if (continuousRequestRef.current) {
          clearInterval(continuousRequestRef.current);
          continuousRequestRef.current = null;
        }
      };
    } else {
      // Stop continuous requests if conditions not met
      if (continuousRequestRef.current) {
        clearInterval(continuousRequestRef.current);
        continuousRequestRef.current = null;
      }
    }
  }, [continuousRequests, continuousInterval, handleTestInference, status?.ip_address, status?.model_deployed, testPrompt]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (continuousRequestRef.current) {
        clearInterval(continuousRequestRef.current);
      }
    };
  }, []);

  const toggleContinuousRequests = () => {
    if (!testPrompt.trim() || !status?.ip_address || !status?.model_deployed) {
      setTestError('Please enter a prompt and ensure model is deployed before starting continuous requests');
      return;
    }
    setContinuousRequests(!continuousRequests);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: 2
        }
      }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', pb: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 600 }}>
          Instance Orchestration
        </Typography>
        <Box>
          <IconButton size="small" onClick={handleRefresh} disabled={loading}>
            <RefreshIcon />
          </IconButton>
          <IconButton size="small" onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {status && (
          <>
            {/* Overall Progress */}
            <Box sx={{ mb: 4 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  Overall Progress
                </Typography>
                <Typography variant="body2" fontWeight="bold">
                  {status.progress}%
                </Typography>
              </Box>
              <LinearProgress 
                variant="determinate" 
                value={status.progress} 
                sx={{ height: 8, borderRadius: 1 }}
              />
            </Box>

            {/* Status Chip */}
            <Box sx={{ mb: 3 }}>
              <Chip
                label={status.status.toUpperCase()}
                color={
                  status.status === 'ready' ? 'success' :
                  status.status === 'failed' ? 'error' :
                  status.status === 'setting_up' || status.status === 'deploying_model' ? 'warning' :
                  'info'
                }
                sx={{ fontWeight: 600 }}
              />
            </Box>

            {/* Phase Timeline */}
            <Stack spacing={2} sx={{ mb: 3 }}>
              {PHASES.map((phase, idx) => {
                const phaseStatus = getPhaseStatus(phase.id);
                const isActive = phaseStatus === 'active';
                const isCompleted = phaseStatus === 'completed';

                return (
                  <Paper
                    key={phase.id}
                    variant="outlined"
                    sx={{
                      p: 2,
                      border: isActive ? 2 : 1,
                      borderColor: isActive ? 'primary.main' : 'divider',
                      backgroundColor: isActive ? 'primary.50' : 'background.paper'
                    }}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      {isCompleted ? (
                        <CheckCircleIcon color="success" />
                      ) : (
                        <RadioButtonUncheckedIcon 
                          color={isActive ? 'primary' : 'disabled'} 
                        />
                      )}
                      <Box sx={{ flex: 1 }}>
                        <Typography variant="body1" sx={{ fontWeight: isActive ? 600 : 400 }}>
                          {phase.label}
                        </Typography>
                        {isActive && status.current_phase === phase.id && (
                          <Typography variant="caption" color="text.secondary">
                            {status.logs?.split('\n').slice(-1)[0] || 'In progress...'}
                          </Typography>
                        )}
                      </Box>
                      {isActive && (
                        <Chip label="Active" color="primary" size="small" />
                      )}
                    </Box>
                  </Paper>
                );
              })}
            </Stack>

            {/* Instance Details */}
            {(status.ip_address || status.instance_id) && (
              <Box sx={{ mb: 3 }}>
                <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                  Instance Details
                </Typography>
                <Stack spacing={1}>
                  {status.instance_id && (
                    <Box>
                      <Typography variant="caption" color="text.secondary">Instance ID:</Typography>
                      <Typography variant="body2">{status.instance_id}</Typography>
                    </Box>
                  )}
                  {status.ip_address && (
                    <Box>
                      <Typography variant="caption" color="text.secondary">IP Address:</Typography>
                      <Typography variant="body2">{status.ip_address}</Typography>
                    </Box>
                  )}
                  {status.model_deployed && (
                    <Box>
                      <Typography variant="caption" color="text.secondary">Model:</Typography>
                      <Typography variant="body2">{status.model_deployed}</Typography>
                    </Box>
                  )}
                </Stack>
                {status.ip_address && (
                  <Button
                    variant="contained"
                    size="small"
                    onClick={() => {
                      const instanceData = {
                        id: status.instance_id,
                        instance_id: status.instance_id,
                        ipAddress: status.ip_address,
                        ip_address: status.ip_address,
                        sshUser: status.ssh_user || 'ubuntu',
                        ssh_user: status.ssh_user || 'ubuntu',
                      };
                      navigate('/profiling', {
                        state: {
                          openRunWorkload: true,
                          instanceData,
                        },
                      });
                      onClose();
                    }}
                    sx={{ mt: 1.5, textTransform: 'none', fontWeight: 600 }}
                  >
                    Go to Run Workload
                  </Button>
                )}
              </Box>
            )}

            {/* Logs */}
            {status.logs && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                  Logs
                </Typography>
                <Paper
                  variant="outlined"
                  sx={{
                    p: 2,
                    maxHeight: 200,
                    overflow: 'auto',
                    backgroundColor: 'grey.50',
                    fontFamily: 'monospace',
                    fontSize: '0.75rem'
                  }}
                >
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                    {status.logs}
                  </pre>
                </Paper>
              </Box>
            )}

            {/* Error Message */}
            {status.error_message && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {status.error_message}
              </Alert>
            )}

            {/* Success Message */}
            {status.status === 'ready' && !status.model_deployed && (
              <Alert severity="success" sx={{ mt: 2 }}>
                Instance setup complete! Select a model to deploy.
                <Button
                  variant="contained"
                  size="small"
                  onClick={() => setShowModelSelector(true)}
                  sx={{ ml: 2, textTransform: 'none' }}
                >
                  Deploy Model
                </Button>
              </Alert>
            )}
            
            {status.status === 'ready' && status.model_deployed && (
              <>
                <Alert 
                  severity="success" 
                  sx={{ mt: 2 }}
                >
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                      Instance setup and model deployment complete!
                    </Typography>
                    <Typography variant="body2">
                      Model: {status.model_deployed}
                    </Typography>
                    {status.ip_address && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                        Instance IP: {status.ip_address}
                      </Typography>
                    )}
                  </Box>
                </Alert>

                {/* Model Configuration Section */}
                {showConfigBeforeNavigate && (
                  <Paper variant="outlined" sx={{ mt: 3, p: 2 }}>
                    <Typography variant="subtitle2" sx={{ mb: 2, fontWeight: 600 }}>
                      Configure Model Parameters
                    </Typography>
                    <Stack spacing={2}>
                      <TextField
                        fullWidth
                        label="Input Tokens"
                        type="number"
                        value={modelConfig.inputTokens}
                        onChange={(e) => setModelConfig(prev => ({ ...prev, inputTokens: parseInt(e.target.value) || 0 }))}
                        helperText="Number of input tokens for inference"
                        inputProps={{ min: 1, max: 8192 }}
                      />
                      <TextField
                        fullWidth
                        label="Max Tokens"
                        type="number"
                        value={modelConfig.maxTokens}
                        onChange={(e) => setModelConfig(prev => ({ ...prev, maxTokens: parseInt(e.target.value) || 0 }))}
                        helperText="Maximum tokens to generate"
                        inputProps={{ min: 1, max: 8192 }}
                      />
                      <TextField
                        fullWidth
                        label="Temperature"
                        type="number"
                        value={modelConfig.temperature}
                        onChange={(e) => setModelConfig(prev => ({ ...prev, temperature: parseFloat(e.target.value) || 0 }))}
                        helperText="Sampling temperature (0.0 to 2.0)"
                        inputProps={{ min: 0, max: 2, step: 0.1 }}
                      />
                      <Box sx={{ display: 'flex', gap: 2, mt: 1 }}>
                        <Button
                          variant="contained"
                          color="primary"
                          size="large"
                          startIcon={<DashboardIcon />}
                          onClick={() => {
                            if (status.ip_address) {
                              const instanceData = {
                                id: status.instance_id,
                                instance_id: status.instance_id,
                                ipAddress: status.ip_address,
                                ip_address: status.ip_address,
                                sshUser: status.ssh_user || 'ubuntu',
                                ssh_user: status.ssh_user || 'ubuntu',
                                model_deployed: status.model_deployed,
                                modelConfig: modelConfig
                              };
                              navigate('/telemetry', {
                                state: { instanceData }
                              });
                              onClose();
                            }
                          }}
                          sx={{ textTransform: 'none', fontWeight: 600, flex: 1 }}
                        >
                          Go to Telemetry Dashboard
                        </Button>
                        <Button
                          variant="outlined"
                          onClick={() => {
                            setShowConfigBeforeNavigate(false);
                            setAutoNavigateEnabled(true);
                          }}
                          sx={{ textTransform: 'none' }}
                        >
                          Skip Configuration
                        </Button>
                      </Box>
                    </Stack>
                  </Paper>
                )}

                {/* Test Inference Section */}
                <Paper variant="outlined" sx={{ mt: 3, p: 2 }}>
                  <Typography variant="subtitle2" sx={{ mb: 2, fontWeight: 600 }}>
                    Test Model Inference
                  </Typography>
                  
                  <Stack spacing={2}>
                    <TextField
                      fullWidth
                      label="Test Prompt"
                      placeholder="Enter a prompt to test the model..."
                      value={testPrompt}
                      onChange={(e) => setTestPrompt(e.target.value)}
                      multiline
                      rows={3}
                      disabled={testLoading}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                          handleTestInference();
                        }
                      }}
                    />
                    
                    <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
                      <Button
                        variant="contained"
                        color="primary"
                        startIcon={testLoading ? <CircularProgress size={16} /> : <SendIcon />}
                        onClick={handleTestInference}
                        disabled={testLoading || !testPrompt.trim() || continuousRequests}
                        sx={{ textTransform: 'none' }}
                      >
                        {testLoading ? 'Sending...' : 'Send Request'}
                      </Button>
                      
                      <FormControlLabel
                        control={
                          <Switch
                            checked={continuousRequests}
                            onChange={toggleContinuousRequests}
                            color="primary"
                            disabled={!testPrompt.trim() || !status?.ip_address || !status?.model_deployed}
                          />
                        }
                        label={
                          <Typography variant="body2">
                            {continuousRequests ? 'Continuous Requests Active' : 'Start Continuous Requests'}
                          </Typography>
                        }
                      />
                      
                      {continuousRequests && (
                        <FormControl size="small" sx={{ minWidth: 120 }}>
                          <InputLabel>Interval (s)</InputLabel>
                          <Select
                            value={continuousInterval}
                            label="Interval (s)"
                            onChange={(e) => setContinuousInterval(Number(e.target.value))}
                            disabled={!continuousRequests}
                          >
                            <MenuItem value={1}>1 second</MenuItem>
                            <MenuItem value={2}>2 seconds</MenuItem>
                            <MenuItem value={5}>5 seconds</MenuItem>
                            <MenuItem value={10}>10 seconds</MenuItem>
                            <MenuItem value={15}>15 seconds</MenuItem>
                            <MenuItem value={30}>30 seconds</MenuItem>
                          </Select>
                        </FormControl>
                      )}
                    </Box>
                    
                    {continuousRequests && (
                      <Alert severity="info" sx={{ mt: 1 }}>
                        <Typography variant="body2">
                          Sending requests every {continuousInterval} second{continuousInterval !== 1 ? 's' : ''} to keep GPU busy. 
                          Metrics will update with each response.
                        </Typography>
                      </Alert>
                    )}

                    {testError && (
                      <Alert severity="error" onClose={() => setTestError(null)}>
                        {testError}
                      </Alert>
                    )}

                    {throughputMetrics && (
                      <Box sx={{ mt: 1 }}>
                        <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                          Performance Metrics
                        </Typography>
                        <Grid container spacing={2}>
                          <Grid item xs={6}>
                            <Paper variant="outlined" sx={{ p: 1.5 }}>
                              <Typography variant="caption" color="text.secondary">
                                Tokens/Second
                              </Typography>
                              <Typography variant="h6" color="primary">
                                {throughputMetrics.tokensPerSecond}
                              </Typography>
                            </Paper>
                          </Grid>
                          <Grid item xs={6}>
                            <Paper variant="outlined" sx={{ p: 1.5 }}>
                              <Typography variant="caption" color="text.secondary">
                                Latency
                              </Typography>
                              <Typography variant="h6">
                                {throughputMetrics.latency}s
                              </Typography>
                            </Paper>
                          </Grid>
                          <Grid item xs={4}>
                            <Typography variant="caption" color="text.secondary">
                              Prompt Tokens: {throughputMetrics.promptTokens}
                            </Typography>
                          </Grid>
                          <Grid item xs={4}>
                            <Typography variant="caption" color="text.secondary">
                              Completion: {throughputMetrics.completionTokens}
                            </Typography>
                          </Grid>
                          <Grid item xs={4}>
                            <Typography variant="caption" color="text.secondary">
                              Total: {throughputMetrics.totalTokens}
                            </Typography>
                          </Grid>
                        </Grid>
                      </Box>
                    )}

                    {testResponse && (
                      <Box sx={{ mt: 1 }}>
                        <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                          Model Response
                        </Typography>
                        <Paper 
                          variant="outlined" 
                          sx={{ 
                            p: 2, 
                            backgroundColor: 'grey.50',
                            maxHeight: 200,
                            overflow: 'auto'
                          }}
                        >
                          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                            {testResponse.content}
                          </Typography>
                        </Paper>
                      </Box>
                    )}
                  </Stack>
                </Paper>
              </>
            )}
          </>
        )}

        {!status && !error && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <Typography color="text.secondary">Loading orchestration status...</Typography>
          </Box>
        )}
      </DialogContent>
      
      {/* Dialog Actions */}
      <Box sx={{ p: 2, pt: 1, borderTop: '1px solid', borderColor: 'divider', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Button
          onClick={onClose}
          sx={{ textTransform: 'none' }}
        >
          Close
        </Button>
        
        {status?.status === 'ready' && status?.model_deployed && status?.ip_address && !showConfigBeforeNavigate && (
          <Button
            variant="contained"
            color="primary"
            size="large"
            startIcon={<DashboardIcon />}
            onClick={() => {
              const instanceData = {
                id: status.instance_id,
                instance_id: status.instance_id,
                ipAddress: status.ip_address,
                ip_address: status.ip_address,
                sshUser: status.ssh_user || 'ubuntu',
                ssh_user: status.ssh_user || 'ubuntu',
                model_deployed: status.model_deployed,
                modelConfig: modelConfig
              };
              navigate('/telemetry', {
                state: { instanceData }
              });
              onClose();
            }}
            sx={{ textTransform: 'none', fontWeight: 600, minWidth: 200 }}
          >
            View Telemetry Dashboard
          </Button>
        )}
        
        {status?.status === 'ready' && !status?.model_deployed && (
          <Button
            variant="contained"
            color="primary"
            onClick={() => setShowModelSelector(true)}
            sx={{ textTransform: 'none' }}
          >
            Deploy Model
          </Button>
        )}
      </Box>
      
      {/* Model Selector Dialog */}
      <ModelSelector
        open={showModelSelector}
        onClose={() => setShowModelSelector(false)}
        orchestrationId={orchestrationId}
        onDeploy={(model) => {
          setShowModelSelector(false);
          // Status will be refreshed automatically by the polling useEffect
        }}
      />
    </Dialog>
  );
}


