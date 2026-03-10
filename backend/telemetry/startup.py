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
    """Ensure demo account exists with email demo@allyin.ai and password demo."""
    try:
        async with async_session() as session:
            stmt = select(User).where(User.email == "demo@allyin.ai")
            result = await session.execute(stmt)
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                logger.info("Demo account already exists: demo@allyin.ai")
                return
            
            # Create new user
            # Hash password - this may fail on first attempt due to bcrypt initialization
            # so we'll catch and retry
            try:
                hashed_password = get_password_hash("demo")
            except ValueError as e:
                if "password cannot be longer than 72 bytes" in str(e):
                    # This is a bcrypt initialization bug - wait and retry once
                    import asyncio
                    await asyncio.sleep(0.5)
                    hashed_password = get_password_hash("demo")
                else:
                    raise
            new_user = User(
                email="demo@allyin.ai",
                hashed_password=hashed_password,
                is_active=True,
            )
            session.add(new_user)
            await session.commit()
            logger.info("Demo account created: demo@allyin.ai")
    except Exception as e:
        logger.warning(f"Failed to create demo account (will retry on next request): {e}")
        # Don't fail startup if demo account creation fails - it can be created later

