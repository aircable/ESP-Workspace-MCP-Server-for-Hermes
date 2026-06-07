"""ESP-Workspace MCP Server Entry Point.

Usage:
    python run_server.py                          # Default: SSE mode, port 8765
    python run_server.py --stdio                   # Stdio mode
    python run_server.py --port 9000               # Custom port
    python run_server.py --env-file /path/to/.env  # Custom env file

Example:
    python run_server.py --host 0.0.0.0 --port 8765

Environment variables (or .env):
    MCP_API_TOKEN       - Bearer token for authentication (required)
    MCP_HOST            - Bind address (default: 0.0.0.0)
    MCP_PORT            - Listen port (default: 8765)
    MCP_ALLOWED_ROOTS   - Comma-separated allowed filesystem roots
    MCP_WISH_PRODUCT    - Default WISH_PRODUCT value for ESP-IDF builds
    MCP_EIM_PATH        - Path to eim executable (default: eim)
    MCP_LOG_LEVEL       - Logging level (default: INFO)
"""
import argparse
import logging
import sys

from esp_workspace_mcp.config import load_settings
from esp_workspace_mcp.server import create_server


def main():
    parser = argparse.ArgumentParser(description="ESP-Workspace MCP Server")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode (default: SSE)")
    parser.add_argument("--host", type=str, help="Bind address")
    parser.add_argument("--port", type=int, help="Listen port")
    parser.add_argument("--env-file", type=str, default=".env", help="Path to .env file")
    args = parser.parse_args()

    # Load settings
    settings = load_settings(env_file=args.env_file)

    # Override with CLI args
    host = args.host or settings.MCP_HOST
    port = args.port or settings.MCP_PORT

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, settings.MCP_LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger(__name__)

    # Create MCP server
    mcp = create_server(settings)

    if args.stdio:
        logger.info("Starting ESP-Workspace MCP server on stdio")
        mcp.run()
    else:
        import uvicorn
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.routing import Route
        from starlette.responses import JSONResponse, Response
        from starlette.types import Receive, Scope, Send

        from mcp.server.sse import SseServerTransport

        # Create SSE transport
        sse = SseServerTransport("/messages")

        # --- Auth helper: read Bearer token from ASGI scope headers ---
        def check_auth(scope: Scope) -> bool:
            """Return True if auth is valid or not configured. False otherwise."""
            if not settings.MCP_API_TOKEN:
                return True
            for name, value in scope.get("headers", []):
                if name == b"authorization":
                    token = value.decode("latin-1")
                    if token.startswith("Bearer ") and token[7:] == settings.MCP_API_TOKEN:
                        return True
                    return False
            return False

        def send_401(send: Send) -> None:
            """Send a bare ASGI 401 response."""
            response = Response(
                b'{"error":"Unauthorized"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": "Bearer"},
            )

            async def _send_401():
                await response({"type": "http", "method": "GET", "headers": [], "path": "/sse"}, lambda: None, send)

            return _send_401

        # --- Raw ASGI handler for /sse ---
        # This bypasses Starlette's request_response wrapper which would try to
        # send a Response after connect_sse() has already sent the HTTP response
        # via EventSourceResponse. The double http.response.start causes:
        #   AssertionError in starlette/middleware/base.py body_stream()
        async def sse_asgi_handler(scope: Scope, receive: Receive, send: Send):
            """Raw ASGI handler for /sse — GET establishes SSE, POST handles StreamableHTTP."""
            if scope["type"] != "http":
                return

            method = scope.get("method", "GET")
            path = scope.get("path", "")

            # Auth check (inline, no middleware)
            if not check_auth(scope):
                logger.warning("Unauthorized access attempt on %s", path)
                resp = Response(
                    b'{"error":"Unauthorized: invalid or missing Bearer token"}',
                    status_code=401,
                    media_type="application/json",
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await resp(scope, receive, send)
                return

            if method == "GET":
                # SSE connection — EventSourceResponse sends the full HTTP response.
                # After connect_sse() exits, the response is complete. Do NOT return
                # a Starlette Response object — that would cause double http.response.start.
                async with sse.connect_sse(scope, receive, send) as streams:
                    await mcp._mcp_server.run(
                        streams[0], streams[1],
                        mcp._mcp_server.create_initialization_options(),
                    )
                # Response already sent by EventSourceResponse. Nothing more to do.
                return

            elif method == "POST":
                # StreamableHTTP POST to /sse
                request = Request(scope, receive)
                body = await request.body()
                session_id_param = request.query_params.get("session_id")

                if session_id_param:
                    new_scope = dict(scope)
                    new_scope["query_string"] = f"session_id={session_id_param}".encode("ascii")
                    async def buffered_receive():
                        return {"type": "http.request", "body": body, "more_body": False}
                    try:
                        await sse.handle_post_message(new_scope, buffered_receive, send)
                    except Exception as exc:
                        logger.warning("Error handling POST /sse: %s: %s", type(exc).__name__, exc)
                else:
                    resp = Response(
                        "session_id query parameter is required",
                        status_code=400,
                    )
                    await resp(scope, receive, send)
            else:
                resp = Response(status_code=405)
                await resp(scope, receive, send)

        # --- Raw ASGI handler for /messages ---
        async def messages_asgi_handler(scope: Scope, receive: Receive, send: Send):
            """Handle POST /messages — standard MCP SSE message endpoint."""
            try:
                await sse.handle_post_message(scope, receive, send)
            except Exception as exc:
                # ClosedResourceError: client disconnected, session expired
                if type(exc).__name__ == "ClosedResourceError":
                    logger.info("POST /messages: session already closed (client disconnected)")
                    resp = Response(
                        b'{"error":"SSE session closed (client disconnected)"}',
                        status_code=410,
                        media_type="application/json",
                    )
                    await resp(scope, receive, send)
                    return
                logger.warning("Error handling POST /messages: %s: %s", type(exc).__name__, exc)

        # --- Health check via Starlette (no special handling needed) ---
        async def health(request):
            return JSONResponse({"status": "ok", "server": "esp-workspace-mcp"})

        # Minimal Starlette app for /health only
        app = Starlette(routes=[Route("/health", health)])

        # Top-level ASGI app: route /sse and /messages as raw ASGI,
        # everything else goes through Starlette
        async def asgi_app(scope: Scope, receive: Receive, send: Send):
            if scope["type"] == "http":
                path = scope.get("path", "")
                if path.startswith("/messages"):
                    await messages_asgi_handler(scope, receive, send)
                    return
                if path == "/sse" or path == "/sse/":
                    await sse_asgi_handler(scope, receive, send)
                    return
            await app(scope, receive, send)

        # Check if sse module has connect_sse
        logger.info(f"SseServerTransport has connect_sse: {hasattr(sse, 'connect_sse')}")

        # Log auth status
        if settings.MCP_API_TOKEN:
            token = settings.MCP_API_TOKEN
            masked = f"***{token[-4:]}" if len(token) >= 4 else "*" * len(token)
            logger.info("Bearer token authentication enabled (token=%s)", masked)
        else:
            logger.warning("WARNING: No MCP_API_TOKEN set — server is unauthenticated!")

        # Suppress noisy uvicorn access logs (GET /sse, POST /messages)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

        logger.info(f"Starting ESP-Workspace MCP server on http://{host}:{port}/sse")
        uvicorn.run(
            asgi_app,
            host=host,
            port=port,
            log_level=settings.MCP_LOG_LEVEL.lower(),
            access_log=False,
        )


if __name__ == "__main__":
    main()
