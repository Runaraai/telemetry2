"""
telemetry.workload.vllm_openai — Workload backend for vLLM via OpenAI-compatible API.

Sends requests with streaming enabled to measure TTFT accurately.
Works with any OpenAI-compatible inference server (vLLM, LiteLLM, etc.).
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, Callable

import aiohttp

from .base import WorkloadBackend, WorkloadStats, RequestResult


class VLLMOpenAIBackend(WorkloadBackend):
    """
    Benchmark a vLLM (or OpenAI-compatible) server using the /v1/chat/completions
    endpoint with streaming to capture TTFT.

    Concurrency is controlled by max_concurrent; requests are dispatched as a
    semaphore-guarded pool so the server isn't overwhelmed.
    """

    name = "vllm_openai"

    def __init__(
        self,
        server_url: str = "http://localhost:8000",
        model: str = "",
        max_concurrent: int = 4,
        timeout: float = 120.0,
    ):
        self.server_url     = server_url.rstrip("/")
        self.model          = model
        self.max_concurrent = max_concurrent
        self.timeout        = timeout

    # ── model auto-detection ──────────────────────────────────────────────────

    async def _get_model(self) -> str:
        """Fetch the first available model from /v1/models if none specified."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.server_url}/v1/models",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    models = data.get("data", [])
                    if models:
                        return models[0]["id"]
        except Exception:
            pass
        return ""

    # ── single streaming request ──────────────────────────────────────────────

    async def _send_one(
        self,
        session: aiohttp.ClientSession,
        model: str,
        prompt: str,
        max_tokens: int,
    ) -> RequestResult:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,
        }

        result = RequestResult(prompt=prompt)
        t_start = time.perf_counter()
        first_token = False
        output_text = ""

        try:
            async with session.post(
                f"{self.server_url}/v1/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    result.success = False
                    result.error   = f"HTTP {resp.status}: {body[:200]}"
                    return result

                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break

                    try:
                        import json
                        obj = json.loads(chunk)
                    except Exception:
                        continue

                    delta = (
                        obj.get("choices", [{}])[0]
                           .get("delta", {})
                           .get("content", "")
                    )
                    if delta and not first_token:
                        result.ttft_ms = (time.perf_counter() - t_start) * 1000
                        first_token = True

                    output_text += delta or ""

                    # usage block (last chunk in some servers)
                    usage = obj.get("usage")
                    if usage:
                        result.input_tokens  = usage.get("prompt_tokens", 0)
                        result.output_tokens = usage.get("completion_tokens", 0)

        except asyncio.TimeoutError:
            result.success = False
            result.error   = "timeout"
            return result
        except Exception as exc:
            result.success = False
            result.error   = str(exc)
            return result

        result.total_ms = (time.perf_counter() - t_start) * 1000
        if result.output_tokens == 0:
            # Approximate from whitespace-split if server didn't return usage
            result.output_tokens = max(1, len(output_text.split()))
        return result

    # ── public run() ──────────────────────────────────────────────────────────

    async def run(
        self,
        prompts: list[str],
        max_tokens: int = 200,
        on_request_done: Optional[Callable[[int, RequestResult], None]] = None,
    ) -> WorkloadStats:
        model = self.model or await self._get_model()
        if not model:
            raise RuntimeError(
                f"Could not determine model from {self.server_url}/v1/models. "
                "Pass model= explicitly."
            )

        sem = asyncio.Semaphore(self.max_concurrent)
        results: list[Optional[RequestResult]] = [None] * len(prompts)
        t0 = time.perf_counter()

        async def _task(idx: int, prompt: str) -> None:
            async with sem:
                connector = aiohttp.TCPConnector(limit=self.max_concurrent)
                async with aiohttp.ClientSession(connector=connector) as session:
                    res = await self._send_one(session, model, prompt, max_tokens)
                results[idx] = res
                if on_request_done:
                    on_request_done(idx, res)

        await asyncio.gather(*[_task(i, p) for i, p in enumerate(prompts)])

        duration = time.perf_counter() - t0
        final = [r for r in results if r is not None]
        return WorkloadStats.from_results(
            final,
            model=model,
            duration_s=duration,
            server_url=self.server_url,
            concurrency=self.max_concurrent,
        )

    # ── availability check ────────────────────────────────────────────────────

    @classmethod
    def is_available(cls, server_url: str = "http://localhost:8000", **kwargs) -> bool:
        try:
            import urllib.request
            req = urllib.request.urlopen(
                f"{server_url.rstrip('/')}/v1/models", timeout=5
            )
            return req.status == 200
        except Exception:
            return False
