import React, { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Grid,
  Card,
  CardContent,
  Typography,
  Box,
  Stack,
  Chip,
  IconButton,
  FormControl,
  InputLabel,
  Select,
  MenuItem
} from '@mui/material';
import {
  Close as CloseIcon,
  CloudUpload as DeployIcon
} from '@mui/icons-material';
import apiService from '../services/api';

// Available models - ordered from smallest to largest
// RECOMMENDED: Mistral 7B - Small, reliable, publicly available, works on single GPU, no authentication required
const AVAILABLE_MODELS = [
  {
    id: 'mistral-7b',
    name: 'Mistral 7B ⭐ RECOMMENDED',
    size: '7B',
    memory: '16 GiB',
    gpus: ['RTX 4090', 'A10', 'A100', 'H100'],
    tokensPerSec: '80-120',
    description: '⭐ RECOMMENDED: Mistral 7B Instruct - Small, reliable model that runs on single GPU. Publicly available, no authentication required, fast download, guaranteed to work. Perfect for testing and production.',
    vllm_model_path: 'mistralai/Mistral-7B-Instruct-v0.2',
    vllm_config: {
      tensor_parallel_size: 1,  // Single GPU is sufficient
      max_model_len: 8192,
      max_num_seqs: 64,
      gpu_memory_utilization: 0.90,
    },
    recommended: true,  // Mark as recommended
  },
  {
    id: 'llama4-scout',
    name: 'Llama 4 Scout (Experimental)',
    size: '17B',
    memory: '34 GiB',
    gpus: ['H100', 'A100'],
    tokensPerSec: '120-150',
    description: '⚠️ EXPERIMENTAL: Meta Llama 4 Scout - Uses XET/compressed-tensors storage which may have download issues. Requires 2+ GPUs. Not recommended for first-time use.',
    vllm_model_path: 'RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic',
    vllm_config: {
      tensor_parallel_size: 2,  // Requires at least 2 GPUs
      max_model_len: 1024,
      max_num_seqs: 16,
      gpu_memory_utilization: 0.70,
      enforce_eager: true,
    },
    experimental: true,  // Mark as experimental
  },
  {
    id: 'llama3.1',
    name: 'Llama 3.1 Instruct',
    size: '8B / 70B',
    memory: '16-140 GiB',
    gpus: ['A100', 'H100'],
    tokensPerSec: '80-170',
    description: 'Meta Llama 3.1 Instruct family with 8B (single GPU) and 70B (multi-GPU) variants.',
    variants: [
      {
        name: 'Llama 3.1 8B Instruct',
        vllm_model_path: 'meta-llama/Llama-3.1-8B-Instruct',
        vllm_config: {
          tensor_parallel_size: 1,
          max_model_len: 8192,
          max_num_seqs: 64,
          gpu_memory_utilization: 0.90,
        }
      },
      {
        name: 'Llama 3.1 70B Instruct',
        vllm_model_path: 'meta-llama/Llama-3.1-70B-Instruct',
        vllm_config: {
          tensor_parallel_size: 8,
          max_model_len: 16384,
          max_num_seqs: 32,
          gpu_memory_utilization: 0.85,
        }
      }
    ]
  },
  {
    id: 'qwen2.5',
    name: 'Qwen 2.5',
    size: '32B',
    memory: '64 GiB',
    gpus: ['H100', 'A100'],
    tokensPerSec: '100-150',
    description: 'Qwen 2.5 32B model with excellent multilingual and coding capabilities',
    vllm_model_path: 'Qwen/Qwen2.5-32B-Instruct',
    vllm_config: {
      tensor_parallel_size: 4,
      max_model_len: 32768,
      max_num_seqs: 64,
      gpu_memory_utilization: 0.90,
    }
  },
  {
    id: 'mistral-mixtral',
    name: 'Mistral / Mixtral',
    size: '7B / 8x7B / 8x22B',
    memory: '14-176 GiB',
    gpus: ['A100', 'H100'],
    tokensPerSec: '100-200',
    description: 'Mistral AI models - choose from Mistral 7B or Mixtral 8x7B/8x22B variants',
    vllm_model_path: 'mistralai/Mistral-7B-Instruct-v0.2', // Default to Mistral 7B
    vllm_config: {
      tensor_parallel_size: 1, // For 7B; 8 for Mixtral
      max_model_len: 8192,
      max_num_seqs: 128,
      gpu_memory_utilization: 0.85,
    },
    variants: [
      {
        name: 'Mistral 7B',
        vllm_model_path: 'mistralai/Mistral-7B-Instruct-v0.2',
        vllm_config: {
          tensor_parallel_size: 1,
          max_model_len: 8192,
          max_num_seqs: 128,
          gpu_memory_utilization: 0.85,
        }
      },
      {
        name: 'Mixtral 8x7B',
        vllm_model_path: 'mistralai/Mixtral-8x7B-Instruct-v0.1',
        vllm_config: {
          tensor_parallel_size: 8,
          max_model_len: 32768,
          max_num_seqs: 64,
          gpu_memory_utilization: 0.90,
        }
      },
      {
        name: 'Mixtral 8x22B',
        vllm_model_path: 'mistralai/Mixtral-8x22B-Instruct-v0.1',
        vllm_config: {
          tensor_parallel_size: 8,
          max_model_len: 65536,
          max_num_seqs: 32,
          gpu_memory_utilization: 0.90,
        }
      }
    ]
  }
];

