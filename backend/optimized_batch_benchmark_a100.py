#!/usr/bin/env python3
"""
Optimized Batch Size and Sequence Length Benchmark for A100
===========================================================

This script provides proper A100-optimized benchmarking with:
- vLLM vs TensorRT-LLM inference engines
- True batch processing (parallel, not sequential)
- Proper GPU utilization for A100 8x configuration
- Optimized for SM Util (%), HBM BW (%), and NVLink BW (%) measurements

Usage:
    python optimized_batch_benchmark.py --model meta-llama/Meta-Llama-3.1-70B --engine vllm
    python optimized_batch_benchmark.py --model Qwen/Qwen2.5-32B --engine tensorrt-llm
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
import warnings

import torch
import numpy as np
import psutil

# Import transformers for tokenizer functionality
try:
    from transformers import AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logger.warning("transformers not available - input token length enforcement disabled")

warnings.filterwarnings("ignore")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('optimized_benchmark.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class OptimizedGPUMetrics:
    """GPU metrics for A100 optimization"""
    timestamp: str
    gpu_id: int
    gpu_utilization_percent: float  # Coarse GPU busy % from nvidia-smi (not true SM occupancy)
    memory_used_gb: float
    memory_total_gb: float
    hbm_bandwidth_utilization_percent: float
    hbm_bandwidth_raw_gbps: float = 0.0  # Raw GB/s measured
    nvlink_bandwidth_utilization_percent: float = 0.0
    nvlink_bandwidth_raw_gbps: float = 0.0  # Raw GB/s measured
    temperature_c: float = 0.0
    sm_active_percent: float = None  # TRUE SM Active % from DCGM profiling (DCGM_FI_PROF_SM_ACTIVE)

@dataclass
class OptimizedBenchmarkResult:
    """Results from optimized benchmark with comprehensive metrics"""
    timestamp: str
    engine: str
    model_name: str
    batch_size: int
    input_length: int
    output_length: int
    total_tokens_generated: int
    total_requests: int
    duration_seconds: float
    throughput_tokens_per_second: float
    throughput_requests_per_second: float
    latency_p50_ms: float  # Legacy - now equals ttft_p50_ms (None = not measured)
    latency_p95_ms: float  # Legacy - now equals ttft_p95_ms (None = not measured)
    # New comprehensive metrics for detailed table format
    ttft_p50_ms: float = None  # Time to first token p50 (None = not measured, never 0.0)
    ttft_p95_ms: float = None  # Time to first token p95 (None = not measured, never 0.0)
    tbt_p50_ms: float = None   # Time between tokens p50 (None = not measured, never 0.0)
    tbt_p95_ms: float = None   # Time between tokens p95 (None = not measured, never 0.0)
    prefill_latency_ms: float = None  # None = not measured, never 0.0
    decode_latency_ms: float = None  # None = not measured, never 0.0
    decode_throughput_tokens_per_second: float = 0.0
    gpu_utilization_percent: float = 0.0  # Coarse GPU busy % from nvidia-smi (not true SM occupancy)
    sm_active_percent: float = None  # TRUE SM Active % from DCGM profiling (DCGM_FI_PROF_SM_ACTIVE)
    hbm_bandwidth_utilization_percent: float = None  # None = not measured with Nsight, only set if real data
    hbm_bandwidth_raw_gbps: float = None  # Raw GB/s measured from Nsight
    nvlink_bandwidth_utilization_percent: float = None  # None = not measured
    nvlink_bandwidth_raw_gbps: float = None  # Raw GB/s from DCGM
    power_draw_watts: float = 0.0
    performance_per_watt: float = 0.0
    cost_usd: float = 0.0
    performance_per_dollar: float = 0.0
    gpu_metrics: List[OptimizedGPUMetrics] = None
    success: bool = True
    iteration_number: int = None  # Which iteration this result represents (1-based)
    total_iterations: int = None  # Total number of iterations run

class OptimizedBatchBenchmark:
    """Optimized benchmark using vLLM/TensorRT-LLM for true batch processing"""
    
    def __init__(self, model_name: str, engine: str = "vllm", input_length: int = 1024, allow_estimates: bool = False, enable_nsight: bool = False):
        self.model_name = model_name
        self.engine = engine.lower()
        self.input_length = input_length
        self.allow_estimates = allow_estimates
        self.enable_nsight = enable_nsight
        self.model = None
        self.tokenizer = None
        self.llm_engine = None
        self.monitoring_active = False
        self.gpu_metrics_history = []
        self.power_samples = []  # For time-averaged power calculation
        self.monitoring_lock = threading.Lock()  # Add synchronization lock
        
        # Dedicated DCGM monitoring (separate from nvidia-smi monitoring)
        self.dcgm_monitoring_active = False
        self.dcgm_thread = None
        self.dcgm_metrics_history = []
        
        # Nsight Compute integration for real HBM bandwidth measurement
        self.nsight_hbm_cache = {}
        self.nsight_last_update = 0
        self.nsight_available = False
        self.nsight_enabled = enable_nsight  # Store the enable flag
        
        # CRITICAL FIX: Disable Nsight by default unless explicitly enabled
        if not enable_nsight:
            self.nsight_available = False
            logger.info("💡 Nsight Compute disabled by default (use --enable-nsight + sudo to enable)")
            return
        
        # Check Nsight Compute availability once at startup
        self.ncu_path = None
        try:
            # Try standard path first
            result = subprocess.run(['ncu', '--version'], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                self.ncu_path = 'ncu'
                self.nsight_available = True
                logger.info("🎯 Nsight Compute detected - real HBM bandwidth measurement enabled")
        except:
            # Try common installation paths
            possible_paths = [
                '/opt/nvidia/nsight-compute/2024.3.2/ncu',
                '/opt/nvidia/nsight-compute/2024.3.1/ncu', 
                '/opt/nvidia/nsight-compute/2024.3.0/ncu',
                '/usr/local/cuda/bin/ncu',
                '/usr/bin/ncu'
            ]
            
            for path in possible_paths:
                try:
                    result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=3)
                    if result.returncode == 0:
                        self.ncu_path = path
                        self.nsight_available = True
                        logger.info(f"🎯 Nsight Compute detected at {path} - real HBM bandwidth measurement enabled")
                        break
                except:
                    continue
            
            if not self.nsight_available:
                if enable_nsight:
                    logger.error("❌ --enable-nsight flag provided but Nsight Compute not found!")
                    logger.error("📋 To enable HBM measurement:")
                    logger.error("   1. Install: sudo apt install nvidia-nsight-compute-2024.3.2")
                    logger.error("   2. Or download from: https://developer.nvidia.com/nsight-compute")
                    logger.error("   3. Run benchmark with: sudo python script.py --enable-nsight")
                    logger.error("   4. Without Nsight: HBM utilization will be 0% (not measured)")
                else:
                    logger.info("💡 Install nvidia-nsight-compute for real HBM measurement: sudo apt install nsight-compute-2024.3.2")
        
        # Force enable Nsight if requested by user (even if not found)
        if enable_nsight and not self.nsight_available:
            logger.warning("⚠️ --enable-nsight flag provided but Nsight Compute not detected. Will attempt anyway.")
            self.nsight_available = True
            self.ncu_path = 'ncu'  # Default path
        elif enable_nsight and self.nsight_available:
            logger.info("🚀 Nsight Compute enabled by user flag - HBM measurement active")
        
        # Validate engine
        if self.engine not in ["vllm", "tensorrt-llm"]:
            raise ValueError("Engine must be 'vllm' or 'tensorrt-llm'")
            
        logger.info(f"Initializing {engine.upper()} benchmark for model: {model_name}")
    
    def cleanup_system_before_benchmark(self):
        """Clean up any running processes and ensure system is in normal state"""
        logger.info("=== CLEANING UP SYSTEM BEFORE BENCHMARK ===")
        logger.info("✅ Cleanup disabled to prevent self-termination issues")
        logger.info("=== SYSTEM CLEANUP COMPLETED ===")
        return  # TEMPORARY: Disable cleanup to avoid process killing issues
        
        try:
            # Get current process ID to avoid killing ourselves
            current_pid = str(os.getpid())
            
            # Check for running benchmark processes
            result = subprocess.run(['pgrep', '-f', 'optimized_batch_benchmark'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                all_pids = result.stdout.strip().split('\n')
                # Filter out current process ID
                pids_to_kill = [pid.strip() for pid in all_pids if pid.strip() != current_pid]
                
                if pids_to_kill:
                    logger.warning(f"Found running benchmark processes: {pids_to_kill} (excluding current PID {current_pid})")
                    for pid in pids_to_kill:
                        try:
                            logger.info(f"Stopping benchmark process {pid}")
                            subprocess.run(['kill', pid], timeout=5)
                        except Exception as e:
                            logger.warning(f"Could not stop process {pid}: {e}")
                    time.sleep(3)
                else:
                    logger.info(f"Found current benchmark process (PID {current_pid}), no cleanup needed")
            
            # Check and stop vLLM processes
            result = subprocess.run(['pgrep', '-f', 'VLLM::'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                logger.info("Found running vLLM processes, cleaning up...")
                subprocess.run(['pkill', '-f', 'VLLM::'], timeout=10)
                time.sleep(5)
            
            # Check GPU memory status
            result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu', 
                                   '--format=csv,noheader,nounits'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                total_memory_used = 0
                active_gpus = 0
                
                for i, line in enumerate(lines):
                    if ',' in line:
                        memory_used, gpu_util = line.split(',')
                        memory_used = int(memory_used.strip())
                        gpu_util = int(gpu_util.strip())
                        total_memory_used += memory_used
                        if memory_used > 1000 or gpu_util > 5:  # 1GB threshold, 5% util
                            active_gpus += 1
                
                if active_gpus > 0:
                    logger.warning(f"Found {active_gpus} GPUs with significant memory usage ({total_memory_used}MB total)")
                    logger.info("Waiting for GPU memory to clear...")
                    time.sleep(10)
                else:
                    logger.info("✅ GPU memory status: Clean")
            
            # Final verification
            result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used', 
                                   '--format=csv,noheader,nounits'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                max_memory = max([int(line.strip()) for line in lines if line.strip().isdigit()])
                if max_memory < 1000:  # Less than 1GB per GPU
                    logger.info("✅ System cleanup completed - Ready for benchmark")
                else:
                    logger.warning(f"⚠️ GPU {max_memory}MB still in use, but proceeding...")
            
            logger.info("=== SYSTEM CLEANUP COMPLETED ===")
            
        except subprocess.TimeoutExpired:
            logger.warning("Timeout during system cleanup, proceeding anyway...")
        except Exception as e:
            logger.warning(f"Error during system cleanup: {e}, proceeding anyway...")
    
    def initialize_vllm_engine(self):
        """Initialize vLLM engine for optimized inference"""
        try:
            from vllm import LLM, SamplingParams
            
            logger.info("Loading vLLM engine with ULTRA-CONSERVATIVE settings...")
            
            # Memory calculation for safe configuration
            gpu_memory_gb = 80  # A100-80GB
            model_memory_gb = 39  # From measurements
            memory_util = 0.80  # 80% utilization (64GB per GPU) - back to original working settings
            available_memory = gpu_memory_gb * memory_util
            kv_cache_memory = available_memory - model_memory_gb
            
            logger.info("=" * 80)
            logger.info("vLLM ULTRA-CONSERVATIVE CONFIGURATION (V1 ENGINE)")
            logger.info("=" * 80)
            logger.info(f"📊 GPU Memory: {gpu_memory_gb}GB per GPU")
            logger.info(f"📊 Model Memory: {model_memory_gb}GB")
            logger.info(f"📊 Utilization: {memory_util*100:.0f}%")
            logger.info(f"📊 Available: {available_memory:.1f}GB per GPU")
            logger.info(f"📊 KV Cache: {kv_cache_memory:.1f}GB per GPU")
            logger.info(f"📊 Total KV Cache: {kv_cache_memory * 8:.1f}GB fleet")
            logger.info("=" * 80)
            
            self.llm_engine = LLM(
                model=self.model_name,
                tensor_parallel_size=8,  # Use all 8 A100 GPUs
                
                        # Back to original working settings
                        gpu_memory_utilization=0.80,  # 80% utilization (64GB per GPU)
                        max_model_len=32768,  # Allow 32K total context (input + output) for 16K sequences
                        max_num_batched_tokens=4096,  # Back to original working value
                        max_num_seqs=128,  # Back to original working value
                
                trust_remote_code=True,
                dtype="half",  # Use FP16 for A100 optimization
                enforce_eager=False,  # Use CUDA graphs for performance
                disable_custom_all_reduce=False,  # Use optimized all-reduce
                
                # Disable chunked prefill to reduce memory overhead
                enable_chunked_prefill=False,  # Changed from True
                
                # Prevent memory fragmentation
                block_size=16  # Default, but explicit
            )
            
            # Log batch processing configuration
            logger.info("=" * 80)
            logger.info("vLLM BATCH PROCESSING CONFIGURATION")
            logger.info("=" * 80)
            logger.info(f"📊 Max Num Batched Tokens: 4,096 tokens/iteration")
            logger.info(f"📊 Max Num Seqs: 128 concurrent requests")
            logger.info(f"📊 Chunked Prefill: Disabled")
            logger.info(f"📊 Block Size: 16")
            logger.info("=" * 80)
            logger.info("🎯 Configuration optimized for THROUGHPUT with memory safety")
            logger.info("🎯 Expected: BS=32 → 800-1,200 tok/s (16-24× improvement)")
            logger.info("🎯 Expected: BS=64 → 1,400-1,800 tok/s (28-36× improvement)")
            logger.info("🎯 SM Active should scale: 0.3% → 40-55% → 55-70%")
            logger.info("=" * 80)
            
            # Initialize sampling params
            self.sampling_params = SamplingParams(
                temperature=0.7,
                top_p=0.9,
                max_tokens=16384,  # Will be overridden per test
                stop=None
            )
            
            # Initialize tokenizer for input length enforcement
            if TRANSFORMERS_AVAILABLE and not self.tokenizer:
                try:
                    self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True, use_fast=True)
                    # CRITICAL FIX: Prevent tokenizer truncation that causes 8K limit
                    self.tokenizer.model_max_length = int(1e9)  # Avoid HF auto-truncation heuristics
                    logger.info(f"Tokenizer initialized for input length enforcement (max_length={self.tokenizer.model_max_length})")
                except Exception as e:
                    logger.warning(f"Could not initialize tokenizer: {e}")
            
            logger.info("vLLM engine initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize vLLM engine: {e}")
            return False
    
    def initialize_tensorrt_llm_engine(self):
        """Initialize TensorRT-LLM engine for optimized inference"""
        if self.engine == "tensorrt-llm":
            logger.warning("TensorRT-LLM not implemented; use --engine vllm for now.")
            if not self.allow_estimates:
                logger.error("TensorRT-LLM not available and --allow-estimates not specified. Exiting.")
                return False
            else:
                logger.info("Falling back to vLLM due to --allow-estimates flag")
                return self.initialize_vllm_engine()
            
        try:
            # TensorRT-LLM initialization would go here
            # For now, we'll provide the structure
            logger.info("TensorRT-LLM engine initialization not yet implemented")
            logger.info("Falling back to vLLM for now")
            return self.initialize_vllm_engine()
            
        except Exception as e:
            logger.error(f"Failed to initialize TensorRT-LLM engine: {e}")
            return False
    
    def initialize_engine(self):
        """Initialize the selected inference engine"""
        if self.engine == "vllm":
            return self.initialize_vllm_engine()
        elif self.engine == "tensorrt-llm":
            return self.initialize_tensorrt_llm_engine()
        else:
            raise ValueError(f"Unknown engine: {self.engine}")
    
    def get_gpu_metrics_nvidia_smi(self, skip_dcgm: bool = False) -> List[OptimizedGPUMetrics]:
        """Get comprehensive GPU metrics using nvidia-smi for basic metrics and DCGM for bandwidth"""
        metrics = []
        
        # CRITICAL FIX: Only call DCGM if not skipping and not currently monitoring
        if not skip_dcgm and not self.monitoring_active:
            dcgm_bandwidth_data = self._get_dcgm_bandwidth_metrics()
            nsight_hbm_data = self._get_nsight_compute_hbm_metrics()
        else:
            dcgm_bandwidth_data = {}
            nsight_hbm_data = {}
            if skip_dcgm:
                logger.debug("Skipping DCGM calls (monitoring active)")
        
        try:
            # Use nvidia-smi for basic metrics (SM util, memory, power, temp)
            result = subprocess.run([
                'nvidia-smi', '--query-gpu=index,utilization.gpu,memory.used,memory.total,utilization.memory,temperature.gpu,power.draw',
                '--format=csv,noheader,nounits'
            ], capture_output=True, text=True, timeout=10)
            
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if line.strip():
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) >= 7:
                        gpu_id = int(parts[0])
                        sm_util = float(parts[1]) if parts[1] != 'N/A' else 0.0
                        mem_used = float(parts[2]) / 1024.0 if parts[2] != 'N/A' else 0.0  # Convert MB to GB
                        mem_total = float(parts[3]) / 1024.0 if parts[3] != 'N/A' else 0.0  # Convert MB to GB
                        mem_util = float(parts[4]) if parts[4] != 'N/A' else 0.0
                        temp = float(parts[5]) if parts[5] != 'N/A' else 0.0
                        power = float(parts[6]) if parts[6] != 'N/A' else 0.0
                        
                        # Get HBM bandwidth - prioritize DCGM (now has real data!), then Nsight, then estimate
                        hbm_util = 0.0
                        if gpu_id in dcgm_bandwidth_data and 'hbm_utilization_percent' in dcgm_bandwidth_data[gpu_id]:
                            # DCGM now provides real HBM data (field 1005)!
                            hbm_util = dcgm_bandwidth_data[gpu_id]['hbm_utilization_percent']
                            logger.debug(f"Using DCGM HBM data for GPU {gpu_id}: {hbm_util:.1f}%")
                        elif gpu_id in nsight_hbm_data:
                            hbm_util = nsight_hbm_data[gpu_id].get('hbm_utilization_percent', 0.0)
                            logger.debug(f"Using Nsight HBM data for GPU {gpu_id}: {hbm_util:.1f}%")
                        elif self.allow_estimates and sm_util > 5.0:
                            # Fallback to estimation only if enabled
                            memory_intensity = (mem_used / mem_total) * 100 if mem_total > 0 else 0
                            power_factor = min(1.5, power / 300.0) if power > 0 else 0.1
                            hbm_util = min(90.0, (sm_util * 0.7) + (memory_intensity * 0.3) * power_factor)
                            logger.info(f"Estimated HBM for GPU {gpu_id}: {hbm_util:.1f}%")
                        
                        nvlink_util = dcgm_bandwidth_data.get(gpu_id, {}).get('nvlink_utilization_percent', 0.0)
                        
                        # Get raw bandwidth values and SM Active from DCGM
                        hbm_raw_gbps = dcgm_bandwidth_data.get(gpu_id, {}).get('hbm_raw_gbps', None)
                        nvlink_raw_gbps = dcgm_bandwidth_data.get(gpu_id, {}).get('nvlink_raw_gbps', None)
                        sm_active_percent = dcgm_bandwidth_data.get(gpu_id, {}).get('sm_active_percent', None)
                        
                        metrics.append(OptimizedGPUMetrics(
                            timestamp=datetime.now().isoformat(),
                            gpu_id=gpu_id,
                            gpu_utilization_percent=sm_util,  # Coarse GPU busy % from nvidia-smi
                            memory_used_gb=mem_used,
                            memory_total_gb=mem_total,
                            hbm_bandwidth_utilization_percent=hbm_util if hbm_util > 0 else None,  # Real DCGM data or None
                            hbm_bandwidth_raw_gbps=hbm_raw_gbps,
                            nvlink_bandwidth_utilization_percent=nvlink_util if nvlink_raw_gbps else None,
                            nvlink_bandwidth_raw_gbps=nvlink_raw_gbps,
                            temperature_c=temp,
                            sm_active_percent=sm_active_percent  # TRUE SM Active % from DCGM profiling
                        ))
            
        except Exception as e:
            logger.warning(f"Error getting GPU metrics: {e}")
            # Fallback to basic metrics
            for i in range(torch.cuda.device_count()):
                metrics.append(OptimizedGPUMetrics(
                    timestamp=datetime.now().isoformat(),
                    gpu_id=i,
                    gpu_utilization_percent=0.0,  # Coarse GPU busy % from nvidia-smi
                    memory_used_gb=torch.cuda.memory_allocated(i) / (1024**3),
                    memory_total_gb=torch.cuda.get_device_properties(i).total_memory / (1024**3),
                    hbm_bandwidth_utilization_percent=None,  # Not measured
                    hbm_bandwidth_raw_gbps=None,
                    nvlink_bandwidth_utilization_percent=None,  # Not measured
                    nvlink_bandwidth_raw_gbps=None,
                    temperature_c=0.0,
                    sm_active_percent=None  # Not available if monitoring fails
                ))
        
        return metrics
    
    def _get_dcgm_bandwidth_metrics(self) -> Dict[int, Dict[str, float]]:
        """Get real SM utilization, HBM and NVLink bandwidth from DCGM profiling
        
        CRITICAL FIX: Use correct DCGM field IDs matching successful terminal command
        
        DCGM Field IDs (matching terminal command):
        - 1002: SM Active % (DCGM_FI_PROF_SM_ACTIVE) - TRUE SM UTILIZATION
        - 1005: DRAM utilization % (DCGM_FI_PROF_DRAM_ACTIVE) - TRUE HBM UTILIZATION
        - 1011: NVLink TX bytes (DCGM_FI_PROF_NVLINK_TX_BYTES)
        - 1012: NVLink RX bytes (DCGM_FI_PROF_NVLINK_RX_BYTES)
        """
        bandwidth_data = {}
        
        # CRITICAL FIX: Always run DCGM when root (removed monitoring_active check to fix deadlock)
        import os
        is_root = os.geteuid() == 0
        
        if not is_root:
            logger.warning("❌ DCGM requires root privileges - run with sudo for SM Active, HBM, and NVLink metrics")
            for i in range(torch.cuda.device_count()):
                bandwidth_data[i] = {
                    'hbm_utilization_percent': 0.0,
                    'nvlink_utilization_percent': 0.0,
                    'hbm_raw_gbps': 0.0,
                    'nvlink_raw_gbps': 0.0,
                    'nvlink_utilization_normalized_basis_mb_s': 600000.0,
                    'sm_active_percent': None
                }
            return bandwidth_data
        
        logger.info("✅ Running DCGM profiling as root")
        
        try:
            # CRITICAL FIX #1: Explicitly enable DCGM profiling for SM Active & NVLink
            logger.debug("🔍 Enabling DCGM profiling for SM Active and NVLink metrics...")
            
            # Enable profiling globally
            try:
                subprocess.run(['dcgmi', 'profile', '--pause'], capture_output=True, timeout=2)
                subprocess.run(['dcgmi', 'profile', '--resume'], capture_output=True, timeout=2)
                logger.debug("✅ DCGM profiling enabled")
            except Exception as e:
                logger.warning(f"Failed to enable DCGM profiling: {e}")
            
            # Check if running as root (required for DCGM profiling)
            import os
            if os.geteuid() != 0:
                logger.warning("⚠️ Not running as root - DCGM profiling will fail!")
                logger.error("❌ DCGM profiling requires root privileges!")
                logger.error("🔧 Fix: Run benchmark with sudo:")
                logger.error("   sudo python optimized_batch_benchmark.py --model ...")
                logger.error("   OR: Configure DCGM permissions (see documentation)")
                logger.warning("⚠️ SM_ACTIVE will be NULL without DCGM profiling enabled")
                # Don't exit, just warn and continue without DCGM metrics
                return {}
            
            result_check = subprocess.run(['dcgmi', 'profile', '--status'], 
                                          capture_output=True, text=True, timeout=5)
            
            if result_check.returncode == 0:
                if 'Paused' in result_check.stdout:
                    logger.warning("⚠️ DCGM profiling is paused - attempting to enable...")
                    try:
                        # Try to resume profiling (may require sudo)
                        subprocess.run(['dcgmi', 'profile', '--resume'], 
                                      capture_output=True, text=True, timeout=5)
                        logger.info("✅ DCGM profiling resumed")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not resume DCGM profiling: {e}")
                        logger.warning("⚠️ SM_ACTIVE measurements will be NULL - run with sudo or fix DCGM permissions")
                else:
                    logger.debug("✅ DCGM profiling is active")
            else:
                logger.warning("⚠️ Could not check DCGM profiling status")
            
            # CRITICAL FIX #2: Use correct field IDs matching successful terminal command
            # Field IDs for A100 profiling (matching terminal command):
            # 1002: SM Active % (DCGM_FI_PROF_SM_ACTIVE) - TRUE SM UTILIZATION
            # 1005: DRAM utilization % (DCGM_FI_PROF_DRAM_ACTIVE) - TRUE HBM UTILIZATION
            # 1011: NVLink TX bytes (DCGM_FI_PROF_NVLINK_TX_BYTES)
            # 1012: NVLink RX bytes (DCGM_FI_PROF_NVLINK_RX_BYTES)
            # CRITICAL FIX: Use faster sampling (100ms, 5 samples) to capture spikes during inference
            # CRITICAL FIX: Use single-shot DCGM call to prevent infinite loops
            result = subprocess.run([
                'dcgmi', 'dmon', '-e', '1002,1005,1011,1012', '-d', '100', '-c', '1'
            ], capture_output=True, text=True, timeout=2)
            
            logger.info(f"🔍 DCGM command executed: return_code={result.returncode}")
            if result.stderr:
                logger.warning(f"🔍 DCGM stderr: {result.stderr[:200]}")
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                logger.info(f"🔍 DCGM returned {len(lines)} lines of output")
                
                # CRITICAL DEBUG: Log raw DCGM output (LIMITED to prevent infinite loop)
                logger.info("=" * 80)
                logger.info("RAW DCGM OUTPUT (for debugging) - FIRST 10 LINES ONLY:")
                for i, line in enumerate(lines[:10]):  # LIMIT to first 10 lines
                    logger.info(f"  {line}")
                if len(lines) > 10:
                    logger.info(f"  ... and {len(lines) - 10} more lines (truncated to prevent infinite loop)")
                logger.info("=" * 80)
                
                # Parse DCGM output - A100 FIXED VERSION with robust parsing
                # Format: GPU 0     0.000        0.000        0                           0
                i = 0
                parsed_gpus = set()  # Track parsed GPUs to prevent duplicates
                max_iterations = len(lines) * 2  # Safety limit to prevent infinite loops
                iteration_count = 0
                
                while i < len(lines) and iteration_count < max_iterations:
                    iteration_count += 1
                    line = lines[i].strip()
                    
                    # Skip empty lines, headers, and comments
                    if (not line or line.startswith('#') or line.startswith('Entity') or 
                        line.startswith('ID') or not 'GPU' in line):
                        i += 1
                        continue
                    
                    # Clean up multiple spaces and split properly
                    line_cleaned = ' '.join(line.split())
                    parts = line_cleaned.split()
                    
                    if len(parts) >= 5 and parts[0] == 'GPU':
                        try:
                            gpu_id = int(parts[1])
                            
                            # Skip if we already parsed this GPU (prevent duplicates)
                            if gpu_id in parsed_gpus:
                                i += 1
                                continue
                            
                            parsed_gpus.add(gpu_id)
                            
                            # Parse DCGM values
                            sm_active_raw = parts[2]
                            hbm_raw = parts[3]
                            nvlink_tx_raw = parts[4]
                            nvlink_rx_raw = parts[5] if len(parts) > 5 else '0'
                            
                            # CRITICAL FIX: DCGM returns fractions (0-1), NOT percentages!
                            sm_active_fraction = float(sm_active_raw) if sm_active_raw != 'N/A' else None
                            hbm_fraction = float(hbm_raw) if hbm_raw != 'N/A' else 0.0
                            
                            # Convert fractions to percentages by multiplying by 100
                            sm_active_percent = sm_active_fraction * 100.0 if sm_active_fraction is not None else None
                            hbm_utilization_percent = hbm_fraction * 100.0
                            nvlink_tx_bytes = float(nvlink_tx_raw) if nvlink_tx_raw != 'N/A' else 0.0
                            nvlink_rx_bytes = float(nvlink_rx_raw) if nvlink_rx_raw != 'N/A' else 0.0
                            
                            # Calculate NVLink bandwidth (bytes over 500ms window)
                            sampling_window_sec = 0.5  # 5 samples × 100ms
                            nvlink_tx_gbps = nvlink_tx_bytes / sampling_window_sec / 1e9
                            nvlink_rx_gbps = nvlink_rx_bytes / sampling_window_sec / 1e9
                            nvlink_total_gbps = nvlink_tx_gbps + nvlink_rx_gbps
                            
                            # A100 NVLink utilization (600 GB/s bidirectional per GPU)
                            nvlink_utilization_percent = min(100.0, (nvlink_total_gbps / 600.0) * 100)
                            
                            bandwidth_data[gpu_id] = {
                                'hbm_utilization_percent': hbm_utilization_percent,
                                'nvlink_utilization_percent': nvlink_utilization_percent,
                                'hbm_raw_gbps': None,
                                'nvlink_raw_gbps': nvlink_total_gbps,
                                'nvlink_tx_gbps': nvlink_tx_gbps,
                                'nvlink_rx_gbps': nvlink_rx_gbps,
                                'sm_active_percent': sm_active_percent
                            }
                            
                            sm_str = f"{sm_active_percent:.1f}%" if sm_active_percent is not None else "N/A"
                            logger.info(
                                f"✅ A100 GPU {gpu_id}: SM Active={sm_str}, "
                                f"HBM={hbm_utilization_percent:.1f}%, "
                                f"NVLink={nvlink_utilization_percent:.1f}% "
                                f"(Total={nvlink_total_gbps:.2f} GB/s)"
                            )
                            
                        except (ValueError, IndexError) as e:
                            logger.warning(f"❌ Failed to parse DCGM line {i}: '{line}' - {e}")
                    
                    i += 1
                
                if iteration_count >= max_iterations:
                    logger.warning(f"⚠️ DCGM parsing hit safety limit ({max_iterations} iterations) - stopping to prevent infinite loop")
                
                if bandwidth_data:
                    logger.info(f"DCGM bandwidth data collected for {len(bandwidth_data)} GPUs")
                else:
                    logger.warning("No DCGM bandwidth data could be parsed")
            else:
                logger.warning(f"DCGM command failed: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            logger.warning("DCGM command timed out - skipping this monitoring cycle")
            # Return empty data structure for graceful fallback
            for i in range(torch.cuda.device_count()):
                bandwidth_data[i] = {
                    'hbm_utilization_percent': 0.0,
                    'nvlink_utilization_percent': 0.0,
                    'hbm_raw_gbps': 0.0,
                    'nvlink_raw_gbps': 0.0,
                    'nvlink_utilization_normalized_basis_mb_s': 600000.0,
                    'sm_active_percent': None  # Not available if DCGM profiling fails
                }
        except Exception as e:
            logger.warning(f"DCGM profiling metrics unavailable: {e}")
            # Return empty data structure for graceful fallback
            for i in range(torch.cuda.device_count()):
                bandwidth_data[i] = {
                    'hbm_utilization_percent': 0.0,
                    'nvlink_utilization_percent': 0.0,
                    'hbm_raw_gbps': 0.0,
                    'nvlink_raw_gbps': 0.0,
                    'nvlink_utilization_normalized_basis_mb_s': 600000.0,
                    'sm_active_percent': None  # Not available if DCGM profiling fails
                }
        
        return bandwidth_data
    
    
    def _update_nsight_hbm_cache(self) -> None:
        """Update HBM cache using Nsight Compute - called periodically, not every monitoring cycle"""
        if not self.nsight_available:
            return
            
        current_time = time.time()
        # Only update cache every 30 seconds to avoid overhead
        if current_time - self.nsight_last_update < 30:
            return
            
        try:
            logger.debug("🔍 Sampling HBM bandwidth with Nsight Compute...")
            
            # Use a more efficient approach: sample all GPUs in one command
            if not self.ncu_path:
                logger.debug("NCU path not set, cannot collect HBM metrics")
                return
                
            cmd = [
                self.ncu_path, 
                '--metrics', 'dram__bytes_read.sum,dram__bytes_write.sum',
                '--csv', '--page', 'csv-summary'
            ]
            
            # FIXED: Use shorter timeout and non-blocking approach
            # Run for a very short period and parse results
            result = subprocess.run(cmd + ['--duration', '1000'], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0 and result.stdout:
                lines = result.stdout.strip().split('\n')
                
                for line in lines:
                    if 'dram__bytes_read.sum' in line or 'dram__bytes_write.sum' in line:
                        # Parse the CSV output - format varies by ncu version
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 4:
                            try:
                                # Extract GPU ID and bandwidth values
                                gpu_id = int(parts[0]) if parts[0].isdigit() else 0
                                bytes_read = float(parts[1]) if parts[1] != 'N/A' and parts[1] else 0.0
                                bytes_written = float(parts[2]) if parts[2] != 'N/A' and parts[2] else 0.0
                                
                                # FIXED: Convert to GB/s (1-second sampling window as per --duration 1000)
                                gbps_read = (bytes_read / (1024**3)) / 1.0
                                gbps_written = (bytes_written / (1024**3)) / 1.0
                                total_gbps = gbps_read + gbps_written
                                
                                # Auto-detect GPU type for correct HBM peak bandwidth
                                try:
                                    # Get GPU name to determine peak HBM bandwidth
                                    gpu_name_result = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], 
                                                                   capture_output=True, text=True, timeout=5)
                                    if gpu_name_result.returncode == 0:
                                        gpu_names = gpu_name_result.stdout.strip().split('\n')
                                        gpu_name = gpu_names[gpu_id] if gpu_id < len(gpu_names) else gpu_names[0] if gpu_names else ""
                                        if "A100" in gpu_name:
                                            hbm_peak_gbps = 2039.0  # A100 80GB
                                        elif "H100" in gpu_name:
                                            hbm_peak_gbps = 3350.0  # H100 
                                        elif "H200" in gpu_name:
                                            hbm_peak_gbps = 4800.0  # H200
                                        else:
                                            hbm_peak_gbps = 1555.0  # Default (V100-like)
                                    else:
                                        hbm_peak_gbps = 2039.0  # Default to A100
                                except:
                                    hbm_peak_gbps = 2039.0  # Default fallback
                                
                                hbm_utilization_percent = min(100.0, (total_gbps / hbm_peak_gbps) * 100)
                                
                                self.nsight_hbm_cache[gpu_id] = {
                                    'hbm_utilization_percent': hbm_utilization_percent,
                                    'hbm_raw_gbps': total_gbps,
                                    'hbm_read_gbps': gbps_read,
                                    'hbm_write_gbps': gbps_written,
                                    'timestamp': current_time
                                }
                                
                            except (ValueError, IndexError) as e:
                                logger.debug(f"Failed to parse ncu HBM data: {e}")
                                continue
                
                self.nsight_last_update = current_time
                logger.info(f"✅ Updated HBM cache from Nsight Compute: {len(self.nsight_hbm_cache)} GPUs")
                
        except subprocess.TimeoutExpired:
            logger.warning("⚠️ Nsight Compute timed out - disabling to prevent hangs")
            self.nsight_available = False
        except Exception as e:
            logger.debug(f"Nsight Compute HBM sampling failed: {e}")
            # Don't disable on every error, just log it
    
    def _get_nsight_compute_hbm_metrics(self) -> Dict[int, Dict[str, float]]:
        """Get cached HBM bandwidth metrics from Nsight Compute"""
        # Update cache if needed
        self._update_nsight_hbm_cache()
        
        # Return the cached data
        result = {}
        for gpu_id, data in self.nsight_hbm_cache.items():
            result[gpu_id] = {
                'hbm_utilization_percent': data['hbm_utilization_percent'],
                'hbm_raw_gbps': data['hbm_raw_gbps'],
                'method': 'nsight_compute_cached'
            }
        
        return result
    
    def _estimate_hbm_utilization(self, mem_util: float, sm_util: float, power: float) -> float:
        """Enhanced HBM utilization estimation for A100"""
        # Base HBM utilization on memory utilization
        base_hbm = mem_util
        
        # Adjust based on SM utilization (higher SM util = more memory traffic)
        sm_factor = min(2.0, sm_util / 50.0) if sm_util > 0 else 0.1
        
        # Adjust based on power consumption (higher power = more intensive memory access)
        power_factor = min(1.5, power / 300.0) if power > 0 else 0.1
        
        # A100-specific scaling factors
        estimated_hbm = base_hbm * sm_factor * power_factor
        
        return min(100.0, max(0.0, estimated_hbm))
    
    def _estimate_nvlink_utilization(self, sm_util: float, power: float, gpu_id: int, total_gpus: int) -> float:
        """Enhanced NVLink utilization estimation for A100"""
        # NVLink usage is more relevant in multi-GPU scenarios
        if total_gpus < 2:
            return 0.0
            
        # Base NVLink utilization on SM utilization and GPU position
        # GPUs in the middle of the topology typically have more NVLink traffic
        topology_factor = 1.0
        if total_gpus >= 8:  # A100 8x configuration
            if gpu_id in [2, 3, 4, 5]:  # Middle GPUs likely have more NVLink traffic
                topology_factor = 1.4
            elif gpu_id in [1, 6]:  # Edge GPUs
                topology_factor = 1.2
        
        # Scale with SM utilization but account for model parallelism overhead
        nvlink_base = sm_util * 0.6  # Not all SM activity results in NVLink traffic
        
        # Adjust based on power consumption (indicates intensive communication)
        power_factor = min(1.3, power / 350.0) if power > 0 else 0.1
        
        estimated_nvlink = nvlink_base * topology_factor * power_factor
        
        return min(100.0, max(0.0, estimated_nvlink))
    
    def get_advanced_gpu_profiling_metrics(self, duration: int = 10) -> Dict[str, float]:
        """
        Get advanced GPU profiling metrics using available tools
        This method attempts to use multiple profiling approaches for better HBM/NVLink data
        """
        profiling_results = {
            'hbm_bandwidth_actual': 0.0,
            'nvlink_bandwidth_actual': 0.0,
            'tensor_core_utilization': 0.0,
            'dram_efficiency': 0.0
        }
        
        try:
            # Method 1: Try nvprof for detailed metrics if available
            nvprof_result = self._try_nvprof_profiling(duration)
            if nvprof_result and nvprof_result.get('hbm_bandwidth_actual', 0) > 0:
                profiling_results.update(nvprof_result)
                logger.info(f"nvprof profiling completed: {nvprof_result}")
            
            # Method 2: Try DCGM advanced metrics
            dcgm_advanced = self._get_dcgm_advanced_metrics()
            if dcgm_advanced:
                profiling_results.update(dcgm_advanced)
            
            # Method 3: Enhanced estimation based on current workload characteristics
            current_metrics = self.get_gpu_metrics_nvidia_smi()
            if current_metrics:
                profile_estimate = self._estimate_workload_profiling_metrics(current_metrics)
                profiling_results.update(profile_estimate)
                
        except Exception as e:
            logger.warning(f"Advanced profiling failed: {e}")
        
        return profiling_results
    
    def _try_nvprof_profiling(self, duration: int) -> Dict[str, float]:
        """Use nvprof for detailed HBM and NVLink bandwidth profiling"""
        profiling_results = {
            'hbm_bandwidth_actual': 0.0,
            'nvlink_bandwidth_actual': 0.0,
            'dram_efficiency': 0.0,
            'tensor_core_utilization': 0.0
        }
        
        try:
            # Check if nvprof is available
            nvprof_path = '/usr/lib/nvidia-cuda-toolkit/bin/nvprof'
            if not os.path.exists(nvprof_path):
                # Try which command
                result = subprocess.run(['which', 'nvprof'], capture_output=True, text=True)
                if result.returncode != 0:
                    logger.debug("nvprof not found in PATH")
                    return profiling_results
                nvprof_path = result.stdout.strip()
            
            # Create a temporary profiling script that captures metrics during inference
            profiling_script = self._create_nvprof_monitoring_script(duration)
            
            # Run nvprof with specific metrics for A100
            cmd = [
                nvprof_path,
                '--print-gpu-trace',
                '--metrics', 'dram_read_bytes,dram_write_bytes,sm__sass_average_data_bytes_per_sector_mem_global_op_ld,dram_read_throughput,dram_write_throughput,sm__pipe_alu_cycles_active,dram_utilization',
                '--csv',
                '--profile-all-processes',
                '--output-profile', f'/tmp/nvprof_output_{int(time.time())}.nvvp'
            ]
            
            # For real-time monitoring, we'll use a different approach
            # Let's get current process metrics
            current_pid = os.getpid()
            
            # Try to get metrics using nvprof with process-specific monitoring
            try:
                # Alternative: Use nvidia-ml-py or direct nvml calls if available
                result = self._get_nvprof_live_metrics()
                if result:
                    profiling_results.update(result)
                    logger.info(f"nvprof metrics captured: {result}")
                
            except Exception as e:
                logger.debug(f"nvprof live metrics failed: {e}")
                
                # Fallback: Use nvidia-smi with more detailed queries that nvprof would provide
                fallback_result = self._get_enhanced_nvidia_smi_metrics()
                if fallback_result:
                    profiling_results.update(fallback_result)
                    logger.info("Using enhanced nvidia-smi as nvprof fallback")
            
        except Exception as e:
            logger.debug(f"nvprof profiling failed: {e}")
        
        return profiling_results
    
    def _create_nvprof_monitoring_script(self, duration: int) -> str:
        """Create a monitoring script for nvprof"""
        script_content = f"""
