"""Application startup utilities for telemetry."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_password_hash
from .config import get_settings
from .db import async_engine, async_session
from .migrations import run_bootstrap
from .models import User

logger = logging.getLogger(__name__)


async def init_telemetry() -> None:
    """Initialize telemetry schema and extensions."""

    settings = get_settings()
    logger.info(
        "Initializing telemetry schema '%s' with retention %s days",
        settings.db_schema,
        settings.metrics_retention_days,
    )
    await run_bootstrap(
        async_engine,
        schema=settings.db_schema,
        retention_days=settings.metrics_retention_days,
    )
    
    # Create demo account if it doesn't exist
    await _ensure_demo_account()


async def _ensure_demo_account() -> None:
    """Ensure demo account exists (configurable via DEMO_ACCOUNT_EMAIL env var)."""
    import os
    demo_email = os.getenv("DEMO_ACCOUNT_EMAIL", "demo@omniference.com")
    demo_password = os.getenv("DEMO_ACCOUNT_PASSWORD", "demo")
    try:
        async with async_session() as session:
            stmt = select(User).where(User.email == demo_email)
            result = await session.execute(stmt)
            existing_user = result.scalar_one_or_none()

            if existing_user:
                logger.info("Demo account already exists: %s", demo_email)
                return

            # Create new user
            # Hash password - this may fail on first attempt due to bcrypt initialization
            # so we'll catch and retry
            try:
                hashed_password = get_password_hash(demo_password)
            except ValueError as e:
                if "password cannot be longer than 72 bytes" in str(e):
                    # This is a bcrypt initialization bug - wait and retry once
                    import asyncio
                    await asyncio.sleep(0.5)
                    hashed_password = get_password_hash(demo_password)
                else:
                    raise
            new_user = User(
                email=demo_email,
                hashed_password=hashed_password,
                is_active=True,
            )
            session.add(new_user)
            await session.commit()
            logger.info("Demo account created: %s", demo_email)
    except Exception as e:
        logger.warning("Failed to create demo account (will retry on next request): %s", e)
        # Don't fail startup if demo account creation fails - it can be created later

