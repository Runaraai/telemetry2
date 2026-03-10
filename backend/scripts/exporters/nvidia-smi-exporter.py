#!/usr/bin/env python3
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class MetricsCollector:
    def __init__(self):
        self.metrics = ""
        self.lock = threading.Lock()

    def collect(self):
        try:
            # Query comprehensive nvidia-smi metrics
            cmd = [
                'nvidia-smi',
                '--query-gpu=index,name,uuid,temperature.gpu,utilization.gpu,utilization.memory,'
                'memory.total,memory.free,memory.used,power.draw,power.limit,clocks.sm,clocks.mem,'
                'clocks.gr,fan.speed,pcie.link.gen.current,pcie.link.width.current,encoder.stats.sessionCount,'
                'encoder.stats.averageFps,encoder.stats.averageLatency',
                '--format=csv,noheader,nounits'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode != 0:
                return
            
            lines = result.stdout.strip().split('\n')
            metrics_lines = []
            
            for line in lines:
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 20:
                    continue
                
                gpu_idx, name, uuid, temp, util_gpu, util_mem, mem_total, mem_free, mem_used, \
                    power_draw, power_limit, clock_sm, clock_mem, clock_gr, fan_speed, \
                    pcie_gen, pcie_width, enc_sessions, enc_fps, enc_latency = parts[:20]
                
                labels = f'gpu="{gpu_idx}",name="{name}",uuid="{uuid}"'
                
                # Temperature
                if temp and temp != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_temperature_celsius{{{labels}}} {temp}')
                
                # Utilization
                if util_gpu and util_gpu != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_utilization_gpu_percent{{{labels}}} {util_gpu}')
                if util_mem and util_mem != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_utilization_memory_percent{{{labels}}} {util_mem}')
                
                # Memory
                if mem_total and mem_total != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_memory_total_mib{{{labels}}} {mem_total}')
                if mem_free and mem_free != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_memory_free_mib{{{labels}}} {mem_free}')
                if mem_used and mem_used != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_memory_used_mib{{{labels}}} {mem_used}')
                
                # Power
                if power_draw and power_draw != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_power_draw_watts{{{labels}}} {power_draw}')
                if power_limit and power_limit != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_power_limit_watts{{{labels}}} {power_limit}')
                
                # Clocks
                if clock_sm and clock_sm != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_clock_sm_mhz{{{labels}}} {clock_sm}')
                if clock_mem and clock_mem != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_clock_memory_mhz{{{labels}}} {clock_mem}')
                if clock_gr and clock_gr != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_clock_graphics_mhz{{{labels}}} {clock_gr}')
                
                # Fan
                if fan_speed and fan_speed != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_fan_speed_percent{{{labels}}} {fan_speed}')
                
                # PCIe
                if pcie_gen and pcie_gen != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_pcie_link_gen{{{labels}}} {pcie_gen}')
                if pcie_width and pcie_width != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_pcie_link_width{{{labels}}} {pcie_width}')
                
                # Encoder
                if enc_sessions and enc_sessions != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_encoder_sessions{{{labels}}} {enc_sessions}')
                if enc_fps and enc_fps != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_encoder_fps{{{labels}}} {enc_fps}')
                if enc_latency and enc_latency != '[N/A]':
                    metrics_lines.append(f'nvidia_smi_encoder_latency_us{{{labels}}} {enc_latency}')
            
            with self.lock:
                self.metrics = '\n'.join(metrics_lines) + '\n'
        
        except Exception as e:
            print(f"Error collecting metrics: {e}")

    def get_metrics(self):
        with self.lock:
            return self.metrics

collector = MetricsCollector()

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(collector.get_metrics().encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Suppress logs

def collect_loop():
    while True:
        collector.collect()
        time.sleep(1)

if __name__ == '__main__':
    # Start collection thread
    thread = threading.Thread(target=collect_loop, daemon=True)
    thread.start()
    
    # Start HTTP server
    server = HTTPServer(('0.0.0.0', 9401), MetricsHandler)
    print("nvidia-smi exporter listening on :9401")
    server.serve_forever()
