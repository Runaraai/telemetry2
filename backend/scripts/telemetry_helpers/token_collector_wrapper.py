#!/usr/bin/env python3
"""
Automatic Token Metrics Collector Wrapper

This wrapper script runs inference commands and automatically extracts token metrics
from stdout/stderr, log files, or by monitoring process output.

Usage:
    # Run any inference command - metrics are automatically collected
    python token_collector_wrapper.py -- python your_inference_script.py --args
    
    # Monitor a log file for token metrics
    python token_collector_wrapper.py --log-file /path/to/inference.log -- python your_script.py
    
    # Use environment variable to enable auto-collection
    OMNIFERENCE_TOKEN_COLLECTOR=1 python your_inference_script.py
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, List

import requests


# Common patterns to extract token metrics from logs
TOKEN_PATTERNS = [
    # vLLM patterns
    (r'tokens/s:\s*([\d.]+)', 'tokens_per_second'),
    (r'throughput:\s*([\d.]+)\s*tokens/s', 'tokens_per_second'),
    (r'generation_throughput:\s*([\d.]+)', 'tokens_per_second'),
    (r'num_output_tokens:\s*(\d+)', 'total_tokens'),
    (r'total_tokens:\s*(\d+)', 'total_tokens'),
    
    # TensorRT-LLM patterns
    (r'Throughput:\s*([\d.]+)\s*tokens/sec', 'tokens_per_second'),
    (r'Total tokens:\s*(\d+)', 'total_tokens'),
    
    # Generic patterns
    (r'tokens_per_second[:\s=]+([\d.]+)', 'tokens_per_second'),
    (r'tps[:\s=]+([\d.]+)', 'tokens_per_second'),
    (r'throughput[:\s=]+([\d.]+)', 'tokens_per_second'),
    (r'total.*tokens[:\s=]+(\d+)', 'total_tokens'),
    
    # JSON patterns
    (r'"tokens_per_second"[:\s]*([\d.]+)', 'tokens_per_second'),
    (r'"throughput"[:\s]*([\d.]+)', 'tokens_per_second'),
    (r'"total_tokens"[:\s]*(\d+)', 'total_tokens'),
    
    # Request patterns
    (r'requests/s:\s*([\d.]+)', 'requests_per_second'),
    (r'requests_per_second[:\s=]+([\d.]+)', 'requests_per_second'),
    (r'total.*requests[:\s=]+(\d+)', 'total_requests'),
]


class TokenCollector:
    """Collects token metrics from various sources and reports to token-exporter."""
    
    def __init__(self, exporter_url: str = "http://localhost:9402"):
        self.exporter_url = f"{exporter_url}/update"
        self.metrics: Dict[str, float] = {
            'tokens_per_second': 0.0,
            'total_tokens': 0,
            'requests_per_second': 0.0,
            'total_requests': 0,
        }
        self.lock = threading.Lock()
        self.running = True
        
    def update_metrics(self, **kwargs):
        """Update metrics and send to exporter."""
        with self.lock:
            for key, value in kwargs.items():
                if key in self.metrics:
                    if 'total' in key:
                        # For counters, take the maximum (cumulative)
                        self.metrics[key] = max(self.metrics[key], int(value))
                    else:
                        # For rates, update with latest value
                        self.metrics[key] = float(value)
        
        # Send to exporter
        try:
            response = requests.post(
                self.exporter_url,
                json=self.metrics,
                timeout=1.0
            )
            response.raise_for_status()
        except Exception as e:
            # Silently fail - don't interrupt the workload
            pass
    
    def parse_line(self, line: str) -> Optional[Dict[str, float]]:
        """Parse a line of text for token metrics."""
        found = {}
        
        # Try JSON first
        try:
            if line.strip().startswith('{'):
                data = json.loads(line)
                if 'tokens_per_second' in data:
                    found['tokens_per_second'] = float(data['tokens_per_second'])
                if 'total_tokens' in data:
                    found['total_tokens'] = int(data['total_tokens'])
                if 'requests_per_second' in data:
                    found['requests_per_second'] = float(data['requests_per_second'])
                if 'total_requests' in data:
                    found['total_requests'] = int(data['total_requests'])
                if found:
                    return found
        except:
            pass
        
        # Try regex patterns
        for pattern, metric_key in TOKEN_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1))
                    if 'total' in metric_key:
                        value = int(value)
                    found[metric_key] = value
                except:
                    continue
        
        return found if found else None
    
    def monitor_stream(self, stream, stream_name: str = "stdout"):
        """Monitor a stream (stdout/stderr) for token metrics."""
        for line in stream:
            if not self.running:
                break
            line_str = line.decode('utf-8', errors='ignore') if isinstance(line, bytes) else str(line)
            metrics = self.parse_line(line_str)
            if metrics:
                self.update_metrics(**metrics)
                print(f"[TokenCollector] Found {stream_name} metrics: {metrics}", file=sys.stderr)
    
    def monitor_file(self, file_path: Path, poll_interval: float = 0.5):
        """Monitor a log file for token metrics (tail-like behavior)."""
        file_path = Path(file_path)
        if not file_path.exists():
            print(f"[TokenCollector] Warning: Log file {file_path} does not exist", file=sys.stderr)
            return
        
        # Start from end of file
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)  # Seek to end
        
        while self.running:
            try:
                line = f.readline()
                if line:
                    metrics = self.parse_line(line)
                    if metrics:
                        self.update_metrics(**metrics)
                        print(f"[TokenCollector] Found log metrics: {metrics}", file=sys.stderr)
                else:
                    time.sleep(poll_interval)
            except Exception as e:
                print(f"[TokenCollector] Error monitoring file: {e}", file=sys.stderr)
                time.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(
        description="Automatic token metrics collector wrapper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run inference command with automatic metric collection
  python token_collector_wrapper.py -- python inference.py --model llama
  
  # Monitor a log file while running a command
  python token_collector_wrapper.py --log-file /var/log/inference.log -- python inference.py
  
  # Just monitor a log file (no command to run)
  python token_collector_wrapper.py --log-file /var/log/inference.log --monitor-only
        """
    )
    parser.add_argument(
        '--exporter-url',
        default='http://localhost:9402',
        help='Token exporter URL (default: http://localhost:9402)'
    )
    parser.add_argument(
        '--log-file',
        type=Path,
        help='Log file to monitor for token metrics'
    )
    parser.add_argument(
        '--monitor-only',
        action='store_true',
        help='Only monitor log file, do not run a command'
    )
    parser.add_argument(
        '--',
        dest='command',
        nargs=argparse.REMAINDER,
        help='Command to run (use -- to separate from wrapper args)'
    )
    
    args = parser.parse_args()
    
    collector = TokenCollector(exporter_url=args.exporter_url)
    
    threads = []
    
    # Monitor log file if specified
    if args.log_file:
        log_thread = threading.Thread(
            target=collector.monitor_file,
            args=(args.log_file,),
            daemon=True
        )
        log_thread.start()
        threads.append(log_thread)
    
    # Run command if provided
    if args.command and not args.monitor_only:
        # Start monitoring stdout/stderr
        process = subprocess.Popen(
            args.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True
        )
        
        stdout_thread = threading.Thread(
            target=collector.monitor_stream,
            args=(process.stdout, 'stdout'),
            daemon=True
        )
        stderr_thread = threading.Thread(
            target=collector.monitor_stream,
            args=(process.stderr, 'stderr'),
            daemon=True
        )
        
        stdout_thread.start()
        stderr_thread.start()
        threads.extend([stdout_thread, stderr_thread])
        
        # Wait for process to complete
        return_code = process.wait()
        
        # Give threads a moment to finish
        collector.running = False
        time.sleep(0.5)
        
        sys.exit(return_code)
    
    elif args.monitor_only:
        # Just monitor the log file
        print(f"[TokenCollector] Monitoring {args.log_file} for token metrics...", file=sys.stderr)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            collector.running = False
            print("\n[TokenCollector] Stopped monitoring", file=sys.stderr)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()

