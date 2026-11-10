"""Strict, bounded, canonical research-task intake for external orchestrators."""
from __future__ import annotations

from datetime import date
import hashlib
import ipaddress
import json
import math
import re
import unicodedata
from typing import Any, Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_TASK_BYTES = 65_536
MAX_SPEC_BYTES = 6_144
SLUG_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
PARAMETER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
HOST_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
INVALID_PERCENT_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")
URI_PATH_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9._~!$&'()*+,;=:@/\-]|%[0-9A-Fa-f]{2})*$"
)
URI_QUERY_FRAGMENT_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9._~!$&'()*+,;=:@/?\-]|%[0-9A-Fa-f]{2})*$"
)

_DENIED_PARAMETER_KEYS = frozenset(
    """approval approved approval_status approval_digest approved_digest approved_task_digest
    task_digest verdict verdict_policy confirm_oos oos oos_confirmation oos_budget oos_limit
    oos_trial budget split actor_id agent_id author author_agent_id reviewer reviewer_id
    reviewer_agent_id operator operator_id identity identities role review review_content
    review_assessment review_recommendation assessment runtime agent_runtime executable command cwd
    env environment dataset dataset_version is_dataset oos_dataset is_root oos_root db database
    db_path capture capture_path path project_root state_dir journal town_url run_id request_id
    message_id evidence evidence_policy token access_token refresh_token secret credential
    credentials authorization""".split()
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"ss_[0-9a-f]{12}_[A-Za-z0-9_-]{32,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class ResearchTaskError(ValueError):
    """Fixed, redacted validation failure."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


StrictText = Annotated[str, Field(strict=True, min_length=1)]
Slug = Annotated[str, Field(strict=True, pattern=SLUG_PATTERN)]


def _valid_text(value: str, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and unicodedata.normalize("NFC", value) == value
        and not any(unicodedata.category(character).startswith("C") for character in value)
        and not any(pattern.search(value) for pattern in _CREDENTIAL_PATTERNS)
    )


def _valid_https_uri(value: str) -> bool:
    if (
        not _valid_text(value, 2_048)
        or any(character.isspace() for character in value)
        or "\\" in value
        or INVALID_PERCENT_PATTERN.search(value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or URI_PATH_PATTERN.fullmatch(parsed.path) is None
        or URI_QUERY_FRAGMENT_PATTERN.fullmatch(parsed.query) is None
        or URI_QUERY_FRAGMENT_PATTERN.fullmatch(parsed.fragment) is None
    ):
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    return (
        len(ascii_hostname) <= 253
        and not ascii_hostname.endswith(".")
        and all(HOST_LABEL_PATTERN.fullmatch(label) for label in ascii_hostname.split("."))
    )


class ResearchSourceV1(_StrictModel):
    uri: StrictText
    label: StrictText
    accessed_on: StrictText

    @model_validator(mode="after")
    def validate_source(self):
        if (
            not _valid_https_uri(self.uri)
            or not _valid_text(self.label, 128)
        ):
            raise ValueError("invalid source")
        try:
            if date.fromisoformat(self.accessed_on).isoformat() != self.accessed_on:
                raise ValueError
        except ValueError:
            raise ValueError("invalid source date") from None
        return self


class ResearchIdeaV1(_StrictModel):
    title: StrictText
    hypothesis: StrictText
    rationale: StrictText
    sources: Annotated[list[ResearchSourceV1], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def validate_idea(self):
        if not (
            _valid_text(self.title, 160)
            and _valid_text(self.hypothesis, 1_000)
            and _valid_text(self.rationale, 2_000)
        ):
            raise ValueError("invalid idea")
        return self


def _validate_parameter(value: Any, *, depth: int) -> None:
    if depth > 4:
        raise ValueError("parameter depth exceeded")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > 1e12:
            raise ValueError("numeric parameter out of bounds")
        return
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > 1e12:
            raise ValueError("numeric parameter out of bounds")
        return
    if isinstance(value, str):
        if not _valid_text(value, 256):
            raise ValueError("invalid parameter string")
        return
    if isinstance(value, list):
        if len(value) > 32:
            raise ValueError("parameter array too large")
        for item in value:
            _validate_parameter(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 32:
            raise ValueError("parameter object too large")
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or PARAMETER_KEY_PATTERN.fullmatch(key) is None
                or key in _DENIED_PARAMETER_KEYS
                or not _valid_text(key, 64)
            ):
                raise ValueError("invalid parameter key")
            _validate_parameter(item, depth=depth + 1)
        return
    raise ValueError("invalid parameter value")


class StrictStrategySpec(_StrictModel):
    name: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    universe: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    signal: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    entry_rule: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    exit_rule: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    position_sizing: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    rebalance: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    parameters: dict[str, Any]

    @model_validator(mode="after")
    def validate_spec(self):
        for field in (
            self.name,
            self.universe,
            self.signal,
            self.entry_rule,
            self.exit_rule,
            self.position_sizing,
            self.rebalance,
        ):
            if not _valid_text(field, 512):
                raise ValueError("invalid strategy text")
        _validate_parameter(self.parameters, depth=0)
        if len(_canonical(self.model_dump(mode="json"))) > MAX_SPEC_BYTES:
            raise ValueError("strategy specification too large")
        return self


class ResearchCandidateV1(_StrictModel):
    candidate_id: Slug
    strategy_spec: StrictStrategySpec


class ResearchTaskV1(_StrictModel):
    schema_version: Literal["sharpeshooter.research-task.v1"]
    client_task_id: Slug
    idea: ResearchIdeaV1
    candidates: Annotated[list[ResearchCandidateV1], Field(min_length=2, max_length=8)]
    selected_candidate_id: Slug

    @model_validator(mode="after")
    def validate_candidates(self):
        identifiers = [candidate.candidate_id for candidate in self.candidates]
        specifications = [
            _canonical(candidate.strategy_spec.model_dump(mode="json"))
            for candidate in self.candidates
        ]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("candidate identifiers must be unique")
        if len(set(specifications)) != len(specifications):
            raise ValueError("candidate specifications must be unique")
        if identifiers.count(self.selected_candidate_id) != 1:
            raise ValueError("selected candidate is missing")
        return self


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ResearchTaskError("Research task is invalid.")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ResearchTaskError("Research task is invalid.")


def parse_research_task(raw: bytes) -> ResearchTaskV1:
    """Parse untrusted bytes into the strict v1 task without echoing input."""
    try:
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_TASK_BYTES or raw.startswith(b"\xef\xbb\xbf"):
            raise ResearchTaskError("Research task is invalid.")
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
        )
        _scan_tree(value, depth=1)
        task = ResearchTaskV1.model_validate(value, strict=True)
        if len(canonical_task_bytes(task)) > MAX_TASK_BYTES:
            raise ResearchTaskError("Research task is invalid.")
        return task
    except ResearchTaskError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ResearchTaskError("Research task is invalid.") from None


def _scan_tree(value: Any, *, depth: int) -> None:
    if depth > 8:
        raise ResearchTaskError("Research task is invalid.")
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value or any(
            unicodedata.category(character).startswith("C") for character in value
        ):
            raise ResearchTaskError("Research task is invalid.")
        return
    if isinstance(value, list):
        for item in value:
            _scan_tree(item, depth=depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            _scan_tree(key, depth=depth + 1)
            _scan_tree(item, depth=depth + 1)


def canonical_task_bytes(task: ResearchTaskV1) -> bytes:
    try:
        canonical = _canonical(task.model_dump(mode="json"))
    except (AttributeError, TypeError, ValueError, UnicodeError):
        raise ResearchTaskError("Research task is invalid.") from None
    if len(canonical) > MAX_TASK_BYTES:
        raise ResearchTaskError("Research task is invalid.")
    return canonical


def research_task_digest(task: ResearchTaskV1) -> str:
    return "sha256:" + hashlib.sha256(canonical_task_bytes(task)).hexdigest()
