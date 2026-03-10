"""
AI-powered telemetry insights endpoint for GPU metrics analysis.
"""

import logging
import hashlib
import time
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
import statistics
import os

from mapper.services.llm_recommendation_engine import LLMRecommendationEngine

logger = logging.getLogger(__name__)
router = APIRouter()

# Simple in-memory cache for insights
INSIGHTS_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes


class TelemetryInsightRequest(BaseModel):
    """Request model for telemetry AI insights."""
    metric_name: str
    metric_key: str
    unit: str
    data: List[Dict[str, Any]]  # Time-series data: [{"timestamp": "...", "gpu_0": value, ...}]
    gpu_ids: List[int]
    precalculated_statistics: Optional[Dict[str, Any]] = None  # Pre-calculated stats from full dataset


class TelemetryInsightResponse(BaseModel):
    """Response model for telemetry AI insights."""
    metric_name: str
    insights: str
    statistics: Dict[str, Any]
    patterns: Dict[str, Any]
    cached: bool = False


def calculate_statistics(data: List[Dict[str, Any]], gpu_ids: List[int], metric_key: str) -> Dict[str, Any]:
    """Calculate comprehensive statistics for the metric data."""
    stats = {}
    
    for gpu_id in gpu_ids:
        gpu_key = f"gpu_{gpu_id}"
        # Look for the data with metric key appended (e.g., gpu_0_util, gpu_0_temp)
        data_key = f"gpu_{gpu_id}_{metric_key}"
        values = []
        
        for point in data:
            # Try with metric key first, fall back to without for backward compatibility
            value = point.get(data_key) or point.get(gpu_key)
            if value is not None:
                try:
                    values.append(float(value))
                except (ValueError, TypeError):
                    continue
        
        if not values:
            stats[gpu_key] = {
                "min": 0,
                "max": 0,
                "avg": 0,
                "stddev": 0,
                "count": 0
            }
            continue
        
        stats[gpu_key] = {
            "min": min(values),
            "max": max(values),
            "avg": statistics.mean(values),
            "stddev": statistics.stdev(values) if len(values) > 1 else 0,
            "median": statistics.median(values),
            "p95": sorted(values)[int(len(values) * 0.95)] if len(values) > 1 else values[0],
            "p99": sorted(values)[int(len(values) * 0.99)] if len(values) > 1 else values[0],
            "count": len(values)
        }
    
    # Calculate overall statistics
    all_values = []
    for gpu_id in gpu_ids:
        gpu_key = f"gpu_{gpu_id}"
        data_key = f"gpu_{gpu_id}_{metric_key}"
        for point in data:
            # Try with metric key first, fall back to without for backward compatibility
            value = point.get(data_key) or point.get(gpu_key)
            if value is not None:
                try:
                    all_values.append(float(value))
                except (ValueError, TypeError):
                    continue
    
    if all_values:
        stats["overall"] = {
            "min": min(all_values),
            "max": max(all_values),
            "avg": statistics.mean(all_values),
            "stddev": statistics.stdev(all_values) if len(all_values) > 1 else 0,
            "median": statistics.median(all_values),
            "p95": sorted(all_values)[int(len(all_values) * 0.95)] if len(all_values) > 1 else all_values[0],
            "p99": sorted(all_values)[int(len(all_values) * 0.99)] if len(all_values) > 1 else all_values[0],
            "count": len(all_values)
        }
    
    return stats


def detect_patterns(data: List[Dict[str, Any]], gpu_ids: List[int], stats: Dict[str, Any], metric_key: str, unit: str) -> Dict[str, Any]:
    """Detect patterns and anomalies in the metric data."""
    patterns = {
        "trend": "stable",
        "anomalies": [],
        "spikes": [],
        "drops": [],
        "pattern_description": ""
    }
    
    overall_stats = stats.get("overall", {})
    if not overall_stats:
        return patterns
    
    avg = overall_stats.get("avg", 0)
    stddev = overall_stats.get("stddev", 0)
    max_val = overall_stats.get("max", 0)
    min_val = overall_stats.get("min", 0)
    
    # Detect trend
    if len(data) > 5:
        # Compare first half vs second half
        half = len(data) // 2
        first_half_values = []
        second_half_values = []
        
        for gpu_id in gpu_ids:
            gpu_key = f"gpu_{gpu_id}"
            data_key = f"gpu_{gpu_id}_{metric_key}"
            for i, point in enumerate(data):
                value = point.get(data_key) or point.get(gpu_key)
                if value is not None:
                    try:
                        val = float(value)
                        if i < half:
                            first_half_values.append(val)
                        else:
                            second_half_values.append(val)
                    except (ValueError, TypeError):
                        continue
        
        if first_half_values and second_half_values:
            first_avg = statistics.mean(first_half_values)
            second_avg = statistics.mean(second_half_values)
            change_pct = ((second_avg - first_avg) / first_avg * 100) if first_avg > 0 else 0
            
            if change_pct > 10:
                patterns["trend"] = "increasing"
            elif change_pct < -10:
                patterns["trend"] = "decreasing"
    
    # Detect anomalies (values > 3 standard deviations from mean)
    threshold = avg + (3 * stddev)
    low_threshold = avg - (3 * stddev) if avg - (3 * stddev) > 0 else 0
    
    for point in data:
        for gpu_id in gpu_ids:
            gpu_key = f"gpu_{gpu_id}"
            data_key = f"gpu_{gpu_id}_{metric_key}"
            value = point.get(data_key) or point.get(gpu_key)
            if value is not None:
                try:
                    val = float(value)
                    if val > threshold:
                        patterns["spikes"].append({
                            "gpu": gpu_id,
                            "value": val,
                            "timestamp": point.get("timestamp", "unknown")
                        })
                    elif val < low_threshold:
                        patterns["drops"].append({
                            "gpu": gpu_id,
                            "value": val,
                            "timestamp": point.get("timestamp", "unknown")
                        })
                except (ValueError, TypeError):
                    continue
    
    # Generate pattern description
    if patterns["trend"] == "increasing":
        patterns["pattern_description"] = f"Metric shows an increasing trend over the time period"
    elif patterns["trend"] == "decreasing":
        patterns["pattern_description"] = f"Metric shows a decreasing trend over the time period"
    else:
        if stddev < avg * 0.1:  # Low variance
            patterns["pattern_description"] = f"Metric is stable with minimal variation (avg: {avg:.2f} {unit})"
        else:
            patterns["pattern_description"] = f"Metric shows moderate variation (avg: {avg:.2f} ± {stddev:.2f} {unit})"
    
    if len(patterns["spikes"]) > 0:
        patterns["anomalies"].append(f"Detected {len(patterns['spikes'])} spike(s) above normal range")
    if len(patterns["drops"]) > 0:
        patterns["anomalies"].append(f"Detected {len(patterns['drops'])} drop(s) below normal range")
    
    return patterns


