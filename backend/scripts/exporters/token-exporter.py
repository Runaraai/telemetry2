#!/usr/bin/env python3
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from pathlib import Path

class TokenMetrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.data_file = Path('/data/tokens.json')
        self.metrics = {
            'tokens_per_second': 0.0,
            'total_tokens': 0,
            'requests_per_second': 0.0,
            'total_requests': 0,
            'ttft_p50_ms': 0.0,
            'ttft_p95_ms': 0.0,
            'cost_per_watt': 0.0,
            'last_update': 0
        }
        self.load_data()

    def load_data(self):
        try:
            if self.data_file.exists():
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    with self.lock:
                        self.metrics.update(data)
        except Exception as e:
            print(f"Error loading data: {e}")

    def save_data(self):
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            with self.lock:
                with open(self.data_file, 'w') as f:
                    json.dump(self.metrics, f)
        except Exception as e:
            print(f"Error saving data: {e}")

    def update_metrics(self, tokens_per_sec=None, total_tokens=None, 
                     requests_per_sec=None, total_requests=None,
                     ttft_p50_ms=None, ttft_p95_ms=None, cost_per_watt=None):
        with self.lock:
            if tokens_per_sec is not None:
                self.metrics['tokens_per_second'] = float(tokens_per_sec)
            if total_tokens is not None:
                self.metrics['total_tokens'] = int(total_tokens)
            if requests_per_sec is not None:
                self.metrics['requests_per_second'] = float(requests_per_sec)
            if total_requests is not None:
                self.metrics['total_requests'] = int(total_requests)
            if ttft_p50_ms is not None:
                self.metrics['ttft_p50_ms'] = float(ttft_p50_ms)
            if ttft_p95_ms is not None:
                self.metrics['ttft_p95_ms'] = float(ttft_p95_ms)
            if cost_per_watt is not None:
                self.metrics['cost_per_watt'] = float(cost_per_watt)
            self.metrics['last_update'] = time.time()
        self.save_data()

    def get_prometheus_metrics(self):
        with self.lock:
            lines = [
                '# HELP token_throughput_per_second Current token generation throughput',
                '# TYPE token_throughput_per_second gauge',
                f'token_throughput_per_second {self.metrics["tokens_per_second"]}',
                '',
                '# HELP tokens_per_second Alias for token_throughput_per_second (for compatibility)',
                '# TYPE tokens_per_second gauge',
                f'tokens_per_second {self.metrics["tokens_per_second"]}',
                '',
                '# HELP token_total_generated Total tokens generated',
                '# TYPE token_total_generated counter',
                f'token_total_generated {self.metrics["total_tokens"]}',
                '',
                '# HELP inference_requests_per_second Current request throughput',
                '# TYPE inference_requests_per_second gauge',
                f'inference_requests_per_second {self.metrics["requests_per_second"]}',
                '',
                '# HELP inference_total_requests Total inference requests',
                '# TYPE inference_total_requests counter',
                f'inference_total_requests {self.metrics["total_requests"]}',
                '',
                '# HELP ttft_p50_ms Time to first token P50 in milliseconds',
                '# TYPE ttft_p50_ms gauge',
                f'ttft_p50_ms {self.metrics["ttft_p50_ms"]}',
                '',
                '# HELP ttft_p95_ms Time to first token P95 in milliseconds',
                '# TYPE ttft_p95_ms gauge',
                f'ttft_p95_ms {self.metrics["ttft_p95_ms"]}',
                '',
                '# HELP cost_per_watt Performance per watt (tokens per second per watt)',
                '# TYPE cost_per_watt gauge',
                f'cost_per_watt {self.metrics["cost_per_watt"]}',
                '',
                '# HELP performance_per_watt Alias for cost_per_watt (for compatibility)',
                '# TYPE performance_per_watt gauge',
                f'performance_per_watt {self.metrics["cost_per_watt"]}',
                '',
                '# HELP token_metrics_last_update_timestamp Last update timestamp',
                '# TYPE token_metrics_last_update_timestamp gauge',
                f'token_metrics_last_update_timestamp {self.metrics["last_update"]}',
                ''
            ]
            return '\n'.join(lines)

token_metrics = TokenMetrics()

class TokenHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(token_metrics.get_prometheus_metrics().encode())
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/update':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)
                data = json.loads(body.decode())
                            
                token_metrics.update_metrics(
                    tokens_per_sec=data.get('tokens_per_second'),
                    total_tokens=data.get('total_tokens'),
                    requests_per_sec=data.get('requests_per_second'),
                    total_requests=data.get('total_requests'),
                    ttft_p50_ms=data.get('ttft_p50_ms'),
                    ttft_p95_ms=data.get('ttft_p95_ms'),
                    cost_per_watt=data.get('cost_per_watt')
                )
                            
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logs

def reload_loop():
    while True:
        time.sleep(5)
        token_metrics.load_data()

if __name__ == '__main__':
    # Start reload thread
    thread = threading.Thread(target=reload_loop, daemon=True)
    thread.start()
                
    # Start HTTP server
    server = HTTPServer(('0.0.0.0', 9402), TokenHandler)
    print("Token exporter listening on :9402")
    print("POST metrics to http://localhost:9402/update with JSON:")
    print('  {"tokens_per_second": 123.4, "total_tokens": 5000, "requests_per_second": 2.5, "total_requests": 100}')
    server.serve_forever()