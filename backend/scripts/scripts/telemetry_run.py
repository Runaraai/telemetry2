#!/usr/bin/env python3
"""
telemetry_run.py — CLI entry point for the unified telemetry tool.

Usage examples
--------------
# Auto-detect GPU, use vLLM on localhost:8000, with kernel profiling
python telemetry_run.py

# Custom server, model, request count
python telemetry_run.py --server http://localhost:8000 --model Qwen/Qwen2.5-3B-Instruct \\
    --num-requests 50 --max-tokens 200

# Disable kernel profiling (faster, no /start_profile endpoint needed)
python telemetry_run.py --no-kernel

# Save results to a specific path
python telemetry_run.py --output /tmp/my_run.json

# Use DCGM Docker exporter at a non-default address
python telemetry_run.py --dcgm-url http://localhost:9400/metrics

# Skip GPU backend entirely (workload + kernel only)
python telemetry_run.py --no-gpu
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# ── allow running from the scripts/ directory without installing ──────────────
sys.path.insert(0, str(Path(__file__).parent))

from telemetry                   import (TelemetryRunner, TelemetryResult,
                                         AutoGpuBackend, VLLMOpenAIBackend,
                                         TorchVLLMKernelBackend,
                                         print_report, save_json)
from telemetry.gpu.nvml          import NVMLBackend
from telemetry.gpu.dcgm          import DCGMBackend

# ── default prompts ───────────────────────────────────────────────────────────

DEFAULT_PROMPTS = [
    "Explain the attention mechanism in transformers.",
    "What is the difference between supervised and unsupervised learning?",
    "Describe how a GPU executes parallel workloads.",
    "What are the main trade-offs between TTFT and throughput in LLM serving?",
    "How does FlashAttention reduce memory bandwidth requirements?",
    "Explain the KV-cache and how it speeds up autoregressive decoding.",
    "What is tensor parallelism and when is it beneficial?",
    "Describe the softmax operation and its numerical stability tricks.",
    "What is quantization in the context of neural networks?",
    "How does speculative decoding work?",
    "Explain the role of layer normalization in transformers.",
    "What is the difference between MHA and GQA attention?",
    "How does RLHF improve language model alignment?",
    "Describe the SwiGLU activation function.",
    "What is model distillation and why is it useful?",
    "Explain the PagedAttention algorithm.",
    "What metrics matter most for LLM production serving?",
    "Describe the Chinchilla scaling laws.",
    "How does beam search differ from greedy decoding?",
    "What is prefix caching and how does it save compute?",
    "Explain rotary position embeddings (RoPE).",
    "What is the role of the feed-forward network in a transformer block?",
    "How does weight tying reduce model size?",
    "Describe the differences between encoder-only, decoder-only and encoder-decoder models.",
    "What is sparse attention and what problem does it solve?",
    "How does gradient checkpointing trade compute for memory?",
    "Explain the CUDA programming model briefly.",
    "What is warp divergence and why does it hurt GPU performance?",
    "How does the NCCL library enable multi-GPU communication?",
    "What is the difference between data parallelism and pipeline parallelism?",
    "Explain how continuous batching works in vLLM.",
    "What are the key bottlenecks when running large LLMs?",
    "Describe the memory layout of a transformer's KV cache.",
    "How do quantization formats like GPTQ and AWQ differ?",
    "What is the role of the scheduler in an LLM inference server?",
    "Explain the concept of flops utilization (MFU).",
    "What is DRAM bandwidth and why is it critical for LLMs?",
    "How does temperature affect token sampling?",
    "Explain nucleus (top-p) sampling.",
    "What is a mixture-of-experts (MoE) model?",
    "How does LoRA enable parameter-efficient fine-tuning?",
    "Describe the differences between BF16 and FP16.",
    "What is INT8 quantization and when does it degrade quality?",
    "How does flash decoding parallelize across the sequence dimension?",
    "Explain what 'prefill' and 'decode' phases mean in LLM inference.",
    "What are the design goals of the Llama model family?",
    "Describe the Mistral 7B architecture improvements.",
    "How do sliding window attention and full attention compare?",
    "What is multi-query attention (MQA)?",
    "Explain the concept of a prompt template and its importance.",
]


# ── argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Unified LLM telemetry: GPU + workload + kernel profiling",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Server / model
    p.add_argument("--server",       default="http://localhost:8000",
                   help="vLLM / OpenAI-compatible server URL")
    p.add_argument("--model",        default="",
                   help="Model name (auto-detected from /v1/models if empty)")
    p.add_argument("--num-requests", type=int, default=50,
                   help="Number of inference requests to send")
    p.add_argument("--max-tokens",   type=int, default=200,
                   help="Max output tokens per request")
    p.add_argument("--concurrency",  type=int, default=4,
                   help="Max concurrent requests")

    # GPU
    p.add_argument("--dcgm-url",  default="http://localhost:9400/metrics",
                   help="DCGM exporter URL")
    p.add_argument("--gpu-index", type=int, default=0,
                   help="GPU index for NVML backend")
    p.add_argument("--gpu-poll",  type=float, default=0.5,
                   help="GPU sampling interval in seconds")
    p.add_argument("--no-gpu",    action="store_true",
                   help="Disable GPU monitoring entirely")

    # Kernel
    p.add_argument("--no-kernel",        action="store_true",
                   help="Disable kernel profiling (no vLLM profiler needed)")
    p.add_argument("--trace-dir",        default="/tmp/vllm_traces",
                   help="Directory where vLLM writes torch profiler traces")
    p.add_argument("--kernel-start",     type=int, default=10,
                   help="Request index to start kernel profiling")
    p.add_argument("--kernel-stop",      type=int, default=30,
                   help="Request index to stop  kernel profiling")

    # Output
    p.add_argument("--output",   default="",
                   help="JSON output path (auto-generated if empty)")
    p.add_argument("--title",    default="Telemetry Run",
                   help="Run title for the report")
    p.add_argument("--quiet",    action="store_true",
                   help="Suppress per-request progress")

    return p.parse_args()


# ── build GPU backend ─────────────────────────────────────────────────────────

def build_gpu_backend(args: argparse.Namespace):
    if args.no_gpu:
        return None
    try:
        backend = AutoGpuBackend(
            dcgm_url=args.dcgm_url,
            gpu_index=args.gpu_index,
        )
        print(f"[setup] GPU backend   : {backend.describe()}")
        return backend
    except RuntimeError as e:
        print(f"[setup] GPU backend unavailable — {e}")
        print("[setup] Continuing without GPU monitoring.")
        return None


# ── build Kernel backend ──────────────────────────────────────────────────────

def build_kernel_backend(args: argparse.Namespace):
    if args.no_kernel:
        return None
    if TorchVLLMKernelBackend.is_available(server_url=args.server,
                                           trace_dir=args.trace_dir):
        b = TorchVLLMKernelBackend(server_url=args.server,
                                   trace_dir=args.trace_dir)
        print(f"[setup] Kernel backend: {b.name} (trace_dir={args.trace_dir})")
        return b
    else:
        print("[setup] Kernel backend: unavailable (vLLM /start_profile not reachable)")
        print("[setup] Start vLLM with --profiler-config to enable kernel profiling.")
        return None


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    args = parse_args()

    # Build backends
    gpu_backend = build_gpu_backend(args)
    kernel_backend = build_kernel_backend(args)

    workload_backend = VLLMOpenAIBackend(
        server_url=args.server,
        model=args.model,
        max_concurrent=args.concurrency,
    )
    print(f"[setup] Workload      : {workload_backend.name} @ {args.server}")

    # Verify server is reachable
    if not VLLMOpenAIBackend.is_available(server_url=args.server):
        print(f"\n[ERROR] Cannot reach {args.server}/v1/models — is vLLM running?")
        print("Start vLLM with:")
        print(f"  vllm serve <model> --host 0.0.0.0 --port 8000 "
              f"--attention-backend TRITON_ATTN --enforce-eager")
        sys.exit(1)

    # Select prompts
    prompts = (DEFAULT_PROMPTS * 10)[:args.num_requests]
    print(f"[setup] Requests      : {len(prompts)}  max_tokens={args.max_tokens}")
    print()

    # Dummy GPU backend if GPU monitoring disabled
    if gpu_backend is None:
        from telemetry.gpu.base import GpuBackend, GpuSample
        class _NoopGpu(GpuBackend):
            name = "noop"
            capabilities = []
            def collect(self): return None
            @classmethod
            def is_available(cls, **kw): return True
            def describe(self): return "disabled"
        gpu_backend = _NoopGpu()

    # Build and run
    runner = TelemetryRunner(
        gpu_backend=gpu_backend,
        workload_backend=workload_backend,
        kernel_backend=kernel_backend,
        gpu_poll_s=args.gpu_poll,
        kernel_start_idx=args.kernel_start,
        kernel_stop_idx=args.kernel_stop,
    )

    result: TelemetryResult = await runner.run(
        prompts=prompts,
        max_tokens=args.max_tokens,
        verbose=not args.quiet,
    )

    # Print report
    print_report(result, title=args.title)

    # Save JSON
    out_path = args.output or None
    saved = save_json(result, output_path=out_path, title=args.title)
    print(f"Results saved → {saved}")


if __name__ == "__main__":
    asyncio.run(main())
