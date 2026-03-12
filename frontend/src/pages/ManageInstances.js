
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { 
  Box, Typography, Stack, TextField, Button, Alert, Card, CardContent, Dialog, DialogTitle, DialogContent, DialogActions, Link, Grid, Chip, CircularProgress, Paper, FormControl, InputLabel, Select, MenuItem, Tabs, Tab
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  HelpOutline as HelpOutlineIcon,
  PlayArrow as PlayArrowIcon,
  Computer as ComputerIcon,
  Cloud as CloudIcon,
  VpnKey as VpnKeyIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  OpenInNew as OpenInNewIcon,
  DeleteOutline as DeleteOutlineIcon
} from '@mui/icons-material';
import apiService, { friendlyError } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import InstanceOrchestration from '../components/InstanceOrchestration';
import ModelSelector from '../components/ModelSelector';
import { useUI } from '../components/ui/UIProvider';
import RefreshControl from '../components/ui/RefreshControl';
import { ListSkeleton } from '../components/ui/Skeletons';

// GPU specifications lookup — maps GPU family keywords to their known specs
const GPU_SPECS = {
  'H100': { vram: 80, vramUnit: 'GB HBM3', cudaCores: 16896, tensorCores: 528, memBandwidth: '3.35 TB/s', arch: 'Hopper', tdp: 700 },
  'H200': { vram: 141, vramUnit: 'GB HBM3e', cudaCores: 16896, tensorCores: 528, memBandwidth: '4.8 TB/s', arch: 'Hopper', tdp: 700 },
  'A100': { vram: 80, vramUnit: 'GB HBM2e', cudaCores: 6912, tensorCores: 432, memBandwidth: '2.0 TB/s', arch: 'Ampere', tdp: 400 },
  'A10': { vram: 24, vramUnit: 'GB GDDR6', cudaCores: 9216, tensorCores: 288, memBandwidth: '600 GB/s', arch: 'Ampere', tdp: 150 },
  'L4': { vram: 24, vramUnit: 'GB GDDR6', cudaCores: 7424, tensorCores: 232, memBandwidth: '300 GB/s', arch: 'Ada Lovelace', tdp: 72 },
  'L40': { vram: 48, vramUnit: 'GB GDDR6', cudaCores: 18176, tensorCores: 568, memBandwidth: '864 GB/s', arch: 'Ada Lovelace', tdp: 300 },
  'L40S': { vram: 48, vramUnit: 'GB GDDR6', cudaCores: 18176, tensorCores: 568, memBandwidth: '864 GB/s', arch: 'Ada Lovelace', tdp: 350 },
  'V100': { vram: 32, vramUnit: 'GB HBM2', cudaCores: 5120, tensorCores: 640, memBandwidth: '900 GB/s', arch: 'Volta', tdp: 300 },
  'T4': { vram: 16, vramUnit: 'GB GDDR6', cudaCores: 2560, tensorCores: 320, memBandwidth: '300 GB/s', arch: 'Turing', tdp: 70 },
  'B200': { vram: 192, vramUnit: 'GB HBM3e', cudaCores: 18432, tensorCores: 576, memBandwidth: '8.0 TB/s', arch: 'Blackwell', tdp: 1000 },
  'GH200': { vram: 96, vramUnit: 'GB HBM3', cudaCores: 16896, tensorCores: 528, memBandwidth: '4.0 TB/s', arch: 'Hopper', tdp: 900 },
  'MI300': { vram: 192, vramUnit: 'GB HBM3', arch: 'CDNA 3', tdp: 750, memBandwidth: '5.3 TB/s' },
  'RENDER-S': { vram: 16, vramUnit: 'GB GDDR6', arch: 'Turing', tdp: 70 },
};

// Match a commercial type or GPU model string to a GPU_SPECS entry
function lookupGpuSpecs(nameOrModel) {
  if (!nameOrModel) return null;
  const upper = nameOrModel.toUpperCase();
  // Try exact prefix matches first (longer keys first to match L40S before L40)
  const sorted = Object.keys(GPU_SPECS).sort((a, b) => b.length - a.length);
  for (const key of sorted) {
    if (upper.includes(key)) return { key, ...GPU_SPECS[key] };
  }
  return null;
}

const PROVIDERS = [
  {
    id: 'scaleway',
    label: 'Scaleway',
    logo: 'https://www.scaleway.com/favicon-192x192.png',
    name: 'Scaleway',
    color: '#4A00FF',
    bgColor: '#1a1a18',
    requiredFields: ['Access Key', 'Secret Key', 'Project ID'],
    helpUrl: 'https://www.scaleway.com/en/docs/iam/how-to/create-api-keys/',
    helpText: 'To get your Scaleway credentials:\\n1. Go to Scaleway Console -> IAM -> API Keys\\n2. Create an Access Key and Secret Key\\n3. Copy your Project ID from Project settings\\n4. Paste keys and Project ID here'
  }
];

const NEBIUS_REGION_ZONE_MAP = {
  'eu-north1': ['eu-north1-a', 'eu-north1-b', 'eu-north1-c'],
  'eu-north2': ['eu-north2-a', 'eu-north2-b', 'eu-north2-c'],
  'eu-west1': ['eu-west1-a', 'eu-west1-b', 'eu-west1-c'],
  'me-west1': ['me-west1-a', 'me-west1-b', 'me-west1-c'],
  'uk-south1': ['uk-south1-a', 'uk-south1-b', 'uk-south1-c'],
  'us-central1': ['us-central1-a', 'us-central1-b', 'us-central1-c'],
};

// Static Scaleway regions and sample configurations (used as fallback when API fails)
const SCW_REGIONS = [
  'fr-par-1',
  'fr-par-2',
  'fr-par-3',
  'nl-ams-1',
  'nl-ams-2',
  'nl-ams-3',
  'pl-waw-1',
  'pl-waw-2',
  'pl-waw-3',
];

const SCW_SAMPLE_CONFIGS_BY_REGION = {
  'fr-par-1': [
    { id: 'l4-1-24g', name: 'L4-1-24G', gpus: 1, vcpus: 8, ramBytes: 51_539_607_552, priceEurHour: 0.75, availability: 'available' },
    { id: 'l4-2-24g', name: 'L4-2-24G', gpus: 2, vcpus: 16, ramBytes: 103_079_215_104, priceEurHour: 1.5, availability: 'available' },
    { id: 'l4-4-24g', name: 'L4-4-24G', gpus: 4, vcpus: 32, ramBytes: 206_158_430_208, priceEurHour: 3.0, availability: 'quota required' },
  ],
  'fr-par-2': [
    { id: 'a100-1-80g', name: 'A100-1-80G', gpus: 1, vcpus: 12, ramBytes: 128_000_000_000, priceEurHour: 2.9, availability: 'available' },
    { id: 'a100-2-80g', name: 'A100-2-80G', gpus: 2, vcpus: 24, ramBytes: 256_000_000_000, priceEurHour: 5.6, availability: 'quota required' },
  ],
  'fr-par-3': [
    { id: 'h100-1-80g', name: 'H100-1-80G', gpus: 1, vcpus: 16, ramBytes: 192_000_000_000, priceEurHour: 6.5, availability: 'available' },
  ],
  'nl-ams-1': [
    { id: 'render-s', name: 'RENDER-S', gpus: 1, vcpus: 10, ramBytes: 45_097_156_608, priceEurHour: 1.22, availability: 'out of stock' },
    { id: 'l4-1-24g', name: 'L4-1-24G', gpus: 1, vcpus: 8, ramBytes: 51_539_607_552, priceEurHour: 0.8, availability: 'available' },
  ],
  'nl-ams-2': [
    { id: 'l4-2-24g', name: 'L4-2-24G', gpus: 2, vcpus: 16, ramBytes: 103_079_215_104, priceEurHour: 1.6, availability: 'available' },
  ],
  'nl-ams-3': [
    { id: 'l4-4-24g', name: 'L4-4-24G', gpus: 4, vcpus: 32, ramBytes: 206_158_430_208, priceEurHour: 3.1, availability: 'quota required' },
  ],
  'pl-waw-1': [
    { id: 'l4-1-24g', name: 'L4-1-24G', gpus: 1, vcpus: 8, ramBytes: 51_539_607_552, priceEurHour: 0.78, availability: 'available' },
  ],
  'pl-waw-2': [
    { id: 'l4-2-24g', name: 'L4-2-24G', gpus: 2, vcpus: 16, ramBytes: 103_079_215_104, priceEurHour: 1.55, availability: 'available' },
  ],
  'pl-waw-3': [
    { id: 'l4-4-24g', name: 'L4-4-24G', gpus: 4, vcpus: 32, ramBytes: 206_158_430_208, priceEurHour: 3.05, availability: 'quota required' },
  ],
};

function storageKey(providerId) {
  return `cloudCreds_${providerId}`;
}

const formatUsd = (value) => {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return null;
  }
  return `$${Number(value).toFixed(2)}`;
};

// Helper to convert backend credential to frontend format
function parseBackendCredential(credential, secret) {
  if (!credential || !secret) {
    return null;
  }

  try {
    const secretData = typeof secret === 'string' ? JSON.parse(secret) : secret;

    return {
      accessKeyId: secretData.accessKeyId || secretData.access_key_id || secretData.apiKey || '',
      secretKey: secretData.secretKey || secretData.secret_key || '',
      projectId: secretData.projectId || secretData.project_id || ''
    };
  } catch (e) {
    console.warn('⚠️ parseBackendCredential(scaleway): Secret is not valid JSON');
    return {
      accessKeyId: '',
      secretKey: '',
      projectId: ''
    };
  }
}

// Helper to convert frontend format to backend credential secret
function createBackendSecret(providerId, data) {
  return JSON.stringify({
    accessKeyId: data.accessKeyId,
    secretKey: data.secretKey,
    projectId: data.projectId
  });
}

export default function ManageInstances() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, user } = useAuth();
  const [viewMode, setViewMode] = useState('cloud'); // 'cloud' or 'local'
  const { showToast, confirm } = useUI();
  const [lastUpdated, setLastUpdated] = useState(null);
  const [selectedProvider, setSelectedProvider] = useState('scaleway');
  const [openModal, setOpenModal] = useState(null);
  const [credentials, setCredentials] = useState({}); // Store credentials from backend
  const [credentialSecrets, setCredentialSecrets] = useState({}); // Cache credential secrets
  const [credentialsLoading, setCredentialsLoading] = useState(true);
  const [showHelpDialog, setShowHelpDialog] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [migrationPlan, setMigrationPlan] = useState(null);
  
  // Local instance form state
  const [localInstanceForm, setLocalInstanceForm] = useState({
    ipAddress: '',
    sshKey: '',
    sshUser: 'ubuntu'
  });
  
  // SSH public key fetched from backend .env (auto-populated into all launch forms)
  const [envSSHKey, setEnvSSHKey] = useState('');

  // Fetch SSH public key from backend on mount and auto-populate all launch forms
  useEffect(() => {
    apiService.getSSHPublicKey()
      .then((key) => {
        if (key) {
          setEnvSSHKey(key);
          // Auto-populate SSH key into all provider launch forms
          setLaunchForm(prev => ({ ...prev, sshKey: key }));
          setScwLaunchForm(prev => ({ ...prev, publicKey: key }));
          setNebiusLaunchForm(prev => ({ ...prev, sshPublicKey: key }));
        }
      })
      .catch(() => {}); // silently ignore if not configured
  }, []);

  // Ensure page is white on mount
  useEffect(() => {
    document.body.style.backgroundColor = '#2d2d2a';
    return () => {
      document.body.style.backgroundColor = '';
    };
  }, []);

  // Handle migration handoff from profiling
  useEffect(() => {
    const state = location.state;
    if (state?.migrateTarget) {
      const { migrateTarget, sourceInstance } = state;
      setMigrationPlan({ target: migrateTarget, source: sourceInstance });
      setSelectedProvider(migrateTarget.provider || null);
      setAggregatedViewMode('cloud');
      setMessage(`Migration target selected: ${migrateTarget.name}. Launch it, then delete source ${sourceInstance?.name || sourceInstance?.id || ''}.`);
    }
  }, [location.state]);
  
  // Instances state
  const [instances, setInstances] = useState({});
  const [expandedProvider, setExpandedProvider] = useState(null);
  const providerInstances = selectedProvider ? (instances[selectedProvider] || []) : [];
  
  // Aggregated view state
  const [aggregatedViewMode, setAggregatedViewMode] = useState('cloud'); // 'cloud' or 'aggregated'
  const [aggregatedInstances, setAggregatedInstances] = useState([]);
  const [aggregatedLoading, setAggregatedLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filters, setFilters] = useState({
    cloud: [],
    gpuType: '',
    numGpus: '',
    availability: ''
  });
  const [sortBy, setSortBy] = useState('cost_asc'); // cost_asc, cost_desc

  const gpuTypeOptions = useMemo(() => {
    const common = [
      'B200',
      'H200',
      'H100',
      'GH200',
      'A100',
      'A10',
      'L40S',
      'L40',
      'L4',
      'V100',
      'T4',
      'MI300',
    ];
    const fromData = new Set();
    (aggregatedInstances || []).forEach((item) => {
      const model = (item.gpu_model || '').trim();
      if (model) fromData.add(model);
    });
    return Array.from(new Set([...common, ...Array.from(fromData)])).filter(Boolean);
  }, [aggregatedInstances]);
  
  // Launch instance state
  const [launchDialogOpen, setLaunchDialogOpen] = useState(false);
  const [instanceTypes, setInstanceTypes] = useState([]);
  const [regions, setRegions] = useState([]);
  const [sshKeys, setSshKeys] = useState([]);
  const [launchLoading, setLaunchLoading] = useState(false);
  const [launchForm, setLaunchForm] = useState({
    instanceType: '',
    region: '',
    sshKeyName: '', // Keep for backward compatibility, but we'll use sshKey primarily
    sshKey: '' // Manual SSH key input
  });
  
  // Orchestration state
  const [orchestrationDialogOpen, setOrchestrationDialogOpen] = useState(false);
  const [orchestrationId, setOrchestrationId] = useState(null);
  const [orchestrationStatus, setOrchestrationStatus] = useState(null);
  const [instanceOrchestrations, setInstanceOrchestrations] = useState({}); // Map instance_id -> orchestration
  
  // Expanded card state
  const [expandedCards, setExpandedCards] = useState(new Set());

  // Scaleway launch modal
  const SCW_INITIAL_LAUNCH_FORM = {
    region: '',
    publicKey: '',
    sshKeyName: '',
    commercialType: '',
    rootVolumeSize: null, // in GB, null means use default
    rootVolumeType: null, // 'l_ssd' or 'sbs_volume', null means use default
  };
  const [scwLaunchOpen, setScwLaunchOpen] = useState(false);
  const [scwLaunchConfig, setScwLaunchConfig] = useState(null);
  const [scwLaunchForm, setScwLaunchForm] = useState(SCW_INITIAL_LAUNCH_FORM);
  const [scwLaunchLoading, setScwLaunchLoading] = useState(false);
  const [scwProgress, setScwProgress] = useState({
    open: false,
    serverId: null,
    zone: null,
    status: null,
    ip: null,
    stateDetail: null,
    refreshedInstances: false,
  });

  // Unified full-screen launching state (used by all providers)
  const [launchingScreen, setLaunchingScreen] = useState({
    active: false,
    provider: null,      // 'scaleway' | 'lambda' | 'nebius'
    phase: 'launching',  // 'launching' | 'waiting_ip' | 'ready'
    ip: null,
    instanceName: null,
    sshUser: 'ubuntu',
  });

  // Scaleway state (real fetch via backend proxy; defaults seeded with static list)
  const [scwRegions, setScwRegions] = useState(SCW_REGIONS);
  const [scwRegion, setScwRegion] = useState(SCW_REGIONS[0]);
  const [scwConfigs, setScwConfigs] = useState([]);
  const [scwLoading, setScwLoading] = useState(false);
  const [scwInstancesZone, setScwInstancesZone] = useState(null);
  const [scwDeleteDialog, setScwDeleteDialog] = useState({ open: false, instance: null });
  const [scwDeleteLoading, setScwDeleteLoading] = useState(false);
  const [scwModalConfigs, setScwModalConfigs] = useState([]);
  const [scwModalLoading, setScwModalLoading] = useState(false);
  const [scwLaunchPreset, setScwLaunchPreset] = useState(false);
const [nebiusRegions, setNebiusRegions] = useState(['eu-north1', 'eu-west1', 'us-central1']);
  const [nebiusRegion, setNebiusRegion] = useState('eu-north1');
const [nebiusConfigs, setNebiusConfigs] = useState([]);
const [nebiusQuota, setNebiusQuota] = useState(null);
const [nebiusLoading, setNebiusLoading] = useState(false);
const [nebiusProjectId, setNebiusProjectId] = useState('');
const [nebiusDeleteDialog, setNebiusDeleteDialog] = useState({ open: false, instance: null });
const [nebiusDeleteLoading, setNebiusDeleteLoading] = useState(false);
  const nebiusRegionBreakdown = useMemo(() => {
    const available = [];
    const unavailable = [];
    const seenPresets = new Set(); // Track seen preset IDs to avoid duplicates
    
    (nebiusConfigs || []).forEach((preset) => {
      // Nebius often reuses preset IDs/names across platforms; include platform_id to avoid collapsing
      // distinct GPU families (e.g., H100 vs H200) into a single card.
      const baseId = preset.id || preset.name || '';
      const presetKey = preset.platform_id ? `${preset.platform_id}:${baseId}` : baseId || `${preset.platform_name}:${preset.name}`;
      
      // Skip if we've already seen this preset
      if (seenPresets.has(presetKey)) {
        return;
      }
      seenPresets.add(presetKey);
      
      const regions = Array.isArray(preset.platform_regions) ? preset.platform_regions : [];
      if (!regions.length || regions.includes(nebiusRegion)) {
        available.push(preset);
      } else {
        unavailable.push(preset);
      }
    });
    return { available, unavailable };
  }, [nebiusConfigs, nebiusRegion]);
  const nebiusAvailablePresets = nebiusRegionBreakdown.available;
  const nebiusUnavailablePresets = nebiusRegionBreakdown.unavailable;
  const nebiusZoneOptions = useMemo(() => {
    const zones = new Set();
    nebiusAvailablePresets.forEach((preset) => {
      (preset.platform_zones || []).forEach((zone) => {
        if (!nebiusRegion || zone.startsWith(nebiusRegion)) {
          zones.add(zone);
        }
      });
    });
    if (zones.size === 0 && NEBIUS_REGION_ZONE_MAP[nebiusRegion]) {
      NEBIUS_REGION_ZONE_MAP[nebiusRegion].forEach((zone) => zones.add(zone));
    }
    if (zones.size === 0 && nebiusRegion) {
      zones.add(`${nebiusRegion}-a`);
    }
    return Array.from(zones);
  }, [nebiusAvailablePresets, nebiusRegion]);
  
  // Filtered and sorted aggregated instances
  const filteredAndSortedInstances = useMemo(() => {
    let filtered = [...aggregatedInstances];
    
    // Apply search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(inst => 
        (inst.name && inst.name.toLowerCase().includes(query)) ||
        (inst.description && inst.description.toLowerCase().includes(query)) ||
        (inst.gpu_model && inst.gpu_model.toLowerCase().includes(query)) ||
        (inst.provider && inst.provider.toLowerCase().includes(query))
      );
    }
    
    // Apply cloud filter
    if (filters.cloud && filters.cloud.length > 0) {
      filtered = filtered.filter(inst => filters.cloud.includes(inst.provider));
    }
    
    // Apply GPU type filter
    if (filters.gpuType) {
      filtered = filtered.filter(inst => 
        inst.gpu_model && inst.gpu_model.toUpperCase() === filters.gpuType.toUpperCase()
      );
    }
    
    // Apply num GPUs filter
    if (filters.numGpus) {
      const numGpus = parseInt(filters.numGpus);
      filtered = filtered.filter(inst => inst.num_gpus === numGpus);
    }
    
    // Apply availability filter
    if (filters.availability) {
      filtered = filtered.filter(inst => {
        if (!inst.availability) return false;
        const availability = inst.availability.toLowerCase();
        const filterValue = filters.availability.toLowerCase();
        return availability.includes(filterValue) || availability === filterValue;
      });
    }
    
    // Apply sorting
    filtered.sort((a, b) => {
      if (sortBy === 'cost_asc' || sortBy === 'cost_desc') {
        const aCost = a.cost_per_hour_usd || 999999;
        const bCost = b.cost_per_hour_usd || 999999;
        return sortBy === 'cost_asc' ? aCost - bCost : bCost - aCost;
      }
      return 0;
    });
    
    return filtered;
  }, [aggregatedInstances, searchQuery, filters, sortBy]);
  
  const lastUserIdRef = useRef(null);

  const resolveNebiusProjectId = useCallback(
    (projectIdValue, region) => {
      if (!projectIdValue) return projectIdValue;
      if (typeof projectIdValue !== 'string') return projectIdValue;
      const trimmed = projectIdValue.trim();
      if (!trimmed) return trimmed;

      // Support passing a region->project map in the Project ID field:
      // - CSV: "eu-north1:proj1,us-central1:proj2"
      // - JSON: '{"eu-north1":"proj1","us-central1":"proj2"}'
      if (trimmed.includes(':') && trimmed.includes(',')) {
        const mapping = {};
        trimmed.split(',').forEach((entry) => {
          const part = entry.trim();
          if (!part) return;
          const idx = part.indexOf(':');
          if (idx <= 0) return;
          const key = part.slice(0, idx).trim();
          const val = part.slice(idx + 1).trim();
          if (key && val) mapping[key] = val;
        });
        return mapping[region] || mapping[region?.trim?.()] || projectIdValue;
      }

      if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
        try {
          const parsed = JSON.parse(trimmed);
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            return parsed[region] || projectIdValue;
          }
        } catch (e) {
          return projectIdValue;
        }
      }

      return projectIdValue;
    },
    []
  );

  const getNebiusAuth = useCallback(() => {
    const cred = credentials['nebius'];
    const secret = credentialSecrets['nebius'];
    if (cred && secret) {
      const parsed = parseBackendCredential(cred, secret);
      if (parsed?.serviceAccountId && parsed?.keyId && parsed?.secretKey && parsed?.projectId) {
        return parsed;
      }
    }
    // Legacy fallback during migration
    const raw = localStorage.getItem(storageKey('nebius'));
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (parsed.serviceAccountId && parsed.keyId && parsed.secretKey && parsed.projectId) {
        return parsed;
      }
    } catch (e) {
      return null;
    }
    return null;
  }, [credentials, credentialSecrets]);

  // Nebius launch modal
  const NEBUS_INITIAL_LAUNCH_FORM = {
    presetId: '',
    zoneId: 'eu-north1-a',
    sshPublicKey: '',
    sshKeyName: '',
  };
  const [nebiusLaunchOpen, setNebiusLaunchOpen] = useState(false);
  const [nebiusLaunchForm, setNebiusLaunchForm] = useState(NEBUS_INITIAL_LAUNCH_FORM);
  const [nebiusLaunchLoading, setNebiusLaunchLoading] = useState(false);
  const [nebiusProgress, setNebiusProgress] = useState({
    open: false,
    instanceName: null,
    status: null,
    ip: null,
    startTime: null,
  });
  const handleOpenNebiusLaunch = useCallback(
    (preset) => {
      if (!preset) return;
      const presetId = preset.id || preset.name;
      const presetZones = (Array.isArray(preset.platform_zones) ? preset.platform_zones : []).filter((zone) =>
        nebiusRegion ? zone?.startsWith(nebiusRegion) : true
      );
      const fallbackZone =
        presetZones[0] ||
        nebiusZoneOptions[0] ||
        (nebiusRegion ? `${nebiusRegion}-a` : 'eu-north1-a');

      setNebiusLaunchForm({
        presetId,
        zoneId: fallbackZone,
        sshPublicKey: envSSHKey || '',
        sshKeyName: '',
      });
      setNebiusLaunchOpen(true);
    },
    [nebiusZoneOptions, nebiusRegion]
  );
  useEffect(() => {
    if (!nebiusLaunchOpen) return;
    if (!nebiusAvailablePresets.length) return;
    if (!nebiusLaunchForm.presetId || !nebiusAvailablePresets.some((preset) => (preset.id || preset.name) === nebiusLaunchForm.presetId)) {
      const firstPreset = nebiusAvailablePresets[0];
      setNebiusLaunchForm((prev) => ({
        ...prev,
        presetId: firstPreset?.id || firstPreset?.name || prev.presetId,
      }));
    }
  }, [nebiusLaunchOpen, nebiusAvailablePresets, nebiusLaunchForm.presetId]);
  useEffect(() => {
    if (!nebiusLaunchOpen) return;
    if (!nebiusZoneOptions.length) return;
    if (!nebiusLaunchForm.zoneId || !nebiusZoneOptions.includes(nebiusLaunchForm.zoneId)) {
      setNebiusLaunchForm((prev) => ({
        ...prev,
        zoneId: nebiusZoneOptions[0],
      }));
    }
  }, [nebiusLaunchOpen, nebiusZoneOptions, nebiusLaunchForm.zoneId]);
  const formatGiB = (bytes) => {
    if (!bytes || Number.isNaN(bytes)) return 'N/A';
    return `${(bytes / (1024 ** 3)).toFixed(0)} GiB`;
  };
  const formatPrice = (price) => {
    if (price === null || price === undefined || Number.isNaN(price)) return '—';
    return `€${price}/hour`;
  };
