"""Pure construction and verification for tamper-evident result receipts."""
from dataclasses import dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class Receipt:
    payload: dict[str, Any]
    integrity_hash: str


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    computed_hash: str
    stored_hash: str


def canonical_receipt_bytes(payload: dict[str, Any]) -> bytes:
    if not isinstance(payload, dict) or "integrity_hash" in payload:
        raise ValueError("Receipt payload must be an object without integrity_hash")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def build_receipt(*, receipt_id: str, issued_at: str, idea: dict, strategy: dict,
                  evaluation: dict, review: dict, provenance: dict) -> Receipt:
    payload = {
        "schema_version": "1.0", "receipt_id": receipt_id, "issued_at": issued_at,
        "idea": idea, "strategy": strategy, "evaluation": evaluation,
        "review": review, "provenance": provenance,
    }
    canonical = canonical_receipt_bytes(payload)
    stored = json.loads(canonical)
    return Receipt(stored, "sha256:" + hashlib.sha256(canonical).hexdigest())


def verify_receipt(payload: dict[str, Any], integrity_hash: str) -> VerificationResult:
    try:
        computed = "sha256:" + hashlib.sha256(canonical_receipt_bytes(payload)).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError):
        computed = ""
    valid = isinstance(integrity_hash, str) and computed == integrity_hash
    return VerificationResult(valid, computed, integrity_hash if isinstance(integrity_hash, str) else "")
