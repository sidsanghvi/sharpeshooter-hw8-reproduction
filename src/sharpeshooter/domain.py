from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ActorContext:
    """Trusted context created by CLI or key authentication, never request JSON."""
    operator_id: str
    agent_id: str | None = None
    role: str | None = None

    @classmethod
    def operator(cls, operator_id: str):
        return cls(operator_id)


@dataclass(frozen=True)
class Operator:
    operator_id: str
    display_name: str
    created_at: str


@dataclass(frozen=True)
class Policy:
    policy_id: str
    operator_id: str
    effective_at: str
    oos_limit_per_family: int
    review_separation: str
    claim_ttl_seconds: int


@dataclass(frozen=True)
class IssuedKey:
    agent_id: str
    plaintext_key: str


@dataclass(frozen=True)
class Idea:
    idea_id: str
    family_id: str
    operator_id: str
    author_agent_id: str
    title: str
    hypothesis: str
    rationale: str
    created_at: str
    current_stage: str


@dataclass(frozen=True)
class SimilarityWarning:
    related_idea_id: str
    similarity_score: float


@dataclass(frozen=True)
class Registration:
    idea: Idea
    warnings: tuple[SimilarityWarning, ...]


@dataclass(frozen=True)
class Claim:
    claim_id: str
    idea_id: str
    queue: str
    agent_id: str
    claimed_at: str
    expires_at: str
    token: str | None = None


# Shared schemas at both transport boundaries. Extra fields (including actor IDs
# and credentials) are rejected, never copied into validation error details.
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from .config import IDENTIFIER_PATTERN

Identifier = Annotated[str, Field(pattern="^" + IDENTIFIER_PATTERN + "$")]
Stage = Literal["proposed", "approved", "claimed(builder)", "tested", "claimed(review)", "reviewed", "receipted", "verdict"]
Nonblank = Annotated[str, Field(min_length=1, pattern=r"\S")]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchInput(ToolInput):
    query: str
    stages: list[Stage] | None = None
    family_id: Identifier | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20

    @model_validator(mode="after")
    def require_query_or_filter(self):
        if not self.query.strip() and not self.stages and self.family_id is None:
            raise ValueError("A query or filter is required")
        return self


class SourceInput(ToolInput):
    uri: Nonblank
    label: Nonblank
    accessed_on: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class WriteInput(ToolInput):
    # UUID accepts its wire string while all other inputs retain strict types.
    idempotency_key: Annotated[UUID, Field(strict=False)]


class RegisterInput(WriteInput):
    title: Nonblank
    hypothesis: Nonblank
    rationale: Nonblank
    sources: Annotated[list[SourceInput], Field(min_length=1)]
    parent_idea_id: Identifier | None = None


class ClaimInput(WriteInput):
    queue: Literal["build", "review"]
    idea_id: Identifier | None = None
    lease_seconds: int | None = None


class StrategySpec(ToolInput):
    name: JsonValue
    universe: JsonValue
    signal: JsonValue
    entry_rule: JsonValue
    exit_rule: JsonValue
    position_sizing: JsonValue
    rebalance: JsonValue
    parameters: JsonValue


class SubmitTestInput(WriteInput):
    idea_id: Identifier
    claim_token: Nonblank
    split: Literal["is", "oos"]
    strategy_spec: StrategySpec
    confirm_oos: bool = False


class SubmitReviewInput(WriteInput):
    idea_id: Identifier
    run_id: Identifier
    claim_token: Nonblank
    assessment: Nonblank
    concerns: list[str]
    recommendation: Literal["accept", "revise", "reject"]


class GetResultInput(ToolInput):
    idea_id: Identifier | None = None
    receipt_id: Identifier | None = None

    @model_validator(mode="after")
    def exactly_one_identifier(self):
        if (self.idea_id is None) == (self.receipt_id is None):
            raise ValueError("Exactly one identifier is required")
        return self


TOOL_INPUTS = {
    "search": SearchInput, "register": RegisterInput, "claim": ClaimInput,
    "submit_test": SubmitTestInput, "submit_review": SubmitReviewInput,
    "get_result": GetResultInput,
}


class IdeaSummary(BaseModel):
    idea_id: str
    family_id: str
    title: str
    hypothesis: str
    sources: list[SourceInput]
    current_stage: Stage
    author_agent_id: str
    operator_id: str
    similarity_score: float
    latest_result: dict | None = None
    review_summary: dict | None = None
    receipt_id: str | None = None


class SearchResponse(BaseModel):
    ok: Literal[True] = True
    normalized_query: str
    ideas: list[IdeaSummary]


class RegisterResponse(BaseModel):
    ok: Literal[True] = True
    idea_id: str
    family_id: str
    stage: Literal["proposed"] = "proposed"
    warnings: list[dict]
    created_at: str


class ClaimResponse(BaseModel):
    ok: Literal[True] = True
    claim_id: str
    claim_token: str
    idea_id: str
    queue: Literal["build", "review"]
    prior_stage: Stage
    current_stage: Stage
    claimed_at: str
    expires_at: str
    job_context: dict


class TestResponse(BaseModel):
    ok: Literal[True] = True
    run_id: str
    version_id: str
    strategy_hash: str
    split: Literal["is", "oos"]
    request_state: Literal["succeeded"]
    synthetic_metrics: bool
    metrics: dict[str, int | float]
    checks: dict[str, str | int | bool]
    dataset_version: str
    dataset_split_hash: str
    oos_trial_number: int | None
    budget_used: int
    budget_limit: int


class ReviewResponse(BaseModel):
    ok: Literal[True] = True
    review_id: str
    idea_id: str
    run_id: str
    reviewer_agent_id: str
    stage: Literal["reviewed"] = "reviewed"
    created_at: str


class GetResultResponse(BaseModel):
    ok: Literal[True] = True
    ready: Literal[True] = True
    stage: Stage
    receipt: dict
    integrity_hash: str