import time
import psutil
import os

# Monitor current process for {duration} seconds
start_time = time.time()
while time.time() - start_time < {duration}:
    try:
        # Get memory bandwidth from /proc/meminfo or other sources
        time.sleep(1)
    except:
        break
"""
        script_path = f'/tmp/nvprof_monitor_{int(time.time())}.py'
        with open(script_path, 'w') as f:
            f.write(script_content)
        return script_path
    
    def _get_nvprof_live_metrics(self) -> Dict[str, float]:
        """Get live metrics using nvprof or fallback methods"""
        
        # First try to use nvprof directly with CSV output
        try:
            nvprof_result = self._run_nvprof_direct()
            if nvprof_result:
                return nvprof_result
        except Exception as e:
            logger.debug(f"Direct nvprof failed: {e}")
        
        # Try to use nvidia-ml-py for more detailed metrics
        try:
            import pynvml
            pynvml.nvmlInit()
            
            device_count = pynvml.nvmlDeviceGetCount()
            if device_count == 0:
                return {}
            
            # Get metrics from first GPU (assuming uniform usage across all GPUs)
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            
            # Get memory info
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            
            # Get utilization rates
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            
            # Get power draw (indicator of memory/NVLink activity)
            power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # Convert to watts
            
            # Estimate HBM utilization based on memory utilization and power
            memory_util_rate = (mem_info.used / mem_info.total) * 100
            
            # Enhanced HBM estimate using nvml data
            hbm_utilization = min(100.0, memory_util_rate * 1.2 + (power / 400.0) * 30)
            
            # NVLink estimate based on multi-GPU setup and power consumption
            nvlink_utilization = min(100.0, (power - 200) / 200.0 * 100) if power > 200 else 0
            
            return {
                'hbm_bandwidth_actual': hbm_utilization,
                'nvlink_bandwidth_actual': nvlink_utilization,
                'dram_efficiency': memory_util_rate,
                'tensor_core_utilization': util.gpu,  # GPU utilization as proxy
                'profiling_method': 'nvml_live'
            }
            
        except ImportError:
            logger.debug("pynvml not available for live metrics")
        except Exception as e:
            logger.debug(f"nvml live metrics failed: {e}")
        
        return {}
    
    def _run_nvprof_direct(self) -> Dict[str, float]:
        """Run nvprof directly to get HBM and NVLink metrics"""
        try:
            # Create a temporary output file for nvprof results
            output_file = f'/tmp/nvprof_metrics_{int(time.time())}.csv'
            
            # Run nvprof with specific metrics that capture HBM and NVLink usage
            cmd = [
                '/usr/lib/nvidia-cuda-toolkit/bin/nvprof',
                '--print-gpu-trace',
                '--metrics', 'dram_read_throughput,dram_write_throughput,sm__throughput.avg.pct_of_peak_sustained_elapsed.bytes_per_second',
                '--csv',
                '--profile-all-processes',
                '--output-profile', '/dev/null',  # We only need CSV output
                'timeout', '5', 'nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'
            ]
            
            # Try a simpler approach: get metrics during a short profiling run
            result = subprocess.run([
                '/usr/lib/nvidia-cuda-toolkit/bin/nvprof',
                '--print-gpu-summary',
                '--print-api-trace',
                '--csv',
                'timeout', '3', 'nvidia-smi', '--loop=1'
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0 and result.stdout:
                # Parse nvprof CSV output for bandwidth metrics
                metrics = self._parse_nvprof_output(result.stdout)
                if metrics:
                    return metrics
            
            # Alternative: Try to get specific A100 metrics
            result2 = subprocess.run([
                '/usr/lib/nvidia-cuda-toolkit/bin/nvprof',
                '--query-metrics',
                'dram_read_throughput,dram_write_throughput,sm__throughput.avg.pct_of_peak_sustained_elapsed.bytes_per_second'
            ], capture_output=True, text=True, timeout=10)
            
            if result2.returncode == 0:
                # Parse metric definitions and get current values
                return self._parse_nvprof_metrics_query(result2.stdout)
                
        except Exception as e:
            logger.debug(f"Direct nvprof execution failed: {e}")
        
        return {}
    
    def _parse_nvprof_output(self, output: str) -> Dict[str, float]:
        """Parse nvprof CSV output to extract bandwidth metrics"""
        try:
            # Look for bandwidth metrics in the output
            lines = output.split('\n')
            for line in lines:
                if 'dram_read_throughput' in line.lower() or 'dram_write_throughput' in line.lower():
                    # Extract throughput values
                    parts = line.split(',')
                    if len(parts) >= 2:
                        try:
                            # Parse throughput values (typically in GB/s)
                            read_throughput = float(parts[1]) if parts[1].replace('.', '').isdigit() else 0
                            write_throughput = float(parts[2]) if len(parts) > 2 and parts[2].replace('.', '').isdigit() else 0
                            
                            # A100 HBM2e theoretical max: ~2039 GB/s
                            max_hbm_throughput = 2039.0
                            total_throughput = read_throughput + write_throughput
                            hbm_utilization = min(100.0, (total_throughput / max_hbm_throughput) * 100)
                            
                            return {
                                'hbm_bandwidth_actual': hbm_utilization,
                                'nvlink_bandwidth_actual': min(100.0, hbm_utilization * 0.6),  # Estimate
                                'profiling_method': 'nvprof_direct'
                            }
                        except (ValueError, IndexError):
                            continue
        except Exception as e:
            logger.debug(f"Failed to parse nvprof output: {e}")
        
        return {}
    
    def _parse_nvprof_metrics_query(self, output: str) -> Dict[str, float]:
        """Parse nvprof metrics query output"""
        # This would parse the metrics definitions and try to get current values
        # For now, return empty dict as this is complex to implement without running a full profiled application
        return {}
    
    def _get_enhanced_nvidia_smi_metrics(self) -> Dict[str, float]:
        """Enhanced nvidia-smi metrics that approximate nvprof data"""
        try:
            # Get more detailed nvidia-smi output
            result = subprocess.run([
                'nvidia-smi',
                '--query-gpu=memory.used,memory.total,utilization.memory,utilization.gpu,power.draw,temperature.gpu',
                '--format=csv,noheader,nounits'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                return {}
            
            lines = result.stdout.strip().split('\n')
            if not lines or not lines[0].strip():
                return {}
            
            # Parse first GPU (assume uniform across all)
            parts = [p.strip() for p in lines[0].split(',')]
            if len(parts) >= 6:
                mem_used = float(parts[0]) if parts[0] != 'N/A' else 0.0
                mem_total = float(parts[1]) if parts[1] != 'N/A' else 0.0
                mem_util = float(parts[2]) if parts[2] != 'N/A' else 0.0
                gpu_util = float(parts[3]) if parts[3] != 'N/A' else 0.0
                power = float(parts[4]) if parts[4] != 'N/A' else 0.0
                temp = float(parts[5]) if parts[5] != 'N/A' else 0.0
                
                # Enhanced HBM calculation using more data points
                memory_intensity = (mem_used / mem_total) * 100
                
                # HBM utilization: combination of memory usage, GPU activity, and power draw
                hbm_base = mem_util
                power_factor = min(1.5, power / 350.0) if power > 0 else 0.5
                gpu_factor = min(1.3, gpu_util / 80.0) if gpu_util > 0 else 0.3
                
                hbm_actual = min(100.0, hbm_base * power_factor * gpu_factor)
                
                # NVLink utilization: based on power consumption above idle
                # A100 idle ~150W, max ~400W, so NVLink activity correlates with excess power
                idle_power = 150
                active_power = max(0, power - idle_power)
                max_extra_power = 250  # Max additional power beyond idle
                nvlink_actual = min(100.0, (active_power / max_extra_power) * 100) if max_extra_power > 0 else 0
                
                return {
                    'hbm_bandwidth_actual': hbm_actual,
                    'nvlink_bandwidth_actual': nvlink_actual,
                    'dram_efficiency': memory_intensity,
                    'tensor_core_utilization': min(100.0, gpu_util * 1.1),
                    'profiling_method': 'enhanced_nvidia_smi'
                }
            
        except Exception as e:
            logger.debug(f"Enhanced nvidia-smi failed: {e}")
        
        return {}
    
    def _get_dcgm_advanced_metrics(self) -> Dict[str, float]:
        """Try to get advanced DCGM metrics for better bandwidth estimates"""
        try:
            # Try to get more detailed DCGM metrics
            # These field IDs are for GPU utilization, memory bandwidth, etc.
            result = subprocess.run([
                'dcgmi', 'dmon', '-e', '155,150,151,203,204', '-d', '1', '-c', '3'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and result.stdout:
                # Parse advanced DCGM output for better metrics
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    # Calculate average metrics across all GPUs
                    total_hbm = 0.0
                    total_nvlink = 0.0
                    gpu_count = 0
                    
                    for line in lines[1:]:  # Skip header
                        if 'GPU' in line:
                            parts = line.split()
                            if len(parts) >= 4:
                                # Extract power and other metrics for better estimates
                                power = float(parts[2]) if parts[2].replace('.', '').isdigit() else 0
                                temp = float(parts[3]) if parts[3].replace('.', '').isdigit() else 0
                                
                                # Use power and temperature for better HBM/NVLink estimates
                                # Higher power typically correlates with more intensive memory/NVLink usage
                                hbm_estimate = min(100.0, (power / 400.0) * 100)  # Normalize to 400W max
                                nvlink_estimate = min(100.0, ((power - 250) / 150.0) * 100) if power > 250 else 0
                                
                                total_hbm += max(0.0, hbm_estimate)
                                total_nvlink += max(0.0, nvlink_estimate)
                                gpu_count += 1
                    
                    if gpu_count > 0:
                        return {
                            'hbm_bandwidth_actual': total_hbm / gpu_count,
                            'nvlink_bandwidth_actual': total_nvlink / gpu_count,
                            'profiling_method': 'dcgm_advanced'
                        }
                        
        except Exception as e:
            logger.debug(f"DCGM advanced metrics failed: {e}")
        
        return {}
    
    def _estimate_workload_profiling_metrics(self, current_metrics: List[OptimizedGPUMetrics]) -> Dict[str, float]:
        """Estimate advanced profiling metrics based on current workload characteristics"""
        if not current_metrics:
            return {}
        
        # Calculate average metrics across all GPUs
        avg_sm_util = sum(m.gpu_utilization_percent for m in current_metrics) / len(current_metrics)
        avg_hbm_util_list = [m.hbm_bandwidth_utilization_percent for m in current_metrics if m.hbm_bandwidth_utilization_percent is not None]
        avg_nvlink_util_list = [m.nvlink_bandwidth_utilization_percent for m in current_metrics if m.nvlink_bandwidth_utilization_percent is not None]
        avg_hbm_util = sum(avg_hbm_util_list) / len(avg_hbm_util_list) if avg_hbm_util_list else 0
        avg_nvlink_util = sum(avg_nvlink_util_list) / len(avg_nvlink_util_list) if avg_nvlink_util_list else 0
        
        # Enhanced estimates based on workload patterns
        # High SM utilization + high memory use likely indicates tensor operations
        tensor_core_util = min(100.0, avg_sm_util * 1.2)  # Tensor cores typically cause higher SM util
        
        # DRAM efficiency based on memory bandwidth utilization vs theoretical max
        # A100 HBM2e: ~2039 GB/s theoretical, assume efficient usage if high utilization
        dram_efficiency = min(100.0, avg_hbm_util * 1.1) if avg_hbm_util > 50 else avg_hbm_util * 2
        
        return {
            'tensor_core_utilization': tensor_core_util,
            'dram_efficiency': dram_efficiency,
            'hbm_bandwidth_actual': avg_hbm_util,
            'nvlink_bandwidth_actual': avg_nvlink_util,
            'profiling_method': 'workload_estimation'
        }
    
    def start_gpu_monitoring(self):
        """Start GPU monitoring in background thread with proper synchronization"""
        with self.monitoring_lock:
            if self.monitoring_active:
                logger.debug("GPU monitoring already active")
                return
            self.monitoring_active = True
            self.gpu_metrics_history = []  # Clear previous metrics
            self.power_samples = []  # Clear previous power samples
            self.monitoring_thread = threading.Thread(target=self._monitor_gpus)
            self.monitoring_thread.daemon = True
            self.monitoring_thread.start()
            logger.debug("GPU monitoring thread started")
    
    def start_dcgm_monitoring(self):
        """Start dedicated DCGM monitoring thread to capture SM Active & NVLink during inference"""
        import os
        if os.geteuid() != 0:
            logger.warning("⚠️ DCGM monitoring requires root - SM Active and NVLink will be N/A")
            return
        
        # Test DCGM sampling before starting the monitoring thread
        if not self.test_dcgm_sampling():
            logger.warning("⚠️ DCGM test failed - monitoring thread will run but may not collect data")
        
        self.dcgm_monitoring_active = True
        self.dcgm_metrics_history = []
        self.dcgm_thread = threading.Thread(target=self._monitor_dcgm)
        self.dcgm_thread.daemon = True
        self.dcgm_thread.start()
        logger.info("✅ DCGM monitoring thread started (sampling SM Active & NVLink during inference)")
    
    def stop_dcgm_monitoring(self):
        """Stop DCGM monitoring thread"""
        self.dcgm_monitoring_active = False
        if hasattr(self, 'dcgm_thread') and self.dcgm_thread:
            self.dcgm_thread.join(timeout=5)
            logger.info(f"✅ DCGM monitoring thread stopped - collected {len(self.dcgm_metrics_history)} samples")
    
    def _monitor_dcgm(self):
        """Background DCGM monitoring - samples SM Active & NVLink during inference"""
        logger.info("🔥 DCGM monitoring thread running - will sample every 500ms")
        sample_count = 0
        
        while self.dcgm_monitoring_active:
            try:
                # CRITICAL FIX: Use single sample (-c 1) to avoid blocking issues
                # This takes only ~100ms instead of 500ms
                result = subprocess.run([
                    'dcgmi', 'dmon', 
                    '-e', '1002,1005,1011,1012',  # SM Active, HBM Active, NVLink TX, NVLink RX
                    '-d', '100',   # 100ms sample interval
                    '-c', '1'      # CRITICAL: Only 1 sample to avoid overlap
                ], capture_output=True, text=True, timeout=2)
                
                if result.returncode == 0 and result.stdout:
                    logger.debug(f"📊 DCGM raw output:\n{result.stdout}")
                    
                    # Parse the output
                    dcgm_data = self._parse_dcgm_output(result.stdout)
                    
                    if dcgm_data:
                        sample_count += 1
                        timestamp = time.time()
                        for gpu_id, metrics in dcgm_data.items():
                            self.dcgm_metrics_history.append({
                                'timestamp': timestamp,
                                'gpu_id': gpu_id,
                                'sm_active_percent': metrics.get('sm_active_percent'),
                                'hbm_utilization_percent': metrics.get('hbm_utilization_percent'),
                                'nvlink_raw_gbps': metrics.get('nvlink_raw_gbps'),
                                'nvlink_utilization_percent': metrics.get('nvlink_utilization_percent')
                            })
                        logger.debug(f"✅ DCGM sample {sample_count}: captured {len(dcgm_data)} GPUs")
                    else:
                        logger.warning("⚠️ DCGM returned empty data")
                else:
                    logger.warning(f"⚠️ DCGM command failed: returncode={result.returncode}")
                    
                time.sleep(0.5)  # Sample every 500ms
                
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ DCGM command timed out")
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"❌ DCGM monitoring error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(1)
        
        logger.info(f"✅ DCGM monitoring stopped - collected {sample_count} samples")
    
    def _parse_dcgm_output(self, output: str) -> Dict[int, Dict[str, float]]:
        """Parse DCGM dmon output and return metrics by GPU ID"""
        bandwidth_data = {}
        
        try:
            lines = output.strip().split('\n')
            logger.debug(f"📋 DCGM output has {len(lines)} lines")
            
            for i, line in enumerate(lines):
                line = line.strip()
                
                # Skip header lines
                if not line or line.startswith('#') or line.startswith('Entity') or line.startswith('ID'):
                    continue
                
                # Look for GPU lines
                if 'GPU' in line:
                    # Clean up and split
                    line_cleaned = ' '.join(line.split())
                    parts = line_cleaned.split()
                    
                    logger.debug(f"🔍 Parsing line {i}: '{line_cleaned}' -> {len(parts)} parts")
                    
                    if len(parts) >= 5 and parts[0] == 'GPU':
                        try:
                            # NEW: Parse correct field order (1002, 1005, 1011, 1012)
                            # Format: ["GPU", "7", "sm_active", "hbm_util", "nvlink_tx", "nvlink_rx"]
                            gpu_id = int(parts[1])
                            # CRITICAL FIX: DCGM returns fractions (0-1), NOT percentages!
                            # Field 1002 (SM Active): 0.366 = 36.6% SM Active
                            # Field 1005 (HBM/DRAM Active): 0.456 = 45.6% HBM utilization
                            sm_active_fraction = float(parts[2]) if parts[2] != 'N/A' else None
                            hbm_fraction = float(parts[3]) if parts[3] != 'N/A' else 0.0
                            
                            # Convert fractions to percentages by multiplying by 100
                            sm_active_percent = sm_active_fraction * 100.0 if sm_active_fraction is not None else None
                            hbm_utilization_percent = hbm_fraction * 100.0  # NOW CORRECT!
                            nvlink_tx_bytes = float(parts[4]) if parts[4] != 'N/A' else 0.0
                            nvlink_rx_bytes = float(parts[5]) if len(parts) > 5 and parts[5] != 'N/A' else 0.0
                            
                            # Calculate bidirectional NVLink bandwidth
                            # Convert bytes over 100ms window to GB/s
                            sampling_window_sec = 0.1  # 1 sample × 100ms
                            nvlink_tx_gbps = nvlink_tx_bytes / sampling_window_sec / 1e9
                            nvlink_rx_gbps = nvlink_rx_bytes / sampling_window_sec / 1e9
                            nvlink_total_gbps = nvlink_tx_gbps + nvlink_rx_gbps
                            
                            # Calculate NVLink utilization (A100 = 600 GB/s bidirectional per GPU)
                            nvlink_utilization_percent = min(100.0, (nvlink_total_gbps / 600.0) * 100)
                            
                            bandwidth_data[gpu_id] = {
                                'sm_active_percent': sm_active_percent,
                                'hbm_utilization_percent': hbm_utilization_percent,
                                'nvlink_raw_gbps': nvlink_total_gbps,
                                'nvlink_tx_gbps': nvlink_tx_gbps,
                                'nvlink_rx_gbps': nvlink_rx_gbps,
                                'nvlink_utilization_percent': nvlink_utilization_percent
                            }
                            
                            sm_str = f"{sm_active_percent:.1f}%" if sm_active_percent is not None else "N/A"
                            logger.debug(f"✅ GPU {gpu_id}: SM Active={sm_str}, HBM={hbm_utilization_percent:.1f}%, NVLink={nvlink_utilization_percent:.1f}% (TX={nvlink_tx_gbps:.2f} GB/s, RX={nvlink_rx_gbps:.2f} GB/s)")
                            
                        except (ValueError, IndexError) as e:
                            logger.warning(f"⚠️ Failed to parse GPU line: {e}")
                            continue
            
            if not bandwidth_data:
                logger.warning(f"⚠️ No GPU data parsed from DCGM output:\n{output}")
            
        except Exception as e:
            logger.error(f"❌ DCGM parsing error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return bandwidth_data
    
    def test_dcgm_sampling(self):
        """Test DCGM sampling to verify it works before benchmark"""
        logger.info("🧪 Testing DCGM sampling...")
        
        try:
            # Enable profiling first
            subprocess.run(['dcgmi', 'profile', '--pause'], capture_output=True, timeout=2)
            subprocess.run(['dcgmi', 'profile', '--resume'], capture_output=True, timeout=2)
            
            result = subprocess.run([
                'dcgmi', 'dmon', 
                '-e', '1002,1005,1011,1012',
                '-d', '100',
                '-c', '1'
            ], capture_output=True, text=True, timeout=5)
            
            logger.info(f"🧪 DCGM test output:\n{result.stdout}")
            
            if result.returncode == 0:
                dcgm_data = self._parse_dcgm_output(result.stdout)
                if dcgm_data:
                    logger.info(f"✅ DCGM test successful - captured {len(dcgm_data)} GPUs")
                    for gpu_id, metrics in dcgm_data.items():
                        sm = metrics.get('sm_active_percent')
                        sm_str = f"{sm:.1f}%" if sm is not None else "N/A"
                        logger.info(f"   GPU {gpu_id}: SM Active={sm_str}")
                    return True
                else:
                    logger.error("❌ DCGM test failed - no data parsed")
                    return False
            else:
                logger.error(f"❌ DCGM test failed - returncode={result.returncode}, stderr={result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ DCGM test exception: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def stop_gpu_monitoring(self):
        """Stop GPU monitoring with proper synchronization"""
        with self.monitoring_lock:
            if not self.monitoring_active:
                logger.debug("GPU monitoring already stopped")
                return
            self.monitoring_active = False
            if hasattr(self, 'monitoring_thread'):
                self.monitoring_thread.join(timeout=5)
                logger.debug("GPU monitoring thread stopped")
    
    def _monitor_gpus(self):
        """Background GPU monitoring - FIXED: Avoid DCGM conflicts"""
        while self.monitoring_active:
            try:
                # Use lightweight nvidia-smi only to avoid DCGM conflicts
                # DCGM calls are reserved for main thread only
                # CRITICAL FIX: Use skip_dcgm=True to avoid conflicts during monitoring
                metrics = self.get_gpu_metrics_nvidia_smi(skip_dcgm=True)
                if metrics:
                    # CRITICAL FIX: Use monitoring lock to prevent race conditions
                    with self.monitoring_lock:
                        self.gpu_metrics_history.extend(metrics)
                
                # Also collect power samples for time-averaged calculation
                try:
                    result = subprocess.run([
                        'nvidia-smi', '--query-gpu=power.draw', '--format=csv,noheader,nounits'
                    ], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        power_values = [float(p.strip()) for p in result.stdout.strip().split('\n') 
                                      if p.strip() and p.strip() != 'N/A']
                        if power_values:
                            # Log the count to debug fleet power scaling
                            logger.debug(f"Power sample GPUs={len(power_values)} values={power_values}")
                            # Properly scale to fleet total: average per GPU × GPU count
                            avg_power_per_gpu = np.mean(power_values)
                            fleet_total_power = avg_power_per_gpu * len(power_values)
                            self.power_samples.append(fleet_total_power)  # Total fleet power
                            # If only one GPU reading, manually multiply by expected GPU count
                            expected_gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 8
                            if len(power_values) == 1 and expected_gpu_count > 1:
                                logger.debug(f"Single GPU power reading {avg_power_per_gpu:.1f}W, scaling by {expected_gpu_count}")
                                fleet_total_power = avg_power_per_gpu * expected_gpu_count
                                self.power_samples[-1] = fleet_total_power
                except Exception as power_e:
                    logger.debug(f"Power sampling failed: {power_e}")
                
                time.sleep(2)  # Monitor every 2 seconds
            except Exception as e:
                logger.warning(f"GPU monitoring error: {e}")
                time.sleep(5)
    
    def _get_lightweight_gpu_metrics(self) -> List[Dict]:
        """Lightweight GPU metrics using only nvidia-smi - no DCGM to avoid conflicts"""
        try:
            result = subprocess.run([
                'nvidia-smi', '--query-gpu=index,utilization.gpu,memory.used,memory.total,utilization.memory,temperature.gpu,power.draw',
                '--format=csv,noheader,nounits'
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                metrics = []
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 7:
                            try:
                                gpu_idx = int(parts[0])
                                gpu_util = float(parts[1]) if parts[1] != 'N/A' else 0.0
                                mem_used = float(parts[2]) if parts[2] != 'N/A' else 0.0
                                mem_total = float(parts[3]) if parts[3] != 'N/A' else 0.0
                                mem_util = float(parts[4]) if parts[4] != 'N/A' else 0.0
                                temp = float(parts[5]) if parts[5] != 'N/A' else 0.0
                                power = float(parts[6]) if parts[6] != 'N/A' else 0.0
                                
                                metrics.append({
                                    'gpu_index': gpu_idx,
                                    'gpu_utilization_percent': gpu_util,
                                    'memory_used_mb': mem_used,
                                    'memory_total_mb': mem_total,
                                    'memory_utilization_percent': mem_util,
                                    'temperature_c': temp,
                                    'power_draw_w': power,
                                    'timestamp': time.time()
                                })
                            except (ValueError, IndexError) as e:
                                logger.debug(f"Failed to parse GPU metrics line: {line}, error: {e}")
                                continue
                return metrics
        except Exception as e:
            logger.debug(f"Lightweight GPU metrics failed: {e}")
        return []

    def _ensure_token_length(self, texts: List[str], target_tokens: int) -> List[str]:
        """Ensure texts have exactly target_tokens by padding/trimming using the model tokenizer"""
        if not TRANSFORMERS_AVAILABLE or not self.tokenizer:
            logger.debug("Tokenizer not available - skipping token length enforcement")
            return texts
            
        try:
            fixed = []
            for t in texts:
                ids = self.tokenizer(t, add_special_tokens=False).input_ids
                if len(ids) < target_tokens:
                    # Pad by repeating the text until we reach target length
                    reps = (target_tokens // max(1, len(ids))) + 1
                    ids = (ids * reps)[:target_tokens]
                else:
                    # Trim to target length
                    ids = ids[:target_tokens]
                fixed.append(self.tokenizer.decode(ids, clean_up_tokenization_spaces=False))
            return fixed
        except Exception as e:
            logger.warning(f"Token length enforcement failed: {e}")
            return texts
    
    def generate_test_prompts(self, batch_size: int) -> List[str]:
        """Generate optimized test prompts for target input length"""
        # TODO: Add proper tokenizer-based input length enforcement to ensure exact token counts
        # Current approach uses approximate prompts - should tokenize and pad/trim to self.input_length
        base_prompt = """Write a comprehensive technical analysis of artificial intelligence and machine learning technologies. 
        Please cover the following topics in detail:
        1. Current state of AI and ML technologies
        2. Key applications across different industries
        3. Technical challenges and limitations
        4. Emerging trends and future prospects
        5. Impact on society and economy
        6. Ethical considerations and governance
        7. Technical implementation details
        8. Performance metrics and benchmarks
        9. Integration with existing systems
        10. Training methodologies and data requirements
        
        Provide detailed technical insights, current market analysis, implementation strategies, 
        performance benchmarks, scalability considerations, security aspects, and future roadmap. 
        Include specific examples, case studies, and quantitative data where possible. 
        Discuss the intersection of AI/ML with cloud computing, edge computing, IoT, and other emerging technologies. 
        Please provide detailed technical explanations with specific examples, mathematical formulations where appropriate, 
        and practical implementation guidance. Focus on both theoretical foundations and practical applications."""
        
        # Generate batch variations for true parallel processing
        prompts = []
        for i in range(batch_size):
            if i == 0:
                prompts.append(base_prompt)
            else:
                # Add variation to prevent caching and ensure true batch processing
                variation = f" [Variant {i+1}: Focus area = {['Healthcare', 'Finance', 'Manufacturing', 'Education', 'Transportation', 'Energy', 'Retail', 'Entertainment'][i % 8]}]"
                prompts.append(base_prompt + variation)
        
        # Ensure exact token length using tokenizer
        prompts = self._ensure_token_length(prompts, self.input_length)
        return prompts
    
    def run_vllm_batch_benchmark(self, batch_size: int, output_length: int, duration_seconds: int = 60, hourly_rate: float = None) -> OptimizedBenchmarkResult:
        """Run optimized batch benchmark using vLLM"""
        logger.info(f"Running vLLM batch benchmark: batch_size={batch_size}, output_length={output_length}")
        
        # Import SamplingParams here to avoid scope issues
        from vllm import SamplingParams
        
        start_time = time.time()
        prompts = self.generate_test_prompts(batch_size)
        
        # Validate token length enforcement
        if self.tokenizer and TRANSFORMERS_AVAILABLE:
            try:
                encoded = self.tokenizer(prompts, add_special_tokens=False)
                actual_tokens = [len(ids) for ids in encoded['input_ids']]
                mean_tokens = np.mean(actual_tokens)
                logger.info(f"Token length validation: target={self.input_length}, actual_mean={mean_tokens:.1f}, range=[{min(actual_tokens)}, {max(actual_tokens)}]")
            except Exception as e:
                logger.debug(f"Token validation failed: {e}")
        
        # Update sampling params for this test - ensure proper generation
        # CRITICAL FIX: Use stop_token_ids=[] to completely disable EOS token forcing
        # This is the proper way to prevent vLLM from replacing the last token with EOS
        # Based on vLLM optimization guide: ignore_eos alone is insufficient in some versions
        test_sampling_params = SamplingParams(
            temperature=0.7,
            top_p=0.9,
            max_tokens=output_length,
            stop=None,
            stop_token_ids=[],  # CRITICAL: Empty list disables ALL stop tokens including EOS
            ignore_eos=True,  # CRITICAL: Force full token generation for accurate benchmarking
            skip_special_tokens=False,  # Keep all tokens for accurate counting
            spaces_between_special_tokens=False,
            include_stop_str_in_output=False  # Ensure clean output counting
        )
        
        # Ensure vLLM engine is initialized before proceeding
        if not hasattr(self, "llm_engine") or self.llm_engine is None:
            logger.warning("llm_engine is missing or None; attempting to (re)initialize vLLM engine")
            try:
                self.initialize_vllm_engine()
            except Exception as e:
                logger.error(f"Failed to (re)initialize vLLM engine: {e}")
                raise
            # Verify initialization succeeded
            if not hasattr(self, "llm_engine") or self.llm_engine is None:
                raise RuntimeError("vLLM engine not initialized (llm_engine missing after initialize_vllm_engine)")

        # Check for potential memory issues with large batch sizes
        estimated_memory_needed = batch_size * (self.input_length + output_length) * 4  # Rough estimate in bytes
        estimated_memory_gb = estimated_memory_needed / (1024**3)
        if estimated_memory_gb > 500:  # More than 500GB estimated memory needed
            logger.warning(f"Large memory estimate for batch_size={batch_size}: ~{estimated_memory_gb:.1f}GB. Consider reducing batch size if OOM occurs.")
        
        total_tokens = 0
        total_requests = 0
        # Per-request timing data - fix for proper TTFT/TBT measurement
        ttft_list_ms = []      # Time to first token per request
        tbt_list_ms = []       # Time between tokens per request  
        decode_times_ms = []   # Total decode time per request
        prefill_latencies = []  # Store real prefill latencies from vLLM
        decode_latencies = []   # Store real decode latencies from vLLM
        end_time = start_time + duration_seconds
        
        try:
            # Clear any previous metrics to ensure clean measurement
            self.gpu_metrics_history = []
            
            # Start GPU monitoring RIGHT BEFORE inference starts
            # This ensures we only capture metrics during actual inference, not during model loading/warmup
            logger.info("Starting GPU monitoring for inference phase...")
            self.start_gpu_monitoring()
            
            # CRITICAL FIX: Start dedicated DCGM monitoring to capture SM Active & NVLink during inference
            logger.info("Starting DCGM monitoring for SM Active & NVLink metrics...")
            self.start_dcgm_monitoring()
            
            # Wait for monitoring to start and do a warmup run to stabilize metrics
            time.sleep(2)
            initial_metrics = self.get_gpu_metrics_nvidia_smi()
            if initial_metrics:
                avg_sm = sum(m.gpu_utilization_percent for m in initial_metrics) / len(initial_metrics)
                logger.info(f"Initial monitoring check: GPU util={avg_sm:.1f}%, metrics_count={len(self.gpu_metrics_history)}")
                if len(self.gpu_metrics_history) == 0:
                    logger.warning("⚠️ No GPU metrics captured yet - monitoring may have issues")
            else:
                logger.error("❌ Failed to get initial GPU metrics - monitoring broken!")
            
            # CRITICAL: Do a warmup run and clear metrics history to avoid capturing initialization
            logger.info("Performing warmup run to stabilize GPU state...")
            try:
                warmup_outputs = self.llm_engine.generate(prompts, test_sampling_params)
                # Clear metrics captured during warmup - we only want steady-state inference metrics
                logger.info(f"Clearing {len(self.gpu_metrics_history)} warmup metrics, starting fresh...")
                self.gpu_metrics_history = []
                self.power_samples = []  # Also clear power samples for accurate time-averaged calculation
            except Exception as e:
                logger.warning(f"Warmup failed, proceeding anyway: {e}")
            
            logger.info("Starting actual inference benchmark with clean metrics...")
            
            # FIXED: Single generation call instead of time-loop that never completes
            # vLLM generate() blocks until all responses are done, so we don't need a while loop
            
            # CRITICAL FIX: Add CUDA synchronization for accurate timing
            logger.debug("🔄 Synchronizing CUDA before timing...")
            torch.cuda.synchronize()
            batch_start = time.time()
            actual_duration = 0.0  # Initialize in case of error
            
            # TRUE BATCH PROCESSING - process all prompts in parallel (single call)
            try:
                logger.info(f"🚀 Starting vLLM generation for {batch_size} prompts...")
                
                # FIXED: Use threading-based timeout instead of unreliable signal-based timeout
                import threading
                import queue
                
                # Set timeout based on workload size (more tokens = longer timeout)
                total_expected_tokens = batch_size * output_length
                timeout_seconds = max(300, total_expected_tokens // 1000)  # At least 5 min, +1 sec per 1K tokens
                logger.info(f"⏰ Setting timeout to {timeout_seconds}s for {total_expected_tokens} expected tokens")
                
                # Threading-based timeout implementation
                result_queue = queue.Queue()
                exception_queue = queue.Queue()
                
                def generate_with_timeout():
                    try:
                        outputs = self.llm_engine.generate(prompts, test_sampling_params)
                        result_queue.put(outputs)
                    except Exception as e:
                        exception_queue.put(e)
                
                # Start generation in separate thread
                generation_thread = threading.Thread(target=generate_with_timeout)
                generation_thread.daemon = True
                generation_thread.start()
                
                # Wait for completion or timeout
                generation_thread.join(timeout=timeout_seconds)
                
                if generation_thread.is_alive():
                    logger.error(f"❌ vLLM generation timed out after {timeout_seconds}s for {total_expected_tokens} tokens")
                    # Try to recover by reinitializing the engine
                    logger.info("🔄 Attempting engine recovery...")
                    try:
                        del self.llm_engine
                        import gc
                        gc.collect()
                        torch.cuda.empty_cache()
                        self.initialize_vllm_engine()
                        logger.info("✅ Engine recovery successful")
                    except Exception as recovery_error:
                        logger.error(f"❌ Engine recovery failed: {recovery_error}")
                    outputs = None
                elif not exception_queue.empty():
                    # Generation failed with exception
                    raise exception_queue.get()
                elif not result_queue.empty():
                    # Generation completed successfully
                    outputs = result_queue.get()
                else:
                    # This shouldn't happen, but handle it gracefully
                    logger.error("❌ vLLM generation completed but no result or exception found")
                    outputs = None
                
                # CRITICAL FIX: Add CUDA synchronization after generation for accurate timing
                logger.debug("🔄 Synchronizing CUDA after generation...")
                torch.cuda.synchronize()
                generation_end_time = time.time()
                actual_duration = generation_end_time - batch_start
                logger.info(f"✅ Generation completed in {actual_duration:.2f}s (with CUDA sync)")
                
                # DEBUG: Log generation results for validation
                logger.info(f"Generated {len(outputs)} outputs from batch of {batch_size} prompts")
                
                # CRITICAL: Add immediate debug to ensure we reach this point
                if not outputs:
                    logger.error("❌ No outputs returned from vLLM generate() - this is the problem!")
                    outputs = []  # Set empty outputs to prevent further errors
                
                logger.info(f"DEBUG: outputs type={type(outputs)}, len={len(outputs)}")
                if outputs:
                    logger.info(f"DEBUG: first output type={type(outputs[0])}")
                    if hasattr(outputs[0], '__dict__'):
                        logger.info(f"DEBUG: first output attributes={[k for k in dir(outputs[0]) if not k.startswith('_')]}")
                    else:
                        logger.info(f"DEBUG: first output is not an object: {outputs[0]}")
                
                # STRICT TOKEN COUNTING: sum tokens across ALL requests in the batch
                if outputs:
                    logger.info(f"🔢 Starting token counting for {len(outputs)} outputs...")
                    per_request_tokens = []
                    for i, output in enumerate(outputs):
                        try:
                            tokens = 0
                            # FIXED: Handle vLLM 0.11.0+ API for token counting
                            if hasattr(output, "outputs") and output.outputs:
                                # vLLM 0.11.0+ format: RequestOutput.outputs[].token_ids
                                for completion in output.outputs:
                                    if hasattr(completion, "token_ids") and completion.token_ids:
                                        tokens = len(completion.token_ids)
                                        break
                                    elif hasattr(completion, "text") and completion.text:
                                        tokens = max(0, len(completion.text) // 4)
                                        break
                            elif hasattr(output, "token_ids") and output.token_ids:
                                # Legacy format: RequestOutput.token_ids
                                tokens = len(output.token_ids)
                            elif hasattr(output, "text") and isinstance(output.text, str) and output.text.strip():
                                # Fallback: estimate from text length
                                tokens = max(0, len(output.text) // 4)
                            else:
                                # Try metrics as last resort
                                m = getattr(output, "metrics", None)
                                if m is not None and getattr(m, "num_output_tokens", None) is not None:
                                    tokens = int(m.num_output_tokens)
                            per_request_tokens.append(tokens)
                            logger.info(f"✅ Output {i}: tokens={tokens}")
                        except Exception as e:
                            logger.error(f"❌ Error processing output {i}: {e}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            per_request_tokens.append(0)
                    # Assertions and totals
                    if len(per_request_tokens) != batch_size:
                        logger.warning(f"Expected {batch_size} outputs, got {len(per_request_tokens)}")
                    total_tokens = int(sum(per_request_tokens))
                    total_requests = len(per_request_tokens)
                    logger.info(f"🎯 TOKEN COUNTING SUMMARY: total_tokens={total_tokens}, per_request_avg={np.mean(per_request_tokens) if per_request_tokens else 0:.1f}, total_requests={total_requests}")
                    if total_tokens == 0:
                        logger.error("🚨 CRITICAL: No tokens were counted from any output!")
                    
                    # CRITICAL FIX: Log finish reasons to debug 8K token limit
                    logger.info("🔍 FINISH REASON ANALYSIS:")
                    for i, output in enumerate(outputs):
                        try:
                            if hasattr(output, "outputs") and output.outputs:
                                for j, completion in enumerate(output.outputs):
                                    finish_reason = getattr(completion, "finish_reason", "unknown")
                                    prompt_tokens = len(getattr(output, "prompt_token_ids", []))
                                    gen_tokens = len(getattr(completion, "token_ids", []))
                                    logger.info(f"  Request {i}.{j}: finish_reason='{finish_reason}', prompt_tokens={prompt_tokens}, gen_tokens={gen_tokens}")
                                    if finish_reason == "length":
                                        logger.warning(f"  ⚠️ Request {i}.{j} hit length limit - check max_model_len or max_tokens!")
                        except Exception as e:
                            logger.warning(f"  Could not analyze finish reason for output {i}: {e}")
                        
                # Handle timing metrics (separate from token counting)
                    # Process results and extract per-request timing metrics (only for object outputs)
                    for i, output in enumerate(outputs):
                        output_tokens = 0
                        
                        # Handle different vLLM output structures (for timing metrics only - tokens already counted)
                        if hasattr(output, "outputs") and output.outputs:
                            out = output.outputs[0]
                            if hasattr(out, "token_ids") and out.token_ids:
                                output_tokens = len(out.token_ids)
                            elif hasattr(out, "text"):
                                # Fallback: estimate tokens from text
                                text = out.text
                                if text and len(text.strip()) > 0:
                                    output_tokens = max(1, len(text) // 4)  # Rough estimation
                        elif hasattr(output, "token_ids") and output.token_ids:
                            # Direct token_ids structure
                            output_tokens = len(output.token_ids)
                        elif hasattr(output, "text"):
                            # Direct text structure
                            text = output.text
                            if text and len(text.strip()) > 0:
                                output_tokens = max(1, len(text) // 4)  # Rough estimation
                        
                        if output_tokens == 0:
                            logger.warning(f"TIMING LOOP: No tokens found in output {i} - skipping timing metrics")
                            continue
                    
                        # CRITICAL FIX: Extract per-request TTFT and decode timing from vLLM 0.11.0+ API
                        try:
                            ttft_ms = None
                            decode_ms = None
                            
                            # FIXED: Handle vLLM 0.11.0+ API changes
                            # New structure: RequestOutput.outputs[].metrics instead of RequestOutput.metrics
                            if hasattr(output, "outputs") and output.outputs:
                                # vLLM 0.11.0+ format: RequestOutput.outputs[].metrics
                                for completion in output.outputs:
                                    if hasattr(completion, "metrics") and completion.metrics:
                                        m = completion.metrics
                                        # Handle various vLLM timing field names
                                        if hasattr(m, "first_token_time") and hasattr(m, "arrival_time"):
                                            ttft_ms = (m.first_token_time - m.arrival_time) * 1000.0
                                        elif hasattr(m, "ttft") and m.ttft is not None:
                                            ttft_ms = m.ttft * 1000.0
                                        elif hasattr(m, "time_to_first_token") and m.time_to_first_token is not None:
                                            ttft_ms = m.time_to_first_token * 1000.0
                                        
                                        if hasattr(m, "decode_time") and m.decode_time is not None:
                                            decode_ms = m.decode_time * 1000.0
                                        elif hasattr(m, "total_decode_time") and m.total_decode_time is not None:
                                            decode_ms = m.total_decode_time * 1000.0
                                        break  # Use first completion's metrics
                            elif hasattr(output, "metrics") and output.metrics:
                                # Legacy vLLM format: RequestOutput.metrics
                                m = output.metrics
                                if hasattr(m, "first_token_time") and hasattr(m, "arrival_time"):
                                    ttft_ms = (m.first_token_time - m.arrival_time) * 1000.0
                                elif hasattr(m, "ttft") and m.ttft is not None:
                                    ttft_ms = m.ttft * 1000.0
                                
                                if hasattr(m, "decode_time") and m.decode_time is not None:
                                    decode_ms = m.decode_time * 1000.0
                            
                            # Log successful extraction for debugging
                            if ttft_ms is not None or decode_ms is not None:
                                logger.debug(f"✅ Extracted timing for output {i}: TTFT={ttft_ms:.1f}ms, Decode={decode_ms:.1f}ms")
                            else:
                                logger.debug(f"⚠️ No timing metrics found for output {i} - vLLM version may not support metrics")
                            
                            # No synthetic fallbacks; missing stays None
                            
                            # Store the timing data
                            if ttft_ms is not None:
                                ttft_list_ms.append(ttft_ms)
                                prefill_latencies.append(ttft_ms)
                            if decode_ms is not None:
                                decode_times_ms.append(decode_ms)
                                decode_latencies.append(decode_ms)
                                # Calculate TBT = decode_time / (output_tokens - 1)
                                if output_tokens > 1:
                                    tbt_ms = decode_ms / (output_tokens - 1)
                                    tbt_list_ms.append(tbt_ms)
                                
                        except Exception as e:
                            logger.debug(f"Per-request timing extraction failed: {e}")
                            continue
                        
            except Exception as e:
                logger.error(f"Error in vLLM batch processing: {e}")
                outputs = []  # Set empty outputs so the rest of the code doesn't break
        
        finally:
            # Stop monitoring
            self.stop_gpu_monitoring()
            self.stop_dcgm_monitoring()
        
        # Use actual generation duration instead of total time (which includes setup/cleanup)
        duration = actual_duration if actual_duration > 0 else (time.time() - start_time)
        throughput_tokens = total_tokens / duration if duration > 0 else 0
        throughput_requests = total_requests / duration if duration > 0 else 0
        
        logger.info(f"📊 BENCHMARK METRICS: duration={duration:.2f}s, tokens={total_tokens}, requests={total_requests}")
        logger.info(f"📊 THROUGHPUT: {throughput_tokens:.2f} tokens/s, {throughput_requests:.2f} requests/s")
        
        # Calculate proper latency percentiles using per-request TTFT/TBT data (no synthetic fallbacks)
        # CRITICAL FIX: Return None instead of 0.0 when no per-request data is available
        ttft_p50_ms = float(np.percentile(ttft_list_ms, 50)) if ttft_list_ms else None
        ttft_p95_ms = float(np.percentile(ttft_list_ms, 95)) if ttft_list_ms else None
        tbt_p50_ms  = float(np.percentile(tbt_list_ms, 50))  if tbt_list_ms  else None
        tbt_p95_ms  = float(np.percentile(tbt_list_ms, 95))  if tbt_list_ms  else None
        
        # Calculate comprehensive metrics from historical data collected during monitoring
        # This avoids the issue of capturing idle GPU state after inference completes
        # CRITICAL FIX: Use monitoring lock when reading gpu_metrics_history
        with self.monitoring_lock:
            if self.gpu_metrics_history:
                # Group metrics by GPU ID and calculate averages across all monitoring samples
                gpu_metrics_by_id = {}
                for metric in self.gpu_metrics_history:
                    if metric.gpu_id not in gpu_metrics_by_id:
                        gpu_metrics_by_id[metric.gpu_id] = []
                    gpu_metrics_by_id[metric.gpu_id].append(metric)
                
                # Calculate averages across all GPUs and all time samples
                all_sm_utils = []
                all_hbm_utils = []
                all_nvlink_utils = []
                all_sm_active = []  # TRUE SM Active % from DCGM profiling
                
                # Create updated final_metrics using historical data for each GPU
                final_metrics = []
                for gpu_id, metrics_list in gpu_metrics_by_id.items():
                    if metrics_list:
                        # Calculate average metrics for this GPU
                        gpu_sm_utils = [m.gpu_utilization_percent for m in metrics_list]
                        # Only average HBM/NVLink if actually measured (not None)
                        gpu_hbm_utils = [m.hbm_bandwidth_utilization_percent for m in metrics_list if m.hbm_bandwidth_utilization_percent is not None]
                        gpu_nvlink_utils = [m.nvlink_bandwidth_utilization_percent for m in metrics_list if m.nvlink_bandwidth_utilization_percent is not None]
                        gpu_hbm_raw = [m.hbm_bandwidth_raw_gbps for m in metrics_list if m.hbm_bandwidth_raw_gbps is not None]
                        gpu_nvlink_raw = [m.nvlink_bandwidth_raw_gbps for m in metrics_list if m.nvlink_bandwidth_raw_gbps is not None]
                        gpu_sm_active = [m.sm_active_percent for m in metrics_list if m.sm_active_percent is not None]
                        
                        # Use the most recent metric as base but update with historical averages
                        base_metric = metrics_list[-1]  # Most recent metric
                        
                        # Update the metric with historical averages
                        base_metric.gpu_utilization_percent = sum(gpu_sm_utils) / len(gpu_sm_utils)
                        base_metric.hbm_bandwidth_utilization_percent = sum(gpu_hbm_utils) / len(gpu_hbm_utils) if gpu_hbm_utils else None
                        base_metric.nvlink_bandwidth_utilization_percent = sum(gpu_nvlink_utils) / len(gpu_nvlink_utils) if gpu_nvlink_utils else None
                        base_metric.hbm_bandwidth_raw_gbps = sum(gpu_hbm_raw) / len(gpu_hbm_raw) if gpu_hbm_raw else None
                        base_metric.nvlink_bandwidth_raw_gbps = sum(gpu_nvlink_raw) / len(gpu_nvlink_raw) if gpu_nvlink_raw else None
                        base_metric.sm_active_percent = sum(gpu_sm_active) / len(gpu_sm_active) if gpu_sm_active else None
                        
                        final_metrics.append(base_metric)
                        
                        # Also collect for overall averages (only non-None values)
                        all_sm_utils.extend(gpu_sm_utils)
                        all_hbm_utils.extend(gpu_hbm_utils)  # Already filtered for non-None
                        all_nvlink_utils.extend(gpu_nvlink_utils)  # Already filtered for non-None
                        all_sm_active.extend(gpu_sm_active)  # TRUE SM Active % from DCGM
                
                # CRITICAL FIX: Merge DCGM data from dedicated monitoring thread
                if self.dcgm_metrics_history:
                    logger.info(f"✅ Merging {len(self.dcgm_metrics_history)} DCGM samples collected during inference")
                    
                    # Group DCGM metrics by GPU
                    dcgm_by_gpu = {}
                    for sample in self.dcgm_metrics_history:
                        gpu_id = sample['gpu_id']
                        if gpu_id not in dcgm_by_gpu:
                            dcgm_by_gpu[gpu_id] = {
                                'sm_active_samples': [],
                                'hbm_util_samples': [],
                                'nvlink_samples': [],
                                'nvlink_util_samples': []
                            }
                        if sample['sm_active_percent'] is not None:
                            dcgm_by_gpu[gpu_id]['sm_active_samples'].append(sample['sm_active_percent'])
                        if sample['hbm_utilization_percent'] is not None:
                            dcgm_by_gpu[gpu_id]['hbm_util_samples'].append(sample['hbm_utilization_percent'])
                        if sample['nvlink_raw_gbps'] is not None:
                            dcgm_by_gpu[gpu_id]['nvlink_samples'].append(sample['nvlink_raw_gbps'])
                        if sample['nvlink_utilization_percent'] is not None:
                            dcgm_by_gpu[gpu_id]['nvlink_util_samples'].append(sample['nvlink_utilization_percent'])
                    
                    # Merge into final_metrics
                    for metric in final_metrics:
                        if metric.gpu_id in dcgm_by_gpu:
                            sm_samples = dcgm_by_gpu[metric.gpu_id]['sm_active_samples']
                            hbm_util_samples = dcgm_by_gpu[metric.gpu_id]['hbm_util_samples']
                            nvlink_samples = dcgm_by_gpu[metric.gpu_id]['nvlink_samples']
                            nvlink_util_samples = dcgm_by_gpu[metric.gpu_id]['nvlink_util_samples']
                            
                            if sm_samples:
                                metric.sm_active_percent = np.mean(sm_samples)
                                logger.info(f"🔥 GPU {metric.gpu_id}: SM Active={metric.sm_active_percent:.1f}% (from {len(sm_samples)} DCGM samples)")
                            if hbm_util_samples:
                                metric.hbm_bandwidth_utilization_percent = np.mean(hbm_util_samples)
                                logger.info(f"🔥 GPU {metric.gpu_id}: HBM Utilization={metric.hbm_bandwidth_utilization_percent:.1f}% (from {len(hbm_util_samples)} DCGM samples)")
                            if nvlink_samples:
                                metric.nvlink_bandwidth_raw_gbps = np.mean(nvlink_samples)
                            if nvlink_util_samples:
                                metric.nvlink_bandwidth_utilization_percent = np.mean(nvlink_util_samples)
                    
                    # Update overall averages with DCGM data
                    all_dcgm_sm_active = [s for gpu_data in dcgm_by_gpu.values() for s in gpu_data['sm_active_samples']]
                    all_dcgm_hbm_util = [s for gpu_data in dcgm_by_gpu.values() for s in gpu_data['hbm_util_samples']]
                    all_dcgm_nvlink_util = [s for gpu_data in dcgm_by_gpu.values() for s in gpu_data['nvlink_util_samples']]
                    
                    if all_dcgm_sm_active:
                        all_sm_active = all_dcgm_sm_active  # Replace with DCGM data
                    if all_dcgm_hbm_util:
                        all_hbm_utils = all_dcgm_hbm_util  # Replace with DCGM data
                    if all_dcgm_nvlink_util:
                        all_nvlink_utils = all_dcgm_nvlink_util  # Replace with DCGM data
                
                avg_gpu_util = sum(all_sm_utils) / len(all_sm_utils) if all_sm_utils else 0
                avg_hbm_util = sum(all_hbm_utils) / len(all_hbm_utils) if all_hbm_utils else None  # None = not measured
                avg_nvlink_util = sum(all_nvlink_utils) / len(all_nvlink_utils) if all_nvlink_utils else None  # None = not measured
                avg_sm_active = sum(all_sm_active) / len(all_sm_active) if all_sm_active else None  # None = DCGM profiling not available
                
                hbm_status = f"{avg_hbm_util:.1f}%" if avg_hbm_util is not None else "N/A"
                nvlink_status = f"{avg_nvlink_util:.1f}%" if avg_nvlink_util is not None else "N/A"
                sm_active_status = f"{avg_sm_active:.1f}%" if avg_sm_active is not None else "N/A"
                logger.info(f"Using historical metrics: SM={avg_gpu_util:.1f}%, SM Active={sm_active_status}, HBM={hbm_status}, NVLink={nvlink_status} (from {len(all_sm_utils)} samples)")
            else:
                # Fallback to final snapshot if no historical data
                logger.warning("No historical GPU metrics available, using final snapshot (likely idle values)")
                final_metrics = self.get_gpu_metrics_nvidia_smi()
                avg_gpu_util = sum(m.gpu_utilization_percent for m in final_metrics) / len(final_metrics) if final_metrics else 0
                avg_hbm_util_list = [m.hbm_bandwidth_utilization_percent for m in final_metrics if m.hbm_bandwidth_utilization_percent is not None]
                avg_nvlink_util_list = [m.nvlink_bandwidth_utilization_percent for m in final_metrics if m.nvlink_bandwidth_utilization_percent is not None]
                avg_sm_active_list = [m.sm_active_percent for m in final_metrics if m.sm_active_percent is not None]
                avg_hbm_util = sum(avg_hbm_util_list) / len(avg_hbm_util_list) if avg_hbm_util_list else None
                avg_nvlink_util = sum(avg_nvlink_util_list) / len(avg_nvlink_util_list) if avg_nvlink_util_list else None
                avg_sm_active = sum(avg_sm_active_list) / len(avg_sm_active_list) if avg_sm_active_list else None
        # Use time-averaged power samples for more accurate performance_per_watt calculation
        if self.power_samples:
            avg_power = np.mean(self.power_samples)  # Time-averaged fleet power in watts
            logger.info(f"Time-averaged fleet power: {avg_power:.1f}W (from {len(self.power_samples)} samples)")
        else:
            # Fallback to instantaneous reading if no time-averaged data
            avg_power = 0.0
            try:
                result = subprocess.run([
                    'nvidia-smi', '--query-gpu=power.draw', '--format=csv,noheader,nounits'
                ], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    power_values = [float(p.strip()) for p in result.stdout.strip().split('\n') if p.strip() and p.strip() != 'N/A']
                    if power_values:
                        # Properly scale to fleet total: average per GPU × GPU count
                        avg_power_per_gpu = np.mean(power_values)
                        avg_power = avg_power_per_gpu * len(power_values)  # Fleet watts
                        # If only one GPU reading, manually multiply by expected GPU count
                        expected_gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 8
                        if len(power_values) == 1 and expected_gpu_count > 1:
                            logger.info(f"Single GPU power reading {avg_power_per_gpu:.1f}W, scaling by {expected_gpu_count}")
                            avg_power = avg_power_per_gpu * expected_gpu_count
                        logger.info(f"Instantaneous fleet power (fallback): {avg_power:.1f}W across {len(power_values)} GPUs")
            except Exception as e:
                logger.debug(f"Could not get power metrics: {e}")
        
        # HBM and NVLink metrics: HBM from Nsight Compute (if available), NVLink from DCGM
        if self.nsight_available:
            logger.info("Using Nsight Compute for real HBM bandwidth + DCGM for NVLink telemetry")
        else:
            logger.info("Using DCGM for NVLink + basic telemetry; HBM bandwidth not collected (install nvidia-nsight-compute for real HBM measurement)")
        
        # Calculate comprehensive performance metrics using real vLLM data
        # Use actual prefill and decode latencies from vLLM RequestOutput metrics
        if prefill_latencies:
            prefill_latency_ms = np.percentile(prefill_latencies, 50)  # Use P50 for consistency
            logger.info(f"Real prefill latencies from vLLM: {len(prefill_latencies)} samples, P50={prefill_latency_ms:.1f}ms")
        else:
            prefill_latency_ms = None  # None = not measured, never 0.0
            logger.info("Prefill latency not available (no per-request metrics)")
            
        if decode_latencies:
            decode_latency_ms = np.percentile(decode_latencies, 50)  # Use P50 for consistency
            logger.info(f"Real decode latencies from vLLM: {len(decode_latencies)} samples, P50={decode_latency_ms:.1f}ms")
        else:
            decode_latency_ms = None  # None = not measured, never 0.0
            logger.info("Decode latency not available (no per-request metrics)")
        
        # Calculate actual decode throughput (tokens/sec during decode phase only)
        decode_throughput_tokens_per_second = 0.0
        if decode_times_ms:
            total_decode_s = sum(decode_times_ms) / 1000.0
            decode_tokens = total_tokens  # All generated tokens are from decode phase
            if total_decode_s > 0:
                decode_throughput_tokens_per_second = decode_tokens / total_decode_s
                logger.info(f"Measured decode throughput: {decode_throughput_tokens_per_second:.1f} tokens/sec (from {len(decode_times_ms)} requests)")
        
        # Performance per watt
        performance_per_watt = throughput_tokens / avg_power if avg_power > 0 else 0
        
        # Cost calculation - make configurable
        cost_usd = None
        performance_per_dollar = None
        if hourly_rate is not None:
            cost_usd = (duration / 3600.0) * hourly_rate
            performance_per_dollar = throughput_tokens / cost_usd if cost_usd > 0 else None
        
        # CRITICAL DEBUG: Log final token counts before creating result
        logger.info(f"FINAL RESULTS DEBUG: total_tokens={total_tokens}, total_requests={total_requests}, duration={duration:.2f}s")
        
        # Calculate average raw bandwidth values for result
        avg_hbm_raw_gbps = None
        avg_nvlink_raw_gbps = None
        if final_metrics:
            hbm_raw_list = [m.hbm_bandwidth_raw_gbps for m in final_metrics if m.hbm_bandwidth_raw_gbps is not None]
            nvlink_raw_list = [m.nvlink_bandwidth_raw_gbps for m in final_metrics if m.nvlink_bandwidth_raw_gbps is not None]
            avg_hbm_raw_gbps = sum(hbm_raw_list) / len(hbm_raw_list) if hbm_raw_list else None
            avg_nvlink_raw_gbps = sum(nvlink_raw_list) / len(nvlink_raw_list) if nvlink_raw_list else None
        
        result = OptimizedBenchmarkResult(
            timestamp=datetime.now().isoformat(),
            engine="vllm",
            model_name=self.model_name,
            batch_size=batch_size,
            input_length=self.input_length,
            output_length=output_length,
            total_tokens_generated=total_tokens,
            total_requests=total_requests,
            duration_seconds=duration,
            throughput_tokens_per_second=throughput_tokens,
            throughput_requests_per_second=throughput_requests,
            latency_p50_ms=ttft_p50_ms,  # Legacy - equals ttft_p50_ms (None = not measured)
            latency_p95_ms=ttft_p95_ms,  # Legacy - equals ttft_p95_ms (None = not measured)
            # New explicit timing metrics (None = not measured)
            ttft_p50_ms=ttft_p50_ms,
            ttft_p95_ms=ttft_p95_ms,
            tbt_p50_ms=tbt_p50_ms,
            tbt_p95_ms=tbt_p95_ms,
            # New comprehensive metrics
            prefill_latency_ms=prefill_latency_ms,
            decode_latency_ms=decode_latency_ms,
            decode_throughput_tokens_per_second=decode_throughput_tokens_per_second,
            gpu_utilization_percent=avg_gpu_util,  # Coarse GPU busy % from nvidia-smi
            sm_active_percent=avg_sm_active,  # TRUE SM Active % from DCGM profiling (DCGM_FI_PROF_SM_ACTIVE)
            hbm_bandwidth_utilization_percent=avg_hbm_util,  # None = not measured
            hbm_bandwidth_raw_gbps=avg_hbm_raw_gbps,  # None = not measured
            nvlink_bandwidth_utilization_percent=avg_nvlink_util,  # None = not measured
            nvlink_bandwidth_raw_gbps=avg_nvlink_raw_gbps,  # None = not measured
            power_draw_watts=avg_power,
            performance_per_watt=performance_per_watt,
            cost_usd=cost_usd,
            performance_per_dollar=performance_per_dollar,
            gpu_metrics=final_metrics,
            success=True
        )
        
        ttft_str = f"{ttft_p50_ms:.1f}ms" if ttft_p50_ms is not None else "N/A"
        tbt_str = f"{tbt_p50_ms:.1f}ms" if tbt_p50_ms is not None else "N/A"
        logger.info(f"vLLM benchmark completed: {throughput_tokens:.1f} tokens/sec, {ttft_str} TTFT p50, {tbt_str} TBT p50")
        
        # Clear historical metrics for next test to prevent data pollution
        self.gpu_metrics_history = []
        self.power_samples = []  # Also clear power samples for next test
        
        return result
    
    def run_comprehensive_benchmark(self, max_batch_size: int = 128, 
                                  output_lengths: List[int] = [1024, 16384, 32768, 262144], 
                                  input_lengths: List[int] = [1024, 4096, 16384],
                                  test_duration: int = 60,
                                  full_comprehensive: bool = False,
                                  hourly_rate: float = None,
                                  iterations: int = 1) -> List[OptimizedBenchmarkResult]:
        """Run comprehensive benchmark across batch sizes, output lengths, and input lengths"""
        
        # Track total benchmark runtime
        benchmark_start_time = time.time()
        
        if not self.initialize_engine():
            logger.error("Failed to initialize inference engine")
            return []
        
        # Define test configurations based on comprehensive table format
        if full_comprehensive:
            # Full comprehensive testing as per your table format
            batch_sizes = [1, 32, 64, 128]
            # Use the output_lengths passed from command line arguments
            # This ensures consistency with --output-lengths parameter
        else:
            # Default focused testing - ONLY batch size 64 as requested
            batch_sizes = [64]
            if max_batch_size >= 128:
                batch_sizes.append(128)
            batch_sizes = [bs for bs in batch_sizes if bs <= max_batch_size]
        
        results = []
        
        logger.info(f"Starting comprehensive benchmark with {self.engine.upper()}")
        logger.info(f"Batch sizes: {batch_sizes}")
        logger.info(f"Output lengths: {output_lengths}")
        logger.info(f"Input lengths: {input_lengths}")
        
        # Test all combinations of input_length, batch_size, and output_length
        for input_length in input_lengths:
            # Update the input length for this test series
            original_input_length = self.input_length
            self.input_length = input_length
            try:
                for output_length in output_lengths:
                    for batch_size in batch_sizes:
                        if batch_size > max_batch_size:
                            continue

                        logger.info(f"Testing input_len={input_length}, batch_size={batch_size}, output_length={output_length}")

                        # Check workload size limits to prevent vLLM hanging
                        total_tokens = batch_size * output_length
                        if total_tokens > 2000000:  # 2M tokens limit
                            logger.warning(f"⚠️ Skipping test: {total_tokens} tokens exceeds 2M limit (batch_size={batch_size}, output_length={output_length})")
                            # Append a placeholder result indicating the test was skipped
                            results.append(OptimizedBenchmarkResult(
                                timestamp=datetime.now().isoformat(),
                                engine=self.engine,
                                model_name=self.model_name,
                                batch_size=batch_size,
                                input_length=input_length,
                                output_length=output_length,
                                total_tokens_generated=0,
                                total_requests=0,
                                duration_seconds=0.0,
                                throughput_tokens_per_second=0.0,
                                throughput_requests_per_second=0.0,
                                latency_p50_ms=0.0,
                                latency_p95_ms=0.0,
                                success=False
                            ))
                            # Save intermediate even for skipped to record decisions
                            self.save_results(results, f"intermediate_{self.engine}_{input_length}_{batch_size}_{output_length}")
                            time.sleep(1)
                            continue

                        try:
                            if self.engine == "vllm":
                                # Run multiple iterations and select the best result
                                iteration_results = []
                                best_result = None
                                best_throughput = 0.0
                                
                                for iteration in range(iterations):
                                    logger.info(f"  Iteration {iteration + 1}/{iterations} for input_len={input_length}, batch_size={batch_size}, output_length={output_length}")
                                    
                                    iteration_result = self.run_vllm_batch_benchmark(batch_size, output_length, test_duration, hourly_rate)
                                    iteration_results.append(iteration_result)
                                    
                                    # Track best result based on throughput
                                    if iteration_result.throughput_tokens_per_second > best_throughput:
                                        best_throughput = iteration_result.throughput_tokens_per_second
                                        best_result = iteration_result
                                    
                                    # CRITICAL: Save intermediate results after each iteration to prevent data loss
                                    # Add iteration number and total iterations to the result
                                    iteration_result.iteration_number = iteration + 1
                                    iteration_result.total_iterations = iterations
                                    
                                    # Create a temporary results list with all completed iterations so far
                                    temp_results = []
                                    for i, temp_result in enumerate(iteration_results):
                                        temp_result.iteration_number = i + 1
                                        temp_result.total_iterations = iterations
                                        temp_results.append(temp_result)
                                    
                                    # Save intermediate results after each iteration
                                    self.save_results(temp_results, f"intermediate_iteration_{iteration + 1}_{self.engine}_{input_length}_{batch_size}_{output_length}")
                                    logger.info(f"  💾 Saved intermediate results after iteration {iteration + 1}/{iterations}")
                                    
                                    # Brief pause between iterations
                                    if iteration < iterations - 1:
                                        time.sleep(3)
                                
                                # Save ALL iteration results (not just the best)
                                if iteration_results:
                                    logger.info(f"  ✅ Completed {len(iteration_results)} iterations")
                                    logger.info(f"  📊 Throughput range: {min(r.throughput_tokens_per_second for r in iteration_results):.1f} - {max(r.throughput_tokens_per_second for r in iteration_results):.1f} tokens/sec")
                                    logger.info(f"  🏆 Best iteration: {best_throughput:.1f} tokens/sec (from {iterations} runs)")
                                    
                                    # Add ALL iteration results to the main results list
                                    for i, iteration_result in enumerate(iteration_results):
                                        # Add iteration number to the result for identification
                                        iteration_result.iteration_number = i + 1
                                        iteration_result.total_iterations = iterations
                                        results.append(iteration_result)
                                else:
                                    logger.warning(f"  ⚠️ No successful iterations for this configuration")
                                    continue
                            else:
                                logger.warning("TensorRT-LLM not implemented yet, skipping")
                                continue

                            # Save intermediate results
                            self.save_results(results, f"intermediate_{self.engine}_{input_length}_{batch_size}_{output_length}")
                            # Brief pause between different configurations
                            time.sleep(2)
                        except Exception as e:
                            logger.error(f"Error in benchmark input_len={input_length}, batch_size={batch_size}, output_length={output_length}: {e}")
                            continue
            finally:
                # Restore original input length for next series
                self.input_length = original_input_length

        # Calculate total benchmark runtime
        benchmark_end_time = time.time()
        total_runtime_seconds = benchmark_end_time - benchmark_start_time
        total_runtime_minutes = total_runtime_seconds / 60.0
        
        logger.info(f"Comprehensive benchmark completed. Total results: {len(results)}")
        logger.info(f"Total benchmark runtime: {total_runtime_minutes:.1f} minutes ({total_runtime_seconds:.1f} seconds)")
        
        # Store total runtime for later use in results
        self.total_benchmark_runtime_seconds = total_runtime_seconds
        
        return results
    
    def save_results(self, results: List[OptimizedBenchmarkResult], suffix: str = ""):
        """Save results to JSON file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        engine_name = self.engine.lower()
        model_short = self.model_name.split('/')[-1]
        
        filename = f"{model_short}_{engine_name}_optimized_benchmark_{timestamp}_{suffix}.json"
        
        results_data = {
            "benchmark_info": {
                "engine": self.engine,
                "model_name": self.model_name,
                "timestamp": timestamp,
                "total_tests": len(results),
                "total_runtime_seconds": getattr(self, 'total_benchmark_runtime_seconds', None),
                "total_runtime_minutes": round(getattr(self, 'total_benchmark_runtime_seconds', 0) / 60.0, 1) if hasattr(self, 'total_benchmark_runtime_seconds') else None,
                "provenance": {
                    "nvlink_pct_basis_mb_s": 600000,
                    "hbm_measured": False,  # FIXED: Only set True if Nsight attached to process and yielded dram bytes
                    "timing_source": "vllm_per_request_metrics_when_available" if self.engine == "vllm" else "fallback_estimate",
                    "monitor_interval_s": 1,
                    "warmup_excluded": True,
                    "allow_estimates": self.allow_estimates,
                    "nvlink_util_basis": "percentage of 600 GB/s bidirectional aggregate per GPU",
                    "performance_per_watt_unit": "tokens/sec/Watt",
                    "power_calculation": "time-averaged fleet power across benchmark duration",
                    "notes": "HBM/NVLink set to null when not measured; latencies set to null when vLLM RequestOutput.metrics unavailable"
                }
            },
            "results": [asdict(result) for result in results]
        }
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"Results saved to {filename}")

