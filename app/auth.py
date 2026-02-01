import os
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from functools import wraps

SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "default-secret-key-change-in-production")
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "changeme")

SESSION_COOKIE_NAME = "yufka_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

serializer = URLSafeTimedSerializer(SECRET_KEY)


def create_session_token(username: str) -> str:
    """Create a signed session token."""
    return serializer.dumps({"username": username})


def verify_session_token(token: str) -> dict | None:
    """Verify and decode session token."""
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None


def verify_credentials(username: str, password: str) -> bool:
    """Verify username and password."""
    return username == AUTH_USERNAME and password == AUTH_PASSWORD


def get_current_user(request: Request) -> dict | None:
    """Get current user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return verify_session_token(token)


def require_auth(func):
    """Decorator to require authentication for a route."""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return await func(request, *args, **kwargs)
    return wrapper


def create_login_response(username: str, redirect_url: str = "/") -> RedirectResponse:
    """Create response with session cookie after successful login."""
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    token = create_session_token(username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


def create_logout_response(redirect_url: str = "/login") -> RedirectResponse:
    """Create response that clears session cookie."""
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response
