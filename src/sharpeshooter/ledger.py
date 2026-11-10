"""Synchronous deterministic domain actions; transports must authenticate first."""
from contextlib import contextmanager, nullcontext
from datetime import date, timedelta
from pathlib import Path
import hashlib
import hmac
import json
import re
import secrets
from uuid import UUID, uuid4

from .auth import hash_claim_token, matches_key, new_key
from .config import Config, IDENTIFIER_PATTERN, MAX_CLAIM_TTL_SECONDS, SQLITE_INTEGER_MAX
from .db import Database
from .domain import ActorContext, Claim, Idea, IssuedKey, Operator, Policy, Registration, SimilarityWarning, SystemClock, utc_timestamp
from .errors import DomainError, error_result
from .domain import (TOOL_INPUTS, SearchResponse, IdeaSummary, RegisterResponse,
                     ClaimResponse, TestResponse, ReviewResponse, GetResultResponse)
from .evaluator import DeterministicStubEvaluator, EvaluationRequest, EvaluatorFailure, selected_manifest
from .receipts import build_receipt, canonical_receipt_bytes, verify_receipt
from pydantic import ValidationError

# Deliberately small and committed: similarity is a warning, not equivalence.
STOP_WORDS = frozenset("a an and are as at be by for from in is it of on or that the this to with".split())


def identifier():
    return uuid4().hex


def require(condition, code, message):
    if not condition:
        raise DomainError(code, message)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), "invalid_input", f"{name} must be nonempty text")
    return value.strip()


def valid_identifier(value):
    return isinstance(value, str) and re.fullmatch(IDENTIFIER_PATTERN, value) is not None


def validate_identifier(value, name):
    require(valid_identifier(value), "invalid_input", f"{name} must be 32 lowercase hexadecimal characters")


def audit_identifier(value):
    # Never bind malformed objects or stringify their potentially secret contents.
    return value if valid_identifier(value) else None


