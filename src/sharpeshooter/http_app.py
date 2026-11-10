"""Single synchronous ledger service with MCP and the matching HTTP fallback."""
from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request
from mcp.server.transport_security import (
    DEFAULT_MAX_REQUEST_BODY_SIZE,
    RequestBodyLimitMiddleware,
    TransportSecuritySettings,
)
from starlette.responses import JSONResponse

from .auth import authenticate_bearer
from .config import Config
from .errors import DomainError, error_result, http_status
from .ledger import Ledger
from .mcp_server import create_mcp_server, current_actor, validate_mcp_envelope


MCP_TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "ledger:8000"],
    allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
)


class BearerBoundary:
    """Authenticate both transports before body parsing or SDK dispatch."""

    def __init__(self, app, *, ledger_getter):
        self.app = app
        self.ledger_getter = ledger_getter
        # Keep the SDK's existing body-size cap ahead of our buffering as well.
        self.mcp_app = RequestBodyLimitMiddleware(self._mcp_request, DEFAULT_MAX_REQUEST_BODY_SIZE)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        protected = path.startswith("/v1/tools/") or path == "/mcp" or path.startswith("/mcp/")
        if scope["type"] != "http" or not protected:
            return await self.app(scope, receive, send)
        authorization = next((value.decode("latin1") for name, value in scope["headers"] if name.lower() == b"authorization"), None)
        try:
            actor = authenticate_bearer(self.ledger_getter(), authorization)
        except DomainError as exc:
            result = error_result(exc)
            return await JSONResponse(result, status_code=http_status(result))(scope, receive, send)
        token = current_actor.set(actor)
        try:
            if scope["method"] == "POST" and (path == "/mcp" or path.startswith("/mcp/")):
                await self.mcp_app(scope, receive, send)
            else:
                await self.app(scope, receive, send)
        finally:
            current_actor.reset(token)

    async def _mcp_request(self, scope, receive, send):
        body = await Request(scope, receive).body()
        try:
            validate_mcp_envelope(body)
        except (ValueError, TypeError, RecursionError):
            # Neither exception text nor untrusted envelope fields enter the
            # response/audit. Authentication has already supplied this actor.
            try:
                with self.ledger_getter().action("transport.mcp", current_actor.get()):
                    raise DomainError("INVALID_INPUT", "Malformed MCP request envelope")
            except DomainError as exc:
                result = error_result(exc)
            return await JSONResponse(result, status_code=http_status(result))(scope, receive, send)
        pending = True

        async def replay():
            nonlocal pending
            if pending:
                pending = False
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(*, ledger=None):
    owned = ledger is None
    active_ledger = ledger

    def get_ledger():
        if active_ledger is None:
            raise RuntimeError("Service lifespan is not running")
        return active_ledger

    mcp = create_mcp_server(get_ledger)
    mcp_app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=MCP_TRANSPORT_SECURITY,
    )

    @asynccontextmanager
    async def lifespan(app):
        nonlocal active_ledger
        if owned:
            active_ledger = Ledger(Config.from_env().db_path)
            active_ledger.initialize()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            if owned:
                active_ledger.close()
                active_ledger = None

    app = FastAPI(title="SharpeShooter", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BearerBoundary, ledger_getter=get_ledger)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v1/tools/{tool_name}")
    async def tool(tool_name: str, request: Request):
        actor = current_actor.get()
        try:
            arguments = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            result = get_ledger().reject_tool_input(actor, tool_name)
        else:
            result = get_ledger().execute_tool(actor, tool_name, arguments)
        return JSONResponse(result, status_code=http_status(result))

    app.mount("/", mcp_app)
    return app


# Importing the ASGI application creates neither a database nor credentials.
app = create_app()
