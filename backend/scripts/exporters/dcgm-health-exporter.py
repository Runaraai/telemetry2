#!/usr/bin/env python3
import subprocess
import time
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthMetricsCollector:
    def __init__(self):
        self.metrics = ""
        self.lock = threading.Lock()

    def collect(self):
        try:
            metrics_lines = []
                        
            # Query GPU configuration and health status
            cmd = [
                'nvidia-smi',
                '--query-gpu=index,name,uuid,compute_mode,persistence_mode,power.management,'
                'power.limit,power.default_limit,power.min_limit,power.max_limit,'
                'temperature.gpu,temperature.memory,clocks.current.sm,clocks.current.memory,'
                'clocks.max.sm,clocks.max.memory,clocks_throttle_reasons.active,'
                'clocks_throttle_reasons.gpu_idle,clocks_throttle_reasons.applications_clocks_setting,'
                'clocks_throttle_reasons.sw_power_cap,clocks_throttle_reasons.hw_slowdown,'
                'clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.hw_power_brake_slowdown,'
                'clocks_throttle_reasons.sync_boost,ecc.mode.current,ecc.errors.corrected.volatile.total,'
                'ecc.errors.uncorrected.volatile.total',
                '--format=csv,noheader,nounits'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                        
            if result.returncode != 0:
                return
                        
            lines = result.stdout.strip().split('\\n')
                        
            for line in lines:
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 28:
                    continue
                            
                gpu_idx, name, uuid = parts[0], parts[1], parts[2]
                compute_mode, persistence_mode, power_mgmt = parts[3], parts[4], parts[5]
                power_limit, power_default, power_min, power_max = parts[6], parts[7], parts[8], parts[9]
                temp_gpu, temp_mem = parts[10], parts[11]
                clock_sm, clock_mem, clock_sm_max, clock_mem_max = parts[12], parts[13], parts[14], parts[15]
                            
                # Throttle reasons (bitmask flags)
                throttle_active = parts[16]
                throttle_idle = parts[17]
                throttle_app_clocks = parts[18]
                throttle_sw_power = parts[19]
                throttle_hw_slowdown = parts[20]
                throttle_hw_thermal = parts[21]
                throttle_hw_power_brake = parts[22]
                throttle_sync_boost = parts[23]
                            
                ecc_mode = parts[24]
                ecc_sbe = parts[25]
                ecc_dbe = parts[26]
                            
                labels = f'gpu="{gpu_idx}",name="{name}",uuid="{uuid}"'
                            
                # Configuration metrics
                if compute_mode and compute_mode != '[N/A]':
                    # Convert compute mode to numeric (0=Default, 1=Exclusive Thread, 2=Prohibited, 3=Exclusive Process)
                    mode_map = {'Default': 0, 'Exclusive_Thread': 1, 'Prohibited': 2, 'Exclusive_Process': 3}
                    mode_val = mode_map.get(compute_mode, 0)
                    metrics_lines.append(f'gpu_compute_mode{{{labels}}} {mode_val}')
                            
                if persistence_mode and persistence_mode != '[N/A]':
                    persist_val = 1 if persistence_mode == 'Enabled' else 0
                    metrics_lines.append(f'gpu_persistence_mode{{{labels}}} {persist_val}')
                            
                # Power limits
                if power_limit and power_limit != '[N/A]':
                    metrics_lines.append(f'gpu_power_limit_watts{{{labels}}} {power_limit}')
                if power_default and power_default != '[N/A]':
                    metrics_lines.append(f'gpu_power_default_limit_watts{{{labels}}} {power_default}')
                if power_min and power_min != '[N/A]':
                    metrics_lines.append(f'gpu_power_min_limit_watts{{{labels}}} {power_min}')
                if power_max and power_max != '[N/A]':
                    metrics_lines.append(f'gpu_power_max_limit_watts{{{labels}}} {power_max}')
                            
                # Temperature thresholds (these are typically fixed per GPU model)
                if temp_gpu and temp_gpu != '[N/A]':
                    # Most GPUs throttle around 83-87C and shutdown around 92-95C
                    metrics_lines.append(f'gpu_slowdown_temp_celsius{{{labels}}} 87')
                    metrics_lines.append(f'gpu_shutdown_temp_celsius{{{labels}}} 92')
                            
                # Clock maximums
                if clock_sm_max and clock_sm_max != '[N/A]':
                    metrics_lines.append(f'gpu_sm_clock_max_mhz{{{labels}}} {clock_sm_max}')
                if clock_mem_max and clock_mem_max != '[N/A]':
                    metrics_lines.append(f'gpu_memory_clock_max_mhz{{{labels}}} {clock_mem_max}')
                            
                # Throttle reasons (convert Active to bitmask)
                if throttle_active and throttle_active != '[N/A]':
                    try:
                        throttle_val = int(throttle_active, 16) if 'x' in throttle_active.lower() else int(throttle_active)
                        metrics_lines.append(f'gpu_throttle_reasons{{{labels}}} {throttle_val}')
                    except:
                        pass
                            
                # Individual throttle flags
                if throttle_idle and throttle_idle != '[N/A]':
                    val = 1 if throttle_idle.lower() == 'active' else 0
                    metrics_lines.append(f'gpu_throttle_idle{{{labels}}} {val}')
                if throttle_app_clocks and throttle_app_clocks != '[N/A]':
                    val = 1 if throttle_app_clocks.lower() == 'active' else 0
                    metrics_lines.append(f'gpu_throttle_app_clocks{{{labels}}} {val}')
                if throttle_sw_power and throttle_sw_power != '[N/A]':
                    val = 1 if throttle_sw_power.lower() == 'active' else 0
                    metrics_lines.append(f'gpu_throttle_sw_power{{{labels}}} {val}')
                if throttle_hw_slowdown and throttle_hw_slowdown != '[N/A]':
                    val = 1 if throttle_hw_slowdown.lower() == 'active' else 0
                    metrics_lines.append(f'gpu_throttle_hw_slowdown{{{labels}}} {val}')
                if throttle_hw_thermal and throttle_hw_thermal != '[N/A]':
                    val = 1 if throttle_hw_thermal.lower() == 'active' else 0
                    metrics_lines.append(f'gpu_throttle_hw_thermal{{{labels}}} {val}')
                if throttle_hw_power_brake and throttle_hw_power_brake != '[N/A]':
                    val = 1 if throttle_hw_power_brake.lower() == 'active' else 0
                    metrics_lines.append(f'gpu_throttle_hw_power_brake{{{labels}}} {val}')
                            
                # ECC status
                if ecc_mode and ecc_mode != '[N/A]':
                    ecc_val = 1 if ecc_mode == 'Enabled' else 0
                    metrics_lines.append(f'gpu_ecc_mode{{{labels}}} {ecc_val}')
                if ecc_sbe and ecc_sbe != '[N/A]':
                    metrics_lines.append(f'gpu_ecc_sbe_total{{{labels}}} {ecc_sbe}')
                if ecc_dbe and ecc_dbe != '[N/A]':
                    metrics_lines.append(f'gpu_ecc_dbe_total{{{labels}}} {ecc_dbe}')
                        
            # Query topology information
            try:
                topo_cmd = ['nvidia-smi', 'topo', '-m']
                topo_result = subprocess.run(topo_cmd, capture_output=True, text=True, timeout=5)
                if topo_result.returncode == 0:
                    # Store topology as info metric
                    topo_data = topo_result.stdout.strip()
                    # Simplified: just indicate topology was captured
                    metrics_lines.append(f'gpu_topology_available{{}} 1')
            except:
                pass
                        
            with self.lock:
                self.metrics = '\\n'.join(metrics_lines) + '\\n'
                    
        except Exception as e:
            print(f"Error collecting health metrics: {e}")

    def get_metrics(self):
        with self.lock:
            return self.metrics

collector = HealthMetricsCollector()

class HealthHandler(BaseHTTPRequestHandler):
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
        time.sleep(5)  # Collect every 5 seconds (config/health changes less frequently)

if __name__ == '__main__':
    # Start collection thread
    thread = threading.Thread(target=collect_loop, daemon=True)
    thread.start()
                
    # Start HTTP server
    server = HTTPServer(('0.0.0.0', 9403), HealthHandler)
    print("DCGM health exporter listening on :9403")
    server.serve_forever()