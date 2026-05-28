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
from esp_workspace_mcp.auth import BearerAuthMiddleware


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
        from starlette.types import ASGIApp, Receive, Scope, Send
        
        from mcp.server.sse import SseServerTransport
        
        # Create SSE transport
        sse = SseServerTransport("/messages")
        
        async def handle_sse_get(request: Request):
            """Handle GET /sse — establish SSE connection."""
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await mcp._mcp_server.run(
                    streams[0], streams[1],
                    mcp._mcp_server.create_initialization_options(),
                )
            return Response()
        
        async def sse_post_handler(scope: Scope, receive: Receive, send: Send):
            """Handle POST /sse — StreamableHTTP POST to /sse path."""
            request = Request(scope, receive)
            session_id_param = request.query_params.get("session_id")
            body = await request.body()
            
            if session_id_param:
                new_scope = dict(scope)
                new_scope["query_string"] = f"session_id={session_id_param}".encode("ascii")
            else:
                new_scope = scope
            
            if session_id_param:
                async def buffered_receive():
                    return {"type": "http.request", "body": body, "more_body": False}
                await sse.handle_post_message(new_scope, buffered_receive, send)
            else:
                response = Response(
                    "session_id query parameter is required",
                    status_code=400,
                )
                await response(scope, receive, send)
        
        async def combined_sse_handler(request: Request):
            """Combined handler for /sse — dispatches by HTTP method."""
            if request.method == "GET":
                return await handle_sse_get(request)
            elif request.method == "POST":
                return await sse_post_handler(request.scope, request.receive, request._send)
            else:
                return Response(status_code=405)
        
        async def messages_handler(scope: Scope, receive: Receive, send: Send):
            """Handle POST /messages — standard MCP SSE message endpoint."""
            await sse.handle_post_message(scope, receive, send)
        
        async def health(request):
            return JSONResponse({"status": "ok", "server": "esp-workspace-mcp"})
        
        # Build the ASGI app that routes /messages outside auth middleware
        # We need /messages to bypass auth (it has session_id validation built in)
        # while /sse needs auth validation.
        # Strategy: put auth at Starlette level with exempt_paths including /messages
        
        # Custom ASGI wrapper for /messages to avoid double auth
        def messages_asgi_wrapper(app: ASGIApp) -> ASGIApp:
            """Simple pass-through — auth middleware will be configured to exempt /messages."""
            return app
        
        # Build Starlette app — use a single app with Route-based dispatch
        # to avoid Mount vs Route priority conflicts
        app = Starlette(
            routes=[
                Route("/health", health),
                Route("/sse", combined_sse_handler),
                Route("/sse/", combined_sse_handler),
                # /messages is handled as a raw ASGI app to avoid routing issues
            ],
        )
        
        # Mount /messages as a sub-app with raw ASGI
        # We wrap it so it bypasses the auth middleware
        messages_app = sse.handle_post_message
        
        # Add auth middleware - exempt /messages (session-based security is sufficient)
        # and /health
        if settings.MCP_API_TOKEN:
            app.add_middleware(
                BearerAuthMiddleware,
                api_token=settings.MCP_API_TOKEN,
                exempt_paths=["/health", "/messages", "/messages/"],
            )
            # Log masked token for debugging (never log full token)
            token = settings.MCP_API_TOKEN or ""
            if len(token) >= 4:
                masked = f"***{token[-4:]}"
            else:
                masked = "*" * len(token)
            logger.info("Bearer token authentication enabled (token=%s)", masked)
        else:
            logger.warning("WARNING: No MCP_API_TOKEN set — server is unauthenticated!")
        
        # Now mount /messages using the raw ASGI app
        # We need to do this at the ASGI level to ensure it works with the middleware
        original_app = app
        
        async def asgi_app_with_messages(scope: Scope, receive: Receive, send: Send):
            """Top-level ASGI app that routes /messages before Starlette."""
            if scope["type"] == "http" and scope["path"].startswith("/messages"):
                await messages_app(scope, receive, send)
            else:
                await original_app(scope, receive, send)
        
        logger.info(f"Starting ESP-Workspace MCP server on http://{host}:{port}/sse")
        uvicorn.run(asgi_app_with_messages, host=host, port=port, log_level=settings.MCP_LOG_LEVEL.lower())


if __name__ == "__main__":
    main()