class Ledger:
    def __init__(self, path, *, clock=None, evaluator=None, is_root=None, oos_root=None):
        self.db = Database(path)
        self.clock = clock or SystemClock()
        config = Config.from_env()
        self.is_root = Path(is_root) if is_root is not None else config.is_root
        self.oos_root = Path(oos_root) if oos_root is not None else config.oos_root
        self.evaluator = evaluator if evaluator is not None else DeterministicStubEvaluator(is_root=self.is_root, oos_root=self.oos_root)

    def close(self):
        self.db.close()

    def initialize(self):
        self.db.initialize()
        with self.db.transaction():
            if not self.db.connection.execute("SELECT 1 FROM audit_events LIMIT 1").fetchone():
                self._audit("database.initialized", None, {}, utc_timestamp(self.clock.now()))

    def _audit(self, event_type, actor, payload, now, idea_id=None, subject_id=None):
        self.db.connection.execute(
            "INSERT INTO audit_events(event_type,actor_operator_id,actor_agent_id,subject_idea_id,subject_id,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (event_type, audit_identifier(getattr(actor, "operator_id", None)),
             audit_identifier(getattr(actor, "agent_id", None)),
             audit_identifier(idea_id), audit_identifier(subject_id),
             json.dumps(payload, sort_keys=True, separators=(",", ":")), now),
        )

    @contextmanager
    def action(self, event_type, actor, *, idea_id=None, payload=None):
        """Atomic domain write with durable rejection audit and lease housekeeping.

        Later submit actions must call require_live_claim *inside* this context,
        before any writes. A separate validate_claim call is not authorization
        for a subsequent transaction. Payloads must never include credentials.
        """
        failure = None
        payload = {} if payload is None else payload
        with (self.db.transaction() if not self.db.connection.in_transaction else nullcontext(self.db.connection)) as conn:
            now = utc_timestamp(self.clock.now())
            self._expire_claims(now)
            savepoint = "domain_action_" + identifier()
            conn.execute("SAVEPOINT " + savepoint)
            try:
                if idea_id is not None:
                    validate_identifier(idea_id, "idea_id")
                yield conn, now
            except DomainError as exc:
                conn.execute("ROLLBACK TO " + savepoint)
                self._audit(event_type + ".rejected", actor, {"code": exc.code}, now, idea_id)
                failure = exc
            else:
                self._audit(event_type, actor, payload, now, idea_id)
            finally:
                conn.execute("RELEASE " + savepoint)
        if failure:
            raise failure

    def _operator(self, actor):
        require(isinstance(actor, ActorContext) and actor.agent_id is None and actor.role is None,
                "forbidden", "Operator action required")
        validate_identifier(actor.operator_id, "operator_id")
        require(self.db.connection.execute("SELECT 1 FROM operators WHERE operator_id=?", (actor.operator_id,)).fetchone(),
                "forbidden", "Unknown operator")

    def _agent(self, actor, role=None):
        require(isinstance(actor, ActorContext) and actor.agent_id is not None, "forbidden", "Agent action required")
        validate_identifier(actor.operator_id, "operator_id")
        validate_identifier(actor.agent_id, "agent_id")
        row = self.db.connection.execute("SELECT * FROM agent_keys WHERE agent_id=?", (actor.agent_id,)).fetchone()
        require(row and row["revoked_at"] is None and row["operator_id"] == actor.operator_id and row["role"] == actor.role,
                "forbidden", "Invalid agent context")
        require(role is None or actor.role == role, "forbidden", f"{role} role required")

    def create_operator(self, display_name):
        payload = {}
        with self.action("operator.create", None, payload=payload) as (conn, now):
            operator = Operator(identifier(), text(display_name, "display_name"), now)
            conn.execute("INSERT INTO operators VALUES (?,?,?)", (operator.operator_id, operator.display_name, now))
            policy = self._insert_policy(operator.operator_id, now, 2, "distinct_agent", 300)
            payload.update(operator=vars(operator), policy=vars(policy))
        return operator

    def _insert_policy(self, operator_id, now, limit, separation, ttl):
        policy = Policy(identifier(), operator_id, now, limit, separation, ttl)
        self.db.connection.execute("INSERT INTO operator_policy_versions VALUES (?,?,?,?,?,?)", tuple(vars(policy).values()))
        return policy

    def current_policy(self, operator_id):
        validate_identifier(operator_id, "operator_id")
        row = self.db.connection.execute("SELECT * FROM operator_policy_versions WHERE operator_id=? ORDER BY effective_at DESC,rowid DESC LIMIT 1", (operator_id,)).fetchone()
        require(row, "not_found", "Operator policy not found")
        return Policy(**dict(row))

    def configure_policy(self, actor, *, oos_limit_per_family=None, review_separation=None, claim_ttl_seconds=None):
        payload = {}
        with self.action("policy.configure", actor, payload=payload) as (_, now):
            self._operator(actor)
            current = self.current_policy(actor.operator_id)
            limit = current.oos_limit_per_family if oos_limit_per_family is None else oos_limit_per_family
            ttl = current.claim_ttl_seconds if claim_ttl_seconds is None else claim_ttl_seconds
            separation = current.review_separation if review_separation is None else review_separation
            require(type(limit) is int and 0 <= limit <= SQLITE_INTEGER_MAX, "invalid_input", "OOS limit must fit a nonnegative SQLite integer")
            require(type(ttl) is int and 1 <= ttl <= MAX_CLAIM_TTL_SECONDS, "invalid_input", "Claim TTL must be an integer from 1 through 31536000 seconds")
            require(separation in ("distinct_agent", "distinct_operator"), "invalid_input", "Unknown review separation")
            policy = self._insert_policy(actor.operator_id, now, limit, separation, ttl)
            payload.update(vars(policy))
        return policy

    def issue_key(self, actor, role):
        payload = {}
        with self.action("key.issue", actor, payload=payload) as (conn, now):
            self._operator(actor)
            require(role in ("Scout", "Builder", "Skeptic"), "invalid_input", "Unknown agent role")
            plaintext, prefix, salt, hashed = new_key()
            agent_id = identifier()
            conn.execute("INSERT INTO agent_keys VALUES (?,?,?,?,?,?,?,NULL)", (agent_id, actor.operator_id, role, prefix, salt, hashed, now))
            payload.update(agent_id=agent_id, role=role)
        return IssuedKey(agent_id, plaintext)

    def authenticate(self, plaintext_key):
        # Accepted authentication is a read. Rejections are auditable without storing supplied secrets.
        row = None
        if isinstance(plaintext_key, str):
            parts = plaintext_key.split("_")
            if len(parts) >= 3 and parts[0] == "ss":
                row = self.db.connection.execute("SELECT * FROM agent_keys WHERE key_prefix=?", (parts[1],)).fetchone()
        if row and row["revoked_at"] is None and matches_key(plaintext_key, row["salt"], row["key_hash"]):
            return ActorContext(row["operator_id"], row["agent_id"], row["role"])
        with self.action("key.authenticate", None):
            raise DomainError("unauthorized", "Invalid or revoked key")

    def revoke_key(self, actor, agent_id):
        with self.action("key.revoke", actor, payload={"agent_id": agent_id}) as (conn, now):
            self._operator(actor)
            validate_identifier(agent_id, "agent_id")
            row = conn.execute("SELECT * FROM agent_keys WHERE agent_id=?", (agent_id,)).fetchone()
            require(row and row["operator_id"] == actor.operator_id, "forbidden", "Key does not belong to operator")
            require(row["revoked_at"] is None, "invalid_state", "Key already revoked")
            conn.execute("UPDATE agent_keys SET revoked_at=? WHERE agent_id=?", (now, agent_id))

    def get_idea(self, idea_id):
        validate_identifier(idea_id, "idea_id")
        row = self.db.connection.execute("SELECT * FROM ideas WHERE idea_id=?", (idea_id,)).fetchone()
        require(row, "not_found", "Idea not found")
        return Idea(**dict(row))

    @staticmethod
    def _tokens(title, hypothesis):
        return set(re.findall(r"[a-z0-9]+", (title + " " + hypothesis).lower())) - STOP_WORDS

    def register(self, actor, *, title, hypothesis, rationale, sources, parent_idea_id=None):
        payload = {}
        with self.action("idea.register", actor, payload=payload) as (conn, now):
            self._agent(actor, "Scout")
            title, hypothesis, rationale = text(title, "title"), text(hypothesis, "hypothesis"), text(rationale, "rationale")
            require(isinstance(sources, (list, tuple)), "invalid_input", "sources must be a list")
            validated = []
            for source in sources:
                require(isinstance(source, dict), "invalid_input", "Source must be an object")
                uri, label, accessed_on = (text(source.get(k), k) for k in ("uri", "label", "accessed_on"))
                try:
                    require(date.fromisoformat(accessed_on).isoformat() == accessed_on, "invalid_input", "Use ISO source date")
                except ValueError:
                    raise DomainError("invalid_input", "Use ISO source date") from None
                validated.append((uri, label, accessed_on))
            idea_id = identifier()
            if parent_idea_id is not None:
                family_id = self.get_idea(parent_idea_id).family_id
            else:
                family_id = identifier()
                conn.execute("INSERT INTO strategy_families VALUES (?,?,?)", (family_id, idea_id, now))
            tokens = self._tokens(title, hypothesis)
            best = None
            for row in conn.execute("SELECT idea_id,title,hypothesis FROM ideas ORDER BY created_at,rowid"):
                other = self._tokens(row["title"], row["hypothesis"])
                score = len(tokens & other) / len(tokens | other) if tokens | other else 0
                if score >= .72 and (best is None or score > best.similarity_score):
                    best = SimilarityWarning(row["idea_id"], score)
            idea = Idea(idea_id, family_id, actor.operator_id, actor.agent_id, title, hypothesis, rationale, now, "proposed")
            conn.execute("INSERT INTO ideas VALUES (?,?,?,?,?,?,?,?,?)", tuple(vars(idea).values()))
            conn.executemany("INSERT INTO sources VALUES (?,?,?,?,?)", [(identifier(), idea_id, *source) for source in validated])
            if parent_idea_id is not None:
                self._link(idea_id, parent_idea_id, "declared_parent", None, now)
            if best:
                self._link(idea_id, best.related_idea_id, "similarity_warning", best.similarity_score, now)
            payload.update(idea_id=idea_id, family_id=family_id, parent_idea_id=parent_idea_id,
                           title=title, hypothesis=hypothesis, rationale=rationale,
                           sources=[dict(zip(("uri", "label", "accessed_on"), source)) for source in validated],
                           warnings=[vars(best)] if best else [])
            result = Registration(idea, (best,) if best else ())
        return result

    def _link(self, child, parent, link_type, score, now):
        self.db.connection.execute("INSERT INTO idea_links VALUES (?,?,?,?,?,?)", (identifier(), child, parent, link_type, score, now))

    def _owned_idea(self, actor, idea_id):
        self._operator(actor)
        idea = self.get_idea(idea_id)
        require(idea.operator_id == actor.operator_id, "forbidden", "Idea does not belong to operator")
        return idea

    def link_family(self, actor, idea_id, parent_idea_id):
        with self.action("idea.link_family", actor, idea_id=idea_id, payload={"parent_idea_id": parent_idea_id}) as (conn, now):
            self._owned_idea(actor, idea_id)
            require(idea_id != parent_idea_id, "invalid_input", "An idea cannot parent itself")
            parent = self.get_idea(parent_idea_id)
            require(not conn.execute("SELECT 1 FROM test_runs WHERE idea_id=? AND split='OOS' LIMIT 1", (idea_id,)).fetchone(),
                    "invalid_state", "Cannot link after first OOS request")
            self._link(idea_id, parent_idea_id, "manual_family", None, now)
            conn.execute("UPDATE ideas SET family_id=? WHERE idea_id=?", (parent.family_id, idea_id))
            result = self.get_idea(idea_id)
        return result

    def approve(self, actor, idea_id, decision, note=""):
        with self.action("idea.approve", actor, idea_id=idea_id, payload={"decision": decision, "note": note}) as (conn, now):
            idea = self._owned_idea(actor, idea_id)
            require(decision in ("approve", "reject"), "invalid_input", "Unknown approval decision")
            require(isinstance(note, str), "invalid_input", "Note must be text")
            require(idea.current_stage == "proposed" and not conn.execute("SELECT 1 FROM approvals WHERE idea_id=?", (idea_id,)).fetchone(),
                    "invalid_state", "Approval already decided")
            conn.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?)", (identifier(), idea_id, actor.operator_id, decision, note, now))
            if decision == "approve":
                conn.execute("UPDATE ideas SET current_stage='approved' WHERE idea_id=?", (idea_id,))
        return self.get_idea(idea_id)

    def _expire_claims(self, now):
        conn = self.db.connection
        for row in conn.execute("SELECT * FROM claims WHERE closed_at IS NULL AND expires_at<=? ORDER BY claimed_at,rowid", (now,)).fetchall():
            conn.execute("UPDATE claims SET closed_at=?,close_reason='expired' WHERE claim_id=?", (now, row["claim_id"]))
            old_stage, new_stage = ("claimed(builder)", "approved") if row["queue"] == "build" else ("claimed(review)", "tested")
            conn.execute("UPDATE ideas SET current_stage=? WHERE idea_id=? AND current_stage=?", (new_stage, row["idea_id"], old_stage))
            self._audit("claim.expired", None, {"claim_id": row["claim_id"], "queue": row["queue"]}, now, row["idea_id"])

    def _eligible(self, actor, idea, queue):
        if queue == "build":
            return actor.operator_id == idea.operator_id
        policy = self.current_policy(idea.operator_id)
        return actor.agent_id != idea.author_agent_id and (policy.review_separation == "distinct_agent" or actor.operator_id != idea.operator_id)

    def claim(self, actor, queue, *, idea_id=None, lease_seconds=None, idempotency_key=None):
        payload = {"queue": queue}
        result = None
        with self.action("claim.acquire", actor, idea_id=idea_id, payload=payload) as (conn, now):
            require(queue in ("build", "review"), "invalid_input", "Unknown queue")
            self._agent(actor, "Builder" if queue == "build" else "Skeptic")
            stage = "approved" if queue == "build" else "tested"
            if idea_id is not None:
                candidate = self.get_idea(idea_id)
                require(candidate.current_stage == stage and self._eligible(actor, candidate, queue), "not_claimable", "Idea is not claimable")
                candidates = [candidate]
            else:
                candidates = [Idea(**dict(row)) for row in conn.execute("SELECT * FROM ideas WHERE current_stage=? ORDER BY created_at,rowid", (stage,))]
            for idea in candidates:
                if not self._eligible(actor, idea, queue):
                    continue
                claim_id = identifier()
                token = self.replay_claim_token(actor, claim_id, idempotency_key) if idempotency_key is not None else secrets.token_urlsafe(32)
                ttl = self.current_policy(idea.operator_id).claim_ttl_seconds
                if idempotency_key is not None:
                    require(lease_seconds is None or type(lease_seconds) is int, "invalid_input", "Lease must be an integer")
                    ttl = 300 if lease_seconds is None else max(60, min(900, lease_seconds))
                try:
                    expires = utc_timestamp(self.clock.now() + timedelta(seconds=ttl))
                except (OverflowError, ValueError):
                    raise DomainError("invalid_input", "Claim expiration exceeds the supported datetime range") from None
                result = Claim(claim_id, idea.idea_id, queue, actor.agent_id, now, expires, token)
                conn.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,NULL,NULL)", (result.claim_id, result.idea_id, queue, actor.agent_id, hash_claim_token(token), now, expires))
                conn.execute("UPDATE ideas SET current_stage=? WHERE idea_id=?", ("claimed(builder)" if queue == "build" else "claimed(review)", idea.idea_id))
                payload.update(claim_id=result.claim_id, idea_id=idea.idea_id,
                               claimed_at=now, expires_at=expires)
                break
        return result

    def require_live_claim(self, actor, idea_id, queue, token, now):
        """Guard for later domain actions, inside an existing action transaction."""
        require(self.db.connection.in_transaction, "invalid_state", "Claim guard requires a write transaction")
        require(queue in ("build", "review"), "invalid_input", "Unknown queue")
        self._agent(actor, "Builder" if queue == "build" else "Skeptic")
        idea = self.get_idea(idea_id)
        require(self._eligible(actor, idea, queue), "forbidden", "Agent is not eligible")
        row = self.db.connection.execute("SELECT * FROM claims WHERE idea_id=? AND queue=? AND agent_id=? AND closed_at IS NULL AND expires_at>?", (idea_id, queue, actor.agent_id, now)).fetchone()
        require(isinstance(token, str) and row and hmac.compare_digest(row["token_hash"], hash_claim_token(token)), "invalid_claim", "A live own claim is required")
        expected = "claimed(builder)" if queue == "build" else "claimed(review)"
        require(idea.current_stage == expected, "invalid_state", "Idea no longer has a live claim")
        return Claim(row["claim_id"], idea_id, queue, actor.agent_id, row["claimed_at"], row["expires_at"])

    def validate_claim(self, actor, idea_id, queue, token):
        with self.action("claim.validate", actor, idea_id=idea_id) as (_, now):
            result = self.require_live_claim(actor, idea_id, queue, token, now)
        return result

    def record_verdict(self, actor, idea_id, decision, note=""):
        with self.action("idea.verdict", actor, idea_id=idea_id, payload={"decision": decision, "note": note}) as (conn, now):
            idea = self._owned_idea(actor, idea_id)
            require(idea.current_stage == "receipted" and conn.execute("SELECT 1 FROM receipts WHERE idea_id=?", (idea_id,)).fetchone(), "invalid_state", "A receipt is required before verdict")
            require(decision in ("accept", "revise", "reject"), "invalid_input", "Unknown verdict")
            require(isinstance(note, str), "invalid_input", "Note must be text")
            conn.execute("INSERT INTO verdicts VALUES (?,?,?,?,?,?)", (identifier(), idea_id, actor.operator_id, decision, note, now))
            conn.execute("UPDATE ideas SET current_stage='verdict' WHERE idea_id=?", (idea_id,))
        return self.get_idea(idea_id)

    def audit_events(self, *, limit=100):
        require(type(limit) is int and 0 < limit <= 10000, "invalid_input", "Audit limit must be between 1 and 10000")
        rows = self.db.connection.execute("SELECT * FROM (SELECT * FROM audit_events ORDER BY event_id DESC LIMIT ?) ORDER BY event_id", (limit,))
        return [dict(row) for row in rows]


    def replay_claim_token(self, actor, claim_id, idempotency_key):
        """Reconstruct a transport lease secret without persisting its plaintext.

        Only authenticated/validated service contexts may use verifier material.
        The key never leaves the service, and the domain-separated message binds
        both the server-generated claim ID and the caller's idempotency UUID.
        """
        from uuid import UUID
        self._agent(actor)
        validate_identifier(claim_id, "claim_id")
        try:
            canonical_key = str(UUID(str(idempotency_key)))
        except (ValueError, TypeError, AttributeError):
            raise DomainError("invalid_input", "Idempotency key must be a UUID") from None
        row = self.db.connection.execute("SELECT key_hash FROM agent_keys WHERE agent_id=?", (actor.agent_id,)).fetchone()
        message = ("SharpeShooter/claim-token/v1:" + claim_id + ":" + canonical_key).encode()
        return hmac.new(bytes.fromhex(row["key_hash"]), message, hashlib.sha256).hexdigest()

    def validate_tool_input(self, actor, tool_name, arguments):
        """Validate without ever echoing raw Pydantic input values."""
        try:
            model = TOOL_INPUTS[tool_name].model_validate(arguments)
            serializable = model.model_dump(mode="json")
            # JSON-compatible includes finite numbers only.
            json.dumps(serializable, allow_nan=False)
            # Issued bearer keys cannot be laundered into stored research text.
            def contains_credential(value):
                if isinstance(value, str):
                    return re.search(r"ss_[0-9a-f]{12}_[A-Za-z0-9_-]{43}", value) is not None
                if isinstance(value, dict):
                    return any(contains_credential(key) or contains_credential(item)
                               for key, item in value.items())
                if isinstance(value, (list, tuple)):
                    return any(contains_credential(item) for item in value)
                return False

            if contains_credential(serializable):
                raise ValueError("Credentials are not permitted in tool arguments")
            return model
        except (ValidationError, ValueError, TypeError):
            raise DomainError("INVALID_INPUT", "Tool arguments do not match the input schema") from None

    @staticmethod
    def _tool_data(request):
        data = request.model_dump(mode="python")
        if isinstance(data.get("idempotency_key"), UUID):
            data["idempotency_key"] = str(data["idempotency_key"])
        return data

    @staticmethod
    def _require_canonical_utf8(data):
        try:
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError):
            raise DomainError("INVALID_INPUT", "Tool arguments do not match the input schema") from None

    @staticmethod
    def _review_idempotency(arguments):
        """Bind schema-invalid review text without persisting or encoding it as UTF-8."""
        if not isinstance(arguments, dict):
            return None, None
        try:
            key = str(UUID(str(arguments.get("idempotency_key"))))
            body = {name: value for name, value in arguments.items() if name != "idempotency_key"}
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False).encode("ascii")
        except (TypeError, ValueError, UnicodeEncodeError):
            return None, None
        return key, hashlib.sha256(encoded).hexdigest()

    def reject_tool_input(self, actor, tool_name):
        # MCP validates before SDK argument parsing, which otherwise echoes inputs.
        event = "tool." + (tool_name if tool_name in TOOL_INPUTS else "unknown")
        try:
            with self.action(event, actor):
                raise DomainError("INVALID_INPUT", "Tool arguments do not match the input schema")
        except DomainError as exc:
            return error_result(exc)

    def execute_tool(self, actor, tool_name, arguments):
        """One application boundary shared by MCP and HTTP.

        The enclosing transaction durably binds both success and domain failure
        responses. action's savepoint rolls back a rejected mutation while its
        redacted audit survives alongside the failure's idempotency record.
        """
        if tool_name == "submit_test":
            return self.submit_test(actor, arguments)
        event = "tool." + (tool_name if tool_name in TOOL_INPUTS else "unknown")
        idem_key = request_hash = stored = None
        audit_payload = {}
        with (self.db.transaction() if not self.db.connection.in_transaction else nullcontext(self.db.connection)) as conn:
            try:
                with self.action(event, actor, payload=audit_payload) as (_, now):
                    self._agent(actor)
                    require(tool_name in TOOL_INPUTS, "NOT_FOUND", "Unknown tool")
                    if tool_name == "submit_review":
                        idem_key, request_hash = self._review_idempotency(arguments)
                    if idem_key is not None:
                        stored = conn.execute("SELECT request_hash,response_json FROM idempotency_keys WHERE agent_id=? AND tool_name=? AND key=?", (actor.agent_id, tool_name, idem_key)).fetchone()
                    if stored:
                        require(hmac.compare_digest(stored["request_hash"], request_hash), "IDEMPOTENCY_CONFLICT", "Idempotency key was used with different arguments")
                        result = json.loads(stored["response_json"])
                        audit_payload["idempotent_replay"] = True
                        if tool_name == "claim" and result["ok"]:
                            result["claim_token"] = self.replay_claim_token(actor, result["claim_id"], idem_key)
                    else:
                        request = self.validate_tool_input(actor, tool_name, arguments)
                        data = self._tool_data(request)
                        validated_key = data.pop("idempotency_key", None)
                        if idem_key is None:
                            idem_key = validated_key
                            request_hash = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                            if idem_key is not None:
                                stored = conn.execute("SELECT request_hash,response_json FROM idempotency_keys WHERE agent_id=? AND tool_name=? AND key=?", (actor.agent_id, tool_name, idem_key)).fetchone()
                                if stored:
                                    require(hmac.compare_digest(stored["request_hash"], request_hash), "IDEMPOTENCY_CONFLICT", "Idempotency key was used with different arguments")
                                    result = json.loads(stored["response_json"])
                                    audit_payload["idempotent_replay"] = True
                                    if tool_name == "claim" and result["ok"]:
                                        result["claim_token"] = self.replay_claim_token(actor, result["claim_id"], idem_key)
                        else:
                            require(validated_key == idem_key, "INVALID_INPUT", "Tool arguments do not match the input schema")
                        if not stored:
                            if tool_name == "register":
                                self._agent(actor, "Scout")
                            elif tool_name == "claim":
                                self._agent(actor, "Builder" if request.queue == "build" else "Skeptic")
                            elif tool_name == "submit_review":
                                self._agent(actor, "Skeptic")
                            self._require_canonical_utf8(data)
                            result = self._execute_tool(actor, tool_name, data, idem_key)
            except DomainError as exc:
                result = error_result(exc)
            if idem_key is not None and request_hash is not None and stored is None:
                # action has already rolled back any rejected projection writes;
                # bind only this safe response and hash in the same transaction.
                persisted = {k: v for k, v in result.items() if k != "claim_token"}
                conn.execute("INSERT INTO idempotency_keys VALUES (?,?,?,?,?,?)", (actor.agent_id, tool_name, idem_key, request_hash, json.dumps(persisted, sort_keys=True, separators=(",", ":")), now))
        return result

    def _test_response_record(self, actor_id, key, request_hash, result, now):
        self.db.connection.execute(
            "INSERT INTO idempotency_keys VALUES (?,?,?,?,?,?)",
            (actor_id, "submit_test", key, request_hash,
             json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), now))

    def _failed_test(self, run, now):
        """Finish once; exceptions and private evaluator metadata never enter history."""
        result = error_result(DomainError("EVALUATOR_FAILED", "Synthetic evaluation failed"))
        self.db.connection.execute(
            "UPDATE test_runs SET request_state='failed',failure_code='EVALUATOR_FAILED',completed_at=?,reservation_expires_at=NULL WHERE run_id=? AND request_state='pending'",
            (now, run["run_id"]))
        self._audit("test.failed", None, {"run_id": run["run_id"], "failure_code": "EVALUATOR_FAILED"}, now, run["idea_id"])
        self._test_response_record(run["request_agent_id"], run["request_key"], run["request_hash"], result, now)
        return result

    def _expire_test_reservations(self, now):
        for row in self.db.connection.execute(
                "SELECT r.*,b.agent_id AS request_agent_id,b.key AS request_key,b.request_hash FROM test_runs r JOIN test_request_bindings b ON b.run_id=r.run_id WHERE r.request_state='pending' AND r.split='OOS' AND r.reservation_expires_at<=?", (now,)).fetchall():
            self._failed_test(row, now)

    def _family_budget(self, idea, now, *, pending=False):
        clause = "(r.request_state='succeeded' OR (r.request_state='pending' AND r.reservation_expires_at>?))" if pending else "r.request_state='succeeded'"
        parameters = (idea.operator_id, idea.family_id, now) if pending else (idea.operator_id, idea.family_id)
        return self.db.connection.execute(
            "SELECT count(*) FROM test_runs r JOIN ideas i ON i.idea_id=r.idea_id WHERE i.operator_id=? AND i.family_id=? AND r.split='OOS' AND " + clause,
            parameters).fetchone()[0]

    def submit_test(self, actor, arguments):
        """Admit/commit, evaluate without a write lock, then finish atomically.

        The pending run binds the idempotency identity during the unlocked phase.
        Only final safe responses enter the immutable idempotency table.
        """
        admitted = None
        idem_key = request_hash = stored = inflight = None
        with self.db.transaction() as conn:
            now = utc_timestamp(self.clock.now())
            self._expire_claims(now)
            self._expire_test_reservations(now)
            audit_payload = {}
            try:
                with self.action("tool.submit_test", actor, payload=audit_payload):
                    self._agent(actor)
                    request = self.validate_tool_input(actor, "submit_test", arguments)
                    data = self._tool_data(request)
                    idem_key = data.pop("idempotency_key")
                    request_hash = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                    stored = conn.execute("SELECT request_hash,response_json FROM idempotency_keys WHERE agent_id=? AND tool_name='submit_test' AND key=?", (actor.agent_id, idem_key)).fetchone()
                    if stored:
                        require(hmac.compare_digest(stored["request_hash"], request_hash), "IDEMPOTENCY_CONFLICT", "Idempotency key was used with different arguments")
                        audit_payload["idempotent_replay"] = True
                        return json.loads(stored["response_json"])
                    inflight = conn.execute("SELECT r.*,b.request_hash FROM test_request_bindings b JOIN test_runs r ON r.run_id=b.run_id WHERE b.agent_id=? AND b.key=?", (actor.agent_id, idem_key)).fetchone()
                    if inflight:
                        require(hmac.compare_digest(inflight["request_hash"], request_hash), "IDEMPOTENCY_CONFLICT", "Idempotency key was used with different arguments")
                        raise DomainError("STATUS_CONFLICT", "This test request is already pending")
                    self._agent(actor, "Builder")
                    self._require_canonical_utf8(data)
                    row = conn.execute("SELECT * FROM ideas WHERE idea_id=?", (request.idea_id,)).fetchone()
                    require(row is not None, "STATUS_CONFLICT", "An approved idea and live build claim are required")
                    idea = Idea(**dict(row))
                    approval = conn.execute("SELECT 1 FROM approvals WHERE idea_id=? AND decision='approve'", (idea.idea_id,)).fetchone()
                    require(approval, "STATUS_CONFLICT", "An approved idea and live build claim are required")
                    require(not conn.execute("SELECT 1 FROM test_runs WHERE idea_id=? AND split='OOS' AND request_state='succeeded'", (idea.idea_id,)).fetchone(),
                            "STATUS_CONFLICT", "The idea already has a successful OOS test")
                    claim = self.require_live_claim(actor, idea.idea_id, "build", request.claim_token, now)
                    if request.split == "oos":
                        require(request.confirm_oos is True, "OOS_CONFIRMATION_REQUIRED", "Explicit OOS confirmation is required")
                    canonical_spec = json.dumps(data["strategy_spec"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
                    try:
                        canonical_bytes = canonical_spec.encode("utf-8")
                    except UnicodeEncodeError:
                        raise DomainError("INVALID_INPUT", "Strategy specification must contain valid UTF-8 text") from None
                    strategy_hash = hashlib.sha256(canonical_bytes).hexdigest()
                    frozen = conn.execute("SELECT * FROM strategy_versions WHERE idea_id=? AND frozen_for_oos=1 ORDER BY ordinal LIMIT 1", (idea.idea_id,)).fetchone()
                    if request.split == "oos" and frozen:
                        require(frozen["canonical_spec_json"] == canonical_spec and frozen["strategy_hash"] == strategy_hash,
                                "STATUS_CONFLICT", "OOS retries require the first frozen strategy")
                    require(not conn.execute("SELECT 1 FROM test_runs WHERE idea_id=? AND split='OOS' AND request_state='pending'", (idea.idea_id,)).fetchone(),
                            "STATUS_CONFLICT", "An OOS test is already pending for the idea")
                    policy = self.current_policy(idea.operator_id)
                    if request.split == "oos":
                        require(self._family_budget(idea, now, pending=True) < policy.oos_limit_per_family,
                                "OOS_BUDGET_EXHAUSTED", "The family OOS budget is exhausted")
                    try:
                        manifest = selected_manifest(self.is_root if request.split == "is" else self.oos_root, request.split)
                    except EvaluatorFailure:
                        raise DomainError("EVALUATOR_FAILED", "Synthetic evaluation failed") from None
                    if request.split == "oos" and frozen:
                        version_id = frozen["version_id"]
                    else:
                        version_id = identifier()
                        ordinal = conn.execute("SELECT coalesce(max(ordinal),0)+1 FROM strategy_versions WHERE idea_id=?", (idea.idea_id,)).fetchone()[0]
                        conn.execute("INSERT INTO strategy_versions VALUES (?,?,?,?,?,?,?,?)", (version_id, idea.idea_id, ordinal, canonical_spec, strategy_hash,
                                     int(request.split == "oos"), actor.agent_id, now))
                    run_id = identifier()
                    conn.execute("INSERT INTO test_runs(run_id,idea_id,version_id,split,request_state,dataset_version,dataset_split_hash,created_at,started_at,reservation_expires_at) VALUES (?,?,?,?,'pending',?,?,?,?,?)",
                                 (run_id, idea.idea_id, version_id, request.split.upper(), manifest["dataset_version"], manifest["split_hash"], now, now,
                                  claim.expires_at if request.split == "oos" else None))
                    conn.execute("INSERT INTO test_request_bindings VALUES (?,?,?,?)", (actor.agent_id, idem_key, request_hash, run_id))
                    admitted = EvaluationRequest(run_id, idea.idea_id, idea.family_id, idea.operator_id, request.split,
                                                 json.loads(canonical_spec), strategy_hash, manifest["dataset_version"], manifest["split_hash"])
                    audit_payload.update(run_id=run_id, version_id=version_id, split=request.split, strategy_hash=strategy_hash)
            except DomainError as exc:
                result = error_result(exc)
            if admitted is None:
                if idem_key is not None and stored is None and inflight is None:
                    self._test_response_record(actor.agent_id, idem_key, request_hash, result, now)
                return result

        # No admission transaction spans this potentially failing operation.
        try:
            evaluated = self.evaluator.evaluate(admitted)
            require(evaluated.synthetic_metrics is True, "EVALUATOR_FAILED", "Synthetic evaluation failed")
            json.dumps({"metrics": evaluated.metrics, "checks": evaluated.checks}, allow_nan=False)
        except Exception:
            evaluated = None
        with self.db.transaction() as conn:
            now = utc_timestamp(self.clock.now())
            self._expire_claims(now)
            self._expire_test_reservations(now)
            run = conn.execute("SELECT r.*,b.agent_id AS request_agent_id,b.key AS request_key,b.request_hash FROM test_runs r JOIN test_request_bindings b ON b.run_id=r.run_id WHERE r.run_id=?", (admitted.run_id,)).fetchone()
            if run["request_state"] != "pending":
                return json.loads(conn.execute("SELECT response_json FROM idempotency_keys WHERE agent_id=? AND tool_name='submit_test' AND key=?", (actor.agent_id, idem_key)).fetchone()[0])
            if evaluated is None:
                return self._failed_test(run, now)
            try:
                claim = self.require_live_claim(actor, admitted.idea_id, "build", request.claim_token, now)
            except DomainError:
                return self._failed_test(run, now)
            idea = self.get_idea(admitted.idea_id)
            trial = None
            if admitted.split == "oos":
                trial = conn.execute("SELECT coalesce(max(r.oos_trial_number),0)+1 FROM test_runs r JOIN ideas i ON i.idea_id=r.idea_id WHERE i.operator_id=? AND i.family_id=? AND r.split='OOS' AND r.request_state='succeeded'", (idea.operator_id, idea.family_id)).fetchone()[0]
            try:
                result = TestResponse(run_id=admitted.run_id, version_id=run["version_id"], strategy_hash=admitted.strategy_hash,
                                      split=admitted.split, request_state="succeeded", synthetic_metrics=True,
                                      metrics=evaluated.metrics, checks=evaluated.checks, dataset_version=admitted.dataset_version,
                                      dataset_split_hash=admitted.dataset_split_hash, oos_trial_number=trial,
                                      budget_used=self._family_budget(idea, now) + int(admitted.split == "oos"),
                                      budget_limit=self.current_policy(idea.operator_id).oos_limit_per_family).model_dump(mode="json")
            except (ValidationError, ValueError, TypeError):
                return self._failed_test(run, now)
            conn.execute("UPDATE test_runs SET request_state='succeeded',evaluator_name=?,evaluator_version=?,metrics_json=?,checks_json=?,oos_trial_number=?,completed_at=?,reservation_expires_at=NULL WHERE run_id=?",
                         (evaluated.evaluator_name, evaluated.evaluator_version, json.dumps(evaluated.metrics, allow_nan=False), json.dumps(evaluated.checks, allow_nan=False), trial, now, admitted.run_id))
            if admitted.split == "oos":
                conn.execute("UPDATE claims SET closed_at=?,close_reason='test_succeeded' WHERE claim_id=?", (now, claim.claim_id))
                conn.execute("UPDATE ideas SET current_stage='tested' WHERE idea_id=?", (idea.idea_id,))
            self._audit("test.succeeded", actor, {"run_id": admitted.run_id, "split": admitted.split, "synthetic_metrics": True}, now, idea.idea_id)
            self._test_response_record(actor.agent_id, idem_key, request_hash, result, now)
            return result

    def _execute_tool(self, actor, tool_name, data, idem_key):
        if tool_name == "search":
            return self.search(actor, **data)
        if tool_name == "register":
            registration = self.register(actor, **data)
            idea = registration.idea
            return RegisterResponse(idea_id=idea.idea_id, family_id=idea.family_id,
                                    warnings=[vars(w) for w in registration.warnings], created_at=idea.created_at).model_dump(mode="json")
        if tool_name == "claim":
            claim = self.claim(actor, **data, idempotency_key=idem_key)
            require(claim is not None, "CLAIM_UNAVAILABLE", "No eligible work is available")
            idea = self.get_idea(claim.idea_id)
            return ClaimResponse(claim_id=claim.claim_id, claim_token=claim.token,
                                 idea_id=claim.idea_id, queue=claim.queue,
                                 prior_stage="approved" if claim.queue == "build" else "tested",
                                 current_stage=idea.current_stage, claimed_at=claim.claimed_at,
                                 expires_at=claim.expires_at,
                                 job_context={"title": idea.title, "hypothesis": idea.hypothesis, "rationale": idea.rationale}).model_dump(mode="json")
        if tool_name == "submit_review":
            return self._submit_review(actor, data)
        if tool_name == "get_result":
            return self._get_result(data)
        raise DomainError("STATUS_CONFLICT", "Required domain transition is not available yet",
                          {"prerequisite": "evaluation"})

    def _submit_review(self, actor, data):
        conn, now = self.db.connection, utc_timestamp(self.clock.now())
        row = conn.execute("SELECT * FROM ideas WHERE idea_id=?", (data["idea_id"],)).fetchone()
        require(row is not None, "STATUS_CONFLICT", "A tested idea and live review claim are required")
        idea = Idea(**dict(row))
        policy = self.current_policy(idea.operator_id)
        if actor.agent_id == idea.author_agent_id or (policy.review_separation == "distinct_operator" and actor.operator_id == idea.operator_id):
            raise DomainError("SELF_REVIEW_FORBIDDEN", "The configured independent review rule is not satisfied")
        run = conn.execute("SELECT * FROM test_runs WHERE run_id=? AND idea_id=? AND split='OOS' AND request_state='succeeded'",
                           (data["run_id"], idea.idea_id)).fetchone()
        require(run is not None, "STATUS_CONFLICT", "Review requires the idea's successful OOS run")
        claim = self.require_live_claim(actor, idea.idea_id, "review", data["claim_token"], now)
        require(not conn.execute("SELECT 1 FROM reviews WHERE idea_id=?", (idea.idea_id,)).fetchone(),
                "STATUS_CONFLICT", "The idea already has a review")
        review_id = identifier()
        conn.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?)",
                     (review_id, idea.idea_id, run["run_id"], actor.agent_id, data["assessment"].strip(),
                      json.dumps(list(data["concerns"]), ensure_ascii=False, separators=(",", ":")), data["recommendation"], now))
        conn.execute("UPDATE claims SET closed_at=?,close_reason='review_submitted' WHERE claim_id=?", (now, claim.claim_id))
        conn.execute("UPDATE ideas SET current_stage='reviewed' WHERE idea_id=?", (idea.idea_id,))
        self._audit("review.submitted", actor,
                    {"review_id": review_id, "run_id": run["run_id"], "separation_rule": policy.review_separation,
                     "recommendation": data["recommendation"]}, now, idea.idea_id, review_id)
        return ReviewResponse(review_id=review_id, idea_id=idea.idea_id, run_id=run["run_id"],
                              reviewer_agent_id=actor.agent_id, created_at=now).model_dump(mode="json")

    def _event_for(self, event_type, idea_id, *, payload_key=None, payload_value=None):
        matches = []
        for row in self.db.connection.execute("SELECT * FROM audit_events WHERE event_type=? ORDER BY event_id", (event_type,)):
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                raise DomainError("STATUS_CONFLICT", "Receipt provenance is incomplete or ambiguous") from None
            require(isinstance(payload, dict), "STATUS_CONFLICT", "Receipt provenance is incomplete or ambiguous")
            if row["subject_idea_id"] != idea_id and payload.get("idea_id") != idea_id:
                continue
            if payload_key is not None and payload.get(payload_key) != payload_value:
                continue
            matches.append((row, payload))
        require(len(matches) == 1, "STATUS_CONFLICT", "Receipt provenance is incomplete or ambiguous")
        return matches[0]

    def _stored_receipt_response(self, row):
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            raise DomainError("STATUS_CONFLICT", "Stored receipt integrity verification failed") from None
        require(verify_receipt(payload, row["integrity_hash"]).valid,
                "STATUS_CONFLICT", "Stored receipt integrity verification failed")
        idea = self.get_idea(row["idea_id"])
        return GetResultResponse(stage=idea.current_stage, receipt=payload,
                                 integrity_hash=row["integrity_hash"]).model_dump(mode="json")

    def _get_result(self, data):
        conn = self.db.connection
        if data.get("receipt_id") is not None:
            stored = conn.execute("SELECT * FROM receipts WHERE receipt_id=?", (data["receipt_id"],)).fetchone()
            require(stored is not None, "NOT_FOUND", "Receipt not found")
            return self._stored_receipt_response(stored)
        idea = self.get_idea(data["idea_id"])
        stored = conn.execute("SELECT * FROM receipts WHERE idea_id=?", (idea.idea_id,)).fetchone()
        if stored:
            return self._stored_receipt_response(stored)
        run = conn.execute("SELECT * FROM test_runs WHERE idea_id=? AND split='OOS' AND request_state='succeeded' ORDER BY completed_at DESC,rowid DESC LIMIT 1", (idea.idea_id,)).fetchone()
        require(run is not None, "STATUS_CONFLICT", "A successful OOS run is required")
        review = conn.execute("SELECT * FROM reviews WHERE idea_id=? AND run_id=? ORDER BY rowid LIMIT 1", (idea.idea_id, run["run_id"])).fetchone()
        require(review is not None, "REVIEW_REQUIRED", "An independent review is required")
        version = conn.execute("SELECT * FROM strategy_versions WHERE version_id=? AND idea_id=? AND frozen_for_oos=1",
                               (run["version_id"], idea.idea_id)).fetchone()
        require(version is not None, "STATUS_CONFLICT", "Frozen strategy provenance is missing")
        try:
            spec = json.loads(version["canonical_spec_json"])
            spec_bytes = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
            require(hashlib.sha256(spec_bytes).hexdigest() == version["strategy_hash"], "STATUS_CONFLICT", "Frozen strategy provenance is invalid")
            metrics, checks = json.loads(run["metrics_json"]), json.loads(run["checks_json"])
            concerns = json.loads(review["concerns_json"])
        except (ValueError, TypeError, UnicodeEncodeError, json.JSONDecodeError):
            raise DomainError("STATUS_CONFLICT", "Stored receipt provenance is invalid") from None
        reviewer = conn.execute("SELECT operator_id FROM agent_keys WHERE agent_id=?", (review["reviewer_agent_id"],)).fetchone()
        tester = conn.execute("SELECT operator_id FROM agent_keys WHERE agent_id=?", (version["created_by"],)).fetchone()
        evaluator_identity = all(isinstance(value, str) and value.strip()
                                 for value in (run["evaluator_name"], run["evaluator_version"]))
        require(reviewer is not None and tester is not None and evaluator_identity
                and run["oos_trial_number"] is not None and run["dataset_version"] and run["dataset_split_hash"],
                "STATUS_CONFLICT", "Stored receipt provenance is invalid")
        registration, registration_payload = self._event_for("idea.register", idea.idea_id)
        approval, approval_payload = self._event_for("idea.approve", idea.idea_id, payload_key="decision", payload_value="approve")
        test_event, test_payload = self._event_for("test.succeeded", idea.idea_id, payload_key="run_id", payload_value=run["run_id"])
        review_event, review_payload = self._event_for("review.submitted", idea.idea_id, payload_key="review_id", payload_value=review["review_id"])
        separation = review_payload.get("separation_rule")
        provenance_valid = (
            registration_payload.get("idea_id") == idea.idea_id
            and registration["actor_agent_id"] == idea.author_agent_id
            and registration["actor_operator_id"] == idea.operator_id
            and approval_payload.get("decision") == "approve"
            and approval["actor_operator_id"] == idea.operator_id
            and test_payload.get("split") == "oos"
            and test_event["actor_agent_id"] == version["created_by"]
            and test_event["actor_operator_id"] == idea.operator_id
            and tester["operator_id"] == idea.operator_id
            and review_event["actor_agent_id"] == review["reviewer_agent_id"]
            and review_event["actor_operator_id"] == reviewer["operator_id"]
            and review_event["subject_id"] == review["review_id"]
            and review_payload.get("run_id") == run["run_id"]
            and review_payload.get("recommendation") == review["recommendation"]
            and separation in ("distinct_agent", "distinct_operator")
            and review["reviewer_agent_id"] != idea.author_agent_id
            and (separation != "distinct_operator" or reviewer["operator_id"] != idea.operator_id)
            and isinstance(metrics, dict) and isinstance(checks, dict)
            and isinstance(concerns, list) and all(isinstance(value, str) for value in concerns)
        )
        require(provenance_valid, "STATUS_CONFLICT", "Stored receipt provenance is invalid")
        now = utc_timestamp(self.clock.now())
        receipt = build_receipt(
            receipt_id=identifier(), issued_at=now,
            idea={"idea_id": idea.idea_id, "family_id": idea.family_id, "operator_id": idea.operator_id,
                  "author_agent_id": idea.author_agent_id},
            strategy={"version_id": version["version_id"], "strategy_hash": "sha256:" + version["strategy_hash"],
                      "frozen_spec": spec, "frozen_at": version["created_at"]},
            evaluation={"run_id": run["run_id"], "split": "oos", "family_oos_trial_number": run["oos_trial_number"],
                        "dataset_version": run["dataset_version"], "dataset_split_hash": run["dataset_split_hash"],
                        "evaluator_name": run["evaluator_name"], "evaluator_version": run["evaluator_version"],
                        "synthetic_metrics": True, "metrics": metrics, "checks": checks},
            review={"review_id": review["review_id"], "reviewer_agent_id": review["reviewer_agent_id"],
                    "reviewer_operator_id": reviewer["operator_id"], "separation_rule": separation,
                    "assessment": review["assessment"], "concerns": concerns, "recommendation": review["recommendation"]},
            provenance={"registration_event_id": registration["event_id"], "approval_event_id": approval["event_id"],
                        "test_event_id": test_event["event_id"], "review_event_id": review_event["event_id"]})
        conn.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,?)",
                     (receipt.payload["receipt_id"], idea.idea_id, run["run_id"], review["review_id"],
                      canonical_receipt_bytes(receipt.payload).decode("utf-8"), receipt.integrity_hash, now))
        conn.execute("UPDATE ideas SET current_stage='receipted' WHERE idea_id=?", (idea.idea_id,))
        return self._stored_receipt_response(conn.execute("SELECT * FROM receipts WHERE idea_id=?", (idea.idea_id,)).fetchone())

    def search(self, actor, query, *, stages=None, family_id=None, limit=20):
        with self.action("idea.search", actor):
            self._agent(actor)
            request = self.validate_tool_input(actor, "search", {"query": query, "stages": stages,
                                                                 "family_id": family_id, "limit": limit})
            normalized = " ".join(request.query.lower().split())
            tokens = set(re.findall(r"[a-z0-9]+", normalized))
            ranked = []
            for row in self.db.connection.execute("SELECT rowid,* FROM ideas ORDER BY created_at DESC,rowid DESC"):
                if request.stages and row["current_stage"] not in request.stages:
                    continue
                if request.family_id is not None and row["family_id"] != request.family_id:
                    continue
                words = set(re.findall(r"[a-z0-9]+", (row["title"] + " " + row["hypothesis"]).lower()))
                overlap = len(tokens & words)
                if tokens and not overlap:
                    continue
                sources = [dict(source) for source in self.db.connection.execute("SELECT uri,label,accessed_on FROM sources WHERE idea_id=? ORDER BY rowid", (row["idea_id"],))]
                latest = self.db.connection.execute("SELECT * FROM test_runs WHERE idea_id=? AND request_state='succeeded' ORDER BY completed_at DESC,rowid DESC LIMIT 1", (row["idea_id"],)).fetchone()
                latest_result = None
                if latest is not None:
                    metrics, checks = json.loads(latest["metrics_json"]), json.loads(latest["checks_json"])
                    latest_result = {
                        "run_id": latest["run_id"], "split": latest["split"].lower(), "synthetic_metrics": True,
                        "metrics": {name: metrics[name] for name in ("annualized_return", "annualized_volatility", "sharpe_ratio", "max_drawdown", "observations") if name in metrics},
                        "checks": {name: checks[name] for name in ("acceptance", "date_min", "date_max", "observations", "synthetic_metrics") if name in checks},
                        "dataset_version": latest["dataset_version"], "dataset_split_hash": latest["dataset_split_hash"],
                        "family_oos_trial_number": latest["oos_trial_number"],
                    }
                review = self.db.connection.execute("SELECT * FROM reviews WHERE idea_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (row["idea_id"],)).fetchone()
                review_summary = None if review is None else {
                    "review_id": review["review_id"], "run_id": review["run_id"],
                    "recommendation": review["recommendation"],
                    "concern_count": len(json.loads(review["concerns_json"])),
                }
                receipt = self.db.connection.execute("SELECT receipt_id FROM receipts WHERE idea_id=?", (row["idea_id"],)).fetchone()
                summary = IdeaSummary(idea_id=row["idea_id"], family_id=row["family_id"], title=row["title"],
                                      hypothesis=row["hypothesis"], sources=sources, current_stage=row["current_stage"],
                                      author_agent_id=row["author_agent_id"], operator_id=row["operator_id"],
                                      similarity_score=overlap / len(tokens) if tokens else 0.0,
                                      latest_result=latest_result, review_summary=review_summary,
                                      receipt_id=receipt["receipt_id"] if receipt else None)
                ranked.append((overlap, row["created_at"], row["rowid"], summary))
            ranked.sort(key=lambda entry: entry[:3], reverse=True)
            result = SearchResponse(normalized_query=normalized, ideas=[entry[3] for entry in ranked[:request.limit]])
        return result.model_dump(mode="json")
