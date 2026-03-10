#!/usr/bin/env python3
"""
Continuous Inference Script for vLLM API
Sends repeated requests to keep GPU busy and generate throughput data.

This script can be run from:
1. The backend server (where httpx is available)
2. The instance itself (using requests library)
3. Any machine with Python and requests/httpx installed
"""

import argparse
import time
import sys
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

# Try to use httpx (async, better for high throughput), fallback to requests
try:
    import asyncio
    import httpx
    USE_ASYNC = True
except ImportError:
    try:
        import requests
        USE_ASYNC = False
    except ImportError:
        print("ERROR: Neither httpx nor requests is available.")
        print("Please install one of them:")
        print("  pip install httpx  # Recommended for async")
        print("  pip install requests  # Alternative")
        sys.exit(1)

class ContinuousInference:
    def __init__(
        self,
        ip_address: str,
        model: str = "mistralai/Mistral-7B-Instruct-v0.2",
        interval: float = 5.0,
        max_tokens: int = 100,
        temperature: float = 0.7,
        prompt: Optional[str] = None
    ):
        self.ip_address = ip_address
        self.model = model
        self.interval = interval
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.prompt = prompt or "What is 2+2? Please explain your answer."
        self.base_url = f"http://{ip_address}:8000/v1/chat/completions"
        self.running = False
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0,
            "total_latency": 0.0,
            "start_time": None
        }

    def send_request_sync(self) -> dict:
        """Send a single inference request synchronously (using requests)."""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.prompt}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }
        
        start_time = time.time()
        try:
            response = requests.post(
                self.base_url,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            latency = time.time() - start_time
            
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
            
            return {
                "success": True,
                "latency": latency,
                "tokens": tokens,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "response": data.get("choices", [{}])[0].get("message", {}).get("content", "")[:100]
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "latency": time.time() - start_time
            }

    async def send_request_async(self, client: "httpx.AsyncClient") -> dict:
        """Send a single inference request asynchronously (using httpx)."""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.prompt}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }
        
        start_time = time.time()
        try:
            response = await client.post(
                self.base_url,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            latency = time.time() - start_time
            
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
            
            return {
                "success": True,
                "latency": latency,
                "tokens": tokens,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "response": data.get("choices", [{}])[0].get("message", {}).get("content", "")[:100]
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "latency": time.time() - start_time
            }

    def run_continuous_sync(self):
        """Run continuous inference requests synchronously."""
        self.running = True
        self.stats["start_time"] = time.time()
        
        print(f"\n{'='*80}")
        print(f"Starting Continuous Inference (Sync Mode)")
        print(f"{'='*80}")
        print(f"Target: {self.base_url}")
        print(f"Model: {self.model}")
        print(f"Prompt: {self.prompt}")
        print(f"Interval: {self.interval} seconds")
        print(f"Max Tokens: {self.max_tokens}")
        print(f"Temperature: {self.temperature}")
        print(f"{'='*80}\n")
        
        while self.running:
            try:
                result = self.send_request_sync()
                self.stats["total_requests"] += 1
                
                if result["success"]:
                    self.stats["successful_requests"] += 1
                    self.stats["total_tokens"] += result["tokens"]
                    self.stats["total_latency"] += result["latency"]
                    
                    # Calculate metrics
                    tokens_per_sec = result["completion_tokens"] / result["latency"] if result["latency"] > 0 else 0
                    overall_tokens_per_sec = self.stats["total_tokens"] / (time.time() - self.stats["start_time"]) if self.stats["start_time"] else 0
                    
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Request #{self.stats['total_requests']}")
                    print(f"  ✓ Success | Latency: {result['latency']:.3f}s | "
                          f"Tokens: {result['tokens']} ({result['prompt_tokens']} prompt + {result['completion_tokens']} completion)")
                    print(f"  Throughput: {tokens_per_sec:.2f} tokens/s | "
                          f"Avg Overall: {overall_tokens_per_sec:.2f} tokens/s")
                    if result.get("response"):
                        print(f"  Response preview: {result['response']}...")
                else:
                    self.stats["failed_requests"] += 1
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Request #{self.stats['total_requests']}")
                    print(f"  ✗ Failed: {result.get('error', 'Unknown error')}")
                
                # Print summary every 10 requests
                if self.stats["total_requests"] % 10 == 0:
                    self.print_summary()
                
                # Wait for next interval
                if self.running:
                    time.sleep(self.interval)
                    
            except KeyboardInterrupt:
                print("\n\nStopping continuous inference...")
                self.running = False
                break
            except Exception as e:
                print(f"\n[ERROR] Unexpected error: {e}")
                self.stats["failed_requests"] += 1
                if self.running:
                    time.sleep(self.interval)
        
        self.print_final_summary()

    async def run_continuous_async(self):
        """Run continuous inference requests asynchronously."""
        self.running = True
        self.stats["start_time"] = time.time()
        
        print(f"\n{'='*80}")
        print(f"Starting Continuous Inference (Async Mode)")
        print(f"{'='*80}")
        print(f"Target: {self.base_url}")
        print(f"Model: {self.model}")
        print(f"Prompt: {self.prompt}")
        print(f"Interval: {self.interval} seconds")
        print(f"Max Tokens: {self.max_tokens}")
        print(f"Temperature: {self.temperature}")
        print(f"{'='*80}\n")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while self.running:
                try:
                    result = await self.send_request_async(client)
                    self.stats["total_requests"] += 1
                    
                    if result["success"]:
                        self.stats["successful_requests"] += 1
                        self.stats["total_tokens"] += result["tokens"]
                        self.stats["total_latency"] += result["latency"]
                        
                        # Calculate metrics
                        tokens_per_sec = result["completion_tokens"] / result["latency"] if result["latency"] > 0 else 0
                        overall_tokens_per_sec = self.stats["total_tokens"] / (time.time() - self.stats["start_time"]) if self.stats["start_time"] else 0
                        
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Request #{self.stats['total_requests']}")
                        print(f"  ✓ Success | Latency: {result['latency']:.3f}s | "
                              f"Tokens: {result['tokens']} ({result['prompt_tokens']} prompt + {result['completion_tokens']} completion)")
                        print(f"  Throughput: {tokens_per_sec:.2f} tokens/s | "
                              f"Avg Overall: {overall_tokens_per_sec:.2f} tokens/s")
                        if result.get("response"):
                            print(f"  Response preview: {result['response']}...")
                    else:
                        self.stats["failed_requests"] += 1
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Request #{self.stats['total_requests']}")
                        print(f"  ✗ Failed: {result.get('error', 'Unknown error')}")
                    
                    # Print summary every 10 requests
                    if self.stats["total_requests"] % 10 == 0:
                        self.print_summary()
                    
                    # Wait for next interval
                    if self.running:
                        await asyncio.sleep(self.interval)
                        
                except KeyboardInterrupt:
                    print("\n\nStopping continuous inference...")
                    self.running = False
                    break
                except Exception as e:
                    print(f"\n[ERROR] Unexpected error: {e}")
                    self.stats["failed_requests"] += 1
                    if self.running:
                        await asyncio.sleep(self.interval)
        
        self.print_final_summary()

    def print_summary(self):
        """Print summary statistics."""
        if self.stats["successful_requests"] == 0:
            return
        
        elapsed = time.time() - self.stats["start_time"]
        avg_latency = self.stats["total_latency"] / self.stats["successful_requests"]
        avg_throughput = self.stats["total_tokens"] / elapsed if elapsed > 0 else 0
        success_rate = (self.stats["successful_requests"] / self.stats["total_requests"]) * 100
        
        print(f"\n{'─'*80}")
        print(f"Summary (last {self.stats['total_requests']} requests):")
        print(f"  Success Rate: {success_rate:.1f}% ({self.stats['successful_requests']}/{self.stats['total_requests']})")
        print(f"  Total Tokens: {self.stats['total_tokens']}")
        print(f"  Avg Latency: {avg_latency:.3f}s")
        print(f"  Avg Throughput: {avg_throughput:.2f} tokens/s")
        print(f"  Elapsed Time: {elapsed:.1f}s")
        print(f"{'─'*80}\n")

    def print_final_summary(self):
        """Print final summary when stopping."""
        if self.stats["start_time"] is None:
            return
        
        elapsed = time.time() - self.stats["start_time"]
        
        print(f"\n{'='*80}")
        print(f"Final Summary")
        print(f"{'='*80}")
        print(f"Total Requests: {self.stats['total_requests']}")
        print(f"Successful: {self.stats['successful_requests']}")
        print(f"Failed: {self.stats['failed_requests']}")
        if self.stats["successful_requests"] > 0:
            success_rate = (self.stats["successful_requests"] / self.stats["total_requests"]) * 100
            avg_latency = self.stats["total_latency"] / self.stats["successful_requests"]
            avg_throughput = self.stats["total_tokens"] / elapsed if elapsed > 0 else 0
            print(f"Success Rate: {success_rate:.1f}%")
            print(f"Total Tokens: {self.stats['total_tokens']}")
            print(f"Average Latency: {avg_latency:.3f}s")
            print(f"Average Throughput: {avg_throughput:.2f} tokens/s")
        print(f"Total Runtime: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
        print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Continuous inference script to keep GPU busy and generate throughput data"
    )
    parser.add_argument(
        "--ip",
        type=str,
        required=True,
        help="IP address of the instance running vLLM (e.g., 150.136.36.90)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="mistralai/Mistral-7B-Instruct-v0.2",
        help="Model name (default: mistralai/Mistral-7B-Instruct-v0.2)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Interval between requests in seconds (default: 5.0)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=100,
        help="Maximum tokens to generate (default: 100)"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Temperature for generation (default: 0.7)"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Custom prompt to use (default: 'What is 2+2? Please explain your answer.')"
    )
    
    args = parser.parse_args()
    
    inference = ContinuousInference(
        ip_address=args.ip,
        model=args.model,
        interval=args.interval,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        prompt=args.prompt
    )
    
    try:
        if USE_ASYNC:
            asyncio.run(inference.run_continuous_async())
        else:
            inference.run_continuous_sync()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Stopping...")
        inference.running = False
        inference.print_final_summary()
        sys.exit(0)


if __name__ == "__main__":
    main()

