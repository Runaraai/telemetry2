class LLMRecommendationEngine:
    """
    Lightweight, offline-friendly insights generator.
    
    Persona: senior GPU performance engineer. Tone: concise, action-oriented, no hype.
    This avoids external LLM dependencies by crafting rule-based summaries from stats + patterns.
    """

    def __init__(self, *args, **kwargs):
        # No external dependencies required.
        pass

    def _format_number(self, value, unit=""):
        if value is None:
            return "N/A"
        if isinstance(value, (int, float)):
            return f"{value:.2f}{unit}"
        return str(value)

    def _build_overview(self, metric_name: str, unit: str, statistics: dict, patterns: dict, gpu_count: int) -> str:
        overall = statistics.get("overall") or {}
        trend = patterns.get("trend", "stable")
        avg = overall.get("avg")
        p95 = overall.get("p95")
        max_val = overall.get("max")
        desc = [
            f"- Metric: **{metric_name}** across **{gpu_count} GPU(s)**.",
            f"- Trend: **{trend}**.",
            f"- Avg: **{self._format_number(avg, f' {unit}') if avg is not None else 'N/A'}**, P95: **{self._format_number(p95, f' {unit}') if p95 is not None else 'N/A'}**, Max: **{self._format_number(max_val, f' {unit}') if max_val is not None else 'N/A'}**.",
        ]
        anomalies = patterns.get("anomalies") or []
        if anomalies:
            desc.append(f"- Anomalies: {', '.join(anomalies)}.")
        if patterns.get("pattern_description"):
            desc.append(f"- Pattern: {patterns['pattern_description']}.")
        return "\n".join(desc)

    def _build_actions(self, metric_key: str, statistics: dict, patterns: dict) -> str:
        actions = []
        overall = statistics.get("overall") or {}
        avg = overall.get("avg")
        max_val = overall.get("max")
        trend = patterns.get("trend", "stable")

        def add(txt):
            actions.append(f"- {txt}")

        if metric_key in {"temp", "slowdown_temp"} and max_val and max_val > 80:
            add("Temperature is high; check airflow, fan curves, and consider reducing power limit or workload intensity.")
        if metric_key in {"power", "power_draw"} and trend == "increasing":
            add("Power draw is rising; verify workload changes and ensure limits/thermal headroom are appropriate.")
        if metric_key in {"util", "sm_util"} and avg is not None and avg < 40:
            add("Utilization is low; check input pipeline, batching, or model parallelism efficiency.")
        if metric_key in {"mem_util", "hbm_util"} and max_val and max_val > 90:
            add("Memory pressure is high; consider smaller batch, tensor parallel tweaks, or gradient checkpointing.")
        if metric_key in {"encoder_util", "decoder_util"} and max_val and max_val > 80:
            add("Video engines are heavily used; monitor encode/decode latency and ensure bitrate/resolution are right-sized.")
        if not actions:
            add("No critical issues detected. Keep monitoring for drift or anomalies.")
        return "\n".join(actions)

    async def generate_telemetry_insights(
        self,
        metric_name: str,
        metric_key: str,
        unit: str,
        statistics: dict,
        patterns: dict,
        gpu_count: int,
    ) -> str:
        """
        Returns markdown with overview and action items.
        """
        overview = self._build_overview(metric_name, unit, statistics, patterns, gpu_count)
        actions = self._build_actions(metric_key, statistics, patterns)

        return (
            "## Summary\n"
            f"{overview}\n\n"
            "## Recommended Actions\n"
            f"{actions}"
        )

    def recommend(self, *args, **kwargs):
        # Backwards compatibility for any legacy calls.
        return {"recommendation": "use generate_telemetry_insights for structured output"}
