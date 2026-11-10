CREATE TABLE IF NOT EXISTS operators (
 operator_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operator_policy_versions (
 policy_id TEXT PRIMARY KEY, operator_id TEXT NOT NULL REFERENCES operators,
 effective_at TEXT NOT NULL, oos_limit_per_family INTEGER NOT NULL CHECK(oos_limit_per_family>=0),
 review_separation TEXT NOT NULL CHECK(review_separation IN ('distinct_agent','distinct_operator')),
 claim_ttl_seconds INTEGER NOT NULL CHECK(claim_ttl_seconds>0)
);
CREATE TABLE IF NOT EXISTS agent_keys (
 agent_id TEXT PRIMARY KEY, operator_id TEXT NOT NULL REFERENCES operators,
 role TEXT NOT NULL CHECK(role IN ('Scout','Builder','Skeptic')), key_prefix TEXT NOT NULL UNIQUE,
 salt TEXT NOT NULL, key_hash TEXT NOT NULL, issued_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS strategy_families (
 family_id TEXT PRIMARY KEY, canonical_idea_id TEXT NOT NULL REFERENCES ideas DEFERRABLE INITIALLY DEFERRED,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ideas (
 idea_id TEXT PRIMARY KEY, family_id TEXT NOT NULL REFERENCES strategy_families,
 operator_id TEXT NOT NULL REFERENCES operators, author_agent_id TEXT NOT NULL REFERENCES agent_keys,
 title TEXT NOT NULL, hypothesis TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL,
 current_stage TEXT NOT NULL CHECK(current_stage IN ('proposed','approved','claimed(builder)','tested','claimed(review)','reviewed','receipted','verdict'))
);
CREATE TABLE IF NOT EXISTS sources (
 source_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas,
 uri TEXT NOT NULL, label TEXT NOT NULL, accessed_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idea_links (
 link_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas, related_idea_id TEXT NOT NULL REFERENCES ideas,
 link_type TEXT NOT NULL CHECK(link_type IN ('declared_parent','manual_family','similarity_warning')),
 similarity_score REAL CHECK(similarity_score>=0 AND similarity_score<=1), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
 approval_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL UNIQUE REFERENCES ideas,
 operator_id TEXT NOT NULL REFERENCES operators, decision TEXT NOT NULL CHECK(decision IN ('approve','reject')),
 note TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
 claim_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas,
 queue TEXT NOT NULL CHECK(queue IN ('build','review')), agent_id TEXT NOT NULL REFERENCES agent_keys,
 token_hash TEXT NOT NULL, claimed_at TEXT NOT NULL, expires_at TEXT NOT NULL, closed_at TEXT, close_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_claim_per_idea ON claims(idea_id) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS queue_stage ON ideas(current_stage,created_at);
CREATE TABLE IF NOT EXISTS strategy_versions (
 version_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas, ordinal INTEGER NOT NULL CHECK(ordinal>0),
 canonical_spec_json TEXT NOT NULL, strategy_hash TEXT NOT NULL, frozen_for_oos INTEGER NOT NULL CHECK(frozen_for_oos IN (0,1)),
 created_by TEXT NOT NULL REFERENCES agent_keys, created_at TEXT NOT NULL, UNIQUE(idea_id,ordinal)
);
CREATE TABLE IF NOT EXISTS test_runs (
 run_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas, version_id TEXT NOT NULL REFERENCES strategy_versions,
 split TEXT NOT NULL CHECK(split IN ('IS','OOS')), request_state TEXT NOT NULL CHECK(request_state IN ('pending','succeeded','failed')),
 dataset_version TEXT, dataset_split_hash TEXT, evaluator_name TEXT, evaluator_version TEXT,
 metrics_json TEXT, checks_json TEXT, failure_code TEXT, oos_trial_number INTEGER,
 created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, reservation_expires_at TEXT
);
CREATE TABLE IF NOT EXISTS test_request_bindings (
 agent_id TEXT NOT NULL REFERENCES agent_keys,
 key TEXT NOT NULL CHECK(length(key)=36),
 request_hash TEXT NOT NULL CHECK(length(request_hash)=64 AND request_hash NOT GLOB '*[^0-9a-f]*'),
 run_id TEXT NOT NULL UNIQUE REFERENCES test_runs,
 PRIMARY KEY(agent_id,key)
);
CREATE TABLE IF NOT EXISTS reviews (
 review_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas, run_id TEXT NOT NULL REFERENCES test_runs,
 reviewer_agent_id TEXT NOT NULL REFERENCES agent_keys, assessment TEXT NOT NULL,
 concerns_json TEXT NOT NULL, recommendation TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
 receipt_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL UNIQUE REFERENCES ideas, run_id TEXT NOT NULL REFERENCES test_runs,
 review_id TEXT NOT NULL REFERENCES reviews, payload_json TEXT NOT NULL, integrity_hash TEXT NOT NULL, issued_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verdicts (
 verdict_id TEXT PRIMARY KEY, idea_id TEXT NOT NULL UNIQUE REFERENCES ideas, operator_id TEXT NOT NULL REFERENCES operators,
 decision TEXT NOT NULL CHECK(decision IN ('accept','revise','reject')), note TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency_keys (
 agent_id TEXT NOT NULL REFERENCES agent_keys, tool_name TEXT NOT NULL, key TEXT NOT NULL,
 request_hash TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(agent_id,tool_name,key)
);
CREATE TABLE IF NOT EXISTS audit_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
 actor_operator_id TEXT, actor_agent_id TEXT, subject_idea_id TEXT, subject_id TEXT,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS operators_no_delete BEFORE DELETE ON operators BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS operator_policy_versions_no_delete BEFORE DELETE ON operator_policy_versions BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_keys_no_delete BEFORE DELETE ON agent_keys BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS strategy_families_no_delete BEFORE DELETE ON strategy_families BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ideas_no_delete BEFORE DELETE ON ideas BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS sources_no_delete BEFORE DELETE ON sources BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS idea_links_no_delete BEFORE DELETE ON idea_links BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS approvals_no_delete BEFORE DELETE ON approvals BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS claims_no_delete BEFORE DELETE ON claims BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS strategy_versions_no_delete BEFORE DELETE ON strategy_versions BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS test_runs_no_delete BEFORE DELETE ON test_runs BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS reviews_no_delete BEFORE DELETE ON reviews BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS verdicts_no_delete BEFORE DELETE ON verdicts BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS idempotency_keys_no_delete BEFORE DELETE ON idempotency_keys BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS operators_no_update BEFORE UPDATE ON operators BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS operator_policy_versions_no_update BEFORE UPDATE ON operator_policy_versions BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS strategy_families_no_update BEFORE UPDATE ON strategy_families BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS sources_no_update BEFORE UPDATE ON sources BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS idea_links_no_update BEFORE UPDATE ON idea_links BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS approvals_no_update BEFORE UPDATE ON approvals BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS strategy_versions_no_update BEFORE UPDATE ON strategy_versions BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS reviews_no_update BEFORE UPDATE ON reviews BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS verdicts_no_update BEFORE UPDATE ON verdicts BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS idempotency_keys_no_update BEFORE UPDATE ON idempotency_keys BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ideas_original_fields BEFORE UPDATE OF idea_id,operator_id,author_agent_id,title,hypothesis,rationale,created_at ON ideas BEGIN SELECT RAISE(ABORT,'original idea fields are immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_keys_original_fields BEFORE UPDATE OF agent_id,operator_id,role,key_prefix,salt,key_hash,issued_at ON agent_keys BEGIN SELECT RAISE(ABORT,'original key fields are immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_keys_no_unrevoke BEFORE UPDATE OF revoked_at ON agent_keys WHEN OLD.revoked_at IS NOT NULL BEGIN SELECT RAISE(ABORT,'revocation is permanent'); END;
CREATE TRIGGER IF NOT EXISTS claims_original_fields BEFORE UPDATE OF claim_id,idea_id,queue,agent_id,token_hash,claimed_at,expires_at ON claims BEGIN SELECT RAISE(ABORT,'original claim fields are immutable'); END;
CREATE TRIGGER IF NOT EXISTS claims_close_once BEFORE UPDATE OF closed_at,close_reason ON claims WHEN OLD.closed_at IS NOT NULL BEGIN SELECT RAISE(ABORT,'closed claims are immutable'); END;
CREATE TRIGGER IF NOT EXISTS test_runs_original_fields BEFORE UPDATE OF run_id,idea_id,version_id,split,created_at ON test_runs BEGIN SELECT RAISE(ABORT,'original run fields are immutable'); END;

CREATE TRIGGER IF NOT EXISTS test_runs_dataset_identity BEFORE UPDATE OF dataset_version,dataset_split_hash ON test_runs BEGIN SELECT RAISE(ABORT,'run dataset identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS test_request_bindings_no_update BEFORE UPDATE ON test_request_bindings BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS test_request_bindings_no_delete BEFORE DELETE ON test_request_bindings BEGIN SELECT RAISE(ABORT,'history is append-only'); END;
