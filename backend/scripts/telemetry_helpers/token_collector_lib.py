"""
Python Library for Easy Token Metrics Integration

This library provides a simple interface for applications to report token metrics
to the Omniference telemetry stack.

Usage:
    from telemetry_helpers.token_collector_lib import TokenReporter
    
    reporter = TokenReporter()
    
    # In your inference loop
    for batch in batches:
        tokens = generate_tokens(batch)
        reporter.report_tokens(tokens, elapsed_time=1.0)
    
    # Or report directly
    reporter.report_metrics(
        tokens_per_second=123.4,
        total_tokens=5000,
        requests_per_second=2.5,
        total_requests=100
    )
"""

import os
import threading
import time
from typing import Optional
from urllib.parse import urljoin

import requests


class TokenReporter:
    """
    Simple reporter for token metrics to Omniference telemetry stack.
    
    Automatically detects token-exporter URL from environment or uses default.
    Thread-safe and non-blocking - failures are silently ignored to not interrupt workloads.
    """
    
    def __init__(
        self,
        exporter_url: Optional[str] = None,
        auto_detect: bool = True,
        report_interval: float = 1.0
    ):
        """
        Initialize token reporter.
        
        Args:
            exporter_url: URL of token-exporter service (default: http://localhost:9402)
            auto_detect: Auto-detect exporter URL from environment variables
            report_interval: Minimum interval between reports (seconds)
        """
        if exporter_url:
            self.exporter_url = urljoin(exporter_url.rstrip('/'), '/update')
        elif auto_detect:
            # Try environment variable first
            self.exporter_url = os.getenv(
                'OMNIFERENCE_TOKEN_EXPORTER_URL',
                'http://localhost:9402/update'
            )
        else:
            self.exporter_url = 'http://localhost:9402/update'
        
        self.report_interval = report_interval
        self.lock = threading.Lock()
        
        # Internal state for automatic calculation
        self._token_count = 0
        self._request_count = 0
        self._last_report_time = time.time()
        self._last_token_count = 0
        self._last_request_count = 0
    
    def report_metrics(
        self,
        tokens_per_second: Optional[float] = None,
        total_tokens: Optional[int] = None,
        requests_per_second: Optional[float] = None,
        total_requests: Optional[int] = None
    ):
        """
        Report token metrics directly.
        
        Args:
            tokens_per_second: Current token generation rate
            total_tokens: Cumulative total tokens generated
            requests_per_second: Current request processing rate
            total_requests: Cumulative total requests processed
        """
        payload = {}
        if tokens_per_second is not None:
            payload['tokens_per_second'] = float(tokens_per_second)
        if total_tokens is not None:
            payload['total_tokens'] = int(total_tokens)
        if requests_per_second is not None:
            payload['requests_per_second'] = float(requests_per_second)
        if total_requests is not None:
            payload['total_requests'] = int(total_requests)
        
        if not payload:
            return
        
        self._send_metrics(payload)
    
    def report_tokens(
        self,
        tokens: int,
        elapsed_time: Optional[float] = None,
        auto_calculate_rate: bool = True
    ):
        """
        Report tokens generated and automatically calculate rate.
        
        Args:
            tokens: Number of tokens generated in this batch/request
            elapsed_time: Time elapsed for this batch (seconds)
            auto_calculate_rate: Automatically calculate tokens_per_second from internal state
        """
        with self.lock:
            self._token_count += tokens
            current_time = time.time()
            
            if elapsed_time and elapsed_time > 0:
                tokens_per_second = tokens / elapsed_time
            elif auto_calculate_rate:
                time_since_last = current_time - self._last_report_time
                if time_since_last >= self.report_interval:
                    tokens_since_last = self._token_count - self._last_token_count
                    tokens_per_second = tokens_since_last / time_since_last if time_since_last > 0 else 0.0
                    self._last_report_time = current_time
                    self._last_token_count = self._token_count
                else:
                    # Too soon, skip rate calculation
                    return
            
            payload = {
                'tokens_per_second': tokens_per_second if elapsed_time or auto_calculate_rate else 0.0,
                'total_tokens': self._token_count
            }
        
        self._send_metrics(payload)
    
    def report_request(self, tokens: Optional[int] = None):
        """
        Report a request processed.
        
        Args:
            tokens: Optional token count for this request
        """
        with self.lock:
            self._request_count += 1
            current_time = time.time()
            
            payload = {'total_requests': self._request_count}
            
            if tokens is not None:
                self._token_count += tokens
                payload['total_tokens'] = self._token_count
            
            # Calculate requests_per_second
            time_since_last = current_time - self._last_report_time
            if time_since_last >= self.report_interval:
                requests_since_last = self._request_count - self._last_request_count
                requests_per_second = requests_since_last / time_since_last if time_since_last > 0 else 0.0
                payload['requests_per_second'] = requests_per_second
                self._last_report_time = current_time
                self._last_request_count = self._request_count
        
        self._send_metrics(payload)
    
    def _send_metrics(self, payload: dict):
        """Send metrics to exporter (non-blocking, errors ignored)."""
        try:
            response = requests.post(
                self.exporter_url,
                json=payload,
                timeout=0.5  # Very short timeout to not block
            )
            # Don't raise on error - silently fail
        except Exception:
            # Silently ignore all errors - don't interrupt workload
            pass
    
    def reset(self):
        """Reset internal counters."""
        with self.lock:
            self._token_count = 0
            self._request_count = 0
            self._last_report_time = time.time()
            self._last_token_count = 0
            self._last_request_count = 0


# Global instance for convenience
_global_reporter: Optional[TokenReporter] = None


def get_reporter() -> TokenReporter:
    """Get or create global token reporter instance."""
    global _global_reporter
    if _global_reporter is None:
        _global_reporter = TokenReporter()
    return _global_reporter


def report_tokens(tokens: int, elapsed_time: Optional[float] = None):
    """Convenience function to report tokens using global reporter."""
    get_reporter().report_tokens(tokens, elapsed_time)


def report_metrics(**kwargs):
    """Convenience function to report metrics using global reporter."""
    get_reporter().report_metrics(**kwargs)