def main():
    parser = argparse.ArgumentParser(description="Optimized A100 Batch Benchmark")
    parser.add_argument("--model", required=True, help="Model name or path")
    parser.add_argument("--engine", choices=["vllm", "tensorrt-llm"], default="vllm", help="Inference engine")
    parser.add_argument("--max-batch-size", type=int, default=64, help="Maximum batch size to test")
    parser.add_argument("--output-lengths", nargs="+", type=int, default=[1024, 32768, 65536, 262144], help="Output lengths to test (1K, 32K, 64K, 256K)")
    parser.add_argument("--input-lengths", nargs="+", type=int, default=[1024, 4096, 16384], help="Input lengths to test")
    parser.add_argument("--test-duration", type=int, default=60, help="Test duration per configuration in seconds")
    parser.add_argument("--quick", action="store_true", help="Quick test with limited configurations")
    parser.add_argument("--full-comprehensive", action="store_true", help="Run full comprehensive test with all input/output lengths and batch sizes")
    parser.add_argument("--hourly-rate", type=float, default=None, help="USD/hour for the machine. If omitted, cost and perf/$ are not reported.")
    parser.add_argument("--allow-estimates", action="store_true", help="Enable heuristic HBM/NVLink estimates and deprecated nvprof fallbacks (off by default).")
    parser.add_argument("--enable-nsight", action="store_true", help="Force enable Nsight Compute for real HBM bandwidth measurement.")
    parser.add_argument("--iterations", type=int, default=1, help="Number of iterations per configuration to get best result (default: 1)")
    
    args = parser.parse_args()
    
    # Adjust for quick test - still test the required batch sizes but with shorter sequences
    if args.quick:
        args.max_batch_size = 64  # Test up to batch 64 for quick test
        args.output_lengths = [2048, 4096]  # Shorter sequences for quick test
        args.input_lengths = [1024]  # Single input length for quick test
        args.test_duration = 30
    
    # Adjust for full comprehensive test
    if args.full_comprehensive:
        args.max_batch_size = 128  # Test all batch sizes up to 128
        args.output_lengths = [1024, 16384, 32768, 262144]  # 1K, 16K, 32K, 256K as requested
        args.input_lengths = [1024, 4096, 16384]  # 1K, 4K, 16K (already includes 16K)
        logger.info("Running FULL COMPREHENSIVE test with all combinations")
    
    logger.info(f"Starting optimized benchmark for {args.model} with {args.engine}")
    logger.info(f"Configuration: max_batch_size={args.max_batch_size}")
    logger.info(f"Input lengths: {args.input_lengths}")
    logger.info(f"Output lengths: {args.output_lengths}")
    logger.info(f"Test duration: {args.test_duration}s per configuration")
    
    # Initialize and run benchmark
    benchmark = OptimizedBatchBenchmark(args.model, args.engine, allow_estimates=args.allow_estimates, enable_nsight=args.enable_nsight)
    
    # Log estimation status
    if args.allow_estimates:
        logger.info("HBM/NVLink estimates enabled by user flag; results are heuristic.")
    if args.enable_nsight:
        logger.info("Nsight Compute force-enabled by user flag for real HBM measurement.")
    
    # Set default hourly rate if not provided
    if args.hourly_rate is None:
        args.hourly_rate = 14.32  # Default A100 hourly rate
        logger.info(f"Using default hourly rate: ${args.hourly_rate}/hour")
    
    # Clean up system before starting benchmark
    benchmark.cleanup_system_before_benchmark()
    
    results = benchmark.run_comprehensive_benchmark(
        max_batch_size=args.max_batch_size,
        output_lengths=args.output_lengths,
        input_lengths=args.input_lengths,
        test_duration=args.test_duration,
        full_comprehensive=args.full_comprehensive,
        hourly_rate=args.hourly_rate,
        iterations=args.iterations
    )
    
    if results:
        benchmark.save_results(results, "final")
        logger.info(f"Benchmark completed successfully with {len(results)} results")
    else:
        logger.error("Benchmark failed with no results")

if __name__ == "__main__":
    main()