def generate_cache_key(metric_name: str, metric_key: str, data_summary: str) -> str:
    """Generate a cache key for the insights."""
    key_str = f"{metric_name}:{metric_key}:{data_summary}"
    return hashlib.md5(key_str.encode()).hexdigest()


def get_data_summary(data: List[Dict[str, Any]], stats: Dict[str, Any]) -> str:
    """Generate a summary fingerprint of the data for caching."""
    # Use overall stats as fingerprint
    overall = stats.get("overall", {})
    return f"{overall.get('min', 0):.2f}:{overall.get('max', 0):.2f}:{overall.get('avg', 0):.2f}:{len(data)}"


def get_llm_engine() -> LLMRecommendationEngine:
    """Dependency to get LLM engine instance."""
    api_key = os.getenv("OPENAI_API_KEY")
    return LLMRecommendationEngine(api_key=api_key)


@router.post("/ai-insights", response_model=TelemetryInsightResponse)
async def generate_telemetry_insights(
    request: TelemetryInsightRequest,
    llm_engine: LLMRecommendationEngine = Depends(get_llm_engine)
) -> TelemetryInsightResponse:
    """
    Generate AI-powered insights for telemetry metrics.
    
    Analyzes GPU telemetry data and provides:
    - Current status assessment
    - Anomaly detection
    - Performance recommendations
    - Health warnings
    """
    try:
        # Use pre-calculated statistics if provided (more accurate for large datasets)
        # Otherwise calculate from sampled data
        if request.precalculated_statistics:
            logger.info(f"✅ Using pre-calculated statistics for {request.metric_name}")
            logger.info(f"Pre-calc stats overall: {request.precalculated_statistics.get('overall', {})}")
            stats = request.precalculated_statistics
        else:
            logger.info(f"⚠️ No pre-calculated statistics, calculating from {len(request.data)} data points for {request.metric_name}")
            stats = calculate_statistics(request.data, request.gpu_ids, request.metric_key)
            logger.info(f"Calculated stats overall: {stats.get('overall', {})}")
        
        # Detect patterns (uses sampled data for trend analysis)
        patterns = detect_patterns(request.data, request.gpu_ids, stats, request.metric_key, request.unit)
        
        # Check cache
        data_summary = get_data_summary(request.data, stats)
        cache_key = generate_cache_key(request.metric_name, request.metric_key, data_summary)
        
        current_time = time.time()
        if cache_key in INSIGHTS_CACHE:
            cached_entry = INSIGHTS_CACHE[cache_key]
            if current_time - cached_entry["timestamp"] < CACHE_TTL_SECONDS:
                logger.info(f"Returning cached insights for {request.metric_name}")
                return TelemetryInsightResponse(
                    metric_name=request.metric_name,
                    insights=cached_entry["insights"],
                    statistics=stats,
                    patterns=patterns,
                    cached=True
                )
        
        # Generate insights using LLM
        logger.info(f"Generating new insights for {request.metric_name}")
        insights = await llm_engine.generate_telemetry_insights(
            metric_name=request.metric_name,
            metric_key=request.metric_key,
            unit=request.unit,
            statistics=stats,
            patterns=patterns,
            gpu_count=len(request.gpu_ids)
        )
        
        # Cache the insights
        INSIGHTS_CACHE[cache_key] = {
            "insights": insights,
            "timestamp": current_time
        }
        
        # Clean up old cache entries
        keys_to_remove = []
        for key, entry in INSIGHTS_CACHE.items():
            if current_time - entry["timestamp"] > CACHE_TTL_SECONDS:
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del INSIGHTS_CACHE[key]
        
        return TelemetryInsightResponse(
            metric_name=request.metric_name,
            insights=insights,
            statistics=stats,
            patterns=patterns,
            cached=False
        )
        
    except Exception as e:
        logger.error(f"Error generating telemetry insights: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate insights: {str(e)}"
        )

