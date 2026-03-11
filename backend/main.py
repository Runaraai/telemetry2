"""
Omniference - AI Performance Analysis Platform
Clean main.py that uses separate services for better organization.
"""

import os
import json
import logging
import re
import yaml
import tempfile
import uuid
import shutil
import textwrap
import subprocess
import asyncio
import time
import socket
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

# FastAPI imports
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Response, Body, BackgroundTasks, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# OpenAI for LLM recommendations
import openai
from openai import RateLimitError
from dotenv import load_dotenv

# Load environment variables BEFORE importing telemetry modules
# (telemetry.db reads config at import time)
load_dotenv()

# Real-time monitoring removed - not needed for interactive analysis
from telemetry.routes import (
    auth_router,
    credentials_router,
    deployments_router,
    health_router,
    instance_orchestration_router,
    metrics_router,
    profiling_router,
    provisioning_router,
    remote_write_router,
    runs_router,
    scaleway_router,
    nebius_router,
    sm_profiling_router,
    websocket_router,
    ai_insights_router,
)
from routes.nebius import router as nebius_instance_router
from telemetry.startup import init_telemetry

# openai.api_key = os.getenv("OPENAI_API_KEY")
# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = "qwen/qwq-32b"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Lambda Cloud API configuration (updated domain per latest docs)
LAMBDA_API_BASE_URL = "https://cloud.lambda.ai/api/v1"
LAMBDA_API_KEY = os.getenv("LAMBDA_API_KEY")

# Number word mapping for numeric conversion
NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20
}

# Environment & Global Setup
WORKLOAD_DIR = os.getenv(
    "WORKLOAD_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data", "slos")
)
DECODER_DIR = os.getenv(
    "DECODER_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data", "decoder_level_dag")
)

# Instance and benchmark management globals
INSTANCE_FILE = os.path.join(os.path.dirname(__file__), "instances.json")
ACTIVE_TESTS: Dict[str, Dict] = {}
executor = ThreadPoolExecutor(max_workers=8)

# OpenTofu configuration
TOFU_WORK_DIR = os.path.join(os.path.dirname(__file__), "tofu_workspaces")
TOFU_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "tofu_configs")
os.makedirs(TOFU_WORK_DIR, exist_ok=True)
os.makedirs(TOFU_CONFIG_DIR, exist_ok=True)

# Default Lambda Cloud instance configuration
DEFAULT_PEM_FILE = os.path.expanduser("../madhur.pem")
DEFAULT_IP = "170.9.235.16"
DEFAULT_USERNAME = "ubuntu"

# ── Structured Logging ───────────────────────────────────────────────────────
# Log level convention used across this codebase:
#   DEBUG   - verbose internal state (disabled in production)
#   INFO    - normal lifecycle events (task start, task end, metric counts)
#   WARNING - recoverable unexpected conditions
#   ERROR   - failed operations that need attention
#
# Message prefix convention:
#   [USER]  - actions initiated by a user (visible in activity log)
#   [SYS]   - internal system events (infra, migrations, background jobs)
#   [METRIC] - telemetry/data ingestion events
#   [SSH]   - SSH / remote execution events
#   [DEPLOY] - deployment pipeline events
#   [BENCH] - benchmarking / profiling events

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    datefmt=_LOG_DATE_FMT,
)
# Silence noisy third-party loggers
for _noisy in ("paramiko", "httpx", "httpcore", "urllib3", "multipart"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Safe LLM call with retries and exponential backoff (using OpenRouter) ---
import time
import httpx

def safe_openai_call(model, messages, max_tokens=None, temperature=0, retries=5, backoff=1.5):
    """
    Make LLM API calls using OpenRouter instead of OpenAI.
    Compatible with the existing function signature.
    """
    # Use OpenRouter model if model parameter doesn't override
    actual_model = OPENROUTER_MODEL if model in ["gpt-4", "gpt-3.5-turbo", "gpt-4o"] else model
    
    for attempt in range(retries):
        try:
            # Call OpenRouter API
            response = httpx.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": actual_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=60.0
            )
            response.raise_for_status()
            
            # Parse response and return in OpenAI-compatible format
            data = response.json()
            
            # Create a simple object that mimics OpenAI's response structure
            class Message:
                def __init__(self, content):
                    self.content = content
            
            class Choice:
                def __init__(self, message_content):
                    self.message = Message(message_content)
            
            class Response:
                def __init__(self, choices):
                    self.choices = choices
            
            return Response([Choice(data["choices"][0]["message"]["content"])])
            
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            if attempt == retries - 1:
                raise Exception(f"OpenRouter API call failed: {str(e)}")
            wait = backoff ** attempt
            print(f"[Retrying OpenRouter] Attempt {attempt+1}, sleeping for {wait:.2f}s due to error: {e}")
            time.sleep(wait)


# --- Helper Functions ---
def sanitize_yaml_string(yaml_string: str) -> str:
    """Removes Markdown code fences from a string to make it valid YAML."""
    if not isinstance(yaml_string, str):
        return ""
    if yaml_string.startswith("```yaml"):
        yaml_string = yaml_string[7:]
    if yaml_string.startswith("```"):
        yaml_string = yaml_string[3:]
    if yaml_string.endswith("```"):
        yaml_string = yaml_string[:-3]
    return yaml_string.strip()

def _clean_and_convert_to_numeric(value: Any) -> Any:
    """
    Parses a string to find the first number or number word, understands units like T, G, M,
    and returns a clean numeric value (float or int).
    """
    if not isinstance(value, str):
        return value

    value_lower = value.lower().strip()

    # Handle word-based numbers (e.g., "Four Tensor Cores per SM")
    for word, num in NUM_WORDS.items():
        if value_lower.startswith(word):
            return num

    # Handle cases like "312/624" by taking the first number
    if '/' in value:
        value = value.split('/')[0].strip()
        value_lower = value.lower().strip()

    match = re.search(r'[\d\.]+', value)
    if not match:
        return value

    num_str = match.group(0)
    try:
        num = float(num_str)
    except ValueError:
        return value

    if 'tflops' in value_lower or 'tops' in value_lower or 'tb/s' in value_lower or 'tbps' in value_lower:
        num *= 1e12
    elif 'gflops' in value_lower or 'gops' in value_lower or 'gb/s' in value_lower or 'gbps' in value_lower or 'ghz' in value_lower:
        num *= 1e9
    elif 'mflops' in value_lower or 'mops' in value_lower or 'mb/s' in value_lower or 'mbps' in value_lower or 'mhz' in value_lower:
        num *= 1e6

    return int(num) if num.is_integer() else num

def truncate_context(context: str, max_tokens: int = 6000) -> str:
    words = context.split()
    return " ".join(words[:max_tokens])

# --- NEW: Decoder transformation function ---
def transform_decoder_to_dag(decoder_data):
    """Transform decoder JSON to DAG format with proper operator visualization"""
    
    # Use the ops array as nodes
    if 'ops' in decoder_data:
        raw_nodes = decoder_data['ops']
    elif 'layers' in decoder_data:
        raw_nodes = decoder_data['layers']
    else:
        return {"nodes": [], "edges": []}
    
    # Transform nodes to match expected format
    nodes = []
    for op in raw_nodes:
        node = {
            "id": op['id'],
            "name": op.get('pretty_name', op.get('name', op['id'])),
            "displayName": op.get('pretty_name', op.get('name', op['id'])),
            "type": op.get('category', 'other'),  # Use category as type for coloring
            "ops": op.get('ops', 0),
            "bytes": op.get('bytes', {}),
            "dtype": op.get('dtype', 'torch.float32'),
            # Add extra metadata for detailed view
            "category": op.get('category', 'other'),
            "timing_us": op.get('timing_us', {}),
            "shapes": op.get('shapes', [])
        }
        nodes.append(node)
    
    # Create edges based on execution order and data dependencies
    edges = []
    
    # Sort nodes by execution time to understand flow
    sorted_nodes = sorted(raw_nodes, key=lambda x: x.get('timing_us', {}).get('start_us', 0))
    
    # Create edges between operations that likely have data dependencies
    for i, current_op in enumerate(sorted_nodes):
        current_category = current_op.get('category', 'other')
        current_shapes = current_op.get('shapes', [])
        
        # Look for next operations that might use this output
        for j in range(i + 1, min(i + 5, len(sorted_nodes))):  # Look ahead max 5 operations
            next_op = sorted_nodes[j]
            next_shapes = next_op.get('shapes', [])
            
            # Create edge if shapes suggest data flow or if it's a logical sequence
            should_connect = False
            
            # Connect major compute operations in sequence
            if current_category in ['gemm', 'attention.sdp', 'norm', 'activation'] and \
               next_op.get('category') in ['gemm', 'attention.sdp', 'norm', 'activation', 'layout']:
                should_connect = True
            
            # Connect layout operations to compute operations
            elif current_category == 'layout' and next_op.get('category') in ['gemm', 'attention.sdp']:
                should_connect = True
            
            # Connect if output/input shapes match
            elif current_shapes and next_shapes:
                for curr_shape in current_shapes:
                    for next_shape in next_shapes:
                        if curr_shape == next_shape and len(curr_shape) > 1:  # Non-scalar matching shapes
                            should_connect = True
                            break
                    if should_connect:
                        break
            
            if should_connect:
                edge = {
                    "source": current_op['id'],
                    "target": next_op['id'],
                    "bytes": current_op.get('bytes', {}).get('HBM', 0)
                }
                edges.append(edge)
                break  # Only connect to the first matching operation
    
    # If no edges were created (fallback), create simple sequential edges for main operations
    if not edges:
        main_ops = [op for op in sorted_nodes if op.get('category') in ['gemm', 'attention.sdp', 'norm', 'activation']]
        for i in range(len(main_ops) - 1):
            edge = {
                "source": main_ops[i]['id'],
                "target": main_ops[i + 1]['id'],
                "bytes": main_ops[i].get('bytes', {}).get('HBM', 0)
            }
            edges.append(edge)
    
    return {
        "name": f"{decoder_data.get('model_name', 'Decoder')} - Layer {decoder_data.get('layer_index', 0)}",
        "nodes": nodes,
        "edges": edges
    }

# --- Placeholder functions for broader analysis ---
def enhanced_makespan_seconds(w, h): return (1.0, type('obj', (object,), {'estimated_throughput': 100.0, 'workload_profile': type('obj', (object,), {})(), 'hardware_profile': type('obj', (object,), {})(), 'scheduling_strategy': 'Optimized', 'resource_utilization': {'gpu': 0.9}, 'optimization_recommendations': ['Consider HBM memory']})())
def energy_for_run_seconds(p, m, pue): return 5000.0
def hourly_cost_onprem(g, p, pw, pue): return 10.50
def cost_per_token(hc, tph): return 0.0001
def analyze_bottlenecks(w, h, m): return {"compute_bound": 0.8}
def generate_suggestions(b, w, h): return [{"suggestion": "Increase batch size"}]

# === Multi-level visualization/analysis YAML prompt builder ===
def build_multilevel_prompt(hardware_name: str, context_text: str, source_urls: str = "") -> str:
    context_text = context_text or ""

    template = """You are a world-class expert in AI accelerators and technical data extraction.
Goal: Produce a single, strict YAML document that adapts to ANY hardware/platform type 
(GPU, TPU, CPU, WSE, LPU/ASIC, platform/pod). 
The schema is universal — you must adjust `meta.kind`, `compute.unit_kind`, 
and the `hierarchy` section based on device type. 
Only output levels that apply to the given hardware.

--- INPUTS ---
HARDWARE NAME:
{{HARDWARE_NAME}}

OPTIONAL CONTEXT (datasheet/manual/spec table/press brief):
<<<CONTEXT_START
{{CONTEXT_TEXT}}
CONTEXT_END>>>

OPTIONAL SOURCE URLS (one per line):
{{SOURCE_URLS}}

--- GLOBAL RULES ---
1) Output STRICT YAML only (no prose, no comments, no markdown fences).
2) Base units: Hz, bytes, bytes_per_second, watts. Use numbers only (no unit strings).
3) Omit any unknown field; do not emit null/unknown placeholders.
4) Use discriminators:
   - meta.kind: one of [gpu, tpu, cpu, lpu, wse, accelerator, platform]
   - level: one of [device, node, rack, pod]
5) Adapt `compute.unit_kind` based on hardware type:
   - GPU → SM (NVIDIA), CU (AMD)
   - TPU → TensorCore (with MXU/vector/scalar subunits)
   - WSE → WSE_PE
   - LPU/ASIC → tile or matrix_unit
   - CPU → core
6) Hierarchies differ by device type:
   - GPU: specify gpcs, tpcs_per_gpc, sms_per_tpc (explicitly list SMs/TPC, TPCs/GPC, GPCs)
   - TPU: specify tensorcores, mxus_per_tensorcore, vector_units, scalar_units
   - CPU: specify sockets, cores_per_socket, threads_per_core
   - WSE: specify tiles, sram_per_tile_B
   - LPU/ASIC: specify chiplets and cores/tiles
   - Platform/pod: specify pod → racks → nodes → devices
7) Emit only hierarchy fields relevant to the device type.
8) Graphs must be **data-driven**:
   - Device → compute units, caches, memory stacks
   - Node → devices, intra-node fabrics, NICs
   - Rack → nodes, rack switches
   - Pod → racks, pod fabric
   - Do not hardcode examples; enumerate from specs
9) Always use deterministic IDs for graph nodes/edges.
10) Precision support, partitioning, and software stacks must reflect device type.
11) Explicit omission rule: If a level does not apply, omit it entirely (no stubs, nulls, placeholders).

--- OUTPUT STRUCTURE ---
meta:
  name: "<string>"
  vendor: "<string>"
  generation: "<string>"
  kind: "<gpu|tpu|cpu|lpu|wse|accelerator|platform>"
  process_nm: <int>
  form_factor: "<SXM|OAM|PCIe|chassis|blade|custom>"
  tdp_W: <int>

hardware_information:
  gpu_model: "<string>"  # Specific product name and identifier
  architecture: "<string>"  # GPU microarchitecture (e.g., Ada, RDNA, Ampere)
  capabilities: ["<feature1>", "<feature2>", "<feature3>"]  # Supported features and instruction sets
  vram_size_B: <int>  # Total video memory capacity in bytes
  vram_type: "<string>"  # Memory technology (GDDR6, HBM2, etc.)
  driver_version: "<string>"  # Installed driver software version
  installation_date: "<YYYY-MM-DD>"  # Driver installation date
  bios_firmware_versions:
    vbios_version: "<string>"
    firmware_version: "<string>"

levels:
  - level: "device"
    accelerator:
      name: "<string>"
      variant: "<e.g., 80GB, SXM5, v5p>"
    compute:
      unit_kind: "<SM|CU|TensorCore|WSE_PE|core|tile>"
      units: <int>
      subunits_per_unit:
        tensor_cores: <int>
        vector_cores: <int>
        scalar_units: <int>
        mxu: <int>
        simd_width: <int>
      warp_or_wavefront_size: <int>
      max_threads_per_unit: <int>
      clock_hz: <int>
      peak_flops:
        fp8_tflops: <float>
        bf16_tflops: <float>
        fp16_tflops: <float>
        tf32_tflops: <float>
        fp32_tflops: <float>
        int8_tops: <float>

    hierarchy:
      # GPU fields
      gpcs: <int>
      tpcs_per_gpc: <int>
      sms_per_tpc: 2
      # TPU fields
      tensorcores: <int>
      mxus_per_tensorcore: <int>
      vector_units: <int>
      scalar_units: <int>
      # CPU fields
      sockets: <int>
      cores_per_socket: <int>
      threads_per_core: <int>
      # WSE fields
      tiles: <int>
      sram_per_tile_B: <int>
      # LPU/ASIC fields
      chiplets: <int>
      cores_per_chiplet: <int>

    unit_resources:
      regfile_B: <int>
      shared_mem_B: <int>
      l1d_B: <int>
      l1i_B: <int>
      max_warps: <int>
      max_threads: <int>

    memory:
      hbm_capacity_B: <int>
      hbm_stacks: <int>
      memory_bus_bits: <int>
      hbm_bandwidth_Bps: <int>
      l2_size_B: <int>
      onchip_sram_B: <int>

    memory_ctrl:
      controllers: <int>
      bus_bits: <int>

    noc:
      topology: "<mesh|ring|xbar|torus|nvlink_fabric>"
      link_bits: <int>
      per_hop_latency_ns: <float>
      bisection_Bps: <int>

    interconnect:
      on_package:
        type: "<NVLink|IF|ICI|custom>"
        version: "<string>"
        per_link_Bps: <int>
        links: <int>
        aggregate_Bps: <int>
      off_package:
        - type: "<NVSwitch|SwarmX|UBB|PCIe>"
          version: "<string>"
          per_link_Bps: <int>
          links: <int>
          topology: "<fat_tree|mesh|ring>"
          aggregate_Bps: <int>
      pcie:
        version: "<4.0|5.0|6.0>"
        lanes: <int>

    latency_ns:
      l1d: <float>
      l2: <float>
      hbm: <float>

    precision_support: [fp8, bf16, fp16, tf32, fp32, int8, int4]

    partitioning:
      mps: <bool>
      mig_slices: [<int>, <int>]

    software:
      stacks: ["CUDA","ROCm","XLA","Neuron","Poplar","custom"]

    diagram:
      grid: { gpc_rows: <int>, gpc_cols: <int> }
      hbm_stack_positions: ["<edge|top|bottom|left|right>"]
      l2_is_central: <bool>

    graph:
      nodes: []
      edges: []

    workload_analysis_notes:
      bandwidth_bound_ops: ["attention","kv_cache","allreduce"]
      scaling_notes: "<brief>"
      recommended_precisions: ["fp8","bf16"]

  - level: "node"
    platform:
      name: "<string>"
      devices: <int>
      intra_node_fabric:
        type: "<NVLink|IF|ICI|SwarmX|custom>"
        aggregate_Bps: <int>
        topology: "<fully_connected|mesh|ring|xbar>"
    host_cpu:
      sockets: <int>
      numa: <int>
    nic:
      count: <int>
      per_nic_bw_Bps: <int>
    board:
      tbp_W: <int>
      cooling: "<air|liquid>"
      dimensions_mm: { w: <int>, h: <int>, l: <int> }
      pcie_switches: <bool>
    diagram:
      grid: { device_rows: <int>, device_cols: <int> }
      fabric_elements: []
    graph:
      nodes: []
      edges: []

  - level: "rack"
    rack:
      nodes: <int>
      power_budget_W: <int>
      cooling: "<air|liquid>"
      rack_fabric:
        type: "<InfiniBand|Ethernet|ICI>"
        per_link_Bps: <int>
        ports_per_node: <int>
        topology: "<fat_tree|dragonfly|torus|mesh>"
    diagram:
      grid: { node_rows: <int>, node_cols: <int> }
    graph:
      nodes: []
      edges: []

  - level: "pod"
    pod:
      racks: <int>
      fabric:
        type: "<InfiniBand|NVLink_Switch_System|ICI|Ethernet>"
        aggregate_Bps: <int>
        topology: "<fat_tree|dragonfly|torus|mesh>"
      total_devices: <int>
      total_hbm_B: <int>
    graph:
      nodes: []
      edges: []

sources:
  - "<url-or-doc-title>"
"""

    # Simple, safe substitutions
    return (
        template
        .replace("{{HARDWARE_NAME}}", hardware_name)
        .replace("{{CONTEXT_TEXT}}", context_text)
        .replace("{{SOURCE_URLS}}", source_urls)
    )

# ============================================================================
# PYDANTIC MODELS FOR API
# ============================================================================

class SimpleAnalysisRequest(BaseModel):
    model: str
    hardware: str
    parameters: Dict[str, Any] = {}

class InteractiveAnalysisRequest(BaseModel):
    model: str
    hardware: str
    
    # ============================================================================
    # MODEL ARCHITECTURE PARAMETERS (Custom Model Configuration)
    # ============================================================================
    custom_params: Optional[int] = None  # Model parameters in billions (1-1000)
    custom_layers: Optional[int] = None  # Number of transformer layers (1-200)
    custom_heads: Optional[int] = None  # Number of attention heads (1-256)
    custom_hidden_size: Optional[int] = None  # Hidden dimension size (512-32768)
    custom_vocab_size: Optional[int] = None  # Vocabulary size (1000-500000)
    
    # ============================================================================
    # HARDWARE SCALING PARAMETERS
    # ============================================================================
    num_gpus: int = 1  # Number of GPUs (1, 2, 3, 4, 5, 6, 7, 8)
    tensor_parallelism: int = 1  # Model sharded across GPUs (1, 2, 4, 8)
    pipeline_parallelism: int = 1  # Layers distributed across GPUs (1-20)
    
    # ============================================================================
    # HARDWARE CONFIGURATION PARAMETERS
    # ============================================================================
    power_limit_watts: int = 700  # Power limit per GPU (350-1000W, 50W increments)
    memory_mode: str = "standard"  # standard, high_bw, ultra_bw, extreme_bw, power_optimized
    tensor_core_mode: str = "balanced"  # conservative, balanced, aggressive, ultra, extreme
    nvlink_topology: str = "ring"  # ring, mesh, hierarchical, adaptive, custom


    
    # ============================================================================
    # WORKLOAD PARAMETERS
    # ============================================================================
    batch_size: int = 1  # Number of concurrent requests (1-256, powers of 2)
    input_length: int = 2048  # Input sequence length (512, 1024, 2048, 4096, 8192, 16384, 32768)
    output_length: int = 256  # Output sequence length (16, 32, 64, 128, 256, 512, 1024, 2048)
    
    # ============================================================================
    # PRECISION & QUANTIZATION PARAMETERS
    # ============================================================================
    precision: str = "fp16"  # FP32, FP16, BF16, FP8, INT8, INT4
    quantization: str = "none"  # none, GPTQ, AWQ, SmoothQuant
    kv_cache_quantization: str = "fp16"  # FP32, FP16, BF16, FP8, INT8
    
    # ============================================================================
    # ATTENTION MECHANISM PARAMETERS
    # ============================================================================
    attention_mechanism: str = "standard"  # standard, flash, paged_attention, multi_query, grouped_query, sliding_window
    
    # ============================================================================
    # SYSTEM CONFIGURATION PARAMETERS
    # ============================================================================
    memory_fraction: float = 0.8  # GPU memory utilization (0.5-0.95)
    target_latency: float = 1.0  # Target latency in seconds (0.1-10.0)
    max_concurrency: int = 100  # Maximum concurrent requests (1-1000)
    
    # ============================================================================
    # OPTIMIZATION PARAMETERS (Boolean toggles)
    # ============================================================================
    flash_attention: bool = False  # Flash Attention 2.0 (~20% speedup)
    cuda_graphs: bool = False  # CUDA Graphs (~10% speedup)
    speculative_decoding: bool = False  # Speculative decoding (~2x speedup)
    
    # ============================================================================
    # LEGACY PARAMETERS (for backward compatibility)
    # ============================================================================
    sequence_length: Optional[int] = None  # Deprecated: use input_length + output_length
    attention_heads: Optional[int] = None  # Deprecated: use custom_heads
    hidden_size: Optional[int] = None  # Deprecated: use custom_hidden_size
    num_layers: Optional[int] = None  # Deprecated: use custom_layers

# Mapper-related response models removed - mapper module not available
# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

app = FastAPI(
    title="Omniference API",
    description="AI Performance Analysis Platform - Clean Architecture",
    version="1.0.0"
)


# CORS origins - can be configured via CORS_ORIGINS environment variable
# Format: comma-separated list, e.g., "https://omniference.com,https://voertx.cloud,http://localhost:3000"
# Special value "*" allows all origins (use with caution in production)
# For hosted websites, allow the production domain and common variations
_cors_origins_env = os.getenv("CORS_ORIGINS", "").strip()
if _cors_origins_env:
    if _cors_origins_env == "*":
        # Allow all origins (development only - not recommended for production)
        allowed_cors_origins = ["*"]
    else:
        allowed_cors_origins = [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()]
else:
    # Default fallback: localhost only. Set CORS_ORIGINS env var for production domains.
    allowed_cors_origins = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    
    # If API_BASE_URL is set, extract domain and add it to allowed origins
    # This ensures the domain used for API calls is always allowed
    api_base_url = os.getenv("API_BASE_URL", "").strip()
    if api_base_url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(api_base_url)
            if parsed.netloc:
                # Add both http and https versions of the domain
                domain = parsed.netloc.split(':')[0]  # Remove port if present
                if domain and domain not in ["localhost", "127.0.0.1"]:
                    allowed_cors_origins.extend([
                        f"https://{domain}",
                        f"http://{domain}",
                        f"https://www.{domain}",
                        f"http://www.{domain}",
                    ])
        except Exception:
            pass  # Ignore parsing errors

# CORS configuration - handle wildcard separately
if allowed_cors_origins == ["*"]:
    # Allow all origins (development only)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # Cannot use credentials with wildcard
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
else:
    # Specific origins with credentials support
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_cors_origins,
        allow_credentials=True,  # Changed to True to allow cookies/auth if needed
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


