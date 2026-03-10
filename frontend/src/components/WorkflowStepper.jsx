import React, { useMemo } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Stepper,
  Step,
  StepLabel,
  StepContent,
  Button,
  Chip,
  LinearProgress,
  Alert,
  TextField,
  Grid,
  Tooltip,
  IconButton,
  Paper,
  Stack,
  alpha,
  useTheme,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Info as InfoIcon,
  ExpandMore as ExpandMoreIcon,
  PlayArrow as PlayIcon,
  Refresh as RefreshIcon,
  Terminal as TerminalIcon,
} from '@mui/icons-material';

const WorkflowPhaseCard = React.memo(({
  phase,
  title,
  description,
  status,
  loading,
  logs,
  onRun,
  disabled,
  children,
  icon: Icon,
  dependencies,
}) => {
  const theme = useTheme();
  
  const getStatusConfig = (status) => {
    switch (status) {
      case 'completed':
        return { color: 'success', icon: CheckCircleIcon, label: 'Complete' };
      case 'failed':
      case 'error':
        return { color: 'error', icon: ErrorIcon, label: 'Failed' };
      case 'running':
      case 'started':
        return { color: 'info', icon: RefreshIcon, label: 'Running...' };
      default:
        return { color: 'default', icon: null, label: 'Not Started' };
    }
  };

  const statusConfig = getStatusConfig(status);
  const StatusIcon = statusConfig.icon;

  const isActive = status === 'running' || status === 'started' || loading;
  const isComplete = status === 'completed';
  const isFailed = status === 'failed' || status === 'error';

  return (
    <Card
      sx={{
        mb: 3,
        borderRadius: 3,
        border: `2px solid ${
          isComplete
            ? theme.palette.success.main
            : isFailed
            ? theme.palette.error.main
            : isActive
            ? theme.palette.info.main
            : alpha(theme.palette.divider, 0.1)
        }`,
        backgroundColor: isActive
          ? alpha(theme.palette.info.main, 0.05)
          : isComplete
          ? alpha(theme.palette.success.main, 0.02)
          : 'background.paper',
        transition: 'all 0.3s ease',
        '&:hover': {
          boxShadow: theme.shadows[4],
        },
      }}
    >
      <CardContent sx={{ p: 3 }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
          {Icon && (
            <Box
              sx={{
                p: 1.5,
                borderRadius: 2,
                backgroundColor: alpha(
                  isComplete
                    ? theme.palette.success.main
                    : isActive
                    ? theme.palette.info.main
                    : theme.palette.primary.main,
                  0.1
                ),
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Icon
                sx={{
                  color:
                    isComplete
                      ? theme.palette.success.main
                      : isActive
                      ? theme.palette.info.main
                      : theme.palette.primary.main,
                  fontSize: 24,
                }}
              />
            </Box>
          )}
          <Box sx={{ flex: 1 }}>
            <Stack direction="row" spacing={2} alignItems="center">
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                {title}
              </Typography>
              <Chip
                icon={StatusIcon ? <StatusIcon /> : null}
                label={loading ? 'Running...' : statusConfig.label}
                color={statusConfig.color}
                size="small"
                sx={{ fontWeight: 500 }}
              />
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {description}
            </Typography>
          </Box>
        </Stack>

        {dependencies && dependencies.length > 0 && (
          <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
            <Typography variant="body2">
              <strong>Prerequisites:</strong> {dependencies.join(', ')} must be completed first.
            </Typography>
          </Alert>
        )}

        {children}

        {isActive && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress sx={{ borderRadius: 1, height: 6 }} />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
              {loading ? 'Initializing...' : 'Processing...'}
            </Typography>
          </Box>
        )}

        <Stack direction="row" spacing={2} sx={{ mt: 3 }}>
          <Button
            variant="contained"
            color="primary"
            startIcon={loading ? <RefreshIcon /> : <PlayIcon />}
            onClick={onRun}
            disabled={disabled || loading}
            sx={{ borderRadius: 2, minWidth: 140 }}
          >
            {loading ? 'Running...' : `Run ${phase}`}
          </Button>
        </Stack>

        {logs && (
          <Accordion sx={{ mt: 3, borderRadius: 2, '&:before': { display: 'none' } }}>
            <AccordionSummary
              expandIcon={<ExpandMoreIcon />}
              sx={{
                backgroundColor: alpha(theme.palette.background.default, 0.5),
                borderRadius: 2,
                '&:hover': {
                  backgroundColor: alpha(theme.palette.action.hover, 0.05),
                },
              }}
            >
              <Stack direction="row" spacing={1.5} alignItems="center">
                <TerminalIcon sx={{ fontSize: 20, color: 'text.secondary' }} />
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  View Logs ({logs.split('\n').length} lines)
                </Typography>
              </Stack>
            </AccordionSummary>
            <AccordionDetails sx={{ p: 0 }}>
              <Paper
                sx={{
                  p: 2,
                  backgroundColor: '#1e1e1e',
                  color: '#d4d4d4',
                  fontFamily: 'monospace',
                  fontSize: '0.75rem',
                  maxHeight: 400,
                  overflow: 'auto',
                  borderRadius: 2,
                }}
              >
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {logs}
                </pre>
              </Paper>
            </AccordionDetails>
          </Accordion>
        )}
      </CardContent>
    </Card>
  );
});

WorkflowPhaseCard.displayName = 'WorkflowPhaseCard';

const WorkflowStepper = ({
  phases,
  activeStep,
  onPhaseRun,
  sshHost,
  sshKey,
  selectedModel,
}) => {
  const theme = useTheme();

  const steps = useMemo(() => {
    return phases.map((phase, index) => ({
      ...phase,
      stepNumber: index + 1,
      isActive: index === activeStep,
      isCompleted: phase.status === 'completed',
      canRun: index === 0 || phases[index - 1]?.status === 'completed',
    }));
  }, [phases, activeStep]);

  return (
    <Box>
      <Stepper
        activeStep={activeStep}
        orientation="vertical"
        sx={{
          '& .MuiStepLabel-root': {
            '& .MuiStepLabel-label': {
              fontWeight: 600,
            },
          },
          '& .MuiStepContent-root': {
            borderLeft: `2px solid ${alpha(theme.palette.divider, 0.2)}`,
            pl: 4,
            ml: 1.5,
          },
        }}
      >
        {steps.map((step, index) => (
          <Step key={step.phase} completed={step.isCompleted}>
            <StepLabel
              optional={
                <Chip
                  label={
                    step.loading
                      ? 'Running...'
                      : step.status === 'completed'
                      ? 'Complete'
                      : step.status === 'failed'
                      ? 'Failed'
                      : 'Pending'
                  }
                  color={
                    step.status === 'completed'
                      ? 'success'
                      : step.status === 'failed'
                      ? 'error'
                      : step.loading
                      ? 'info'
                      : 'default'
                  }
                  size="small"
                />
              }
            >
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                {step.title}
              </Typography>
            </StepLabel>
            <StepContent>
              <WorkflowPhaseCard
                phase={step.phase}
                title={step.title}
                description={step.description}
                status={step.status}
                loading={step.loading}
                logs={step.logs}
                onRun={() => onPhaseRun(step.phase, index)}
                disabled={!step.canRun || !sshHost || !sshKey}
                icon={step.icon}
                dependencies={
                  index > 0
                    ? [`Phase ${index}`]
                    : []
                }
              >
                {step.children}
              </WorkflowPhaseCard>
            </StepContent>
          </Step>
        ))}
      </Stepper>
    </Box>
  );
};

export default WorkflowStepper;

