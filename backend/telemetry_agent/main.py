"""Entry point for the telemetry agent service."""

from __future__ import annotations

import asyncio
import logging
import signal

from .backend_client import BackendClient
from .config import AgentConfig
from .prometheus_client import PrometheusClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("telemetry_agent")


async def run_agent(stop_event: asyncio.Event) -> None:
    config = AgentConfig.from_env()
    logger.info(
        "Telemetry agent starting (run_id=%s, backend=%s, prometheus=%s, poll=%ss)",
        config.run_id,
        config.backend_url,
        config.prometheus_url,
        config.poll_interval.total_seconds(),
    )

    async with PrometheusClient(config.prometheus_url, timeout=config.request_timeout) as prom_client, BackendClient(
        config.backend_url, config.run_id, timeout=config.request_timeout
    ) as backend_client:
        while not stop_event.is_set():
            try:
                samples = await prom_client.fetch_samples()
                if samples:
                    await backend_client.send_metrics(samples)
                    logger.debug("Published %s samples", len(samples))
                else:
                    logger.debug("No samples returned from Prometheus")
            except Exception:  # pragma: no cover - defensive
                logger.exception("Telemetry agent iteration failed")

            try:
                await asyncio.wait_for(stop_event.wait(), config.poll_interval.total_seconds())
            except asyncio.TimeoutError:
                continue

    logger.info("Telemetry agent stopped")


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _signal_handler(signame: str) -> None:
        logger.info("Received signal %s; shutting down telemetry agent", signame)
        stop_event.set()

    for signame in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal, signame), _signal_handler, signame)
        except (ValueError, AttributeError, RuntimeError):  # pragma: no cover - platform specific
            continue


async def _main() -> None:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    await run_agent(stop_event)


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:  # pragma: no cover - interactive use
        logger.info("Telemetry agent interrupted by user")


if __name__ == "__main__":
    main()


