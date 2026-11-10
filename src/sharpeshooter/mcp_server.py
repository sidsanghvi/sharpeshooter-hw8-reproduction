"""The exact six-tool MCP catalog, backed by the shared ledger boundary."""
from contextvars import ContextVar
import json
from typing import Annotated, Literal
from uuid import UUID

from mcp.server import MCPServer
from mcp.types import (
    CallToolResult, TextContent, JSONRPCRequest, JSONRPCNotification,
    client_request_adapter, client_notification_adapter, jsonrpc_message_adapter,
)
from pydantic import Field

from .domain import Identifier, Nonblank, SourceInput, Stage, StrategySpec, TOOL_INPUTS
from .errors import DomainError, error_result

# Set by authenticated HTTP middleware, never supplied in tool arguments.
current_actor = ContextVar("sharpeshooter_actor", default=None)


def tool_result(result):
    return CallToolResult(
        is_error=not result["ok"],
        structured_content=result,
        content=[TextContent(type="text", text=json.dumps(result, sort_keys=True, separators=(",", ":")))],
    )


def validate_mcp_envelope(body):
    """Validate wire framing before the SDK can render raw validation inputs.

    Preserve the original bytes for dispatch. Choosing request vs notification
    explicitly prevents a malformed request ID from falling through the SDK's
    permissive envelope union as a notification.
    """
    message = json.loads(body)
    if not isinstance(message, dict):
        raise ValueError("MCP requires an object envelope")
    if "method" in message:
        if "id" in message:
            JSONRPCRequest.model_validate(message, strict=True)
            client_request_adapter.validate_python(message, strict=True, by_name=False)
        else:
            JSONRPCNotification.model_validate(message, strict=True)
            client_notification_adapter.validate_python(message, strict=True, by_name=False)
    else:
        # Legacy clients may post responses to server-originated requests.
        jsonrpc_message_adapter.validate_python(message, strict=True, by_name=False)


def create_mcp_server(ledger_getter):
    async def validate_before_sdk(ctx, call_next):
        # The SDK normally renders Pydantic failures with raw input values.
        # Validate first and return our redacted, transport-neutral error instead.
        if ctx.method == "tools/call":
            actor = current_actor.get()
            if actor is None:
                return tool_result(error_result(DomainError("AUTH_REQUIRED", "Bearer authentication is required")))
            params = ctx.params or {}
            name = params.get("name")
            if name in TOOL_INPUTS:
                ledger = ledger_getter()
                try:
                    ledger.validate_tool_input(actor, name, params.get("arguments", {}))
                except DomainError:
                    return tool_result(ledger.reject_tool_input(actor, name))
            else:
                return tool_result(ledger_getter().execute_tool(actor, name, {}))
        return await call_next(ctx)

    server = MCPServer(name="SharpeShooter", version="0.1.0", middleware=[validate_before_sdk])

    def invoke(name, arguments):
        return tool_result(ledger_getter().execute_tool(current_actor.get(), name, arguments))

    # Async handlers stay on the synchronous service's SQLite-owning event loop.
    @server.tool()
    async def search(query: str, stages: list[Stage] | None = None,
                     family_id: Identifier | None = None,
                     limit: Annotated[int, Field(ge=1, le=100)] = 20) -> CallToolResult:
        """Search shared research summaries with deterministic token ranking."""
        return invoke("search", {"query": query, "stages": stages, "family_id": family_id, "limit": limit})

    @server.tool()
    async def register(title: Nonblank, hypothesis: Nonblank, rationale: Nonblank,
                       sources: Annotated[list[SourceInput], Field(min_length=1)], idempotency_key: UUID,
                       parent_idea_id: Identifier | None = None) -> CallToolResult:
        """Register a Scout idea and sources; duplicate warnings do not merge budgets."""
        return invoke("register", {"title": title, "hypothesis": hypothesis, "rationale": rationale,
                                   "sources": sources, "idempotency_key": idempotency_key, "parent_idea_id": parent_idea_id})

    @server.tool()
    async def claim(queue: Literal["build", "review"], idempotency_key: UUID,
                    idea_id: Identifier | None = None, lease_seconds: int | None = None) -> CallToolResult:
        """Claim eligible work with a one-time lease secret; requested TTL clamps to 60–900 seconds."""
        return invoke("claim", {"queue": queue, "idempotency_key": idempotency_key,
                                "idea_id": idea_id, "lease_seconds": lease_seconds})

    @server.tool()
    async def submit_test(idea_id: Identifier, claim_token: Nonblank, split: Literal["is", "oos"],
                          strategy_spec: StrategySpec, idempotency_key: UUID,
                          confirm_oos: bool = False) -> CallToolResult:
        """Run a synthetic IS/OOS evaluation; OOS requires confirmation and a frozen strategy."""
        return invoke("submit_test", {"idea_id": idea_id, "claim_token": claim_token, "split": split,
                                      "strategy_spec": strategy_spec, "idempotency_key": idempotency_key, "confirm_oos": confirm_oos})

    @server.tool()
    async def submit_review(idea_id: Identifier, run_id: Identifier, claim_token: Nonblank,
                            assessment: Nonblank, concerns: list[str],
                            recommendation: Literal["accept", "revise", "reject"],
                            idempotency_key: UUID) -> CallToolResult:
        """Submit an independent Skeptic review of a successful OOS run."""
        return invoke("submit_review", {"idea_id": idea_id, "run_id": run_id, "claim_token": claim_token,
                                        "assessment": assessment, "concerns": concerns, "recommendation": recommendation,
                                        "idempotency_key": idempotency_key})

    @server.tool()
    async def get_result(idea_id: Identifier | None = None, receipt_id: Identifier | None = None) -> CallToolResult:
        """Issue or inspect a shared independently reviewed receipt by idea ID or receipt ID."""
        return invoke("get_result", {"idea_id": idea_id, "receipt_id": receipt_id})

    return server
