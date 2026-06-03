import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OTPCode

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5  # max wrong attempts per code


def _generate_code() -> str:
    return str(secrets.randbelow(900000) + 100000)  # 100000–999999


async def create_otp(session: AsyncSession, email: str, purpose: str) -> str:
    """Invalidate previous codes for this email+purpose, create a new one, return plain code."""
    # Mark all previous unused codes as used
    await session.execute(
        update(OTPCode)
        .where(OTPCode.email == email, OTPCode.purpose == purpose, OTPCode.used == False)
        .values(used=True)
    )
    code = _generate_code()
    expires = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
    otp = OTPCode(email=email, code=code, purpose=purpose, expires_at=expires)
    session.add(otp)
    await session.commit()
    return code


async def verify_otp(session: AsyncSession, email: str, code: str, purpose: str) -> bool:
    """Returns True and marks code used if valid; False otherwise."""
    result = await session.execute(
        select(OTPCode)
        .where(
            OTPCode.email == email,
            OTPCode.purpose == purpose,
            OTPCode.used == False,
            OTPCode.expires_at > datetime.utcnow(),
        )
        .order_by(OTPCode.created_at.desc())
        .limit(1)
    )
    otp = result.scalar_one_or_none()
    if not otp:
        return False
    if not secrets.compare_digest(otp.code, code.strip()):
        return False
    otp.used = True
    await session.commit()
    return True
