# Model Selection and Cheapest Instance Determination - Deep Dive

## Overview

This document provides a comprehensive analysis of how the system selects the optimal GPU instance/cloud resource for running a model, with a focus on cost optimization. The system uses a **Total Cost of Ownership (TCO)** approach to determine the cheapest viable configuration.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [TCO Calculation Methodology](#tco-calculation-methodology)
3. [Candidate Generation](#candidate-generation)
4. [Candidate Evaluation and Sorting](#candidate-evaluation-and-sorting)
5. [Best Instance Selection](#best-instance-selection)
6. [Code Flow Analysis](#code-flow-analysis)
7. [Accuracy Assessment](#accuracy-assessment)

---

## Architecture Overview

The model selection and cost optimization system consists of three main components:

1. **Scheduler (`backend/api/scheduler.py`)**: Orchestrates the selection process
2. **DAG Generator (`backend/api/dag_generator.py`)**: Calculates feasibility and TCO metrics
3. **Performance Modeler (`core/performance_modeler.py`)**: Estimates job metrics

### High-Level Flow

```
User Request (model_id, datacenter, workload)
    ↓
Scheduler.schedule()
    ↓
Generate GPU Configurations (all possible gang sizes)
    ↓
Calculate Feasibility Matrix (for all configs)
    ↓
Filter Feasible Candidates (memory + availability)
    ↓
Sort by TCO (cheapest first)
    ↓
Select Best Candidate
    ↓
Allocate Resources
```

---

## TCO Calculation Methodology

### What is TCO?

**Total Cost of Ownership (TCO)** represents the cost per 1,000 tokens processed. It includes:
- **GPU rental costs** (hourly instance pricing)
- **Power costs** (for custom datacenters only)
- **Throughput efficiency** (tokens per second)

### TCO Formula

The TCO calculation is performed in `backend/api/dag_generator.py` in the `_process_gpu_config` function:

```2246:2254:backend/api/dag_generator.py
        if tokens_per_sec > 0:
            tokens_per_hour = tokens_per_sec * 3600
            cost_per_million_tokens = (total_hourly_cost / tokens_per_hour) * 1e6
            cost_per_1k_tokens = (total_hourly_cost / tokens_per_hour) * 1e3
        else:
            # If tokens_per_sec is 0, the model cannot run on this GPU config
            # Set to None instead of inf so it can be properly handled
            cost_per_million_tokens = None
            cost_per_1k_tokens = None
```

**Formula Breakdown:**
```
TCO_per_1k_tokens = (total_hourly_cost / tokens_per_hour) × 1,000

Where:
- tokens_per_hour = tokens_per_sec × 3,600
- total_hourly_cost = GPU_cost + Power_cost (if applicable)
```

### Cost Components

#### 1. GPU Rental Cost

For cloud instances, the cost comes from the instance pricing:

```2101:2110:backend/api/dag_generator.py
        if instances_required is None:
            cost_per_hour = instance_cost_per_hour * gang_size
            effective_cost_per_gpu = instance_cost_per_hour
            effective_instances_required = None
            effective_num_gpus_per_instance = 1
        else:
            cost_per_hour = instance_cost_per_hour * instances_required
            effective_num_gpus_per_instance = num_gpus_per_instance
            effective_instances_required = instances_required
            effective_cost_per_gpu = cost_per_hour / gang_size if gang_size > 0 else instance_cost_per_hour
```

**Key Logic:**
- If `instances_required` is None: Cost = `instance_cost_per_hour × gang_size`
- If `instances_required` is set: Cost = `instance_cost_per_hour × instances_required`

**Example:**
- Instance: `g5.12xlarge` with 4 GPUs, $3.00/hour
- Gang size: 8 GPUs needed
- `instances_required = ceil(8/4) = 2`
- `cost_per_hour = $3.00 × 2 = $6.00`

#### 2. Power Cost (Custom Datacenters Only)

Power costs are only included for custom datacenters, not cloud instances:

```2228:2244:backend/api/dag_generator.py
        is_cloud_instance = (
            cloud_provider is not None
            and cloud_provider != ""
            and cloud_provider != "custom_fleet"
        )
        
        # Get power watts for reporting (even for cloud instances, for informational purposes)
        power_watts_each = gpu_power_watts.get(gpu_type, 400)
        
        if is_cloud_instance:
            # Cloud instances: only GPU rental cost (power already included in cloud pricing)
            power_cost_per_hour_total = 0.0
            total_hourly_cost = cost_per_hour
        else:
            # Custom datacenters: include both GPU and power costs
            power_cost_per_hour_total = (power_watts_each / 1000) * 1.2 * 0.12 * gang_size
            total_hourly_cost = cost_per_hour + power_cost_per_hour_total
```

**Power Cost Formula:**
```
power_cost_per_hour = (power_watts_each / 1000) × 1.2 × $0.12 × gang_size

Where:
- power_watts_each: GPU power consumption (e.g., 400W for A100)
- 1.2: PUE (Power Usage Effectiveness) overhead
- $0.12: Cost per kWh
- gang_size: Number of GPUs
```

**Example:**
- GPU: A100 (400W each)
- Gang size: 8 GPUs
- Power cost = (400/1000) × 1.2 × $0.12 × 8 = $0.46/hour

### Throughput Calculation

Throughput (tokens per second) is critical for TCO because it determines how efficiently resources are utilized. The calculation considers:

1. **Compute-bound throughput** (FLOPs-based)
2. **Memory-bound throughput** (bandwidth-based)
3. **Tensor Parallelism efficiency** (communication overhead)

```2173:2220:backend/api/dag_generator.py
        single_gpu_tokens_per_sec = (
            (tflops * 1e12) * util_efficiency / flops_per_token
        ) if flops_per_token > 0 else 0

        bytes_per_param = {"fp16": 2, "fp32": 4, "int8": 1, "fp8": 1}.get(request.precision, 2)
        memory_ceiling_tokens_per_sec = (
            (memory_bandwidth_gbs * 1e9) / (total_params * bytes_per_param)
        ) if total_params > 0 else 0

        tokens_per_sec = min(single_gpu_tokens_per_sec, memory_ceiling_tokens_per_sec)
        dp_tokens_per_sec = tokens_per_sec * gang_size

        # TP communication overhead
        tp_comm_efficiency_map = {
            1: 1.00, 2: 0.90, 4: 0.80, 8: 0.70,
            16: 0.60, 32: 0.55, 64: 0.50, 128: 0.50
        }

        if gang_size in tp_comm_efficiency_map:
            tp_comm_efficiency = tp_comm_efficiency_map[gang_size]
        else:
            lower, upper = 1, 128
            for size in [1, 2, 4, 8, 16, 32, 64, 128]:
                if size < gang_size:
                    lower = size
                if size > gang_size and upper == 128:
                    upper = size
                    break
            if lower == upper:
                tp_comm_efficiency = tp_comm_efficiency_map[lower]
            else:
                lower_eff = tp_comm_efficiency_map[lower]
                upper_eff = tp_comm_efficiency_map[upper]
                ratio = (gang_size - lower) / (upper - lower)
                tp_comm_efficiency = lower_eff + (upper_eff - lower_eff) * ratio

        tp_tokens_per_sec = (
            (tflops * 1e12) * gang_size * util_efficiency * tp_comm_efficiency / flops_per_token
        ) if flops_per_token > 0 else 0

        if memory_profile["summary"]["weights_gib"] <= gpu_memory_gb:
            recommended_mode = "DP" if gang_size > 1 else "Single"
            tokens_per_sec = dp_tokens_per_sec
            throughput_note = f"DP: {gang_size} replicas" if gang_size > 1 else "Single GPU"
        else:
            recommended_mode = "TP"
            tokens_per_sec = tp_tokens_per_sec
            throughput_note = f"TP: {gang_size} GPUs (single stream)"
```

**Key Points:**
- **Compute-bound**: Limited by GPU FLOPs and utilization efficiency
- **Memory-bound**: Limited by memory bandwidth
- **Actual throughput**: Minimum of compute-bound and memory-bound
- **TP overhead**: Communication efficiency decreases with gang size (50% efficiency at 64+ GPUs)

---

## Candidate Generation

### Smart Gang Size Generation

The system doesn't test all possible gang sizes. Instead, it uses intelligent heuristics to generate relevant configurations:

```741:821:backend/api/scheduler.py
    def _generate_smart_gang_sizes(
        self,
        gpu_memory_gb: float,
        total_available: int,
        gpus_per_server: int = 8,
        max_gang_size: int = 64
    ) -> List[int]:
        """
        Generate intelligent gang sizes based on GPU memory and topology.
        
        Args:
            gpu_memory_gb: Memory capacity of single GPU
            total_available: Total GPUs available of this type
            gpus_per_server: GPUs per server (for topology optimization)
            max_gang_size: Maximum gang size to test
            
        Returns:
            List of gang sizes to test, optimized for:
            - Memory efficiency (powers of 2 for common model sizes)
            - Topology efficiency (multiples of gpus_per_server)
            - Practical allocation ranges
        """
        max_test = min(total_available, max_gang_size)
        
        if max_test < 1:
            return []
        
        gang_sizes = set()
        
        # 1. Always test single GPU
        gang_sizes.add(1)
        
        # 2. Add powers of 2 (common for TP: 2, 4, 8, 16, 32)
        power = 1
        while power <= max_test:
            gang_sizes.add(power)
            power *= 2
        
        # Normalize topology inputs to avoid zero-division
        gpus_per_server = max(1, int(gpus_per_server) if gpus_per_server is not None else 1)
        half_server = max(1, gpus_per_server // 2)

        # 3. Add server-aligned sizes (optimal for NVLink)
        # Full servers: 8, 16, 24, 32, 40, 48...
        for n_servers in range(1, (max_test // gpus_per_server) + 2):
            size = n_servers * gpus_per_server
            if size <= max_test:
                gang_sizes.add(size)
        
        # 4. Add some intermediate sizes for flexibility
        # Half-server increments: 4, 12, 20, 28...
        if half_server > 0:
            for n in range(1, (max_test // half_server) + 1):
                size = n * half_server
                if size <= max_test:
                    gang_sizes.add(size)
        
        # 5. For larger models, add sizes that might be memory-optimal
        # Common model memory requirements: 70B, 405B models
        # 70B ≈ 140GB → needs ~2-3 GPUs @ 80GB, ~3-4 @ 48GB
        # 405B ≈ 900GB → needs ~12 GPUs @ 80GB, ~19 @ 48GB
        
        # Add sizes around common memory breakpoints
        if gpu_memory_gb <= 50:  # L40s, A100-40GB
            # For 48GB GPUs, add: 3, 6, 12, 19, 24
            for size in [3, 6, 12, 19]:
                if size <= max_test:
                    gang_sizes.add(size)
        elif gpu_memory_gb <= 90:  # A100-80GB, H100
            # For 80GB GPUs, add: 2, 3, 6, 12
            for size in [2, 3, 6, 12]:
                if size <= max_test:
                    gang_sizes.add(size)
        else:  # B200, H20 (large memory)
            # For 192GB+ GPUs, smaller gangs work for most models
            for size in [2, 3, 4, 5, 6]:
                if size <= max_test:
                    gang_sizes.add(size)
        
        # Sort and return
        return sorted(gang_sizes)
```

**Strategy:**
1. **Always test single GPU** (baseline)
2. **Powers of 2** (common for tensor parallelism: 2, 4, 8, 16, 32)
3. **Server-aligned sizes** (optimal for NVLink: 8, 16, 24, 32...)
4. **Half-server increments** (flexibility: 4, 12, 20, 28...)
5. **Memory-optimal sizes** (based on GPU memory capacity)

### Cloud Instance Configuration

For cloud instances, the system only tests exact instance configurations (no arbitrary gang sizes):

```1073:1098:backend/api/scheduler.py
            if datacenter_name == "cloud_instances":
                # Extract exact num_gpus from available instance types
                available_instance_sizes = sorted(set([
                    row.get("num_gpus", 1)
                    for row in inventory.cloud_pricing
                    if row.get("num_gpus") is not None
                ]))
                if not available_instance_sizes:
                    available_instance_sizes = [1]  # Fallback if no num_gpus specified

                # Calculate minimum GPUs needed for THIS specific GPU type
                if model_memory_gb and gpu_memory_gb:
                    # Add 20% overhead for KV cache, activations, runtime overhead
                    min_gpus_needed = max(1, math.ceil(model_memory_gb * 1.2 / gpu_memory_gb))
                    # Filter to only test instance sizes >= minimum
                    gang_sizes = [size for size in available_instance_sizes if size >= min_gpus_needed]
                    if not gang_sizes:
                        # Model too large even for biggest instance, include largest for proper error message
                        gang_sizes = [max(available_instance_sizes)]
                    print(f"🔍 {inventory.gpu_type} ({gpu_memory_gb}GB): min_gpus={min_gpus_needed}, testing {gang_sizes}")
                else:
                    # No model memory estimate, test all available sizes
                    gang_sizes = available_instance_sizes
                    print(f"Cloud instance gang sizes for {inventory.gpu_type} ({gpu_memory_gb}GB VRAM): {gang_sizes}")
```

**Key Logic:**
- Only test instance sizes that actually exist (e.g., 1, 4, 8 GPUs per instance)
- Filter by minimum GPUs needed: `ceil(model_memory_gb × 1.2 / gpu_memory_gb)`
- Prevents testing infeasible configurations

---

## Candidate Evaluation and Sorting

### Feasibility Check

Before evaluating cost, the system checks if a configuration is feasible:

```1210:1237:backend/api/scheduler.py
        # Find candidates that can run NOW (have available GPUs)
        candidates: List[Tuple[float, Dict[str, Any], GPUInventory, int]] = []
        for result in gpu_results:
            if not result.get("feasible"):
                continue

            # Get the physical inventory (always gang_size=1)
            gpu_type = result.get("gpu_type")
            requested_gang_size = result.get("gang_size", 1)
            key = (gpu_type, 1)  # Physical inventory key
            inventory = state.inventories.get(key)
            
            if not inventory:
                continue

            # Check if we have enough available GPUs for this gang size
            # Skip availability check for cloud instances (they're on-demand and always available)
            if datacenter_name != "cloud_instances":
                available_gpus = inventory.total - inventory.used
                if available_gpus < requested_gang_size:
                    continue
            
            tco_per_1k = result.get("tco_per_1k_tokens")
            if not tco_per_1k or tco_per_1k <= 0:
                continue
            
            # Store: (tco, result, inventory, gang_size)
            candidates.append((tco_per_1k, result, inventory, requested_gang_size))
```

**Feasibility Criteria:**
1. **Memory feasibility**: Model must fit in GPU memory (checked in DAG generator)
2. **Availability**: Enough GPUs available (for physical datacenters)
3. **Valid TCO**: TCO must be positive and non-zero

### Sorting Algorithm

The system uses a multi-criteria sorting approach to select the best candidate:

```1241:1272:backend/api/scheduler.py
        def _candidate_sort_tuple(candidate_result: Dict[str, Any]) -> tuple:
            """Create sorting tuple enforcing no-overprovision preference then TCO, cost, throughput."""
            gang = candidate_result.get("gang_size", 1)
            num_per_instance = candidate_result.get("num_gpus_per_instance")
            instances_required = candidate_result.get("instances_required")
            if num_per_instance and instances_required:
                total_provisioned = num_per_instance * instances_required
                over_provisioned = total_provisioned > gang
            else:
                over_provisioned = False

            tco = candidate_result.get("tco_per_1k_tokens")
            if tco is None or tco <= 0:
                tco = float("inf")

            total_hourly_cost = 0.0
            for key_cost in ("hourly_gpu_spend", "hourly_power_spend"):
                value = candidate_result.get(key_cost)
                if value is not None:
                    total_hourly_cost += value
            if total_hourly_cost <= 0:
                total_hourly_cost = float("inf")

            # Prefer higher throughput if costs tie
            throughput = candidate_result.get("tokens_per_sec", 0) or 0

            return (
                over_provisioned,
                tco,
                total_hourly_cost,
                -throughput,
            )
```

**Sorting Criteria (in priority order):**

1. **Over-provisioning** (Boolean): Prefer configurations that don't over-provision
   - `over_provisioned = True` if `num_gpus_per_instance × instances_required > gang_size`
   - Example: Need 6 GPUs, but instance has 8 GPUs → over-provisioned

2. **TCO per 1k tokens** (Float): Lower is better
   - Primary cost metric
   - Directly reflects cost efficiency

3. **Total hourly cost** (Float): Lower is better
   - Secondary cost metric (for tie-breaking)
   - Includes GPU + power costs

4. **Throughput** (Negative, so higher is better): Higher is better
   - For final tie-breaking
   - Prefer faster configurations if costs are identical

**Example Sorting:**
```
Config A: over_provisioned=False, TCO=$0.05, cost=$10/hr, throughput=100 tok/s
Config B: over_provisioned=False, TCO=$0.06, cost=$8/hr,  throughput=80 tok/s
Config C: over_provisioned=True,  TCO=$0.04, cost=$12/hr, throughput=120 tok/s

Sorted order: A, B, C
- A wins: same over-provisioning, lower TCO
- B second: same over-provisioning, higher TCO than A
- C last: over-provisioned (even though cheapest TCO)
```

---

## Best Instance Selection

### Selection Process

After sorting, the best candidate is selected:

```1352:1355:backend/api/scheduler.py
        print(f"⚡ Sorting {len(candidates)} candidates by TCO...")
        candidates.sort(key=lambda item: _candidate_sort_tuple(item[1]))
        best_tco_per_1k, best_result, inventory, gang_size = candidates[0]
        print(f"✅ Best candidate: {best_result.get('gpu_type')} x{gang_size} @ ${best_tco_per_1k:.6f}/1k tokens")
```

**Process:**
1. Sort all candidates using `_candidate_sort_tuple`
2. Select the first candidate (lowest TCO, no over-provisioning)
3. Extract best configuration details

### Alternative Configurations

The system also tracks all alternative configurations for transparency:

```1357:1416:backend/api/scheduler.py
        # Store all GPU type alternatives for transparency
        # Group by GPU type and cloud provider and pick best (lowest TCO) config for each variant
        all_alternatives = []
        gpu_type_best: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}

        print(f"📋 Building alternatives list from {len(gpu_results)} GPU results...")
        for result in gpu_results:
            if not result.get("feasible"):
                continue
            
            gpu_type = result.get("gpu_type")
            requested_gang_size = result.get("gang_size", 1)
            tco = result.get("tco_per_1k_tokens", 0)
            cloud_provider = result.get("cloud")
            
            # Skip if TCO is None, 0, negative, or invalid (inf/nan)
            if tco is None or tco <= 0 or not isinstance(tco, (int, float)) or math.isinf(tco) or math.isnan(tco):
                continue
            
            variant_key = (gpu_type, cloud_provider)

            # Keep only the best (lowest TCO) config for each GPU/cloud variant
            if variant_key not in gpu_type_best or tco < gpu_type_best[variant_key]['tco']:
                gpu_type_best[variant_key] = {
                    'tco': tco,
                    'gang_size': requested_gang_size,
                    'result': result
                }
        
        # Convert to list and sort by TCO
        selected_cloud = best_result.get("cloud")
        selected_cost_each = best_result.get("cost_per_hour_single")
        selected_regions = best_result.get("regions", [])
        selected_all_availability = best_result.get("all_availability", [])
        for (gpu_type, cloud_provider), best_config in sorted(gpu_type_best.items(), key=lambda x: x[1]['tco']):
            result = best_config['result']
            gs = best_config['gang_size']
            tco = best_config['tco']
            cost_each = result.get("cost_per_hour_single")
            
            all_alternatives.append({
                "gpu_type": gpu_type,
                "cloud": cloud_provider,
                "gang_size": gs,
                "tco_per_1k_tokens": round(tco, 6),
                "tokens_per_sec": result.get("tokens_per_sec", 0),
                "total_memory_gb": gs * result.get("vram_gb", 80),
                "deployment_mode": result.get("deployment_mode", "TP"),
                "cost_per_hour_each": cost_each,
                "regions": result.get("regions", []),
                "num_gpus_per_instance": result.get("num_gpus_per_instance"),
                "instances_required": result.get("instances_required"),
                "instance_hourly_cost": result.get("instance_hourly_cost"),
                "shade_instance_type": result.get("shade_instance_type"),
                "is_selected": (
                    gpu_type == inventory.gpu_type
                    and gs == gang_size
                    and cloud_provider == selected_cloud
                ),
            })
```

**Purpose:**
- Shows all viable alternatives (grouped by GPU type + cloud provider)
- Helps users understand trade-offs
- Enables comparison with selected configuration

---

## Code Flow Analysis

### Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. User Request: schedule(model_id, datacenter, workload)  │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Load Datacenter Configuration                            │
│    - Load hardware configs or cloud instances                │
│    - Initialize GPU inventories                              │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Generate GPU Configurations                               │
│    - For each GPU type in datacenter:                        │
│      * Generate smart gang sizes (1, 2, 4, 8, 16...)         │
│      * For cloud: use exact instance sizes                   │
│      * Create config: {type, gang_size, cost_per_hour, ...}│
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Calculate Feasibility Matrix                               │
│    - Call calculate_feasibility_matrix()                       │
│    - For each GPU config:                                     │
│      * Check memory feasibility                               │
│      * Calculate throughput (tokens/sec)                     │
│      * Calculate TCO (cost per 1k tokens)                     │
│      * Return: {feasible, tco_per_1k_tokens, ...}            │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Filter Feasible Candidates                                 │
│    - Filter: result.get("feasible") == True                   │
│    - Filter: Available GPUs >= gang_size                     │
│    - Filter: TCO > 0                                         │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Sort Candidates                                            │
│    - Sort by: (over_provisioned, TCO, hourly_cost, -throughput)│
│    - Best candidate = candidates[0]                           │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. Allocate Resources                                         │
│    - Acquire GPU slots from inventory                         │
│    - Create job record                                        │
│    - Register with simulation engine                         │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. Return Response                                            │
│    - best_gpu: Selected configuration                       │
│    - all_alternatives: All viable alternatives              │
│    - assignment: Job assignment details                      │
└─────────────────────────────────────────────────────────────┘
```

### Key Functions

#### `SchedulerManager.schedule()`

Main entry point for scheduling:

```1032:1048:backend/api/scheduler.py
    async def schedule(
        self,
        model_id: str,
        datacenter_name: str,
        workload: Dict[str, Any],
        filtered_instances: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        # Store filtered instances for cloud instance scheduling
        if datacenter_name == "cloud_instances" and filtered_instances:
            self._filtered_cloud_instances = filtered_instances
            # Clear cached state for cloud_instances to force re-initialization with filtered instances
            if datacenter_name in self._datacenters:
                del self._datacenters[datacenter_name]
        else:
            self._filtered_cloud_instances = None

        state = self._get_state(datacenter_name)

        if not state.inventories:
            raise HTTPException(status_code=400, detail="Datacenter has no GPU inventory defined.")
```

#### `_process_gpu_config()`

Processes a single GPU configuration and calculates TCO:

```2058:2308:backend/api/dag_generator.py
def _process_gpu_config(
    gpu_config: Dict[str, Any],
    model_id: str,
    static_memory: Dict[str, Any],
    request: FeasibilityMatrixRequest,
    gpu_memory_specs: Dict[str, int],
    gpu_tflops: Dict[str, int],
    gpu_power_watts: Dict[str, int]
) -> Optional[Dict[str, Any]]:
    """
    Process a single GPU configuration for feasibility calculation.
    This function is designed to be thread-safe and can run in parallel.

    Returns:
        Result dictionary, None to skip, or error dictionary with 'error' key
    """
```

**Key Steps:**
1. Extract GPU configuration (type, gang_size, cost_per_hour)
2. Calculate instance requirements (instances_required)
3. Calculate hourly costs (GPU + power)
4. Check memory feasibility
5. Calculate throughput (tokens_per_sec)
6. Calculate TCO (cost_per_1k_tokens)
7. Return result dictionary

---

## Accuracy Assessment

### Strengths

1. **Comprehensive Cost Model**
   - Includes GPU rental + power costs
   - Accounts for cloud vs. custom datacenter differences
   - Considers instance-level pricing (multi-GPU instances)

2. **Realistic Throughput Estimation**
   - Accounts for compute-bound and memory-bound limits
   - Includes tensor parallelism communication overhead
   - Uses model-specific efficiency factors

3. **Smart Configuration Generation**
   - Only tests relevant gang sizes (not exhaustive)
   - Optimizes for topology (server-aligned sizes)
   - Filters infeasible configurations early

4. **Multi-Criteria Selection**
   - Prioritizes avoiding over-provisioning
   - Uses TCO as primary metric
   - Considers throughput for tie-breaking

### Potential Limitations

1. **Throughput Estimation Accuracy**
   - Uses simplified efficiency models (eta_compute)
   - Communication overhead is approximated (not measured)
   - Doesn't account for network latency between instances

2. **Power Cost Assumptions**
   - Fixed PUE of 1.2 (may vary by datacenter)
   - Fixed power cost of $0.12/kWh (may vary by region)
   - Doesn't account for dynamic power scaling

3. **Instance Availability**
   - Assumes cloud instances are always available
   - Doesn't account for spot instance pricing
   - Doesn't consider regional availability differences

4. **Gang Size Selection**
   - Heuristic-based (may miss optimal configurations)
   - Doesn't test all possible combinations
   - May not find optimal for unusual model sizes

### Recommendations for Improvement

1. **Add Measured Throughput Data**
   - Collect real-world throughput measurements
   - Use measured data instead of theoretical calculations
   - Account for framework overhead (PyTorch, TensorRT, etc.)

2. **Improve Power Cost Modeling**
   - Allow per-datacenter PUE configuration
   - Support regional power cost variations
   - Account for dynamic power scaling

3. **Enhance Cloud Instance Selection**
   - Consider spot instance pricing
   - Account for regional availability
   - Include reserved instance pricing options

4. **Optimize Gang Size Generation**
   - Use model memory requirements to guide selection
   - Test more configurations for large models
   - Consider mixed precision strategies

---

## Summary

The model selection and cheapest instance determination system uses a **sophisticated TCO-based approach** that:

1. **Generates intelligent GPU configurations** based on model requirements and topology
2. **Calculates accurate TCO metrics** including GPU rental and power costs
3. **Evaluates throughput realistically** accounting for compute, memory, and communication limits
4. **Selects optimal configurations** using multi-criteria sorting (over-provisioning, TCO, cost, throughput)
5. **Provides transparency** by showing all viable alternatives

The system is **well-designed and accurate** for most use cases, with some limitations in throughput estimation and power cost modeling that could be improved with real-world measurements and more sophisticated modeling.