const normalizeAvailability = (cfg, zone) => {
    const raw = cfg.raw || {};
    // Prefer explicit stock for the selected zone if present
    let stockVal = raw.stock ?? cfg.stock ?? cfg.availability ?? null;
    if (!stockVal && raw.stocks && typeof raw.stocks === 'object' && zone) {
      const zoneEntry = raw.stocks[zone] || raw.stocks[zone.toLowerCase()] || raw.stocks[zone.toUpperCase()];
      if (zoneEntry) {
        if (typeof zoneEntry === 'string') stockVal = zoneEntry;
        if (typeof zoneEntry === 'object') stockVal = zoneEntry.availability || zoneEntry.stock || zoneEntry.status;
      }
    }
    // Collect all stock/availability hints
    let signals = [];
    if (stockVal) signals.push(stockVal);
    if (raw.availability) signals.push(raw.availability);
    if (raw.status) signals.push(raw.status);
    if (raw.stocks && typeof raw.stocks === 'object') {
      Object.values(raw.stocks).forEach((entry) => {
        if (!entry) return;
        if (typeof entry === 'string') {
          signals.push(entry);
        } else if (typeof entry === 'object') {
          if (entry.stock) signals.push(entry.stock);
          if (entry.availability) signals.push(entry.availability);
          if (entry.status) signals.push(entry.status);
        }
      });
    }

    const v = signals.map((s) => {
      if (typeof s === 'boolean') return s ? 'available' : 'no_capacity';
      if (typeof s === 'number') return s > 0 ? 'available' : 'no_capacity';
      return (s || '').toString().toLowerCase();
    });
    const any = (keywords) => v.some((s) => keywords.some((k) => s.includes(k)));

    if (any(['available', 'low', 'low_stock', 'lowstock', 'high', 'ok', 'normal', 'yes'])) {
      return { label: 'Available', color: 'success' };
    }
    if (any(['scarce', 'shortage'])) {
      return { label: 'No Capacity', color: 'warning' };
    }
    if (any(['quota', 'limited', 'limit'])) {
      return { label: 'Quota Required', color: 'warning' };
    }
    if (any(['out_of_stock', 'out-of-stock', 'out', 'unavailable', 'no_capacity', 'no-capacity', 'nostock', 'no_stock', 'no'])) {
      return { label: 'No Capacity', color: 'warning' };
    }
    // If we have no signal at all, default to No Capacity (better than Unknown for missing stock)
    return { label: 'No Capacity', color: 'warning' };
  };

  const getScwCommercialType = (cfg = {}) => {
    return cfg.commercial_type || cfg.commercialType || cfg.id || cfg.name || '';
  };

  const formatEuroPrice = (price) => {
    if (price === null || price === undefined) return null;
    const numeric = Number(price);
    if (Number.isNaN(numeric)) return null;
    return `€${numeric.toFixed(numeric >= 1 ? 2 : 3)}/hour`;
  };

  const getScalewayCredentials = useCallback(() => {
    // Prefer backend credentials (work across devices)
    const cred = credentials['scaleway'];
    const secret = credentialSecrets['scaleway'];
    if (cred && secret) {
      const parsed = parseBackendCredential(cred, secret);
      if (parsed?.secretKey) {
        return {
          secretKey: parsed.secretKey,
          projectId: parsed.projectId || '',
          accessKeyId: parsed.accessKeyId || '',
        };
      }
    }

    // Fallback to env vars
    if (process.env.REACT_APP_SCW_ACCESS_KEY && process.env.REACT_APP_SCW_SECRET_KEY) {
      return {
        secretKey: process.env.REACT_APP_SCW_SECRET_KEY,
        projectId: process.env.REACT_APP_SCW_PROJECT_ID || '',
        accessKeyId: process.env.REACT_APP_SCW_ACCESS_KEY,
      };
    }

    // Legacy fallback to localStorage
    const raw = localStorage.getItem(storageKey('scaleway'));
    if (!raw) {
      return null;
    }
    try {
      const parsed = JSON.parse(raw);
      return {
        secretKey: parsed.secretKey || parsed.SCALEWAY_SECRET_KEY,
        projectId: parsed.projectId || parsed.SCALEWAY_PROJECT_ID,
        accessKeyId: parsed.accessKeyId || parsed.SCALEWAY_ACCESS_KEY,
      };
    } catch (e) {
      return null;
    }
  }, [credentials, credentialSecrets]);

  const resetScwLaunchState = () => {
    setScwLaunchForm(SCW_INITIAL_LAUNCH_FORM);
    setScwModalConfigs([]);
    setScwModalLoading(false);
    setScwLaunchConfig(null);
    setScwLaunchPreset(false);
  };

  const handleOpenScwLaunch = (preferredConfig = null) => {
    if (!isProviderConnected('scaleway')) {
      setError('Please integrate with Scaleway before launching instances.');
      return;
    }
    const preferredRegion = preferredConfig?.region || scwLaunchForm.region || scwRegion || scwRegions[0] || '';
    const preferredType = preferredConfig ? getScwCommercialType(preferredConfig) : '';
    const isH100 = preferredType?.toLowerCase().includes('h100');
    setScwLaunchPreset(Boolean(preferredConfig));
    if (preferredConfig) {
      setScwLaunchConfig({ ...preferredConfig, commercialType: preferredType });
    } else {
      setScwLaunchConfig(null);
    }
    setScwLaunchForm({
      region: preferredRegion,
      publicKey: envSSHKey || process.env.REACT_APP_SCW_SSH_PUBLIC_KEY || '',
      sshKeyName: 'runara-key',
      commercialType: preferredType,
      rootVolumeSize: null,
      rootVolumeType: isH100 ? 'sbs_volume' : null, // Auto-set sbs_volume for H100
    });
    setScwModalConfigs([]);
    setScwLaunchOpen(true);
    if (preferredRegion && !preferredConfig) {
      loadScwModalConfigs(preferredRegion, preferredType);
    }
  };
  
  // Form state
  const [formData, setFormData] = useState({
    scaleway: {
      accessKeyId: process.env.REACT_APP_SCW_ACCESS_KEY || '',
      secretKey: process.env.REACT_APP_SCW_SECRET_KEY || '',
      projectId: process.env.REACT_APP_SCW_PROJECT_ID || ''
    }
  });

  // Fetch Scaleway products for selected region
  const fetchScalewayConfigs = useCallback(async (regionOverride = null, options = {}) => {
    const zone = regionOverride || scwRegion;

    // Use centralized credential resolver (checks backend store, env vars, localStorage)
    const resolvedCreds = getScalewayCredentials();

    console.log('🔍 fetchScalewayConfigs:', {
      zone,
      hasResolvedCreds: !!resolvedCreds,
      hasSecretKey: !!resolvedCreds?.secretKey,
      hasAccessKey: !!resolvedCreds?.accessKeyId,
      hasProjectId: !!resolvedCreds?.projectId,
    });

    if (!resolvedCreds || !resolvedCreds.secretKey) {
      const errorMsg = 'Scaleway credentials not found. Please integrate first.';
      console.error('❌ fetchScalewayConfigs:', errorMsg);
      setError(errorMsg);
      return [];
    }

    const secretKey = resolvedCreds.secretKey;
    const accessKey = resolvedCreds.accessKeyId || '';
    const projectId = resolvedCreds.projectId || '';

    const silent = options.silent || false;
    const skipState = options.skipState || false;
    if (!silent) {
      setScwLoading(true);
    }
    setError('');
    try {
      const res = await apiService.getScalewayProducts({
        zone,
        secretKey,
        accessKey,
        projectId,
        gpuOnly: true
      });
      const servers = res.servers || res.data || [];
      if (!servers || servers.length === 0) {
        if (!skipState) {
          setScwConfigs([]);
        }
        if (!silent) {
          setMessage(`No products returned for ${zone}. Region may have no capacity.`);
        }
      } else {
        if (!skipState) {
          setScwConfigs(servers);
        }
        if (!silent) {
          setMessage(`Loaded ${servers.length} Scaleway configurations for ${zone}`);
        }
      }
      return servers;
    } catch (e) {
      console.error('Scaleway fetch error:', e);
      if (!skipState) {
        setScwConfigs([]);
      }
      let msg = `Failed to load Scaleway configurations for ${zone}`;
      if (e.response?.status === 401) {
        msg = 'Invalid Scaleway credentials. Please re-integrate.';
      } else if (e.response?.status === 403) {
        msg = 'Access denied for Scaleway credentials.';
      } else if (e.message) {
        msg = `${msg}: ${e.message}`;
      }
      setError(msg);
    } finally {
      if (!silent) {
        setScwLoading(false);
      }
      return [];
    }
  }, [scwRegion, getScalewayCredentials]);

  // Check if provider is connected (from backend credentials, fallback to localStorage)
  const isProviderConnected = (_providerId) => {
    // Check env vars first (hardcoded credentials)
    if (process.env.REACT_APP_SCW_ACCESS_KEY && process.env.REACT_APP_SCW_SECRET_KEY) {
      return true;
    }

    // Check backend credentials
    const cred = credentials['scaleway'];
    const secret = credentialSecrets['scaleway'];
    if (cred && secret) {
      const parsed = parseBackendCredential(cred, secret);
      return !!(parsed?.accessKeyId && parsed?.secretKey);
    }

    // Fallback to localStorage
    const stored = localStorage.getItem(storageKey('scaleway'));
    if (!stored) return false;
    try {
      const parsed = JSON.parse(stored);
      return !!(parsed.accessKeyId && parsed.secretKey);
    } catch (e) {
      return false;
    }
  };

  const loadScwModalConfigs = useCallback(async (region, currentTypeOverride = null) => {
    if (!region) {
      setScwModalConfigs([]);
      setScwLaunchForm((prev) => ({ ...prev, commercialType: '' }));
      return;
    }
    setScwModalLoading(true);
    try {
      const servers = await fetchScalewayConfigs(region, { silent: true, skipState: true });
      setScwModalConfigs(servers || []);
      const currentType = currentTypeOverride !== null ? currentTypeOverride : scwLaunchForm.commercialType;
      const hasCurrent = servers?.some((cfg) => getScwCommercialType(cfg) === currentType);
      let nextType = currentType || '';
      if (!hasCurrent) {
        nextType = servers && servers.length > 0 ? getScwCommercialType(servers[0]) : '';
      }
      setScwLaunchForm((prev) => ({ ...prev, commercialType: nextType }));
    } catch (e) {
      console.error('Failed to load Scaleway modal configs', e);
      setScwModalConfigs([]);
      setScwLaunchForm((prev) => ({ ...prev, commercialType: '' }));
    } finally {
      setScwModalLoading(false);
    }
  }, [fetchScalewayConfigs, scwLaunchForm.commercialType]);

  const fetchScalewayInstances = useCallback(async (regionOverride = null, options = {}) => {
    const zone = regionOverride || scwRegion;
    const showGlobalLoading = options.showGlobalLoading !== false;
    if (showGlobalLoading) {
      setLoading(true);
    }
    setError('');
    setMessage('');
    try {
      const creds = getScalewayCredentials();
      if (!creds) {
        setError('Scaleway credentials not found. Please integrate first.');
        setInstances(prev => ({ ...prev, scaleway: [] }));
        return;
      }
      const { secretKey, projectId } = creds;
      if (!secretKey) {
        setError('Scaleway secret key missing. Please re-integrate.');
        setInstances(prev => ({ ...prev, scaleway: [] }));
        return;
      }
      const res = await apiService.getScalewayInstances({
        zone,
        secretKey,
        projectId,
      });
      const servers = res.servers || [];
      setInstances(prev => ({ ...prev, scaleway: servers }));
      setScwInstancesZone(zone);
      setExpandedProvider('scaleway');
      const suffix = servers.length === 1 ? '' : 's';
      setMessage(`Loaded ${servers.length} Scaleway instance${suffix} in ${zone}.`);
      setLastUpdated(Date.now());
    } catch (e) {
      console.error('Scaleway instances fetch error:', e);
      if (e.response?.status === 401) {
        setError('Invalid Scaleway credentials. Please re-integrate.');
      } else if (e.response?.status === 403) {
        setError('Access denied for Scaleway credentials.');
      } else if (e.response?.status === 404) {
        setError('No Scaleway instances found for this region.');
      } else if (e.message?.toLowerCase().includes('timeout')) {
        setError('Scaleway API timed out. Please try again.');
      } else {
        setError(e?.response?.data?.detail || e.message || 'Failed to fetch Scaleway instances');
      }
      setInstances(prev => ({ ...prev, scaleway: [] }));
      setScwInstancesZone(zone);
    } finally {
      if (showGlobalLoading) {
        setLoading(false);
      }
    }
  }, [getScalewayCredentials, scwRegion]);

  const handleDeleteScwInstance = useCallback(async () => {
    const confirmed = await confirm({
      title: 'Delete instance?',
      description: `Are you sure you want to delete ${scwDeleteDialog.instance?.displayName || 'this instance'}?`,
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel'
    });
    if (!confirmed) return;
    if (!scwDeleteDialog.instance) return;
    const creds = getScalewayCredentials();
    if (!creds || !creds.secretKey) {
      setError('Scaleway credentials not found. Please re-integrate.');
      return;
    }
    const zone = scwDeleteDialog.instance.zone || scwRegion;
    setScwDeleteLoading(true);
    setError('');
    try {
      await apiService.deleteScalewayInstance({
        zone,
        serverId: scwDeleteDialog.instance.id,
        secretKey: creds.secretKey,
        projectId: creds.projectId,
      });
      setMessage(`Deleted ${scwDeleteDialog.instance.displayName || scwDeleteDialog.instance.id}`);
      showToast({ message: 'Instance deletion started', severity: 'success' });
      await fetchScalewayInstances(zone, { showGlobalLoading: false });
    } catch (e) {
      console.error('Scaleway delete error', e);
      if (e.response?.status === 404) {
        setError('Instance not found. It may have already been deleted.');
      } else if (e.response?.status === 401) {
        setError('Invalid Scaleway credentials.');
      } else {
        setError(e?.response?.data?.detail || e.message || 'Failed to delete Scaleway instance');
      }
    } finally {
      setScwDeleteLoading(false);
      setScwDeleteDialog({ open: false, instance: null });
    }
  }, [fetchScalewayInstances, getScalewayCredentials, scwDeleteDialog, scwRegion]);

  const fetchNebiusConfigs = useCallback(async (regionOverride = null) => {
    const parsed = getNebiusAuth();
    if (!parsed) {
      setError('Nebius credentials not found or incomplete. Please integrate first.');
      return;
    }
    const credentialsPayload = {
      service_account_id: parsed.serviceAccountId,
      key_id: parsed.keyId,
      private_key: parsed.secretKey,
    };

    setNebiusLoading(true);
    setError('');
    try {
      // Use the new /api/v1/nebius/presets endpoint
      const targetRegion = regionOverride || nebiusRegion;
      const resolvedProjectId = resolveNebiusProjectId(parsed.projectId, targetRegion);
      const presetResponse = await apiService.getNebiusPresets(credentialsPayload, resolvedProjectId, targetRegion);
      const { presets, quota, project_id } = parseNebiusPresetResponse(presetResponse);
      // Use the resolved project_id from backend (may differ from parsed.projectId if region mapping is used)
      const effectiveProjectId = project_id || resolvedProjectId || parsed.projectId;
      setNebiusProjectId(effectiveProjectId);
      setNebiusConfigs(presets);
      setNebiusQuota(quota);
      if (presets.length > 0) {
        setMessage(`Loaded ${presets.length} Nebius presets for project ${effectiveProjectId}`);
      }
    } catch (e) {
      console.error('Nebius fetch error:', e);
      let msg = `Failed to load Nebius presets`;
      if (e.response?.status === 401) {
        msg = 'Nebius credentials were rejected. Please double-check your Service Account ID, Key ID, Project ID, and Private Key.';
      } else if (e.response?.status === 403) {
        msg = 'Nebius API access denied for these credentials.';
      } else if (e.response?.data?.detail) {
        msg = e.response.data.detail;
      } else if (e.message) {
        msg = `${msg}: ${e.message}`;
      }
      setError(msg);
      setNebiusConfigs([]);
      setNebiusQuota(null);
    } finally {
      setNebiusLoading(false);
    }
  }, [getNebiusAuth, nebiusRegion]);

  // Fetch Nebius instances using the new Direct API endpoints
  const fetchNebiusInstances = useCallback(async () => {
    const parsed = getNebiusAuth();
    if (!parsed) {
      setError('Nebius credentials not found or incomplete. Please integrate first.');
      return;
    }
    const credentialsPayload = {
      service_account_id: parsed.serviceAccountId,
      key_id: parsed.keyId,
      private_key: parsed.secretKey,
    };

    setLoading(true);
    setError('');
    setMessage('');

    try {
      // Remember project for console links
      const effectiveProjectId = resolveNebiusProjectId(parsed.projectId, nebiusRegion);
      setNebiusProjectId(effectiveProjectId);

      // Fetch instances
      const instancesList = await apiService.getNebiusInstances(credentialsPayload, effectiveProjectId);
      
      // Also fetch presets for display
      const presetsListResp = await apiService.getNebiusPresets(credentialsPayload, effectiveProjectId, nebiusRegion);
      const { presets: parsedPresets, quota } = parseNebiusPresetResponse(presetsListResp);
      
      // Update instances state
      setInstances((prev) => {
        const newState = {
          ...prev,
          nebius: instancesList || []
        };
        console.log('New instances state - nebius:', newState.nebius?.length || 0, 'instances');
        return newState;
      });

      // Update presets/configs for launch dialog
      if (parsedPresets && parsedPresets.length > 0) {
        setNebiusConfigs(parsedPresets);
        setNebiusQuota(quota);
        setMessage(`Loaded ${instancesList?.length || 0} Nebius instances and ${parsedPresets.length} presets`);
      } else {
        setMessage(`Loaded ${instancesList?.length || 0} Nebius instances`);
      }
      setLastUpdated(Date.now());

    } catch (e) {
      console.error('Nebius instances fetch error:', e);
      let errorMessage = 'Failed to fetch Nebius instances';
      if (e.response?.status === 401) {
        errorMessage = 'Nebius credentials were rejected. Please double-check your Service Account ID, Project ID, Key ID, and Private Key.';
      } else if (e.response?.status === 403) {
        errorMessage = 'Nebius API access denied for these credentials.';
      } else if (e.response?.data?.detail) {
        errorMessage = e.response.data.detail;
        // Check if it's the NotImplementedError about protobuf files
        if (errorMessage.includes('protobuf files not available') || errorMessage.includes('NotImplementedError')) {
          errorMessage = 'Instance listing requires additional protobuf files. The presets endpoint should work.';
        }
      } else if (e.message) {
        errorMessage = `${errorMessage}: ${e.message}`;
      }
      setError(errorMessage);
      setInstances((prev) => ({
        ...prev,
        nebius: []
      }));
      setNebiusQuota(null);
    } finally {
      setLoading(false);
    }
  }, [getNebiusAuth, nebiusRegion]);

  // Launch Nebius instance
  const handleLaunchNebiusInstance = async () => {
    const parsed = getNebiusAuth();
    if (!parsed) {
      setError('Nebius credentials not found or incomplete. Please integrate first.');
      return;
    }
    if (!nebiusLaunchForm.presetId || !nebiusLaunchForm.sshPublicKey) {
      setError('Please select a preset and provide an SSH public key.');
      return;
    }

    const credentialsPayload = {
      service_account_id: parsed.serviceAccountId,
      key_id: parsed.keyId,
      private_key: parsed.secretKey,
    };

    setNebiusLaunchLoading(true);
    setError('');
    setMessage('');

    try {
      const result = await apiService.launchNebiusInstance(
        credentialsPayload,
        parsed.projectId,
        nebiusLaunchForm.presetId,
        nebiusLaunchForm.sshPublicKey,
        nebiusLaunchForm.zoneId || null,
        nebiusLaunchForm.sshKeyName?.trim() || null
      );
      
      const instName = result.instance_name || result.operation_id || 'Nebius Instance';
      setMessage(`Instance launch initiated: ${instName}`);
      setNebiusLaunchOpen(false);
      setNebiusLaunchForm(NEBUS_INITIAL_LAUNCH_FORM);

      // Open progress dialog to poll for IP
      setNebiusProgress({
        open: true,
        instanceName: instName,
        status: 'launching',
        ip: null,
        startTime: Date.now(),
      });

      // Activate full-screen loading
      setLaunchingScreen({
        active: true,
        provider: 'nebius',
        phase: 'launching',
        ip: null,
        instanceName: instName,
        sshUser: 'ubuntu',
      });

      // Refresh instances after a short delay
      setTimeout(() => {
        fetchNebiusInstances();
      }, 2000);
    } catch (e) {
      console.error('Nebius launch error:', e);
      let errorMessage = 'Failed to launch Nebius instance';
      if (e.response?.status === 401) {
        errorMessage = 'Nebius credentials were rejected. Please double-check your credentials.';
      } else if (e.response?.status === 403) {
        errorMessage = 'Nebius API access denied for these credentials.';
      } else if (e.response?.data?.detail) {
        errorMessage = e.response.data.detail;
        if (errorMessage.includes('protobuf files not available') || errorMessage.includes('NotImplementedError')) {
          errorMessage = 'Instance launching requires additional protobuf files. Please use the Nebius Console to launch instances for now.';
        }
      } else if (e.message) {
        errorMessage = `${errorMessage}: ${e.message}`;
      }
      setError(errorMessage);
    } finally {
      setNebiusLaunchLoading(false);
    }
  };

  const handleDeleteNebiusInstance = useCallback(async () => {
    const confirmed = await confirm({
      title: 'Delete instance?',
      description: `Are you sure you want to delete ${nebiusDeleteDialog.instance?.name || 'this instance'}?`,
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel'
    });
    if (!confirmed) return;
    if (!nebiusDeleteDialog.instance) return;
    const parsed = getNebiusAuth();
    if (!parsed) {
      setError('Nebius credentials not found or incomplete. Please integrate first.');
      return;
    }

    const credentialsPayload = {
      service_account_id: parsed.serviceAccountId,
      key_id: parsed.keyId,
      private_key: parsed.secretKey,
    };

    setNebiusDeleteLoading(true);
    setError('');
    setMessage('');

    try {
      await apiService.deleteNebiusInstance(
        credentialsPayload,
        parsed.projectId,
        nebiusDeleteDialog.instance.id
      );
      setMessage(`Deletion started for ${nebiusDeleteDialog.instance.name || nebiusDeleteDialog.instance.id}`);
      showToast({ message: 'Instance deletion started', severity: 'success' });
      setNebiusDeleteDialog({ open: false, instance: null });
      fetchNebiusInstances();
    } catch (e) {
      console.error('Nebius delete error:', e);
      let errorMessage = 'Failed to delete Nebius instance';
      if (e.response?.status === 401) {
        errorMessage = 'Nebius credentials were rejected. Please double-check your credentials.';
      } else if (e.response?.status === 403) {
        errorMessage = 'Nebius API access denied for these credentials.';
      } else if (e.response?.data?.detail) {
        errorMessage = e.response.data.detail;
      } else if (e.message) {
        errorMessage = `${errorMessage}: ${e.message}`;
      }
      setError(errorMessage);
    } finally {
      setNebiusDeleteLoading(false);
    }
  }, [getNebiusAuth, nebiusDeleteDialog, fetchNebiusInstances]);

  // Fetch aggregated instances from all providers
  const fetchAggregatedInstances = useCallback(async () => {
    setAggregatedLoading(true);
    setError('');
    setMessage('');
    try {
      const instances = await apiService.getAggregatedCatalog();
      setAggregatedInstances(instances);
      setLastUpdated(Date.now());
      showToast({ 
        message: `Loaded ${instances.length} instance${instances.length === 1 ? '' : 's'} from all providers`, 
        severity: 'success', 
        duration: 3000 
      });
    } catch (e) {
      console.error('Aggregated instances fetch error:', e);
      let errorMessage = 'Failed to fetch aggregated instances';
      if (e.response?.status === 401) {
        errorMessage = 'Authentication required. Please log in again.';
      } else if (e.response?.status === 403) {
        errorMessage = 'You do not have permission to access instances.';
      } else if (e.response?.data?.detail) {
        errorMessage = e.response.data.detail;
      } else if (e.message) {
        errorMessage = `${errorMessage}: ${e.message}`;
      }
      setError(errorMessage);
      setAggregatedInstances([]);
    } finally {
      setAggregatedLoading(false);
    }
  }, [showToast]);

  // Clear any local cached credentials when switching users to avoid cross-account leakage
  useEffect(() => {
    const currentId = user?.user_id || null;
    const prevId = lastUserIdRef.current;
    if (prevId && prevId !== currentId) {
      PROVIDERS.forEach((p) => localStorage.removeItem(storageKey(p.id)));
    }
    
    // Load credentials from localStorage into formData
    try {
      const raw = localStorage.getItem(storageKey('scaleway'));
      if (raw) {
        const parsed = JSON.parse(raw);
        setFormData(prev => ({
          ...prev,
          scaleway: {
            accessKeyId: parsed.accessKeyId || parsed.SCALEWAY_ACCESS_KEY || parsed.apiKey || prev.scaleway.accessKeyId,
            secretKey: parsed.secretKey || parsed.SCALEWAY_SECRET_KEY || prev.scaleway.secretKey,
            projectId: parsed.projectId || parsed.SCALEWAY_PROJECT_ID || prev.scaleway.projectId
          }
        }));
      }
    } catch (e) {
      // ignore
    }
    
    if (!currentId) {
      PROVIDERS.forEach((p) => localStorage.removeItem(storageKey(p.id)));
    }
    lastUserIdRef.current = currentId;
  }, [user]);

  // Load existing credentials from backend
  useEffect(() => {
    if (!isAuthenticated) {
      setCredentialsLoading(false);
      return;
    }
    
    const loadCredentials = async () => {
      try {
        setCredentialsLoading(true);
        const credsList = await apiService.listCredentialsWithSecrets();
        
        // Group credentials by provider (prefer name === 'default')
        const credsByProvider = {};
        const secretsByProvider = {};
        
        for (const cred of credsList) {
          if (!credsByProvider[cred.provider] || cred.name === 'default') {
            credsByProvider[cred.provider] = cred;
            secretsByProvider[cred.provider] = cred.secret;
          }
        }
        
        setCredentials(prev => ({
          ...prev,
          ...credsByProvider
        }));
        setCredentialSecrets(prev => ({
          ...prev,
          ...secretsByProvider
        }));
        
        // Load credentials into form data
        PROVIDERS.forEach(provider => {
          const cred = credsByProvider[provider.id];
          const secret = secretsByProvider[provider.id];
          if (cred && secret) {
            const parsed = parseBackendCredential(cred, secret);
            if (parsed) {
              setFormData(prev => ({
                ...prev,
                scaleway: {
                  accessKeyId: parsed.accessKeyId || prev.scaleway.accessKeyId,
                  secretKey: parsed.secretKey || prev.scaleway.secretKey,
                  projectId: parsed.projectId || prev.scaleway.projectId
                }
              }));
            }
          }
        });
      } catch (e) {
        console.error('Failed to load credentials:', e);
      } finally {
        setCredentialsLoading(false);
      }
    };
    
    loadCredentials();
  }, [isAuthenticated]);

  // Migrate localStorage credentials to backend (one-time migration for any authenticated user)
  useEffect(() => {
    const migrateLocalStorageCredentials = async () => {
      if (!isAuthenticated || credentialsLoading) return;

      // Check if we already have backend credentials - if so, skip migration
      const hasBackendCreds = Object.keys(credentials).length > 0;
      if (hasBackendCreds) return;

      try {
        const token = localStorage.getItem('auth_token');
        if (!token) return;
        
        // Migrate each provider's credentials from localStorage
        for (const provider of PROVIDERS) {
          const raw = localStorage.getItem(storageKey(provider.id));
          if (!raw) continue;
          
          try {
            const parsed = JSON.parse(raw);
            let secret = '';
            let credentialType = 'api_key';
            
            if (!parsed.accessKeyId && !parsed.SCALEWAY_ACCESS_KEY) continue;
            secret = JSON.stringify({
              accessKeyId: parsed.accessKeyId || parsed.SCALEWAY_ACCESS_KEY || parsed.apiKey,
              secretKey: parsed.secretKey || parsed.SCALEWAY_SECRET_KEY,
              projectId: parsed.projectId || parsed.SCALEWAY_PROJECT_ID
            });
            credentialType = 'access_key';
            
            if (secret) {
              await apiService.saveCredential(
                provider.id,
                'default',
                credentialType,
                secret,
                `${provider.name} credentials (migrated from localStorage)`
              );
              console.log(`Migrated ${provider.id} credentials to backend`);
            }
          } catch (e) {
            console.warn(`Failed to migrate ${provider.id} credentials:`, e);
          }
        }
        
        // Reload credentials after migration
        const credsList = await apiService.listCredentials();
        const credsByProvider = {};
        const secretsByProvider = {};
        
        for (const cred of credsList) {
          if (!credsByProvider[cred.provider] || cred.name === 'default') {
            credsByProvider[cred.provider] = cred;
            try {
              const credWithSecret = await apiService.getCredential(cred.credential_id);
              secretsByProvider[cred.provider] = credWithSecret.secret;
            } catch (e) {
              console.warn(`Failed to fetch secret for ${cred.provider}:`, e);
            }
          }
        }
        
        setCredentials(credsByProvider);
        setCredentialSecrets(secretsByProvider);
      } catch (e) {
        console.error('Migration failed:', e);
      }
    };
    
    migrateLocalStorageCredentials();
  }, [isAuthenticated, credentialsLoading, credentials]);


  // Auto-connect Scaleway using hardcoded env credentials
  const autoConnectRef = useRef(false);
  useEffect(() => {
    if (autoConnectRef.current) return;
    const accessKey = process.env.REACT_APP_SCW_ACCESS_KEY;
    const secretKey = process.env.REACT_APP_SCW_SECRET_KEY;
    if (accessKey && secretKey) {
      // Save to localStorage so isProviderConnected returns true immediately
      const projectId = process.env.REACT_APP_SCW_PROJECT_ID || '';
      const credsObj = { accessKeyId: accessKey, secretKey: secretKey, projectId };
      localStorage.setItem(storageKey('scaleway'), JSON.stringify(credsObj));
      autoConnectRef.current = true;

      // Also auto-save to backend if authenticated
      if (isAuthenticated && !credentials['scaleway']) {
        const secret = JSON.stringify(credsObj);
        apiService.saveCredential('scaleway', 'default', 'access_key', secret, 'Scaleway credentials')
          .then((savedCred) => {
            setCredentials(prev => ({ ...prev, scaleway: savedCred }));
            setCredentialSecrets(prev => ({ ...prev, scaleway: secret }));
          })
          .catch((e) => console.warn('Auto-save credentials failed:', e));
      }
    }
  }, [isAuthenticated, credentials]);

  // Auto-load Scaleway regions and default select connected provider
  useEffect(() => {
    loadScwRegions();
  }, []);

  // Auto-load Scaleway configs when selected and connected
  useEffect(() => {
    if (selectedProvider === 'scaleway' && isProviderConnected('scaleway')) {
      fetchScalewayConfigs(scwRegion);
      fetchScalewayInstances(scwRegion, { showGlobalLoading: false });
    }
  }, [selectedProvider, scwRegion, fetchScalewayConfigs, fetchScalewayInstances]);


  useEffect(() => {
    if (!scwLaunchOpen) return;
    if (scwLaunchPreset) return;
    if (!Array.isArray(scwModalConfigs) || scwModalConfigs.length === 0) {
      if (scwLaunchForm.commercialType) {
        setScwLaunchForm((prev) => ({ ...prev, commercialType: '' }));
      }
      return;
    }
    const exists = scwModalConfigs.some((cfg) => getScwCommercialType(cfg) === scwLaunchForm.commercialType);
    if (!exists) {
      const first = scwModalConfigs[0];
      if (first) {
        setScwLaunchForm((prev) => ({ ...prev, commercialType: getScwCommercialType(first) }));
      }
    }
  }, [scwModalConfigs, scwLaunchOpen, scwLaunchPreset, scwLaunchForm.commercialType]);

  const { open: scwProgressOpen, serverId: scwProgressServerId, zone: scwProgressZone, refreshedInstances: scwProgressRefreshed } = scwProgress;


  // Poll Scaleway server status when progress dialog is open
  useEffect(() => {
    if (!scwProgressOpen || !scwProgressServerId) return;
    let intervalId;
    const poll = async () => {
      try {
        const cred = credentials['scaleway'];
        const secret = credentialSecrets['scaleway'];
        if (!cred || !secret) return;
        
        const secretData = typeof secret === 'string' ? JSON.parse(secret) : secret;
        const secretKey = secretData.secretKey || secretData.secret_key || '';
        const projectId = secretData.projectId || secretData.project_id || '';
        if (!secretKey) return;
        const res = await apiService.getScalewayServerStatus({
          zone: scwProgressZone,
          serverId: scwProgressServerId,
          secretKey,
          projectId,
        });
        setScwProgress((prev) => ({
          ...prev,
          status: res.status || prev.status,
          ip: res.ip || prev.ip,
          stateDetail: res.state_detail || prev.stateDetail,
        }));
        const statusLower = (res.status || '').toLowerCase();
        const hasIp = Boolean(res.ip);
        const isReady = statusLower === 'running' || statusLower === 'ready';
        // Update full-screen loading phase
        if (hasIp) {
          setLaunchingScreen((prev) => prev.active ? { ...prev, phase: isReady ? 'ready' : 'waiting_ip', ip: res.ip } : prev);
        }
        // Refresh instances periodically when running, even without IP (to catch delayed IP assignment)
        // Also refresh immediately when IP first appears
        if (statusLower === 'running') {
          // Always refresh instances when running to catch IPs assigned after launch
          if (!scwProgressRefreshed || hasIp) {
            await fetchScalewayInstances(scwProgressZone || scwRegion, { showGlobalLoading: false });
            setScwProgress((prev) => ({
              ...prev,
              refreshedInstances: true,
              ip: res.ip || prev.ip
            }));
          }
        }
        // Stop polling and auto-redirect when we have an IP (instance is usable)
        if (hasIp) {
          clearInterval(intervalId);
          setLaunchingScreen((prev) => prev.active ? { ...prev, phase: 'ready', ip: res.ip } : prev);
          // Auto-redirect to Run Workload after a brief delay
          setTimeout(() => {
            setScwProgress((prev) => ({ ...prev, open: false }));
            setLaunchingScreen({ active: false, provider: null, phase: 'launching', ip: null, instanceName: null, sshUser: 'ubuntu' });
            navigate('/profiling', {
              state: {
                openRunWorkload: true,
                instanceData: {
                  ipAddress: res.ip,
                  sshUser: 'root',
                  provider: 'scaleway',
                },
              },
            });
          }, 2000);
        }
        // Stop polling after 3 minutes even without IP (instance might need manual flexible IP)
        const startTime = scwProgress.startTime || Date.now();
        if (Date.now() - startTime > 180000) {
          clearInterval(intervalId);
        }
      } catch (e) {
        console.warn('Scaleway status poll failed', e);
      }
    };
    poll();
    intervalId = setInterval(poll, 6000);
    return () => clearInterval(intervalId);
  }, [scwProgressOpen, scwProgressServerId, scwProgressZone, scwProgressRefreshed, fetchScalewayInstances, scwRegion, credentials, credentialSecrets]);

  // Poll Nebius instances when progress dialog is open to find IP
  useEffect(() => {
    if (!nebiusProgress.open || !nebiusProgress.instanceName) return;
    let intervalId;
    const poll = async () => {
      try {
        const parsed = getNebiusAuth();
        if (!parsed) return;
        const credentialsPayload = {
          service_account_id: parsed.serviceAccountId,
          key_id: parsed.keyId,
          private_key: parsed.secretKey,
        };
        const effectiveProjectId = resolveNebiusProjectId(parsed.projectId, nebiusRegion);
        const instancesList = await apiService.getNebiusInstances(credentialsPayload, effectiveProjectId);
        // Find the launched instance by name
        const found = (instancesList || []).find(
          (inst) => inst.name === nebiusProgress.instanceName || inst.id === nebiusProgress.instanceName
        );
        if (found) {
          const ip = found.public_ip || found.ip || found.network_interfaces?.[0]?.primary_v4_address?.one_to_one_nat?.address || null;
          const foundStatus = (found.status || 'launching').toLowerCase();
          setNebiusProgress((prev) => ({ ...prev, status: foundStatus, ip: ip || prev.ip }));
          // Update full-screen loading
          if (ip) {
            setLaunchingScreen((prev) => prev.active ? { ...prev, phase: 'waiting_ip', ip } : prev);
          }
          if (ip && (foundStatus === 'running' || foundStatus === 'ready')) {
            clearInterval(intervalId);
            setLaunchingScreen((prev) => prev.active ? { ...prev, phase: 'ready' } : prev);
            // Auto-redirect to Run Workload
            setTimeout(() => {
              setNebiusProgress((prev) => ({ ...prev, open: false }));
              setLaunchingScreen({ active: false, provider: null, phase: 'launching', ip: null, instanceName: null, sshUser: 'ubuntu' });
              navigate('/profiling', {
                state: {
                  openRunWorkload: true,
                  instanceData: {
                    ipAddress: ip,
                    sshUser: 'ubuntu',
                    provider: 'nebius',
                  },
                },
              });
            }, 2000);
          }
        }
        // Stop polling after 5 minutes
        if (Date.now() - (nebiusProgress.startTime || Date.now()) > 300000) {
          clearInterval(intervalId);
        }
      } catch (e) {
        console.warn('Nebius progress poll failed', e);
      }
    };
    // Start polling after initial delay (instance needs time to appear)
    const initialTimeout = setTimeout(() => {
      poll();
      intervalId = setInterval(poll, 8000);
    }, 5000);
    return () => {
      clearTimeout(initialTimeout);
      if (intervalId) clearInterval(intervalId);
    };
  }, [nebiusProgress.open, nebiusProgress.instanceName, nebiusProgress.startTime, getNebiusAuth, nebiusRegion, navigate]);

  const handleOpenModal = (providerId) => {
    setOpenModal(providerId);
    setError('');
    setMessage('');
  };

  const handleCloseModal = () => {
    setOpenModal(null);
    setError('');
  };

  const handleInputChange = (providerId, field, value) => {
    setFormData(prev => ({
      ...prev,
      [providerId]: {
        ...prev[providerId],
        [field]: value
      }
    }));
  };

  const validateAndSave = async (providerId) => {
    const provider = PROVIDERS.find(p => p.id === providerId);
    const data = formData[providerId];
    
    setError('');
    setMessage('');
    
    // Validate Scaleway credentials
    if (!data.accessKeyId || !data.secretKey || !data.projectId) {
      setError('Please provide Scaleway Access Key, Secret Key, and Project ID');
      return false;
    }

    // Save to backend
    try {
      if (!isAuthenticated) {
        setError('You must be logged in to save credentials');
        return false;
      }
      
      const secret = createBackendSecret(providerId, data);
      const existingCred = credentials[providerId];
      
      let savedCred;
      if (existingCred) {
        // Update existing credential
        savedCred = await apiService.updateCredential(
          existingCred.credential_id,
          'default',
          `${provider.name} credentials`,
          null,
          secret
        );
      } else {
        // Create new credential
        savedCred = await apiService.saveCredential(
          providerId,
          'default',
          providerId === 'lambda' ? 'api_key' : 'access_key',
          secret,
          `${provider.name} credentials`
        );
      }
      
      // Update local credentials state IMMEDIATELY with the secret we just saved
      // This ensures isProviderConnected returns true right away
      const secretToStore = providerId === 'lambda' ? data.apiKey : secret;
      
      // Update credentials state - ensure savedCred has provider field
      // The API returns a CredentialDetail which should have provider field, but ensure it's set
      const credToStore = savedCred.provider ? savedCred : {
        ...savedCred,
        provider: providerId  // Ensure provider field is set if missing
      };
      const credWithSecretFlag = {
        ...credToStore,
        secret_available: true
      };
      
      // Scaleway-specific logging
      if (providerId === 'scaleway') {
        console.log('🔍 Scaleway credential save:', {
          credentialId: credWithSecretFlag.credential_id,
          secretLength: secretToStore?.length,
          secretPreview: secretToStore ? secretToStore.substring(0, 50) + '...' : null,
          isJSON: (() => {
            try {
              JSON.parse(secretToStore);
              return true;
            } catch {
              return false;
            }
          })()
        });
      }
      
      // Update state - use functional updates to ensure we get the latest state
      setCredentials(prev => {
        const newState = {
          ...prev,
          [providerId]: credWithSecretFlag
        };
        return newState;
      });
      
      setCredentialSecrets(prev => {
        const newState = {
          ...prev,
          [providerId]: secretToStore
        };
        return newState;
      });
      
      // Force a check after state update (Scaleway only)
      if (providerId === 'scaleway') {
        setTimeout(() => {
          const isConnected = isProviderConnected(providerId);
          console.log('🔍 Scaleway after state update:', {
            isConnected,
            hasCred: !!credentials[providerId],
            hasSecret: !!credentialSecrets[providerId]
          });
        }, 100);
      }
      
      setMessage(`${provider.name} credentials saved successfully`);
      setSelectedProvider(providerId);
      handleCloseModal();
      
      // Auto-fetch instances after saving
      try {
        await fetchScalewayConfigs();
      } catch (fetchError) {
        console.error('Auto-fetch after save failed:', fetchError);
        // Error is already handled by fetch functions
      }
      
      return true;
    } catch (e) {
      console.error('❌ Save credentials error:', e);
      console.error('❌ Error details:', {
        status: e.response?.status,
        statusText: e.response?.statusText,
        data: e.response?.data,
        message: e.message,
        providerId,
      });
      
      if (e.response?.status === 401) {
        setError('Authentication required. Please log out and log back in to refresh your token.');
        console.error('❌ Authentication failed - token may be expired or invalid');
      } else if (e.response?.status === 403) {
        setError('You do not have permission to save credentials.');
      } else if (e.response?.status === 409) {
        // Conflict - credential already exists (shouldn't happen with upsert, but handle gracefully)
        const detail = e.response?.data?.detail || 'Credential already exists';
        if (detail.includes('updated')) {
          // If backend says it was updated, treat as success
          console.log('✅ Credential updated successfully (409 conflict resolved)');
          setMessage(`${provider.name} credentials updated successfully`);
          handleCloseModal();
          return true;
        }
        setError(detail || 'A credential with this name already exists. Please use a different name or update the existing one.');
      } else if (e.message?.includes('JSON')) {
        setError('Invalid JSON format. Please check your credentials and try again.');
      } else if (!e.response) {
        // Network error or request didn't reach backend
        setError(`Network error: Failed to connect to server. Please check your internet connection and try again.`);
        console.error('❌ Network error - request may not have reached backend');
      } else {
        setError(`Failed to save credentials: ${e.response?.data?.detail || e.message || 'Unknown error'}`);
      }
      return false;
    }
  };

  // Fetch Lambda instances AND available instance types
  const fetchLambdaInstances = async (apiKey) => {
    if (!apiKey) {
      setError('Please provide a valid Lambda Labs API key');
      return;
    }
    setLoading(true);
    setError('');
    setMessage('');
    try {
      // Add timeout wrapper to prevent hanging (match axios timeout of 90s)
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Request timeout: API call took too long')), 95000)
      );
      
      // Fetch both existing instances AND available instance types in parallel
      const [instancesRes, launchDataRes] = await Promise.allSettled([
        Promise.race([
          apiService.getLambdaCloudInstances(apiKey),
          timeoutPromise
        ]).catch(err => {
          console.error('Instances API call failed or timed out:', err);
          // Don't throw - let Promise.allSettled handle it
          return Promise.reject(err);
        }),
        fetchLaunchData(apiKey).catch(err => {
          console.warn('Failed to fetch launch data (non-critical):', err);
          return null; // Don't fail the whole operation
        })
      ]);
      
      // Handle instances response
      let instancesList = [];
      if (instancesRes.status === 'fulfilled') {
        const data = instancesRes.value;
        console.log('Raw instances response:', data);
        // Try multiple possible response structures
        if (Array.isArray(data?.instances)) {
          instancesList = data.instances;
        } else if (Array.isArray(data?.data?.instances)) {
          instancesList = data.data.instances;
        } else if (Array.isArray(data?.data)) {
          instancesList = data.data;
        } else if (Array.isArray(data)) {
          instancesList = data;
        } else if (data && typeof data === 'object') {
          // Some Lambda APIs return object keyed by instance ID; convert to array
          instancesList = Object.values(data).filter(Boolean);
        } else {
          instancesList = [];
        }
        console.log('Parsed instances list:', instancesList);
        console.log('Number of instances:', instancesList.length);
        
        // Log first instance structure for debugging
        if (instancesList.length > 0) {
          console.log('First instance structure:', instancesList[0]);
        }
      } else {
        const error = instancesRes.reason;
        console.error('Failed to fetch instances:', error);
        
        // Provide more helpful error messages
        let errorMessage = 'Failed to fetch instances';
        if (error?.message) {
          if (error.message.includes('timeout')) {
            errorMessage = 'Request timed out. The Lambda Cloud API may be slow. Please try again.';
          } else if (error.message.includes('401') || error.message.includes('Invalid')) {
            errorMessage = 'Invalid API key. Please check your Lambda Labs API key.';
          } else if (error.message.includes('502') || error.message.includes('Bad Gateway')) {
            errorMessage = 'Backend service unavailable. Please try again in a moment.';
          } else {
            errorMessage = error.message;
          }
        }
        
        // Don't throw - set error state instead so user can see the message
        setError(errorMessage);
        setLoading(false);
        return; // Exit early instead of throwing
      }
      
      // Set instances
      console.log('Setting instances in state:', instancesList.length, 'instances');
      console.log('Instance data sample:', instancesList.length > 0 ? instancesList[0] : 'none');
      setInstances(prev => {
        const newState = {
        ...prev,
          lambda: instancesList
        };
        return newState;
      });
      setSelectedProvider('lambda');
      setLastUpdated(Date.now());
      showToast({ message: `Loaded ${instancesList.length} Lambda instance${instancesList.length === 1 ? '' : 's'}`, severity: 'success', duration: 3000 });
      // Also load launch data (types/regions) to populate available configurations
      await fetchLaunchData(apiKey);
      setLastUpdated(Date.now());
      
      // Fetch orchestration status for each instance (non-blocking)
      const orchestrationPromises = instancesList
        .filter(inst => inst.id)
        .map(async (inst) => {
          try {
            const orchestration = await apiService.getOrchestrationByInstance(inst.id);
            if (orchestration) {
              return { instanceId: inst.id, orchestration };
            }
          } catch (e) {
            // Instance may not have orchestration, that's fine
            console.debug(`No orchestration found for instance ${inst.id}`);
          }
          return null;
        });
      
      const orchestrationResults = await Promise.allSettled(orchestrationPromises);
      const orchestrationsMap = {};
      orchestrationResults.forEach((result) => {
        if (result.status === 'fulfilled' && result.value) {
          orchestrationsMap[result.value.instanceId] = result.value.orchestration;
        }
      });
      setInstanceOrchestrations(prev => ({ ...prev, ...orchestrationsMap }));
      setExpandedProvider('lambda');
      
      // Set message based on results
      const instanceTypesCount = instanceTypes.length;
      if (instancesList.length === 0 && instanceTypesCount === 0) {
        setMessage('No running instances found. Click "Launch New Instance" to create one.');
      } else if (instancesList.length === 0) {
        setMessage(`Loaded ${instanceTypesCount} available GPU configurations. No running instances. You can launch a new instance using the "Launch New Instance" button.`);
      } else if (instanceTypesCount === 0) {
        setMessage(`Loaded ${instancesList.length} running instance${instancesList.length !== 1 ? 's' : ''}.`);
      } else {
        setMessage(`Loaded ${instancesList.length} running instance${instancesList.length !== 1 ? 's' : ''} and ${instanceTypesCount} available GPU configurations.`);
      }
    } catch (e) {
      // Handle different error types
      let errorMessage = 'Failed to fetch instances from Lambda Cloud';
      if (e.message?.toLowerCase().includes('timeout')) {
        errorMessage = 'Request timed out. The Lambda Cloud API may be slow. Please try again.';
      } else if (e.response?.status === 401) {
        errorMessage = 'Invalid Lambda Labs API key. Please check your credentials and try again.';
      } else if (e.response?.status === 403) {
        errorMessage = 'Access denied. Your API key does not have permission to access Lambda resources.';
      } else if (e.response?.status === 429) {
        errorMessage = 'Rate limit exceeded. Please try again in a few minutes.';
      } else if (e.message?.toLowerCase().includes('network') || e.code === 'ECONNABORTED') {
        errorMessage = 'Network error. Please check your internet connection and try again.';
      } else {
        errorMessage = `Failed to fetch Lambda instances: ${e.response?.data?.detail || e.message || 'Unknown error'}`;
      }
      setError(errorMessage);
      // Clear instances on error
      setInstances(prev => ({
        ...prev,
        lambda: []
      }));
    } finally {
      setLoading(false);
    }
  };

  // Refresh control (placed after fetch functions to avoid TDZ)
  const handleRefresh = useCallback(() => {
    // If in aggregated view mode, refresh aggregated instances
    if (aggregatedViewMode === 'aggregated') {
      fetchAggregatedInstances();
      return;
    }
    
    // Otherwise, refresh the selected provider
    fetchScalewayInstances(scwRegion, { showGlobalLoading: true });
  }, [aggregatedViewMode, selectedProvider, scwRegion, fetchScalewayInstances, fetchAggregatedInstances]);

  // Fetch Lambda instance types and regions for launch
  const fetchLaunchData = async (apiKey) => {
    if (!apiKey) return;
    
    try {
      setLaunchLoading(true);
      const [typesRes, regionsRes, sshKeysRes] = await Promise.all([
        apiService.getLambdaCloudInstanceTypes(apiKey).catch((err) => {
          console.error('Failed to fetch instance types:', err);
          console.error('Error details:', err.response?.status, err.response?.statusText, err.message);
          return { instance_types: {} };
        }),
        apiService.getLambdaCloudRegions(apiKey).catch((err) => {
          console.error('Failed to fetch regions:', err);
          return { regions: [] };
        }),
        apiService.getLambdaSshKeys(apiKey).catch((err) => {
          console.error('Failed to fetch SSH keys:', err);
          return { ssh_keys: [] };
        })
      ]);
      
      // Extract instance types from response
      // Lambda API structure per docs: { "data": { "gpu_1x_gh200": { "instance_type": {...}, "regions_with_capacity_available": [...] }, ... } }
      const typesData =
        typesRes.instance_types ||
        typesRes.data?.instance_types ||
        typesRes.data?.data ||
        typesRes.data ||
        {};
      let typesList = [];
      
      // Handle Lambda API structure: data is an object where each key contains { instance_type, regions_with_capacity_available }
      if (typeof typesData === 'object' && !Array.isArray(typesData)) {
        // Extract instance_type from each entry and add regions info
        typesList = Object.entries(typesData).map(([key, value]) => {
          // value structure: { instance_type: {...}, regions_with_capacity_available: [...] }
          const instanceType = value.instance_type || {};
          const regions = value.regions_with_capacity_available || [];
          
          return {
            ...instanceType,
            // Add regions info
            regions: regions,
            // Keep the key as identifier
            key: key,
            // Add availability status
            has_capacity: regions.length > 0
          };
        });
      } else if (Array.isArray(typesData)) {
        // Fallback for array structure
        typesList = typesData;
      }

      // This UI section is "Available GPU Configurations" — filter out CPU-only types.
      typesList = (typesList || []).filter((type) => {
        const gpus = type?.specs?.gpus;
        if (typeof gpus === 'number') return gpus > 0;
        const name = String(type?.name || type?.key || '').toLowerCase();
        return name.includes('gpu_');
      });
      
      console.log('Instance types response:', typesRes);
      console.log('Extracted instance types:', typesList.length, 'types');
      if (typesList.length > 0) {
        console.log('First instance type sample:', JSON.stringify(typesList[0], null, 2));
        console.log('First instance type specs:', typesList[0].specs);
        console.log('First instance type keys:', Object.keys(typesList[0]));
      } else {
        console.warn('No instance types extracted. Raw data:', typesData);
      }
      
      setInstanceTypes(typesList);
      
      // Extract regions from multiple sources
      const regionsData = regionsRes.regions || regionsRes.data?.regions || [];
      let regionsList = Array.isArray(regionsData) ? regionsData : Object.values(regionsData);
      
      // Also collect all unique regions from instance types' regions_with_capacity_available
      const regionsFromInstanceTypes = new Set();
      typesList.forEach(type => {
        if (type.regions && Array.isArray(type.regions)) {
          type.regions.forEach(region => {
            const regionName = typeof region === 'string' ? region : (region.name || region);
            if (regionName) {
              regionsFromInstanceTypes.add(regionName);
            }
          });
        }
      });
      
      // Combine regions from API and instance types
      const allRegions = new Map();
      
      // Add regions from API response
      regionsList.forEach(region => {
        const regionName = typeof region === 'string' ? region : (region.name || region);
        if (regionName) {
          allRegions.set(regionName, typeof region === 'string' ? { name: regionName } : region);
        }
      });
      
      // Add regions from instance types (these are regions with capacity)
      regionsFromInstanceTypes.forEach(regionName => {
        if (!allRegions.has(regionName)) {
          allRegions.set(regionName, { name: regionName, has_capacity: true });
        } else {
          // Mark existing region as having capacity
          allRegions.get(regionName).has_capacity = true;
        }
      });
      
      // Add common Lambda Cloud regions as fallback if we don't have any
      if (allRegions.size === 0) {
        const commonRegions = [
          { name: 'us-east-1', description: 'US East (N. Virginia)' },
          { name: 'us-west-1', description: 'US West (N. California)' },
          { name: 'us-west-2', description: 'US West (Oregon)' },
          { name: 'eu-west-1', description: 'Europe (Ireland)' },
          { name: 'eu-central-1', description: 'Europe (Frankfurt)' },
          { name: 'ap-southeast-1', description: 'Asia Pacific (Singapore)' },
          { name: 'ap-northeast-1', description: 'Asia Pacific (Tokyo)' },
        ];
        commonRegions.forEach(region => {
          allRegions.set(region.name, region);
        });
      }
      
      // Convert to array and sort
      const finalRegions = Array.from(allRegions.values()).sort((a, b) => {
        const nameA = a.name || a;
        const nameB = b.name || b;
        return nameA.localeCompare(nameB);
      });
      
      setRegions(finalRegions);
      
      // Extract SSH keys
      const keysData = sshKeysRes.ssh_keys || [];
      setSshKeys(Array.isArray(keysData) ? keysData : []);
      
    } catch (e) {
      console.error('Failed to fetch launch data:', e);
      setError('Failed to load instance types or regions. Please try again.');
    } finally {
      setLaunchLoading(false);
    }
  };

  const getLambdaApiKey = useCallback(() => {
    const cred = credentials['lambda'];
    const secret = credentialSecrets['lambda'];
    const parsed = cred && secret ? parseBackendCredential(cred, secret) : null;
    return parsed?.apiKey || null;
  }, [credentials, credentialSecrets]);

  const handleLaunchFromCatalog = useCallback(
    async (item) => {
      if (!item?.provider) return;
      if (item.provider === 'lambda') {
        const apiKey = getLambdaApiKey();
        if (!apiKey) {
          showToast({ message: 'Integrate Lambda first (Cloud Based view)', severity: 'warning' });
          return;
        }
        await fetchLaunchData(apiKey);
        setLaunchForm((prev) => ({
          ...prev,
          instanceType: item.name || prev.instanceType,
          region: Array.isArray(item.regions) && item.regions.length > 0 ? item.regions[0] : prev.region,
        }));
        setLaunchDialogOpen(true);
        return;
      }

      if (item.provider === 'scaleway') {
        if (!isProviderConnected('scaleway')) {
          showToast({ message: 'Integrate Scaleway first (Cloud Based view)', severity: 'warning' });
          return;
        }
        const preferredRegion = Array.isArray(item.regions) && item.regions.length > 0 ? item.regions[0] : scwRegion;
        handleOpenScwLaunch({ region: preferredRegion, commercial_type: item.name });
        return;
      }

      if (item.provider === 'nebius') {
        if (!isProviderConnected('nebius')) {
          showToast({ message: 'Integrate Nebius first (Cloud Based view)', severity: 'warning' });
          return;
        }
        const preset = item.raw || {};
        handleOpenNebiusLaunch(preset);
      }
    },
    [fetchLaunchData, getLambdaApiKey, handleOpenNebiusLaunch, handleOpenScwLaunch, isProviderConnected, scwRegion, showToast]
  );

  // Handle launch instance with orchestration
  const handleLaunchInstance = async () => {
    if (!launchForm.instanceType || !launchForm.region || !launchForm.sshKey?.trim()) {
      setError('Please select instance type, region, and provide SSH key');
      return;
    }
    
    try {
      const raw = localStorage.getItem(storageKey('lambda'));
      if (!raw) {
        setError('Lambda API key not found');
        return;
      }
      const parsed = JSON.parse(raw);
      const apiKey = parsed.apiKey;
      
      if (!apiKey) {
        setError('Lambda API key not found');
        return;
      }
      
      // Get SSH key content from manual input
      const sshKeyContent = launchForm.sshKey.trim();
      
      // Use SSH key name from input or generate a default name
      // If user provided a key name, use it; otherwise use a default
      const sshKeyName = launchForm.sshKeyName || 'dio-manual-key';
      
      setLaunchLoading(true);
      setError('');
      setMessage('');
      
      const orchestrationRequest = {
        instance_type: launchForm.instanceType,
        region: launchForm.region,
        ssh_key_name: sshKeyName,
        ssh_key: sshKeyContent
      };
      
      const response = await apiService.startInstanceOrchestration(apiKey, orchestrationRequest);
      
      if (response && response.orchestration_id) {
        setMessage('Instance launch initiated successfully!');
        setError('');

        // Activate full-screen loading
        setLaunchingScreen({
          active: true,
          provider: 'lambda',
          phase: 'launching',
          ip: null,
          instanceName: launchForm.instanceType,
          sshUser: 'ubuntu',
        });

        // Open orchestration dialog (hidden behind full-screen) and close launch dialog
        setTimeout(() => {
          setOrchestrationId(response.orchestration_id);
          setOrchestrationStatus(response);
          setLaunchDialogOpen(false);
          setOrchestrationDialogOpen(true);
          setLaunchForm({ instanceType: '', region: '', sshKeyName: '', sshKey: '' });
          setMessage('');
        }, 1000);
      } else {
        setError('Failed to start orchestration. Please try again.');
        setMessage('');
      }
    } catch (e) {
      console.error('[LAUNCH] Instance launch failed:', e?.response?.data || e?.message || e);
      setError(`Failed to launch instance: ${friendlyError(e, 'Please check your API key and instance configuration.')}`);
    } finally {
      setLaunchLoading(false);
    }
  };

  // ---

  // Load Scaleway regions from backend (fallback to static)
  const loadScwRegions = async () => {
    try {
      const res = await apiService.getScalewayRegions();
      if (Array.isArray(res) && res.length > 0) {
        setScwRegions(res);
        setScwRegion(res[0]);
      }
    } catch (e) {
      // ignore, keep defaults
    }
  };

  // Disabled auto-load on mount to prevent 401 errors with invalid stored credentials
  // Users must manually click "Fetch Instances" to load data
  // useEffect(() => {
  //   const loadInstances = async () => {
  //     for (const provider of PROVIDERS) {
  //       if (isProviderConnected(provider.id)) {
  //         try {
  //           const raw = localStorage.getItem(storageKey(provider.id));
  //           if (raw) {
  //             const parsed = JSON.parse(raw);
  //             if (provider.id === 'lambda' && parsed.apiKey) {
  //               await fetchLambdaInstances(parsed.apiKey);
  //             }
  //           }
  //         } catch (e) {
  //           // ignore
  //         }
  //       }
  //     }
  //   };
  //   loadInstances();
  // }, []);

  const handleLocalInstanceConnect = () => {
    setError('');
    setMessage('');

    if (!localInstanceForm.ipAddress || !localInstanceForm.ipAddress.trim()) {
      setError('Please enter an IP address');
      return;
    }
    if (!localInstanceForm.sshKey || !localInstanceForm.sshKey.trim()) {
      setError('Please enter an SSH key');
      return;
    }
    if (!localInstanceForm.sshUser || !localInstanceForm.sshUser.trim()) {
      setError('Please enter an SSH user');
      return;
    }

    // Create instanceData for local instance
    const instanceData = {
      id: `local-${localInstanceForm.ipAddress.trim()}`,
      name: `Local Instance (${localInstanceForm.ipAddress.trim()})`,
      ipAddress: localInstanceForm.ipAddress.trim(),
      sshUser: localInstanceForm.sshUser.trim(),
      sshKey: localInstanceForm.sshKey.trim(),
      provider: 'local',
      vendor: 'Local',
      status: 'running'
    };

    // Navigate to telemetry with local instance data
    navigate('/telemetry', { state: { instanceData } });
  };

  return (
    <>
    {/* Full-screen launching overlay */}
    {launchingScreen.active && (
      <Box
        sx={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'rgba(26, 26, 24, 0.97)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <Box sx={{ textAlign: 'center', maxWidth: 480, px: 3 }}>
          {/* Spinner */}
          {launchingScreen.phase !== 'ready' && (
            <CircularProgress size={64} thickness={3} sx={{ color: '#818cf8', mb: 4 }} />
          )}
          {launchingScreen.phase === 'ready' && (
            <CheckCircleIcon sx={{ fontSize: 64, color: '#34d399', mb: 4 }} />
          )}

          {/* Title */}
          <Typography variant="h5" sx={{ color: '#fafaf8', fontWeight: 700, mb: 1 }}>
            {launchingScreen.phase === 'ready'
              ? 'Instance Ready!'
              : launchingScreen.phase === 'waiting_ip'
              ? 'Almost there...'
              : 'Launching Instance'}
          </Typography>

          {/* Subtitle */}
          <Typography variant="body1" sx={{ color: '#a8a8a0', mb: 4 }}>
            {launchingScreen.phase === 'ready'
              ? 'Redirecting to Run Workload...'
              : launchingScreen.phase === 'waiting_ip'
              ? 'Waiting for IP address assignment...'
              : `Setting up your ${launchingScreen.provider || ''} instance...`}
          </Typography>

          {/* Progress steps */}
          <Box sx={{ textAlign: 'left', mb: 4 }}>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <CheckCircleIcon sx={{ fontSize: 20, color: '#34d399' }} />
                <Typography variant="body2" sx={{ color: '#fafaf8' }}>
                  Launch requested
                </Typography>
              </Stack>
              <Stack direction="row" spacing={1.5} alignItems="center">
                {launchingScreen.phase === 'launching' ? (
                  <CircularProgress size={18} thickness={4} sx={{ color: '#818cf8' }} />
                ) : (
                  <CheckCircleIcon sx={{ fontSize: 20, color: '#34d399' }} />
                )}
                <Typography variant="body2" sx={{ color: launchingScreen.phase === 'launching' ? '#a8a8a0' : '#fafaf8' }}>
                  Provisioning instance
                </Typography>
              </Stack>
              <Stack direction="row" spacing={1.5} alignItems="center">
                {launchingScreen.phase === 'waiting_ip' ? (
                  <CircularProgress size={18} thickness={4} sx={{ color: '#818cf8' }} />
                ) : launchingScreen.phase === 'ready' ? (
                  <CheckCircleIcon sx={{ fontSize: 20, color: '#34d399' }} />
                ) : (
                  <Box sx={{ width: 20, height: 20, borderRadius: '50%', border: '2px solid #3d3d3a' }} />
                )}
                <Typography variant="body2" sx={{ color: launchingScreen.phase === 'launching' ? '#6b6b65' : launchingScreen.phase === 'waiting_ip' ? '#a8a8a0' : '#fafaf8' }}>
                  Assigning IP address
                </Typography>
              </Stack>
              <Stack direction="row" spacing={1.5} alignItems="center">
                {launchingScreen.phase === 'ready' ? (
                  <CheckCircleIcon sx={{ fontSize: 20, color: '#34d399' }} />
                ) : (
                  <Box sx={{ width: 20, height: 20, borderRadius: '50%', border: '2px solid #3d3d3a' }} />
                )}
                <Typography variant="body2" sx={{ color: launchingScreen.phase === 'ready' ? '#fafaf8' : '#6b6b65' }}>
                  Ready — redirecting to Run Workload
                </Typography>
              </Stack>
            </Stack>
          </Box>

          {/* IP address display */}
          {launchingScreen.ip && (
            <Box sx={{ p: 2, borderRadius: 2, border: '1px solid #3d3d3a', backgroundColor: 'rgba(129, 140, 248, 0.08)', mb: 3 }}>
              <Typography variant="caption" sx={{ color: '#a8a8a0' }}>
                IP Address
              </Typography>
              <Typography variant="h6" sx={{ color: '#818cf8', fontFamily: '"DM Mono", monospace' }}>
                {launchingScreen.ip}
              </Typography>
            </Box>
          )}

          {/* Instance name */}
          {launchingScreen.instanceName && (
            <Typography variant="caption" sx={{ color: '#6b6b65' }}>
              {launchingScreen.provider?.charAt(0).toUpperCase() + launchingScreen.provider?.slice(1)} &middot; {launchingScreen.instanceName}
            </Typography>
          )}

          {/* Cancel button */}
          <Box sx={{ mt: 4 }}>
            <Button
              onClick={() => setLaunchingScreen({ active: false, provider: null, phase: 'launching', ip: null, instanceName: null, sshUser: 'ubuntu' })}
              sx={{ color: '#a8a8a0', textTransform: 'none', '&:hover': { color: '#fafaf8' } }}
            >
              Dismiss
            </Button>
          </Box>
        </Box>
      </Box>
    )}

    <Box sx={{ display: 'flex', minHeight: '100vh', backgroundColor: 'background.default' }}>
      {/* Main Content Area */}
      <Box sx={{ flex: 1, p: 4, display: 'flex', flexDirection: 'column' }}>
        {/* Messages */}
        {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }} onClose={() => setError('')}>{error}</Alert>}


        {loading && <Box sx={{ mb: 3 }}><ListSkeleton items={3} /></Box>}

        {/* Empty State or Content */}
        {viewMode === 'local' ? (
          <Box sx={{ 
            display: 'flex', 
            flexDirection: 'column', 
            alignItems: 'center', 
            justifyContent: 'center', 
            flex: 1,
            textAlign: 'center',
            color: 'text.secondary'
          }}>
            <ComputerIcon sx={{ fontSize: 80, mb: 2, opacity: 0.3 }} />
            <Typography variant="h6" sx={{ mb: 1, color: 'text.secondary' }}>
              Connect to Local Instance
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 500 }}>
              Enter your local instance details in the sidebar to connect via SSH and start monitoring telemetry
            </Typography>
          </Box>
        ) : aggregatedViewMode === 'aggregated' ? (
          <Box>
            {/* Aggregated Instances View */}
            <Typography variant="h5" sx={{ mb: 3, fontWeight: 600 }}>
              All Available Instances
            </Typography>

            {/* Search and Filters */}
            <Box sx={{ mb: 3 }}>
              <TextField
                fullWidth
                placeholder="Search instances..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                sx={{ mb: 2 }}
                size="small"
              />

              <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
                <FormControl size="small" sx={{ minWidth: 150 }}>
                  <InputLabel>Cloud</InputLabel>
                  <Select
                    multiple
                    value={filters.cloud}
                    onChange={(e) => setFilters({ ...filters, cloud: e.target.value })}
                    label="Cloud"
                    renderValue={(selected) => selected.length === 0 ? 'All' : `${selected.length} selected`}
                  >
                    <MenuItem value="lambda">Lambda Labs</MenuItem>
                    <MenuItem value="nebius">Nebius</MenuItem>
                    <MenuItem value="scaleway">Scaleway</MenuItem>
                  </Select>
                </FormControl>

                <FormControl size="small" sx={{ minWidth: 150 }}>
                  <InputLabel>GPU Type</InputLabel>
                  <Select
                    value={filters.gpuType}
                    onChange={(e) => setFilters({ ...filters, gpuType: e.target.value })}
                    label="GPU Type"
                  >
                    <MenuItem value="">All</MenuItem>
                    {gpuTypeOptions.map((opt) => (
                      <MenuItem key={opt} value={opt}>
                        {opt}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <FormControl size="small" sx={{ minWidth: 150 }}>
                  <InputLabel>Num GPUs</InputLabel>
                  <Select
                    value={filters.numGpus}
                    onChange={(e) => setFilters({ ...filters, numGpus: e.target.value })}
                    label="Num GPUs"
                  >
                    <MenuItem value="">All</MenuItem>
                    <MenuItem value="1">1 GPU</MenuItem>
                    <MenuItem value="2">2 GPUs</MenuItem>
                    <MenuItem value="4">4 GPUs</MenuItem>
                    <MenuItem value="8">8 GPUs</MenuItem>
                  </Select>
                </FormControl>

                <FormControl size="small" sx={{ minWidth: 150 }}>
                  <InputLabel>Availability</InputLabel>
                  <Select
                    value={filters.availability}
                    onChange={(e) => setFilters({ ...filters, availability: e.target.value })}
                    label="Availability"
                  >
                    <MenuItem value="">All</MenuItem>
                    <MenuItem value="available">Available</MenuItem>
                    <MenuItem value="out_of_stock">Out of Stock</MenuItem>
                    <MenuItem value="quota_required">Quota Required</MenuItem>
                  </Select>
                </FormControl>

                <FormControl size="small" sx={{ minWidth: 150 }}>
                  <InputLabel>Sort By</InputLabel>
                  <Select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    label="Sort By"
                  >
                    <MenuItem value="cost_asc">Cost (Low to High)</MenuItem>
                    <MenuItem value="cost_desc">Cost (High to Low)</MenuItem>
                  </Select>
                </FormControl>

                <Button
                  variant="outlined"
                  onClick={() => {
                    setSearchQuery('');
                    setFilters({ cloud: [], gpuType: '', numGpus: '', availability: '' });
                    setSortBy('cost_asc');
                  }}
                  sx={{ textTransform: 'none', height: 40 }}
                >
                  Clear Filters
                </Button>
              </Stack>
            </Box>

            {/* Loading State */}
            {aggregatedLoading && (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                <CircularProgress />
              </Box>
            )}

            {/* Empty State */}
            {!aggregatedLoading && aggregatedInstances.length === 0 && (
              <Alert severity="info" sx={{ borderRadius: 2 }}>
                No configurations found. Click refresh to fetch available instance types from all providers.
              </Alert>
            )}

            {/* Aggregated Instances Grid */}
            {!aggregatedLoading && filteredAndSortedInstances.length > 0 && (
              <>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Showing {filteredAndSortedInstances.length} configuration{filteredAndSortedInstances.length === 1 ? '' : 's'}
                  {filteredAndSortedInstances.length !== aggregatedInstances.length && ` (filtered from ${aggregatedInstances.length})`}
                </Typography>
                
                <Grid container spacing={2}>
                  {filteredAndSortedInstances.map((instance) => (
                    <Grid item xs={12} sm={6} md={4} key={`${instance.provider}-${instance.id}`}>
                      <Card 
                        sx={{ 
                          height: '100%',
                          display: 'flex',
                          flexDirection: 'column',
                          transition: 'all 0.2s',
                          '&:hover': {
                            transform: 'translateY(-2px)',
                            boxShadow: 3
                          }
                        }}
                      >
                        <CardContent sx={{ flexGrow: 1 }}>
                          {/* Provider Badge */}
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                            <Chip 
                              label={
                                instance.provider === 'lambda'
                                  ? 'Lambda'
                                  : instance.provider === 'nebius'
                                    ? 'Nebius'
                                    : instance.provider === 'scaleway'
                                      ? 'Scaleway'
                                      : (instance.provider || '').toUpperCase()
                              }
                              size="small"
                              color={
                                instance.provider === 'lambda' ? 'primary' :
                                instance.provider === 'nebius' ? 'success' :
                                'secondary'
                              }
                              sx={{ fontWeight: 600 }}
                            />
                            {instance.availability && (
                              <Chip
                                label={instance.availability}
                                size="small"
                                variant="outlined"
                              />
                            )}
                          </Box>

                          {/* Instance Name/Type */}
                          <Typography variant="h6" sx={{ mb: 1, fontWeight: 600, fontSize: '1rem' }}>
                            {instance.name || instance.id}
                          </Typography>
                          
                          {instance.description && (
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                              {instance.description}
                            </Typography>
                          )}

                          {/* GPU Info */}
                          {instance.gpu_model && (() => {
                            const specs = lookupGpuSpecs(instance.gpu_model) || lookupGpuSpecs(instance.name);
                            return (
                              <Box sx={{ mb: 1.5 }}>
                                <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                                  {instance.gpu_model} {instance.num_gpus && `× ${instance.num_gpus}`}
                                </Typography>
                                {specs && (
                                  <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                                    <Chip label={`${specs.vram} ${specs.vramUnit}`} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
                                    {specs.arch && <Chip label={specs.arch} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />}
                                  </Stack>
                                )}
                              </Box>
                            );
                          })()}

                          {/* Resource Info */}
                          <Stack spacing={0.5} sx={{ mb: 1.5 }}>
                            {instance.vcpus && (
                              <Typography variant="body2" color="text.secondary">
                                vCPUs: {instance.vcpus}
                              </Typography>
                            )}
                            {instance.memory_gb && (
                              <Typography variant="body2" color="text.secondary">
                                RAM: {instance.memory_gb.toFixed(0)} GB
                              </Typography>
                            )}
                          </Stack>

                          {/* IP Addresses */}
                          {Array.isArray(instance.regions) && instance.regions.length > 0 && (
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                              {instance.regions.length} region{instance.regions.length === 1 ? '' : 's'} available
                            </Typography>
                          )}

                          {/* Cost */}
                          {instance.cost_per_hour_usd && (
                            <Box sx={{ 
                              mt: 'auto',
                              pt: 2,
                              borderTop: 1,
                              borderColor: 'divider'
                            }}>
                              <Typography variant="h6" sx={{ fontWeight: 600, color: 'primary.main' }}>
                                ${instance.cost_per_hour_usd.toFixed(2)}/hr
                              </Typography>
                              {instance.cost_per_month_usd && (
                                <Typography variant="caption" color="text.secondary">
                                  ~${instance.cost_per_month_usd.toFixed(0)}/month
                                </Typography>
                              )}
                            </Box>
                          )}

                          <Box sx={{ mt: 2 }}>
                            <Button
                              variant="contained"
                              fullWidth
                              disabled={
                                (instance.provider === 'lambda' && !isProviderConnected('lambda')) ||
                                (instance.provider === 'scaleway' && !isProviderConnected('scaleway')) ||
                                (instance.provider === 'nebius' && !isProviderConnected('nebius'))
                              }
                              onClick={() => handleLaunchFromCatalog(instance)}
                              sx={{ textTransform: 'none' }}
                            >
                              Launch
                            </Button>
                          </Box>
                        </CardContent>
                      </Card>
                    </Grid>
                  ))}
                </Grid>
              </>
            )}
            
            {/* No results after filtering */}
            {!aggregatedLoading && aggregatedInstances.length > 0 && filteredAndSortedInstances.length === 0 && (
              <Alert severity="info" sx={{ borderRadius: 2 }}>
                No instances match your filters. Try adjusting the filters or clearing them.
              </Alert>
            )}
          </Box>
        ) : !selectedProvider ? (
          <Box sx={{ 
            display: 'flex', 
            flexDirection: 'column', 
            alignItems: 'center', 
            justifyContent: 'center', 
            flex: 1,
            textAlign: 'center',
            color: 'text.secondary'
          }}>
            <CloudIcon sx={{ fontSize: 80, mb: 2, opacity: 0.3 }} />
            <Typography variant="h6" sx={{ mb: 1, color: 'text.secondary' }}>
              You have not selected a cloud provider
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Select a cloud provider to see the available instances
            </Typography>
          </Box>
        ) : (
          <Box>
            {/* Selected Provider Content Will Appear Here */}
            <Typography variant="h5" sx={{ mb: 2, fontWeight: 600 }}>
              {PROVIDERS.find(p => p.id === selectedProvider)?.name}
            </Typography>
            
          </Box>
        )}

        {/* Available Instance Types for Lambda (shows all launchable configurations) - Show FIRST, before existing instances */}
        {aggregatedViewMode === 'cloud' && selectedProvider === 'lambda' && isProviderConnected('lambda') && viewMode === 'cloud' && (
          <Box sx={{ mt: 3, mb: 4 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <CloudIcon color="primary" />
                <Typography variant="h6" sx={{ fontWeight: 600 }}>
                  Available GPU Configurations {instanceTypes.length > 0 ? `(${instanceTypes.length})` : ''}
                </Typography>
              </Box>
              {instanceTypes.length === 0 && !launchLoading && (
                <Button
                  size="small"
                  variant="outlined"
                  onClick={async () => {
                    try {
                      // Use backend credentials if available, otherwise fall back to localStorage
                      const cred = credentials['lambda'];
                      const secret = credentialSecrets['lambda'];
                      let apiKey = null;
                      
                      if (cred && secret) {
                        const parsedBackend = parseBackendCredential(cred, secret);
                        apiKey = parsedBackend?.apiKey;
                      }
                      
                      if (!apiKey) {
                        const raw = localStorage.getItem(storageKey('lambda'));
                        if (raw) {
                          const parsed = JSON.parse(raw);
                          apiKey = parsed.apiKey;
                        }
                      }
                      
                      if (!apiKey) {
                        setError('Lambda API key not found. Please re-integrate.');
                        return;
                      }
                      await fetchLaunchData(apiKey);
                    } catch (e) {
                      setError('Failed to load instance types: ' + e.message);
                    }
                  }}
                  sx={{ textTransform: 'none' }}
                >
                  Load Configurations
                </Button>
              )}
            </Box>
            {launchLoading && instanceTypes.length === 0 ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                <CircularProgress />
              </Box>
            ) : instanceTypes.length > 0 ? (
            <Grid container spacing={2}>
              {instanceTypes.map((type, idx) => (
                <Grid item xs={12} md={6} lg={4} key={type.name || idx}>
                  <Card variant="outlined" sx={{ height: '100%', display: 'flex', flexDirection: 'column', '&:hover': { boxShadow: 3 } }}>
                    <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                      <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>
                        {type.name || type.instance_type_name || `Instance ${idx + 1}`}
                      </Typography>
                      {type.description && (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                          {type.description}
                        </Typography>
                      )}
                      {type.gpu_description && (
                        <Typography variant="body2" color="primary" sx={{ mb: 2, fontWeight: 500 }}>
                          {type.gpu_description}
                        </Typography>
                      )}
                      
                      {/* Detailed Specs - Always show if specs exist */}
                      {type.specs && Object.keys(type.specs).length > 0 && (
                        <Box sx={{ mb: 2, flex: 1 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'text.primary' }}>
                            Specifications
                          </Typography>
                          <Stack spacing={1}>
                            {type.specs.gpus !== undefined && type.specs.gpus !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">GPUs:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.gpus}</Typography>
                              </Box>
                            )}
                            {type.specs.gpu_memory_gib !== undefined && type.specs.gpu_memory_gib !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">GPU Memory:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.gpu_memory_gib} GiB</Typography>
                              </Box>
                            )}
                            {type.specs.memory_gib !== undefined && type.specs.memory_gib !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">System Memory:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.memory_gib} GiB</Typography>
                              </Box>
                            )}
                            {type.specs.vcpus !== undefined && type.specs.vcpus !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">vCPUs:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.vcpus}</Typography>
                              </Box>
                            )}
                            {type.specs.storage_gib !== undefined && type.specs.storage_gib !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">Storage:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.storage_gib} GiB</Typography>
                              </Box>
                            )}
                            {type.specs.inbound_bandwidth_gbps !== undefined && type.specs.inbound_bandwidth_gbps !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">Inbound Bandwidth:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.inbound_bandwidth_gbps} Gbps</Typography>
                              </Box>
                            )}
                            {type.specs.outbound_bandwidth_gbps !== undefined && type.specs.outbound_bandwidth_gbps !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">Outbound Bandwidth:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.outbound_bandwidth_gbps} Gbps</Typography>
                              </Box>
                            )}
                            {type.specs.interconnect && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">Interconnect:</Typography>
                                <Chip 
                                  label={type.specs.interconnect} 
                                  size="small" 
                                  color={type.specs.interconnect.toLowerCase().includes('nvlink') ? 'primary' : 'default'}
                                  sx={{ height: 20 }}
                                />
                              </Box>
                            )}
                            {type.specs.nvlink_bandwidth_gbps !== undefined && type.specs.nvlink_bandwidth_gbps !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">NVLink Bandwidth:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.nvlink_bandwidth_gbps} Gbps</Typography>
                              </Box>
                            )}
                            {type.specs.pcie_bandwidth_gbps !== undefined && type.specs.pcie_bandwidth_gbps !== null && (
                              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                                <Typography variant="body2" color="text.secondary">PCIe Bandwidth:</Typography>
                                <Typography variant="body2" fontWeight="bold">{type.specs.pcie_bandwidth_gbps} Gbps</Typography>
                              </Box>
                            )}
                          </Stack>
                        </Box>
                      )}
                      
                      {/* Availability Status */}
                      <Box sx={{ mb: 2 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'text.primary' }}>
                          Availability
                        </Typography>
                        <Stack spacing={1}>
                          {type.has_capacity !== undefined && (
                            <Box>
                              <Chip 
                                label={type.has_capacity ? 'Available' : 'No Capacity'} 
                                size="small" 
                                color={type.has_capacity ? 'success' : 'warning'}
                                sx={{ height: 24 }}
                              />
                            </Box>
                          )}
                          {type.regions && Array.isArray(type.regions) && type.regions.length > 0 && (
                            <Box>
                              <Typography variant="caption" color="text.secondary">
                                Available in {type.regions.length} region{type.regions.length !== 1 ? 's' : ''}:
                              </Typography>
                              <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                                {type.regions.slice(0, 3).map((region, regionIdx) => (
                                  <Typography key={regionIdx} variant="body2" sx={{ fontSize: '0.75rem' }}>
                                    • {typeof region === 'string' ? region : (region.name || region)}
                                  </Typography>
                                ))}
                                {type.regions.length > 3 && (
                                  <Typography variant="caption" color="text.secondary">
                                    + {type.regions.length - 3} more region{type.regions.length - 3 !== 1 ? 's' : ''}
                                  </Typography>
                                )}
                              </Stack>
                            </Box>
                          )}
                        </Stack>
                      </Box>
                      
                      {/* Expandable Additional Details */}
                      <Box sx={{ mb: 2 }}>
                        <Button
                          size="small"
                          onClick={() => {
                            const newExpanded = new Set(expandedCards);
                            if (expandedCards.has(type.name || idx)) {
                              newExpanded.delete(type.name || idx);
                            } else {
                              newExpanded.add(type.name || idx);
                            }
                            setExpandedCards(newExpanded);
                          }}
                          endIcon={expandedCards.has(type.name || idx) ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                          sx={{ textTransform: 'none', p: 0, minWidth: 'auto', color: 'text.secondary' }}
                        >
                          {expandedCards.has(type.name || idx) ? 'Show Less' : 'Show All Details'}
                        </Button>
                        {expandedCards.has(type.name || idx) && (
                          <Box sx={{ mt: 1, pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'text.primary' }}>
                              Complete Details
                            </Typography>
                            <Stack spacing={0.5}>
                              {Object.entries(type).map(([key, value]) => {
                                // Skip already displayed fields
                                if (['name', 'gpu_description', 'specs', 'price_cents_per_hour', 'regions', 'availability', 'instance_type_category'].includes(key)) {
                                  return null;
                                }
                                // Skip null/undefined values
                                if (value === null || value === undefined) {
                                  return null;
                                }
                                // Format the value
                                let displayValue = value;
                                if (typeof value === 'object' && !Array.isArray(value)) {
                                  displayValue = JSON.stringify(value, null, 2);
                                } else if (Array.isArray(value)) {
                                  displayValue = value.join(', ');
                                } else if (typeof value === 'boolean') {
                                  displayValue = value ? 'Yes' : 'No';
                                }
                                return (
                                  <Box key={key}>
                                    <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'capitalize' }}>
                                      {key.replace(/_/g, ' ')}:
                                    </Typography>
                                    <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
                                      {displayValue}
                                    </Typography>
                                  </Box>
                                );
                              })}
                            </Stack>
                          </Box>
                        )}
                      </Box>
                      
                      {/* Pricing */}
                      {type.price_cents_per_hour && (
                        <Box sx={{ 
                          backgroundColor: '#f0f7ff', 
                          p: 1.5, 
                          borderRadius: 1,
                          textAlign: 'center',
                          border: '1px solid #e3f2fd',
                          mb: 2
                        }}>
                          <Typography variant="h6" color="primary" sx={{ fontWeight: 700 }}>
                            ${(type.price_cents_per_hour / 100).toFixed(2)}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            per hour
                          </Typography>
                          {type.price_cents_per_hour && (
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                              ~${((type.price_cents_per_hour / 100) * 24 * 30).toFixed(0)}/month
                            </Typography>
                          )}
                        </Box>
                      )}
                      
                      {/* Launch Button */}
                      <Button
                        variant="contained"
                        color="primary"
                        fullWidth
                        onClick={() => {
                          setLaunchForm(prev => ({ ...prev, instanceType: type.name }));
                          setLaunchDialogOpen(true);
                        }}
                        sx={{ textTransform: 'none', mt: 'auto' }}
                        startIcon={<PlayArrowIcon />}
                      >
                        Launch Instance
                      </Button>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, textAlign: 'center' }}>
                        Setup: ~20-25 min
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
        ) : (
          <Alert severity="info" sx={{ borderRadius: 2 }}>
            <Typography variant="body2">
              Click "Fetch Instances" or "Load Configurations" to see all available GPU instance types you can launch on Lambda Labs.
            </Typography>
          </Alert>
        )}
      </Box>
    )}

        {/* Scaleway region & configurations */}
        {aggregatedViewMode === 'cloud' && selectedProvider === 'scaleway' && isProviderConnected('scaleway') && (
          <Box sx={{ mt: 3, mb: 4 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <CloudIcon color="primary" />
                <Typography variant="h6" sx={{ fontWeight: 600 }}>
                  Scaleway GPU Configurations
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} alignItems="center">
                <FormControl size="small" sx={{ minWidth: 180 }}>
                  <InputLabel>Region</InputLabel>
                  <Select
                    label="Region"
                    value={scwRegion}
                    onChange={(e) => setScwRegion(e.target.value)}
                  >
                    {SCW_REGIONS.map((r) => (
                      <MenuItem key={r} value={r}>{r}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => fetchScalewayConfigs()}
                  disabled={scwLoading}
                  sx={{ textTransform: 'none' }}
                >
                  {scwLoading ? 'Loading...' : 'Refresh'}
                </Button>
              </Stack>
            </Box>

            {scwLoading && scwConfigs.length === 0 && (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                <CircularProgress size={28} />
              </Box>
            )}

            {(!scwConfigs || scwConfigs.length === 0) && !scwLoading && (
              <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
                No products returned for {scwRegion}. Region may have no capacity.
              </Alert>
            )}

            <Grid container spacing={2}>
              {(scwConfigs || []).map((cfg, idx) => {
                const name = cfg.commercial_type || cfg.name || cfg.id || `Instance ${idx + 1}`;
                const gpus = cfg.gpu ?? cfg.raw?.gpu_count ?? cfg.raw?.gpu ?? cfg.gpus ?? 'N/A';
                const vcpus = cfg.vcpus ?? cfg.raw?.ncpus ?? cfg.raw?.vcpu_count ?? cfg.vcpu ?? 'N/A';
                const ramBytes = cfg.ram_bytes ?? cfg.raw?.ram ?? cfg.ramBytes ?? null;
                const price = cfg.hourly_price ?? cfg.raw?.hourly_price?.price ?? cfg.priceEurHour ?? null;
                const availability = normalizeAvailability(cfg, scwRegion);
                const monthly = price ? (price * 24 * 30).toFixed(0) : null;
                const gpuModel = cfg.raw?.gpu_name || cfg.raw?.gpu_model || cfg.model || null;
                return (
                  <Grid item xs={12} md={6} lg={4} key={cfg.id || idx}>
                    <Card variant="outlined" sx={{ height: '100%', display: 'flex', flexDirection: 'column', '&:hover': { boxShadow: 3 } }}>
                      <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                        <Typography variant="h6" sx={{ fontWeight: 600, mb: 0.5 }}>
                          {name}
                        </Typography>
                        {(() => {
                          const specs = lookupGpuSpecs(gpuModel) || lookupGpuSpecs(name);
                          return (
                            <>
                              {(gpuModel || specs) && (
                                <Typography variant="body2" color="primary" sx={{ mb: 0.5, fontWeight: 600 }}>
                                  {gpuModel || specs?.key || ''}
                                </Typography>
                              )}
                              {specs && (
                                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                                  <Chip label={`${specs.vram} ${specs.vramUnit}`} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
                                  {specs.arch && <Chip label={specs.arch} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />}
                                  {specs.tdp && <Chip label={`${specs.tdp}W TDP`} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />}
                                </Stack>
                              )}
                            </>
                          );
                        })()}

                        <Box sx={{ mb: 2 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                            Specifications
                          </Typography>
                          <Stack spacing={0.5}>
                            <Typography variant="body2" color="text.secondary">GPUs: <strong>{gpus}</strong></Typography>
                            {(() => {
                              const specs = lookupGpuSpecs(gpuModel) || lookupGpuSpecs(name);
                              return specs ? (
                                <Typography variant="body2" color="text.secondary">VRAM Total: <strong>{specs.vram * (typeof gpus === 'number' ? gpus : 1)} GB</strong></Typography>
                              ) : null;
                            })()}
                            <Typography variant="body2" color="text.secondary">System Memory: <strong>{formatGiB(ramBytes)}</strong></Typography>
                            <Typography variant="body2" color="text.secondary">vCPUs: <strong>{vcpus}</strong></Typography>
                            {cfg.raw?.storage_gib && (
                              <Typography variant="body2" color="text.secondary">Storage: <strong>{cfg.raw.storage_gib} GiB</strong></Typography>
                            )}
                          </Stack>
                        </Box>

                        <Box sx={{ mb: 2 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                            Availability
                          </Typography>
                          <Chip
                            label={availability.label}
                            color={availability.color}
                            size="small"
                            sx={{ height: 22, textTransform: 'capitalize' }}
                          />
                        </Box>

                        <Box sx={{
                          backgroundColor: '#2d2d2a',
                          p: 1.5,
                          borderRadius: 1,
                          border: '1px solid #3d3d3a',
                          textAlign: 'center',
                          mb: 2
                        }}>
                          <Typography variant="h6" color="primary" sx={{ fontWeight: 700 }}>
                            {formatPrice(price)}
                          </Typography>
                          {monthly && (
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                              ~€{monthly}/month
                            </Typography>
                          )}
                        </Box>

                        <Button
                          variant="contained"
                          size="medium"
                          sx={{ textTransform: 'none', mt: 'auto', borderRadius: 1 }}
                          onClick={() => handleOpenScwLaunch({
                            ...cfg,
                            commercial_type: cfg.commercial_type || cfg.commercialType || cfg.id || name,
                            name,
                            price,
                            region: scwRegion
                          })}
                        >
                          Launch Instance
                        </Button>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, textAlign: 'center' }}>
                          Setup: ~20-25 min
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                );
              })}
            </Grid>
          </Box>
        )}

        {aggregatedViewMode === 'cloud' && selectedProvider === 'nebius' && isProviderConnected('nebius') && (
          <Box sx={{ mt: 3, mb: 4 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <CloudIcon color="primary" />
                <Typography variant="h6" sx={{ fontWeight: 600 }}>
                  Nebius GPU Platforms
                </Typography>
              </Box>
              {typeof getNebiusAuth === 'function' && (() => {
                const auth = getNebiusAuth();
                const selected = nebiusRegion;
                const rawProject = auth?.projectId;
                const resolved = resolveNebiusProjectId(rawProject, selected);
                const isMapped = typeof rawProject === 'string' && rawProject !== resolved;
                return (
                  <Typography variant="caption" color="text.secondary">
                    Project: {String(resolved || '')}{isMapped ? ' (mapped)' : ''}
                  </Typography>
                );
              })()}
              <Stack direction="row" spacing={1} alignItems="center">
                <FormControl size="small" sx={{ minWidth: 180 }}>
                  <InputLabel>Region</InputLabel>
                  <Select
                    label="Region"
                    value={nebiusRegion}
                    onChange={(e) => setNebiusRegion(e.target.value)}
                  >
                    {nebiusRegions.map((region) => (
                      <MenuItem key={region} value={region}>{region}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Button
                  variant="outlined"
                  size="small"
                  disabled={nebiusLoading}
                  onClick={() => fetchNebiusConfigs()}
                  sx={{ textTransform: 'none' }}
                >
                  {nebiusLoading ? 'Loading...' : 'Refresh'}
                </Button>
              </Stack>
            </Box>

            {nebiusLoading && nebiusAvailablePresets.length === 0 && (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                <CircularProgress size={28} />
              </Box>
            )}

            {(!nebiusAvailablePresets || nebiusAvailablePresets.length === 0) && !nebiusLoading && (
              <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
                No platforms returned for {nebiusRegion}. Ensure the region has a mapped project and you have access.
              </Alert>
            )}

            <Grid container spacing={2}>
              {(nebiusAvailablePresets || []).map((preset) => (
                <Grid item xs={12} md={6} lg={4} key={`${preset.platform_id || preset.platform_name || 'platform'}:${preset.id || preset.name}`}>
                  <Card variant="outlined" sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                    <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                      <Typography variant="h6" sx={{ fontWeight: 600, mb: 0.5 }}>
                        {preset.name || preset.id}
                      </Typography>
                      {preset.platform_name && (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          Platform: {preset.platform_name}
                        </Typography>
                      )}
                      {preset.platform_id && (
                        <Typography variant="caption" color="text.secondary" sx={{ mb: 1 }}>
                          Platform ID: {preset.platform_id}
                        </Typography>
                      )}

                      <Box sx={{ mb: 2 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                          Specifications
                        </Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" gap={0.5}>
                          <Chip size="small" label={`${preset.gpus || 0} GPU${(preset.gpus || 0) !== 1 ? 's' : ''}`} color="primary" />
                          <Chip size="small" label={`${preset.vcpus || preset.vcpu_count || 0} vCPUs`} variant="outlined" />
                          <Chip size="small" label={`${preset.memory_gb || preset.memory_gibibytes || 0} GB RAM`} variant="outlined" />
                          {preset.gpu_memory_gb && (
                            <Chip size="small" label={`${preset.gpu_memory_gb} GB GPU mem`} variant="outlined" />
                          )}
                        </Stack>
                      </Box>

                      {typeof preset.hourly_cost_usd === 'number' && (
                        <Paper variant="outlined" sx={{ p: 2, mb: 2, borderRadius: 2 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                            Estimated cost
                          </Typography>
                          <Typography variant="h5" sx={{ fontWeight: 700 }}>
                            {formatUsd(preset.hourly_cost_usd)}
                            <Typography component="span" variant="subtitle2" color="text.secondary" sx={{ ml: 1 }}>
                              / hour
                            </Typography>
                          </Typography>
                          {typeof preset.monthly_cost_usd === 'number' && (
                            <Typography variant="body2" color="text.secondary">
                              ~{formatUsd(preset.monthly_cost_usd)} / month
                            </Typography>
                          )}
                          {preset.cost_breakdown && Object.keys(preset.cost_breakdown).length > 0 && (
                            <Box sx={{ mt: 1 }}>
                              {Object.entries(preset.cost_breakdown).map(([label, values]) => (
                                <Typography key={label} variant="caption" color="text.secondary" display="block">
                                  {label.charAt(0).toUpperCase() + label.slice(1)}: {formatUsd(values?.hourly)} / h
                                </Typography>
                              ))}
                            </Box>
                          )}
                        </Paper>
                      )}

                      <Button
                        variant="contained"
                        sx={{ textTransform: 'none', borderRadius: 1, mt: 'auto' }}
                        endIcon={<PlayArrowIcon />}
                        onClick={() => handleOpenNebiusLaunch(preset)}
                      >
                        Launch Instance
                      </Button>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>

            {nebiusUnavailablePresets.length > 0 && (
              <Box sx={{ mt: 4 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1.5 }}>
                  Not available in {nebiusRegion}
                </Typography>
                <Grid container spacing={2}>
                  {nebiusUnavailablePresets.map((preset) => (
                    <Grid item xs={12} md={6} lg={4} key={`unavailable-${preset.platform_id || preset.platform_name || 'platform'}:${preset.id || preset.name}`}>
                      <Card
                        variant="outlined"
                        sx={{ opacity: 0.6, borderStyle: 'dashed', height: '100%' }}
                      >
                        <CardContent>
                          <Typography variant="subtitle1" sx={{ fontWeight: 500 }}>
                            {preset.name || preset.id}
                          </Typography>
                          {preset.platform_name && (
                            <Typography variant="body2" color="text.secondary">
                              Platform: {preset.platform_name}
                            </Typography>
                          )}
                          <Typography variant="caption" color="text.secondary">
                            Available in {Array.isArray(preset.platform_regions) && preset.platform_regions.length > 0
                              ? preset.platform_regions.join(', ')
                              : 'other regions'}
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                  ))}
                </Grid>
              </Box>
            )}
          </Box>
        )}

        {/* Instances Display for Selected Provider (shows ALL instances - running, stopped, etc.) */}
        {selectedProvider && isProviderConnected(selectedProvider) && 
         instances[selectedProvider] && instances[selectedProvider].length > 0 ? (
          <Box sx={{ mt: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, mb: 2 }}>
              <Stack direction="row" spacing={2} alignItems="center">
                <ComputerIcon color="primary" />
                <Typography variant="h6" sx={{ fontWeight: 600 }}>
                  {selectedProvider === 'scaleway'
                    ? 'Running Instances'
                    : `Instances (${instances[selectedProvider]?.length || 0})`}
                </Typography>
              </Stack>
              {selectedProvider === 'scaleway' && (
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<PlayArrowIcon />}
                  onClick={() => handleOpenScwLaunch()}
                  sx={{ textTransform: 'none' }}
                >
                  Launch New Instance
                </Button>
              )}
              {selectedProvider === 'nebius' && (
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<PlayArrowIcon />}
                  onClick={() => setNebiusLaunchOpen(true)}
                  sx={{ textTransform: 'none' }}
                >
                  Launch New Instance
                </Button>
              )}
            </Box>

              <Grid container spacing={2}>
                {instances[selectedProvider].map((instance, idx) => {
                  if (selectedProvider === 'lambda') {
                      const typeName =
                        instance?.instance_type?.name ||
                        instance?.instance_type_name ||
                        instance?.instance_type ||
                        instance?.plan_name ||
                        instance?.plan?.name ||
                        instance?.plan_slug ||
                        instance?.hardware_type ||
                        instance?.instance_type_id ||
                        'Unknown';
                      const ip =
                        instance.ip ||
                        instance.public_ip ||
                        instance.public_ip_address ||
                        instance.public_ip_address_v4 ||
                        instance.networking?.ip ||
                        instance.networking?.public_ip ||
                        instance.network?.public_ipv4 ||
                        instance.network?.ipv4?.public ||
                        instance.addresses?.[0] ||
                        instance.server?.public_ip ||
                        instance.server?.ipv4 ||
                        'N/A';
                      const status = instance.status || instance.state || 'unknown';
                      const statusLower = (status || '').toLowerCase();
                      // Lambda uses "active" for running instances, normalize it
                      const isRunning = statusLower === 'running' || statusLower === 'active';
                      const rawRegion =
                        instance.region ||
                        instance.region_name ||
                        instance.region_id ||
                        instance.zone ||
                        instance.availability_zone ||
                        instance.location ||
                        instance.instance_region ||
                        null;
                      const region =
                        typeof rawRegion === 'string'
                          ? rawRegion
                          : (rawRegion && typeof rawRegion === 'object'
                              ? (rawRegion.name || rawRegion.description || JSON.stringify(rawRegion))
                              : 'Unknown region');
                      const instanceId = instance.id;
                      const orchestration = instanceOrchestrations[instanceId];
                      const needsModelSelection = orchestration && 
                        orchestration.status === 'ready' && 
                        (!orchestration.model_deployed || orchestration.model_deployed === '');
                      
                      return (
                        <Grid item xs={12} md={6} key={instance.id || idx}>
                          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                              {instance.name || 'Unnamed'}
                            </Typography>
                            <Stack spacing={1}>
                              <Box>
                                <Typography variant="caption" color="text.secondary">Instance Type</Typography>
                                <Typography variant="body2">{typeName}</Typography>
                              </Box>
                              <Box>
                                <Typography variant="caption" color="text.secondary">Region</Typography>
                                <Typography variant="body2">{region}</Typography>
                              </Box>
                              <Stack direction="row" spacing={1} flexWrap="wrap" gap={1}>
                                <Chip 
                                  size="small" 
                                  label={status} 
                                  color={
                                    isRunning ? 'success' : 
                                    statusLower === 'stopped' ? 'default' : 
                                    statusLower === 'booting' ? 'warning' : 
                                    'default'
                                  } 
                                />
                                {ip !== 'N/A' && <Chip size="small" variant="outlined" label={`IP: ${ip}`} />}
                                {instanceId && <Chip size="small" variant="outlined" label={`ID: ${instanceId}`} />}
                                {orchestration && orchestration.model_deployed && (
                                  <Chip size="small" color="primary" label={`Model: ${orchestration.model_deployed.split('/').pop()}`} />
                                )}
                              </Stack>
                              {typeName === 'Unknown' && (
                                <Typography variant="caption" color="text.secondary">
                                  Instance details not fully provided by API; ID: {instanceId || 'N/A'}
                                </Typography>
                              )}
                              {needsModelSelection ? (
                                <Button
                                  size="small"
                                  variant="contained"
                                  color="primary"
                                  startIcon={<PlayArrowIcon />}
                                  onClick={async () => {
                                    // Open orchestration dialog for model selection
                                    setOrchestrationId(orchestration.orchestration_id);
                                    setOrchestrationStatus(orchestration);
                                    setOrchestrationDialogOpen(true);
                                  }}
                                  sx={{ mt: 1, textTransform: 'none' }}
                                >
                                  Select Model to Deploy
                                </Button>
                              ) : isRunning && (
                              <Button
                                size="small"
                                variant="contained"
                                startIcon={<PlayArrowIcon />}
                                onClick={() => {
                                  const instanceData = {
                                    id: instance.id,
                                    name: instance.name,
                                    instanceType: instance.instance_type,
                                    gpuDescription: instance.instance_type?.gpu_description,
                                    priceCentsPerHour: instance.instance_type?.price_cents_per_hour,
                                    ipAddress: ip,
                                    sshUser: 'ubuntu',
                                    provider: 'lambda',
                                    vendor: 'Lambda',
                                    status: isRunning ? 'running' : (status || 'unknown'),
                                  };
                                  navigate('/telemetry', { state: { instanceData } });
                                }}
                                sx={{ mt: 1, textTransform: 'none' }}
                              >
                                Manage Instance
                              </Button>
                              )}
                            </Stack>
                          </Paper>
                        </Grid>
                      );
                    } else if (selectedProvider === 'nebius') {
                      const name = instance.name || instance.id || `Instance ${idx + 1}`;
                      const status = instance.status || 'unknown';
                      const statusColor = status === 'running' ? 'success' : 
                                         status === 'stopped' ? 'default' : 
                                         status === 'starting' || status === 'creating' ? 'warning' : 
                                         status === 'stopping' || status === 'deleting' ? 'error' : 
                                         'default';
                      const instanceType = instance.instance_type || 'N/A';
                      const publicIp = instance.public_ip || 'N/A';
                      const privateIp = instance.private_ip || 'N/A';
                      const zone = instance.zone || 'N/A';
                      const gpus = instance.gpus || 'N/A';
                      const vcpus = instance.vcpus || 'N/A';
                      const memoryGb = instance.memory_gb || 'N/A';
                      
                      return (
                        <Grid item xs={12} md={6} lg={4} key={instance.id || idx}>
                          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, height: '100%', display: 'flex', flexDirection: 'column' }}>
                            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                              {name}
                            </Typography>
                            <Stack spacing={1} sx={{ flex: 1 }}>
                              <Box>
                                <Typography variant="caption" color="text.secondary">Instance Type</Typography>
                                <Typography variant="body2">{instanceType}</Typography>
                              </Box>
                              {gpus !== 'N/A' && (
                                <Box>
                                  <Typography variant="caption" color="text.secondary">Specifications</Typography>
                                  <Stack direction="row" spacing={1} flexWrap="wrap" gap={0.5} sx={{ mt: 0.5 }}>
                                    <Chip size="small" variant="outlined" label={`${gpus} GPU${gpus !== 1 ? 's' : ''}`} />
                                    <Chip size="small" variant="outlined" label={`${vcpus} vCPUs`} />
                                    <Chip size="small" variant="outlined" label={`${memoryGb}GB RAM`} />
                                  </Stack>
                                </Box>
                              )}
                              <Stack direction="row" spacing={1} flexWrap="wrap" gap={1}>
                                <Chip 
                                  size="small" 
                                  label={status} 
                                  color={statusColor}
                                  sx={{ textTransform: 'capitalize' }}
                                />
                                {zone !== 'N/A' && <Chip size="small" variant="outlined" label={zone} />}
                              </Stack>
                              <Stack direction="row" spacing={1} flexWrap="wrap" gap={1}>
                                {publicIp !== 'N/A' && <Chip size="small" variant="outlined" label={`IP: ${publicIp}`} />}
                                {privateIp !== 'N/A' && <Chip size="small" variant="outlined" label={`Private: ${privateIp}`} />}
                              </Stack>
                              <Stack spacing={1} sx={{ mt: 'auto' }}>
                                {status === 'running' && (
                                  <Button
                                    size="small"
                                    variant="contained"
                                    startIcon={<PlayArrowIcon />}
                                    onClick={() => {
                                      const finalIp = publicIp !== 'N/A' ? publicIp : (privateIp !== 'N/A' ? privateIp : '');
                                      const instanceData = {
                                        id: instance.id,
                                        name: name,
                                        instanceType: instanceType,
                                        gpuDescription: instance.gpu_model || instance.gpu_description,
                                        gpuModel: instance.gpu_model || instance.gpu_description,
                                        gpuCount: typeof gpus === 'number' ? gpus : (gpus !== 'N/A' ? parseInt(gpus) || 0 : 0),
                                        vcpus: typeof vcpus === 'number' ? vcpus : (vcpus !== 'N/A' ? parseInt(vcpus) || 0 : 0),
                                        memoryGb: typeof memoryGb === 'number' ? memoryGb : (memoryGb !== 'N/A' ? parseFloat(memoryGb) || 0 : 0),
                                        ipAddress: finalIp,
                                        ip: finalIp,
                                        sshUser: 'ubuntu',
                                        provider: 'nebius',
                                        vendor: 'Nebius',
                                        zone: zone,
                                        region: zone,
                                        status: status || 'running',
                                      };
                                      navigate('/telemetry', { state: { instanceData } });
                                    }}
                                    sx={{ textTransform: 'none', width: '100%' }}
                                  >
                                    Manage Instance
                                  </Button>
                                )}
                                <Button
                                  size="small"
                                  variant="outlined"
                                  color="error"
                                  startIcon={<DeleteOutlineIcon />}
                                  onClick={() => setNebiusDeleteDialog({ open: true, instance })}
                                  sx={{ textTransform: 'none', width: '100%' }}
                                >
                                  Delete Instance
                                </Button>
                              </Stack>
                            </Stack>
                          </Paper>
                        </Grid>
                      );
                    } else if (selectedProvider === 'scaleway') {
                      const raw = instance.raw || {};
                      const name = instance.name || raw.hostname || instance.id || `Server ${idx + 1}`;
                      const typeName = instance.commercial_type || raw.commercial_type || 'N/A';
                      const matchedConfig = scwConfigs.find(cfg => getScwCommercialType(cfg) === typeName);
                      const statusLabel = instance.status || instance.state || raw.state || 'unknown';
                      const normalizedStatus = statusLabel.toLowerCase();
                      
                      // Map Scaleway states to display status
                      // "starting" -> "Booting" (like Lambda)
                      // "stopped" -> "Running" (Scaleway quirk - stopped means running)
                      let displayStatus;
                      if (normalizedStatus === 'starting' || normalizedStatus === 'booting' || normalizedStatus === 'pending') {
                        displayStatus = 'Booting';
                      } else if (normalizedStatus === 'stopped') {
                        displayStatus = 'Running';
                      } else {
                        // Capitalize first letter for display
                        displayStatus = statusLabel.charAt(0).toUpperCase() + statusLabel.slice(1);
                      }
                      
                      // Determine status color
                      // Booting = warning (orange), Running = success (green), Error = error (red)
                      const statusColor = normalizedStatus === 'starting' || normalizedStatus === 'booting'
                        ? 'warning'
                        : displayStatus.toLowerCase().includes('run') || normalizedStatus === 'stopped'
                          ? 'success'
                          : normalizedStatus.includes('stop')
                            ? 'default'
                            : normalizedStatus.includes('error') || normalizedStatus.includes('fail')
                              ? 'error'
                              : 'warning';
                      // Determine if instance is running - Scaleway uses "stopped" state for running instances
                      // If statusColor is 'success', the chip is green which means it's running
                      // Also check normalized status and display status for running indicators
                      const isRunning = statusColor === 'success' || 
                                       normalizedStatus === 'running' || 
                                       normalizedStatus === 'stopped' ||
                                       (displayStatus && typeof displayStatus === 'string' && displayStatus.toLowerCase().includes('run'));
                      const gpus = matchedConfig?.gpu ?? matchedConfig?.raw?.gpu_count ?? matchedConfig?.raw?.gpu ?? raw.gpu ?? raw.gpu_count ?? 'N/A';
                      const vcpus = matchedConfig?.vcpus ?? matchedConfig?.raw?.ncpus ?? matchedConfig?.raw?.vcpu_count ?? raw.vcpu ?? raw.ncpus ?? 'N/A';
                      const ramBytes = matchedConfig?.ram_bytes ?? matchedConfig?.raw?.ram ?? matchedConfig?.raw?.memory ?? raw.memory ?? raw.ram ?? null;
                      const storageBytes = matchedConfig?.raw?.storage_gib ? matchedConfig.raw.storage_gib * 1024 ** 3 : raw.volumes?.[0]?.size || raw.root_volume?.size || null;
                      const storageGiB = storageBytes ? (storageBytes / (1024 ** 3)).toFixed(0) : null;
                      const hourlyPrice = matchedConfig?.hourly_price ?? matchedConfig?.priceEurHour ?? matchedConfig?.raw?.hourly_price?.price ?? matchedConfig?.raw?.hourly_price ?? raw.hourly_price ?? null;
                      const priceLabel = formatEuroPrice(hourlyPrice);
                      const monthlyPrice = hourlyPrice ? (hourlyPrice * 24 * 30).toFixed(0) : null;
                      const gpuModel = matchedConfig?.raw?.gpu_name || matchedConfig?.raw?.gpu_model || raw.gpu_model || raw.gpu_name;
                      // Extract IP addresses - handle various Scaleway API response formats
                      const publicIp = instance.public_ip || raw.public_ip?.address || (Array.isArray(raw.public_ips) && raw.public_ips[0]?.address) || null;
                      const privateIp = instance.private_ip || raw.private_ip || (Array.isArray(raw.private_ips) && raw.private_ips[0]) || null;
                      // Clean and validate IPs
                      const cleanPublicIp = publicIp && typeof publicIp === 'string' && publicIp.trim() !== '' && publicIp !== 'N/A' ? publicIp.trim() : null;
                      const cleanPrivateIp = privateIp && typeof privateIp === 'string' && privateIp.trim() !== '' && privateIp !== 'N/A' ? privateIp.trim() : null;
                      const hasIp = cleanPublicIp || cleanPrivateIp;
                      const createdAt = instance.created_at || raw.creation_date || raw.created_at;
                      let createdDisplay = null;
                      if (createdAt) {
                        const date = new Date(createdAt);
                        createdDisplay = Number.isNaN(date.getTime()) ? createdAt : date.toLocaleString();
                      }
                      const zone = instance.zone || raw.zone || scwInstancesZone || scwRegion;
                      const consoleUrl = zone && instance.id
                        ? `https://console.scaleway.com/instances/servers/${zone}/${instance.id}`
                        : 'https://console.scaleway.com/instances/servers';

                      const displayName = typeName && typeName !== 'N/A' ? typeName : name;
                      return (
                        <Grid item xs={12} md={5} lg={4} key={instance.id || idx}>
                          <Paper
                            variant="outlined"
                            sx={{
                              p: 2,
                              borderRadius: 2,
                              display: 'flex',
                              flexDirection: 'column',
                              height: '100%',
                              maxWidth: 420,
                              width: '100%',
                              mx: 'auto'
                            }}
                          >
                            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                              {displayName}
                            </Typography>
                            {name && name !== displayName && (
                              <Typography variant="caption" color="text.secondary" sx={{ mb: 1 }}>
                                {name}
                              </Typography>
                            )}
                            {gpuModel && (
                              <Typography variant="caption" color="text.secondary" sx={{ mb: 1 }}>
                                GPU: {gpuModel}
                              </Typography>
                            )}
                            <Box sx={{ mb: 1.5 }}>
                              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                                Specifications
                              </Typography>
                              <Stack spacing={0.4}>
                                <Typography variant="body2" color="text.secondary">GPUs: <strong>{gpus}</strong></Typography>
                                <Typography variant="body2" color="text.secondary">System Memory: <strong>{formatGiB(ramBytes)}</strong></Typography>
                                <Typography variant="body2" color="text.secondary">vCPUs: <strong>{vcpus}</strong></Typography>
                                {storageGiB && (
                                  <Typography variant="body2" color="text.secondary">Storage: <strong>{storageGiB} GiB</strong></Typography>
                                )}
                              </Stack>
                            </Box>
                            <Box sx={{ mb: 1.5 }}>
                              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                                Status
                              </Typography>
                              <Stack direction="row" spacing={1} flexWrap="wrap">
                                <Chip size="small" label={displayStatus} color={statusColor} sx={{ textTransform: 'capitalize' }} />
                                {zone && <Chip size="small" variant="outlined" label={zone} />}
                              </Stack>
                            </Box>
                            <Stack direction="row" spacing={1} flexWrap="wrap" gap={1} sx={{ mb: 1 }}>
                              {cleanPublicIp && <Chip size="small" variant="outlined" label={`IP: ${cleanPublicIp}`} />}
                              {cleanPrivateIp && <Chip size="small" variant="outlined" label={`Private: ${cleanPrivateIp}`} />}
                            </Stack>
                            {priceLabel && (
                              <Box sx={{
                                backgroundColor: '#f5f7fb',
                                p: 1.5,
                                borderRadius: 1,
                                border: '1px solid #e1e7f0',
                                textAlign: 'center',
                                mb: 1.5
                              }}>
                                <Typography variant="h6" color="primary" sx={{ fontWeight: 700 }}>
                                  {priceLabel}
                                </Typography>
                                {monthlyPrice && (
                                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                                    ~€{monthlyPrice}/month
                                  </Typography>
                                )}
                              </Box>
                            )}
                            {createdDisplay && (
                              <Box sx={{ mb: 1 }}>
                                <Typography variant="caption" color="text.secondary">Created</Typography>
                                <Typography variant="body2">{createdDisplay}</Typography>
                              </Box>
                            )}
                            {/* Show Manage Instance button if running (green status chip), and always show Delete button */}
                            <Stack spacing={1} sx={{ mt: 'auto' }}>
                              {statusColor === 'success' && (
                                <Button
                                  size="small"
                                  variant="contained"
                                  startIcon={<PlayArrowIcon />}
                                  onClick={() => {
                                    const finalIp = cleanPublicIp || cleanPrivateIp || '';
                                    console.log('Scaleway instance IP extraction:', {
                                      instanceId: instance.id,
                                      publicIp: publicIp,
                                      cleanPublicIp: cleanPublicIp,
                                      privateIp: privateIp,
                                      cleanPrivateIp: cleanPrivateIp,
                                      finalIp: finalIp,
                                      rawInstance: instance,
                                      rawData: raw
                                    });
                                    const instanceData = {
                                      id: instance.id,
                                      name: name,
                                      instanceType: typeName,
                                      gpuDescription: gpuModel,
                                      gpuModel: gpuModel,
                                      gpuCount: typeof gpus === 'number' ? gpus : (gpus !== 'N/A' ? parseInt(gpus) || 0 : 0),
                                      vcpus: typeof vcpus === 'number' ? vcpus : (vcpus !== 'N/A' ? parseInt(vcpus) || 0 : 0),
                                      ramBytes: ramBytes,
                                      priceEurHour: hourlyPrice,
                                      ipAddress: finalIp,
                                      ip: finalIp, // Also set 'ip' field for compatibility
                                      sshUser: 'root',
                                      provider: 'scaleway',
                                      vendor: 'Scaleway',
                                      zone: zone,
                                      region: zone,
                                      status: (instance.status || instance.state || '').toLowerCase() || 'running',
                                    };
                                    navigate('/telemetry', { state: { instanceData } });
                                  }}
                                  sx={{ textTransform: 'none', width: '100%' }}
                                >
                                  Manage Instance
                                </Button>
                              )}
                              <Button
                                size="small"
                                variant="outlined"
                                color="error"
                                startIcon={<DeleteOutlineIcon />}
                                onClick={() => setScwDeleteDialog({ open: true, instance: { ...instance, zone, displayName } })}
                                sx={{ textTransform: 'none', width: '100%' }}
                              >
                                Delete Instance
                              </Button>
                            </Stack>
                            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, textAlign: 'center' }}>
                              Setup typically 20-25 min
                            </Typography>
                          </Paper>
                        </Grid>
                      );
                    }
                    return null;
                  })}
              </Grid>
          </Box>
        ) : selectedProvider === 'lambda' && isProviderConnected('lambda') && instances.lambda && instances.lambda.length === 0 ? (
          <Box sx={{ mt: 3, textAlign: 'center', py: 4 }}>
            <ComputerIcon sx={{ fontSize: 64, color: 'text.secondary', opacity: 0.5, mb: 2 }} />
            <Typography variant="h6" color="text.secondary" sx={{ mb: 1 }}>
              No Instances Found
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              You don't have any running instances. Launch a new instance to get started.
            </Typography>
            <Button
              variant="contained"
              startIcon={<PlayArrowIcon />}
              onClick={async () => {
                try {
                  const raw = localStorage.getItem(storageKey('lambda'));
                  if (!raw) {
                    setError('Lambda API key not found');
                    return;
                  }
                  const parsed = JSON.parse(raw);
                  if (!parsed.apiKey) {
                    setError('Lambda API key not found');
                    return;
                  }
                  await fetchLaunchData(parsed.apiKey);
                  setLaunchDialogOpen(true);
                } catch (e) {
                  setError('Failed to load launch data: ' + e.message);
                }
              }}
              sx={{ textTransform: 'none' }}
            >
              Launch New Instance
            </Button>
          </Box>
        ) : selectedProvider === 'scaleway' && isProviderConnected('scaleway') && instances.scaleway && instances.scaleway.length === 0 ? (
          <Box sx={{ mt: 3, textAlign: 'center', py: 4 }}>
            <ComputerIcon sx={{ fontSize: 64, color: 'text.secondary', opacity: 0.5, mb: 2 }} />
            <Typography variant="h6" color="text.secondary" sx={{ mb: 1 }}>
              No Instances Found
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              You don't have any running Scaleway servers. Fetch instances for {scwRegion} or launch a new GPU configuration above.
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="center">
              <Button
                variant="contained"
                startIcon={<PlayArrowIcon />}
                onClick={() => fetchScalewayInstances(scwRegion)}
                sx={{ textTransform: 'none' }}
              >
                Refresh Instances
              </Button>
              <Button
                variant="outlined"
                startIcon={<PlayArrowIcon />}
                onClick={() => handleOpenScwLaunch()}
                sx={{ textTransform: 'none' }}
              >
                Launch New Instance
              </Button>
            </Stack>
            <Button
              size="small"
              sx={{ mt: 2, textTransform: 'none' }}
              startIcon={<OpenInNewIcon />}
              onClick={() => window.open('https://console.scaleway.com/instances/servers', '_blank', 'noopener,noreferrer')}
            >
              Open Scaleway Console
            </Button>
          </Box>
        ) : null}

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        )}
      </Box>
    </Box>

      {/* Integration Modal */}
      <Dialog
        open={Boolean(openModal)}
        onClose={handleCloseModal}
        maxWidth="sm"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2
          }
        }}
        BackdropProps={{
          sx: {
            backgroundColor: 'rgba(0, 0, 0, 0.5)'
          }
        }}
      >
        {openModal && (() => {
          const provider = PROVIDERS.find(p => p.id === openModal);
          const data = formData[openModal];
          
          return (
            <>
              <DialogTitle sx={{ fontWeight: 600, pb: 1, display: 'flex', alignItems: 'center', gap: 2 }}>
                <Box
                  component="img"
                  src={provider.logo}
                  alt={provider.name}
                  onError={(e) => {
                    e.target.style.display = 'none';
                  }}
                  sx={{
                    width: 40,
                    height: 40,
                    objectFit: 'contain',
                    objectPosition: 'center',
                    borderRadius: 1,
                    backgroundColor: provider.bgColor || 'background.paper',
                    padding: provider.id === 'lambda' ? '6px' : provider.id === 'aws' ? '4px' : provider.id === 'scaleway' ? '4px' : '4px',
                    flexShrink: 0
                  }}
                />
                {provider.name}
              </DialogTitle>
              <DialogContent>
                <Box sx={{ mb: 3 }}>
                  <Link
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      setShowHelpDialog(openModal);
                    }}
                    sx={{
                      textDecoration: 'none',
                      color: 'primary.main',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 0.5,
                      '&:hover': {
                        textDecoration: 'underline'
                      }
                    }}
                  >
                    <HelpOutlineIcon fontSize="small" />
                    How get Keys?
                  </Link>
                                    </Box>
                
                {openModal === 'lambda' && (
              <TextField
                fullWidth
                    label="API Key"
                    value={data.apiKey}
                    onChange={(e) => handleInputChange('lambda', 'apiKey', e.target.value)}
                  type="password"
                    sx={{ mb: 2 }}
                    placeholder="Enter your Lambda Labs API key"
                  />
                )}
                
                {openModal === 'aws' && (
                  <>
                <TextField
                  fullWidth
                      label="Access Key ID"
                      value={data.accessKeyId}
                      onChange={(e) => handleInputChange('aws', 'accessKeyId', e.target.value)}
                      sx={{ mb: 2 }}
                      placeholder="Enter your AWS Access Key ID"
                    />
                <TextField
                  fullWidth
                      label="Secret Access Key"
                      value={data.secretAccessKey}
                      onChange={(e) => handleInputChange('aws', 'secretAccessKey', e.target.value)}
                      type="password"
                      sx={{ mb: 2 }}
                      placeholder="Enter your AWS Secret Access Key"
                    />
                  </>
                )}
                
                {openModal === 'scaleway' && (
                  <>
                <TextField
                  fullWidth
                  label="Access Key ID"
                  value={data.accessKeyId}
                  onChange={(e) => handleInputChange('scaleway', 'accessKeyId', e.target.value)}
                  sx={{ mb: 2 }}
                  placeholder="Enter your Scaleway Access Key ID"
                  type="password"
                />
                <TextField
                  fullWidth
                  label="Secret Key"
                  value={data.secretKey}
                      onChange={(e) => handleInputChange('scaleway', 'secretKey', e.target.value)}
                      type="password"
                      sx={{ mb: 2 }}
                      placeholder="Enter your Scaleway Secret Key"
                    />
                <TextField
                  fullWidth
                  label="Project ID"
                  value={data.projectId}
                  onChange={(e) => handleInputChange('scaleway', 'projectId', e.target.value)}
                  sx={{ mb: 2 }}
                  placeholder="Enter your Scaleway Project ID"
                  type="password"
                />
                  </>
                )}

                {openModal === 'nebius' && (
                  <>
                <TextField
                  fullWidth
                  label="Service Account ID"
                  value={data.serviceAccountId}
                  onChange={(e) => handleInputChange('nebius', 'serviceAccountId', e.target.value)}
                  type="password"
                  sx={{ mb: 2 }}
                  placeholder="serviceaccount-xxxxxxxxxxxxx"
                />
                <TextField
                  fullWidth
                  label="Authorized Key ID"
                  value={data.keyId}
                  onChange={(e) => handleInputChange('nebius', 'keyId', e.target.value)}
                  type="password"
                  sx={{ mb: 2 }}
                  placeholder="accesskey-xxxxxxxxxxxxx"
                />
                <TextField
                  fullWidth
                  label="Project ID"
                  value={data.projectId}
                  onChange={(e) => handleInputChange('nebius', 'projectId', e.target.value)}
                  type="password"
                  sx={{ mb: 2 }}
                  placeholder="project-e00c6v7zpr00335jxwamz1"
                  required
                />
                <TextField
                  fullWidth
                  label="Private Key (PEM)"
                  value={data.secretKey}
                  onChange={(e) => handleInputChange('nebius', 'secretKey', e.target.value)}
                  type="password"
                  multiline
                  rows={4}
                  sx={{ 
                    mb: 2, 
                    fontFamily: 'monospace', 
                    fontSize: '0.85rem',
                    '& textarea': {
                      WebkitTextSecurity: 'disc'
                    }
                  }}
                  placeholder="-----BEGIN PRIVATE KEY-----\n..."
                />
                  </>
                )}
              </DialogContent>
              <DialogActions sx={{ p: 2, pt: 1 }}>
                      <Button
                  onClick={handleCloseModal}
                  sx={{ textTransform: 'none', borderRadius: 1 }}
                >
                  Cancel
                      </Button>
                      <Button
                  onClick={async () => {
                    setLoading(true);
                    await validateAndSave(openModal);
                    setLoading(false);
                  }}
                  variant="contained"
                  disabled={loading}
                  sx={{ textTransform: 'none', borderRadius: 1 }}
                >
                  {loading ? 'Saving...' : 'Save'}
                      </Button>
              </DialogActions>
            </>
          );
        })()}
      </Dialog>

      {/* Nebius Launch Modal */}
      <Dialog
        open={nebiusLaunchOpen}
        onClose={() => {
          setNebiusLaunchOpen(false);
          setNebiusLaunchForm(NEBUS_INITIAL_LAUNCH_FORM);
        }}
        maxWidth="sm"
        fullWidth
        PaperProps={{ sx: { borderRadius: 2 } }}
      >
        <DialogTitle sx={{ fontWeight: 600, pb: 1 }}>
          Launch Nebius Instance
        </DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <FormControl fullWidth size="small">
            <InputLabel>Preset</InputLabel>
            <Select
              label="Preset"
              value={nebiusLaunchForm.presetId}
              onChange={(e) => setNebiusLaunchForm(prev => ({ ...prev, presetId: e.target.value }))}
            >
              {nebiusAvailablePresets.map((preset) => (
                <MenuItem key={preset.id || preset.name} value={preset.id || preset.name}>
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {preset.name || preset.id}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      {preset.gpus || 0} GPUs • {preset.vcpus || 0} vCPUs • {preset.memory_gb || 0} GB RAM
                      {preset.platform_name && ` • ${preset.platform_name}`}
                    </Typography>
                  </Box>
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl fullWidth size="small">
            <InputLabel>Zone</InputLabel>
            <Select
              label="Zone"
              value={nebiusLaunchForm.zoneId}
              onChange={(e) => setNebiusLaunchForm(prev => ({ ...prev, zoneId: e.target.value }))}
            >
              {nebiusZoneOptions.map((zone) => (
                <MenuItem key={zone} value={zone}>
                  {zone}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {envSSHKey ? (
            <Box sx={{ mt: 1, p: 2, borderRadius: '8px', border: '1px solid #3d3d3a', backgroundColor: 'rgba(129, 140, 248, 0.06)' }}>
              <Typography variant="body2" sx={{ color: '#34d399', fontWeight: 600, mb: 0.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                <VpnKeyIcon sx={{ fontSize: 16 }} /> SSH Key Auto-configured
              </Typography>
              <Typography variant="caption" sx={{ color: '#a8a8a0', fontFamily: '"DM Mono", monospace', wordBreak: 'break-all' }}>
                {nebiusLaunchForm.sshPublicKey?.substring(0, 80)}...
              </Typography>
            </Box>
          ) : (
            <TextField
              fullWidth
              label="SSH Public Key"
              multiline
              rows={4}
              value={nebiusLaunchForm.sshPublicKey}
              onChange={(e) => setNebiusLaunchForm(prev => ({ ...prev, sshPublicKey: e.target.value }))}
              placeholder="ssh-rsa AAAAB3NzaC1yc2E... your-email@example.com"
              helperText="Paste your SSH public key here. This will be injected into the instance."
              sx={{ mt: 1 }}
            />
          )}
          <TextField
            fullWidth
            label="SSH Key Name (optional)"
            value={nebiusLaunchForm.sshKeyName}
            onChange={(e) => setNebiusLaunchForm(prev => ({ ...prev, sshKeyName: e.target.value }))}
            placeholder="e.g., dio-nebius-key"
            helperText="Use a friendly name to identify the key on this launch."
          />
        </DialogContent>
        <DialogActions sx={{ p: 2, pt: 1 }}>
          <Button
            onClick={() => {
              setNebiusLaunchOpen(false);
              setNebiusLaunchForm(NEBUS_INITIAL_LAUNCH_FORM);
            }}
            sx={{ textTransform: 'none' }}
            disabled={nebiusLaunchLoading}
          >
            Cancel
          </Button>
          <Button
            onClick={handleLaunchNebiusInstance}
            variant="contained"
            disabled={
              nebiusLaunchLoading ||
              !nebiusLaunchForm.presetId ||
              !nebiusLaunchForm.sshPublicKey?.trim() ||
              nebiusAvailablePresets.length === 0
            }
            sx={{ textTransform: 'none' }}
          >
            {nebiusLaunchLoading ? 'Launching...' : 'Launch Instance'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Help Dialog */}
      <Dialog
        open={Boolean(showHelpDialog)}
        onClose={() => setShowHelpDialog(null)}
        maxWidth="sm"
                      fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2
          }
        }}
      >
        {showHelpDialog && (() => {
          const provider = PROVIDERS.find(p => p.id === showHelpDialog);
                        return (
            <>
              <DialogTitle sx={{ fontWeight: 600, pb: 1 }}>
                How to Get {provider.name} Keys
              </DialogTitle>
              <DialogContent>
                <Typography variant="body1" sx={{ whiteSpace: 'pre-line', mb: 2 }}>
                  {provider.helpText}
                </Typography>
                <Link
                  href={provider.helpUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                              sx={{ 
                    textDecoration: 'none',
                    color: 'primary.main',
                    '&:hover': {
                      textDecoration: 'underline'
                    }
                  }}
                >
                  View Official Documentation →
                </Link>
              </DialogContent>
              <DialogActions sx={{ p: 2, pt: 1 }}>
                                <Button
                  onClick={() => setShowHelpDialog(null)}
                  variant="contained"
                  sx={{ textTransform: 'none', borderRadius: 1 }}
                >
                  Close
                                </Button>
              </DialogActions>
            </>
          );
        })()}
      </Dialog>

      {/* Launch Instance Dialog */}
      <Dialog
        open={launchDialogOpen}
        onClose={() => setLaunchDialogOpen(false)}
        onEnter={() => {
          // Fetch data when dialog opens if not already loaded
          if (instanceTypes.length === 0 && !launchLoading) {
            const raw = localStorage.getItem(storageKey('lambda'));
            if (raw) {
              try {
                const parsed = JSON.parse(raw);
                if (parsed.apiKey) {
                  fetchLaunchData(parsed.apiKey);
                }
              } catch (e) {
                // Silently fail - user can re-enter credentials
              }
            }
          }
        }}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2
          }
        }}
      >
        <DialogTitle sx={{ fontWeight: 600, pb: 1, display: 'flex', alignItems: 'center', gap: 2 }}>
          <PlayArrowIcon color="primary" />
          Launch New Lambda Instance
        </DialogTitle>
        <DialogContent sx={{ maxHeight: '80vh', overflowY: 'auto' }}>
          <Stack spacing={3} sx={{ mt: 1 }}>
            {error && (
              <Alert severity="error" onClose={() => setError('')} sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}
            {message && (
              <Alert severity="success" onClose={() => setMessage('')} sx={{ mb: 2 }}>
                {message}
              </Alert>
            )}
            {launchLoading && instanceTypes.length === 0 ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', py: 4 }}>
                <CircularProgress sx={{ mb: 2 }} />
                <Typography variant="body2" color="text.secondary">
                  Loading instance types...
                </Typography>
              </Box>
            ) : instanceTypes.length === 0 ? (
              <Alert severity="info" sx={{ mb: 2 }}>
                <Typography variant="body2">
                  No instance types loaded. Please click "Fetch Instances" first to load available configurations.
                </Typography>
              </Alert>
            ) : (
              <>
                <FormControl fullWidth>
                  <InputLabel>GPU Instance Type</InputLabel>
                  <Select
                    value={launchForm.instanceType}
                    label="GPU Instance Type"
                    onChange={(e) => {
                      const selectedType = e.target.value;
                      setLaunchForm(prev => ({ 
                        ...prev, 
                        instanceType: selectedType,
                        // Reset region when instance type changes
                        region: ''
                      }));
                    }}
                  >
                    {instanceTypes.map((type) => {
                      const specs = type.specs || type;
                      return (
                        <MenuItem key={type.name || type.instance_type_name} value={type.name || type.instance_type_name}>
                          <Box>
                            <Typography variant="body1" sx={{ fontWeight: 600 }}>
                              {type.name || type.instance_type_name}
                            </Typography>
                            {type.gpu_description && (
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                {type.gpu_description}
                              </Typography>
                            )}
                            {(specs.gpus || specs.memory_gib || specs.vcpus) && (
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                {specs.gpus ? `${specs.gpus} GPUs` : ''} 
                                {specs.gpus && specs.memory_gib ? ' • ' : ''}
                                {specs.memory_gib ? `${specs.memory_gib} GiB RAM` : ''}
                                {specs.vcpus ? ` • ${specs.vcpus} vCPUs` : ''}
                              </Typography>
                            )}
                            {type.price_cents_per_hour && (
                              <Typography variant="caption" color="primary" sx={{ display: 'block', fontWeight: 600 }}>
                                ${(type.price_cents_per_hour / 100).toFixed(2)}/hour
                              </Typography>
                            )}
                          </Box>
                        </MenuItem>
                      );
                    })}
                  </Select>
                </FormControl>

                <FormControl fullWidth>
                  <InputLabel>Region</InputLabel>
                  <Select
                    value={launchForm.region}
                    label="Region"
                    onChange={(e) => setLaunchForm(prev => ({ ...prev, region: e.target.value }))}
                    disabled={!launchForm.instanceType}
                  >
                    {(() => {
                      // Filter regions based on selected instance type
                      let availableRegions = regions;
                      if (launchForm.instanceType) {
                        const selectedType = instanceTypes.find(
                          type => (type.name || type.instance_type_name) === launchForm.instanceType
                        );
                        if (selectedType && selectedType.regions && Array.isArray(selectedType.regions) && selectedType.regions.length > 0) {
                          // Only show regions that have capacity for this instance type
                          const typeRegions = new Set(selectedType.regions.map(r => 
                            typeof r === 'string' ? r : (r.name || r)
                          ));
                          availableRegions = regions.filter(region => {
                            const regionName = typeof region === 'string' ? region : (region.name || region);
                            return typeRegions.has(regionName);
                          });
                        }
                      }
                      
                      return availableRegions.length > 0 ? (
                        availableRegions.map((region) => {
                          const regionName = typeof region === 'string' ? region : (region.name || region);
                          const regionDesc = typeof region === 'object' ? region.description : '';
                          const hasCapacity = typeof region === 'object' ? region.has_capacity : false;
                          return (
                            <MenuItem key={regionName} value={regionName}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                                <Typography variant="body2" sx={{ flex: 1 }}>
                                  {regionName} {regionDesc ? `- ${regionDesc}` : ''}
                                </Typography>
                                {hasCapacity && (
                                  <Chip 
                                    label="Available" 
                                    size="small" 
                                    color="success" 
                                    sx={{ height: 20, fontSize: '0.65rem' }}
                                  />
                                )}
                              </Box>
                            </MenuItem>
                          );
                        })
                      ) : (
                        <MenuItem value="us-east-1" disabled>
                          {launchForm.instanceType 
                            ? 'No regions available for this instance type' 
                            : 'Select an instance type first'}
                        </MenuItem>
                      );
                    })()}
                  </Select>
                  {launchForm.instanceType && (() => {
                    const selectedType = instanceTypes.find(
                      type => (type.name || type.instance_type_name) === launchForm.instanceType
                    );
                    const availableRegions = selectedType?.regions || [];
                    const regionCount = availableRegions.length;
                    return regionCount > 0 ? (
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                        {regionCount} region{regionCount !== 1 ? 's' : ''} with capacity available for this instance type
                      </Typography>
                    ) : (
                      <Typography variant="caption" color="error" sx={{ mt: 0.5, display: 'block' }}>
                        No regions with capacity available for this instance type
                      </Typography>
                    );
                  })()}
                </FormControl>

                {envSSHKey ? (
                  <Box sx={{ mt: 1, p: 2, borderRadius: '8px', border: '1px solid #3d3d3a', backgroundColor: 'rgba(129, 140, 248, 0.06)' }}>
                    <Typography variant="body2" sx={{ color: '#34d399', fontWeight: 600, mb: 0.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                      <VpnKeyIcon sx={{ fontSize: 16 }} /> SSH Key Auto-configured
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#a8a8a0', fontFamily: '"DM Mono", monospace', wordBreak: 'break-all' }}>
                      {launchForm.sshKey?.substring(0, 80)}...
                    </Typography>
                  </Box>
                ) : (
                  <TextField
                    fullWidth
                    label="SSH Private Key"
                    multiline
                    rows={6}
                    value={launchForm.sshKey}
                    onChange={(e) => setLaunchForm(prev => ({ ...prev, sshKey: e.target.value }))}
                    placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...&#10;-----END OPENSSH PRIVATE KEY-----"
                    helperText="Paste your SSH private key here. This will be used to access the instance."
                    sx={{ mt: 1 }}
                  />
                )}
                
                <TextField
                  fullWidth
                  label="SSH Key Name (Optional)"
                  value={launchForm.sshKeyName}
                  onChange={(e) => setLaunchForm(prev => ({ ...prev, sshKeyName: e.target.value }))}
                  placeholder="my-ssh-key"
                  helperText="Optional: Name for this SSH key (default: dio-manual-key)"
                  sx={{ mt: 2 }}
                />
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 2, pt: 1 }}>
          <Button
            onClick={() => {
              setLaunchDialogOpen(false);
              setLaunchForm({ instanceType: '', region: '', sshKeyName: '', sshKey: '' });
              setError('');
              setMessage('');
            }}
            sx={{ textTransform: 'none' }}
          >
            Cancel
          </Button>
          <Button
            onClick={handleLaunchInstance}
            variant="contained"
            disabled={launchLoading || !launchForm.instanceType || !launchForm.region || !launchForm.sshKey?.trim() || instanceTypes.length === 0}
            sx={{ textTransform: 'none' }}
          >
            {launchLoading ? 'Launching...' : 'Launch Instance'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Instance Orchestration Dialog */}
      <InstanceOrchestration
        open={orchestrationDialogOpen}
        onClose={() => {
          setOrchestrationDialogOpen(false);
          setOrchestrationId(null);
          setOrchestrationStatus(null);
          setLaunchingScreen({ active: false, provider: null, phase: 'launching', ip: null, instanceName: null, sshUser: 'ubuntu' });
        }}
        orchestrationId={orchestrationId}
        onStatusUpdate={(data) => {
          if (data.ip_address) {
            setLaunchingScreen((prev) => prev.active ? { ...prev, phase: 'ready', ip: data.ip_address } : prev);
          } else if (data.status === 'waiting_ip' || data.status === 'setting_up') {
            setLaunchingScreen((prev) => prev.active ? { ...prev, phase: 'waiting_ip' } : prev);
          }
        }}
      />

      {/* Scaleway Launch Modal */}
      <Dialog
        open={scwLaunchOpen}
        onClose={() => {
          setScwLaunchOpen(false);
          resetScwLaunchState();
        }}
        maxWidth="sm"
        fullWidth
        PaperProps={{ sx: { borderRadius: 2 } }}
      >
        <DialogTitle sx={{ fontWeight: 600, pb: 1 }}>
          Launch Scaleway Instance
        </DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {scwLaunchPreset && scwLaunchConfig && (
            <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, p: 1.5, mb: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {scwLaunchConfig.name || getScwCommercialType(scwLaunchConfig)}
              </Typography>
              {scwLaunchConfig.price && (
                <Typography variant="body2" color="text.secondary">
                  {formatEuroPrice(scwLaunchConfig.price)} {scwLaunchConfig.raw?.gpu_name ? `• ${scwLaunchConfig.raw.gpu_name}` : ''}
                </Typography>
              )}
            </Box>
          )}
          <FormControl fullWidth size="small">
            <InputLabel>Region</InputLabel>
            <Select
              label="Region"
              value={scwLaunchForm.region}
              onChange={(e) => {
                const newRegion = e.target.value;
                setScwLaunchForm((prev) => ({
                  ...prev,
                  region: newRegion,
                  commercialType: scwLaunchPreset ? prev.commercialType : ''
                }));
                if (!scwLaunchPreset) {
                  loadScwModalConfigs(newRegion, '');
                }
              }}
            >
              {scwRegions.map((r) => (
                <MenuItem key={r} value={r}>{r}</MenuItem>
              ))}
            </Select>
          </FormControl>
          {!scwLaunchPreset && (
          <FormControl fullWidth size="small" disabled={!scwLaunchForm.region || scwModalConfigs.length === 0}>
            <InputLabel>GPU Configuration</InputLabel>
            <Select
              label="GPU Configuration"
              value={scwLaunchForm.commercialType}
              onChange={(e) => {
                const selectedCfg = scwModalConfigs.find(cfg => getScwCommercialType(cfg) === e.target.value);
                if (selectedCfg) {
                  setScwLaunchConfig({ ...selectedCfg, commercialType: getScwCommercialType(selectedCfg) });
                }
                const isH100 = e.target.value?.toLowerCase().includes('h100');
                setScwLaunchForm((prev) => ({
                  ...prev,
                  commercialType: e.target.value,
                  // Auto-set sbs_volume for H100 instances if not already set
                  rootVolumeType: isH100 ? (prev.rootVolumeType || 'sbs_volume') : prev.rootVolumeType,
                }));
              }}
              renderValue={(value) => {
                const cfg = scwModalConfigs.find((item) => getScwCommercialType(item) === value);
                if (!cfg) return value || 'Select GPU configuration';
                const label = cfg.name || getScwCommercialType(cfg);
                const spec = [
                  cfg.gpu ? `${cfg.gpu} GPU` : null,
                  cfg.raw?.gpu_name || cfg.raw?.gpu_model || null,
                  cfg.vcpus ? `${cfg.vcpus} vCPU` : null
                ].filter(Boolean).join(' • ');
                return `${label}${spec ? ` — ${spec}` : ''}`;
              }}
              MenuProps={{
                PaperProps: {
                  sx: {
                    maxHeight: 420,
                    '& .MuiMenuItem-root': { alignItems: 'flex-start' }
                  }
                }
              }}
            >
              {scwModalConfigs.map((cfg) => {
                const value = getScwCommercialType(cfg);
                const gpuName = cfg.raw?.gpu_name || cfg.raw?.gpu_model;
                const spec = [
                  cfg.gpu ? `${cfg.gpu} GPU${cfg.gpu > 1 ? 's' : ''}` : null,
                  cfg.vcpus ? `${cfg.vcpus} vCPU` : null,
                  cfg.ram_bytes ? `${formatGiB(cfg.ram_bytes)} RAM` : null
                ].filter(Boolean).join(' • ');
                return (
                  <MenuItem key={value} value={value}>
                    <Box>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {cfg.name || value}
                      </Typography>
                      {gpuName && (
                        <Typography variant="caption" color="text.secondary">
                          {gpuName}
                        </Typography>
                      )}
                      {spec && (
                        <Typography variant="caption" color="text.secondary">
                          {spec}
                        </Typography>
                      )}
                      {cfg.hourly_price && (
                        <Typography variant="caption" color="primary">
                          {formatEuroPrice(cfg.hourly_price)}
                        </Typography>
                      )}
                    </Box>
                  </MenuItem>
                );
              })}
            </Select>
            {(!scwLaunchForm.region || scwModalConfigs.length === 0) && (
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                Select a region to load available GPU types.
              </Typography>
            )}
          </FormControl>
          )}
          {scwModalLoading && !scwLaunchPreset && (
            <Typography variant="caption" color="text.secondary">
              Loading configurations for {scwLaunchForm.region}...
            </Typography>
          )}
          {envSSHKey ? (
            <Box sx={{ p: 2, borderRadius: '8px', border: '1px solid #3d3d3a', backgroundColor: 'rgba(129, 140, 248, 0.06)' }}>
              <Typography variant="body2" sx={{ color: '#34d399', fontWeight: 600, mb: 0.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                <VpnKeyIcon sx={{ fontSize: 16 }} /> SSH Key Auto-configured
              </Typography>
              <Typography variant="caption" sx={{ color: '#a8a8a0', fontFamily: '"DM Mono", monospace', wordBreak: 'break-all' }}>
                {scwLaunchForm.publicKey?.substring(0, 80)}...
              </Typography>
            </Box>
          ) : (
            <TextField
              label="SSH Public Key"
              placeholder="ssh-ed25519 AAAA... or ssh-rsa AAAA..."
              multiline
              minRows={3}
              value={scwLaunchForm.publicKey}
              onChange={(e) => setScwLaunchForm((prev) => ({ ...prev, publicKey: e.target.value }))}
            />
          )}
          <TextField
            label="SSH Key Name (optional)"
            placeholder="my-key-name"
            value={scwLaunchForm.sshKeyName}
            onChange={(e) => setScwLaunchForm((prev) => ({ ...prev, sshKeyName: e.target.value }))}
          />
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Root Volume Size (GB)"
              type="number"
              placeholder="20"
              value={scwLaunchForm.rootVolumeSize || ''}
              onChange={(e) => {
                const value = e.target.value === '' ? null : parseInt(e.target.value, 10);
                setScwLaunchForm((prev) => ({ ...prev, rootVolumeSize: value }));
              }}
              helperText={scwLaunchForm.rootVolumeSize ? `${scwLaunchForm.rootVolumeSize} GB` : 'Leave empty for default (20GB)'}
              inputProps={{ min: 1, step: 1 }}
              sx={{ flex: 1 }}
            />
            <FormControl sx={{ flex: 1 }} size="small">
              <InputLabel>Volume Type</InputLabel>
              <Select
                label="Volume Type"
                value={scwLaunchForm.rootVolumeType || ''}
                onChange={(e) => setScwLaunchForm((prev) => ({ ...prev, rootVolumeType: e.target.value || null }))}
                disabled={scwLaunchForm.commercialType?.toLowerCase().includes('h100')}
              >
                <MenuItem value="">Default (auto-select)</MenuItem>
                <MenuItem value="sbs_volume">SBS Volume (Block Storage)</MenuItem>
                <MenuItem value="l_ssd" disabled={scwLaunchForm.commercialType?.toLowerCase().includes('h100')}>
                  Local SSD {scwLaunchForm.commercialType?.toLowerCase().includes('h100') && '(Not supported for H100)'}
                </MenuItem>
              </Select>
            </FormControl>
          </Box>
          {scwLaunchForm.commercialType?.toLowerCase().includes('h100') && (
            <Alert severity="info" sx={{ mt: -1 }}>
              H100 instances require SBS Volume (block storage). Local SSD is not supported.
            </Alert>
          )}
        </DialogContent>
                <DialogActions sx={{ p: 2, pt: 1 }}>
                  <Button onClick={() => {
                    setScwLaunchOpen(false);
                    resetScwLaunchState();
                  }} sx={{ textTransform: 'none' }}>Cancel</Button>
                  <Button
                    variant="contained"
                    disabled={
                      scwLaunchLoading ||
                      !scwLaunchForm.region ||
                      !scwLaunchForm.publicKey?.trim() ||
                      !scwLaunchForm.commercialType
                    }
            onClick={async () => {
              const launchRegion = scwLaunchForm.region;
              const launchCommercialType = scwLaunchForm.commercialType;
              const launchPublicKey = scwLaunchForm.publicKey.trim();
              const launchKeyName = scwLaunchForm.sshKeyName.trim() || null;
              try {
                setScwLaunchLoading(true);
                setError('');
                setMessage('');
                const parsed = getScalewayCredentials();
                if (!parsed) {
                  setError('Scaleway credentials not found. Please integrate first.');
                  setScwLaunchLoading(false);
                  return;
                }
                const secretKey = parsed.secretKey;
                const projectId = parsed.projectId;
                if (!secretKey || !projectId) {
                  setError('Scaleway credentials incomplete. Please re-integrate.');
                  setScwLaunchLoading(false);
                  return;
                }
                const res = await apiService.launchScalewayInstance({
                  zone: launchRegion,
                  secretKey,
                  projectId,
                  commercialType: launchCommercialType,
                  publicKey: launchPublicKey,
                  sshKeyName: launchKeyName,
                  rootVolumeSize: scwLaunchForm.rootVolumeSize ? scwLaunchForm.rootVolumeSize * 1_000_000_000 : null, // Convert GB to bytes
                  rootVolumeType: scwLaunchForm.rootVolumeType || null,
                });
                const serverId = res.id || scwLaunchConfig?.name || launchCommercialType;
                setMessage(`Launch requested: ${serverId} in ${res.zone}`);
                // Track launched instance in localStorage for Running Instances page
                try {
                  const tracked = JSON.parse(localStorage.getItem('runara_launched_instances') || '[]');
                  tracked.push({
                    id: res.id,
                    zone: res.zone || launchRegion,
                    name: res.name || `scw-${launchCommercialType}`,
                    commercial_type: launchCommercialType,
                    ip: res.ip || null,
                    launched_at: new Date().toISOString(),
                  });
                  localStorage.setItem('runara_launched_instances', JSON.stringify(tracked));
                } catch (err) {
                  console.warn('Failed to track launched instance:', err);
                }
                // Close modal and reset state before async operations
                setScwLaunchOpen(false);
                resetScwLaunchState();
                setScwLaunchLoading(false);
                // Open progress dialog
                setScwProgress({
                  open: true,
                  serverId,
                  zone: launchRegion,
                  status: res.status || 'launching',
                  ip: res.ip || null,
                  stateDetail: res.state_detail || null,
                  refreshedInstances: false,
                  startTime: Date.now(),
                });
                // Activate full-screen loading — if IP already available, skip ahead
                if (res.ip) {
                  // IP available immediately — show ready and redirect
                  setLaunchingScreen({
                    active: true,
                    provider: 'scaleway',
                    phase: 'ready',
                    ip: res.ip,
                    instanceName: serverId,
                    sshUser: 'root',
                  });
                  setTimeout(() => {
                    setScwProgress((prev) => ({ ...prev, open: false }));
                    setLaunchingScreen({ active: false, provider: null, phase: 'launching', ip: null, instanceName: null, sshUser: 'ubuntu' });
                    navigate('/profiling', {
                      state: {
                        openRunWorkload: true,
                        instanceData: {
                          ipAddress: res.ip,
                          sshUser: 'root',
                          provider: 'scaleway',
                        },
                      },
                    });
                  }, 2000);
                } else {
                  setLaunchingScreen({
                    active: true,
                    provider: 'scaleway',
                    phase: 'launching',
                    ip: null,
                    instanceName: serverId,
                    sshUser: 'root',
                  });
                }
                // Refresh instances asynchronously (don't wait)
                fetchScalewayInstances(launchRegion).catch(err => {
                  console.warn('Failed to refresh instances after launch:', err);
                });
              } catch (e) {
                console.error('Scaleway launch error', e);
                const errorMsg = e?.response?.data?.detail || e.message || 'Failed to launch Scaleway instance';
                setError(errorMsg);
                // Still close modal and reset loading state even on error
                setScwLaunchOpen(false);
                resetScwLaunchState();
                setScwLaunchLoading(false);
              }
            }}
            sx={{ textTransform: 'none' }}
          >
            {scwLaunchLoading ? 'Launching...' : 'Launch Instance'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Nebius Delete Confirmation */}
      <Dialog
        open={nebiusDeleteDialog.open}
        onClose={() => !nebiusDeleteLoading && setNebiusDeleteDialog({ open: false, instance: null })}
      >
        <DialogTitle sx={{ fontWeight: 600 }}>Delete Nebius Instance</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body1">
            Are you sure you want to delete{' '}
            {`"${nebiusDeleteDialog.instance?.name || nebiusDeleteDialog.instance?.id || 'this instance'}"?`}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            This action will terminate the VM in Nebius. It cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button
            onClick={() => !nebiusDeleteLoading && setNebiusDeleteDialog({ open: false, instance: null })}
            disabled={nebiusDeleteLoading}
          >
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDeleteNebiusInstance}
            disabled={nebiusDeleteLoading}
          >
            {nebiusDeleteLoading ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Scaleway Delete Confirmation */}
      <Dialog
        open={scwDeleteDialog.open}
        onClose={() => !scwDeleteLoading && setScwDeleteDialog({ open: false, instance: null })}
        maxWidth="xs"
        fullWidth
        PaperProps={{ sx: { borderRadius: 2 } }}
      >
        <DialogTitle sx={{ fontWeight: 600 }}>Delete Scaleway Instance</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1 }}>
            Are you sure you want to delete
            {` "${scwDeleteDialog.instance?.displayName || scwDeleteDialog.instance?.name || scwDeleteDialog.instance?.id || 'this instance'}"?`}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            This action cannot be undone and the server will be terminated in Scaleway.
          </Typography>
        </DialogContent>
        <DialogActions sx={{ p: 2, pt: 1 }}>
          <Button
            onClick={() => !scwDeleteLoading && setScwDeleteDialog({ open: false, instance: null })}
            sx={{ textTransform: 'none' }}
            disabled={scwDeleteLoading}
          >
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDeleteScwInstance}
            disabled={scwDeleteLoading}
            sx={{ textTransform: 'none' }}
          >
            {scwDeleteLoading ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Scaleway Polling Progress */}
      <Dialog
        open={scwProgress.open}
        onClose={() => setScwProgress((prev) => ({ ...prev, open: false }))}
        maxWidth="sm"
        fullWidth
        PaperProps={{ sx: { borderRadius: 2 } }}
      >
        <DialogTitle sx={{ fontWeight: 600, pb: 1 }}>
          Instance Orchestration (Scaleway)
        </DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            Server: {scwProgress.serverId} — Zone: {scwProgress.zone}
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Typography variant="body2">
              Status: {scwProgress.status || 'pending'} {scwProgress.stateDetail ? `(${scwProgress.stateDetail})` : ''}
            </Typography>
            <Typography variant="body2">IP: {scwProgress.ip || 'waiting...'}</Typography>
            <Box sx={{ mt: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>Overall Progress</Typography>
              <Stack spacing={1}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip size="small" color="success" label="●" sx={{ width: 10, height: 10 }} />
                  <Typography variant="body2">Launching Instance</Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip
                    size="small"
                    color={scwProgress.ip ? 'success' : 'warning'}
                    label="●"
                    sx={{ width: 10, height: 10 }}
                  />
                  <Typography variant="body2">
                    Waiting for IP Address {scwProgress.ip ? '(done)' : '(in progress)'}
                  </Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip
                    size="small"
                    color={
                      scwProgress.status && scwProgress.status.toLowerCase() === 'running' && scwProgress.ip
                        ? 'success'
                        : 'warning'
                    }
                    label="●"
                    sx={{ width: 10, height: 10 }}
                  />
                  <Typography variant="body2">
                    Ready {scwProgress.status && scwProgress.status.toLowerCase() === 'running' && scwProgress.ip ? '(done)' : '(waiting)'}
                  </Typography>
                </Stack>
              </Stack>
            </Box>
            <Typography variant="body2" color="text.secondary">
              This will refresh until the server reports running and has an IP.
            </Typography>
            {scwProgress.ip && scwProgress.status && scwProgress.status.toLowerCase() === 'running' && (
              <Alert severity="success" sx={{ mt: 2 }}>
                Instance is ready! Redirecting to Run Workload...
              </Alert>
            )}
          </Box>
        </DialogContent>
        <DialogActions sx={{ p: 2, pt: 1 }}>
          <Button onClick={() => setScwProgress((prev) => ({ ...prev, open: false }))} sx={{ textTransform: 'none' }}>
            Close
          </Button>
          {scwProgress.ip && scwProgress.status && scwProgress.status.toLowerCase() === 'running' && (
            <Button
              variant="contained"
              onClick={() => {
                setScwProgress((prev) => ({ ...prev, open: false }));
                navigate('/profiling', {
                  state: {
                    openRunWorkload: true,
                    instanceData: {
                      ipAddress: scwProgress.ip,
                      sshUser: 'root',
                      provider: 'scaleway',
                    },
                  },
                });
              }}
              sx={{ textTransform: 'none' }}
            >
              Go to Run Workload
            </Button>
          )}
        </DialogActions>
      </Dialog>

      {/* Nebius Polling Progress */}
      <Dialog
        open={nebiusProgress.open}
        onClose={() => setNebiusProgress((prev) => ({ ...prev, open: false }))}
        maxWidth="sm"
        fullWidth
        PaperProps={{ sx: { borderRadius: 2 } }}
      >
        <DialogTitle sx={{ fontWeight: 600, pb: 1 }}>
          Instance Launching (Nebius)
        </DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            Instance: {nebiusProgress.instanceName}
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Typography variant="body2">
              Status: {nebiusProgress.status || 'launching'}
            </Typography>
            <Typography variant="body2">IP: {nebiusProgress.ip || 'waiting...'}</Typography>
            <Box sx={{ mt: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>Overall Progress</Typography>
              <Stack spacing={1}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip size="small" color="success" label="●" sx={{ width: 10, height: 10 }} />
                  <Typography variant="body2">Launch Requested</Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip
                    size="small"
                    color={nebiusProgress.status === 'running' || nebiusProgress.ip ? 'success' : 'warning'}
                    label="●"
                    sx={{ width: 10, height: 10 }}
                  />
                  <Typography variant="body2">
                    Provisioning {nebiusProgress.status === 'running' || nebiusProgress.ip ? '(done)' : '(in progress)'}
                  </Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip
                    size="small"
                    color={nebiusProgress.ip ? 'success' : 'warning'}
                    label="●"
                    sx={{ width: 10, height: 10 }}
                  />
                  <Typography variant="body2">
                    Waiting for IP Address {nebiusProgress.ip ? '(done)' : '(in progress)'}
                  </Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip
                    size="small"
                    color={nebiusProgress.ip && nebiusProgress.status === 'running' ? 'success' : 'warning'}
                    label="●"
                    sx={{ width: 10, height: 10 }}
                  />
                  <Typography variant="body2">
                    Ready {nebiusProgress.ip && nebiusProgress.status === 'running' ? '(done)' : '(waiting)'}
                  </Typography>
                </Stack>
              </Stack>
            </Box>
            {!nebiusProgress.ip && (
              <Box sx={{ mt: 1 }}>
                <CircularProgress size={20} sx={{ mr: 1 }} />
                <Typography variant="body2" component="span" color="text.secondary">
                  Polling for instance status...
                </Typography>
              </Box>
            )}
            {nebiusProgress.ip && nebiusProgress.status === 'running' && (
              <Alert severity="success" sx={{ mt: 2 }}>
                Instance is ready! Redirecting to Run Workload...
              </Alert>
            )}
          </Box>
        </DialogContent>
        <DialogActions sx={{ p: 2, pt: 1 }}>
          <Button onClick={() => setNebiusProgress((prev) => ({ ...prev, open: false }))} sx={{ textTransform: 'none' }}>
            Close
          </Button>
          {nebiusProgress.ip && nebiusProgress.status === 'running' && (
            <Button
              variant="contained"
              onClick={() => {
                setNebiusProgress((prev) => ({ ...prev, open: false }));
                navigate('/profiling', {
                  state: {
                    openRunWorkload: true,
                    instanceData: {
                      ipAddress: nebiusProgress.ip,
                      sshUser: 'ubuntu',
                      provider: 'nebius',
                    },
                  },
                });
              }}
              sx={{ textTransform: 'none' }}
            >
              Go to Run Workload
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </>
  );
}
  const parseNebiusPresetResponse = (resp) => {
    if (Array.isArray(resp)) {
      return { presets: resp, quota: null, project_id: null };
    }
    if (resp && typeof resp === 'object') {
      return {
        presets: Array.isArray(resp.presets) ? resp.presets : [],
        quota: resp.quota || null,
        project_id: resp.project_id || null,
      };
    }
    return { presets: [], quota: null, project_id: null };
  };
