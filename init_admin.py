#!/usr/bin/env python3
"""
Initialize first admin user in database.
Usage: python3 init_admin.py
"""
import asyncio
import os
from app.db import async_session
from app.models import Admin
from app.config import settings
from sqlalchemy import select


async def init_admin():
    """Create first admin if doesn't exist."""
    async with async_session() as session:
        # Check if admin exists
        result = await session.execute(select(Admin).where(Admin.username == settings.admin_username))
        admin = result.scalar_one_or_none()

        if admin:
            print(f"✓ Admin '{settings.admin_username}' already exists")
            return

        # Create first admin
        admin = Admin(
            username=settings.admin_username,
            password_hash=settings.admin_password_hash,
            totp_enabled=False,
            totp_counter=0,
        )
        session.add(admin)
        await session.commit()
        print(f"✓ Created admin '{settings.admin_username}'")
        print(f"  Password: Read from ADMIN_PASSWORD_HASH in .env")
        print(f"  TOTP: Disabled (enable via /admin/2fa/setup)")


if __name__ == "__main__":
    asyncio.run(init_admin())