# ── Global Exception Handler ─────────────────────────────────────────────────
from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = translate_error(str(exc.detail)) if exc.detail else "An unexpected error occurred."
    logger.error("[SYS] HTTP %s on %s: %s", exc.status_code, request.url.path, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail, "raw": str(exc.detail)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    raw = str(exc)
    detail = translate_error(raw)
    logger.error("[SYS] Unhandled error on %s: %s", request.url.path, raw, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": detail, "raw": raw})


# ── User-Friendly Error Translation ──────────────────────────────────────────
# Maps internal error substrings to user-readable messages.
# Checked in order — first match wins.

USER_FRIENDLY_ERRORS: List[Tuple[str, str]] = [
    ("No active deployment found", "Start GPU monitoring before running a benchmark."),
    ("Run not found", "The monitoring session expired. Start a new session."),
    ("docker: command not found", "Docker is not installed on this instance. Run the Setup step first."),
    ("docker: Cannot connect", "Docker daemon is not running. SSH in and run: sudo systemctl start docker"),
    ("Connection refused", "Cannot reach the instance. Check that it's running and the IP address is correct."),
    ("Authentication failed", "SSH authentication failed. Check your SSH key."),
    ("No route to host", "Cannot connect to the instance. Check that the IP address is correct."),
    ("Timeout", "Operation timed out. The instance may be overloaded or unreachable."),
    ("Permission denied", "Permission denied. Check SSH key and sudo configuration."),
    ("CUDA out of memory", "GPU ran out of memory. Try a smaller model or reduce batch size."),
    ("model not found", "Model not found on the instance. Run the Setup step to download it."),
    ("vllm server is not running", "vLLM inference server is not running. Use Deploy Inference to start it."),
    ("No module named", "Python dependency missing on the instance. Run the Setup step first."),
    ("401", "Authentication required. Please log in again."),
    ("403", "Permission denied. You don't have access to this resource."),
    ("404", "Resource not found. It may have been deleted or the ID is wrong."),
]


def translate_error(detail: str) -> str:
    """Translate a raw error detail string to a user-friendly message."""
    for substring, friendly in USER_FRIENDLY_ERRORS:
        if substring.lower() in detail.lower():
            return friendly
    return detail


def _cleanup_old_workflow_logs(max_age_days: int = 7) -> None:
    """Delete workflow log directories older than max_age_days to prevent unbounded growth."""
    logs_root = os.path.join(os.path.dirname(__file__), "logs")
    if not os.path.isdir(logs_root):
        return
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for entry in os.scandir(logs_root):
        if entry.is_dir() and entry.stat().st_mtime < cutoff:
            try:
                shutil.rmtree(entry.path)
                deleted += 1
            except Exception as e:
                logger.warning("Failed to delete old log dir %s: %s", entry.path, e)
    if deleted:
        logger.info("[USER] Cleaned up %d workflow log directories older than %d days", deleted, max_age_days)


@app.on_event("startup")
async def startup_telemetry() -> None:
    await init_telemetry()
    # Start deployment worker
    from telemetry.services.deployment_worker import deployment_worker
    await deployment_worker.start()
    # Clean up old workflow logs (older than 7 days) on startup
    _cleanup_old_workflow_logs()


@app.on_event("shutdown")
async def shutdown_telemetry() -> None:
    # Stop deployment worker
    from telemetry.services.deployment_worker import deployment_worker
    await deployment_worker.stop()


app.include_router(auth_router, prefix="/api/auth")
app.include_router(runs_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(remote_write_router, prefix="/api")
app.include_router(deployments_router, prefix="/api")
app.include_router(provisioning_router, prefix="/api/telemetry")
app.include_router(credentials_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(scaleway_router, prefix="/api")
app.include_router(nebius_router, prefix="/api")
app.include_router(nebius_instance_router)  # New instance management routes
app.include_router(ai_insights_router, prefix="/api")
app.include_router(sm_profiling_router, prefix="/api")
app.include_router(profiling_router, prefix="/api/telemetry")
app.include_router(instance_orchestration_router)
app.include_router(websocket_router)

# ============================================================================
# API ENDPOINTS
# ============================================================================

# Mapper-related helper functions removed - mapper module not available
# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {"message": "Omniference API - AI Performance Analysis Platform"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now()}

@app.get("/test-benchmark")
async def test_benchmark():
    return {"message": "Benchmark endpoint test", "timestamp": datetime.now()}

# Mapper-related endpoints removed - mapper module not available

# ============================================================================
# CROSS-PLATFORM PERFORMANCE METRICS ENDPOINT
# ============================================================================

# CrossPlatformMetricsRequest removed - used mapper module
    model: str
    hardware_list: List[str]
    # Optional overrides
    batch_size: Optional[int] = None
    input_length: Optional[int] = None
    output_length: Optional[int] = None
    precision: Optional[str] = None
    quantization: Optional[str] = None
    attention_mechanism: Optional[str] = None
    tensor_parallelism: Optional[int] = None
    pipeline_parallelism: Optional[int] = None

# /tensor-inventory endpoint removed because hardware_builder is no longer available.

# /analyze endpoint removed - used AnalysisResponse from mapper module
# /simulate endpoint removed because it depended on hardware mapper components.

# Model scanning functions
def _model_name_from_workload(filename: str) -> str:
    return filename.replace("_block_dag.json", "")

def _model_name_from_decoder(filename: str) -> str:
    name = filename
    if name.endswith("_decoder_dag.json"):
        return name.replace("_decoder_dag.json", "")
    if "_layer0_B1_S16" in name:
        name = name.replace("_layer0_B1_S16", "")
    return name.replace(".json", "")

def _scan_models() -> dict:
    models = {}
    if os.path.isdir(WORKLOAD_DIR):
        for f in os.listdir(WORKLOAD_DIR):
            if f.endswith("_block_dag.json"):
                m = _model_name_from_workload(f)
                models.setdefault(m, {})["workload_file"] = f
    if os.path.isdir(DECODER_DIR):
        for f in os.listdir(DECODER_DIR):
            if f.endswith(".json"):
                m = _model_name_from_decoder(f)
                models.setdefault(m, {})["decoder_file"] = f
    return {k: v for k, v in models.items() if v.get("workload_file") or v.get("decoder_file")}

def _find_decoder_path(requested_name: str) -> str:
    # 1) exact filename
    cand = os.path.join(DECODER_DIR, requested_name)
    if os.path.isfile(cand):
        return cand
    
    # 2) *_block_dag.json -> *_decoder_dag.json
    if requested_name.endswith("_block_dag.json"):
        alt = requested_name.replace("_block_dag.json", "_decoder_dag.json")
        cand = os.path.join(DECODER_DIR, alt)
        if os.path.isfile(cand): return cand
    
    # 3) bare model -> *_decoder_dag.json
    if not requested_name.endswith(".json"):
        alt = f"{requested_name}_decoder_dag.json"
        cand = os.path.join(DECODER_DIR, alt)
        if os.path.isfile(cand): return cand
    
    # 4) Try with _layer0_B1_S16.json suffix (based on decoder JSON)
    if not requested_name.endswith(".json"):
        alt = f"{requested_name}_layer0_B1_S16.json"
        cand = os.path.join(DECODER_DIR, alt)
        if os.path.isfile(cand): return cand
    
    # 5) Try to match by model name from the JSON files
    if os.path.isdir(DECODER_DIR):
        for filename in os.listdir(DECODER_DIR):
            if filename.endswith('.json'):
                filepath = os.path.join(DECODER_DIR, filename)
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                        model_name = data.get('model_name', '')
                        # Extract base model name (e.g., "cerebras_cerebras-gpt-2.7b" from "cerebras/Cerebras-GPT-2.7B")
                        if model_name:
                            base_name = model_name.lower().replace('/', '_').replace('-', '')
                            requested_base = requested_name.lower().replace('_', '').replace('-', '')
                            if base_name in requested_base or requested_base in base_name:
                                return filepath
                except:
                    continue
    
    return ""

# ============================================================================
# LAMBDA CLOUD API HELPER FUNCTIONS
# ============================================================================

async def make_lambda_api_request(
    endpoint: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    api_key_override: Optional[str] = None,
    max_retries: int = 2  # Reduced from 3 to 2 to prevent excessive retry time
) -> Dict[str, Any]:
    """Make a request to Lambda Cloud API with retry logic for transient failures."""
    url = f"{LAMBDA_API_BASE_URL}/{endpoint}"
    
    api_key = api_key_override or LAMBDA_API_KEY
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="LAMBDA_API_KEY environment variable is not set"
        )
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    last_error = None
    for attempt in range(max_retries):
        try:
            # Set timeout to 40s per attempt (with 2 retries + 1s backoff = max 81s total, under 90s frontend timeout)
            async with httpx.AsyncClient(timeout=40.0) as client:
                auth = httpx.BasicAuth(api_key, "")
                if method == "GET":
                    response = await client.get(url, headers=headers, auth=auth)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=data, auth=auth)
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers, auth=auth)
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsupported HTTP method: {method}"
                    )
            
            # Check for HTTP errors
            if response.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid Lambda API key. Please check your LAMBDA_API_KEY environment variable."
                )
            elif response.status_code == 403:
                raise HTTPException(
                    status_code=403,
                    detail="Access forbidden. Your API key may not have the required permissions."
                )
            elif response.status_code >= 400:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("error", {}).get("message", response.text)
                except:
                    pass
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Lambda Cloud API error: {error_detail}"
                )
            
            return response.json()
                
        except httpx.TimeoutException as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(f"Lambda API request timeout (attempt {attempt + 1}/{max_retries}), retrying...")
                await asyncio.sleep(1)  # Reduced backoff from exponential to 1 second
                continue
            raise HTTPException(
                status_code=504,
                detail="Request to Lambda Cloud API timed out after retries"
            )
        except httpx.RequestError as e:
            last_error = e
            error_msg = str(e)
            # Check for DNS resolution errors
            is_dns_error = "gaierror" in error_msg.lower() or "name resolution" in error_msg.lower() or "temporary failure" in error_msg.lower()
            
            if attempt < max_retries - 1 and is_dns_error:
                logger.warning(f"Lambda API DNS resolution error (attempt {attempt + 1}/{max_retries}), retrying... Error: {error_msg}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
            elif is_dns_error:
                logger.error(f"Lambda Cloud API DNS resolution error after {max_retries} attempts: {error_msg}")
                raise HTTPException(
                    status_code=503,
                    detail=f"DNS resolution failed when connecting to Lambda Cloud API after {max_retries} attempts. This may be a temporary network issue. Please try again in a few moments. Error: {error_msg}"
                )
            logger.error(f"Lambda Cloud API request error: {error_msg}")
            raise HTTPException(
                status_code=503,
                detail=f"Failed to connect to Lambda Cloud API: {error_msg}"
            )
        except HTTPException:
            raise
        except Exception as e:
            last_error = e
            error_msg = str(e)
            # Check for DNS resolution errors in general exceptions
            is_dns_error = "gaierror" in error_msg.lower() or "name resolution" in error_msg.lower() or "temporary failure" in error_msg.lower()
            
            if attempt < max_retries - 1 and is_dns_error:
                logger.warning(f"Lambda API DNS resolution error (attempt {attempt + 1}/{max_retries}), retrying... Error: {error_msg}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
            elif is_dns_error:
                logger.error(f"Lambda Cloud API DNS resolution error (general exception) after {max_retries} attempts: {error_msg}")
                raise HTTPException(
                    status_code=503,
                    detail=f"DNS resolution failed when connecting to Lambda Cloud API after {max_retries} attempts. This may be a temporary network issue. Please try again in a few moments. Error: {error_msg}"
                )
            logger.error(f"Unexpected error calling Lambda Cloud API: {error_msg}")
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected error: {error_msg}"
            )
    
    # If we get here, all retries failed
    if last_error:
        error_msg = str(last_error)
        raise HTTPException(
            status_code=500,
            detail=f"Lambda Cloud API request failed after {max_retries} attempts: {error_msg}"
        )

# ============================================================================
# REMOTE INSTANCE MANAGEMENT HELPER FUNCTIONS
# ============================================================================

def load_instances() -> Dict[str, Dict]:
    """Load registered GPU instances from JSON file"""
    if not os.path.exists(INSTANCE_FILE):
        return {}
    with open(INSTANCE_FILE, "r") as f:
        return json.load(f)

def save_instances(data: Dict[str, Dict]):
    """Save GPU instances to JSON file"""
    with open(INSTANCE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def run_ssh_command(instance: Dict, command: str, timeout: int = 300) -> str:
    """
    Run a remote SSH command on a GPU instance.
    Based on Lambda Cloud log fetcher logic with security enhancements.
    """
    pem = os.path.expanduser(instance["pem_file"])
    ip = instance["ip"]
    user = instance.get("username", "ubuntu")

    # Safety check - verify PEM file exists
    if not os.path.exists(pem):
        raise RuntimeError(f"PEM file not found: {pem}")
    
    # Set secure permissions (required by SSH)
    # SSH will refuse keys with permissions more permissive than 600 (owner read/write)
    # We use 400 (owner read-only) which is the most restrictive and secure
    try:
        current_mode = os.stat(pem).st_mode & 0o777
        if current_mode != 0o400 and current_mode != 0o600:
            os.chmod(pem, 0o400)  # Read-only for owner
            logger.debug(f"Set PEM file permissions to 400: {pem} (was {oct(current_mode)})")
        else:
            logger.debug(f"PEM file permissions already correct: {pem} ({oct(current_mode)})")
    except Exception as e:
        logger.warning(f"Could not set PEM file permissions: {e}. SSH may fail if permissions are too open.")
        # Continue anyway - might work if permissions are already correct

    # Build SSH command with security options
    ssh_cmd = [
        "ssh", "-i", pem,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{user}@{ip}",
        command
    ]
    
    # Use UTF-8 encoding with error handling for log files that may contain special characters
    result = subprocess.run(
        ssh_cmd, 
        capture_output=True, 
        text=True, 
        timeout=timeout,
        encoding='utf-8',
        errors='replace'  # Replace invalid UTF-8 characters instead of failing
    )
    if result.returncode != 0:
        error_msg = result.stderr.strip() if result.stderr else "Unknown SSH error"
        raise RuntimeError(error_msg)
    
    # Handle case where stdout might be None (shouldn't happen, but defensive)
    if result.stdout is None:
        return ""
    
    return result.stdout.strip()

# Example endpoints
@app.post("/analyze/upload")
async def analyze_workload_upload(
    workload_file: UploadFile = File(...),
    hardware_file: UploadFile = File(...),
    pricing_file: UploadFile = File(...),
    slos_file: UploadFile = File(...)
):
    # Mapper-related endpoint removed - mapper module not available
    raise HTTPException(status_code=503, detail="Mapper module not available. Analysis features are disabled.")

@app.get("data/workloads")
async def get_example_workloads():
    examples_dir = os.path.join(os.path.dirname(__file__), "..", "data", "models")
    workloads = []
    if os.path.exists(examples_dir):
        for file in os.listdir(examples_dir):
            if file.endswith('.json'):
                    workloads.append({"name": file})
    return {"workloads": workloads}

@app.get("/examples/hardware")
async def get_example_hardware(response: Response, category: Optional[str] = None):
    # Add cache-busting headers
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    
    # Map frontend categories to folder names (legacy support)
    folder_map = {
        "gpu": "GPU",
        "tpu": "TPU",
        "accelerator": "AI Accelerators",
        "cluster": "Cluster"
    }
    
    # Categorize hardware by type
    categorized_hardware = {
        "gpu": [],
        "tpu": [],
        "accelerator": [],
        "cluster": [],
        "hierarchical": []  # New: hierarchical hardware configs
    }
    
    if os.path.exists(hardware_base_dir):
        # Scan each category folder
        for category_key, folder_name in folder_map.items():
            category_dir = os.path.join(hardware_base_dir, folder_name)
            
            if os.path.exists(category_dir) and os.path.isdir(category_dir):
                for file in os.listdir(category_dir):
                    if file.endswith('.json'):
                        try:
                            # Read file to get display name
                            file_path = os.path.join(category_dir, file)
                            with open(file_path, 'r') as f:
                                data = json.load(f)
                            
                            display_name = data.get("meta", {}).get("name", file.replace('.json', ''))
                            
                            categorized_hardware[category_key].append({
                                "name": file,
                                "type": category_key,
                                "display_name": display_name,
                                "folder": folder_name
                            })
                        except Exception as e:
                            print(f"Error reading {file} in {folder_name}: {e}")
                            # Still add it with just filename
                            categorized_hardware[category_key].append({
                                "name": file,
                                "type": category_key,
                                "display_name": file.replace('.json', ''),
                                "folder": folder_name
                            })
        
        # Also scan root hardware directory for any legacy files
        for file in os.listdir(hardware_base_dir):
            if file.endswith('.json'):
                try:
                    file_path = os.path.join(hardware_base_dir, file)
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                    
                    # Auto-detect type for legacy files
                    hw_type = "gpu"  # default
                    if data.get("meta"):
                        name = (data["meta"].get("name") or "").lower()
                        vendor = (data["meta"].get("vendor") or "").lower()
                        
                        if "tpu" in name or vendor == "google":
                            hw_type = "tpu"
                        elif "superpod" in name or "dgx" in name or "cluster" in name:
                            hw_type = "cluster"
                        elif any(keyword in name for keyword in ["groq", "lpu", "mtia", "trn", "trainium", "samba", "datascale"]):
                            hw_type = "accelerator"
                    
                    categorized_hardware[hw_type].append({
                        "name": file,
                        "type": hw_type,
                        "display_name": data.get("meta", {}).get("name", file.replace('.json', '')),
                        "folder": None  # Root directory
                    })
                except Exception as e:
                    print(f"Error reading {file}: {e}")
        
        # Scan for hierarchical hardware configurations (nvidia_a100, nvidia_h100, nvidia_b100, datacentre_1)
        hierarchical_dirs = ["nvidia_a100", "nvidia_h100", "nvidia_b100", "datacentre_1"]
        for hw_dir in hierarchical_dirs:
            hw_path = os.path.join(hardware_base_dir, hw_dir)
            if os.path.exists(hw_path) and os.path.isdir(hw_path):
                # Check if cluster_index.json exists
                index_file = os.path.join(hw_path, "cluster_index.json")
                display_name = hw_dir.replace("_", " ").upper()
                description = None
                total_clusters = 0
                
                if os.path.exists(index_file):
                    try:
                        with open(index_file, 'r') as f:
                            index_data = json.load(f)
                        # Extract name from metadata.hardware or clusters
                        if "metadata" in index_data:
                            display_name = index_data["metadata"].get("hardware", display_name)
                            description = index_data["metadata"].get("description", None)
                            total_clusters = index_data["metadata"].get("total_clusters", 0)
                        elif "name" in index_data:
                            display_name = index_data["name"]
                    except Exception as e:
                        print(f"Error reading index file for {hw_dir}: {e}")
                
                # Count available level files
                level_files = [f for f in os.listdir(hw_path) if f.endswith('.json')]
                
                categorized_hardware["hierarchical"].append({
                    "name": hw_dir,
                    "type": "hierarchical",
                    "display_name": display_name,
                    "folder": hw_dir,
                    "levels": len(level_files),
                    "has_index": os.path.exists(index_file),
                    "total_clusters": total_clusters,
                    "description": description
                })
    
    # If category parameter is provided, return only that category
    if category and category in categorized_hardware:
        return {
            "hardware_configs": categorized_hardware[category],
            "category": category
        }
    
    return {
        "hardware_configs": categorized_hardware,
        "total": sum(len(v) for v in categorized_hardware.values())
    }

@app.get("/examples/workloads")
async def get_example_workloads(response: Response):
    # Add cache-busting headers
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    examples_dir = os.path.join(os.path.dirname(__file__), "..", "data", "models")
    workloads = []
    if os.path.exists(examples_dir):
        for file in os.listdir(examples_dir):
            # List any JSON workload files
            if file.endswith('.json'):
                workloads.append({"name": file})
    return {"workloads": workloads}

@app.get("/examples/workloads/{workload_name}")
async def get_example_workload(workload_name: str):
    workload_path = os.path.join(os.path.dirname(__file__), "..", "data", "models", workload_name)
    if not os.path.exists(workload_path):
        raise HTTPException(status_code=404, detail="Workload not found")
    with open(workload_path, 'r') as f:
        return json.load(f)

@app.get("/examples/hardware/{hardware_name}")
async def get_example_hardware_config(hardware_name: str, response: Response):
    # Add cache-busting headers
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    
    # Try to find file in subdirectories first
    subdirs = ["GPU", "TPU", "AI Accelerators", "Cluster"]
    for subdir in subdirs:
        hardware_path = os.path.join(hardware_base_dir, subdir, hardware_name)
        if os.path.exists(hardware_path):
            with open(hardware_path, 'r') as f:
                return json.load(f)
    
    # If not found in subdirectories, try root directory (for legacy files)
    hardware_path = os.path.join(hardware_base_dir, hardware_name)
    if os.path.exists(hardware_path):
        with open(hardware_path, 'r') as f:
            return json.load(f)
    
    raise HTTPException(status_code=404, detail="Hardware configuration not found")

@app.get("/examples/hardware/{category}/{file_name}")
async def get_hardware_details(category: str, file_name: str, response: Response):
    # Add cache-busting headers
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    
    # Map frontend categories to folder names
    folder_map = {
        "gpu": "GPU",
        "tpu": "TPU",
        "accelerator": "AI Accelerators",
        "cluster": "Cluster",
        "SM-level": "SM-level",
        # Hierarchical hardware configs
        "nvidia_a100": "nvidia_a100",
        "nvidia_h100": "nvidia_h100",
        "nvidia_b100": "nvidia_b100"
    }
    
    if category in folder_map:
        folder_name = folder_map[category]
        hardware_path = os.path.join(hardware_base_dir, folder_name, file_name)
        
        if os.path.exists(hardware_path):
            with open(hardware_path, 'r') as f:
                return json.load(f)
    
    raise HTTPException(status_code=404, detail=f"Hardware file not found: {category}/{file_name}")

@app.get("/examples/hardware/hierarchical/{hardware_name}")
async def get_hierarchical_hardware(hardware_name: str, response: Response):
    """
    Get all hierarchical level files for a specific hardware configuration.
    Returns all JSON files from L-1 (datacenter) to L5 (tensor core).
    """
    # Add cache-busting headers
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    hardware_path = os.path.join(hardware_base_dir, hardware_name)
    
    if not os.path.exists(hardware_path) or not os.path.isdir(hardware_path):
        raise HTTPException(status_code=404, detail=f"Hierarchical hardware config not found: {hardware_name}")
    
    # Expected level files
    level_files = [
        "cluster_index.json",
        "L-1_datacenter.json",
        "L0_cluster.json",
        "L1_rack.json",
        "L2_node.json",
        "L2_5_fabric.json",
        "L3_device.json",
        "L4_sm.json",
        "L5_tensor_core.json"
    ]
    
    result = {
        "hardware_name": hardware_name,
        "levels": {}
    }
    
    # Load each level file
    for level_file in level_files:
        file_path = os.path.join(hardware_path, level_file)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    result["levels"][level_file.replace(".json", "")] = json.load(f)
            except Exception as e:
                print(f"Error reading {level_file} for {hardware_name}: {e}")
                result["levels"][level_file.replace(".json", "")] = None
    
    if not result["levels"]:
        raise HTTPException(status_code=404, detail=f"No level files found for: {hardware_name}")
    
    return result

# Also expose a non-conflicting path to avoid matching the generic
# "/examples/hardware/{category}/{file_name}" route
@app.get("/examples/hierarchical/{hardware_name}")
async def get_hierarchical_hardware_alt(hardware_name: str, response: Response):
    # Delegate to the main handler above
    return await get_hierarchical_hardware(hardware_name, response)

# NEW: Datacentre structure endpoints
@app.get("/examples/datacentre/{datacentre_name}")
async def get_datacentre_structure(datacentre_name: str, response: Response):
    """
    Get the complete datacentre structure including cluster index and datacenter info.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    datacentre_path = os.path.join(hardware_base_dir, datacentre_name)
    
    if not os.path.exists(datacentre_path) or not os.path.isdir(datacentre_path):
        raise HTTPException(status_code=404, detail=f"Datacentre not found: {datacentre_name}")
    
    result = {
        "datacentre_name": datacentre_name,
        "datacenter": None,
        "cluster_index": None,
        "clusters": []
    }
    
    # Load datacenter file
    datacenter_file = os.path.join(datacentre_path, "L-1_datacenter.json")
    if os.path.exists(datacenter_file):
        with open(datacenter_file, 'r') as f:
            result["datacenter"] = json.load(f)
    
    # Load cluster index
    index_file = os.path.join(datacentre_path, "cluster_index.json")
    if os.path.exists(index_file):
        with open(index_file, 'r') as f:
            result["cluster_index"] = json.load(f)
    
    # List available clusters
    clusters_path = os.path.join(datacentre_path, "clusters")
    if os.path.exists(clusters_path) and os.path.isdir(clusters_path):
        result["clusters"] = [d for d in os.listdir(clusters_path) if os.path.isdir(os.path.join(clusters_path, d))]
    
    return result

@app.get("/examples/datacentre/{datacentre_name}/cluster/{cluster_type}")
async def get_cluster_data(datacentre_name: str, cluster_type: str, response: Response):
    """
    Get cluster-level data (L0) for a specific cluster type (a100, h100, b100).
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    cluster_file = os.path.join(hardware_base_dir, datacentre_name, "clusters", cluster_type, f"L0_cluster_{cluster_type}.json")
    
    if not os.path.exists(cluster_file):
        raise HTTPException(status_code=404, detail=f"Cluster file not found: {cluster_type}")
    
    with open(cluster_file, 'r') as f:
        return json.load(f)

@app.get("/examples/datacentre/{datacentre_name}/cluster/{cluster_type}/rack")
async def get_rack_data(datacentre_name: str, cluster_type: str, response: Response):
    """
    Get rack-level data (L1) for a specific cluster type.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    rack_file = os.path.join(hardware_base_dir, datacentre_name, "clusters", cluster_type, "racks", f"L1_rack_{cluster_type}.json")
    
    if not os.path.exists(rack_file):
        raise HTTPException(status_code=404, detail=f"Rack file not found for {cluster_type}")
    
    with open(rack_file, 'r') as f:
        return json.load(f)

@app.get("/examples/datacentre/{datacentre_name}/cluster/{cluster_type}/node")
async def get_node_data(datacentre_name: str, cluster_type: str, response: Response):
    """
    Get node-level data (L2) for a specific cluster type.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    node_file = os.path.join(hardware_base_dir, datacentre_name, "clusters", cluster_type, "racks", "nodes", f"L2_node_{cluster_type}.json")
    
    if not os.path.exists(node_file):
        raise HTTPException(status_code=404, detail=f"Node file not found for {cluster_type}")
    
    with open(node_file, 'r') as f:
        return json.load(f)

@app.get("/examples/datacentre/{datacentre_name}/cluster/{cluster_type}/device")
async def get_device_data(datacentre_name: str, cluster_type: str, response: Response):
    """
    Get device/GPU-level data (L3) for a specific cluster type.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    device_file = os.path.join(hardware_base_dir, datacentre_name, "clusters", cluster_type, "racks", "nodes", "devices", f"L3_device_{cluster_type}.json")
    
    if not os.path.exists(device_file):
        raise HTTPException(status_code=404, detail=f"Device file not found for {cluster_type}")
    
    with open(device_file, 'r') as f:
        return json.load(f)
@app.get("/examples/datacentre/{datacentre_name}/cluster/{cluster_type}/sm")
async def get_sm_data(datacentre_name: str, cluster_type: str, response: Response):
    """
    Get SM-level data (L4) for a specific cluster type.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    sm_file = os.path.join(hardware_base_dir, datacentre_name, "clusters", cluster_type, "racks", "nodes", "devices", "sms", f"L4_sm_{cluster_type}.json")
    
    if not os.path.exists(sm_file):
        raise HTTPException(status_code=404, detail=f"SM file not found for {cluster_type}")
    
    with open(sm_file, 'r') as f:
        return json.load(f)
@app.get("/examples/datacentre/{datacentre_name}/cluster/{cluster_type}/tensor_core")
async def get_tensor_core_data(datacentre_name: str, cluster_type: str, response: Response):
    """
    Get Tensor Core-level data (L5) for a specific cluster type.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    hardware_base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "hardware")
    tc_file = os.path.join(hardware_base_dir, datacentre_name, "clusters", cluster_type, "racks", "nodes", "devices", "sms", "tensor_cores", f"L5_tensor_core_{cluster_type}.json")
    
    if not os.path.exists(tc_file):
        raise HTTPException(status_code=404, detail=f"Tensor Core file not found for {cluster_type}")
    
    with open(tc_file, 'r') as f:
        return json.load(f)

# NEW: Decoder endpoints
@app.get("/api/examples/decoder")
async def api_list_decoder():
    if not os.path.isdir(DECODER_DIR):
        raise HTTPException(status_code=404, detail=f"Decoder directory not found: {DECODER_DIR}")
    return {"decoders": [{"name": f} for f in sorted(os.listdir(DECODER_DIR)) if f.endswith(".json")]}

@app.get("/api/examples/decoder/{decoder_name}")
async def api_get_decoder(decoder_name: str):
    if not os.path.isdir(DECODER_DIR):
        raise HTTPException(status_code=404, detail=f"Decoder directory not found: {DECODER_DIR}")
    path = _find_decoder_path(decoder_name)
    if not path:
        raise HTTPException(status_code=404, detail=f"Decoder DAG not found for '{decoder_name}' in {DECODER_DIR}")
    
    with open(path, "r", encoding="utf-8") as f:
        raw_decoder_data = json.load(f)
    
    # Transform the decoder data to DAG format
    dag_data = transform_decoder_to_dag(raw_decoder_data)
    return dag_data

# ============================================================================
# SIMPLIFIED PROFILING API ENDPOINTS
# ============================================================================

import tempfile
import shutil

# Remote Instance Management Models
class Instance(BaseModel):
    name: str
    ip: str
    pem_file: str
    os: str = "ubuntu"
    username: str = "ubuntu"

class BenchmarkRequest(BaseModel):
    model: str
    engine: str = "vllm"
    quick: Optional[bool] = False
    comprehensive: Optional[bool] = False

class SetClockRequest(BaseModel):
    ip: str
    ssh_user: str
    pem_path: str
    clock_type: str  # "core", "hbm", or "nvlink"
    clock_percent: int  # 0-100

class TofuInstanceRequest(BaseModel):
    provider: str  # "aws"
    instance_name: str
    instance_type: str  # e.g., "g5.xlarge"
    region: str  # e.g., "us-east-1"
    ssh_key_name: Optional[str] = None
    ssh_public_key: Optional[str] = None
    image_id: Optional[str] = None  # AMI ID for AWS
    credentials: Dict[str, Any] = {}  # AWS credentials

class SetupInstanceRequestOld(BaseModel):
    """Legacy setup request - kept for backward compatibility"""
    ip: str
    ssh_user: str
    pem_path: Optional[str] = None
    pem_base64: Optional[str] = None
    script_path: Optional[str] = None

class SetupInstanceRequest(BaseModel):
    """Request model for instance setup (h100_fp8.sh)"""
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None
    model_name: str = "Qwen/Qwen3.5-9B"
    model_path: Optional[str] = None  # Will default to /home/ubuntu/BM/models/{model_name_basename}
    cloud_provider: str = "lambda"  # "lambda" or "scaleway" - determines which scripts to use
    hf_token: Optional[str] = None  # Optional HF token to place on the remote host

def _get_backend_hf_token() -> Optional[str]:
    """Fetch HF token from backend environment or well-known file locations."""
    token = os.environ.get("HF_TOKEN")
    if token:
        return token.strip()
    token_file = os.environ.get("HF_TOKEN_FILE")
    if token_file and os.path.exists(token_file):
        try:
            with open(token_file, "r") as f:
                return f.readline().strip().strip('"')
        except Exception:
            pass
    if os.path.exists("/etc/gpu-setup/hf_token"):
        try:
            with open("/etc/gpu-setup/hf_token", "r") as f:
                return f.readline().strip().strip('"')
        except Exception:
            pass
    return None

class CheckInstanceRequest(BaseModel):
    """Request model for instance check (lol.sh)"""
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None
    cloud_provider: str = "lambda"  # "lambda" or "scaleway"

class DeployVLLMRequest(BaseModel):
    """Request model for vLLM deployment (lol4.sh)"""
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None
    model_path: str = "/home/ubuntu/BM/models/Qwen3.5-9B"
    max_model_len: Optional[int] = None
    max_num_seqs: Optional[int] = None
    gpu_memory_utilization: Optional[float] = None
    tensor_parallel_size: Optional[int] = None
    cloud_provider: str = "lambda"  # "lambda" or "scaleway"

class RunBenchmarkRequest(BaseModel):
    """Request model for workload benchmark (agent.py --mode standard)"""
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None
    model_path: str = "/home/ubuntu/BM/models/Qwen3.5-9B"
    cloud_provider: str = "lambda"  # "lambda" or "scaleway"
    input_seq_len: int = 1000
    output_seq_len: int = 1000
    num_requests: int = 50
    request_rate: float = 25.0
    max_concurrency: int = 4


class KernelProfileRequest(BaseModel):
    """Request model for kernel profiling (agent.py --mode kernel)"""
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None
    model_path: str = "/home/ubuntu/BM/models/Qwen3.5-9B"
    cloud_provider: str = "lambda"
    kernel_requests: int = 20

class VLLMBenchmarkRequest(BaseModel):
    """Request model for vLLM benchmark with user parameters"""
    # SSH connection
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None  # Base64 encoded SSH key
    
    # Model selection and download
    model_name: str = "Qwen/Qwen3.5-9B"  # HuggingFace model name
    model_path: str = "/home/ubuntu/BM/models/Qwen3.5-9B"  # Path to model on remote instance
    download_model: bool = True  # Whether to download model if not present
    
    # vLLM parameters
    max_tokens: Optional[int] = None  # Override max tokens (uses adaptive if None)
    max_model_len: Optional[int] = None  # Override max model length (uses adaptive if None)
    max_num_seqs: Optional[int] = None  # Override max sequences (uses adaptive if None)
    gpu_memory_utilization: Optional[float] = None  # Override GPU memory util (uses adaptive if None)
    tensor_parallel_size: Optional[int] = None  # Override tensor parallel size (uses adaptive if None)
    
    # Benchmark parameters
    num_requests: int = 10  # Number of benchmark requests to send
    batch_size: int = 1  # Batch size for requests (concurrent requests)
    input_seq_len: int = 100  # Input sequence length (prompt length)
    output_seq_len: int = 100  # Output sequence length (max_tokens)
    prompt: str = "What is the capital of France?"  # Benchmark prompt (will be padded/truncated to input_seq_len)
    port: int = 8000  # vLLM server port

# Profiling endpoints removed because workload_analyzer dependency is absent

# ============================================================================
# BENCHMARK DASHBOARD ENDPOINTS
# ============================================================================

@app.get("/benchmark/data")
async def get_benchmark_data():
    """Get all benchmark data from the dashboard folder with enhanced metadata."""
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        benchmark_data = {}
        
        logger.info(f"Looking for benchmark data in: {dashboard_dir.resolve()}")
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        # Extract model name from new format
                        model_name = file_path.stem
                        if 'benchmark_info' in data:
                            if 'model_name' in data['benchmark_info']:
                                model_name = Path(data['benchmark_info']['model_name']).name
                            elif 'model_path' in data['benchmark_info']:
                                model_name = Path(data['benchmark_info']['model_path']).name
                        elif 'model' in data:
                            model_name = data['model']
                        
                        benchmark_data[model_name] = data
                        logger.info(f"Loaded benchmark data: {model_name}")
                except Exception as e:
                    logger.error(f"Error loading {file_path}: {e}")
                    continue
        else:
            logger.warning(f"Dashboard directory does not exist: {dashboard_dir.resolve()}")
        
        return benchmark_data
    except Exception as e:
        logger.error(f"Failed to load benchmark data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to load benchmark data: {str(e)}")

@app.get("/benchmark/models")
async def get_benchmark_models():
    """Get list of available benchmark models."""
    try:
        # Use absolute path resolution from backend directory
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        models = []
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        model_name = file_path.stem
                        if 'model' in data:
                            model_name = data['model']
                        elif 'benchmark_info' in data and 'model_path' in data['benchmark_info']:
                            model_name = Path(data['benchmark_info']['model_path']).name
                        
                        models.append({
                            "name": model_name,
                            "file": file_path.name,
                            "timestamp": data.get('timestamp', ''),
                            "total_configurations": data.get('total_configurations', 0)
                        })
                except Exception as e:
                    print(f"Error loading {file_path}: {e}")
                    continue
        
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load benchmark models: {str(e)}")

@app.get("/benchmark/results/{model_name}")
async def get_benchmark_results(model_name: str):
    """Get benchmark results for a specific model."""
    try:
        # Use absolute path resolution from backend directory
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        # Find the file for this model
        model_file = None
        for file_path in dashboard_dir.glob("*.json"):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    current_model = file_path.stem
                    if 'model' in data:
                        current_model = data['model']
                    elif 'benchmark_info' in data and 'model_path' in data['benchmark_info']:
                        current_model = Path(data['benchmark_info']['model_path']).name
                    
                    if current_model == model_name:
                        model_file = data
                        break
            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")
                continue
        
        if not model_file:
            raise HTTPException(status_code=404, detail=f"Model {model_name} not found")
        
        return model_file
    except Exception as e:
        logger.error(f"Failed to load benchmark results for {model_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to load benchmark results for {model_name}: {str(e)}")

# ============================================================================
# BENCHMARK KPI COMPUTATION ENDPOINTS
# ============================================================================

@app.get("/benchmark/dashboard/metadata")
async def get_dashboard_metadata():
    """Get system and model information for dashboard header."""
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        metadata = {
            "system_info": {},
            "models": []
        }
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        if 'benchmark_info' in data:
                            model_info = {
                                "model_name": Path(data['benchmark_info'].get('model_name', '')).name,
                                "engine": data['benchmark_info'].get('engine', 'unknown'),
                                "timestamp": data['benchmark_info'].get('timestamp', ''),
                                "total_tests": data['benchmark_info'].get('total_tests', 0),
                                "provenance": data['benchmark_info'].get('provenance', {})
                            }
                            
                            # Extract GPU count from first result
                            if 'results' in data and data['results']:
                                first_result = data['results'][0]
                                if 'gpu_metrics' in first_result:
                                    model_info['gpu_count'] = len(first_result['gpu_metrics'])
                                    if first_result['gpu_metrics']:
                                        model_info['gpu_model'] = f"GPU (Total VRAM: {first_result['gpu_metrics'][0].get('memory_total_gb', 0)} GB per GPU)"
                            
                            metadata['models'].append(model_info)
                
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    continue
        
        return metadata
    except Exception as e:
        logger.error(f"Failed to load dashboard metadata: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to load dashboard metadata: {str(e)}")

@app.get("/benchmark/dashboard/detailed-metrics")
async def get_detailed_metrics(
    model: Optional[str] = Query(None),
    batch_size: Optional[int] = Query(None),
    min_input_length: Optional[int] = Query(None),
    max_input_length: Optional[int] = Query(None)
):
    # Function body removed - mapper module not available
    pass

@app.get("/benchmark/dashboard/aggregated-metrics")
async def get_aggregated_metrics(
    group_by: str = Query("model", description="Group by: model, batch_size, input_length"),
    model: Optional[str] = Query(None)
):
    # Function body removed - mapper module not available
    pass

@app.get("/benchmark/dashboard/time-series")
async def get_time_series_data(metric: str = Query("decode_throughput", description="Metric to plot over time")):
    """
    Get time-series data for line graphs.
    Supports: prefill_latency, decode_latency, decode_throughput, power_draw, sm_utilization, hbm_utilization, nvlink_utilization
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        time_series = []
        
        metric_mapping = {
            "prefill_latency": "prefill_latency_ms",
            "decode_latency": "decode_latency_ms",
            "decode_throughput": "decode_throughput_tokens_per_second",
            "power_draw": "power_draw_watts",
            "sm_utilization": "sm_utilization_percent",
            "hbm_utilization": "hbm_bandwidth_utilization_percent",
            "nvlink_utilization": "nvlink_bandwidth_utilization_percent",
            "perf_per_watt": "performance_per_watt",
            "cost": "cost_usd",
            "perf_per_dollar": "performance_per_dollar"
        }
        
        metric_key = metric_mapping.get(metric, metric)
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        if 'results' not in data:
                            continue
                        
                        model_name = Path(data.get('benchmark_info', {}).get('model_name', file_path.stem)).name
                        
                        for idx, result in enumerate(data['results']):
                            if not result.get('success', False):
                                continue
                            
                            time_series.append({
                                "model": model_name,
                                "timestamp": result.get('timestamp', ''),
                                "iteration": idx,
                                "batch_size": result.get('batch_size', 0),
                                "input_length": result.get('input_length', 0),
                                "value": result.get(metric_key, 0),
                                "metric": metric
                            })
                
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    continue
        
        return {"time_series": time_series, "metric": metric}
    except Exception as e:
        logger.error(f"Failed to get time-series data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get time-series data: {str(e)}")

@app.get("/benchmark/dashboard/comparison")
async def get_comparison_data(
    models: Optional[str] = Query(None, description="Comma-separated model names"),
    batch_sizes: Optional[str] = Query(None, description="Comma-separated batch sizes")
):
    """
    Placeholder comparison endpoint (returns selected filters for now).
    """
    try:
        return {
            "models": models.split(",") if models else [],
            "batch_sizes": batch_sizes.split(",") if batch_sizes else [],
            "data": []
        }
    except Exception as e:
        logger.error(f"Failed to get comparison data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get comparison data: {str(e)}")

@app.get("/benchmark/dashboard/summary-table")
async def get_summary_table():
    """
    Get summary table with overall statistics broken down by model.
    Returns average, min, max, std dev for all key metrics.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        from collections import defaultdict
        import statistics
        
        model_metrics = defaultdict(lambda: defaultdict(list))
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        if 'results' not in data:
                            continue
                        
                        model_name = Path(data.get('benchmark_info', {}).get('model_name', file_path.stem)).name
                        
                        for result in data['results']:
                            # Include all results, including failed ones
                            
                            # Helper function to safely get numeric values, filtering out None/null
                            def safe_get_numeric(key, default=0):
                                value = result.get(key, default)
                                return value if value is not None else default
                            
                            # Collect all metrics, filtering out None values
                            prefill_lat = safe_get_numeric('prefill_latency_ms')
                            if prefill_lat is not None:
                                model_metrics[model_name]["prefill_latency_ms"].append(prefill_lat)
                            
                            decode_lat = safe_get_numeric('decode_latency_ms')
                            if decode_lat is not None:
                                model_metrics[model_name]["decode_latency_ms"].append(decode_lat)
                            
                            model_metrics[model_name]["decode_throughput"].append(safe_get_numeric('decode_throughput_tokens_per_second'))
                            model_metrics[model_name]["sm_utilization"].append(safe_get_numeric('sm_active_percent'))
                            model_metrics[model_name]["hbm_utilization"].append(safe_get_numeric('hbm_bandwidth_utilization_percent'))
                            model_metrics[model_name]["nvlink_utilization"].append(safe_get_numeric('nvlink_bandwidth_utilization_percent'))
                            model_metrics[model_name]["power_draw"].append(safe_get_numeric('power_draw_watts'))
                            model_metrics[model_name]["perf_per_watt"].append(safe_get_numeric('performance_per_watt'))
                            model_metrics[model_name]["cost"].append(safe_get_numeric('cost_usd'))
                            model_metrics[model_name]["perf_per_dollar"].append(safe_get_numeric('performance_per_dollar'))
                
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    continue
        
        # Calculate summary statistics
        summary_table = []
        for model_name, metrics in model_metrics.items():
            summary = {"model": model_name}
            
            for metric_name, values in metrics.items():
                if values and len(values) > 0:
                    # Filter out any None values that might have slipped through
                    numeric_values = [v for v in values if v is not None and isinstance(v, (int, float))]
                    if numeric_values:
                        summary[f"{metric_name}_avg"] = statistics.mean(numeric_values)
                        summary[f"{metric_name}_min"] = min(numeric_values)
                        summary[f"{metric_name}_max"] = max(numeric_values)
                        summary[f"{metric_name}_std"] = statistics.stdev(numeric_values) if len(numeric_values) > 1 else 0
                        summary[f"{metric_name}_count"] = len(numeric_values)
                    else:
                        summary[f"{metric_name}_avg"] = 0
                        summary[f"{metric_name}_min"] = 0
                        summary[f"{metric_name}_max"] = 0
                        summary[f"{metric_name}_std"] = 0
                        summary[f"{metric_name}_count"] = 0
                else:
                    summary[f"{metric_name}_avg"] = 0
                    summary[f"{metric_name}_min"] = 0
                    summary[f"{metric_name}_max"] = 0
                    summary[f"{metric_name}_std"] = 0
                    summary[f"{metric_name}_count"] = 0
            
            summary_table.append(summary)
        
        return {"summary": summary_table}
    except Exception as e:
        logger.error(f"Failed to get summary table: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get summary table: {str(e)}")

@app.get("/benchmark/kpis/throughput")
async def get_throughput_kpis():
    """Compute throughput KPIs across all tests."""
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        throughput_data = []
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*_final.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        if isinstance(data, list):
                            for test in data:
                                if test.get('success') and 'throughput_metrics' in test:
                                    throughput_data.append({
                                        'model': test.get('model_name', 'Unknown'),
                                        'test_config': test.get('test_config', {}).get('name', 'Unknown'),
                                        'batch_size': test.get('test_config', {}).get('batch_size', 0),
                                        'tokens_per_second': test['throughput_metrics'].get('tokens_per_second', 0),
                                        'tokens_per_second_per_gpu': test['throughput_metrics'].get('tokens_per_second_per_gpu', 0),
                                        'requests_per_second': test['throughput_metrics'].get('requests_per_second', 0),
                                        'total_tokens': test['throughput_metrics'].get('total_tokens', 0),
                                        'test_duration': test.get('test_duration_seconds', 0),
                                        'timestamp': test.get('timestamp', '')
                                    })
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    continue
        
        return {"throughput_kpis": throughput_data}
    except Exception as e:
        logger.error(f"Failed to compute throughput KPIs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to compute throughput KPIs: {str(e)}")

@app.get("/benchmark/kpis/gpu-metrics")
async def get_gpu_metrics_kpis():
    """Compute GPU utilization, memory, and power KPIs."""
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        gpu_metrics_data = []
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*_final.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        if isinstance(data, list):
                            for test in data:
                                if test.get('success') and 'gpu_metrics' in test:
                                    gpu_metrics = test['gpu_metrics']
                                    
                                    # Compute averages across all GPUs
                                    avg_utilization = sum(g.get('gpu_utilization_percent', 0) for g in gpu_metrics) / len(gpu_metrics) if gpu_metrics else 0
                                    avg_memory = sum(g.get('memory_used_gb', 0) for g in gpu_metrics) / len(gpu_metrics) if gpu_metrics else 0
                                    avg_power = sum(g.get('power_draw_w', 0) for g in gpu_metrics) / len(gpu_metrics) if gpu_metrics else 0
                                    avg_temp = sum(g.get('temperature_c', 0) for g in gpu_metrics) / len(gpu_metrics) if gpu_metrics else 0
                                    
                                    # Per-GPU metrics
                                    per_gpu_metrics = []
                                    for gpu in gpu_metrics:
                                        per_gpu_metrics.append({
                                            'gpu_id': gpu.get('gpu_id', 0),
                                            'utilization': gpu.get('gpu_utilization_percent', 0),
                                            'memory_used': gpu.get('memory_used_gb', 0),
                                            'memory_total': gpu.get('memory_total_gb', 0),
                                            'power_draw': gpu.get('power_draw_w', 0),
                                            'temperature': gpu.get('temperature_c', 0)
                                        })
                                    
                                    gpu_metrics_data.append({
                                        'model': test.get('model_name', 'Unknown'),
                                        'test_config': test.get('test_config', {}).get('name', 'Unknown'),
                                        'batch_size': test.get('test_config', {}).get('batch_size', 0),
                                        'avg_gpu_utilization': avg_utilization,
                                        'avg_memory_used': avg_memory,
                                        'avg_power_draw': avg_power,
                                        'avg_temperature': avg_temp,
                                        'gpu_count': len(gpu_metrics),
                                        'per_gpu_metrics': per_gpu_metrics,
                                        'timestamp': test.get('timestamp', '')
                                    })
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    continue
        
        return {"gpu_metrics_kpis": gpu_metrics_data}
    except Exception as e:
        logger.error(f"Failed to compute GPU metrics KPIs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to compute GPU metrics KPIs: {str(e)}")

@app.get("/benchmark/kpis/latency")
async def get_latency_kpis():
    """Compute latency KPIs (TTFT, TBT) across all tests."""
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        latency_data = []
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*_final.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        if isinstance(data, list):
                            for test in data:
                                if test.get('success') and 'latency_metrics' in test:
                                    latency_metrics = test['latency_metrics']
                                    
                                    latency_data.append({
                                        'model': test.get('model_name', 'Unknown'),
                                        'test_config': test.get('test_config', {}).get('name', 'Unknown'),
                                        'batch_size': test.get('test_config', {}).get('batch_size', 0),
                                        'ttft_p50': latency_metrics.get('ttft_p50_ms', 0),
                                        'ttft_p95': latency_metrics.get('ttft_p95_ms', 0),
                                        'tbt_p50': latency_metrics.get('tbt_p50_ms', 0),
                                        'tbt_p95': latency_metrics.get('tbt_p95_ms', 0),
                                        'total_latency': latency_metrics.get('total_latency_ms', 0),
                                        'tokens_generated': latency_metrics.get('tokens_generated', 0),
                                        'timestamp': test.get('timestamp', '')
                                    })
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    continue
        
        return {"latency_kpis": latency_data}
    except Exception as e:
        logger.error(f"Failed to compute latency KPIs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to compute latency KPIs: {str(e)}")

@app.get("/benchmark/kpis/system-resources")
async def get_system_resource_kpis():
    """Compute system resource utilization KPIs."""
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        system_data = []
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*_final.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        if isinstance(data, list):
                            for test in data:
                                if test.get('success'):
                                    system_metrics = test.get('system_metrics', {})
                                    system_info = test.get('system_info', {})
                                    
                                    system_data.append({
                                        'model': test.get('model_name', 'Unknown'),
                                        'test_config': test.get('test_config', {}).get('name', 'Unknown'),
                                        'batch_size': test.get('test_config', {}).get('batch_size', 0),
                                        'cpu_utilization': system_metrics.get('cpu_utilization_percent', 0),
                                        'memory_used': system_metrics.get('memory_used_gb', 0),
                                        'total_memory': system_info.get('total_memory_gb', 0),
                                        'gpu_count': system_info.get('gpu_count', 0),
                                        'cpu_count': system_info.get('cpu_count', 0),
                                        'platform': system_info.get('platform', 'Unknown'),
                                        'timestamp': test.get('timestamp', '')
                                    })
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    continue
        
        return {"system_resource_kpis": system_data}
    except Exception as e:
        logger.error(f"Failed to compute system resource KPIs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to compute system resource KPIs: {str(e)}")

@app.get("/benchmark/kpis/summary")
async def get_kpi_summary():
    """Get comprehensive KPI summary for all models and tests."""
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        summary = {
            'models': {},
            'overall_stats': {
                'total_tests': 0,
                'successful_tests': 0,
                'failed_tests': 0
            }
        }
        
        if dashboard_dir.exists():
            for file_path in dashboard_dir.glob("*_final.json"):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                        if isinstance(data, list):
                            for test in data:
                                summary['overall_stats']['total_tests'] += 1
                                
                                if test.get('success'):
                                    summary['overall_stats']['successful_tests'] += 1
                                    
                                    model_name = test.get('model_name', 'Unknown')
                                    if model_name not in summary['models']:
                                        summary['models'][model_name] = {
                                            'test_count': 0,
                                            'avg_throughput': 0,
                                            'max_throughput': 0,
                                            'avg_ttft_p50': 0,
                                            'avg_tbt_p50': 0,
                                            'avg_gpu_utilization': 0,
                                            'avg_memory_per_gpu': 0,
                                            'avg_power_per_gpu': 0,
                                            'throughput_samples': [],
                                            'ttft_samples': [],
                                            'tbt_samples': [],
                                            'gpu_util_samples': [],
                                            'memory_samples': [],
                                            'power_samples': []
                                        }
                                    
                                    model_stats = summary['models'][model_name]
                                    model_stats['test_count'] += 1
                                    
                                    # Collect throughput
                                    if 'throughput_metrics' in test:
                                        tps = test['throughput_metrics'].get('tokens_per_second', 0)
                                        model_stats['throughput_samples'].append(tps)
                                        model_stats['max_throughput'] = max(model_stats['max_throughput'], tps)
                                    
                                    # Collect latency
                                    if 'latency_metrics' in test:
                                        model_stats['ttft_samples'].append(test['latency_metrics'].get('ttft_p50_ms', 0))
                                        model_stats['tbt_samples'].append(test['latency_metrics'].get('tbt_p50_ms', 0))
                                    
                                    # Collect GPU metrics
                                    if 'gpu_metrics' in test:
                                        gpu_metrics = test['gpu_metrics']
                                        if gpu_metrics:
                                            avg_util = sum(g.get('gpu_utilization_percent', 0) for g in gpu_metrics) / len(gpu_metrics)
                                            avg_mem = sum(g.get('memory_used_gb', 0) for g in gpu_metrics) / len(gpu_metrics)
                                            avg_pow = sum(g.get('power_draw_w', 0) for g in gpu_metrics) / len(gpu_metrics)
                                            
                                            model_stats['gpu_util_samples'].append(avg_util)
                                            model_stats['memory_samples'].append(avg_mem)
                                            model_stats['power_samples'].append(avg_pow)
                                else:
                                    summary['overall_stats']['failed_tests'] += 1
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    continue
        
        # Compute averages
        for model_name, stats in summary['models'].items():
            if stats['throughput_samples']:
                stats['avg_throughput'] = sum(stats['throughput_samples']) / len(stats['throughput_samples'])
            if stats['ttft_samples']:
                stats['avg_ttft_p50'] = sum(stats['ttft_samples']) / len(stats['ttft_samples'])
            if stats['tbt_samples']:
                stats['avg_tbt_p50'] = sum(stats['tbt_samples']) / len(stats['tbt_samples'])
            if stats['gpu_util_samples']:
                stats['avg_gpu_utilization'] = sum(stats['gpu_util_samples']) / len(stats['gpu_util_samples'])
            if stats['memory_samples']:
                stats['avg_memory_per_gpu'] = sum(stats['memory_samples']) / len(stats['memory_samples'])
            if stats['power_samples']:
                stats['avg_power_per_gpu'] = sum(stats['power_samples']) / len(stats['power_samples'])
            
            # Remove sample arrays to reduce response size
            del stats['throughput_samples']
            del stats['ttft_samples']
            del stats['tbt_samples']
            del stats['gpu_util_samples']
            del stats['memory_samples']
            del stats['power_samples']
        
        return summary
    except Exception as e:
        logger.error(f"Failed to compute KPI summary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to compute KPI summary: {str(e)}")

# ============================================================================
# REMOTE INSTANCE MANAGEMENT & BENCHMARK ORCHESTRATION ENDPOINTS
# ============================================================================

@app.get("/api/status")
async def get_status():
    """
    Return system-wide status of all instances and running tests.
    Uses Lambda Cloud log fetcher approach for connectivity checks.
    """
    instances = load_instances()
    status = {}
    for name, inst in instances.items():
        inst_status = {
            "ip": inst["ip"],
            "username": inst.get("username", "ubuntu"),
            "pem_file": inst.get("pem_file", ""),
            "status": "unknown"
        }
        try:
            # Test connectivity with echo command
            run_ssh_command(inst, "echo 'connection_ok'", timeout=10)
            inst_status["status"] = "online"
        except Exception as e:
            inst_status["status"] = "offline"
            inst_status["error"] = str(e)
        status[name] = inst_status

    return {
        "status": "success",
        "instances": status,
        "active_tests": ACTIVE_TESTS,
        "total_instances": len(status),
        "online_instances": sum(1 for v in status.values() if v["status"] == "online")
    }

@app.get("/api/status/{name}")
async def get_instance_status(name: str):
    """
    Get detailed status for a specific instance.
    Uses Lambda Cloud approach with enhanced system information.
    If name='default' or instance not found, uses DEFAULT_PEM_FILE and DEFAULT_IP.
    """
    instances = load_instances()
    
    # Use default instance if name is "default" or not found in registered instances
    if name == "default" or name not in instances:
        inst = {
            "pem_file": DEFAULT_PEM_FILE,
            "ip": DEFAULT_IP,
            "username": DEFAULT_USERNAME
        }
        instance_name = "default"
        using_defaults = True
    else:
        inst = instances[name]
        instance_name = name
        using_defaults = False

    try:
        # Get system info and uptime
        output = run_ssh_command(inst, "uname -a && uptime", timeout=10)
        return {
            "status": "success",
            "instance": instance_name,
            "ip": inst["ip"],
            "username": inst.get("username", "ubuntu"),
            "system_info": output,
            "online": True,
            "using_defaults": using_defaults
        }
    except Exception as e:
        return {
            "status": "error",
            "instance": instance_name,
            "ip": inst["ip"],
            "online": False,
            "error": str(e),
            "using_defaults": using_defaults
        }

@app.post("/api/instances")
async def add_instance(instance: Instance):
    """Register a new GPU instance"""
    instances = load_instances()
    if instance.name in instances:
        raise HTTPException(status_code=400, detail="Instance already exists")
    instances[instance.name] = instance.dict()
    save_instances(instances)
    return {"status": "success", "message": f"Instance {instance.name} added"}

@app.delete("/api/instances/{name}")
async def remove_instance(name: str):
    """Remove a GPU instance"""
    instances = load_instances()
    if name not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")
    del instances[name]
    save_instances(instances)
    return {"status": "success", "message": f"Instance {name} removed"}

@app.get("/api/test-connection/{name}")
async def test_connection(
    name: str,
    ip: str = Query(None, description="IP address to test (optional, overrides instance config)"),
    pem_file: str = Query(None, description="Path to PEM file (optional, overrides instance config)"),
    username: str = Query(None, description="Username (optional, overrides instance config)")
):
    """Lightweight connectivity check (stub)."""
    return {"status": "not_implemented", "message": "Connection test stub", "instance": name}

@app.get("/api/diagnostics/{name}")
async def get_system_diagnostics(
    name: str,
    ip: str = Query(None, description="IP address to test (optional, overrides instance config)"),
    pem_file: str = Query(None, description="Path to PEM file (optional, overrides instance config)"),
    username: str = Query(None, description="Username (optional, overrides instance config)")
):
    """System diagnostics stub."""
    return {"status": "not_implemented", "message": "Diagnostics stub", "instance": name}

@app.get("/api/logs/{name}/{log_type}")
async def get_logs(
    name: str, 
    log_type: str, 
    full: bool = Query(False, description="Fetch full logs instead of last N lines"),
    lines: int = Query(100, description="Number of lines to fetch for tailed logs"),
    ip: str = Query(None, description="IP address to fetch logs from (optional, overrides instance config)"),
    pem_file: str = Query(None, description="Path to PEM file (optional, overrides instance config)"),
    username: str = Query(None, description="Username (optional, overrides instance config)")
):
    """Logs retrieval stub."""
    return {"status": "not_implemented", "message": "Logs stub", "instance": name, "log_type": log_type}

@app.get("/api/files/{name}")
async def list_files(
    name: str, 
    directory: str = Query("/home/ubuntu/models", description="Directory to list files from"),
    ip: str = Query(None, description="IP address to list files from (optional, overrides instance config)"),
    pem_file: str = Query(None, description="Path to PEM file (optional, overrides instance config)"),
    username: str = Query(None, description="Username (optional, overrides instance config)")
):
    """List files stub."""
    return {"status": "not_implemented", "message": "List files stub", "instance": name, "directory": directory}

@app.get("/api/files/{name}/{filename}")
async def download_file(
    name: str, 
    filename: str, 
    directory: str = Query("/home/ubuntu/models", description="Directory to download file from"),
    ip: str = Query(None, description="IP address to download file from (optional, overrides instance config)"),
    pem_file: str = Query(None, description="Path to PEM file (optional, overrides instance config)"),
    username: str = Query(None, description="Username (optional, overrides instance config)")
):
    """Download file stub."""
    return {"status": "not_implemented", "message": "Download file stub", "instance": name, "filename": filename}
@app.post("/api/run-benchmark/{name}")
async def run_benchmark(name: str, request: BenchmarkRequest = Body(...)):
    """
    Launch remote benchmark (quick or comprehensive).
    If name='default' or instance not found, uses DEFAULT_PEM_FILE and DEFAULT_IP.
    """
    instances = load_instances()
    
    # Use default instance if name is "default" or not found in registered instances
    if name == "default" or name not in instances:
        inst = {
            "pem_file": DEFAULT_PEM_FILE,
            "ip": DEFAULT_IP,
            "username": DEFAULT_USERNAME
        }
        instance_name = "default"
    else:
        inst = instances[name]
        instance_name = name

    timestamp = int(time.time())
    test_id = f"{instance_name}_{timestamp}"

    # Construct benchmark command
    model = request.model
    engine = request.engine
    flags = "--quick" if request.quick else "--full-comprehensive" if request.comprehensive else ""
    log_file = f"benchmark_{timestamp}.log"
    command = (
        f"cd ~/models && "
        f"source ~/a100_benchmark_env/bin/activate && "
        f"nohup python optimized_batch_benchmark.py "
        f"--model {model} --engine {engine} {flags} > {log_file} 2>&1 &"
    )

    def _run():
        try:
            run_ssh_command(inst, command, timeout=15)
            ACTIVE_TESTS[test_id] = {
                "instance": instance_name,
                "ip": inst["ip"],
                "status": "running",
                "start_time": datetime.utcnow().isoformat(),
                "model": model,
                "engine": engine
            }
        except Exception as e:
            ACTIVE_TESTS[test_id] = {
                "instance": instance_name,
                "status": f"error: {e}"
            }

    loop = asyncio.get_event_loop()
    loop.run_in_executor(executor, _run)

    return {
        "status": "started",
        "test_id": test_id,
        "instance": instance_name,
        "ip": inst["ip"],
        "message": f"Benchmark started on {instance_name}",
        "using_defaults": (name == "default" or name not in instances)
    }

@app.post("/api/set-gpu-clock")
async def set_gpu_clock(request: SetClockRequest):
    """
    Set GPU clock settings via SSH following H100 best practices.
    Clock types: "core", "hbm", "nvlink"
    Clock percent: 0-100 (percentage of max clock)
    
    Process:
    1. Check current clock range (nvidia-smi -q -d CLOCK)
    2. Enable persistent mode (nvidia-smi -pm 1)
    3. Set application clocks using -lgc for graphics/SM clock
    4. Optionally set memory clock with -lmc
    5. Verify the change
    6. Apply to all GPUs if needed
    """
    try:
        # Create instance dict for SSH command
        instance = {
            "ip": request.ip,
            "username": request.ssh_user,
            "pem_file": request.pem_path
        }
        
        all_outputs = []
        diagnostics = {}
        
        # Step 1: Check Current Clock Range (nvidia-smi -q -d CLOCK)
        try:
            clock_query_cmd = "nvidia-smi -q -d CLOCK"
            clock_info = run_ssh_command(instance, clock_query_cmd, timeout=10)
            all_outputs.append("=== Current Clock Range ===")
            all_outputs.append(clock_info)
            diagnostics["current_clocks"] = clock_info
            
            # Extract default application clocks if available
            if "Default Applications Clocks" in clock_info:
                import re
                graphics_match = re.search(r'Graphics Clock\s*:\s*(\d+)\s*MHz', clock_info)
                sm_match = re.search(r'SM Clock\s*:\s*(\d+)\s*MHz', clock_info)
                if graphics_match or sm_match:
                    default_graphics = int(graphics_match.group(1)) if graphics_match else None
                    default_sm = int(sm_match.group(1)) if sm_match else None
                    diagnostics["default_graphics_clock"] = default_graphics
                    diagnostics["default_sm_clock"] = default_sm
        except Exception as e:
            logger.warning(f"Could not query current clocks: {e}")
            all_outputs.append(f"Could not query current clocks: {str(e)}")
        
        # Get GPU info for base clock calculation
        try:
            gpu_info_cmd = "nvidia-smi --query-gpu=name --format=csv,noheader,nounits | head -1"
            gpu_info = run_ssh_command(instance, gpu_info_cmd, timeout=10)
            gpu_name = gpu_info.strip().upper()
            diagnostics["gpu_name"] = gpu_name
        except Exception as e:
            gpu_name = "UNKNOWN"
            diagnostics["gpu_detection_error"] = str(e)
        
        # Determine base clocks based on GPU type
        if "H100" in gpu_name:
            base_clocks = {
                "core": 1980,  # H100 SM Clock max (MHz)
                "hbm": 3400,   # H100 HBM max (MHz)
                "nvlink": 900
            }
            gpu_type = "H100"
        elif "A100" in gpu_name:
            base_clocks = {
                "core": 1410,  # A100 SM Clock max (MHz)
                "hbm": 2433,   # A100 HBM max (MHz)
                "nvlink": 900
            }
            gpu_type = "A100"
        else:
            base_clocks = {
                "core": 1980,
                "hbm": 3400,
                "nvlink": 900
            }
            gpu_type = "Unknown (using H100 defaults)"
        
        clock_mhz = int((base_clocks.get(request.clock_type, 1980) * request.clock_percent) / 100)
        
        # Get number of GPUs
        try:
            gpu_count_cmd = "nvidia-smi --list-gpus | wc -l"
            gpu_count_output = run_ssh_command(instance, gpu_count_cmd, timeout=10)
            gpu_count = int(gpu_count_output.strip()) if gpu_count_output.strip().isdigit() else 1
        except:
            gpu_count = 1
        
        diagnostics["gpu_count"] = gpu_count
        diagnostics["target_clock_mhz"] = clock_mhz
        
        # Step 2: Enable persistent mode (nvidia-smi -pm 1)
        all_outputs.append("\n=== Step 2: Setting Persistent Mode ===")
        try:
            pm_cmd = "sudo nvidia-smi -pm 1"
            pm_output = run_ssh_command(instance, pm_cmd, timeout=15)
            all_outputs.append(f"Persistent mode enabled: {pm_output}")
        except Exception as e:
            logger.warning(f"Persistent mode setting warning: {e}")
            all_outputs.append(f"Persistent mode: {str(e)} (may already be enabled)")
        
        # Step 3: Set Application Clocks using -lgc (lock graphics clock)
        all_outputs.append("\n=== Step 3: Setting Application Clocks ===")
        commands = []
        error_messages = []
        
        if request.clock_type == "core":
            # For core clock, use -lgc to lock graphics/SM clock
            # Example: sudo nvidia-smi -lgc 1386,1386
            # Optionally also set memory clock: -lmc 2400,2400
            graphics_clock = clock_mhz
            memory_clock = int((base_clocks.get("hbm", 3400) * request.clock_percent) / 100)
            
            # Apply to all GPUs
            if gpu_count > 1:
                for i in range(gpu_count):
                    # Set graphics/SM clock
                    commands.append(f"sudo nvidia-smi -i {i} -lgc {graphics_clock},{graphics_clock}")
                    # Optionally set memory clock too
                    if request.clock_percent < 100:  # Only if reducing
                        commands.append(f"sudo nvidia-smi -i {i} -lmc {memory_clock},{memory_clock}")
            else:
                commands.append(f"sudo nvidia-smi -lgc {graphics_clock},{graphics_clock}")
                if request.clock_percent < 100:
                    commands.append(f"sudo nvidia-smi -lmc {memory_clock},{memory_clock}")
                    
        elif request.clock_type == "hbm":
            # For HBM/memory clock, use -lmc
            graphics_clock = int((base_clocks.get("core", 1980) * request.clock_percent) / 100)
            memory_clock = clock_mhz
            
            if gpu_count > 1:
                for i in range(gpu_count):
                    commands.append(f"sudo nvidia-smi -i {i} -lgc {graphics_clock},{graphics_clock}")
                    commands.append(f"sudo nvidia-smi -i {i} -lmc {memory_clock},{memory_clock}")
            else:
                commands.append(f"sudo nvidia-smi -lgc {graphics_clock},{graphics_clock}")
                commands.append(f"sudo nvidia-smi -lmc {memory_clock},{memory_clock}")
                    
        elif request.clock_type == "nvlink":
            # NVLink clock is typically tied to core clock
            all_outputs.append("NVLink clock is typically tied to core clock")
            commands.append("nvidia-smi --query-gpu=clocks.current.nvlink --format=csv,noheader,nounits")
        else:
            raise HTTPException(status_code=400, detail=f"Invalid clock type: {request.clock_type}")
        
        # Step 4: Execute commands
        all_outputs.append("\n=== Step 4: Executing Clock Commands ===")
        try:
            for cmd in commands:
                try:
                    output = run_ssh_command(instance, cmd, timeout=30)
                    all_outputs.append(f"Command: {cmd}")
                    all_outputs.append(f"Output: {output}")
                except Exception as e:
                    error_msg = f"Command failed: {cmd}\nError: {str(e)}"
                    error_messages.append(error_msg)
                    all_outputs.append(error_msg)
                    logger.error(error_msg)
            
            # Step 5: Verify the change (nvidia-smi -q -d CLOCK)
            all_outputs.append("\n=== Step 5: Verifying Clock Changes ===")
            try:
                verify_cmd = "nvidia-smi -q -d CLOCK"
                verify_output = run_ssh_command(instance, verify_cmd, timeout=10)
                all_outputs.append(verify_output)
                diagnostics["verification"] = verify_output
                
                # Extract Applications Clocks section
                if "Applications Clocks" in verify_output:
                    import re
                    app_clocks_section = re.search(r'Applications Clocks\s*\n(.*?)(?=\n\n|\nDefault|$)', verify_output, re.DOTALL)
                    if app_clocks_section:
                        app_clocks = app_clocks_section.group(1)
                        all_outputs.append(f"\nApplications Clocks:\n{app_clocks}")
                        diagnostics["applications_clocks"] = app_clocks
            except Exception as e:
                verify_output = f"Could not verify clock settings: {str(e)}"
                all_outputs.append(verify_output)
            
            # Step 6: Check for throttling reasons
            try:
                perf_cmd = "nvidia-smi -q -d PERFORMANCE | grep -A 10 'Throttle Reasons'"
                perf_output = run_ssh_command(instance, perf_cmd, timeout=10)
                diagnostics["throttle_reasons"] = perf_output
                if perf_output and "Active" in perf_output:
                    all_outputs.append(f"\nThrottling detected:\n{perf_output}")
            except Exception as e:
                logger.warning(f"Could not check throttling: {e}")
            
            # Check if there were errors
            if error_messages and len(error_messages) == len(commands):
                # All commands failed
                raise HTTPException(
                    status_code=500,
                    detail=f"All clock setting commands failed. GPU may not support clock adjustments or permissions may be insufficient. Errors: {'; '.join(error_messages)}"
                )
            
            return {
                "status": "success" if not error_messages else "partial",
                "message": f"Set {request.clock_type} clock to {request.clock_percent}% ({clock_mhz} MHz) on {gpu_count} GPU(s)",
                "clock_type": request.clock_type,
                "clock_percent": request.clock_percent,
                "clock_mhz": clock_mhz,
                "gpu_type": gpu_type,
                "gpu_count": gpu_count,
                "output": "\n".join(all_outputs),
                "diagnostics": diagnostics,
                "warnings": error_messages if error_messages else None
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to set clock via SSH: {str(e)}. Diagnostics: {json.dumps(diagnostics, indent=2)}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting GPU clock: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to set GPU clock: {str(e)}"
        )

@app.post("/api/setup-instance")
async def setup_instance(request: SetupInstanceRequest):
    """
    Run the h100_fp8.sh setup script on a remote instance via SSH.
    This script sets up the H100 system for LLM benchmarking.
    """
    try:
        # Handle PEM file - either use existing path, create from base64, or use saved file
        pem_file_path = None
        
        # First, try to use saved PEM file (by IP+user hash)
        import hashlib
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        temp_dir = os.path.join(backend_dir, "temp_pem")
        os.makedirs(temp_dir, exist_ok=True)  # Ensure directory exists
        pem_hash = hashlib.md5(f"{request.ip}_{request.ssh_user}".encode()).hexdigest()
        saved_pem_path = os.path.join(temp_dir, f"pem_{pem_hash}.pem")
        
        if os.path.exists(saved_pem_path):
            pem_file_path = saved_pem_path
            logger.info(f"Using saved PEM file: {pem_file_path}")
        elif request.pem_base64:
            # Decode base64 PEM content and save to temporary file
            import base64
            import tempfile
            
            try:
                # Handle data URL format if present
                pem_base64_clean = request.pem_base64
                if request.pem_base64.startswith('data:'):
                    comma_index = request.pem_base64.find(',')
                    if comma_index != -1:
                        pem_base64_clean = request.pem_base64[comma_index + 1:]
                pem_content = base64.b64decode(pem_base64_clean).decode('utf-8')
                
                # Create temporary PEM file
                temp_dir = os.path.join(os.path.dirname(__file__), "temp_pem")
                os.makedirs(temp_dir, exist_ok=True)
                
                # Generate unique filename based on IP and timestamp
                import hashlib
                pem_hash = hashlib.md5(f"{request.ip}_{request.ssh_user}".encode()).hexdigest()
                pem_file_path = os.path.join(temp_dir, f"pem_{pem_hash}.pem")
                
                # Write PEM content to file
                with open(pem_file_path, 'w', encoding='utf-8') as f:
                    f.write(pem_content)
                
                # Set secure permissions (required by SSH)
                os.chmod(pem_file_path, 0o400)
                
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to decode PEM file: {str(e)}"
                )
        elif request.pem_path:
            # Use provided PEM file path
            pem_file_path = os.path.expanduser(request.pem_path)
            if not os.path.exists(pem_file_path):
                # If it's just a filename, check for saved PEM file
                if not os.path.dirname(request.pem_path) and os.path.exists(saved_pem_path):
                    pem_file_path = saved_pem_path
                    logger.info(f"Using saved PEM file for filename: {request.pem_path}")
                else:
                    # If it's just a filename, provide a helpful error
                    if not os.path.dirname(request.pem_path):
                        raise HTTPException(
                            status_code=404,
                            detail=f"PEM file not found: {request.pem_path}. Please upload the PEM file first or provide the full path."
                        )
                    else:
                        raise HTTPException(
                            status_code=404,
                            detail=f"PEM file not found: {pem_file_path}. Please check the file path or upload PEM via frontend."
                        )
        else:
            # If no pem_path or pem_base64, but we have a saved file, use it
            if os.path.exists(saved_pem_path):
                pem_file_path = saved_pem_path
                logger.info(f"Using saved PEM file (no parameters provided)")
            else:
                raise HTTPException(
                    status_code=400,
                    detail="PEM file not found. Please upload the PEM file first or provide pem_path (full path) or pem_base64."
                )
        
        # Ensure PEM file has correct permissions before SSH (required by SSH)
        if pem_file_path and os.path.exists(pem_file_path):
            try:
                os.chmod(pem_file_path, 0o400)  # Read-only for owner
                logger.debug(f"Set PEM file permissions before setup: {pem_file_path}")
            except Exception as e:
                logger.warning(f"Failed to set PEM file permissions: {e}")
        
        # Create instance dict for SSH command
        instance = {
            "ip": request.ip,
            "username": request.ssh_user,
            "pem_file": pem_file_path
        }
        
        all_outputs = []
        
        # Determine script path
        # If script_path is provided, use it; otherwise upload and run the script
        script_path = request.script_path
        
        if not script_path:
            # Upload the h100_fp8.sh script to the remote instance
            local_script_path = os.path.join(os.path.dirname(__file__), "h100_fp8_general.sh")
            
            if not os.path.exists(local_script_path):
                raise HTTPException(
                    status_code=404,
                    detail=f"Setup script not found at {local_script_path}"
                )
            
            # Read the script content with UTF-8 encoding
            with open(local_script_path, 'r', encoding='utf-8') as f:
                script_content = f.read()
            
            # Create a temporary file on the remote instance
            remote_script_path = "/tmp/h100_fp8_setup.sh"
            
            # Upload script via SSH (using echo and redirect)
            # Split into chunks to avoid command line length limits
            import base64
            script_b64 = base64.b64encode(script_content.encode()).decode()
            
            upload_cmd = f"echo '{script_b64}' | base64 -d > {remote_script_path} && chmod +x {remote_script_path}"
            try:
                upload_output = run_ssh_command(instance, upload_cmd, timeout=30)
                all_outputs.append(f"Script uploaded: {upload_output}")
                script_path = remote_script_path
            except Exception as e:
                # Alternative: use heredoc
                script_escaped = script_content.replace("'", "'\"'\"'")
                upload_cmd = f"cat > {remote_script_path} << 'SCRIPT_EOF'\n{script_content}\nSCRIPT_EOF\nchmod +x {remote_script_path}"
                upload_output = run_ssh_command(instance, upload_cmd, timeout=30)
                all_outputs.append(f"Script uploaded (alternative method): {upload_output}")
                script_path = remote_script_path
        
        # Run the setup script
        all_outputs.append(f"\n=== Running Setup Script: {script_path} ===")
        
        # Run script in background and capture output
        # Use nohup to keep it running even if SSH disconnects
        run_cmd = f"nohup bash {script_path} > /tmp/h100_setup.log 2>&1 & echo $!"
        try:
            pid_output = run_ssh_command(instance, run_cmd, timeout=10)
            pid = pid_output.strip()
            all_outputs.append(f"Setup script started with PID: {pid}")
            
            # Wait a bit and check status
            import time
            time.sleep(2)
            
            # Check if process is still running
            check_cmd = f"ps -p {pid} > /dev/null 2>&1 && echo 'running' || echo 'finished'"
            status = run_ssh_command(instance, check_cmd, timeout=5)
            all_outputs.append(f"Process status: {status.strip()}")
            
            # Get initial log output
            log_cmd = "tail -50 /tmp/h100_setup.log 2>/dev/null || echo 'Log file not yet created'"
            log_output = run_ssh_command(instance, log_cmd, timeout=5)
            all_outputs.append(f"\nInitial log output:\n{log_output}")
            
            return {
                "status": "started",
                "message": f"Setup script started on instance",
                "pid": pid,
                "script_path": script_path,
                "log_file": "/tmp/h100_setup.log",
                "output": "\n".join(all_outputs),
                "instructions": "The setup script is running in the background. Check the log file for progress."
            }
            
        except Exception as e:
            # Try running synchronously with timeout
            all_outputs.append(f"\nTrying synchronous execution (this may take several minutes)...")
            run_cmd = f"bash {script_path}"
            try:
                output = run_ssh_command(instance, run_cmd, timeout=1800)  # 30 minute timeout
                all_outputs.append(output)
                return {
                    "status": "success",
                    "message": "Setup script completed successfully",
                    "output": "\n".join(all_outputs)
                }
            except Exception as e2:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to run setup script: {str(e2)}. Initial error: {str(e)}"
                )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting up instance: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to setup instance: {str(e)}"
        )

@app.get("/api/setup-instance/status")
async def get_setup_status(
    ip: str = Query(..., description="IP address"),
    ssh_user: str = Query("ubuntu", description="SSH username"),
    pem_path: Optional[str] = Query(None, description="Path to PEM file"),
    pem_base64: Optional[str] = Query(None, description="Base64-encoded PEM content"),
    pid: Optional[str] = Query(None, description="Process ID to check")
):
    """Setup status stub (not implemented)."""
    return {"status": "not_implemented"}

@app.post("/api/setup-instance/save-pem")
async def save_pem_file(
    ip: str = Body(..., description="IP address"),
    ssh_user: str = Body("ubuntu", description="SSH username"),
    pem_base64: str = Body(..., description="Base64-encoded PEM content")
):
    """Save PEM stub (not implemented)."""
    return {"status": "not_implemented"}

@app.get("/api/setup-instance/check")
async def check_setup_complete(
    ip: str = Query(..., description="IP address"),
    ssh_user: str = Query("ubuntu", description="SSH username"),
    pem_path: Optional[str] = Query(None, description="Path to PEM file"),
    pem_base64: Optional[str] = Query(None, description="Base64-encoded PEM content (for POST requests)")
):
    """Setup completion stub (not implemented)."""
    return {"status": "not_implemented"}
# ============================================================================
# OPENTOFU (TERRAFORM) INTEGRATION FOR AWS
# ============================================================================

def create_aws_tofu_config(instance_name: str, instance_type: str, region: str, 
                          ssh_key_name: Optional[str] = None, 
                          ssh_public_key: Optional[str] = None,
                          image_id: Optional[str] = None) -> str:
    """Create OpenTofu configuration for AWS EC2 instance"""
    # Default GPU-enabled AMI (Deep Learning AMI)
    ami_id = image_id or "ami-0c02fb55956c7d316"  # Default Ubuntu GPU AMI (update as needed)
    
    config = f'''terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region = "{region}"
}}

resource "aws_instance" "{instance_name}" {{
  ami           = "{ami_id}"
  instance_type = "{instance_type}"
  
  tags = {{
    Name = "{instance_name}"
    ManagedBy = "Omniference"
  }}
'''
    
    if ssh_key_name:
        config += f'  key_name = "{ssh_key_name}"\n'
    
    if ssh_public_key:
        config += f'''  root_block_device {{
    volume_size = 100
    volume_type = "gp3"
  }}
  
  user_data = <<-EOF
    #!/bin/bash
    echo "{ssh_public_key}" >> /home/ubuntu/.ssh/authorized_keys
    chmod 600 /home/ubuntu/.ssh/authorized_keys
    chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys
  EOF
'''
    
    config += "}\n\n"
    config += f'''output "instance_id" {{
  value = aws_instance.{instance_name}.id
}}

output "public_ip" {{
  value = aws_instance.{instance_name}.public_ip
}}

output "private_ip" {{
  value = aws_instance.{instance_name}.private_ip
}}
'''
    return config

def run_tofu_command(work_dir: str, command: str, env_vars: Dict[str, str] = None) -> Tuple[str, str, int]:
    """Run OpenTofu command in specified working directory"""
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)
    
    # Check if OpenTofu is installed
    try:
        result = subprocess.run(["tofu", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            raise FileNotFoundError("OpenTofu not found")
    except FileNotFoundError:
        # Try terraform as fallback
        try:
            result = subprocess.run(["terraform", "--version"], capture_output=True, text=True, timeout=5)
            tofu_cmd = "terraform"
        except FileNotFoundError:
            raise RuntimeError("Neither OpenTofu nor Terraform found. Please install OpenTofu.")
    else:
        tofu_cmd = "tofu"
    
    # Split command into parts
    cmd_parts = command.split()
    full_cmd = [tofu_cmd] + cmd_parts
    
    result = subprocess.run(
        full_cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        env=env,
        timeout=300
    )
    
    return result.stdout, result.stderr, result.returncode

@app.post("/api/tofu/instance/create")
async def create_tofu_instance(request: TofuInstanceRequest):
    """Create an instance using OpenTofu for AWS"""
    try:
        # Create workspace directory
        workspace_id = f"{request.provider}_{request.instance_name}_{int(time.time())}"
        work_dir = os.path.join(TOFU_WORK_DIR, workspace_id)
        os.makedirs(work_dir, exist_ok=True)
        
        # Generate OpenTofu configuration
        if request.provider == "aws":
            config_content = create_aws_tofu_config(
                request.instance_name,
                request.instance_type,
                request.region,
                request.ssh_key_name,
                request.ssh_public_key,
                request.image_id
            )
            # Set AWS credentials
            env_vars = {}
            if "aws_access_key_id" in request.credentials:
                env_vars["AWS_ACCESS_KEY_ID"] = request.credentials["aws_access_key_id"]
            if "aws_secret_access_key" in request.credentials:
                env_vars["AWS_SECRET_ACCESS_KEY"] = request.credentials["aws_secret_access_key"]
            if "aws_session_token" in request.credentials:
                env_vars["AWS_SESSION_TOKEN"] = request.credentials["aws_session_token"]
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported provider: {request.provider}")
        
        # Write configuration file
        config_file = os.path.join(work_dir, "main.tf")
        with open(config_file, "w") as f:
            f.write(config_content)
        
        # Initialize OpenTofu
        stdout, stderr, rc = run_tofu_command(work_dir, "init", env_vars)
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"OpenTofu init failed: {stderr}")
        
        # Plan (optional - can skip for faster creation)
        # stdout, stderr, rc = run_tofu_command(work_dir, "plan -out=tfplan", env_vars)
        
        # Apply configuration
        stdout, stderr, rc = run_tofu_command(work_dir, "apply -auto-approve", env_vars)
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"OpenTofu apply failed: {stderr}")
        
        # Get outputs
        stdout, stderr, rc = run_tofu_command(work_dir, "output -json", env_vars)
        outputs = {}
        if rc == 0:
            try:
                outputs = json.loads(stdout)
            except:
                pass
        
        return {
            "status": "success",
            "message": f"Instance {request.instance_name} created successfully",
            "workspace_id": workspace_id,
            "provider": request.provider,
            "outputs": outputs,
            "stdout": stdout
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating OpenTofu instance: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create instance: {str(e)}"
        )

@app.post("/api/tofu/instance/destroy/{workspace_id}")
async def destroy_tofu_instance(workspace_id: str, credentials: Dict[str, Any] = Body(...)):
    """Destroy an instance using OpenTofu"""
    try:
        work_dir = os.path.join(TOFU_WORK_DIR, workspace_id)
        if not os.path.exists(work_dir):
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")
        
        # Set credentials based on provider (detect from workspace or config)
        env_vars = {}
        if "aws_access_key_id" in credentials:
            env_vars["AWS_ACCESS_KEY_ID"] = credentials["aws_access_key_id"]
            env_vars["AWS_SECRET_ACCESS_KEY"] = credentials.get("aws_secret_access_key", "")
        # Destroy resources
        stdout, stderr, rc = run_tofu_command(work_dir, "destroy -auto-approve", env_vars)
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"OpenTofu destroy failed: {stderr}")
        
        return {
            "status": "success",
            "message": f"Instance destroyed successfully",
            "workspace_id": workspace_id,
            "stdout": stdout
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error destroying OpenTofu instance: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to destroy instance: {str(e)}"
        )

@app.get("/api/tofu/instance/list")
async def list_tofu_instances():
    """List all OpenTofu workspaces"""
    try:
        workspaces = []
        if os.path.exists(TOFU_WORK_DIR):
            for workspace_id in os.listdir(TOFU_WORK_DIR):
                work_dir = os.path.join(TOFU_WORK_DIR, workspace_id)
                if os.path.isdir(work_dir):
                    # Try to get state info
                    state_file = os.path.join(work_dir, "terraform.tfstate")
                    state_info = {}
                    if os.path.exists(state_file):
                        try:
                            with open(state_file, "r") as f:
                                state = json.load(f)
                                if "outputs" in state:
                                    state_info = state["outputs"]
                        except:
                            pass
                    
                    workspaces.append({
                        "workspace_id": workspace_id,
                        "state": state_info
                    })
        
        return {
            "status": "success",
            "workspaces": workspaces,
            "count": len(workspaces)
        }
    except Exception as e:
        logger.error(f"Error listing OpenTofu workspaces: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list workspaces: {str(e)}"
        )

# ============================================================================
# LAMBDA CLOUD API INTEGRATION ENDPOINTS
# ============================================================================

async def _get_lambda_api_key_from_user(request: Optional["Request"] = None) -> Optional[str]:
    """Get the user's Lambda API key from stored credentials."""
    logger.info("_get_lambda_api_key_from_user called")
    try:
        if not request:
            logger.warning("No request object provided to _get_lambda_api_key_from_user")
            return None
        
        authorization = request.headers.get("Authorization")
        logger.info(f"Authorization header present: {authorization is not None}")
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("No valid Authorization header found")
            return None
        
        token = authorization.split(" ")[1]
        logger.info(f"Token extracted, length: {len(token)}")
        from telemetry.auth import decode_access_token
        from telemetry.db import async_session
        from telemetry.models import User
        from telemetry.repository import TelemetryRepository
        from sqlalchemy import select
        from uuid import UUID
        
        payload = decode_access_token(token)
        logger.info(f"Token decode result: {payload is not None}")
        if not payload:
            logger.warning("Token decode failed")
            return None
        
        user_id_str = payload.get("sub")
        logger.info(f"User ID from token: {user_id_str}")
        if not user_id_str:
            logger.warning("No user_id in token payload")
            return None
        
        try:
            user_id = UUID(user_id_str)
            logger.info(f"Parsed user_id: {user_id}")
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid user_id in token: {e}")
            return None
        
        async with async_session() as session:
            stmt = select(User).where(User.user_id == user_id)
            result = await session.execute(stmt)
            current_user = result.scalar_one_or_none()
            if not current_user:
                logger.warning(f"User not found for user_id: {user_id}")
                return None
            
            logger.info(f"User found: {current_user.email}")
            repo = TelemetryRepository(session)
            credentials = await repo.list_credentials(
                user_id=current_user.user_id,
                provider="lambda",
                credential_type="api_key"
            )
            
            logger.info(f"Found {len(credentials)} Lambda credentials for user {current_user.user_id}")
            if not credentials:
                logger.warning(f"No Lambda credentials found for user {current_user.user_id}")
                return None
            
            default_cred = next((c for c in credentials if c.name == "default"), credentials[0])
            secret = await repo.get_credential_secret(default_cred)
            logger.info(f"Retrieved Lambda API key for user {current_user.user_id}, secret length: {len(secret) if secret else 0}")
            return secret
            
    except Exception as e:
        logger.error(f"Failed to get user Lambda API key: {e}", exc_info=True)
        return None

async def resolve_lambda_api_key(request: Optional[Request], header_api_key: Optional[str]) -> str:
    """
    Resolve Lambda API key from header, user credentials, or environment.
    Priority: header -> user credential -> env.
    """
    if header_api_key:
        return header_api_key
    
    user_key = await _get_lambda_api_key_from_user(request)
    if user_key:
        return user_key
    
    if LAMBDA_API_KEY:
        return LAMBDA_API_KEY
    
    raise HTTPException(
        status_code=400,
        detail="Lambda API key not provided. Set X-Lambda-API-Key header or configure credentials."
    )

@app.get("/api/v1/lambda-cloud/instances")
async def list_lambda_instances(
    request: Request,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """Proxy to Lambda Cloud API to list instances."""
    api_key = await resolve_lambda_api_key(request, x_lambda_api_key)
    return await make_lambda_api_request("instances", api_key_override=api_key)

@app.get("/api/v1/lambda-cloud/instances/{instance_id}")
async def get_lambda_instance(
    instance_id: str,
    request: Request,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """Proxy to Lambda Cloud API to get a single instance."""
    api_key = await resolve_lambda_api_key(request, x_lambda_api_key)
    return await make_lambda_api_request(f"instances/{instance_id}", api_key_override=api_key)

@app.get("/api/v1/lambda-cloud/instance-types")
async def list_lambda_instance_types(
    request: Request,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """Proxy to Lambda Cloud API to list instance types."""
    api_key = await resolve_lambda_api_key(request, x_lambda_api_key)
    return await make_lambda_api_request("instance-types", api_key_override=api_key)

@app.get("/api/v1/lambda-cloud/regions")
async def list_lambda_regions(
    request: Request,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """Proxy to Lambda Cloud API to list regions. Fallback: derive regions from instance types if /regions is unavailable."""
    api_key = await resolve_lambda_api_key(request, x_lambda_api_key)
    try:
        return await make_lambda_api_request("regions", api_key_override=api_key)
    except HTTPException as e:
        # If the regions endpoint is not available, synthesize regions from instance types
        if e.status_code == 404:
            try:
                types_resp = await make_lambda_api_request("instance-types", api_key_override=api_key)
                types_data = (
                    types_resp.get("instance_types")
                    or types_resp.get("data", {}).get("instance_types")
                    or types_resp.get("data")
                    or {}
                )
                regions_map: Dict[str, Dict[str, Any]] = {}
                if isinstance(types_data, dict):
                    iterator = types_data.values()
                elif isinstance(types_data, list):
                    iterator = types_data
                else:
                    iterator = []
                for entry in iterator:
                    regions = entry.get("regions") or entry.get("regions_with_capacity_available") or []
                    for reg in regions:
                        name = reg.get("name") if isinstance(reg, dict) else reg
                        if not name:
                            continue
                        desc = reg.get("description") if isinstance(reg, dict) else None
                        regions_map[name] = {"name": name, "description": desc} if desc else {"name": name}
                return {"regions": list(regions_map.values())}
            except Exception as fallback_error:
                logger.error(f"Failed to synthesize Lambda regions from instance types: {fallback_error}", exc_info=True)
                raise HTTPException(
                    status_code=502,
                    detail="Lambda Cloud regions endpoint unavailable and fallback synthesis failed."
                )
        raise

@app.post("/api/v1/lambda-cloud/instance-operations/launch")
async def lambda_launch_instance(
    payload: Dict[str, Any] = Body(...),
    request: Request = None,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """Launch Lambda instance via Lambda Cloud API."""
    api_key = await resolve_lambda_api_key(request, x_lambda_api_key)
    return await make_lambda_api_request("instance-operations/launch", method="POST", data=payload, api_key_override=api_key)

@app.get("/api/v1/lambda-cloud/ssh-keys")
async def lambda_list_ssh_keys(
    request: Request,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """List Lambda SSH keys via Lambda Cloud API."""
    api_key = await resolve_lambda_api_key(request, x_lambda_api_key)
    return await make_lambda_api_request("ssh-keys", api_key_override=api_key)

@app.post("/api/v1/lambda-cloud/ssh-keys")
async def lambda_create_ssh_key(
    payload: Dict[str, Any] = Body(...),
    request: Request = None,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """Create Lambda SSH key via Lambda Cloud API."""
    api_key = await resolve_lambda_api_key(request, x_lambda_api_key)
    return await make_lambda_api_request("ssh-keys", method="POST", data=payload, api_key_override=api_key)

@app.delete("/api/v1/lambda-cloud/ssh-keys/{key_id}")
async def lambda_delete_ssh_key(
    key_id: str,
    request: Request,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """Delete Lambda SSH key via Lambda Cloud API."""
    api_key = await resolve_lambda_api_key(request, x_lambda_api_key)
    return await make_lambda_api_request(f"ssh-keys/{key_id}", method="DELETE", api_key_override=api_key)

@app.get("/api/v1/lambda-cloud/health")
async def check_lambda_api_health(
    request: Request,
    x_lambda_api_key: Optional[str] = Header(None, alias="X-Lambda-API-Key")
):
    """
    Check if Lambda Cloud API is configured and reachable.
    """
    return {
        "api_key_configured": bool(LAMBDA_API_KEY),
        "api_key_present": bool(LAMBDA_API_KEY),
        "api_key_last4": f"...{LAMBDA_API_KEY[-4:]}" if LAMBDA_API_KEY else None
    }

@app.get("/api/v1/lambda-cloud/config")
async def get_lambda_api_config():
    """
    Get Lambda Cloud API configuration status.
    Returns configuration status (does not expose the actual API key).
    """
    return {
        "api_key_configured": bool(LAMBDA_API_KEY),
        "api_base_url": LAMBDA_API_BASE_URL,
        "endpoints": {
            "instances": f"{LAMBDA_API_BASE_URL}/instances",
            "instance_types": f"{LAMBDA_API_BASE_URL}/instance-types",
            "regions": f"{LAMBDA_API_BASE_URL}/regions"
        }
    }

# ============================================================================
# UNIFIED INSTANCES API - Aggregated View
# ============================================================================

class UnifiedInstance(BaseModel):
    """Normalized instance structure across all cloud providers."""
    id: str
    name: Optional[str] = None
    provider: str  # "lambda", "nebius", "scaleway"
    instance_type: str  # Normalized instance type name
    gpu_model: Optional[str] = None  # e.g., "H100", "A100", "L4"
    num_gpus: Optional[int] = None
    vcpus: Optional[int] = None
    memory_gb: Optional[float] = None
    status: str  # Normalized: "running", "stopped", "pending", etc.
    availability: Optional[str] = None  # "available", "out_of_stock", "quota_required"
    public_ip: Optional[str] = None
    private_ip: Optional[str] = None
    region: Optional[str] = None
    zone: Optional[str] = None
    cost_per_hour_usd: Optional[float] = None
    cost_per_month_usd: Optional[float] = None
    created_at: Optional[str] = None
    raw: Dict[str, Any]  # Original provider data for reference


class UnifiedCatalogItem(BaseModel):
    """Normalized 'available instance type / preset / product' structure across providers."""
    id: str
    provider: str  # "lambda", "nebius", "scaleway"
    name: str
    description: Optional[str] = None
    gpu_model: Optional[str] = None
    num_gpus: Optional[int] = None
    vcpus: Optional[int] = None
    memory_gb: Optional[float] = None
    storage_gb: Optional[float] = None
    availability: Optional[str] = None
    regions: List[str] = []
    cost_per_hour_usd: Optional[float] = None
    cost_per_month_usd: Optional[float] = None
    raw: Dict[str, Any]


class MigrationRequest(BaseModel):
    """Request to migrate workload from a source instance to a target instance type."""
    source_provider: str
    source_instance_id: str
    source_zone: Optional[str] = None
    target_provider: str
    target_payload: Dict[str, Any]
    target_region: Optional[str] = None
    target_zone: Optional[str] = None
    # Optional credentials for providers that require them (e.g., Scaleway)
    target_secret_key: Optional[str] = None
    target_project_id: Optional[str] = None



class MigrationResponse(BaseModel):
    target_provider: str
    target_instance_id: Optional[str] = None
    status: str
    detail: Optional[str] = None


def extract_gpu_info_from_name(name: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract GPU model and count from instance type name.
    
    Examples:
        "gpu_1x_h100" -> ("H100", 1)
        "gpu_2x_a100" -> ("A100", 2)
        "gpu_8x_a100_80gb_sxm4" -> ("A100", 8)
        "L4-1-24G" -> ("L4", 1)
        "H100-2-80G" -> ("H100", 2)
    """
    import re
    name_lower = name.lower()
    
    # Pattern 1: gpu_Nx_model format (Lambda)
    match = re.search(r'gpu_(\d+)x?_([a-z0-9]+)', name_lower)
    if match:
        count = int(match.group(1))
        model = match.group(2).upper()
        return model, count
    
    # Pattern 2: model-N-size format (Scaleway)
    match = re.search(r'([a-z][0-9]+)-(\d+)', name_lower)
    if match:
        model = match.group(1).upper()
        count = int(match.group(2))
        return model, count
    
    # Pattern 3: Look for common GPU names
    gpu_names = ['h100', 'h200', 'a100', 'a10', 'l4', 'l40', 'v100', 'p100', 't4']
    for gpu in gpu_names:
        if gpu in name_lower:
            # Try to find count
            count_match = re.search(rf'{gpu}.*?(\d+)', name_lower)
            if count_match:
                return gpu.upper(), int(count_match.group(1))
            return gpu.upper(), 1
    
    return None, None


def normalize_lambda_catalog_item(key: str, entry: Dict[str, Any]) -> UnifiedCatalogItem:
    instance_type = entry.get("instance_type") or {}
    specs = instance_type.get("specs") or {}
    regions = entry.get("regions_with_capacity_available") or entry.get("regions") or []
    region_names: List[str] = []
    for r in regions:
        if isinstance(r, str):
            region_names.append(r)
        elif isinstance(r, dict):
            name = r.get("name") or r.get("region") or r.get("id")
            if name:
                region_names.append(name)

    name = instance_type.get("name") or key
    gpu_model, num_gpus = extract_gpu_info_from_name(name)
    if instance_type.get("gpu_description") and not gpu_model:
        gpu_model, _ = extract_gpu_info_from_name(str(instance_type.get("gpu_description")))

    price_cents = instance_type.get("price_cents_per_hour")
    cost_per_hour = price_cents / 100.0 if isinstance(price_cents, (int, float)) else None

    availability = "available" if region_names else "no_capacity"

    return UnifiedCatalogItem(
        id=key,
        provider="lambda",
        name=name,
        description=instance_type.get("description") or instance_type.get("gpu_description"),
        gpu_model=gpu_model,
        num_gpus=num_gpus or specs.get("gpus"),
        vcpus=specs.get("vcpus"),
        memory_gb=specs.get("memory_gib"),
        storage_gb=specs.get("storage_gib"),
        availability=availability,
        regions=sorted(set(region_names)),
        cost_per_hour_usd=cost_per_hour,
        cost_per_month_usd=cost_per_hour * 730 if cost_per_hour else None,
        raw=entry,
    )


def normalize_nebius_catalog_item(preset: Dict[str, Any]) -> UnifiedCatalogItem:
    platform_id = preset.get("platform_id") or ""
    preset_id = preset.get("id") or preset.get("name") or ""
    item_id = f"{platform_id}:{preset_id}" if platform_id and preset_id else (preset_id or platform_id)

    name = preset.get("name") or preset_id or "Nebius preset"
    gpu_model, num_gpus = extract_gpu_info_from_name(name)
    if preset.get("platform_name") and not gpu_model:
        gpu_model, _ = extract_gpu_info_from_name(str(preset.get("platform_name")))

    regions = preset.get("platform_regions") or preset.get("platform_zones") or []
    region_names: List[str] = []
    if isinstance(regions, list):
        for r in regions:
            if isinstance(r, str):
                region_names.append(r)

    return UnifiedCatalogItem(
        id=item_id or name,
        provider="nebius",
        name=name,
        description=preset.get("platform_name"),
        gpu_model=gpu_model,
        num_gpus=num_gpus or preset.get("gpus"),
        vcpus=preset.get("vcpus"),
        memory_gb=preset.get("memory_gb"),
        storage_gb=None,
        availability="available" if region_names else None,
        regions=sorted(set(region_names)),
        cost_per_hour_usd=preset.get("hourly_cost_usd"),
        cost_per_month_usd=preset.get("monthly_cost_usd"),
        raw=preset,
    )


def _parse_price_like(value: Any) -> Optional[float]:
    """Parse common price shapes into a float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(value, dict):
        for key in ("price", "value", "amount"):
            if key in value:
                try:
                    return float(value[key])
                except Exception:
                    return None
        units = value.get("units")
        nanos = value.get("nanos")
        if units is not None:
            try:
                units_f = float(units)
                nanos_f = float(nanos) if nanos is not None else 0.0
                return units_f + nanos_f / 1e9
            except Exception:
                return None
    return None


def _scaleway_product_vcpus(product: Dict[str, Any]) -> Optional[int]:
    for key in ("vcpus", "ncpus", "vcpu_count", "cpu_count"):
        val = product.get(key)
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            try:
                return int(val)
            except Exception:
                continue
    return None


def _scaleway_product_ram_bytes(product: Dict[str, Any]) -> Optional[int]:
    for key in ("ram_bytes", "ram", "memory_bytes", "memory"):
        val = product.get(key)
        if isinstance(val, (int, float)) and val:
            return int(val)
        if isinstance(val, str):
            try:
                return int(float(val))
            except Exception:
                continue
    return None


def _scaleway_product_hourly_price_eur(product: Dict[str, Any]) -> Optional[float]:
    for key in ("hourly_price", "hourly_price_with_tax", "hourly_price_without_tax"):
        parsed = _parse_price_like(product.get(key))
        if parsed is not None:
            return parsed
    return None


def _scaleway_gpu_description_from_type(commercial_type: str) -> Optional[str]:
    """Build a Lambda-like description from Scaleway commercial types when possible."""
    import re

    ct = (commercial_type or "").strip()
    if not ct:
        return None

    m = re.search(r"(?i)\b([a-z]+[0-9]+)\b(?:-([a-z][a-z0-9]*))?-(\d+)-(\d+)g\b", ct)
    if not m:
        return None
    model, variant, count_str, mem_str = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        count = int(count_str)
        mem = int(mem_str)
    except Exception:
        return None
    suffix = f" {variant.upper()}" if variant else ""
    return f"{count}x {model.upper()} ({mem} GB{suffix})"


def normalize_scaleway_catalog_item(zone: str, commercial_type: str, product: Dict[str, Any]) -> Optional[UnifiedCatalogItem]:
    gpu_model, num_gpus = extract_gpu_info_from_name(commercial_type)
    product_gpus = product.get("gpu")
    if product_gpus is None:
        product_gpus = product.get("gpu_count")
    if isinstance(product_gpus, int) and product_gpus > 0:
        num_gpus = product_gpus

    if not num_gpus or num_gpus <= 0:
        return None

    # Extra safety: only include known GPU families for Scaleway catalogs.
    # (The products API includes many non-GPU server types.)
    known_gpu_models = {
        "B200",
        "GH200",
        "H200",
        "H100",
        "A100",
        "A10",
        "L40S",
        "L40",
        "L4",
        "V100",
        "T4",
        "MI300",
    }
    if gpu_model:
        normalized_model = str(gpu_model).upper()
        if normalized_model not in known_gpu_models:
            return None

    ram_bytes = _scaleway_product_ram_bytes(product)
    memory_gb = ram_bytes / (1024**3) if isinstance(ram_bytes, (int, float)) and ram_bytes else None

    # Convert EUR to USD (approximate rate: 1 EUR = 1.1 USD)
    cost_per_hour_eur = _scaleway_product_hourly_price_eur(product)
    cost_per_hour_usd = cost_per_hour_eur * 1.1 if isinstance(cost_per_hour_eur, (int, float)) else None

    availability_value = product.get("availability") or product.get("stock")
    availability_str = str(availability_value).lower() if availability_value is not None else ""
    is_available = availability_str in {"available", "in_stock", "in-stock", "in stock", "ok"}

    return UnifiedCatalogItem(
        id=f"{zone}:{commercial_type}",
        provider="scaleway",
        name=commercial_type,
        description=_scaleway_gpu_description_from_type(commercial_type),
        gpu_model=gpu_model,
        num_gpus=num_gpus,
        vcpus=_scaleway_product_vcpus(product),
        memory_gb=memory_gb,
        storage_gb=None,
        availability=("available" if is_available else (availability_value if availability_value is not None else None)),
        regions=[zone] if is_available else [],
        cost_per_hour_usd=cost_per_hour_usd,
        cost_per_month_usd=cost_per_hour_usd * 730 if cost_per_hour_usd else None,
        raw=product,
    )


def normalize_status(provider: str, status: str) -> str:
    """Normalize status strings across providers."""
    if not status:
        return "unknown"
    
    status_lower = status.lower()
    
    # Running states
    if status_lower in ['active', 'running', 'started', 'booting']:
        return "running"
    
    # Stopped states
    if status_lower in ['stopped', 'stopped_in_place', 'stopping']:
        return "stopped"
    
    # Pending states
    if status_lower in ['pending', 'booting', 'starting']:
        return "pending"
    
    # Error states
    if status_lower in ['error', 'unhealthy', 'failed']:
        return "error"
    
    # Terminated states
    if status_lower in ['terminated', 'deleted']:
        return "terminated"
    
    return status


def normalize_lambda_instance(instance: Dict[str, Any], instance_types_map: Dict[str, Any]) -> UnifiedInstance:
    """Normalize Lambda Labs instance to unified format."""
    instance_type_obj = instance.get("instance_type", {})
    instance_type_name = instance_type_obj.get("name", "") if isinstance(instance_type_obj, dict) else str(instance_type_obj)
    
    # Extract GPU info from instance type name
    gpu_model, num_gpus = extract_gpu_info_from_name(instance_type_name)
    
    # Try to get more details from instance_types_map
    instance_type_details = instance_types_map.get(instance_type_name, {})
    
    # Extract pricing if available
    cost_per_hour = None
    if instance_type_details:
        price_cents = instance_type_details.get("price_cents_per_hour")
        if price_cents:
            cost_per_hour = price_cents / 100.0
    
    # Get region info
    region_obj = instance.get("region", {})
    region_name = region_obj.get("name") if isinstance(region_obj, dict) else str(region_obj) if region_obj else None
    
    # Get IP
    ip = instance.get("ip") or instance.get("public_ip")
    
    # Get status
    status_obj = instance.get("status", {})
    status_state = status_obj.get("state") if isinstance(status_obj, dict) else str(status_obj)
    
    return UnifiedInstance(
        id=instance.get("id", ""),
        name=instance.get("name"),
        provider="lambda",
        instance_type=instance_type_name,
        gpu_model=gpu_model,
        num_gpus=num_gpus,
        vcpus=instance_type_details.get("vcpus"),
        memory_gb=instance_type_details.get("memory_gib"),
        status=normalize_status("lambda", status_state or ""),
        availability=None,  # Lambda instances are already running
        public_ip=ip,
        private_ip=None,
        region=region_name,
        zone=None,
        cost_per_hour_usd=cost_per_hour,
        cost_per_month_usd=cost_per_hour * 730 if cost_per_hour else None,
        created_at=None,
        raw=instance
    )


def normalize_nebius_instance(instance: Dict[str, Any], presets_map: Dict[str, Any]) -> UnifiedInstance:
    """Normalize Nebius instance to unified format."""
    instance_type = instance.get("instance_type", "")
    
    # Get preset details
    preset = presets_map.get(instance_type, {})
    
    # Extract GPU info from preset
    gpu_model = None
    num_gpus = preset.get("gpus", 0)
    
    # Try to extract GPU model from instance_type or preset name
    if instance_type:
        gpu_model, detected_gpus = extract_gpu_info_from_name(instance_type)
        if detected_gpus:
            num_gpus = detected_gpus
    
    if not gpu_model and preset.get("name"):
        gpu_model, _ = extract_gpu_info_from_name(preset.get("name", ""))
    
    return UnifiedInstance(
        id=instance.get("id", ""),
        name=instance.get("name"),
        provider="nebius",
        instance_type=instance_type,
        gpu_model=gpu_model,
        num_gpus=num_gpus if num_gpus > 0 else None,
        vcpus=preset.get("vcpus"),
        memory_gb=preset.get("memory_gb"),
        status=normalize_status("nebius", instance.get("status", "")),
        availability=None,  # Nebius instances are already running
        public_ip=instance.get("public_ip"),
        private_ip=instance.get("private_ip"),
        region=None,
        zone=instance.get("zone"),
        cost_per_hour_usd=preset.get("hourly_cost_usd"),
        cost_per_month_usd=preset.get("monthly_cost_usd"),
        created_at=instance.get("created_at"),
        raw=instance
    )


def normalize_scaleway_instance(instance: Dict[str, Any], products_map: Dict[str, Any]) -> UnifiedInstance:
    """Normalize Scaleway instance to unified format."""
    commercial_type = instance.get("commercial_type", "")
    
    # Get product details
    product = products_map.get(commercial_type, {})
    
    # Extract GPU info
    gpu_model, num_gpus = extract_gpu_info_from_name(commercial_type)
    
    # Use product data if available
    if product:
        product_gpus = product.get("gpu")
        if product_gpus is None:
            product_gpus = product.get("gpu_count")
        if product_gpus:
            num_gpus = product_gpus
    
    # Convert EUR to USD (approximate rate: 1 EUR = 1.1 USD)
    cost_per_hour_eur = _scaleway_product_hourly_price_eur(product)
    cost_per_hour_usd = cost_per_hour_eur * 1.1 if cost_per_hour_eur else None
    
    # RAM bytes to GB
    ram_bytes = _scaleway_product_ram_bytes(product)
    memory_gb = ram_bytes / (1024**3) if ram_bytes else None
    
    # Extract public IP - try multiple methods (same as /api/scaleway/instances endpoint)
    public_ip = None
    private_ip = instance.get("private_ip")
    
    # Method 1: Check public_ip object (most common)
    public_ip_obj = instance.get("public_ip")
    if public_ip_obj:
        if isinstance(public_ip_obj, dict):
            public_ip = public_ip_obj.get("address") or public_ip_obj.get("id")
        elif isinstance(public_ip_obj, str):
            public_ip = public_ip_obj
    
    # Method 2: Check direct ip field
    if not public_ip:
        public_ip = instance.get("ip")
    
    # Method 3: Check public_ips array
    if not public_ip and instance.get("public_ips"):
        public_ips_array = instance.get("public_ips") or []
        for entry in public_ips_array:
            if isinstance(entry, dict):
                public_ip = entry.get("address") or entry.get("id")
                if public_ip:
                    break
            elif isinstance(entry, str):
                public_ip = entry
                break
    
    # Method 4: Check for IP in raw network interfaces
    if not public_ip and instance.get("public_ip_address"):
        addr = instance.get("public_ip_address")
        if isinstance(addr, dict):
            public_ip = addr.get("address")
        elif isinstance(addr, str):
            public_ip = addr
    
    return UnifiedInstance(
        id=instance.get("id", ""),
        name=instance.get("name"),
        provider="scaleway",
        instance_type=commercial_type,
        gpu_model=gpu_model,
        num_gpus=num_gpus,
        vcpus=_scaleway_product_vcpus(product),
        memory_gb=memory_gb,
        status=normalize_status("scaleway", instance.get("status") or instance.get("state", "")),
        availability=product.get("availability") or product.get("stock"),
        public_ip=public_ip,
        private_ip=private_ip,
        region=None,
        zone=instance.get("zone"),
        cost_per_hour_usd=cost_per_hour_usd,
        cost_per_month_usd=cost_per_hour_usd * 730 if cost_per_hour_usd else None,
        created_at=instance.get("created_at"),
        raw=instance
    )

SCW_ZONES = [
    "fr-par-1",
    "fr-par-2",
    "fr-par-3",
    "nl-ams-1",
    "nl-ams-2",
    "nl-ams-3",
    "pl-waw-1",
    "pl-waw-2",
    "pl-waw-3",
]


@app.get("/api/instances/aggregated", response_model=List[UnifiedInstance])
async def get_aggregated_instances(
    request: Request
):
    """
    Get aggregated instances from all configured cloud providers.
    
    Fetches instances from Lambda Labs, Nebius, and Scaleway in parallel,
    normalizes them to a unified format, and returns a combined list.
    
    Returns instances only from providers that have valid credentials configured.
    If a provider fails, it will be skipped and an error will be logged.
    """
    try:
        # Extract user from request token
        from telemetry.auth import decode_access_token
        from telemetry.db import get_session
        from telemetry.models import User
        from telemetry.repository import TelemetryRepository
        from sqlalchemy import select
        from uuid import UUID
        
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
        
        token = auth_header.split(" ")[1]
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        
        # Get current user
        async for session in get_session():
            stmt = select(User).where(User.user_id == UUID(user_id_str))
            result = await session.execute(stmt)
            current_user = result.scalar_one_or_none()
            if not current_user:
                raise HTTPException(status_code=401, detail="User not found")
            if not current_user.is_active:
                raise HTTPException(status_code=403, detail="User account is inactive")
            break
        
        # Fetch credentials for all providers within session context
        lambda_api_key = None
        nebius_creds = None
        scaleway_creds = None
        
        async for session in get_session():
            repo = TelemetryRepository(session)
            
            # Fetch Lambda credentials
            try:
                lambda_creds = await repo.list_credentials(
                    user_id=current_user.user_id,
                    provider="lambda",
                    credential_type="api_key"
                )
                if lambda_creds:
                    cred = lambda_creds[0]
                    secret = await repo.get_credential_secret(cred)
                    lambda_api_key = secret if isinstance(secret, str) else secret.get("apiKey") or secret.get("api_key")
            except Exception as e:
                logger.debug(f"Failed to fetch Lambda credentials: {e}")
            
            # Fetch Nebius credentials
            try:
                nebius_creds_list = await repo.list_credentials(
                    user_id=current_user.user_id,
                    provider="nebius",
                    credential_type="service_account"
                )
                if nebius_creds_list:
                    cred = nebius_creds_list[0]
                    secret = await repo.get_credential_secret(cred)
                    secret_data = json.loads(secret) if isinstance(secret, str) else secret
                    project_id = secret_data.get("projectId") or secret_data.get("project_id")
                    service_account_id = secret_data.get("serviceAccountId") or secret_data.get("service_account_id")
                    key_id = secret_data.get("keyId") or secret_data.get("key_id")
                    private_key = secret_data.get("secretKey") or secret_data.get("secret_key") or secret_data.get("privateKey") or secret_data.get("private_key")
                    
                    if all([project_id, service_account_id, key_id, private_key]):
                        nebius_creds = {
                            "project_id": project_id,
                            "service_account_id": service_account_id,
                            "key_id": key_id,
                            "private_key": private_key
                        }
            except Exception as e:
                logger.debug(f"Failed to fetch Nebius credentials: {e}")
            
            # Fetch Scaleway credentials
            try:
                scaleway_creds_list = await repo.list_credentials(
                    user_id=current_user.user_id,
                    provider="scaleway",
                    credential_type="access_key"
                )
                if scaleway_creds_list:
                    cred = scaleway_creds_list[0]
                    secret = await repo.get_credential_secret(cred)
                    secret_data = json.loads(secret) if isinstance(secret, str) else secret
                    secret_key = secret_data.get("secretKey") or secret_data.get("secret_key") or secret
                    project_id = secret_data.get("projectId") or secret_data.get("project_id")
                    
                    if secret_key:
                        scaleway_creds = {
                            "secret_key": secret_key,
                            "project_id": project_id
                        }
            except Exception as e:
                logger.debug(f"Failed to fetch Scaleway credentials: {e}")
            
            break  # Exit after first iteration
        
        # Now fetch instances from all providers in parallel (outside session context)
        async def fetch_lambda():
            if not lambda_api_key:
                return []
            try:
                instances_resp, types_resp = await asyncio.gather(
                    make_lambda_api_request("instances", api_key_override=lambda_api_key),
                    make_lambda_api_request("instance-types", api_key_override=lambda_api_key),
                    return_exceptions=True
                )
                
                if isinstance(instances_resp, Exception):
                    logger.error(f"Lambda instances fetch failed: {instances_resp}")
                    return []
                if isinstance(types_resp, Exception):
                    logger.warning(f"Lambda instance types fetch failed: {types_resp}")
                    types_resp = {}
                
                instances_data = instances_resp.get("data", {})
                instances_list = []
                if isinstance(instances_data, dict):
                    instances_list = list(instances_data.values()) if instances_data else []
                elif isinstance(instances_data, list):
                    instances_list = instances_data
                
                types_data = types_resp.get("data", {}) if types_resp else {}
                instance_types_map = {}
                if isinstance(types_data, dict):
                    for key, value in types_data.items():
                        if isinstance(value, dict):
                            instance_type = value.get("instance_type", {})
                            if instance_type:
                                type_name = instance_type.get("name", key)
                                instance_types_map[type_name] = instance_type
                
                normalized = []
                for inst in instances_list:
                    try:
                        normalized.append(normalize_lambda_instance(inst, instance_types_map))
                    except Exception as e:
                        logger.error(f"Error normalizing Lambda instance: {e}")
                
                logger.info(f"Fetched {len(normalized)} Lambda instances")
                return normalized
            except Exception as e:
                logger.error(f"Lambda fetch error: {e}", exc_info=True)
                return []
        
        async def fetch_nebius():
            if not nebius_creds:
                return []
            try:
                from managers.nebius_manager import NebiusManager
                
                creds_payload = {
                    "service_account_id": nebius_creds["service_account_id"],
                    "key_id": nebius_creds["key_id"],
                    "private_key": nebius_creds["private_key"]
                }
                
                manager = NebiusManager(creds_payload)
                
                instances_list, presets_list = await asyncio.gather(
                    manager.list_instances(nebius_creds["project_id"]),
                    manager.get_presets(nebius_creds["project_id"]),
                    return_exceptions=True
                )
                
                if isinstance(instances_list, Exception):
                    logger.error(f"Nebius instances fetch failed: {instances_list}")
                    return []
                if isinstance(presets_list, Exception):
                    logger.warning(f"Nebius presets fetch failed: {presets_list}")
                    presets_list = []
                
                presets_map = {}
                for preset in presets_list:
                    preset_id = preset.get("id")
                    if preset_id:
                        presets_map[preset_id] = preset
                
                normalized = []
                for inst in instances_list:
                    try:
                        normalized.append(normalize_nebius_instance(inst, presets_map))
                    except Exception as e:
                        logger.error(f"Error normalizing Nebius instance: {e}")
                
                logger.info(f"Fetched {len(normalized)} Nebius instances")
                return normalized
            except Exception as e:
                logger.error(f"Nebius fetch error: {e}", exc_info=True)
                return []
        
        async def fetch_scaleway():
            if not scaleway_creds:
                return []
            try:
                headers = {"X-Auth-Token": scaleway_creds["secret_key"]}
                if scaleway_creds.get("project_id"):
                    headers["X-Project-ID"] = scaleway_creds["project_id"]
                
                import httpx
                zones = SCW_ZONES

                async def fetch_zone(zone: str) -> List[UnifiedInstance]:
                    async with httpx.AsyncClient(timeout=30) as client:
                        instances_resp, products_resp = await asyncio.gather(
                            client.get(
                                f"https://api.scaleway.com/instance/v1/zones/{zone}/servers",
                                headers=headers,
                                params={"per_page": 100},
                            ),
                            client.get(
                                f"https://api.scaleway.com/instance/v1/zones/{zone}/products/servers",
                                headers=headers,
                            ),
                            return_exceptions=True,
                        )

                    if isinstance(instances_resp, Exception):
                        logger.error(f"Scaleway instances fetch failed for {zone}: {instances_resp}")
                        return []
                    if not hasattr(instances_resp, "status_code") or instances_resp.status_code != 200:
                        logger.debug(
                            f"Scaleway instances API returned {getattr(instances_resp, 'status_code', 'unknown')} for {zone}"
                        )
                        return []

                    products_map: Dict[str, Any] = {}
                    if not isinstance(products_resp, Exception) and hasattr(products_resp, "status_code") and products_resp.status_code == 200:
                        products_data = products_resp.json()
                        servers_products = products_data.get("servers", {}) or {}
                        for key, product in servers_products.items():
                            commercial_type = (product or {}).get("commercial_type", key)
                            products_map[commercial_type] = product
                    elif isinstance(products_resp, Exception):
                        logger.warning(f"Scaleway products fetch failed for {zone}: {products_resp}")

                    instances_data = instances_resp.json()
                    instances_list = instances_data.get("servers", []) or []

                    normalized: List[UnifiedInstance] = []
                    for inst in instances_list:
                        try:
                            if isinstance(inst, dict) and not inst.get("zone"):
                                inst = {**inst, "zone": zone}
                            normalized.append(normalize_scaleway_instance(inst, products_map))
                        except Exception as e:
                            logger.error(f"Error normalizing Scaleway instance for {zone}: {e}")
                    return normalized

                results = await asyncio.gather(*(fetch_zone(z) for z in zones), return_exceptions=True)
                normalized: List[UnifiedInstance] = []
                for r in results:
                    if isinstance(r, Exception):
                        logger.warning(f"Scaleway zone fetch error: {r}")
                        continue
                    normalized.extend(r)

                logger.info(f"Fetched {len(normalized)} Scaleway instances")
                return normalized
            except Exception as e:
                logger.error(f"Scaleway fetch error: {e}", exc_info=True)
                return []
        
        # Fetch from all providers in parallel
        lambda_instances, nebius_instances, scaleway_instances = await asyncio.gather(
            fetch_lambda(),
            fetch_nebius(),
            fetch_scaleway(),
            return_exceptions=True
        )
        
        # Handle exceptions
        if isinstance(lambda_instances, Exception):
            logger.error(f"Lambda aggregation failed: {lambda_instances}")
            lambda_instances = []
        if isinstance(nebius_instances, Exception):
            logger.error(f"Nebius aggregation failed: {nebius_instances}")
            nebius_instances = []
        if isinstance(scaleway_instances, Exception):
            logger.error(f"Scaleway aggregation failed: {scaleway_instances}")
            scaleway_instances = []
        
        # Combine all instances
        all_instances = lambda_instances + nebius_instances + scaleway_instances
        
        logger.info(f"Aggregated total: {len(all_instances)} instances (Lambda: {len(lambda_instances)}, Nebius: {len(nebius_instances)}, Scaleway: {len(scaleway_instances)})")
        
        return all_instances
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to aggregate instances: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to aggregate instances: {str(e)}"
        )


@app.get("/api/instances/aggregated-catalog", response_model=List[UnifiedCatalogItem])
async def get_aggregated_catalog(request: Request):
    """
    Get aggregated *available instance configurations* from all configured cloud providers.

    This powers the "Instance Based" view: Lambda instance-types, Nebius GPU presets, and Scaleway GPU products.
    Providers without configured credentials are skipped.
    """
    try:
        from telemetry.auth import decode_access_token
        from telemetry.db import get_session
        from telemetry.models import User
        from telemetry.repository import TelemetryRepository
        from sqlalchemy import select
        from uuid import UUID

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

        token = auth_header.split(" ")[1]
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token")

        user_id_str = payload.get("sub")
        if not user_id_str:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        async for session in get_session():
            stmt = select(User).where(User.user_id == UUID(user_id_str))
            result = await session.execute(stmt)
            current_user = result.scalar_one_or_none()
            if not current_user:
                raise HTTPException(status_code=401, detail="User not found")
            if not current_user.is_active:
                raise HTTPException(status_code=403, detail="User account is inactive")
            break

        lambda_api_key: Optional[str] = None
        nebius_creds: Optional[Dict[str, Any]] = None
        scaleway_creds: Optional[Dict[str, Any]] = None

        async for session in get_session():
            repo = TelemetryRepository(session)

            # Lambda
            try:
                lambda_creds = await repo.list_credentials(
                    user_id=current_user.user_id,
                    provider="lambda",
                    credential_type="api_key",
                )
                if lambda_creds:
                    cred = lambda_creds[0]
                    secret = await repo.get_credential_secret(cred)
                    lambda_api_key = secret if isinstance(secret, str) else secret.get("apiKey") or secret.get("api_key")
            except Exception as e:
                logger.debug(f"Failed to fetch Lambda credentials: {e}")

            # Nebius
            try:
                nebius_creds_list = await repo.list_credentials(
                    user_id=current_user.user_id,
                    provider="nebius",
                    credential_type="service_account",
                )
                if nebius_creds_list:
                    cred = nebius_creds_list[0]
                    secret = await repo.get_credential_secret(cred)
                    secret_data = json.loads(secret) if isinstance(secret, str) else secret
                    if secret_data:
                        nebius_creds = {
                            "service_account_id": secret_data.get("serviceAccountId") or secret_data.get("service_account_id"),
                            "key_id": secret_data.get("keyId") or secret_data.get("key_id"),
                            "private_key": secret_data.get("secretKey") or secret_data.get("private_key") or secret_data.get("secret_key"),
                            "project_id": secret_data.get("projectId") or secret_data.get("project_id"),
                        }
            except Exception as e:
                logger.debug(f"Failed to fetch Nebius credentials: {e}")

            # Scaleway
            try:
                scaleway_creds_list = await repo.list_credentials(
                    user_id=current_user.user_id,
                    provider="scaleway",
                    credential_type="access_key",
                )
                if scaleway_creds_list:
                    cred = scaleway_creds_list[0]
                    secret = await repo.get_credential_secret(cred)
                    secret_data = json.loads(secret) if isinstance(secret, str) else secret
                    secret_key = secret_data.get("secretKey") or secret_data.get("secret_key") or secret
                    project_id = secret_data.get("projectId") or secret_data.get("project_id")
                    if secret_key:
                        scaleway_creds = {
                            "secret_key": secret_key,
                            "project_id": project_id,
                        }
            except Exception as e:
                logger.debug(f"Failed to fetch Scaleway credentials: {e}")

            break

        async def fetch_lambda_catalog() -> List[UnifiedCatalogItem]:
            if not lambda_api_key:
                return []
            try:
                types_resp = await make_lambda_api_request("instance-types", api_key_override=lambda_api_key)
                types_data = types_resp.get("data", {}) if isinstance(types_resp, dict) else {}
                items: List[UnifiedCatalogItem] = []
                if isinstance(types_data, dict):
                    for key, entry in types_data.items():
                        if not isinstance(entry, dict):
                            continue
                        try:
                            items.append(normalize_lambda_catalog_item(key, entry))
                        except Exception as e:
                            logger.warning(f"Failed to normalize Lambda catalog item {key}: {e}")
                return items
            except Exception as e:
                logger.error(f"Lambda catalog fetch error: {e}", exc_info=True)
                return []

        async def fetch_nebius_catalog() -> List[UnifiedCatalogItem]:
            if not nebius_creds or not nebius_creds.get("project_id"):
                return []
            try:
                from managers.nebius_manager import NebiusManager

                creds_payload = {
                    "service_account_id": nebius_creds["service_account_id"],
                    "key_id": nebius_creds["key_id"],
                    "private_key": nebius_creds["private_key"],
                }
                manager = NebiusManager(creds_payload)
                presets_list = await manager.get_presets(nebius_creds["project_id"])
                items: List[UnifiedCatalogItem] = []
                for preset in presets_list or []:
                    try:
                        items.append(normalize_nebius_catalog_item(preset))
                    except Exception as e:
                        logger.warning(f"Failed to normalize Nebius preset: {e}")
                return items
            except Exception as e:
                logger.error(f"Nebius catalog fetch error: {e}", exc_info=True)
                return []

        async def fetch_scaleway_catalog() -> List[UnifiedCatalogItem]:
            if not scaleway_creds:
                return []
            try:
                zones = SCW_ZONES
                headers = {"X-Auth-Token": scaleway_creds["secret_key"]}
                if scaleway_creds.get("project_id"):
                    headers["X-Project-ID"] = scaleway_creds["project_id"]

                import httpx

                async def fetch_zone(zone: str) -> List[UnifiedCatalogItem]:
                    availability_lookup: Dict[str, Any] = {}
                    async with httpx.AsyncClient(timeout=30) as client:
                        products_resp = await client.get(
                            f"https://api.scaleway.com/instance/v1/zones/{zone}/products/servers",
                            headers=headers,
                            params={"availability": "true"},
                        )
                        if products_resp.status_code == 400:
                            # Some Scaleway environments reject this param; retry without it.
                            products_resp = await client.get(
                                f"https://api.scaleway.com/instance/v1/zones/{zone}/products/servers",
                                headers=headers,
                            )

                        # Fetch availability per server type (best-effort).
                        try:
                            avail_resp = await client.get(
                                f"https://api.scaleway.com/instance/v1/zones/{zone}/products/servers/availability",
                                headers=headers,
                            )
                            if avail_resp.status_code == 200:
                                avail_data = avail_resp.json()
                                raw_avail = avail_data.get("servers") or {}
                                for k, info in raw_avail.items():
                                    if isinstance(info, dict):
                                        availability_lookup[k] = (
                                            info.get("availability")
                                            or info.get("stock")
                                            or info.get("status")
                                        )
                                    else:
                                        availability_lookup[k] = info
                        except Exception:
                            pass
                    if products_resp.status_code != 200:
                        logger.debug(f"Scaleway products API returned {products_resp.status_code} for {zone}")
                        return []
                    products_data = products_resp.json()
                    servers_products = products_data.get("servers", {}) or {}
                    items: List[UnifiedCatalogItem] = []
                    for key, product in servers_products.items():
                        commercial_type = (product or {}).get("commercial_type", key)
                        enriched = dict(product or {})
                        availability_value = (
                            enriched.get("availability")
                            or enriched.get("stock")
                            or availability_lookup.get(commercial_type)
                            or availability_lookup.get(key)
                        )
                        if availability_value is not None:
                            # Ensure the normalizer sees a per-zone availability signal.
                            enriched.setdefault("availability", availability_value)
                        item = normalize_scaleway_catalog_item(zone, commercial_type, enriched)
                        if item:
                            items.append(item)
                    return items

                results = await asyncio.gather(*(fetch_zone(z) for z in zones), return_exceptions=True)
                items: List[UnifiedCatalogItem] = []
                for r in results:
                    if isinstance(r, Exception):
                        logger.warning(f"Scaleway zone catalog fetch error: {r}")
                        continue
                    items.extend(r)
                # Merge per commercial_type across zones (so a single card can show region availability count).
                merged: Dict[str, UnifiedCatalogItem] = {}
                merged_raw: Dict[str, Dict[str, Any]] = {}
                for item in items:
                    key = item.name
                    zone_list = item.regions or []
                    # For scaleway, each item is zone-scoped; stash raw per zone for reference.
                    for z in zone_list:
                        merged_raw.setdefault(key, {})[z] = item.raw

                    if key not in merged:
                        merged[key] = UnifiedCatalogItem(
                            id=f"scaleway:{key}",
                            provider="scaleway",
                            name=item.name,
                            description=item.description,
                            gpu_model=item.gpu_model,
                            num_gpus=item.num_gpus,
                            vcpus=item.vcpus,
                            memory_gb=item.memory_gb,
                            storage_gb=item.storage_gb,
                            availability=item.availability,
                            regions=list(zone_list),
                            cost_per_hour_usd=item.cost_per_hour_usd,
                            cost_per_month_usd=item.cost_per_month_usd,
                            raw={"zones": {}},
                        )
                        continue

                    existing = merged[key]
                    existing.regions = sorted(set((existing.regions or []) + list(zone_list)))
                    # If any zone is available, consider the merged config available.
                    if (existing.availability or "").lower() != "available" and (item.availability or "").lower() == "available":
                        existing.availability = "available"
                    # Prefer lowest hourly cost if present (should be same across zones, but safe).
                    if item.cost_per_hour_usd is not None:
                        if existing.cost_per_hour_usd is None or item.cost_per_hour_usd < existing.cost_per_hour_usd:
                            existing.cost_per_hour_usd = item.cost_per_hour_usd
                            existing.cost_per_month_usd = item.cost_per_month_usd

                # Attach merged raw map
                for key, zones_map in merged_raw.items():
                    if key in merged:
                        merged[key].raw = {"zones": zones_map}

                return list(merged.values())
            except Exception as e:
                logger.error(f"Scaleway catalog fetch error: {e}", exc_info=True)
                return []

        lambda_items, nebius_items, scaleway_items = await asyncio.gather(
            fetch_lambda_catalog(),
            fetch_nebius_catalog(),
            fetch_scaleway_catalog(),
            return_exceptions=True,
        )

        if isinstance(lambda_items, Exception):
            logger.error(f"Lambda catalog aggregation failed: {lambda_items}")
            lambda_items = []
        if isinstance(nebius_items, Exception):
            logger.error(f"Nebius catalog aggregation failed: {nebius_items}")
            nebius_items = []
        if isinstance(scaleway_items, Exception):
            logger.error(f"Scaleway catalog aggregation failed: {scaleway_items}")
            scaleway_items = []

        return list(lambda_items) + list(nebius_items) + list(scaleway_items)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to aggregate catalog: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to aggregate catalog: {str(e)}")


@app.post("/api/instances/migrate", response_model=MigrationResponse)
async def migrate_instance(payload: MigrationRequest, request: Request) -> MigrationResponse:
    """
    Backend-assisted migration:
      1) Launch target
      2) Wait until running
      3) Tear down source (best-effort; skipped if launch fails)
    """
    target_provider = (payload.target_provider or "").lower()
    source_provider = (payload.source_provider or "").lower()
    target_instance_id: Optional[str] = None

    # Helper: wait for Lambda
    async def _wait_lambda_running(instance_id: str, api_key: str, max_attempts: int = 20, delay: int = 10) -> bool:
        for attempt in range(max_attempts):
            try:
                inst = await make_lambda_api_request(
                    f"instances/{instance_id}",
                    api_key_override=api_key,
                )
                state = (
                    inst.get("data", {}).get("state")
                    or inst.get("state")
                    or inst.get("status")
                    or ""
                )
                if isinstance(state, str) and state.lower() in {"active", "running"}:
                    return True
            except Exception as exc:
                logger.debug(f"Polling target instance {instance_id} attempt {attempt+1} failed: {exc}")
            await asyncio.sleep(delay)
        return False

    # Helper: wait for Scaleway
    async def _wait_scaleway_running(server_id: str, zone: str, secret_key: str, project_id: Optional[str], max_attempts: int = 20, delay: int = 10) -> bool:
        headers = {"X-Auth-Token": secret_key}
        if project_id:
            headers["X-Project-ID"] = project_id
        url = f"https://api.scaleway.com/instance/v1/zones/{zone}/servers/{server_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(max_attempts):
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json().get("server", {})
                        state = (data.get("state") or data.get("status") or "").lower()
                        if state in {"running", "started"}:
                            return True
                    else:
                        logger.debug(f"Scaleway poll {server_id} attempt {attempt+1} status {resp.status_code}")
                except Exception as exc:
                    logger.debug(f"Scaleway poll error attempt {attempt+1}: {exc}")
                await asyncio.sleep(delay)
        return False

    # Launch target instance
    if target_provider == "lambda":
        api_key = request.headers.get("x-lambda-api-key") or request.headers.get("X-Lambda-API-Key")
        if not api_key:
            raise HTTPException(status_code=400, detail="X-Lambda-API-Key header is required for Lambda migration")
        try:
            launch_resp = await make_lambda_api_request(
                "instance-operations/launch",
                method="POST",
                data=payload.target_payload,
                api_key_override=api_key,
            )
            instance_ids = (
                launch_resp.get("data", {}).get("instance_ids")
                or launch_resp.get("instance_ids")
                or []
            )
            if not instance_ids:
                raise HTTPException(status_code=502, detail="Launch succeeded but no instance_ids returned")
            target_instance_id = instance_ids[0]
            ready = await _wait_lambda_running(target_instance_id, api_key)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Migration launch failed (lambda): {e}", exc_info=True)
            raise HTTPException(status_code=502, detail=f"Failed to launch target instance: {e}")
    elif target_provider == "scaleway":
        zone = payload.target_zone or payload.target_payload.get("zone")
        secret_key = payload.target_secret_key or payload.target_payload.get("secret_key")
        project_id = payload.target_project_id or payload.target_payload.get("project_id")
        commercial_type = payload.target_payload.get("commercial_type")
        public_key = payload.target_payload.get("public_key")
        if not zone or not secret_key or not project_id or not commercial_type or not public_key:
            raise HTTPException(status_code=400, detail="Scaleway migration requires zone, secret_key, project_id, commercial_type, and public_key")
        headers = {"X-Auth-Token": secret_key, "X-Project-ID": project_id}
        create_body = {
            "name": payload.target_payload.get("name") or f"scw-migrate-{uuid.uuid4().hex[:6]}",
            "commercial_type": commercial_type,
            "project": project_id,
            "image": payload.target_payload.get("image") or "ubuntu_jammy",
            "enable_ipv6": False,
            "dynamic_ip_required": True,
            "routed_ip_enabled": True,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # Ensure SSH key exists
                await client.post(
                    "https://api.scaleway.com/iam/v1alpha1/ssh-keys",
                    headers=headers,
                    json={"name": payload.target_payload.get("ssh_key_name") or f"omniference-{uuid.uuid4().hex[:6]}", "public_key": public_key, "project_id": project_id},
                )
                resp = await client.post(
                    f"https://api.scaleway.com/instance/v1/zones/{zone}/servers",
                    headers=headers,
                    json=create_body,
                )
                if resp.status_code in (400, 422) and "routed_ip" in resp.text.lower():
                    create_body.pop("routed_ip_enabled", None)
                    resp = await client.post(
                        f"https://api.scaleway.com/instance/v1/zones/{zone}/servers",
                        headers=headers,
                        json=create_body,
                    )
                if resp.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"Scaleway create server failed: {resp.text}")
                server = resp.json().get("server") or {}
                target_instance_id = server.get("id") or server.get("name")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Migration launch failed (scaleway): {e}", exc_info=True)
            raise HTTPException(status_code=502, detail=f"Failed to launch target instance: {e}")
        ready = await _wait_scaleway_running(target_instance_id, zone, secret_key, project_id)
    else:
        raise HTTPException(status_code=400, detail=f"Provider {target_provider} not supported for migration")

    if not ready:
        return MigrationResponse(
            target_provider=target_provider,
            target_instance_id=target_instance_id,
            status="launching",
            detail="Target launched but not yet running; source not terminated.",
        )

    # Teardown source (best effort)
    teardown_detail = "skipped"
    if source_provider == "lambda" and payload.source_instance_id:
        api_key = request.headers.get("x-lambda-api-key") or request.headers.get("X-Lambda-API-Key")
        if api_key:
            try:
                await make_lambda_api_request(
                    "instance-operations/terminate",
                    method="POST",
                    data={"instance_ids": [payload.source_instance_id]},
                    api_key_override=api_key,
                )
                teardown_detail = "terminated source"
            except Exception as exc:
                teardown_detail = f"failed to terminate source: {exc}"
                logger.error(teardown_detail)
    elif source_provider == "scaleway" and payload.source_instance_id:
        zone = payload.source_zone or payload.target_zone or payload.target_payload.get("zone")
        secret_key = payload.target_secret_key or payload.target_payload.get("secret_key")
        project_id = payload.target_project_id or payload.target_payload.get("project_id")
        if zone and secret_key:
            headers = {"X-Auth-Token": secret_key}
            if project_id:
                headers["X-Project-ID"] = project_id
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    await client.delete(
                        f"https://api.scaleway.com/instance/v1/zones/{zone}/servers/{payload.source_instance_id}",
                        headers=headers,
                    )
                teardown_detail = "terminated source"
            except Exception as exc:
                teardown_detail = f"failed to terminate source: {exc}"
                logger.error(teardown_detail)

    return MigrationResponse(
        target_provider=target_provider,
        target_instance_id=target_instance_id,
        status="completed" if teardown_detail.startswith("terminated") else "launched",
        detail=teardown_detail,
    )


# ----------------------------------------------------------------------------
# SIMPLE CONFIG MANAGEMENT ENDPOINTS
# ----------------------------------------------------------------------------
from fastapi import Body

def _write_env_key(file_path: str, key: str, value: str) -> None:
    content = ""
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    lines = content.splitlines() if content else []
    updated = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    new_content = "\n".join(lines) + "\n"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

@app.post("/api/v1/config/lambda-key")
async def set_lambda_api_key(payload: Dict[str, str] = Body(...)):
    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")

    try:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        _write_env_key(env_path, "LAMBDA_API_KEY", api_key)

        os.environ["LAMBDA_API_KEY"] = api_key
        global LAMBDA_API_KEY
        LAMBDA_API_KEY = api_key

        return {"success": True, "message": "Lambda API key saved to backend .env and applied"}
    except Exception as e:
        logger.error(f"Failed to set Lambda API key: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# SYSTEM-BASED BENCHMARK API ENDPOINTS
# ============================================================================

@app.get("/api/benchmarks/systems")
async def get_available_systems():
    """
    Get list of available benchmark systems.
    """
    try:
        backend_dir = Path(__file__).parent
        benchmarks_dir = backend_dir.parent / "data" / "benchmarks"
        print(f"DEBUG: Current working directory: {Path.cwd()}")
        print(f"DEBUG: Benchmarks dir path: {benchmarks_dir.absolute()}")
        print(f"DEBUG: Benchmarks dir exists: {benchmarks_dir.exists()}")
        if not benchmarks_dir.exists():
            return {"systems": [], "message": "No benchmark data available"}
        
        systems = []
        for system_dir in benchmarks_dir.iterdir():
            if system_dir.is_dir():
                summary_file = system_dir / "summary.json"
                if summary_file.exists():
                    with open(summary_file, 'r') as f:
                        summary_data = json.load(f)
                    systems.append({
                        "system_name": summary_data.get("system_name", system_dir.name),
                        "gpu_model": summary_data.get("gpu_model", "Unknown"),
                        "gpu_count": summary_data.get("gpu_count", 0),
                        "available_benchmarks": len(summary_data.get("available_benchmarks", [])),
                        "system_specs": summary_data.get("system_specs", {})
                    })
        
        return {"systems": systems}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list systems: {str(e)}")

@app.get("/api/benchmarks/{system}")
async def get_system_summary(system: str):
    """
    Get summary data for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        summary_file = backend_dir.parent / "data" / "benchmarks" / system / "summary.json"
        if not summary_file.exists():
            raise HTTPException(status_code=404, detail=f"System {system} not found")
        
        with open(summary_file, 'r') as f:
            data = json.load(f)
        
        return data
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in {system} summary: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load system data: {str(e)}")

@app.get("/api/benchmarks/{system}/benchmarks")
async def get_system_benchmarks(system: str):
    """
    Get list of available benchmarks for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        system_dir = backend_dir.parent / "data" / "benchmarks" / system
        if not system_dir.exists():
            raise HTTPException(status_code=404, detail=f"System {system} not found")
        
        benchmarks = []
        for file_path in system_dir.glob("*.json"):
            if file_path.name != "summary.json":
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                benchmarks.append({
                    "filename": file_path.name,
                    "model": data.get('benchmark_info', {}).get('model_name', 'Unknown'),
                    "engine": data.get('benchmark_info', {}).get('engine', 'Unknown'),
                    "total_tests": data.get('benchmark_info', {}).get('total_tests', 0),
                    "total_runtime_minutes": data.get('benchmark_info', {}).get('total_runtime_minutes', 0),
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime
                })
        
        return {"benchmarks": benchmarks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list benchmarks for {system}: {str(e)}")

@app.get("/api/benchmarks/{system}/{filename}")
async def get_benchmark_data(system: str, filename: str):
    """
    Get benchmark data for a specific system and file.
    """
    try:
        backend_dir = Path(__file__).parent
        file_path = backend_dir.parent / "data" / "benchmarks" / system / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Benchmark file {filename} not found for system {system}")
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        return data
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in {filename}: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load benchmark data: {str(e)}")

@app.get("/api/benchmarks/{system}/{filename}/summary")
async def get_benchmark_summary(system: str, filename: str):
    """
    Get summary of non-null benchmark data for a specific system and file.
    """
    try:
        backend_dir = Path(__file__).parent
        file_path = backend_dir.parent / "data" / "benchmarks" / system / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Benchmark file {filename} not found for system {system}")
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Extract non-null values from results
        non_null_data = {}
        if 'results' in data and data['results']:
            for i, result in enumerate(data['results']):
                non_null_result = {}
                for key, value in result.items():
                    if value is not None:
                        non_null_result[key] = value
                if non_null_result:
                    non_null_data[f"result_{i}"] = non_null_result
        
        # Extract benchmark info
        if 'benchmark_info' in data:
            non_null_benchmark = {}
            for key, value in data['benchmark_info'].items():
                if value is not None:
                    non_null_benchmark[key] = value
            non_null_data['benchmark_info'] = non_null_benchmark
        
        return {
            "system": system,
            "filename": filename,
            "non_null_data": non_null_data,
            "total_results": len(data.get('results', [])),
            "non_null_results": len([r for r in data.get('results', []) if any(v is not None for v in r.values())])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process benchmark data: {str(e)}")

@app.get("/api/benchmarks/{system}/{filename}/metrics")
async def get_benchmark_metrics(system: str, filename: str):
    """
    Get structured metrics for visualization from benchmark data.
    """
    try:
        backend_dir = Path(__file__).parent
        file_path = backend_dir.parent / "data" / "benchmarks" / system / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Benchmark file {filename} not found for system {system}")
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        metrics = {
            "throughput": [],
            "latency": [],
            "gpu_utilization": [],
            "memory_utilization": [],
            "power_consumption": [],
            "cost_analysis": [],
            "gpu_metrics": [],
            "all_results": []
        }
        
        if 'results' in data:
            for i, result in enumerate(data['results']):
                # Throughput metrics
                if result.get('throughput_tokens_per_second') is not None:
                    metrics["throughput"].append({
                        "iteration": i + 1,
                        "tokens_per_second": result['throughput_tokens_per_second'],
                        "requests_per_second": result.get('throughput_requests_per_second', 0)
                    })
                
                # Latency metrics (only non-null values)
                latency_data = {}
                for key in ['latency_p50_ms', 'latency_p95_ms', 'ttft_p50_ms', 'ttft_p95_ms', 'tbt_p50_ms', 'tbt_p95_ms', 'prefill_latency_ms', 'decode_latency_ms']:
                    if result.get(key) is not None:
                        latency_data[key] = result[key]
                if latency_data:
                    latency_data["iteration"] = i + 1
                    metrics["latency"].append(latency_data)
                
                # GPU utilization
                if result.get('gpu_utilization_percent') is not None:
                    metrics["gpu_utilization"].append({
                        "iteration": i + 1,
                        "utilization_percent": result['gpu_utilization_percent'],
                        "sm_active_percent": result.get('sm_active_percent', 0)
                    })
                
                # Memory utilization
                if result.get('hbm_bandwidth_utilization_percent') is not None:
                    metrics["memory_utilization"].append({
                        "iteration": i + 1,
                        "hbm_utilization_percent": result['hbm_bandwidth_utilization_percent'],
                        "nvlink_utilization_percent": result.get('nvlink_bandwidth_utilization_percent', 0)
                    })
                
                # Power consumption
                if result.get('power_draw_watts') is not None:
                    metrics["power_consumption"].append({
                        "iteration": i + 1,
                        "power_watts": result['power_draw_watts'],
                        "performance_per_watt": result.get('performance_per_watt', 0)
                    })
                
                # Cost analysis
                if result.get('cost_usd') is not None:
                    metrics["cost_analysis"].append({
                        "iteration": i + 1,
                        "cost_usd": result['cost_usd'],
                        "performance_per_dollar": result.get('performance_per_dollar', 0)
                    })
                
                # GPU metrics per GPU
                if 'gpu_metrics' in result and result['gpu_metrics']:
                    for gpu_metric in result['gpu_metrics']:
                        if gpu_metric.get('gpu_utilization_percent') is not None:
                            metrics["gpu_metrics"].append({
                                "iteration": i + 1,
                                "gpu_id": gpu_metric.get('gpu_id', 0),
                                "utilization_percent": gpu_metric['gpu_utilization_percent'],
                                "memory_used_gb": gpu_metric.get('memory_used_gb', 0),
                                "memory_total_gb": gpu_metric.get('memory_total_gb', 0),
                                "temperature_c": gpu_metric.get('temperature_c', 0),
                                "hbm_utilization_percent": gpu_metric.get('hbm_bandwidth_utilization_percent', 0),
                                "nvlink_utilization_percent": gpu_metric.get('nvlink_bandwidth_utilization_percent', 0)
                            })
                
                # Store all non-null results for comprehensive display
                non_null_result = {}
                for key, value in result.items():
                    if value is not None:
                        non_null_result[key] = value
                if non_null_result:
                    non_null_result["iteration"] = i + 1
                    metrics["all_results"].append(non_null_result)
        
        return {
            "system": system,
            "filename": filename,
            "metrics": metrics,
            "summary": {
                "total_iterations": len(data.get('results', [])),
                "has_throughput": len(metrics["throughput"]) > 0,
                "has_latency": len(metrics["latency"]) > 0,
                "has_gpu_metrics": len(metrics["gpu_metrics"]) > 0,
                "has_power_data": len(metrics["power_consumption"]) > 0,
                "has_cost_data": len(metrics["cost_analysis"]) > 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to extract metrics: {str(e)}")

@app.get("/api/benchmarks/compare")
async def compare_systems(systems: str):
    """
    Compare multiple systems. Systems should be comma-separated (e.g., "A100,H100").
    """
    try:
        system_list = [s.strip() for s in systems.split(',')]
        comparison_data = {}
        
        for system in system_list:
            summary_file = Path(f"data/benchmarks/{system}/summary.json")
            if summary_file.exists():
                with open(summary_file, 'r') as f:
                    data = json.load(f)
                comparison_data[system] = data
        
        if not comparison_data:
            raise HTTPException(status_code=404, detail="No systems found for comparison")
        
        return {"systems": comparison_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compare systems: {str(e)}")

# ============================================================================
# LEGACY PROFILING DASHBOARD API ENDPOINTS (for backward compatibility)
# ============================================================================

@app.get("/api/profiling/dashboard/list")
async def get_profiling_dashboard_list():
    """
    Get list of available profiling dashboard files.
    """
    try:
        dashboard_dir = Path("data/dashboard")
        if not dashboard_dir.exists():
            return {"files": [], "message": "No profiling data available"}
        
        files = []
        for file_path in dashboard_dir.glob("*.json"):
            files.append({
                "filename": file_path.name,
                "path": str(file_path),
                "size": file_path.stat().st_size,
                "modified": file_path.stat().st_mtime
            })
        
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list profiling files: {str(e)}")

@app.get("/api/profiling/dashboard/{filename}")
async def get_profiling_dashboard_data(filename: str):
    """
    Get profiling dashboard data for a specific file.
    """
    try:
        file_path = Path(f"data/dashboard/{filename}")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Profiling file {filename} not found")
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        return data
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in {filename}: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load profiling data: {str(e)}")

@app.get("/api/profiling/dashboard/{filename}/summary")
async def get_profiling_dashboard_summary(filename: str):
    """
    Get summary of non-null profiling data for a specific file.
    """
    try:
        file_path = Path(f"data/dashboard/{filename}")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Profiling file {filename} not found")
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Extract non-null values from results
        non_null_data = {}
        if 'results' in data and data['results']:
            for i, result in enumerate(data['results']):
                non_null_result = {}
                for key, value in result.items():
                    if value is not None:
                        non_null_result[key] = value
                if non_null_result:
                    non_null_data[f"result_{i}"] = non_null_result
        
        # Extract benchmark info
        if 'benchmark_info' in data:
            non_null_benchmark = {}
            for key, value in data['benchmark_info'].items():
                if value is not None:
                    non_null_benchmark[key] = value
            non_null_data['benchmark_info'] = non_null_benchmark
        
        return {
            "filename": filename,
            "non_null_data": non_null_data,
            "total_results": len(data.get('results', [])),
            "non_null_results": len([r for r in data.get('results', []) if any(v is not None for v in r.values())])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process profiling data: {str(e)}")

@app.get("/api/profiling/dashboard/{filename}/metrics")
async def get_profiling_metrics(filename: str):
    """
    Get structured metrics for visualization from profiling data.
    """
    try:
        file_path = Path(f"data/dashboard/{filename}")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Profiling file {filename} not found")
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        metrics = {
            "throughput": [],
            "latency": [],
            "gpu_utilization": [],
            "memory_utilization": [],
            "power_consumption": [],
            "cost_analysis": [],
            "gpu_metrics": [],
            "all_results": []  # Store all non-null results for comprehensive display
        }
        
        if 'results' in data:
            for i, result in enumerate(data['results']):
                # Throughput metrics
                if result.get('throughput_tokens_per_second') is not None:
                    metrics["throughput"].append({
                        "iteration": i + 1,
                        "tokens_per_second": result['throughput_tokens_per_second'],
                        "requests_per_second": result.get('throughput_requests_per_second', 0)
                    })
                
                # Latency metrics (only non-null values)
                latency_data = {}
                for key in ['latency_p50_ms', 'latency_p95_ms', 'ttft_p50_ms', 'ttft_p95_ms', 'tbt_p50_ms', 'tbt_p95_ms', 'prefill_latency_ms', 'decode_latency_ms']:
                    if result.get(key) is not None:
                        latency_data[key] = result[key]
                if latency_data:
                    latency_data["iteration"] = i + 1
                    metrics["latency"].append(latency_data)
                
                # GPU utilization
                if result.get('gpu_utilization_percent') is not None:
                    metrics["gpu_utilization"].append({
                        "iteration": i + 1,
                        "utilization_percent": result['gpu_utilization_percent'],
                        "sm_active_percent": result.get('sm_active_percent', 0)
                    })
                
                # Memory utilization
                if result.get('hbm_bandwidth_utilization_percent') is not None:
                    metrics["memory_utilization"].append({
                        "iteration": i + 1,
                        "hbm_utilization_percent": result['hbm_bandwidth_utilization_percent'],
                        "nvlink_utilization_percent": result.get('nvlink_bandwidth_utilization_percent', 0)
                    })
                
                # Power consumption
                if result.get('power_draw_watts') is not None:
                    metrics["power_consumption"].append({
                        "iteration": i + 1,
                        "power_watts": result['power_draw_watts'],
                        "performance_per_watt": result.get('performance_per_watt', 0)
                    })
                
                # Cost analysis
                if result.get('cost_usd') is not None:
                    metrics["cost_analysis"].append({
                        "iteration": i + 1,
                        "cost_usd": result['cost_usd'],
                        "performance_per_dollar": result.get('performance_per_dollar', 0)
                    })
                
                # GPU metrics per GPU
                if 'gpu_metrics' in result and result['gpu_metrics']:
                    for gpu_metric in result['gpu_metrics']:
                        if gpu_metric.get('gpu_utilization_percent') is not None:
                            metrics["gpu_metrics"].append({
                                "iteration": i + 1,
                                "gpu_id": gpu_metric.get('gpu_id', 0),
                                "utilization_percent": gpu_metric['gpu_utilization_percent'],
                                "memory_used_gb": gpu_metric.get('memory_used_gb', 0),
                                "memory_total_gb": gpu_metric.get('memory_total_gb', 0),
                                "temperature_c": gpu_metric.get('temperature_c', 0),
                                "hbm_utilization_percent": gpu_metric.get('hbm_bandwidth_utilization_percent', 0),
                                "nvlink_utilization_percent": gpu_metric.get('nvlink_bandwidth_utilization_percent', 0)
                            })
                
                # Store all non-null results for comprehensive display
                non_null_result = {}
                for key, value in result.items():
                    if value is not None:
                        non_null_result[key] = value
                if non_null_result:
                    non_null_result["iteration"] = i + 1
                    metrics["all_results"].append(non_null_result)
        
        return {
            "filename": filename,
            "metrics": metrics,
            "summary": {
                "total_iterations": len(data.get('results', [])),
                "has_throughput": len(metrics["throughput"]) > 0,
                "has_latency": len(metrics["latency"]) > 0,
                "has_gpu_metrics": len(metrics["gpu_metrics"]) > 0,
                "has_power_data": len(metrics["power_consumption"]) > 0,
                "has_cost_data": len(metrics["cost_analysis"]) > 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to extract metrics: {str(e)}")

# ============================================================================
# NEW SYSTEM-BASED DASHBOARD ENDPOINTS
# ============================================================================

@app.get("/api/dashboard/systems")
async def get_dashboard_systems():
    """
    Get available systems for the new dashboard structure.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        if not dashboard_dir.exists():
            return {"systems": []}
        
        systems = []
        
        # Look for system-specific files
        for file_path in dashboard_dir.glob("*.json"):
            filename = file_path.name.lower()
            
            # Determine system based on filename
            if "h100" in filename:
                system_name = "H100"
            elif "a100" in filename:
                system_name = "A100"
            else:
                continue
            
            # Check if we already have this system
            existing_system = next((s for s in systems if s["name"] == system_name), None)
            if not existing_system:
                existing_system = {
                    "name": system_name,
                    "description": f"{system_name} GPU System",
                    "files": [],
                    "configs": []
                }
                systems.append(existing_system)
            
            # Determine config type based on filename
            if "config1" in filename or "prefill" in filename:
                config_type = "prefill"
            elif "config2" in filename or "generation" in filename:
                config_type = "generation"
            else:
                config_type = "unknown"
            
            existing_system["files"].append({
                "filename": file_path.name,
                "config_type": config_type,
                "size": file_path.stat().st_size,
                "modified": file_path.stat().st_mtime
            })
            
            if config_type not in existing_system["configs"]:
                existing_system["configs"].append(config_type)
        
        return {"systems": systems}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard systems: {str(e)}")

@app.get("/api/dashboard/{system}/overview")
async def get_system_overview(system: str):
    """
    Get overview data for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        # Find all files for this system
        system_files = []
        for file_path in dashboard_dir.glob(f"*{system.lower()}*.json"):
            system_files.append(file_path)
        
        if not system_files:
            raise HTTPException(status_code=404, detail=f"No data found for system {system}")
        
        overview_data = {
            "system": system,
            "files": [],
            "system_info": {},
            "summary_stats": {},
            "configurations": []
        }
        
        all_results = []
        
        for file_path in system_files:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            benchmark_info = data.get("benchmark_info", {})
            results = data.get("results", [])
            
            # Extract system info from first file
            if not overview_data["system_info"]:
                overview_data["system_info"] = benchmark_info.get("system_info", {})
            
            # Determine config type
            filename = file_path.name.lower()
            if "config1" in filename or "prefill" in filename:
                config_type = "prefill"
            elif "config2" in filename or "generation" in filename:
                config_type = "generation"
            else:
                config_type = "unknown"
            
            overview_data["files"].append({
                "filename": file_path.name,
                "config_type": config_type,
                "results_count": len(results),
                "benchmark_info": benchmark_info
            })
            
            # Add results with config type
            for result in results:
                result["config_type"] = config_type
                all_results.append(result)
            
            if config_type not in overview_data["configurations"]:
                overview_data["configurations"].append(config_type)
        
        # Calculate summary statistics
        if all_results:
            metrics = [
                "throughput_tokens_per_second", "gpu_utilization_percent", 
                "sm_active_percent", "hbm_bandwidth_utilization_percent",
                "nvlink_bandwidth_utilization_percent", "power_draw_watts",
                "performance_per_watt", "cost_usd", "performance_per_dollar"
            ]
            
            for metric in metrics:
                values = [r.get(metric) for r in all_results if r.get(metric) is not None]
                if values:
                    overview_data["summary_stats"][metric] = {
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values),
                        "count": len(values)
                    }
        
        return overview_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system overview: {str(e)}")

@app.get("/api/dashboard/{system}/throughput")
async def get_system_throughput(system: str):
    """
    Get throughput and latency data for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        # Find all files for this system
        system_files = []
        for file_path in dashboard_dir.glob(f"*{system.lower()}*.json"):
            system_files.append(file_path)
        
        if not system_files:
            raise HTTPException(status_code=404, detail=f"No data found for system {system}")
        
        throughput_data = {
            "system": system,
            "time_series": [],
            "comparison": {},
            "configs": []
        }
        
        for file_path in system_files:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            results = data.get("results", [])
            filename = file_path.name.lower()
            
            # Determine config type
            if "config1" in filename or "prefill" in filename:
                config_type = "prefill"
            elif "config2" in filename or "generation" in filename:
                config_type = "generation"
            else:
                config_type = "unknown"
            
            if config_type not in throughput_data["configs"]:
                throughput_data["configs"].append(config_type)
            
            # Process results for time series
            for i, result in enumerate(results):
                throughput_data["time_series"].append({
                    "iteration": i + 1,
                    "config_type": config_type,
                    "batch_size": result.get("batch_size"),
                    "input_length": result.get("input_length"),
                    "output_length": result.get("output_length"),
                    "throughput_tokens_per_second": result.get("throughput_tokens_per_second"),
                    "throughput_requests_per_second": result.get("throughput_requests_per_second"),
                    "latency_p50_ms": result.get("latency_p50_ms"),
                    "latency_p95_ms": result.get("latency_p95_ms"),
                    "ttft_p50_ms": result.get("ttft_p50_ms"),
                    "ttft_p95_ms": result.get("ttft_p95_ms"),
                    "tbt_p50_ms": result.get("tbt_p50_ms"),
                    "tbt_p95_ms": result.get("tbt_p95_ms")
                })
            
            # Calculate comparison metrics
            if results:
                throughput_values = [r.get("throughput_tokens_per_second") for r in results if r.get("throughput_tokens_per_second") is not None]
                if throughput_values:
                    throughput_data["comparison"][config_type] = {
                        "avg_throughput": sum(throughput_values) / len(throughput_values),
                        "max_throughput": max(throughput_values),
                        "min_throughput": min(throughput_values),
                        "test_count": len(throughput_values)
                    }
        
        return throughput_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system throughput: {str(e)}")
@app.get("/api/dashboard/{system}/utilization")
async def get_system_utilization(system: str):
    """
    Get GPU utilization data for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        # Find all files for this system
        system_files = []
        for file_path in dashboard_dir.glob(f"*{system.lower()}*.json"):
            system_files.append(file_path)
        
        if not system_files:
            raise HTTPException(status_code=404, detail=f"No data found for system {system}")
        
        utilization_data = {
            "system": system,
            "gpu_utilization": [],
            "sm_utilization": [],
            "per_gpu_data": [],
            "configs": []
        }
        
        for file_path in system_files:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            results = data.get("results", [])
            filename = file_path.name.lower()
            
            # Determine config type
            if "config1" in filename or "prefill" in filename:
                config_type = "prefill"
            elif "config2" in filename or "generation" in filename:
                config_type = "generation"
            else:
                config_type = "unknown"
            
            if config_type not in utilization_data["configs"]:
                utilization_data["configs"].append(config_type)
            
            # Process results
            for result in results:
                utilization_data["gpu_utilization"].append({
                    "config_type": config_type,
                    "batch_size": result.get("batch_size"),
                    "gpu_utilization_percent": result.get("gpu_utilization_percent"),
                    "sm_active_percent": result.get("sm_active_percent")
                })
                
                utilization_data["sm_utilization"].append({
                    "config_type": config_type,
                    "batch_size": result.get("batch_size"),
                    "sm_active_percent": result.get("sm_active_percent")
                })
        
        return utilization_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system utilization: {str(e)}")

@app.get("/api/dashboard/{system}/bandwidth")
async def get_system_bandwidth(system: str):
    """
    Get bandwidth utilization data for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        # Find all files for this system
        system_files = []
        for file_path in dashboard_dir.glob(f"*{system.lower()}*.json"):
            system_files.append(file_path)
        
        if not system_files:
            raise HTTPException(status_code=404, detail=f"No data found for system {system}")
        
        bandwidth_data = {
            "system": system,
            "hbm_data": [],
            "nvlink_data": [],
            "comparison": {},
            "configs": []
        }
        
        for file_path in system_files:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            results = data.get("results", [])
            filename = file_path.name.lower()
            
            # Determine config type
            if "config1" in filename or "prefill" in filename:
                config_type = "prefill"
            elif "config2" in filename or "generation" in filename:
                config_type = "generation"
            else:
                config_type = "unknown"
            
            if config_type not in bandwidth_data["configs"]:
                bandwidth_data["configs"].append(config_type)
            
            # Process results
            for result in results:
                bandwidth_data["hbm_data"].append({
                    "config_type": config_type,
                    "batch_size": result.get("batch_size"),
                    "hbm_bandwidth_utilization_percent": result.get("hbm_bandwidth_utilization_percent"),
                    "hbm_bandwidth_raw_gbps": result.get("hbm_bandwidth_raw_gbps")
                })
                
                bandwidth_data["nvlink_data"].append({
                    "config_type": config_type,
                    "batch_size": result.get("batch_size"),
                    "nvlink_bandwidth_utilization_percent": result.get("nvlink_bandwidth_utilization_percent"),
                    "nvlink_bandwidth_raw_gbps": result.get("nvlink_bandwidth_raw_gbps")
                })
            
            # Calculate comparison metrics
            if results:
                hbm_values = [r.get("hbm_bandwidth_utilization_percent") for r in results if r.get("hbm_bandwidth_utilization_percent") is not None]
                nvlink_values = [r.get("nvlink_bandwidth_utilization_percent") for r in results if r.get("nvlink_bandwidth_utilization_percent") is not None]
                
                if hbm_values:
                    bandwidth_data["comparison"][f"{config_type}_hbm"] = {
                        "avg": sum(hbm_values) / len(hbm_values),
                        "max": max(hbm_values),
                        "min": min(hbm_values)
                    }
                
                if nvlink_values:
                    bandwidth_data["comparison"][f"{config_type}_nvlink"] = {
                        "avg": sum(nvlink_values) / len(nvlink_values),
                        "max": max(nvlink_values),
                        "min": min(nvlink_values)
                    }
        
        return bandwidth_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system bandwidth: {str(e)}")

@app.get("/api/dashboard/{system}/power")
async def get_system_power(system: str):
    """
    Get power and efficiency data for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        # Find all files for this system
        system_files = []
        for file_path in dashboard_dir.glob(f"*{system.lower()}*.json"):
            system_files.append(file_path)
        
        if not system_files:
            raise HTTPException(status_code=404, detail=f"No data found for system {system}")
        
        power_data = {
            "system": system,
            "power_draw": [],
            "efficiency": [],
            "cost_analysis": [],
            "configs": []
        }
        
        for file_path in system_files:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            results = data.get("results", [])
            filename = file_path.name.lower()
            
            # Determine config type
            if "config1" in filename or "prefill" in filename:
                config_type = "prefill"
            elif "config2" in filename or "generation" in filename:
                config_type = "generation"
            else:
                config_type = "unknown"
            
            if config_type not in power_data["configs"]:
                power_data["configs"].append(config_type)
            
            # Process results
            for result in results:
                power_data["power_draw"].append({
                    "config_type": config_type,
                    "batch_size": result.get("batch_size"),
                    "power_draw_watts": result.get("power_draw_watts")
                })
                
                power_data["efficiency"].append({
                    "config_type": config_type,
                    "batch_size": result.get("batch_size"),
                    "performance_per_watt": result.get("performance_per_watt"),
                    "throughput_tokens_per_second": result.get("throughput_tokens_per_second"),
                    "power_draw_watts": result.get("power_draw_watts")
                })
                
                power_data["cost_analysis"].append({
                    "config_type": config_type,
                    "batch_size": result.get("batch_size"),
                    "cost_usd": result.get("cost_usd"),
                    "performance_per_dollar": result.get("performance_per_dollar"),
                    "throughput_tokens_per_second": result.get("throughput_tokens_per_second")
                })
        
        return power_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system power data: {str(e)}")

@app.get("/api/dashboard/compare")
async def compare_systems_dashboard(systems: str = Query(..., description="Comma-separated list of systems to compare")):
    """
    Compare multiple systems for the dashboard.
    """
    try:
        system_list = [s.strip() for s in systems.split(",")]
        comparison_data = {}
        
        for system in system_list:
            # Get overview data for each system
            try:
                overview_response = await get_system_overview(system)
                comparison_data[system] = {
                    "overview": overview_response,
                    "system": system
                }
            except Exception as e:
                logger.warning(f"Failed to load data for system {system}: {str(e)}")
                continue
        
        # Calculate speedup comparisons
        speedup_data = {}
        if len(comparison_data) >= 2:
            systems = list(comparison_data.keys())
            baseline = systems[0]
            
            for system in systems[1:]:
                speedup_data[f"{system}_vs_{baseline}"] = {}
                
                # Compare key metrics
                baseline_stats = comparison_data[baseline]["overview"]["summary_stats"]
                system_stats = comparison_data[system]["overview"]["summary_stats"]
                
                for metric in ["throughput_tokens_per_second", "performance_per_watt", "performance_per_dollar"]:
                    if metric in baseline_stats and metric in system_stats:
                        baseline_avg = baseline_stats[metric]["avg"]
                        system_avg = system_stats[metric]["avg"]
                        
                        if baseline_avg > 0:
                            speedup = system_avg / baseline_avg
                            speedup_data[f"{system}_vs_{baseline}"][metric] = {
                                "speedup": speedup,
                                "baseline": baseline_avg,
                                "system": system_avg
                            }
        
        return {
            "comparison": comparison_data,
            "speedup": speedup_data,
            "systems": system_list
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compare systems: {str(e)}")

@app.get("/api/dashboard/{system}/data")
async def get_dashboard_system_data(system: str):
    """
    Get all dashboard data for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        if not dashboard_dir.exists():
            raise HTTPException(status_code=404, detail="Dashboard data not found")
        
        system_files = []
        all_results = []
        
        # Find all files for the system
        for file_path in dashboard_dir.glob("*.json"):
            filename = file_path.name.lower()
            
            # Check if this file belongs to the requested system
            if (system.lower() == "h100" and "h100" in filename) or \
               (system.lower() == "a100" and "a100" in filename):
                
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    
                # Determine config type
                config_type = "unknown"
                if "config1" in filename or "prefill" in filename:
                    config_type = "prefill"
                elif "config2" in filename or "generation" in filename:
                    config_type = "generation"
                
                system_files.append({
                    "filename": file_path.name,
                    "config_type": config_type,
                    "benchmark_info": data.get('benchmark_info', {}),
                    "results_count": len(data.get('results', [])),
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime
                })
                
                # Add results with config type
                if 'results' in data:
                    for result in data['results']:
                        # Auto-assign config type based on input/output length ratio
                        input_len = result.get('input_length', 0)
                        output_len = result.get('output_length', 0)
                        
                        if input_len > output_len:
                            result['config_type'] = 'prefill'
                        elif output_len > input_len:
                            result['config_type'] = 'generation'
                        else:
                            # If equal lengths, determine based on typical patterns
                            if input_len >= 1000:  # Long input typically means prefill
                                result['config_type'] = 'prefill'
                            else:  # Short input typically means generation
                                result['config_type'] = 'generation'
                            
                        result['filename'] = file_path.name
                        all_results.append(result)
        
        if not system_files:
            raise HTTPException(status_code=404, detail=f"No data found for system {system}")
        
        # Calculate summary statistics
        summary_stats = {}
        if all_results:
            metrics = [
                'throughput_tokens_per_second', 'throughput_requests_per_second',
                'gpu_utilization_percent', 'sm_active_percent',
                'hbm_bandwidth_utilization_percent', 'nvlink_bandwidth_utilization_percent',
                'power_draw_watts', 'performance_per_watt', 'cost_usd', 'performance_per_dollar'
            ]
            
            for metric in metrics:
                values = [r.get(metric, 0) for r in all_results if r.get(metric) is not None]
                if values:
                    summary_stats[metric] = {
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values),
                        "count": len(values)
                    }
                else:
                    summary_stats[metric] = {"avg": 0, "min": 0, "max": 0, "count": 0}
        
        return {
            "system": system,
            "files": system_files,
            "results": all_results,
            "summary_stats": summary_stats,
            "total_results": len(all_results)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard data for {system}: {str(e)}")

@app.get("/api/dashboard/{system}/gpu-metrics")
async def get_dashboard_gpu_metrics(system: str):
    """
    Get GPU metrics with per-GPU breakdown for a specific system.
    """
    try:
        backend_dir = Path(__file__).parent
        dashboard_dir = backend_dir.parent / "data" / "dashboard"
        
        if not dashboard_dir.exists():
            raise HTTPException(status_code=404, detail="Dashboard data not found")
        
        gpu_metrics = []
        
        # Find all files for the system
        for file_path in dashboard_dir.glob("*.json"):
            filename = file_path.name.lower()
            
            # Check if this file belongs to the requested system
            if (system.lower() == "h100" and "h100" in filename) or \
               (system.lower() == "a100" and "a100" in filename):
                
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                # Process each result
                if 'results' in data:
                    for result_idx, result in enumerate(data['results']):
                        # Determine config type based on input/output length
                        input_len = result.get('input_length', 0)
                        output_len = result.get('output_length', 0)
                        
                        if input_len > output_len:
                            config_type = 'prefill'
                        elif output_len > input_len:
                            config_type = 'generation'
                        else:
                            # If equal lengths, determine based on typical patterns
                            if input_len >= 1000:  # Long input typically means prefill
                                config_type = 'prefill'
                            else:  # Short input typically means generation
                                config_type = 'generation'
                        
                        # Extract GPU metrics if available
                        gpu_metrics_data = result.get('gpu_metrics', [])
                        
                        if isinstance(gpu_metrics_data, list) and len(gpu_metrics_data) > 0:
                            # Use actual per-GPU data from the JSON
                            for gpu_metric_data in gpu_metrics_data:
                                gpu_metric = {
                                    'system': system,
                                    'config_type': config_type,
                                    'filename': file_path.name,
                                    'test_iteration': result_idx + 1,
                                    'gpu_id': gpu_metric_data.get('gpu_id', 0),
                                    'batch_size': result.get('batch_size', 0),
                                    'input_length': input_len,
                                    'output_length': output_len,
                                    'timestamp': gpu_metric_data.get('timestamp', result.get('timestamp', '')),
                                    'gpu_utilization_percent': gpu_metric_data.get('gpu_utilization_percent', 0),
                                    'sm_active_percent': gpu_metric_data.get('sm_active_percent', 0),
                                    'hbm_bandwidth_utilization_percent': gpu_metric_data.get('hbm_bandwidth_utilization_percent', 0),
                                    'hbm_bandwidth_raw_gbps': gpu_metric_data.get('hbm_bandwidth_raw_gbps', None),
                                    'nvlink_bandwidth_utilization_percent': gpu_metric_data.get('nvlink_bandwidth_utilization_percent', 0),
                                    'nvlink_bandwidth_raw_gbps': gpu_metric_data.get('nvlink_bandwidth_raw_gbps', None),
                                    'power_draw_watts': gpu_metric_data.get('power_draw_watts', None),
                                    'temperature_c': gpu_metric_data.get('temperature_c', None),
                                    'memory_used_gb': gpu_metric_data.get('memory_used_gb', None),
                                    'memory_total_gb': gpu_metric_data.get('memory_total_gb', None)
                                }
                                gpu_metrics.append(gpu_metric)
                        else:
                            # Fallback: create per-GPU entries using aggregate data
                            gpu_count = 8  # Default to 8 GPUs
                            if 'benchmark_info' in data and 'system_info' in data['benchmark_info']:
                                gpu_count = data['benchmark_info']['system_info'].get('gpu_count', 8)
                            
                            for gpu_id in range(gpu_count):
                                gpu_metric = {
                                    'system': system,
                                    'config_type': config_type,
                                    'filename': file_path.name,
                                    'test_iteration': result_idx + 1,
                                    'gpu_id': gpu_id,
                                    'batch_size': result.get('batch_size', 0),
                                    'input_length': input_len,
                                    'output_length': output_len,
                                    'timestamp': result.get('timestamp', ''),
                                    'gpu_utilization_percent': result.get('gpu_utilization_percent', 0),
                                    'sm_active_percent': result.get('sm_active_percent', 0),
                                    'hbm_bandwidth_utilization_percent': result.get('hbm_bandwidth_utilization_percent', 0),
                                    'hbm_bandwidth_raw_gbps': result.get('hbm_bandwidth_raw_gbps', None),
                                    'nvlink_bandwidth_utilization_percent': result.get('nvlink_bandwidth_utilization_percent', 0),
                                    'nvlink_bandwidth_raw_gbps': result.get('nvlink_bandwidth_raw_gbps', None),
                                    'power_draw_watts': result.get('power_draw_watts', 0) / gpu_count if result.get('power_draw_watts') else None,
                                    'temperature_c': None,
                                    'memory_used_gb': None,
                                    'memory_total_gb': None
                                }
                                gpu_metrics.append(gpu_metric)
        
        if not gpu_metrics:
            raise HTTPException(status_code=404, detail=f"No GPU metrics found for system {system}")
        
        # Calculate summary statistics by config type
        summary_stats = {}
        config_types = set(metric['config_type'] for metric in gpu_metrics)
        
        for config_type in config_types:
            config_metrics = [m for m in gpu_metrics if m['config_type'] == config_type]
            
            # Calculate averages safely, handling None values
            gpu_util_values = [m['gpu_utilization_percent'] for m in config_metrics if m['gpu_utilization_percent'] is not None]
            sm_active_values = [m['sm_active_percent'] for m in config_metrics if m['sm_active_percent'] is not None]
            hbm_util_values = [m['hbm_bandwidth_utilization_percent'] for m in config_metrics if m['hbm_bandwidth_utilization_percent'] is not None]
            nvlink_util_values = [m['nvlink_bandwidth_utilization_percent'] for m in config_metrics if m['nvlink_bandwidth_utilization_percent'] is not None]
            power_values = [m['power_draw_watts'] for m in config_metrics if m['power_draw_watts'] is not None]
            
            summary_stats[config_type] = {
                'total_tests': len(set(m['test_iteration'] for m in config_metrics)),
                'total_gpus': len(set(m['gpu_id'] for m in config_metrics)),
                'avg_gpu_utilization': sum(gpu_util_values) / len(gpu_util_values) if gpu_util_values else 0,
                'avg_sm_active': sum(sm_active_values) / len(sm_active_values) if sm_active_values else 0,
                'avg_hbm_utilization': sum(hbm_util_values) / len(hbm_util_values) if hbm_util_values else 0,
                'avg_nvlink_utilization': sum(nvlink_util_values) / len(nvlink_util_values) if nvlink_util_values else 0,
                'avg_power_per_gpu': sum(power_values) / len(power_values) if power_values else 0
            }
        
        return {
            "system": system,
            "gpu_metrics": gpu_metrics,
            "summary_stats": summary_stats,
            "total_metrics": len(gpu_metrics)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get GPU metrics for {system}: {str(e)}")

@app.get("/api/models")
async def get_available_models():
    """
    Get list of all available models from data/models directory.
    """
    try:
        backend_dir = Path(__file__).parent
        models_dir = backend_dir.parent / "data" / "models"
        
        if not models_dir.exists():
            raise HTTPException(status_code=404, detail="Models directory not found")
        
        # Get all JSON files in the models directory
        model_files = list(models_dir.glob("*.json"))
        models = []
        
        for model_file in model_files:
            try:
                with open(model_file, 'r') as f:
                    data = json.load(f)
                
                # Extract model info
                model_info = data.get('model', {})
                models.append({
                    'id': model_file.stem,  # filename without extension
                    'name': model_info.get('name', model_file.stem),
                    'params': model_info.get('params', 'Unknown'),
                    'layers': model_info.get('layers', 0),
                    'hidden_dim': model_info.get('hidden_dim', 0),
                    'num_heads': model_info.get('num_heads', 0),
                    'num_kv_heads': model_info.get('num_kv_heads', 0)
                })
            except Exception as e:
                print(f"Error reading model file {model_file}: {e}")
                continue
        
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get models: {str(e)}")

@app.get("/api/models/{model_id}")
async def get_model_data(model_id: str):
    """
    Get model architecture data by model ID.
    """
    try:
        backend_dir = Path(__file__).parent
        models_dir = backend_dir.parent / "data" / "models"
        model_file = models_dir / f"{model_id}.json"
        
        if not model_file.exists():
            raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
        
        with open(model_file, 'r') as f:
            data = json.load(f)
        
        # Modify the model_graph to show individual layers instead of a single layer_stack
        if 'model_graph' in data and 'nodes' in data['model_graph']:
            # Find the layer_stack node
            layer_stack_node = None
            for node in data['model_graph']['nodes']:
                if node.get('type') == 'layer_stack':
                    layer_stack_node = node
                    break
            
            if layer_stack_node:
                # Get the number of layers
                num_layers = layer_stack_node.get('count', 80)
                
                # Create individual layer nodes
                layer_nodes = []
                for i in range(num_layers):
                    layer_nodes.append({
                        "id": f"layer_{i}",
                        "type": "decoder_layer",
                        "label": f"Layer {i}",
                        "layer_index": i,
                        "flops_per_layer": layer_stack_node.get('flops_per_layer', 233),
                        "memory_gb_per_layer": layer_stack_node.get('memory_gb_per_layer', 1.75),
                        "clickable": True,
                        "prefill_ref": True
                    })
                
                # Replace the layer_stack node with individual layer nodes
                data['model_graph']['nodes'] = [
                    node for node in data['model_graph']['nodes'] 
                    if node.get('type') != 'layer_stack'
                ] + layer_nodes
                
                # Update edges to connect to individual layers
                new_edges = []
                for edge in data['model_graph']['edges']:
                    if edge.get('target') == 'layers':
                        # Connect to first layer
                        new_edges.append({"source": edge['source'], "target": "layer_0"})
                    elif edge.get('source') == 'layers':
                        # Connect from last layer
                        new_edges.append({"source": f"layer_{num_layers-1}", "target": edge['target']})
                    else:
                        new_edges.append(edge)
                
                # Add connections between consecutive layers
                for i in range(num_layers - 1):
                    new_edges.append({"source": f"layer_{i}", "target": f"layer_{i+1}"})
                
                data['model_graph']['edges'] = new_edges
        
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get model data: {str(e)}")

@app.get("/api/prefill_dag/{model_name}/{layer_index}")
async def get_prefill_layer(model_name: str, layer_index: int):
    """
    Get prefill DAG data for a specific model and layer.
    """
    try:
        backend_dir = Path(__file__).parent
        prefill_dir = backend_dir.parent / "data" / "prefill_layers"
        
        # Map model names to their prefill files
        model_file_mapping = {
            "llama3_70b": "LLaMA3_70B_realistic_prefill_with_ops.json",
            "llama4_scout": "LLaMA4_Scout_realistic_prefill_with_ops.json",
            "llama4_maverick": "LLaMA4_Maverick_realistic_prefill_with_ops.json",
            "qwen_32b_omni": "Qwen_32B_Omni_realistic_prefill_with_ops.json"
        }
        
        filename = model_file_mapping.get(model_name)
        if not filename:
            raise HTTPException(status_code=404, detail=f"Prefill data not found for model {model_name}")
        
        prefill_file = prefill_dir / filename
        if not prefill_file.exists():
            raise HTTPException(status_code=404, detail=f"Prefill file {filename} not found")
        
        with open(prefill_file, 'r') as f:
            data = json.load(f)
        
        # Extract the specific layer data
        layers = data.get("layers", [])
        layer_data = None
        
        for layer in layers:
            if layer.get("layer_index") == layer_index:
                layer_data = layer
                break
        
        if not layer_data:
            raise HTTPException(status_code=404, detail=f"Layer {layer_index} not found for model {model_name}")
        
        # Create graph structure from operators data
        operators = layer_data.get("operators", [])
        
        # Create nodes from operators
        nodes = []
        for i, op in enumerate(operators):
            node = {
                "id": f"op_{i}",
                "name": op.get("name", f"Operator {i}"),
                "type": op.get("type", "Unknown"),
                "label": op.get("name", f"Op {i}"),
                "op_type": op.get("type", "Unknown"),
                "flops_g": op.get("flops_g", 0),
                "memory_mb": op.get("memory_mb", 0)
            }
            nodes.append(node)
        
        # Create edges between consecutive operators
        edges = []
        for i in range(len(nodes) - 1):
            edges.append({
                "source": nodes[i]["id"],
                "target": nodes[i + 1]["id"],
                "type": "sequential"
            })
        
        graph = {
            "nodes": nodes,
            "edges": edges
        }
        
        return {
            "layer_index": layer_index,
            "graph": graph,
            "metrics": layer_data.get("metrics", {}),
            "architecture": data.get("model_info", {}).get("architecture", {}),
            "model_info": data.get("model_info", {})
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get prefill layer data: {str(e)}")

@app.get("/api/prefill_data/{model_name}")
async def get_prefill_data(model_name: str):
    """
    Get full prefill data for a model.
    """
    try:
        backend_dir = Path(__file__).parent
        prefill_dir = backend_dir.parent / "data" / "prefill_layers"
        
        # Map model names to their prefill files
        model_file_mapping = {
            "llama3_70b": "LLaMA3_70B_realistic_prefill_with_ops.json",
            "llama4_scout": "LLaMA4_Scout_realistic_prefill_with_ops.json",
            "llama4_maverick": "LLaMA4_Maverick_realistic_prefill_with_ops.json",
            "qwen_32b_omni": "Qwen_32B_Omni_realistic_prefill_with_ops.json"
        }
        
        filename = model_file_mapping.get(model_name)
        if not filename:
            raise HTTPException(status_code=404, detail=f"Prefill data not found for model {model_name}")
        
        prefill_file = prefill_dir / filename
        if not prefill_file.exists():
            raise HTTPException(status_code=404, detail=f"Prefill file {filename} not found")
        
        with open(prefill_file, 'r') as f:
            data = json.load(f)
        
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get prefill data: {str(e)}")

# ---------------------------------------
# 🧩 Benchmark Request Schema
# ---------------------------------------
class BenchmarkParams(BaseModel):
    # Benchmark configuration
    model: str
    engine: str
    max_batch_size: int
    input_lengths: int
    output_lengths: int
    iterations: int
    hourly_rate: float

    # SSH connection parameters
    ssh_host: str
    ssh_user: str
    pem_path: str   # path to PEM file accessible by backend
# ---------------------------------------
# ⚙️ Benchmark Task
# ---------------------------------------
def run_benchmark_task(params: BenchmarkParams, log_dir: str):
    """Runs the benchmark script on remote instance via SSH, extracts JSON path, and fetches file"""
    
    # Handle PEM file - use saved PEM file if available
    import hashlib
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(backend_dir, "temp_pem")
    os.makedirs(temp_dir, exist_ok=True)
    pem_hash = hashlib.md5(f"{params.ssh_host}_{params.ssh_user}".encode()).hexdigest()
    saved_pem_path = os.path.join(temp_dir, f"pem_{pem_hash}.pem")
    
    pem_file_path = None
    if os.path.exists(saved_pem_path):
        pem_file_path = saved_pem_path
        logger.info(f"Using saved PEM file for benchmark: {pem_file_path}")
    elif params.pem_path:
        pem_file_path = os.path.expanduser(params.pem_path)
        if not os.path.exists(pem_file_path):
            if os.path.exists(saved_pem_path):
                pem_file_path = saved_pem_path
                logger.info(f"Using saved PEM file for filename: {params.pem_path}")
            else:
                logger.error(f"PEM file not found: {params.pem_path}")
                return
    else:
        if os.path.exists(saved_pem_path):
            pem_file_path = saved_pem_path
        else:
            logger.error("No PEM file found for benchmark")
            return
    
    # Ensure PEM file has correct permissions
    if pem_file_path and os.path.exists(pem_file_path):
        try:
            os.chmod(pem_file_path, 0o400)
        except Exception as e:
            logger.warning(f"Failed to set PEM permissions: {e}")
    
    # Create instance dict for SSH
    instance = {
        "ip": params.ssh_host,
        "username": params.ssh_user,
        "pem_file": pem_file_path
    }
    
    # 1️⃣ Upload benchmark script to remote instance if it doesn't exist
    script_path = "/tmp/optimized_batch_benchmark_a100.py"
    local_script_path = os.path.join(backend_dir, "optimized_batch_benchmark_a100.py")
    
    if not os.path.exists(local_script_path):
        logger.error(f"Benchmark script not found locally: {local_script_path}")
        return
    
    logger.info(f"Uploading benchmark script to {params.ssh_host}...")
    try:
        # Check if script already exists on remote
        check_cmd = f"test -f {script_path} && echo 'exists' || echo 'missing'"
        check_result = run_ssh_command(instance, check_cmd, timeout=5).strip()
        
        if check_result != "exists":
            # Upload script using SSH
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(params.ssh_host, username=params.ssh_user, key_filename=pem_file_path, timeout=10)
            
            sftp = ssh.open_sftp()
            sftp.put(local_script_path, script_path)
            # Make script executable
            ssh.exec_command(f"chmod +x {script_path}")
            sftp.close()
            ssh.close()
            logger.info(f"✅ Uploaded benchmark script to {script_path}")
        else:
            logger.info(f"✅ Script already exists on remote: {script_path}")
    except Exception as e:
        logger.error(f"Failed to upload benchmark script: {e}")
        return
    
    # 2️⃣ Construct command for remote benchmark script
    # Convert input_lengths and output_lengths to lists if they're single values
    input_lengths_str = str(params.input_lengths) if isinstance(params.input_lengths, (int, str)) else " ".join(map(str, params.input_lengths))
    output_lengths_str = str(params.output_lengths) if isinstance(params.output_lengths, (int, str)) else " ".join(map(str, params.output_lengths))
    
    benchmark_cmd = (
        f"cd ~ && "
        f"source ~/h100_benchmark_env/bin/activate 2>/dev/null || true && "
        f"python3 {script_path} "
        f"--model {params.model} "
        f"--engine {params.engine} "
        f"--max-batch-size {params.max_batch_size} "
        f"--input-lengths {input_lengths_str} "
        f"--output-lengths {output_lengths_str} "
        f"--iterations {params.iterations} "
        f"--hourly-rate {params.hourly_rate} "
        f"2>&1 | tee /tmp/benchmark_output.log"
    )
    
    logger.info(f"🚀 Starting benchmark on {params.ssh_host} for {params.model} ({params.engine})")
    logger.info(f"Command: {benchmark_cmd}")
    
    # 3️⃣ Run benchmark on remote instance in background with nohup
    output_log_path = os.path.join(log_dir, "run_output.log")
    
    try:
        # Execute benchmark command in background
        nohup_cmd = f"nohup bash -c '{benchmark_cmd}' > /tmp/benchmark_nohup.log 2>&1 & echo $!"
        pid_output = run_ssh_command(instance, nohup_cmd, timeout=10)
        pid = pid_output.strip() if pid_output else None
        logger.info(f"Benchmark started with PID: {pid}")
        
        # Monitor progress by checking log file periodically
        max_wait_time = 3600 * 2  # 2 hours max
        check_interval = 30  # Check every 30 seconds
        elapsed = 0
        
        while elapsed < max_wait_time:
            time.sleep(check_interval)
            elapsed += check_interval
            
            # Check if process is still running
            try:
                check_pid_cmd = f"ps -p {pid} > /dev/null 2>&1 && echo 'running' || echo 'finished'"
                status = run_ssh_command(instance, check_pid_cmd, timeout=5).strip()
                
                if status == "finished":
                    logger.info(f"Benchmark process {pid} finished")
                    break
                    
                # Get latest log output
                try:
                    log_cmd = "tail -n 50 /tmp/benchmark_output.log 2>/dev/null || echo 'Log not ready yet'"
                    log_output = run_ssh_command(instance, log_cmd, timeout=5)
                    if log_output:
                        with open(output_log_path, "a", encoding='utf-8') as f:
                            f.write(f"\n--- Progress update at {elapsed}s ---\n")
                            f.write(log_output)
                            f.write("\n")
                except:
                    pass
                    
            except Exception as e:
                logger.warning(f"Error checking benchmark status: {e}")
        
        # 4️⃣ Get final benchmark output
        logger.info("Fetching final benchmark output...")
        final_output = run_ssh_command(instance, "cat /tmp/benchmark_output.log 2>/dev/null || echo 'No output log'", timeout=30)
        if final_output:
            with open(output_log_path, "w", encoding='utf-8') as f:
                f.write(final_output)
        
        # 5️⃣ Get internal benchmark log
        internal_log_path_remote = "~/optimized_benchmark.log"
        internal_log_path_local = os.path.join(log_dir, "optimized_benchmark.log")
        
        try:
            log_content = run_ssh_command(instance, f"cat {internal_log_path_remote} 2>/dev/null || echo ''", timeout=10)
            if log_content and len(log_content.strip()) > 0:
                with open(internal_log_path_local, "w", encoding='utf-8') as f:
                    f.write(log_content)
                logger.info(f"✅ Saved benchmark log to {internal_log_path_local}")
        except Exception as e:
            logger.warning(f"Could not fetch internal log: {e}")
        
        # 6️⃣ Parse JSON file path from log
        json_path = None
        if os.path.exists(internal_log_path_local):
            with open(internal_log_path_local, "r", encoding='utf-8') as f:
                for line in f:
                    match = re.search(r"Results saved to\s+([\w\-/\.]+\.json)", line)
                    if match:
                        json_path = match.group(1)
                        break
        
        if not json_path:
            # Try to find JSON files in home directory
            try:
                find_cmd = "find ~ -name '*_final.json' -o -name '*_optimized_benchmark_*.json' 2>/dev/null | head -1"
                json_path = run_ssh_command(instance, find_cmd, timeout=10).strip()
                if not json_path:
                    logger.warning("⚠️ No JSON benchmark file path found. Check logs for errors.")
                    return
            except:
                logger.warning("⚠️ Could not find JSON benchmark file.")
                return
        
        # 7️⃣ Fetch JSON file via SSH
        try:
            logger.info(f"🔗 Retrieving {json_path} from {params.ssh_host}...")
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(params.ssh_host, username=params.ssh_user, key_filename=pem_file_path, timeout=30)
            
            sftp = ssh.open_sftp()
            local_json_path = os.path.join(log_dir, os.path.basename(json_path))
            sftp.get(json_path, local_json_path)
            sftp.close()
            ssh.close()
            
            logger.info(f"✅ Retrieved {json_path} → {local_json_path}")
        except Exception as e:
            logger.error(f"❌ Failed to fetch JSON via SSH: {e}")
            
    except Exception as e:
        logger.error(f"❌ Benchmark execution failed: {e}", exc_info=True)

# ---------------------------------------
# 🌐 Benchmark Endpoint
# ---------------------------------------
@app.post("/run-benchmark")
async def run_benchmark(params: BenchmarkParams, background_tasks: BackgroundTasks):
    """Triggered when user clicks Run Benchmark from frontend."""

    # Create timestamped logs folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = f"logs/{params.model.replace('/', '_')}_{params.engine}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)

    # Run benchmark as background job
    background_tasks.add_task(run_benchmark_task, params, log_dir)

    return {
        "status": "started",
        "message": f"Benchmark started for {params.model} ({params.engine}) on {params.ssh_host}",
        "log_directory": log_dir
    }

# ---------------------------------------
# 🌐 vLLM Benchmark Endpoint
# ---------------------------------------
@app.post("/api/run-vllm-benchmark")
async def run_vllm_benchmark(request: VLLMBenchmarkRequest, background_tasks: BackgroundTasks):
    """
    Run vLLM benchmark on remote GPU instance using lol4.sh with user parameters.
    This will:
    1. Upload lol4.sh and detect_gpu_info.sh to the remote instance
    2. Start vLLM server with user parameters
    3. Run benchmark against the server
    """
    import hashlib
    import paramiko
    
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(backend_dir, "temp_pem")
    os.makedirs(temp_dir, exist_ok=True)
    
    # Handle PEM file (from base64 or saved file)
    pem_hash = hashlib.md5(f"{request.ssh_host}_{request.ssh_user}".encode()).hexdigest()
    saved_pem_path = os.path.join(temp_dir, f"pem_{pem_hash}.pem")
    
    pem_file_path = None
    if request.pem_base64:
        # Decode base64 PEM and save
        import base64
        try:
            pem_base64_clean = request.pem_base64
            if pem_base64_clean.startswith('data:'):
                comma_index = pem_base64_clean.find(',')
                if comma_index != -1:
                    pem_base64_clean = pem_base64_clean[comma_index + 1:]
            pem_content = base64.b64decode(pem_base64_clean).decode('utf-8')
            with open(saved_pem_path, 'w') as f:
                f.write(pem_content)
            os.chmod(saved_pem_path, 0o400)
            pem_file_path = saved_pem_path
            logger.info(f"Saved PEM file from base64: {saved_pem_path}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to decode PEM file: {str(e)}")
    elif os.path.exists(saved_pem_path):
        pem_file_path = saved_pem_path
    else:
        raise HTTPException(status_code=400, detail="PEM file not found. Please provide pem_base64 or save PEM file first.")
    
    if pem_file_path and os.path.exists(pem_file_path):
        try:
            os.chmod(pem_file_path, 0o400)
        except Exception as e:
            logger.warning(f"Failed to set PEM permissions: {e}")
    
    instance = {
        "ip": request.ssh_host,
        "username": request.ssh_user,
        "pem_file": pem_file_path
    }
    
    # Create log directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = f"logs/vllm_benchmark_{request.ssh_host}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    
    # Run in background
    background_tasks.add_task(run_vllm_benchmark_task, request, instance, log_dir)
    
    return {
        "status": "started",
        "message": f"vLLM benchmark started on {request.ssh_host}",
        "log_directory": log_dir,
        "server_port": request.port
    }

def run_vllm_benchmark_task(request: VLLMBenchmarkRequest, instance: dict, log_dir: str):
    """Background task to run vLLM benchmark with full workflow"""
    import paramiko
    import time
    import re
    
    try:
        logger.info(f"🚀 Starting vLLM benchmark on {request.ssh_host}")
        
        # Connect via SSH
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(request.ssh_host, username=request.ssh_user, key_filename=instance["pem_file"], timeout=30)
        sftp = ssh.open_sftp()
        
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 1. Upload detect_gpu_info.sh
        logger.info("Uploading detect_gpu_info.sh...")
        local_detect_script = os.path.join(backend_dir, "scripts", "detect_gpu_info.sh")
        remote_detect_script = "~/detect_gpu_info.sh"
        if os.path.exists(local_detect_script):
            sftp.put(local_detect_script, remote_detect_script)
            ssh.exec_command(f"chmod +x {remote_detect_script}")
            logger.info(f"✅ Uploaded {remote_detect_script}")
        
        # 1.5. Check if model exists, download if needed
        if request.download_model:
            logger.info(f"Checking if model exists at {request.model_path}...")
            check_model_cmd = f"test -f {request.model_path}/config.json && echo 'exists' || echo 'missing'"
            stdin, stdout, stderr = ssh.exec_command(check_model_cmd)
            model_exists = stdout.read().decode().strip()
            
            if model_exists != "exists":
                logger.info(f"Model not found. Downloading {request.model_name}...")
                # Upload lol.sh for model download
                local_lol_script = os.path.join(backend_dir, "scripts", "lol.sh")
                remote_lol_script = "~/lol_download.sh"
                
                if os.path.exists(local_lol_script):
                    with open(local_lol_script, 'r') as f:
                        lol_content = f.read()
                    
                    # Modify to download specific model and path
                    lol_content = re.sub(
                        r'RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic',
                        request.model_name,
                        lol_content
                    )
                    lol_content = re.sub(
                        r'--local-dir ./models/scout17b-fp8dyn',
                        f'--local-dir {request.model_path}',
                        lol_content
                    )
                    # Only run model download part (skip other setup)
                    # Extract just the download section
                    model_dir = os.path.dirname(request.model_path)
                    model_name_escaped = request.model_name.replace("'", "'\\''")
                    model_path_escaped = request.model_path.replace("'", "'\\''")
                    download_section = f"""#!/bin/bash
set -e
source ~/venv/bin/activate 2>/dev/null || (python3 -m venv ~/venv && source ~/venv/bin/activate)
pip install -q "huggingface_hub[cli]" hf-transfer 2>/dev/null || pip install -q "huggingface_hub" hf-transfer
HF_TOKEN="${HF_TOKEN:-}"
if [ -n "$HF_TOKEN" ]; then
    huggingface-cli login --token "$HF_TOKEN" 2>/dev/null || true
else
    echo "HF_TOKEN not set; skipping login (required for gated/private models)."
fi
mkdir -p {model_dir}
cd {model_dir}
python3 << 'PYEOF'
from huggingface_hub import snapshot_download
import os
hf_token = os.environ.get('HF_TOKEN')
print('Downloading {model_name_escaped} to {model_path_escaped}...')
snapshot_download(
    repo_id='{model_name_escaped}',
    local_dir='{model_path_escaped}',
    token=hf_token
)
print('✅ Model download complete!')
PYEOF
"""
                    with sftp.file(remote_lol_script, 'w') as f:
                        f.write(download_section)
                    ssh.exec_command(f"chmod +x {remote_lol_script}")
                    logger.info(f"✅ Created download script")
                    
                    # Run download in background and monitor
                    logger.info("Starting model download (this may take a while)...")
                    download_cmd = f"nohup bash {remote_lol_script} > ~/model_download.log 2>&1 & echo $!"
                    stdin, stdout, stderr = ssh.exec_command(download_cmd)
                    download_pid = stdout.read().decode().strip()
                    logger.info(f"Model download started with PID: {download_pid}")
                    
                    # Wait for download to complete (check for config.json)
                    max_download_wait = 3600  # 1 hour
                    download_elapsed = 0
                    while download_elapsed < max_download_wait:
                        time.sleep(30)  # Check every 30 seconds
                        download_elapsed += 30
                        
                        check_cmd = f"test -f {request.model_path}/config.json && echo 'ready' || echo 'downloading'"
                        stdin, stdout, stderr = ssh.exec_command(check_cmd)
                        status = stdout.read().decode().strip()
                        
                        if status == "ready":
                            logger.info(f"✅ Model download complete after {download_elapsed}s")
                            break
                        
                        # Show progress
                        if download_elapsed % 300 == 0:  # Every 5 minutes
                            size_cmd = f"du -sh {request.model_path} 2>/dev/null || echo '0'"
                            stdin, stdout, stderr = ssh.exec_command(size_cmd)
                            size = stdout.read().decode().strip()
                            logger.info(f"Download progress ({download_elapsed}s): {size}")
                    
                    if download_elapsed >= max_download_wait:
                        logger.error("❌ Model download timed out")
                        ssh.close()
                        return
                else:
                    logger.warning("lol.sh not found, skipping model download")
            else:
                logger.info("✅ Model already exists")
        
        # 2. Create modified lol4.sh with user parameters
        logger.info("Creating customized vLLM launch script...")
        local_lol4_script = os.path.join(os.path.dirname(__file__), "scripts", "lol4.sh")
        remote_lol4_script = "~/lol4_custom.sh"
        
        # Read the original script
        with open(local_lol4_script, 'r') as f:
            script_content = f.read()
        
        # Modify script to use user parameters and run in detached mode
        # Replace MODEL_PATH
        script_content = script_content.replace(
            'MODEL_PATH="${MODEL_PATH:-/home/ubuntu/BM/models/scout17b-fp8dyn}"',
            f'MODEL_PATH="{request.model_path}"'
        )
        
        # Override parameters if provided (use regex replacement for more reliability)
        if request.max_model_len:
            # Replace the calculation line with direct assignment
            script_content = re.sub(
                r'MAX_MODEL_LEN=\$\(calculate_max_model_len.*?\)',
                f'MAX_MODEL_LEN={request.max_model_len}',
                script_content
            )
        
        if request.max_num_seqs:
            script_content = re.sub(
                r'MAX_NUM_SEQS=\$\(calculate_max_num_seqs.*?\)',
                f'MAX_NUM_SEQS={request.max_num_seqs}',
                script_content
            )
        
        if request.gpu_memory_utilization:
            script_content = re.sub(
                r'GPU_MEM_UTIL=\$\(calculate_gpu_memory_utilization.*?\)',
                f'GPU_MEM_UTIL={request.gpu_memory_utilization}',
                script_content
            )
        
        if request.tensor_parallel_size:
            script_content = re.sub(
                r'TENSOR_PARALLEL_SIZE=\$\(calculate_tensor_parallel_size.*?\)',
                f'TENSOR_PARALLEL_SIZE={request.tensor_parallel_size}',
                script_content
            )
        
        # Modify docker run command to run in detached mode (remove -it, add -d)
        script_content = script_content.replace('--rm -it --gpus', '--rm -d --gpus')
        
        # Write modified script to remote
        with sftp.file(remote_lol4_script, 'w') as f:
            f.write(script_content)
        ssh.exec_command(f"chmod +x {remote_lol4_script}")
        logger.info(f"✅ Created {remote_lol4_script}")
        
        # 3. Upload benchmark script
        logger.info("Uploading benchmark script...")
        local_benchmark_script = os.path.join(os.path.dirname(__file__), "scripts", "benchmark_vllm.sh")
        remote_benchmark_script = "~/benchmark_vllm.sh"
        if os.path.exists(local_benchmark_script):
            sftp.put(local_benchmark_script, remote_benchmark_script)
            ssh.exec_command(f"chmod +x {remote_benchmark_script}")
            logger.info(f"✅ Uploaded {remote_benchmark_script}")
        
        sftp.close()
        
        # 4. Start vLLM server in background
        logger.info("Starting vLLM server...")
        server_cmd = f"nohup bash {remote_lol4_script} > ~/vllm_server.log 2>&1 & echo $!"
        stdin, stdout, stderr = ssh.exec_command(server_cmd)
        server_pid = stdout.read().decode().strip()
        logger.info(f"vLLM server started with PID: {server_pid}")
        
        # 5. Wait for server to be ready
        logger.info("Waiting for vLLM server to be ready...")
        max_wait = 300  # 5 minutes
        wait_interval = 5
        elapsed = 0
        server_ready = False
        
        while elapsed < max_wait:
            time.sleep(wait_interval)
            elapsed += wait_interval
            
            # Check if server is responding
            check_cmd = f"curl -s http://localhost:{request.port}/health 2>/dev/null | head -1 || echo 'not_ready'"
            stdin, stdout, stderr = ssh.exec_command(check_cmd)
            response = stdout.read().decode().strip()
            
            if response and "not_ready" not in response:
                server_ready = True
                logger.info(f"✅ vLLM server is ready after {elapsed}s")
                break
            
            logger.info(f"Waiting for server... ({elapsed}s/{max_wait}s)")
        
        if not server_ready:
            logger.error("❌ vLLM server did not become ready in time")
            ssh.close()
            return
        
        # 6. Run benchmark with user-defined parameters
        logger.info(f"Running benchmark with {request.num_requests} requests, batch_size={request.batch_size}, input_seq_len={request.input_seq_len}, output_seq_len={request.output_seq_len}...")
        benchmark_cmd = (
            f"VLLM_URL=http://localhost:{request.port} "
            f"NUM_REQUESTS={request.num_requests} "
            f"BATCH_SIZE={request.batch_size} "
            f"INPUT_SEQ_LEN={request.input_seq_len} "
            f"OUTPUT_SEQ_LEN={request.output_seq_len} "
            f'PROMPT="{request.prompt}" '
            f"MAX_TOKENS={request.output_seq_len} "
            f"bash {remote_benchmark_script} > ~/vllm_benchmark.log 2>&1"
        )
        
        stdin, stdout, stderr = ssh.exec_command(benchmark_cmd)
        exit_status = stdout.channel.recv_exit_status()
        
        if exit_status == 0:
            logger.info("✅ Benchmark completed successfully")
        else:
            logger.warning(f"⚠️ Benchmark exited with status {exit_status}")
        
        # 7. Fetch logs
        logger.info("Fetching benchmark results...")
        try:
            # Get benchmark log
            stdin, stdout, stderr = ssh.exec_command("cat ~/vllm_benchmark.log")
            benchmark_log = stdout.read().decode()
            with open(os.path.join(log_dir, "benchmark.log"), "w") as f:
                f.write(benchmark_log)
            
            # Get server log
            stdin, stdout, stderr = ssh.exec_command("cat ~/vllm_server.log")
            server_log = stdout.read().decode()
            with open(os.path.join(log_dir, "server.log"), "w") as f:
                f.write(server_log)
            
            logger.info(f"✅ Logs saved to {log_dir}")
        except Exception as e:
            logger.error(f"Failed to fetch logs: {e}")
        
        ssh.close()
        
    except Exception as e:
        logger.error(f"❌ vLLM benchmark failed: {e}", exc_info=True)

# ---------------------------------------
# 🌐 Workflow Endpoints (Step-by-step)
# ---------------------------------------

def _resolve_workflow_pem_file(
    ssh_host: str,
    ssh_user: str,
    pem_base64: Optional[str],
) -> str:
    """
    Resolve SSH key for workflow endpoints.

    Priority:
    1. Decode pem_base64 from request and persist as host+user-scoped PEM
    2. Reuse host+user-scoped PEM in backend/temp_pem
    3. Reuse legacy global PEM file if available
    """
    import base64
    import hashlib

    backend_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(backend_dir, "temp_pem")
    os.makedirs(temp_dir, exist_ok=True)

    pem_hash = hashlib.md5(f"{ssh_host}_{ssh_user}".encode()).hexdigest()
    saved_pem_path = os.path.join(temp_dir, f"pem_{pem_hash}.pem")
    legacy_saved_pem_path = "/tmp/uploaded_key.pem"

    if pem_base64:
        try:
            if os.path.exists(saved_pem_path):
                try:
                    os.chmod(saved_pem_path, 0o600)
                except Exception:
                    pass

            pem_base64_clean = pem_base64
            if pem_base64_clean.startswith("data:"):
                comma_index = pem_base64_clean.find(",")
                if comma_index != -1:
                    pem_base64_clean = pem_base64_clean[comma_index + 1:]

            pem_content = base64.b64decode(pem_base64_clean).decode("utf-8")
            with open(saved_pem_path, "w", encoding="utf-8") as f:
                f.write(pem_content)
            os.chmod(saved_pem_path, 0o400)
            return saved_pem_path
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to decode PEM: {str(exc)}")

    if os.path.exists(saved_pem_path):
        try:
            os.chmod(saved_pem_path, 0o400)
        except Exception:
            pass
        logger.warning(
            "Workflow request missing pem_base64; reusing saved PEM for host=%s user=%s (%s)",
            ssh_host,
            ssh_user,
            saved_pem_path,
        )
        return saved_pem_path

    if os.path.exists(legacy_saved_pem_path):
        try:
            os.chmod(legacy_saved_pem_path, 0o400)
        except Exception:
            pass
        logger.warning(
            "Workflow request missing pem_base64; using legacy saved PEM for host=%s user=%s (%s)",
            ssh_host,
            ssh_user,
            legacy_saved_pem_path,
        )
        return legacy_saved_pem_path

    raise HTTPException(
        status_code=400,
        detail=(
            "PEM file not found. Please provide pem_base64 in the request or upload/save a PEM first."
        ),
    )


@app.post("/api/workflow/setup-instance")
async def workflow_setup_instance(request: SetupInstanceRequest, background_tasks: BackgroundTasks):
    """
    Setup phase: Run h100_fp8.sh to install drivers, CUDA, DCGM, and download model.
    """
    logger.warning(
        "Workflow setup request received: host=%s user=%s provider=%s has_pem_base64=%s pem_len=%s model=%s",
        request.ssh_host,
        request.ssh_user,
        request.cloud_provider,
        bool(request.pem_base64),
        len(request.pem_base64) if request.pem_base64 else 0,
        request.model_name,
    )
    
    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )
    
    # Determine model path
    if not request.model_path:
        model_basename = os.path.basename(request.model_name.replace('/', '_'))
        request.model_path = f"/home/ubuntu/BM/models/{model_basename}"
    
    # Create log directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workflow_id = f"workflow_{request.ssh_host}_{timestamp}"
    log_dir = f"logs/{workflow_id}"
    os.makedirs(log_dir, exist_ok=True)
    
    # Run in background
    background_tasks.add_task(workflow_setup_task, request, pem_file_path, log_dir)
    
    return {
        "status": "started",
        "workflow_id": workflow_id,
        "message": f"Setup started on {request.ssh_host}",
        "log_directory": log_dir
    }

@app.post("/api/workflow/check-instance")
async def workflow_check_instance(request: CheckInstanceRequest, background_tasks: BackgroundTasks):
    """
    Check phase: Run lol.sh to verify nvidia-smi and restart DCGM.
    """
    logger.warning(
        "Workflow check request received: host=%s user=%s provider=%s has_pem_base64=%s pem_len=%s",
        request.ssh_host,
        request.ssh_user,
        request.cloud_provider,
        bool(request.pem_base64),
        len(request.pem_base64) if request.pem_base64 else 0,
    )
    
    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workflow_id = f"workflow_{request.ssh_host}_{timestamp}"
    log_dir = f"logs/{workflow_id}"
    os.makedirs(log_dir, exist_ok=True)
    
    background_tasks.add_task(workflow_check_task, request, pem_file_path, log_dir)
    
    return {
        "status": "started",
        "workflow_id": workflow_id,
        "message": f"Check started on {request.ssh_host}",
        "log_directory": log_dir
    }

@app.post("/api/workflow/deploy-vllm")
async def workflow_deploy_vllm(request: DeployVLLMRequest, background_tasks: BackgroundTasks):
    """
    Deploy phase: Run lol4.sh to start vLLM server with adaptive GPU parameters.
    """
    logger.warning(
        "Workflow deploy request received: host=%s user=%s provider=%s has_pem_base64=%s pem_len=%s model_path=%s",
        request.ssh_host,
        request.ssh_user,
        request.cloud_provider,
        bool(request.pem_base64),
        len(request.pem_base64) if request.pem_base64 else 0,
        request.model_path,
    )
    
    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workflow_id = f"workflow_{request.ssh_host}_{timestamp}"
    log_dir = f"logs/{workflow_id}"
    os.makedirs(log_dir, exist_ok=True)
    
    background_tasks.add_task(workflow_deploy_task, request, pem_file_path, log_dir)
    
    return {
        "status": "started",
        "workflow_id": workflow_id,
        "message": f"Deploy started on {request.ssh_host}",
        "log_directory": log_dir
    }

@app.post("/api/workflow/run-benchmark")
async def workflow_run_benchmark(request: RunBenchmarkRequest, background_tasks: BackgroundTasks):
    """
    Benchmark phase: Upload agent.py to the instance and run workload profiling.
    Collects TTFT, TPOT, throughput, latency, bottleneck analysis.
    Results are uploaded to the profiling API and stored in the database.
    """
    logger.info(
        "Workflow benchmark request: host=%s user=%s provider=%s model=%s num_requests=%d concurrency=%d",
        request.ssh_host, request.ssh_user, request.cloud_provider,
        request.model_path, request.num_requests, request.max_concurrency,
    )

    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workflow_id = f"workflow_{request.ssh_host}_{timestamp}"
    log_dir = f"logs/{workflow_id}"
    os.makedirs(log_dir, exist_ok=True)

    background_tasks.add_task(workflow_benchmark_task, request, pem_file_path, log_dir)

    return {
        "status": "started",
        "workflow_id": workflow_id,
        "message": f"Benchmark started on {request.ssh_host}",
        "log_directory": log_dir
    }


@app.post("/api/workflow/kernel-profile")
async def workflow_kernel_profile(request: KernelProfileRequest, background_tasks: BackgroundTasks):
    """
    Kernel profiling phase: Upload agent.py and run kernel-level profiling.
    Captures CUDA kernel breakdown (matmul, attention, activation, etc.).
    Separate from standard benchmark to avoid contaminating hardware metrics.
    """
    logger.info(
        "Workflow kernel profile request: host=%s user=%s provider=%s kernel_requests=%d",
        request.ssh_host, request.ssh_user, request.cloud_provider, request.kernel_requests,
    )

    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workflow_id = f"workflow_{request.ssh_host}_{timestamp}"
    log_dir = f"logs/{workflow_id}"
    os.makedirs(log_dir, exist_ok=True)

    background_tasks.add_task(workflow_kernel_profile_task, request, pem_file_path, log_dir)

    return {
        "status": "started",
        "workflow_id": workflow_id,
        "message": f"Kernel profiling started on {request.ssh_host}",
        "log_directory": log_dir
    }

# ── Model Catalog ─────────────────────────────────────────────────────────────

_MODELS_JSON_PATH = os.path.join(os.path.dirname(__file__), "telemetry", "data", "models.json")
_models_cache: Optional[list] = None


def _load_models() -> list:
    global _models_cache
    if _models_cache is not None:
        return _models_cache
    try:
        with open(_MODELS_JSON_PATH, "r") as f:
            _models_cache = json.load(f)
    except Exception as e:
        logger.warning("Failed to load models.json: %s", e)
        _models_cache = []
    return _models_cache


@app.get("/api/models")
async def list_models(
    gpu_type: Optional[str] = None,
    vram_gb: Optional[int] = None,
):
    """Return the unified model catalog, optionally filtered by GPU type or VRAM."""
    models = _load_models()
    if gpu_type:
        models = [m for m in models if gpu_type in (m.get("compatible_gpus") or [])]
    if vram_gb is not None:
        models = [m for m in models if (m.get("vram_gb") or 0) <= vram_gb]
    return {"models": models}


# ── Workflow State Persistence ────────────────────────────────────────────────
# Stores per-host completion timestamps to a JSON file so the frontend can
# show "Completed 3 days ago" badges without re-running every phase.

_WORKFLOW_STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "workflow_states.json")


def _load_workflow_states() -> dict:
    """Load all persisted workflow states from disk."""
    try:
        os.makedirs(os.path.dirname(_WORKFLOW_STATE_FILE), exist_ok=True)
        if os.path.exists(_WORKFLOW_STATE_FILE):
            with open(_WORKFLOW_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_workflow_states(states: dict) -> None:
    """Persist all workflow states to disk."""
    try:
        os.makedirs(os.path.dirname(_WORKFLOW_STATE_FILE), exist_ok=True)
        with open(_WORKFLOW_STATE_FILE, "w") as f:
            json.dump(states, f, indent=2)
    except Exception as e:
        logger.warning("Failed to persist workflow states: %s", e)


def _update_workflow_phase(ssh_host: str, phase: str, **extra) -> None:
    """Mark a workflow phase as completed for the given SSH host."""
    states = _load_workflow_states()
    host_state = states.setdefault(ssh_host, {})
    host_state[f"{phase}_completed_at"] = datetime.utcnow().isoformat()
    host_state.update(extra)
    _save_workflow_states(states)


@app.get("/api/workflow/state/{ssh_host:path}")
async def get_workflow_state(ssh_host: str):
    """
    Return the persisted workflow state for a given SSH host.
    Shows which phases were completed and when, so the frontend can
    display completion badges without re-running setup.
    """
    states = _load_workflow_states()
    state = states.get(ssh_host, {})
    return {
        "ssh_host": ssh_host,
        "setup_completed_at": state.get("setup_completed_at"),
        "check_completed_at": state.get("check_completed_at"),
        "vllm_deployed_at": state.get("vllm_deployed_at"),
        "vllm_model": state.get("vllm_model"),
        "last_verified_at": state.get("last_verified_at"),
    }


# ── Environment Status Check ──────────────────────────────────────────────────

class EnvironmentCheckRequest(BaseModel):
    """Request for checking instance environment readiness."""
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None
    cloud_provider: str = "lambda"
    model_path: str = "/home/ubuntu/BM/models/Qwen3.5-9B"


@app.post("/api/workflow/state")
async def check_environment_state(request: EnvironmentCheckRequest):
    """
    Check the environment state of a remote instance.
    Runs quick SSH checks to determine what's installed and running.
    Returns component readiness without modifying anything.
    """
    import paramiko

    logger.info("Environment check: host=%s user=%s provider=%s", request.ssh_host, request.ssh_user, request.cloud_provider)

    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )

    result = {
        "ssh_host": request.ssh_host,
        "driver": False,
        "cuda": False,
        "docker": False,
        "dcgm": False,
        "model": False,
        "vllm_running": False,
        "vllm_model": None,
        "gpu_type": None,
        "gpu_count": 0,
        "gpu_memory_gb": 0,
        "error": None,
    }

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(request.ssh_host, username=request.ssh_user, key_filename=pem_file_path, timeout=15)

        def _run(cmd: str) -> tuple:
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            code = stdout.channel.recv_exit_status()
            return code, out, err

        # 1. NVIDIA driver
        code, out, _ = _run("nvidia-smi --query-gpu=name,count,memory.total --format=csv,noheader,nounits 2>/dev/null | head -1")
        if code == 0 and out:
            result["driver"] = True
            parts = [p.strip() for p in out.split(",")]
            if len(parts) >= 3:
                result["gpu_type"] = parts[0]
                try:
                    result["gpu_memory_gb"] = round(int(parts[2]) / 1024)
                except (ValueError, IndexError):
                    pass
            # Get GPU count
            code2, count_out, _ = _run("nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l")
            if code2 == 0 and count_out.isdigit():
                result["gpu_count"] = int(count_out)

        # 2. CUDA
        code, out, _ = _run("nvcc --version 2>/dev/null | grep 'release' || ls /usr/local/cuda/version.json 2>/dev/null")
        result["cuda"] = code == 0 and bool(out)

        # 3. Docker
        code, _, _ = _run("docker --version 2>/dev/null")
        result["docker"] = code == 0

        # 4. DCGM
        code, _, _ = _run("dcgmi discovery -l 2>/dev/null | head -3")
        result["dcgm"] = code == 0

        # 5. Model downloaded
        code, _, _ = _run(f"test -d {request.model_path} && ls {request.model_path}/*.safetensors {request.model_path}/*.bin 2>/dev/null | head -1")
        result["model"] = code == 0

        # 6. vLLM running
        code, out, _ = _run("docker inspect vllm --format '{{.State.Running}} {{.Config.Cmd}}' 2>/dev/null")
        if code == 0 and out.startswith("true"):
            result["vllm_running"] = True
            # Try to get model name from container args
            code3, model_out, _ = _run("docker inspect vllm --format '{{range .Config.Cmd}}{{.}} {{end}}' 2>/dev/null")
            if code3 == 0 and "--model" in model_out:
                try:
                    parts = model_out.split()
                    model_idx = parts.index("--model") + 1
                    if model_idx < len(parts):
                        result["vllm_model"] = parts[model_idx]
                except (ValueError, IndexError):
                    pass

        ssh.close()
        logger.info("Environment check result: host=%s driver=%s docker=%s model=%s vllm=%s gpu=%s×%d",
                     request.ssh_host, result["driver"], result["docker"], result["model"],
                     result["vllm_running"], result["gpu_type"], result["gpu_count"])

    except Exception as e:
        result["error"] = str(e)
        logger.error("Environment check failed: host=%s error=%s", request.ssh_host, e)

    return result


# ── Inference Server Control ──────────────────────────────────────────────────

class InferenceStartRequest(BaseModel):
    """Request to start vLLM inference server."""
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None
    model_path: str = "/home/ubuntu/BM/models/Qwen3.5-9B"
    cloud_provider: str = "lambda"
    # vLLM server parameters (all optional — auto-detected from GPU if not set)
    tensor_parallel_size: Optional[int] = None
    max_model_len: Optional[int] = None
    max_num_seqs: Optional[int] = None
    gpu_memory_utilization: Optional[float] = None
    dtype: str = "auto"
    enforce_eager: bool = True


class InferenceStopRequest(BaseModel):
    """Request to stop vLLM inference server."""
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None


@app.post("/api/inference/start")
async def inference_start(request: InferenceStartRequest, background_tasks: BackgroundTasks):
    """
    Start vLLM inference server on the remote instance.
    Uses the existing deploy scripts (lol4.sh / lol4_scaleway.sh) with user-specified params.
    Returns immediately; poll /api/workflow/logs/{workflow_id}?phase=deploy for progress.
    """
    logger.info("Inference start: host=%s model=%s provider=%s tp=%s max_len=%s",
                request.ssh_host, request.model_path, request.cloud_provider,
                request.tensor_parallel_size, request.max_model_len)

    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workflow_id = f"workflow_{request.ssh_host}_{timestamp}"
    log_dir = f"logs/{workflow_id}"
    os.makedirs(log_dir, exist_ok=True)

    # Convert to DeployVLLMRequest for the existing deploy task
    deploy_request = DeployVLLMRequest(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
        model_path=request.model_path,
        max_model_len=request.max_model_len,
        max_num_seqs=request.max_num_seqs,
        gpu_memory_utilization=request.gpu_memory_utilization,
        tensor_parallel_size=request.tensor_parallel_size,
        cloud_provider=request.cloud_provider,
    )

    background_tasks.add_task(workflow_deploy_task, deploy_request, pem_file_path, log_dir)

    inference_url = f"http://{request.ssh_host}:8000"
    return {
        "status": "started",
        "workflow_id": workflow_id,
        "message": f"Starting inference server on {request.ssh_host}",
        "inference_url": inference_url,
        "log_directory": log_dir,
    }


@app.post("/api/inference/stop")
async def inference_stop(request: InferenceStopRequest):
    """
    Stop vLLM inference server on the remote instance.
    Synchronous — waits for container to stop (usually < 10s).
    """
    import paramiko

    logger.info("Inference stop: host=%s", request.ssh_host)

    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(request.ssh_host, username=request.ssh_user, key_filename=pem_file_path, timeout=15)

        stdin, stdout, stderr = ssh.exec_command("docker stop vllm 2>/dev/null; docker rm vllm 2>/dev/null; echo 'STOPPED'", timeout=30)
        out = stdout.read().decode().strip()
        ssh.close()

        logger.info("Inference stopped: host=%s output=%s", request.ssh_host, out[:100])
        return {"status": "stopped", "message": f"Inference server stopped on {request.ssh_host}"}

    except Exception as e:
        logger.error("Inference stop failed: host=%s error=%s", request.ssh_host, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/inference/status")
async def inference_status(request: InferenceStopRequest):
    """
    Check vLLM inference server status on the remote instance.
    Returns whether it's running, which model, uptime, etc.
    """
    import paramiko

    pem_file_path = _resolve_workflow_pem_file(
        ssh_host=request.ssh_host,
        ssh_user=request.ssh_user,
        pem_base64=request.pem_base64,
    )

    result = {
        "running": False,
        "model": None,
        "url": f"http://{request.ssh_host}:8000",
        "uptime": None,
        "container_id": None,
        "error": None,
    }

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(request.ssh_host, username=request.ssh_user, key_filename=pem_file_path, timeout=10)

        stdin, stdout, stderr = ssh.exec_command(
            "docker inspect vllm --format '{{.State.Running}}|{{.State.StartedAt}}|{{.Id}}|{{range .Config.Cmd}}{{.}} {{end}}' 2>/dev/null",
            timeout=10,
        )
        out = stdout.read().decode().strip()
        code = stdout.channel.recv_exit_status()

        if code == 0 and out:
            parts = out.split("|", 3)
            if len(parts) >= 4:
                result["running"] = parts[0].lower() == "true"
                result["uptime"] = parts[1] if parts[1] else None
                result["container_id"] = parts[2][:12] if parts[2] else None
                cmd_str = parts[3]
                if "--model" in cmd_str:
                    try:
                        tokens = cmd_str.split()
                        model_idx = tokens.index("--model") + 1
                        if model_idx < len(tokens):
                            result["model"] = tokens[model_idx]
                    except (ValueError, IndexError):
                        pass

        ssh.close()

    except Exception as e:
        result["error"] = str(e)
        logger.error("Inference status check failed: host=%s error=%s", request.ssh_host, e)

    return result


# ── Connection Storage ────────────────────────────────────────────────────────

class SaveConnectionRequest(BaseModel):
    """Request to save an SSH connection for reuse."""
    name: str
    ssh_host: str
    ssh_user: str = "ubuntu"
    pem_base64: Optional[str] = None
    cloud_provider: str = "lambda"

# In-memory connection store (persisted to disk as JSON)
_CONNECTIONS_FILE = os.path.join(os.path.dirname(__file__), "data", "connections.json")


def _load_connections() -> list:
    if os.path.exists(_CONNECTIONS_FILE):
        try:
            with open(_CONNECTIONS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_connections(connections: list):
    os.makedirs(os.path.dirname(_CONNECTIONS_FILE), exist_ok=True)
    with open(_CONNECTIONS_FILE, "w") as f:
        json.dump(connections, f, indent=2, default=str)


@app.get("/api/connections")
async def list_connections():
    """List all saved SSH connections (without PEM keys for security)."""
    connections = _load_connections()
    # Strip PEM content for listing
    safe = []
    for c in connections:
        safe.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "ssh_host": c.get("ssh_host"),
            "ssh_user": c.get("ssh_user"),
            "cloud_provider": c.get("cloud_provider"),
            "created_at": c.get("created_at"),
            "last_used_at": c.get("last_used_at"),
            "has_key": bool(c.get("pem_base64")),
        })
    return safe


@app.post("/api/connections")
async def save_connection(request: SaveConnectionRequest):
    """Save a new SSH connection."""
    import uuid
    connections = _load_connections()

    # Check for duplicate host
    for c in connections:
        if c["ssh_host"] == request.ssh_host:
            # Update existing
            c["name"] = request.name
            c["ssh_user"] = request.ssh_user
            c["pem_base64"] = request.pem_base64
            c["cloud_provider"] = request.cloud_provider
            c["last_used_at"] = datetime.now().isoformat()
            _save_connections(connections)
            logger.info("Updated connection: name=%s host=%s", request.name, request.ssh_host)
            return {"status": "updated", "id": c["id"]}

    conn = {
        "id": str(uuid.uuid4())[:8],
        "name": request.name,
        "ssh_host": request.ssh_host,
        "ssh_user": request.ssh_user,
        "pem_base64": request.pem_base64,
        "cloud_provider": request.cloud_provider,
        "created_at": datetime.now().isoformat(),
        "last_used_at": datetime.now().isoformat(),
    }
    connections.append(conn)
    _save_connections(connections)
    logger.info("Saved connection: name=%s host=%s id=%s", request.name, request.ssh_host, conn["id"])
    return {"status": "created", "id": conn["id"]}


@app.get("/api/connections/{connection_id}")
async def get_connection(connection_id: str):
    """Get a saved connection (includes PEM for use)."""
    connections = _load_connections()
    for c in connections:
        if c["id"] == connection_id:
            c["last_used_at"] = datetime.now().isoformat()
            _save_connections(connections)
            return c
    raise HTTPException(status_code=404, detail="Connection not found")


@app.delete("/api/connections/{connection_id}")
async def delete_connection(connection_id: str):
    """Delete a saved connection."""
    connections = _load_connections()
    connections = [c for c in connections if c["id"] != connection_id]
    _save_connections(connections)
    logger.info("Deleted connection: id=%s", connection_id)
    return {"status": "deleted"}


@app.get("/api/workflow/logs/{workflow_id}")
async def get_workflow_logs(workflow_id: str, phase: Optional[str] = None):
    """
    Get logs and status for a workflow phase.
    """
    log_dir = f"logs/{workflow_id}"
    if not os.path.exists(log_dir):
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    if phase:
        log_file = os.path.join(log_dir, f"{phase}.log")
        status_file = os.path.join(log_dir, f"{phase}_status.json")
        container_log_file = os.path.join(log_dir, "vllm_container.log")
        
        logs = ""
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = f.read()
        
        # Include container logs for deploy phase
        container_logs = ""
        if phase == "deploy" and os.path.exists(container_log_file):
            with open(container_log_file, 'r') as f:
                container_logs = f.read()
        
        status = {"status": "unknown", "message": ""}
        if os.path.exists(status_file):
            import json
            try:
                with open(status_file, 'r') as f:
                    status = json.load(f)
            except:
                pass
        
        result = {
            "logs": logs,
            "phase": phase,
            "status": status.get("status", "unknown"),
            "message": status.get("message", ""),
            "error_details": status.get("error_details", ""),
            "run_id": status.get("run_id", ""),
        }
        if container_logs:
            result["container_logs"] = container_logs
        return result
    else:
        # Return all logs and statuses
        result = {"logs": {}, "statuses": {}}
        for phase_name in ["setup", "check", "deploy", "benchmark", "kernel_profile"]:
            log_file = os.path.join(log_dir, f"{phase_name}.log")
            status_file = os.path.join(log_dir, f"{phase_name}_status.json")
            
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    result["logs"][phase_name] = f.read()
            
            if os.path.exists(status_file):
                import json
                try:
                    with open(status_file, 'r') as f:
                        result["statuses"][phase_name] = json.load(f)
                except:
                    result["statuses"][phase_name] = {"status": "unknown", "message": ""}
        
        return result

# Background task functions
def workflow_setup_task(request: SetupInstanceRequest, pem_file_path: str, log_dir: str):
    """Background task for setup phase"""
    import paramiko
    import re
    import json
    import time
    import socket
    
    status_file = os.path.join(log_dir, "setup_status.json")
    
    try:
        # Write initial status
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Starting setup..."}, f)
        
        logger.info(f"🚀 Starting setup on {request.ssh_host}")
        
        # Verify PEM file exists and has correct permissions
        if not os.path.exists(pem_file_path):
            raise FileNotFoundError(f"PEM file not found: {pem_file_path}")
        
        # Ensure PEM file has correct permissions
        try:
            current_mode = os.stat(pem_file_path).st_mode & 0o777
            if current_mode != 0o400 and current_mode != 0o600:
                os.chmod(pem_file_path, 0o400)
                logger.debug(f"Set PEM file permissions to 400: {pem_file_path}")
        except Exception as e:
            logger.warning(f"Could not set PEM file permissions: {e}")
        
        # Attempt SSH connection with better error handling
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            # Try to load the key first to check if it's valid and not password-protected
            key = None
            key_errors = []
            
            # Try loading as RSA key
            try:
                key = paramiko.RSAKey.from_private_key_file(pem_file_path)
                logger.debug("Loaded SSH key as RSA key")
            except Exception as e:
                key_errors.append(f"RSA: {str(e)}")
            
            # Try loading as ED25519 key
            if key is None:
                try:
                    key = paramiko.Ed25519Key.from_private_key_file(pem_file_path)
                    logger.debug("Loaded SSH key as ED25519 key")
                except Exception as e:
                    key_errors.append(f"ED25519: {str(e)}")
            
            # Try loading as ECDSA key
            if key is None:
                try:
                    key = paramiko.ECDSAKey.from_private_key_file(pem_file_path)
                    logger.debug("Loaded SSH key as ECDSA key")
                except Exception as e:
                    key_errors.append(f"ECDSA: {str(e)}")
            
            # If all key loading attempts failed, provide helpful error
            if key is None:
                error_details = "; ".join(key_errors)
                if "passphrase" in error_details.lower() or "password" in error_details.lower():
                    raise ValueError(
                        f"SSH key is password-protected: {pem_file_path}. "
                        "Password-protected keys are not supported in automated workflows. "
                        "Please use an SSH key without a passphrase, or use ssh-agent to add the key first."
                    )
                else:
                    raise ValueError(
                        f"Failed to load SSH key from {pem_file_path}. "
                        f"Errors: {error_details}. "
                        "Please verify the key file is valid and not corrupted."
                    )
            
            logger.info(f"SSH key loaded successfully, attempting connection to {request.ssh_host} as {request.ssh_user}")
            
            # For Scaleway instances, allow more time for boot and SSH service to start
            cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
            ssh_timeout = 60 if cloud_provider == 'scaleway' else 30
            
            # Retry logic for SSH connection (Scaleway instances can take time to boot)
            max_retries = 10 if cloud_provider == 'scaleway' else 2  # Increased retries for Scaleway
            initial_delay = 15 if cloud_provider == 'scaleway' else 0  # Initial delay for Scaleway
            retry_delay = 15  # seconds between retries
            last_error = None
            
            logger.info(f"SSH connection parameters - Cloud: {cloud_provider}, Timeout: {ssh_timeout}s, Max retries: {max_retries}, Initial delay: {initial_delay}s")
            
            # Add initial delay for Scaleway instances (give them time to boot)
            if initial_delay > 0:
                logger.info(f"⏳ Waiting {initial_delay}s for Scaleway instance to boot before SSH attempts...")
                time.sleep(initial_delay)
                logger.info(f"✅ Initial delay complete, starting SSH connection attempts...")
            
            # Port check function to verify SSH port is open
            def check_port_open(host, port, timeout=5):
                """Check if a port is open on the host"""
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    return result == 0
                except Exception:
                    return False
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"🔄 SSH connection attempt {attempt + 1}/{max_retries} to {request.ssh_host} as {request.ssh_user}...")
                    
                    # For Scaleway, do a port check first (non-blocking way to verify readiness)
                    # Check port on all attempts for Scaleway to avoid wasting SSH connection attempts
                    if cloud_provider == 'scaleway':
                        logger.info(f"🔍 Checking if SSH port 22 is open on {request.ssh_host}...")
                        port_open = check_port_open(request.ssh_host, 22, timeout=10)
                        if not port_open:
                            logger.warning(f"⚠️  Port 22 not yet open on {request.ssh_host} (attempt {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                logger.info(f"⏳ Waiting {retry_delay}s before retry...")
                                time.sleep(retry_delay)
                                retry_delay = int(retry_delay * 1.2)  # Exponential backoff
                                continue
                            else:
                                # Last attempt and port is still closed - fail with helpful message
                                total_wait = initial_delay + sum(int(15 * (1.2 ** i)) for i in range(max_retries - 1))
                                logger.error(f"❌ Port 22 still closed after {max_retries} attempts over ~{total_wait}s")
                                error_msg = (
                                    f"SSH port 22 is not accessible on {request.ssh_host} after {max_retries} attempts (~{total_wait}s).\n\n"
                                    f"**Troubleshooting Steps:**\n"
                                    f"1. **Check Security Groups**: In Scaleway console → Instance → Security Groups → "
                                    f"   Add inbound rule: TCP port 22 from 0.0.0.0/0 (or your IP)\n"
                                    f"2. **Verify Instance Status**: Ensure instance shows 'running' (not 'stopped' or 'booting')\n"
                                    f"3. **Check SSH Service**: Use Scaleway's web console to verify SSH service is running\n"
                                    f"4. **Verify SSH Key**: Confirm your SSH public key was added to the instance's authorized_keys\n"
                                    f"5. **Image Configuration**: Ensure the image has SSH enabled by default\n\n"
                                    f"If the instance is running but SSH is blocked, this is typically a security group/firewall issue."
                                )
                                raise RuntimeError(error_msg)
                        else:
                            logger.info(f"✅ Port 22 is open on {request.ssh_host}, proceeding with SSH connection...")
                    
                    # Connect with the loaded key
                    logger.debug(f"Attempting SSH connect with timeout={ssh_timeout}s...")
                    ssh.connect(
                        request.ssh_host, 
                        username=request.ssh_user, 
                        pkey=key,
                        timeout=ssh_timeout,
                        allow_agent=False,
                        look_for_keys=False
                    )
                    logger.info(f"✅ SSH connection established to {request.ssh_host} (attempt {attempt + 1}/{max_retries})")
                    break  # Success, exit retry loop
                except (socket.timeout, paramiko.SSHException, Exception) as e:
                    last_error = e
                    error_type = type(e).__name__
                    logger.warning(f"❌ SSH connection attempt {attempt + 1}/{max_retries} failed ({error_type}): {str(e)}")
                    
                    if attempt < max_retries - 1:
                        logger.info(f"⏳ Waiting {retry_delay}s before retry {attempt + 2}/{max_retries}...")
                        time.sleep(retry_delay)
                        retry_delay = int(retry_delay * 1.2)  # Exponential backoff (less aggressive)
                    else:
                        # Last attempt failed, provide helpful error message
                        total_wait_time = initial_delay + (max_retries - 1) * retry_delay
                        logger.error(f"❌ All {max_retries} SSH connection attempts failed after ~{total_wait_time}s total wait time")
                        error_msg = (
                            f"SSH connection failed after {max_retries} attempts over ~{total_wait_time} seconds. "
                            f"Instance at {request.ssh_host} may not be fully booted yet. "
                            f"Please wait a few minutes and try again, or verify: 1) Instance is in 'running' state, "
                            f"2) Port 22 is open, 3) SSH service is running on the server, 4) SSH key is correct"
                        )
                        raise RuntimeError(error_msg) from e
                except Exception as e:
                    # This should not happen if retry logic is working correctly
                    logger.error(f"Unexpected error in SSH retry loop: {str(e)}", exc_info=True)
                    raise
        except RuntimeError:
            # Re-raise RuntimeErrors from the retry loop (they already have good error messages)
            raise
        except paramiko.AuthenticationException as e:
            error_msg = (
                f"SSH authentication failed to {request.ssh_host}: {str(e)}. "
                f"Please verify: 1) SSH key is correct and matches the server's authorized_keys, "
                f"2) User '{request.ssh_user}' exists on the server, "
                f"3) Key permissions are correct (should be 400 or 600)"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            # Catch any other unexpected errors (e.g., during key loading)
            error_msg = f"Failed to connect to {request.ssh_host} as {request.ssh_user}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e
        sftp = ssh.open_sftp()
        
        # Resolve HF token (request-provided or backend-configured) and persist securely on the remote host
        resolved_hf_token = getattr(request, "hf_token", None) or _get_backend_hf_token()
        if resolved_hf_token:
            try:
                import base64 as _b64
                token_b64 = _b64.b64encode(resolved_hf_token.encode("utf-8")).decode("utf-8")
                remote_owner = request.ssh_user if request.ssh_user else "root"
                # Use base64 on remote to avoid shell escaping issues
                token_cmd = (
                    "sudo mkdir -p /etc/gpu-setup && "
                    f"echo '{token_b64}' | base64 -d | sudo tee /etc/gpu-setup/hf_token >/dev/null && "
                    "sudo chmod 600 /etc/gpu-setup/hf_token && "
                    f"sudo chown {remote_owner}:{remote_owner} /etc/gpu-setup/hf_token"
                )
                ssh.exec_command(token_cmd)
                logger.info("HF token provided and persisted to /etc/gpu-setup/hf_token on remote host.")
            except Exception as e:
                logger.warning(f"Failed to persist HF token on remote host: {e}")
        
        # Upload scripts
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Upload detect_gpu_info.sh
        cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
        if cloud_provider == 'scaleway':
            remote_detect = "/root/detect_gpu_info.sh"  # Scaleway uses root user
        else:
            remote_detect = "/home/ubuntu/detect_gpu_info.sh"  # Lambda uses ubuntu user
        
        local_detect = os.path.join(backend_dir, "scripts", "detect_gpu_info.sh")
        if os.path.exists(local_detect):
            sftp.put(local_detect, remote_detect)
            ssh.exec_command(f"chmod +x {remote_detect}")
        else:
            logger.error(f"❌ detect_gpu_info.sh not found at {local_detect}")
            raise FileNotFoundError(f"detect_gpu_info.sh not found at {local_detect}")
        
        # Upload and modify setup script (cloud-specific where needed)
        if cloud_provider == 'scaleway':
            script_name = "h100_fp8_scaleway.sh"
            remote_setup = "/root/h100_fp8_scaleway.sh"  # Scaleway uses root user
        else:
            script_name = "h100_fp8.sh"
            remote_setup = "/home/ubuntu/h100_fp8.sh"  # Lambda uses ubuntu user
        
        local_setup = os.path.join(backend_dir, "scripts", script_name)
        
        if not os.path.exists(local_setup):
            logger.error(f"❌ {script_name} not found at {local_setup}")
            raise FileNotFoundError(f"{script_name} not found at {local_setup}")
        
        logger.info(f"Using {script_name} for cloud provider: {cloud_provider}")
        
        with open(local_setup, 'r') as f:
            setup_content = f.read()
        
        # Replace model name and path in the script
        setup_content = re.sub(
            r'MODEL_NAME="\$\{MODEL_NAME:-[^"]+\}"',
            f'MODEL_NAME="{request.model_name}"',
            setup_content
        )
        setup_content = re.sub(
            r'MODEL_PATH="\$\{MODEL_PATH:-[^"]+\}"',
            f'MODEL_PATH="{request.model_path}"',
            setup_content
        )
        # Also update the Python script's environment variables
        setup_content = re.sub(
            r"model_name = os\.environ\.get\('MODEL_NAME', '[^']+'\)",
            f"model_name = os.environ.get('MODEL_NAME', '{request.model_name}')",
            setup_content
        )
        setup_content = re.sub(
            r"model_path = os\.environ\.get\('MODEL_PATH', '[^']+'\)",
            f"model_path = os.environ.get('MODEL_PATH', '{request.model_path}')",
            setup_content
        )
        
        with sftp.file(remote_setup, 'w') as f:
            f.write(setup_content)
        ssh.exec_command(f"chmod +x {remote_setup}")
        
        sftp.close()
        
        # Update status
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Executing setup script..."}, f)
        
        # Execute setup script with environment variables
        logger.info("Executing setup script...")
        cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
        if cloud_provider == 'scaleway':
            default_model_path = f"/scratch/BM/models/{os.path.basename(request.model_name.replace('/', '_'))}"
            log_path = "/root/setup.log"
        else:
            default_model_path = f"/home/ubuntu/BM/models/{os.path.basename(request.model_name.replace('/', '_'))}"
            log_path = "/home/ubuntu/setup.log"
        
        model_path = request.model_path or default_model_path
        hf_env = f"HF_TOKEN='{resolved_hf_token}' " if resolved_hf_token else ""
        cmd = f"{hf_env}MODEL_NAME='{request.model_name}' MODEL_PATH='{model_path}' bash {remote_setup} 2>&1 | tee {log_path}"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        
        # Stream output
        log_file = os.path.join(log_dir, "setup.log")
        with open(log_file, 'w') as f:
            for line in stdout:
                f.write(line)
                f.flush()
        
        exit_status = stdout.channel.recv_exit_status()
        
        # Fetch log from remote
        try:
            cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
            log_path = "/root/setup.log" if cloud_provider == 'scaleway' else "/home/ubuntu/setup.log"
            stdin, stdout, stderr = ssh.exec_command(f"cat {log_path}")
            remote_log = stdout.read().decode()
            with open(log_file, 'w') as f:
                f.write(remote_log)
        except Exception as e:
            logger.warning(f"Could not fetch remote log: {e}")
        
        ssh.close()
        
        # Detect if a reboot is required (written by the setup script into the log)
        try:
            with open(log_file, 'r') as _lf:
                _log_content = _lf.read()
            reboot_required = (
                "REBOOT_REQUIRED" in _log_content
                or "reboot required" in _log_content.lower()
                or "⚠️  WARNING: System reboot may be required" in _log_content
                or "Driver installed. A reboot may be required." in _log_content
            )
        except Exception:
            reboot_required = False

        # Write final status
        if exit_status == 0:
            if reboot_required:
                msg = (
                    "Setup completed, but a system reboot is required for the NVIDIA driver to take effect. "
                    "SSH into the instance and run: sudo reboot — then run Check once it's back up."
                )
                with open(status_file, 'w') as f:
                    json.dump({"status": "reboot_required", "message": msg}, f)
                logger.warning("[DEPLOY] Setup finished but reboot required on %s", request.ssh_host)
            else:
                with open(status_file, 'w') as f:
                    json.dump({"status": "completed", "message": "Setup completed successfully"}, f)
                logger.info("[DEPLOY] Setup completed successfully on %s", request.ssh_host)
                _update_workflow_phase(request.ssh_host, "setup")
        else:
            with open(status_file, 'w') as f:
                json.dump({"status": "failed", "message": f"Setup failed with exit status {exit_status}"}, f)
            logger.error("[DEPLOY] Setup failed with exit status %d on %s", exit_status, request.ssh_host)
            
    except Exception as e:
        with open(status_file, 'w') as f:
            json.dump({"status": "failed", "message": translate_error(str(e))}, f)
        logger.error("[DEPLOY] Setup failed on %s: %s", getattr(request, 'ssh_host', '?'), e, exc_info=True)

def workflow_check_task(request: CheckInstanceRequest, pem_file_path: str, log_dir: str):
    """Background task for check phase"""
    import paramiko
    import json
    import socket
    import time
    
    status_file = os.path.join(log_dir, "check_status.json")
    
    try:
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Starting check..."}, f)
        
        logger.info(f"🔍 Starting check on {request.ssh_host}")
        
        # Verify PEM file and load key (same logic as setup task)
        if not os.path.exists(pem_file_path):
            raise FileNotFoundError(f"PEM file not found: {pem_file_path}")
        
        try:
            current_mode = os.stat(pem_file_path).st_mode & 0o777
            if current_mode != 0o400 and current_mode != 0o600:
                os.chmod(pem_file_path, 0o400)
        except Exception as e:
            logger.warning(f"Could not set PEM file permissions: {e}")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Load key with proper error handling
        key = None
        key_errors = []
        for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey]:
            try:
                key = key_class.from_private_key_file(pem_file_path)
                break
            except Exception as e:
                key_errors.append(f"{key_class.__name__}: {str(e)}")
                continue
        
        if key is None:
            error_details = "; ".join(key_errors)
            raise ValueError(f"Failed to load SSH key from {pem_file_path}. Errors: {error_details}")
        
        logger.info(f"SSH key loaded successfully, attempting connection to {request.ssh_host} as {request.ssh_user}")
        
        # For Scaleway instances, allow more time and retries (same as setup task)
        cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
        ssh_timeout = 60 if cloud_provider == 'scaleway' else 30
        
        # Retry logic for SSH connection (Scaleway instances can take time)
        max_retries = 10 if cloud_provider == 'scaleway' else 2
        initial_delay = 15 if cloud_provider == 'scaleway' else 0
        retry_delay = 15  # seconds between retries
        
        logger.info(f"SSH connection parameters - Cloud: {cloud_provider}, Timeout: {ssh_timeout}s, Max retries: {max_retries}, Initial delay: {initial_delay}s")
        
        # Add initial delay for Scaleway instances
        if initial_delay > 0:
            logger.info(f"⏳ Waiting {initial_delay}s for Scaleway instance before SSH attempts...")
            time.sleep(initial_delay)
            logger.info(f"✅ Initial delay complete, starting SSH connection attempts...")
        
        # Port check function to verify SSH port is open
        def check_port_open(host, port, timeout=5):
            """Check if a port is open on the host"""
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((host, port))
                sock.close()
                return result == 0
            except Exception:
                return False
        
        # Retry loop for SSH connection
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 SSH connection attempt {attempt + 1}/{max_retries} to {request.ssh_host} as {request.ssh_user}...")
                
                # For Scaleway, do a port check first (non-blocking way to verify readiness)
                if cloud_provider == 'scaleway' and attempt > 0:
                    logger.info(f"🔍 Checking if SSH port 22 is open on {request.ssh_host}...")
                    port_open = check_port_open(request.ssh_host, 22, timeout=10)
                    if not port_open:
                        logger.info(f"⚠️  Port 22 not yet open on {request.ssh_host}, will retry after {retry_delay}s...")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay = int(retry_delay * 1.2)  # Exponential backoff
                            continue
                    else:
                        logger.info(f"✅ Port 22 is open on {request.ssh_host}, proceeding with SSH connection...")
                
                # Connect with the loaded key
                ssh.connect(
                    request.ssh_host,
                    username=request.ssh_user,
                    pkey=key,
                    timeout=ssh_timeout,
                    allow_agent=False,
                    look_for_keys=False
                )
                logger.info(f"✅ SSH connection established to {request.ssh_host} (attempt {attempt + 1}/{max_retries})")
                break  # Success, exit retry loop
            except (socket.timeout, paramiko.SSHException, Exception) as e:
                error_type = type(e).__name__
                logger.warning(f"❌ SSH connection attempt {attempt + 1}/{max_retries} failed ({error_type}): {str(e)}")
                
                if attempt < max_retries - 1:
                    logger.info(f"⏳ Waiting {retry_delay}s before retry {attempt + 2}/{max_retries}...")
                    time.sleep(retry_delay)
                    retry_delay = int(retry_delay * 1.2)  # Exponential backoff
                else:
                    # Last attempt failed
                    total_wait_time = initial_delay + (max_retries - 1) * retry_delay
                    logger.error(f"❌ All {max_retries} SSH connection attempts failed after ~{total_wait_time}s total wait time")
                    error_msg = (
                        f"SSH connection failed after {max_retries} attempts over ~{total_wait_time} seconds. "
                        f"Instance at {request.ssh_host} may not be accessible. "
                        f"Please verify: 1) Instance is in 'running' state, 2) Port 22 is open, "
                        f"3) SSH service is running on the server, 4) SSH key is correct"
                    )
                    raise RuntimeError(error_msg) from e
        sftp = ssh.open_sftp()
        
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
        if cloud_provider == 'scaleway':
            script_name = "lol_scaleway.sh"
            remote_check = "/root/lol_custom.sh"  # Scaleway uses root user
        else:
            script_name = "lol.sh"
            remote_check = "/home/ubuntu/lol_custom.sh"  # Lambda uses ubuntu user
        
        local_check = os.path.join(backend_dir, "scripts", script_name)
        
        if not os.path.exists(local_check):
            raise FileNotFoundError(f"{script_name} not found at {local_check}")
        
        logger.info(f"Using {script_name} for cloud provider: {cloud_provider}")
        
        sftp.put(local_check, remote_check)
        ssh.exec_command(f"chmod +x {remote_check}")
        
        sftp.close()
        
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Executing check script..."}, f)
        
        # Execute check script
        log_path = "/root/check.log" if cloud_provider == 'scaleway' else "/home/ubuntu/check.log"
        cmd = f"bash {remote_check} 2>&1 | tee {log_path}"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        
        log_file = os.path.join(log_dir, "check.log")
        with open(log_file, 'w') as f:
            for line in stdout:
                f.write(line)
                f.flush()
        
        exit_status = stdout.channel.recv_exit_status()
        
        # Fetch log
        try:
            log_path = "/root/check.log" if cloud_provider == 'scaleway' else "/home/ubuntu/check.log"
            stdin, stdout, stderr = ssh.exec_command(f"cat {log_path}")
            remote_log = stdout.read().decode()
            with open(log_file, 'w') as f:
                f.write(remote_log)
        except Exception as e:
            logger.warning(f"Could not fetch remote log: {e}")
        
        ssh.close()
        
        if exit_status == 0:
            with open(status_file, 'w') as f:
                json.dump({"status": "completed", "message": "Check completed successfully"}, f)
            logger.info("✅ Check completed successfully")
            _update_workflow_phase(request.ssh_host, "check",
                                   last_verified_at=datetime.utcnow().isoformat())
        else:
            with open(status_file, 'w') as f:
                json.dump({"status": "failed", "message": f"Check failed with exit status {exit_status}"}, f)
            logger.error(f"❌ Check failed with exit status {exit_status}")
            
    except RuntimeError:
        # Re-raise RuntimeErrors from the retry loop (they already have good error messages)
        raise
    except paramiko.AuthenticationException as e:
        error_msg = (
            f"SSH authentication failed to {request.ssh_host}: {str(e)}. "
            f"Please verify: 1) SSH key is correct and matches the server's authorized_keys, "
            f"2) User '{request.ssh_user}' exists on the server, "
            f"3) Key permissions are correct (should be 400 or 600)"
        )
        logger.error(error_msg)
        with open(status_file, 'w') as f:
            json.dump({"status": "failed", "message": error_msg}, f)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        with open(status_file, 'w') as f:
            json.dump({"status": "failed", "message": str(e)}, f)
        logger.error(f"❌ Check failed: {e}", exc_info=True)
        raise RuntimeError(f"Check failed: {str(e)}") from e

def workflow_deploy_task(request: DeployVLLMRequest, pem_file_path: str, log_dir: str):
    """Background task for deploy phase"""
    import paramiko
    import re
    import time
    import json
    
    status_file = os.path.join(log_dir, "deploy_status.json")
    
    try:
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Starting deploy..."}, f)
        
        logger.info(f"🚀 Starting deploy on {request.ssh_host}")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(request.ssh_host, username=request.ssh_user, key_filename=pem_file_path, timeout=30)
        sftp = ssh.open_sftp()
        
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Upload detect_gpu_info.sh
        cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
        remote_home = "/root" if cloud_provider == "scaleway" else "/home/ubuntu"
        deploy_log_path = f"{remote_home}/deploy.log"
        if cloud_provider == 'scaleway':
            remote_detect = "/root/detect_gpu_info.sh"  # Scaleway uses root user
            remote_deploy = "/root/lol4_custom.sh"
        else:
            remote_detect = "/home/ubuntu/detect_gpu_info.sh"  # Lambda uses ubuntu user
            remote_deploy = "/home/ubuntu/lol4_custom.sh"
        
        local_detect = os.path.join(backend_dir, "scripts", "detect_gpu_info.sh")
        if not os.path.exists(local_detect):
            raise FileNotFoundError(f"detect_gpu_info.sh not found at {local_detect}")
        sftp.put(local_detect, remote_detect)
        ssh.exec_command(f"chmod +x {remote_detect}")
        
        # Upload and modify lol4.sh or lol4_scaleway.sh
        if cloud_provider == 'scaleway':
            script_name = "lol4_scaleway.sh"
        else:
            script_name = "lol4.sh"
        
        local_deploy = os.path.join(backend_dir, "scripts", script_name)
        
        if not os.path.exists(local_deploy):
            raise FileNotFoundError(f"{script_name} not found at {local_deploy}")
        
        logger.info(f"Using {script_name} for cloud provider: {cloud_provider}")
        
        with open(local_deploy, 'r') as f:
            deploy_content = f.read()
        
        # Set MODEL_PATH
        deploy_content = re.sub(
            r'MODEL_PATH="\$\{MODEL_PATH:-[^"]+\}"',
            f'MODEL_PATH="{request.model_path}"',
            deploy_content
        )
        # Also update CONTAINER_MODEL_PATH to match the model basename
        model_basename = os.path.basename(request.model_path)
        deploy_content = re.sub(
            r'CONTAINER_MODEL_PATH="/models/[^"]+"',
            f'CONTAINER_MODEL_PATH="/models/{model_basename}"',
            deploy_content
        )
        # Update the MODEL_BASENAME calculation
        deploy_content = re.sub(
            r'MODEL_BASENAME=\$\(basename "\$MODEL_PATH"\)',
            f'MODEL_BASENAME="{model_basename}"',
            deploy_content
        )
        
        # Override parameters if provided
        if request.max_model_len:
            deploy_content = re.sub(
                r'MAX_MODEL_LEN=\$\(calculate_max_model_len.*?\)',
                f'MAX_MODEL_LEN={request.max_model_len}',
                deploy_content
            )
        
        if request.max_num_seqs:
            deploy_content = re.sub(
                r'MAX_NUM_SEQS=\$\(calculate_max_num_seqs.*?\)',
                f'MAX_NUM_SEQS={request.max_num_seqs}',
                deploy_content
            )
        
        if request.gpu_memory_utilization:
            deploy_content = re.sub(
                r'GPU_MEM_UTIL=\$\(calculate_gpu_memory_utilization.*?\)',
                f'GPU_MEM_UTIL={request.gpu_memory_utilization}',
                deploy_content
            )
        
        if request.tensor_parallel_size:
            deploy_content = re.sub(
                r'TENSOR_PARALLEL_SIZE=\$\(calculate_tensor_parallel_size.*?\)',
                f'TENSOR_PARALLEL_SIZE={request.tensor_parallel_size}',
                deploy_content
            )
        
        # Ensure detached mode
        deploy_content = deploy_content.replace('--rm -it --gpus', '--rm -d --gpus')
        
        with sftp.file(remote_deploy, 'w') as f:
            f.write(deploy_content)
        ssh.exec_command(f"chmod +x {remote_deploy}")
        
        sftp.close()
        
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Verifying model path exists..."}, f)
        
        # Verify model path exists before deploying
        check_model_cmd = f"test -d '{request.model_path}' && echo 'exists' || echo 'not_found'"
        stdin, stdout, stderr = ssh.exec_command(check_model_cmd)
        model_check = stdout.read().decode().strip()
        if "not_found" in model_check:
            error_msg = f"Model path does not exist: {request.model_path}. Please run Setup phase first."
            logger.error(error_msg)
            with open(status_file, 'w') as f:
                json.dump({"status": "failed", "message": error_msg}, f)
            ssh.close()
            return
        
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Executing deploy script..."}, f)
        
        # Execute deploy script
        cmd = f"bash {remote_deploy} 2>&1 | tee {deploy_log_path}"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        
        log_file = os.path.join(log_dir, "deploy.log")
        with open(log_file, 'w') as f:
            for line in stdout:
                f.write(line)
                f.flush()
        
        exit_status = stdout.channel.recv_exit_status()
        
        # Wait for server to be ready
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Waiting for vLLM server to be ready..."}, f)
        
        logger.info("Waiting for vLLM server to be ready...")
        max_wait = 600  # Increased to 10 minutes for large models
        wait_interval = 10  # Check every 10 seconds
        elapsed = 0
        server_ready = False
        container_running = False
        
        while elapsed < max_wait:
            time.sleep(wait_interval)
            elapsed += wait_interval
            
            # Check if container exists (running or exited) - use sudo to match script
            check_container_cmd = "sudo docker ps -a --filter name=vllm --format '{{.Status}}' 2>/dev/null || echo 'not_running'"
            stdin, stdout, stderr = ssh.exec_command(check_container_cmd)
            container_status = stdout.read().decode().strip()
            
            if "not_running" not in container_status and container_status:
                container_running = True
                # Check if container exited
                if "Exited" in container_status or "Dead" in container_status or "not_running" in container_status:
                    # Container crashed or doesn't exist, get logs
                    logger.error(f"Container exited or not found! Status: {container_status}")
                    try:
                        # Try to get logs from exited container
                        stdin, stdout, stderr = ssh.exec_command("sudo docker logs vllm --tail 100 2>&1")
                        container_logs = stdout.read().decode()
                        if not container_logs:
                            # Try to get logs by container ID if name doesn't work
                            stdin, stdout, stderr = ssh.exec_command("sudo docker ps -a --filter name=vllm --format '{{.ID}}' 2>/dev/null | head -1")
                            container_id = stdout.read().decode().strip()
                            if container_id:
                                stdin, stdout, stderr = ssh.exec_command(f"sudo docker logs {container_id} --tail 100 2>&1")
                                container_logs = stdout.read().decode()
                        logger.error(f"Container logs:\n{container_logs}")
                        container_log_file = os.path.join(log_dir, "vllm_container.log")
                        with open(container_log_file, 'w') as f:
                            f.write(container_logs)
                        with open(status_file, 'w') as f:
                            json.dump({"status": "failed", "message": f"Container exited. Check logs for details."}, f)
                        break
                    except Exception as e:
                        logger.error(f"Could not fetch container logs: {e}")
                        with open(status_file, 'w') as f:
                            json.dump({"status": "failed", "message": f"Container exited and could not fetch logs: {str(e)}"}, f)
                        break
                else:
                    # Container is running, check health
                    # Try /health first, then /v1/models, check for HTTP 200 or valid JSON
                    # Use a more robust check that combines both endpoints
                    check_cmd = """curl -s -f -m 5 http://localhost:8000/health 2>/dev/null && echo "HEALTH_OK" || (curl -s -f -m 5 http://localhost:8000/v1/models 2>/dev/null | head -1 && echo "MODELS_OK" || echo "FAILED")"""
                    stdin, stdout, stderr = ssh.exec_command(check_cmd)
                    check_output = stdout.read().decode().strip()
                    check_error = stderr.read().decode().strip()
                    
                    # Also check HTTP status code explicitly
                    http_check_cmd = "curl -s -o /dev/null -w '%{http_code}' -m 5 http://localhost:8000/health 2>/dev/null || curl -s -o /dev/null -w '%{http_code}' -m 5 http://localhost:8000/v1/models 2>/dev/null || echo '000'"
                    stdin2, stdout2, stderr2 = ssh.exec_command(http_check_cmd)
                    http_code = stdout2.read().decode().strip()
                    
                    # Server is ready if:
                    # 1. HTTP code is 200, OR
                    # 2. We get a valid response from health/models endpoint (not empty, not "FAILED")
                    is_ready = False
                    if http_code == "200":
                        is_ready = True
                        logger.info(f"✅ Health check passed: HTTP {http_code}")
                    elif check_output and "FAILED" not in check_output and len(check_output) > 0:
                        # Got a valid response (either health or models endpoint)
                        is_ready = True
                        logger.info(f"✅ Health check passed: Got valid response from server")
                    elif check_output and ("HEALTH_OK" in check_output or "MODELS_OK" in check_output):
                        is_ready = True
                        logger.info(f"✅ Health check passed: Endpoint responded")
                    
                    if is_ready:
                        server_ready = True
                        logger.info(f"✅ vLLM server is ready after {elapsed}s (HTTP {http_code})")
                        with open(status_file, 'w') as f:
                            json.dump({"status": "completed", "message": f"Deploy completed successfully - server ready after {elapsed}s"}, f)
                        break
                    else:
                        logger.debug(f"Health check not ready yet: http_code={http_code}, output={check_output[:100]}")
            else:
                # Container doesn't exist yet or never started
                # Check if it exited immediately by looking at all containers
                check_exited_cmd = "sudo docker ps -a --filter 'name=vllm' --format '{{.Status}}' 2>/dev/null | head -1 || echo 'not_found'"
                stdin, stdout, stderr = ssh.exec_command(check_exited_cmd)
                exited_status = stdout.read().decode().strip()
                if "Exited" in exited_status:
                    logger.error(f"Container exited immediately! Status: {exited_status}")
                    try:
                        stdin, stdout, stderr = ssh.exec_command("sudo docker logs vllm --tail 100 2>&1")
                        container_logs = stdout.read().decode()
                        logger.error(f"Container logs:\n{container_logs}")
                        container_log_file = os.path.join(log_dir, "vllm_container.log")
                        with open(container_log_file, 'w') as f:
                            f.write(container_logs)
                        with open(status_file, 'w') as f:
                            json.dump({"status": "failed", "message": "Container exited immediately. Check logs for details."}, f)
                        break
                    except:
                        pass
            
            status_msg = f"Waiting for server... ({elapsed}s/{max_wait}s)"
            if container_running:
                status_msg += " - Container running, checking health..."
                # Periodically fetch container logs to show progress (every 30 seconds)
                if elapsed % 30 == 0:
                    try:
                        # Use sudo to match the script
                        stdin, stdout, stderr = ssh.exec_command("sudo docker logs vllm --tail 20 2>&1")
                        container_logs = stdout.read().decode()
                        if not container_logs or "No such container" in container_logs:
                            # Try to find container by ID or check if it exited
                            stdin, stdout, stderr = ssh.exec_command("sudo docker ps -a --filter name=vllm --format '{{.ID}} {{.Status}}' 2>/dev/null | head -1")
                            container_info = stdout.read().decode().strip()
                            if container_info:
                                container_id = container_info.split()[0] if container_info else None
                                if container_id:
                                    stdin, stdout, stderr = ssh.exec_command(f"sudo docker logs {container_id} --tail 20 2>&1")
                                    container_logs = stdout.read().decode()
                        container_log_file = os.path.join(log_dir, "vllm_container.log")
                        with open(container_log_file, 'w') as f:
                            f.write(container_logs)
                        # Append to deploy log as well
                        with open(log_file, 'a') as f:
                            f.write(f"\n--- Container logs at {elapsed}s ---\n{container_logs}\n")
                    except Exception as e:
                        logger.warning(f"Could not fetch container logs: {e}")
            else:
                status_msg += " - Waiting for container to start..."
            
            with open(status_file, 'w') as f:
                json.dump({"status": "running", "message": status_msg}, f)
            logger.info(status_msg)
        
        # Fetch deploy log
        try:
            stdin, stdout, stderr = ssh.exec_command(f"cat {deploy_log_path}")
            remote_log = stdout.read().decode()
            with open(log_file, 'w') as f:
                f.write(remote_log)
        except Exception as e:
            logger.warning(f"Could not fetch remote log: {e}")
        
        # Fetch container logs if available (use sudo to match script)
        try:
            stdin, stdout, stderr = ssh.exec_command("sudo docker logs vllm --tail 100 2>&1")
            container_logs = stdout.read().decode()
            if not container_logs or "No such container" in container_logs:
                # Try to find by container ID
                stdin, stdout, stderr = ssh.exec_command("sudo docker ps -a --filter name=vllm --format '{{.ID}}' 2>/dev/null | head -1")
                container_id = stdout.read().decode().strip()
                if container_id:
                    stdin, stdout, stderr = ssh.exec_command(f"sudo docker logs {container_id} --tail 100 2>&1")
                    container_logs = stdout.read().decode()
            container_log_file = os.path.join(log_dir, "vllm_container.log")
            with open(container_log_file, 'w') as f:
                f.write(container_logs)
            logger.info(f"Saved container logs to {container_log_file}")
        except Exception as e:
            logger.warning(f"Could not fetch container logs: {e}")
        
        # Final status check before closing SSH
        if not server_ready and container_running:
            # One last check - maybe server became ready just now
            try:
                final_check_cmd = "curl -s -f -m 5 http://localhost:8000/health 2>/dev/null && echo 'READY' || echo 'NOT_READY'"
                stdin, stdout, stderr = ssh.exec_command(final_check_cmd)
                final_output = stdout.read().decode().strip()
                if "READY" in final_output:
                    server_ready = True
                    logger.info("✅ Server became ready on final check!")
            except Exception as e:
                logger.warning(f"Final health check failed: {e}")
        
        ssh.close()
        
        # Write final status
        if server_ready:
            with open(status_file, 'w') as f:
                json.dump({"status": "completed", "message": "Deploy completed successfully - vLLM server is ready"}, f)
            logger.info("✅ Deploy completed successfully")
            _update_workflow_phase(
                request.ssh_host, "vllm",
                vllm_model=getattr(request, "model_path", None),
            )
        else:
            error_msg = "Deploy failed - server did not become ready within timeout"
            if not container_running:
                error_msg = "Deploy failed - container did not start or exited"
            with open(status_file, 'w') as f:
                json.dump({"status": "failed", "message": error_msg}, f)
            logger.error(f"❌ {error_msg}")
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Deploy failed: {error_msg}", exc_info=True)
        try:
            with open(status_file, 'w') as f:
                json.dump({"status": "failed", "message": error_msg}, f)
        except Exception as write_error:
            logger.error(f"Failed to write status file: {write_error}")
        
        # Try to close SSH if still open
        try:
            if 'ssh' in locals() and ssh:
                ssh.close()
        except:
            pass

def _upload_agent_package_via_ssh(ssh, remote_home: str, log_func=None):
    """Upload agent.py + telemetry/ package to remote instance via SFTP.

    Returns the remote directory path where agent.py was placed.
    """
    import os as _os
    from pathlib import Path as _Path

    _log = log_func or logger.info
    backend_dir = _os.path.dirname(_os.path.abspath(__file__))
    scripts_dir = _os.path.join(backend_dir, "scripts", "scripts")
    remote_dir = f"{remote_home}/omni-agent"

    _log(f"Uploading agent package to {remote_dir} ...")
    ssh.exec_command(f"rm -rf {remote_dir} && mkdir -p {remote_dir}")
    import time; time.sleep(0.5)

    sftp = ssh.open_sftp()
    try:
        # Upload main scripts
        for fname in ["agent.py", "upload.py"]:
            local = _os.path.join(scripts_dir, fname)
            if _os.path.exists(local):
                sftp.put(local, f"{remote_dir}/{fname}")
                _log(f"  Uploaded {fname}")

        # Upload telemetry package recursively
        tel_dir = _os.path.join(scripts_dir, "telemetry")
        if _os.path.isdir(tel_dir):
            for root, dirs, files in _os.walk(tel_dir):
                rel = _os.path.relpath(root, scripts_dir).replace("\\", "/")
                remote_sub = f"{remote_dir}/{rel}"
                try:
                    sftp.mkdir(remote_sub)
                except IOError:
                    pass
                for f in files:
                    if f.endswith(".py"):
                        sftp.put(_os.path.join(root, f), f"{remote_sub}/{f}")
            _log("  Uploaded telemetry/ package")
    finally:
        sftp.close()

    return remote_dir


def _create_run_for_workflow(ssh_host: str, mode: str = "workload") -> tuple:
    """Create a telemetry run and return (run_id, ingest_token).

    Uses a direct HTTP call to the local backend API.
    """
    import urllib.request
    import json as _json

    api_base = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

    # We need a JWT token. Use a service-level approach:
    # First login as demo user to get a token, then create the run.
    demo_email = os.getenv("DEMO_ACCOUNT_EMAIL", "demo@omniference.com")
    demo_password = os.getenv("DEMO_ACCOUNT_PASSWORD", "demo")

    # Login
    login_req = urllib.request.Request(
        f"{api_base}/api/telemetry/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=_json.dumps({"email": demo_email, "password": demo_password}).encode(),
    )
    with urllib.request.urlopen(login_req, timeout=10) as resp:
        login_data = _json.loads(resp.read())
    jwt_token = login_data["access_token"]

    # Create run
    create_req = urllib.request.Request(
        f"{api_base}/api/telemetry/runs",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {jwt_token}",
        },
        data=_json.dumps({
            "instance_id": ssh_host,
            "run_type": mode,
        }).encode(),
    )
    with urllib.request.urlopen(create_req, timeout=10) as resp:
        run_data = _json.loads(resp.read())

    run_id = run_data["run_id"]
    ingest_token = run_data["ingest_token"]
    logger.info(f"Created {mode} run: run_id={run_id}")
    return run_id, ingest_token


def _run_agent_via_ssh(
    ssh, remote_dir: str, mode: str, run_id: str, ingest_token: str,
    backend_url: str, num_requests: int = 50, concurrency: int = 4,
    max_tokens: int = 200, kernel_requests: int = 20,
    log_file: str = "", status_file: str = "",
):
    """Execute agent.py on the remote instance and stream logs.

    Returns (exit_code, output_tail).
    """
    import json as _json
    import time

    extra_args = ""
    if mode == "standard":
        extra_args = f"--num-requests {num_requests} --concurrency {concurrency} --max-tokens {max_tokens}"
    elif mode == "kernel":
        extra_args = f"--kernel-requests {kernel_requests}"

    cmd = (
        f"cd {remote_dir} && python3 agent.py"
        f" --mode {mode}"
        f" {extra_args}"
        f" --backend-url {backend_url}"
        f" --run-id {run_id}"
        f" --ingest-token {ingest_token}"
        f" --skip-runara"
        f" --no-start-vllm"
        f" --skip-dcgm"
        f" 2>&1"
    )

    logger.info(f"Executing agent.py --mode {mode} on remote (run_id={run_id})")
    if status_file:
        with open(status_file, 'w') as f:
            _json.dump({"status": "running", "message": f"Running agent.py --mode {mode} ..."}, f)

    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=1800)

    # Stream output to log file
    output_lines = []
    if log_file:
        with open(log_file, 'w') as f:
            for line in stdout:
                output_lines.append(line)
                f.write(line)
                f.flush()
                line_lower = line.lower().strip()
                if any(kw in line_lower for kw in ['phase', '✓', '✗', '⚠', 'error', 'upload', 'complete', 'bottleneck']):
                    logger.info(f"Agent [{mode}]: {line.strip()}")
    else:
        for line in stdout:
            output_lines.append(line)

    exit_code = stdout.channel.recv_exit_status()
    output_tail = "".join(output_lines[-50:])

    logger.info(f"Agent --mode {mode} exited with code {exit_code}")
    return exit_code, output_tail


def workflow_benchmark_task(request: RunBenchmarkRequest, pem_file_path: str, log_dir: str):
    """Background task for benchmark phase — runs agent.py --mode standard.

    Uploads agent.py + telemetry/ package to the instance, creates a run,
    and executes agent.py to collect workload metrics (TTFT, TPOT, throughput,
    bottleneck analysis). Results are uploaded to the profiling API.
    """
    import paramiko
    import json
    import time

    status_file = os.path.join(log_dir, "benchmark_status.json")
    log_file = os.path.join(log_dir, "benchmark.log")

    try:
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Connecting to instance..."}, f)

        cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
        remote_home = "/root" if cloud_provider == "scaleway" else "/home/ubuntu"

        logger.info(f"Connecting to {request.ssh_host} as {request.ssh_user} ...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(request.ssh_host, username=request.ssh_user, key_filename=pem_file_path, timeout=30)

        # Step 1: Upload agent package
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Uploading agent package..."}, f)
        remote_dir = _upload_agent_package_via_ssh(ssh, remote_home)

        # Step 2: Create a run in the backend
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Creating profiling run..."}, f)
        backend_url = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
        run_id, ingest_token = _create_run_for_workflow(request.ssh_host, mode="workload")

        # Step 3: Execute agent.py --mode standard
        with open(status_file, 'w') as f:
            json.dump({
                "status": "running",
                "message": f"Running workload benchmark ({request.num_requests} requests, concurrency {request.max_concurrency})...",
                "run_id": run_id,
            }, f)

        exit_code, output_tail = _run_agent_via_ssh(
            ssh, remote_dir, mode="standard",
            run_id=run_id, ingest_token=ingest_token,
            backend_url=backend_url,
            num_requests=request.num_requests,
            concurrency=request.max_concurrency,
            max_tokens=request.output_seq_len,
            log_file=log_file, status_file=status_file,
        )

        ssh.close()

        if exit_code == 0:
            with open(status_file, 'w') as f:
                json.dump({
                    "status": "completed",
                    "message": "Benchmark completed successfully",
                    "run_id": run_id,
                }, f)
            logger.info(f"Benchmark completed: run_id={run_id}")
        else:
            with open(status_file, 'w') as f:
                json.dump({
                    "status": "failed",
                    "message": f"Agent exited with code {exit_code}",
                    "run_id": run_id,
                    "error_details": output_tail[-500:] if output_tail else "",
                }, f)
            logger.error(f"Benchmark failed: exit_code={exit_code}")

    except Exception as e:
        error_message = str(e)
        import traceback
        error_details = traceback.format_exc()[-1500:]
        with open(status_file, 'w') as f:
            json.dump({
                "status": "failed",
                "message": error_message,
                "error_details": error_details,
            }, f)
        try:
            with open(log_file, 'a') as f:
                f.write(f"\n\n=== ERROR ===\n{error_details}\n")
        except:
            pass
        logger.error(f"Benchmark failed: {error_message}", exc_info=True)



def workflow_kernel_profile_task(request: KernelProfileRequest, pem_file_path: str, log_dir: str):
    """Background task for kernel profiling — runs agent.py --mode kernel.

    Uploads agent.py + telemetry/ to the instance, creates a kernel-type run,
    and executes agent.py --mode kernel to capture CUDA kernel breakdown.
    """
    import paramiko
    import json

    status_file = os.path.join(log_dir, "kernel_profile_status.json")
    log_file = os.path.join(log_dir, "kernel_profile.log")

    try:
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Connecting to instance..."}, f)

        cloud_provider = getattr(request, 'cloud_provider', 'lambda').lower()
        remote_home = "/root" if cloud_provider == "scaleway" else "/home/ubuntu"

        logger.info(f"Connecting to {request.ssh_host} for kernel profiling ...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(request.ssh_host, username=request.ssh_user, key_filename=pem_file_path, timeout=30)

        # Step 1: Upload agent package
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Uploading agent package..."}, f)
        remote_dir = _upload_agent_package_via_ssh(ssh, remote_home)

        # Step 2: Create a kernel run
        with open(status_file, 'w') as f:
            json.dump({"status": "running", "message": "Creating kernel profiling run..."}, f)
        backend_url = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
        run_id, ingest_token = _create_run_for_workflow(request.ssh_host, mode="kernel")

        # Step 3: Execute agent.py --mode kernel
        with open(status_file, 'w') as f:
            json.dump({
                "status": "running",
                "message": f"Running kernel profiling ({request.kernel_requests} requests)...",
                "run_id": run_id,
            }, f)

        exit_code, output_tail = _run_agent_via_ssh(
            ssh, remote_dir, mode="kernel",
            run_id=run_id, ingest_token=ingest_token,
            backend_url=backend_url,
            kernel_requests=request.kernel_requests,
            log_file=log_file, status_file=status_file,
        )

        ssh.close()

        if exit_code == 0:
            with open(status_file, 'w') as f:
                json.dump({
                    "status": "completed",
                    "message": "Kernel profiling completed successfully",
                    "run_id": run_id,
                }, f)
            logger.info(f"Kernel profiling completed: run_id={run_id}")
        else:
            with open(status_file, 'w') as f:
                json.dump({
                    "status": "failed",
                    "message": f"Agent exited with code {exit_code}",
                    "run_id": run_id,
                    "error_details": output_tail[-500:] if output_tail else "",
                }, f)
            logger.error(f"Kernel profiling failed: exit_code={exit_code}")

    except Exception as e:
        error_message = str(e)
        import traceback
        error_details = traceback.format_exc()[-1500:]
        with open(status_file, 'w') as f:
            json.dump({
                "status": "failed",
                "message": error_message,
                "error_details": error_details,
            }, f)
        try:
            with open(log_file, 'a') as f:
                f.write(f"\n\n=== ERROR ===\n{error_details}\n")
        except:
            pass
        logger.error(f"Kernel profiling failed: {error_message}", exc_info=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
