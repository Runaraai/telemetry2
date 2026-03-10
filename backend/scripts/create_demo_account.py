"""Script to create the demo account with historical data."""

import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from telemetry.models import Base, User
from telemetry.auth import get_password_hash
from telemetry.config import get_settings


async def create_demo_account():
    """Create demo account with email madhur@allyin.ai and password madhur."""
    settings = get_settings()
    
    # Create database engine
    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )
    
    # Create session
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        # Check if user already exists
        stmt = select(User).where(User.email == "madhur@allyin.ai")
        result = await session.execute(stmt)
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            print(f"Demo account already exists: madhur@allyin.ai")
            print(f"User ID: {existing_user.user_id}")
            return
        
        # Create new user
        hashed_password = get_password_hash("madhur")
        new_user = User(
            email="madhur@allyin.ai",
            hashed_password=hashed_password,
            is_active=True,
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        
        print(f"✅ Demo account created successfully!")
        print(f"   Email: madhur@allyin.ai")
        print(f"   Password: madhur")
        print(f"   User ID: {new_user.user_id}")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_demo_account())



