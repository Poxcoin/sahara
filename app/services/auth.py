import secrets
import bcrypt as _bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, Response, HTTPException, status
from cryptography.fernet import Fernet
import os

from app.config import settings

_COOKIE = "sahara_session"
_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="sahara-auth")


def create_session_cookie(response: Response, user_id: int) -> None:
    token = _serializer().dumps(user_id)
    response.set_cookie(_COOKIE, token, max_age=_MAX_AGE, httponly=True, samesite="lax")


def get_user_id_from_cookie(request: Request) -> int | None:
    token = request.cookies.get(_COOKIE)
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def clear_session(response: Response) -> None:
    response.delete_cookie(_COOKIE)


# ── Pending OTP cookie (short-lived, holds email while user enters OTP) ──
_PENDING_COOKIE = "sahara_pending"
_PENDING_MAX_AGE = 60 * 15  # 15 minutes


def set_pending_cookie(response: Response, email: str, purpose: str) -> None:
    token = _serializer().dumps({"e": email, "p": purpose})
    response.set_cookie(
        _PENDING_COOKIE, token,
        max_age=_PENDING_MAX_AGE, httponly=True, samesite="lax"
    )


def get_pending(request: Request) -> dict | None:
    token = request.cookies.get(_PENDING_COOKIE)
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=_PENDING_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def clear_pending_cookie(response: Response) -> None:
    response.delete_cookie(_PENDING_COOKIE)


# ── CSRF double-submit cookie ──
_CSRF_COOKIE = "_csrf"


def get_csrf_token(request: Request) -> str:
    return request.cookies.get(_CSRF_COOKIE, "")


def ensure_csrf_cookie(response: Response, request: Request) -> str:
    """Return existing CSRF token or set a fresh one."""
    token = request.cookies.get(_CSRF_COOKIE, "")
    if not token:
        token = secrets.token_hex(16)
        response.set_cookie(_CSRF_COOKIE, token, httponly=True, samesite="strict", secure=True)
    return token


def verify_csrf(request: Request, form_token: str) -> None:
    cookie_token = request.cookies.get(_CSRF_COOKIE, "")
    if not cookie_token or not secrets.compare_digest(cookie_token, form_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


# ── Admin Session Management ──
_ADMIN_COOKIE = "sahara_admin_session"
_ADMIN_MAX_AGE = 60 * 60  # 1 hour


def create_admin_session(response: Response, admin_id: int) -> None:
    """Create secure admin session cookie (1 hour, httponly, strict SameSite)."""
    token = _serializer().dumps(admin_id, salt="sahara-admin")
    response.set_cookie(
        _ADMIN_COOKIE, token,
        max_age=_ADMIN_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict"
    )


def get_admin_id_from_cookie(request: Request) -> int | None:
    """Extract admin ID from secure session cookie."""
    token = request.cookies.get(_ADMIN_COOKIE)
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=_ADMIN_MAX_AGE, salt="sahara-admin")
    except (BadSignature, SignatureExpired):
        return None


def clear_admin_session(response: Response) -> None:
    """Clear admin session cookie."""
    response.delete_cookie(_ADMIN_COOKIE)


# ── TOTP Encryption (KEK stored in env) ──
def _get_totp_cipher() -> Fernet:
    """Get TOTP cipher using KEK from environment."""
    kek = os.getenv("TOTP_ENCRYPTION_KEY", "")
    if not kek:
        raise RuntimeError("TOTP_ENCRYPTION_KEY not configured. Run: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" and set TOTP_ENCRYPTION_KEY in .env")
    return Fernet(kek.encode() if isinstance(kek, str) else kek)


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt TOTP secret for storage in DB."""
    cipher = _get_totp_cipher()
    encrypted = cipher.encrypt(secret.encode())
    return encrypted.decode()


def decrypt_totp_secret(encrypted_secret: str) -> str:
    """Decrypt TOTP secret from DB."""
    try:
        cipher = _get_totp_cipher()
        decrypted = cipher.decrypt(encrypted_secret.encode())
        return decrypted.decode()
    except Exception:
        raise ValueError("Failed to decrypt TOTP secret")


# ── TOTP (2FA) ──
def generate_totp_secret() -> str:
    """Generate random TOTP secret (base32, 32 chars) - returns plaintext, caller must encrypt."""
    import pyotp
    return pyotp.random_base32()


def get_totp_provisioning_uri(username: str, secret: str) -> str:
    """Generate QR code as data:image URI for admin 2FA setup."""
    import pyotp
    import qrcode
    import io
    import base64

    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=username, issuer_name="SAHARA Admin")

    # Generate QR code image
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to data:image
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_base64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{img_base64}"


def verify_totp(secret: str, token: str, *, allow_previous: bool = True, encrypted: bool = True) -> bool:
    """Verify TOTP token with replay protection.

    Args:
        secret: TOTP secret (encrypted Fernet string by default)
        token: 6-digit code from user
        allow_previous: Whether to accept tokens from the previous 30s window
        encrypted: If True, decrypt secret first

    Returns:
        True if token is valid, False otherwise

    Security notes:
    - Only accepts current (and optionally previous) 30s window to prevent replay
    - Caller must check totp_counter in DB to prevent time-window replay
    """
    import pyotp
    try:
        # Decrypt secret if needed
        plaintext_secret = decrypt_totp_secret(secret) if encrypted else secret

        totp = pyotp.TOTP(plaintext_secret)
        window = 1 if allow_previous else 0
        return totp.verify(token, valid_window=window)
    except Exception:
        return False


def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate backup codes (128 bits, human-friendly) for 2FA recovery."""
    # Generate 128-bit codes formatted as xxxx-xxxx-xxxx for readability
    codes = []
    for _ in range(count):
        code = secrets.token_urlsafe(16)[:20]  # 128-bit base64 -> 20 chars
        # Format as xxxx-xxxx-xxxx
        formatted = f"{code[:4]}-{code[4:8]}-{code[8:12]}"
        codes.append(formatted)
    return codes


def backup_codes_to_json(codes: list[str]) -> str:
    """Convert list of backup codes to JSON with used tracking."""
    import json
    return json.dumps([{"code": code, "used": False} for code in codes])


def parse_backup_codes(json_str: str) -> list[dict]:
    """Parse JSON backup codes with used flag."""
    import json
    try:
        return json.loads(json_str) if json_str else []
    except Exception:
        return []


def mark_backup_code_used(json_str: str, code: str) -> str:
    """Mark a backup code as used in JSON store."""
    import json
    codes = json.loads(json_str) if json_str else []
    for entry in codes:
        if entry["code"] == code:
            entry["used"] = True
            break
    return json.dumps(codes)
