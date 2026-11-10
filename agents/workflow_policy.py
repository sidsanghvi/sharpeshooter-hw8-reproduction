from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping


@dataclass(frozen=True)
class BuilderWorkflowPolicy:
    version: str
    claim_lease_seconds: int

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("workflow policy version must be nonempty")
        if type(self.claim_lease_seconds) is not int or self.claim_lease_seconds <= 0:
            raise ValueError("claim lease seconds must be a positive integer")


BUILDER_WORKFLOW_POLICIES: Mapping[str, BuilderWorkflowPolicy] = MappingProxyType(
    {
        "1": BuilderWorkflowPolicy(version="1", claim_lease_seconds=300),
        "2": BuilderWorkflowPolicy(version="2", claim_lease_seconds=600),
    }
)
ACTIVE_BUILDER_WORKFLOW_POLICY_VERSION: Literal["1", "2"] = "2"


def current_builder_workflow_policy() -> BuilderWorkflowPolicy:
    return BUILDER_WORKFLOW_POLICIES[ACTIVE_BUILDER_WORKFLOW_POLICY_VERSION]
