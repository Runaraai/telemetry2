import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  Box,
  Typography,
  Button,
  MobileStepper,
  Chip,
  Divider,
  IconButton,
} from '@mui/material';
import {
  Close as CloseIcon,
  KeyboardArrowLeft,
  KeyboardArrowRight,
  Cloud as CloudIcon,
  PlayArrow as PlayIcon,
  BarChart as BarChartIcon,
  CheckCircleOutline as CheckIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';

const STORAGE_KEY = 'omniference_onboarding_done';

const STEPS = [
  {
    icon: <CloudIcon sx={{ fontSize: 40, color: '#3DA866' }} />,
    label: 'Step 1 of 3',
    title: 'Connect your GPU',
    subtitle: 'Launch a cloud GPU or connect one you already have running.',
    bullets: [
      'Go to Manage Instances to add API keys for Lambda Labs, Nebius, or Scaleway.',
      "Launch a GPU — we'll give you model-fit recommendations before you pick.",
      "Once it's running, copy the SSH host shown in Running Instances.",
    ],
    cta: { label: 'Go to Manage Instances', path: '/instances' },
    tip: 'Not sure which GPU to pick? L40S (48 GB) handles most 7–34B models. H100 (80 GB) is needed for 70B+.',
  },
  {
    icon: <PlayIcon sx={{ fontSize: 40, color: '#3DA866' }} />,
    label: 'Step 2 of 3',
    title: 'Set up & deploy inference',
    subtitle: 'Install dependencies, download the model, then start the vLLM server.',
    bullets: [
      'Open Run Workload and paste your SSH host.',
      'Click Setup — this installs Docker, CUDA tools, and vLLM on the instance.',
      'Click Check to verify prerequisites, then Deploy Inference to start vLLM.',
    ],
    cta: { label: 'Go to Run Workload', path: '/profiling' },
    tip: 'Setup only needs to run once. Next time, just hit Check → Deploy.',
  },
  {
    icon: <BarChartIcon sx={{ fontSize: 40, color: '#3DA866' }} />,
    label: 'Step 3 of 3',
    title: 'Run a benchmark & see results',
    subtitle: 'Pick your benchmark mode and watch metrics stream in real-time.',
    bullets: [
      'In the Profiling tab, choose a model and click Run Workload Benchmark for throughput, TTFT, and inter-token latency.',
      'For kernel-level GPU analysis, use Run Kernel Profile (adds ~10 % overhead).',
      'Switch to the Telemetry tab any time to watch live GPU utilisation graphs.',
    ],
    cta: { label: 'Start benchmarking', path: '/profiling' },
    tip: 'Leave the inference server running between benchmark runs — it stays warm so your first request is fast.',
  },
];

export default function OnboardingWizard() {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const done = localStorage.getItem(STORAGE_KEY);
    if (!done) setOpen(true);
  }, []);

  const dismiss = () => {
    localStorage.setItem(STORAGE_KEY, '1');
    setOpen(false);
  };

  const handleCta = () => {
    navigate(STEPS[step].cta.path);
    dismiss();
  };

  const current = STEPS[step];

  return (
    <Dialog
      open={open}
      onClose={dismiss}
      maxWidth="sm"
      fullWidth
      PaperProps={{
        sx: {
          backgroundColor: '#142B1D',
          border: '1px solid #1E4530',
          borderRadius: '16px',
          overflow: 'hidden',
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 3,
          pt: 2.5,
          pb: 1.5,
          borderBottom: '1px solid #1E4530',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <img src="/logo.png" alt="Runara" style={{ height: '22px' }} />
          <Typography variant="body2" sx={{ color: '#94a3b8' }}>
            Quick start guide
          </Typography>
        </Box>
        <IconButton size="small" onClick={dismiss} sx={{ color: '#94a3b8' }}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      <DialogContent sx={{ px: 3, py: 3 }}>
        {/* Step badge */}
        <Chip
          label={current.label}
          size="small"
          sx={{
            backgroundColor: 'rgba(61, 168, 102, 0.12)',
            color: '#3DA866',
            border: '1px solid rgba(61, 168, 102, 0.3)',
            mb: 2,
          }}
        />

        {/* Icon + heading */}
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, mb: 2.5 }}>
          <Box
            sx={{
              p: 1.5,
              borderRadius: '12px',
              backgroundColor: 'rgba(61, 168, 102, 0.08)',
              border: '1px solid rgba(61, 168, 102, 0.2)',
              flexShrink: 0,
            }}
          >
            {current.icon}
          </Box>
          <Box>
            <Typography variant="h3" sx={{ mb: 0.5 }}>
              {current.title}
            </Typography>
            <Typography variant="body2" sx={{ color: '#94a3b8' }}>
              {current.subtitle}
            </Typography>
          </Box>
        </Box>

        {/* Bullets */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, mb: 3 }}>
          {current.bullets.map((b, i) => (
            <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
              <CheckIcon sx={{ color: '#3DA866', fontSize: 18, mt: '2px', flexShrink: 0 }} />
              <Typography variant="body1" sx={{ color: '#cbd5e1', lineHeight: 1.6 }}>
                {b}
              </Typography>
            </Box>
          ))}
        </Box>

        {/* Tip box */}
        <Box
          sx={{
            p: 1.5,
            borderRadius: '8px',
            backgroundColor: 'rgba(30, 58, 138, 0.2)',
            border: '1px solid rgba(30, 69, 168, 0.3)',
            mb: 3,
          }}
        >
          <Typography variant="body2" sx={{ color: '#93c5fd' }}>
            <strong>Tip:</strong> {current.tip}
          </Typography>
        </Box>

        <Divider sx={{ mb: 2.5 }} />

        {/* Navigation */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <MobileStepper
            variant="dots"
            steps={STEPS.length}
            position="static"
            activeStep={step}
            sx={{
              p: 0,
              backgroundColor: 'transparent',
              '& .MuiMobileStepper-dot': { backgroundColor: '#1E4530' },
              '& .MuiMobileStepper-dotActive': { backgroundColor: '#3DA866' },
            }}
            backButton={
              <Button
                size="small"
                onClick={() => setStep((s) => s - 1)}
                disabled={step === 0}
                startIcon={<KeyboardArrowLeft />}
                sx={{ color: '#94a3b8', '&:hover': { color: '#e2e8f0' } }}
              >
                Back
              </Button>
            }
            nextButton={
              step < STEPS.length - 1 ? (
                <Button
                  size="small"
                  onClick={() => setStep((s) => s + 1)}
                  endIcon={<KeyboardArrowRight />}
                  sx={{ color: '#94a3b8', '&:hover': { color: '#e2e8f0' } }}
                >
                  Next
                </Button>
              ) : (
                <Box sx={{ width: 72 }} />
              )
            }
          />

          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              size="small"
              variant="outlined"
              onClick={dismiss}
              sx={{ fontSize: '12px' }}
            >
              Skip tour
            </Button>
            <Button
              size="small"
              variant="contained"
              onClick={handleCta}
              sx={{ fontSize: '12px', whiteSpace: 'nowrap' }}
            >
              {current.cta.label}
            </Button>
          </Box>
        </Box>
      </DialogContent>
    </Dialog>
  );
}
