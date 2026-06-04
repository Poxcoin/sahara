import secrets
import bcrypt as _bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, Response, HTTPException, status

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
