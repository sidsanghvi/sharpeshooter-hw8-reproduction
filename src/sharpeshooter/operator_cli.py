"""Local operator-only administration. Agent actions are not exposed here."""
import argparse
from dataclasses import asdict, is_dataclass
import json
import sqlite3
import sys

from .config import Config
from .domain import ActorContext
from .errors import DomainError
from .ledger import Ledger


def parser():
    root = argparse.ArgumentParser(prog="sharpeshooter-admin")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("init-db", "audit", "create-operator", "set-policy", "configure-policy", "issue-key", "revoke-key", "approve", "link-family", "verdict"):
        command = commands.add_parser(name)
        command.add_argument("--db", default=str(Config.from_env().db_path))
        if name not in ("init-db", "audit", "create-operator"):
            command.add_argument("--operator-id", required=True)
        if name in ("approve", "link-family", "verdict"):
            command.add_argument("--idea-id", required=True)
        if name in ("approve", "verdict"):
            command.add_argument("--decision", required=True, choices=("approve", "reject") if name == "approve" else ("accept", "revise", "reject"))
            command.add_argument("--note", default="")
        if name == "audit":
            command.add_argument("--limit", type=int, default=100)
        elif name == "create-operator":
            command.add_argument("--display-name", required=True)
        elif name in ("set-policy", "configure-policy"):
            command.add_argument("--oos-limit-per-family", type=int)
            command.add_argument("--review-separation", choices=("distinct_agent", "distinct_operator"))
            command.add_argument("--claim-ttl-seconds", type=int)
        elif name == "issue-key":
            command.add_argument("--role", required=True, choices=("Scout", "Builder", "Skeptic"))
        elif name == "revoke-key":
            command.add_argument("--agent-id", required=True)
        elif name == "link-family":
            command.add_argument("--parent-idea-id", required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    ledger = Ledger(args.db)
    try:
        actor = ActorContext.operator(args.operator_id) if hasattr(args, "operator_id") else None
        if args.command == "init-db":
            ledger.initialize()
            result = {"status": "initialized", "db": args.db}
        elif args.command == "audit":
            result = ledger.audit_events(limit=args.limit)
        elif args.command == "create-operator":
            result = ledger.create_operator(args.display_name)
        elif args.command in ("set-policy", "configure-policy"):
            result = ledger.configure_policy(actor, oos_limit_per_family=args.oos_limit_per_family,
                                             review_separation=args.review_separation, claim_ttl_seconds=args.claim_ttl_seconds)
        elif args.command == "issue-key":
            # This response is the only plaintext credential disclosure.
            result = ledger.issue_key(actor, args.role)
        elif args.command == "revoke-key":
            ledger.revoke_key(actor, args.agent_id)
            result = {"status": "revoked", "agent_id": args.agent_id}
        elif args.command == "approve":
            result = ledger.approve(actor, args.idea_id, args.decision, args.note)
        elif args.command == "link-family":
            result = ledger.link_family(actor, args.idea_id, args.parent_idea_id)
        else:
            result = ledger.record_verdict(actor, args.idea_id, args.decision, args.note)
        print(json.dumps(asdict(result) if is_dataclass(result) else result, sort_keys=True))
        return 0
    except DomainError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}), file=sys.stderr)
        return 1
    except sqlite3.Error:
        print(json.dumps({"error": "database_error", "message": "Database operation failed; initialize the database first"}), file=sys.stderr)
        return 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