export default function ModelSelector({ open, onClose, orchestrationId, onDeploy }) {
  const [deploying, setDeploying] = useState(null);
  const [selectedVariant, setSelectedVariant] = useState({});
  const [quickModelId, setQuickModelId] = useState('');
  const [catalogModels, setCatalogModels] = useState(null); // null = not loaded yet

  // Fetch model catalog from backend; fall back to AVAILABLE_MODELS if unavailable
  React.useEffect(() => {
    if (!open) return;
    apiService.listModels().then((data) => {
      if (data?.models?.length) {
        // Map catalog format to the format expected by this component
        const mapped = data.models.map((m) => ({
          id: m.id,
          name: m.name,
          size: m.size_b ? `${m.size_b}B` : '',
          memory: m.vram_gb ? `${m.vram_gb} GiB` : '',
          gpus: m.compatible_gpus || [],
          tokensPerSec: m.tokens_per_sec_range ? m.tokens_per_sec_range.join('-') : '',
          description: m.description || '',
          vllm_model_path: m.hf_id,
          vllm_config: m.vllm_config || {},
          recommended: m.recommended || false,
          experimental: m.experimental || false,
        }));
        setCatalogModels(mapped);
      }
    }).catch(() => setCatalogModels(null));
  }, [open]);

  const models = catalogModels || AVAILABLE_MODELS;

  const handleDeploy = async (model, variant = null) => {
    setDeploying(model.id);
    try {
      // Get API key from localStorage (using same key format as ManageInstances)
      const raw = localStorage.getItem('cloudCreds_lambda');
      const parsed = raw ? JSON.parse(raw) : {};
      const apiKey = parsed.apiKey;

      if (!apiKey) {
        alert('Lambda API key not found. Please configure it first.');
        return;
      }

      // Use variant config if provided, otherwise use model config
      const deployConfig = variant || model;
      
      // The deployModel API now returns immediately and deploys in the background
      // The parent component will poll status to show progress
      await apiService.deployModel(orchestrationId, {
        model_name: deployConfig.vllm_model_path || model.id,
        vllm_config: deployConfig.vllm_config || model.vllm_config || {}
      });

      // Show success message - deployment is now running in background
      // Status polling in parent component will show progress
      if (onDeploy) {
        onDeploy(model);
      }
    } catch (e) {
      // Extract error message FIRST before any logging
      let errorMessage = 'Failed to deploy model';
      const responseData = e.response?.data;
      
      // Log for debugging
      console.error('=== DEPLOY MODEL ERROR ===');
      console.error('Error object:', e);
      console.error('Response data:', responseData);
      console.error('Response data.detail:', responseData?.detail);
      
      // Extract error message with priority: detail > message > responseData string > e.message
      if (responseData?.detail) {
        errorMessage = responseData.detail;
        console.error('Using responseData.detail:', errorMessage);
      } else if (responseData?.message) {
        errorMessage = responseData.message;
        console.error('Using responseData.message:', errorMessage);
      } else if (typeof responseData === 'string') {
        errorMessage = responseData;
        console.error('Using responseData as string:', errorMessage);
      } else if (e.message) {
        errorMessage = e.message;
        console.error('Using e.message:', errorMessage);
      }
      
      console.error('Final error message to display:', errorMessage);
      
      // Handle specific error cases
      if (e.response?.status === 524 || e.message?.includes('524')) {
        alert('Deployment request timed out, but deployment may have started. Please check the status - it may take 10-30 minutes to complete.');
      } else if (errorMessage.includes('deploying_model') || errorMessage.includes('already in progress')) {
        alert('A model deployment is already in progress. Please wait for it to complete before deploying another model.');
      } else {
        // Always show the extracted error message
        alert(errorMessage);
      }
    } finally {
      setDeploying(null);
    }
  };

  const handleQuickDeploy = () => {
    const model = models.find((m) => m.id === quickModelId);
    if (!model) return;
    const variant = model.variants && model.variants.length > 0 ? model.variants[0] : null;
    handleDeploy(model, variant);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="lg"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: 2
        }
      }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', pb: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 600 }}>
          Select Model to Deploy
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        <Box sx={{ mb: 2, display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <FormControl sx={{ minWidth: 240 }}>
            <InputLabel>Quick Model Select</InputLabel>
            <Select
              value={quickModelId}
              label="Quick Model Select"
              onChange={(e) => setQuickModelId(e.target.value)}
            >
              <MenuItem value=""><em>Select model</em></MenuItem>
              {models.map((m) => (
                <MenuItem key={m.id} value={m.id}>{m.name}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button
            variant="contained"
            startIcon={<DeployIcon />}
            disabled={!quickModelId || deploying !== null}
            onClick={handleQuickDeploy}
            sx={{ textTransform: 'none' }}
          >
            Deploy Selected
          </Button>
        </Box>

        <Grid container spacing={3} sx={{ mt: 1 }}>
          {models.map((model) => (
            <Grid item xs={12} md={6} key={model.id}>
              <Card
                variant="outlined"
                sx={{
                  height: '100%',
                  border: model.recommended ? '2px solid' : '1px solid',
                  borderColor: model.recommended ? 'success.main' : 'divider',
                  bgcolor: model.recommended ? 'action.hover' : 'background.paper',
                  '&:hover': {
                    boxShadow: 3,
                    borderColor: model.recommended ? 'success.dark' : 'primary.main'
                  },
                  transition: 'all 0.2s'
                }}
              >
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Typography variant="h6" sx={{ fontWeight: 600 }}>
                      {model.name}
                    </Typography>
                    {model.recommended && (
                      <Chip 
                        label="Recommended" 
                        size="small" 
                        color="success" 
                        sx={{ fontWeight: 'bold' }}
                      />
                    )}
                    {model.experimental && (
                      <Chip 
                        label="Experimental" 
                        size="small" 
                        color="warning" 
                        sx={{ fontWeight: 'bold' }}
                      />
                    )}
                  </Box>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    {model.description}
                  </Typography>
                  
                  <Stack spacing={1} sx={{ mb: 2 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Typography variant="body2" color="text.secondary">Size:</Typography>
                      <Typography variant="body2" fontWeight="bold">{model.size}</Typography>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Typography variant="body2" color="text.secondary">Memory:</Typography>
                      <Typography variant="body2" fontWeight="bold">{model.memory}</Typography>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Typography variant="body2" color="text.secondary">Performance:</Typography>
                      <Typography variant="body2" fontWeight="bold">{model.tokensPerSec} tokens/sec</Typography>
                    </Box>
                    <Box>
                      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>Recommended GPUs:</Typography>
                      <Stack direction="row" spacing={1} flexWrap="wrap" gap={1}>
                        {model.gpus.map((gpu) => (
                          <Chip key={gpu} label={gpu} size="small" color="primary" variant="outlined" />
                        ))}
                      </Stack>
                    </Box>
                  </Stack>

                  {/* Variant selector for Llama 3.1 */}
                  {model.variants && model.variants.length > 0 && (
                    <FormControl fullWidth sx={{ mb: 2 }}>
                      <InputLabel>Select Variant</InputLabel>
                      <Select
                        value={selectedVariant[model.id] !== undefined ? selectedVariant[model.id] : ''}
                        label="Select Variant"
                        onChange={(e) => setSelectedVariant(prev => ({ ...prev, [model.id]: parseInt(e.target.value) }))}
                      >
                        {model.variants.map((variant, idx) => (
                          <MenuItem key={idx} value={idx}>
                            {variant.name}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  )}

                  <Button
                    variant="contained"
                    color="primary"
                    fullWidth
                    onClick={() => {
                      const variant = model.variants && model.variants.length > 0 && selectedVariant[model.id] !== undefined 
                        ? model.variants[selectedVariant[model.id]]
                        : null;
                      handleDeploy(model, variant);
                    }}
                    disabled={deploying === model.id || (model.variants && model.variants.length > 0 && (selectedVariant[model.id] === undefined || selectedVariant[model.id] === ''))}
                    startIcon={<DeployIcon />}
                    sx={{ textTransform: 'none', mt: 1 }}
                  >
                    {deploying === model.id ? 'Deploying...' : 'Deploy Model'}
                  </Button>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </DialogContent>
      <DialogActions sx={{ p: 2, pt: 1 }}>
        <Button onClick={onClose} sx={{ textTransform: 'none' }}>
          Cancel
        </Button>
      </DialogActions>
    </Dialog>
  );
}
