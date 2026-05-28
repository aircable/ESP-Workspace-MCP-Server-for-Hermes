"""SSE transport with Bearer token authentication."""
import logging
from functools import wraps
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


def _mask_token(token: str, show: int = 4) -> str:
    if not token:
        return ""
    if len(token) <= show:
        return "*" * len(token)
    return f"***{token[-show:]}"


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces Bearer token authentication."""
    
    def __init__(self, app, api_token: str, exempt_paths: Optional[list] = None):
        super().__init__(app)
        self.api_token = api_token
        self.exempt_paths = exempt_paths or ["/health"]
    
    async def dispatch(self, request: Request, call_next):
        # Allow health check without auth
        if request.url.path in self.exempt_paths:
            logger.debug("Auth: exempt path %s", request.url.path)
            return await call_next(request)
        
        # Check Authorization header
        auth = request.headers.get("Authorization", "")
        provided_token = None
        if auth.startswith("Bearer "):
            provided_token = auth[7:]

        # Debug logging (masked tokens only)
        logger.debug(
            "Auth check: path=%s method=%s auth_header=%s provided=%s expected=%s",
            request.url.path,
            request.method,
            auth[:7] + "..." if auth else "",
            _mask_token(provided_token),
            _mask_token(self.api_token),
        )

        if not provided_token or provided_token != self.api_token:
            logger.warning(
                "Unauthorized access attempt on %s: provided=%s expected=%s",
                request.url.path,
                _mask_token(provided_token),
                _mask_token(self.api_token),
            )
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized: invalid or missing Bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return await call_next(request)


def require_token(api_token: str):
    """Decorator for requiring Bearer token on a specific endpoint."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        return wrapper
    return decorator
