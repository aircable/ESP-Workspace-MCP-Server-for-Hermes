"""SSE transport with Bearer token authentication."""
import logging
from typing import Optional

from starlette.types import ASGIApp, Scope, Receive, Send, Message
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


def _mask_token(token: str, show: int = 4) -> str:
    if not token:
        return ""
    if len(token) <= show:
        return "*" * len(token)
    return f"***{token[-show:]}"


class BearerAuthMiddleware:
    """Pure ASGI middleware that enforces Bearer token authentication.

    Unlike BaseHTTPMiddleware, this works correctly with raw ASGI handlers
    (like MCP SSE handle_post_message) that emit http.response.start +
    http.response.body directly instead of returning Starlette Response objects.

    BaseHTTPMiddleware.body_stream() asserts message["type"] == "http.response.body"
    which breaks when the inner app sends http.response.start directly.
    See: https://github.com/modelcontextprotocol/python-sdk/issues/883
    """

    def __init__(self, app: ASGIApp, api_token: str, exempt_paths: Optional[list] = None):
        self.app = app
        self.api_token = api_token
        self.exempt_paths = exempt_paths or ["/health"]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Non-HTTP scopes (lifespan, websocket) pass through
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Exempt paths bypass auth entirely
        if path in self.exempt_paths:
            logger.debug("Auth: exempt path %s", path)
            await self.app(scope, receive, send)
            return

        # Extract Authorization header from the raw ASGI scope
        # This avoids creating a Request object (which consumes the receive channel)
        # and works with both Starlette responses and raw ASGI handlers
        auth_header = None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth_header = value.decode("latin-1")
                break

        provided_token = None
        if auth_header and auth_header.startswith("Bearer "):
            provided_token = auth_header[7:]

        # Debug logging (masked tokens only)
        logger.debug(
            "Auth check: path=%s method=%s auth_header=%s provided=%s expected=%s",
            path,
            scope.get("method", "?"),
            (auth_header[:7] + "...") if auth_header else "",
            _mask_token(provided_token),
            _mask_token(self.api_token),
        )

        if not provided_token or provided_token != self.api_token:
            logger.warning(
                "Unauthorized access attempt on %s: provided=%s expected=%s",
                path,
                _mask_token(provided_token),
                _mask_token(self.api_token),
            )
            # Send 401 directly via ASGI — no BaseHTTPMiddleware involvement
            response = JSONResponse(
                status_code=401,
                content={"error": "Unauthorized: invalid or missing Bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        # Token valid — pass through to inner app
        await self.app(scope, receive, send)


def require_token(api_token: str):
    """Decorator for requiring Bearer token on a specific endpoint."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        return wrapper
    return decorator
