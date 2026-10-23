-- RegressLab v1.3 design baseline; PostgreSQL 16.
-- Application-generated UUIDs. Apply through one Alembic migration in implementation.
BEGIN;
CREATE TABLE projects (
 id UUID PRIMARY KEY, name VARCHAR(80) NOT NULL CHECK(length(name)>0),
 description TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), archived_at TIMESTAMPTZ
);
CREATE TABLE artifacts (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), kind TEXT NOT NULL,
 sha256 CHAR(64) NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'), relative_path TEXT NOT NULL,
 size_bytes BIGINT NOT NULL CHECK(size_bytes>=0), content_type TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(project_id,kind,sha256)
);
CREATE TABLE dataset_versions (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), name VARCHAR(80) NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('VALIDATING','READY','INVALID','ARCHIVED')),
 source_name TEXT NOT NULL, source_version TEXT NOT NULL, source_url TEXT NOT NULL,
 license_url TEXT NOT NULL, license_text TEXT NOT NULL, label_vocab JSONB NOT NULL DEFAULT '[]',
 content_sha256 CHAR(64), labelset_sha256 CHAR(64), split_manifest_sha256 CHAR(64), evaluation_data_sha256 CHAR(64),
 feature_catalog_sha256 CHAR(64), counts JSONB NOT NULL DEFAULT '{}', manifest JSONB NOT NULL DEFAULT '{}',
 raw_artifact_id UUID REFERENCES artifacts(id), error JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), sealed_at TIMESTAMPTZ
);
CREATE INDEX datasets_project_status ON dataset_versions(project_id,status,created_at);
CREATE TABLE samples (
 dataset_id UUID NOT NULL REFERENCES dataset_versions(id), sample_id VARCHAR(160) NOT NULL,
 group_id VARCHAR(160) NOT NULL, component_key VARCHAR(160) NOT NULL,
 source_partition TEXT NOT NULL CHECK(source_partition IN ('train','dev','test')),
 role TEXT NOT NULL CHECK(role IN ('TRAIN','DEV','DISCOVERY','CONFIRM','AUDIT')),
 text TEXT NOT NULL CHECK(char_length(text) BETWEEN 1 AND 8192), gold_label VARCHAR(100) NOT NULL,
 locale VARCHAR(16) NOT NULL, metadata JSONB NOT NULL DEFAULT '{}', features JSONB NOT NULL,
 text_sha256 CHAR(64) NOT NULL, PRIMARY KEY(dataset_id,sample_id)
);
CREATE INDEX samples_role ON samples(dataset_id,role,sample_id);
CREATE INDEX samples_component ON samples(dataset_id,component_key);
CREATE TABLE model_versions (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), name VARCHAR(80) NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('BUILTIN_TFIDF','PRECOMPUTED','OLLAMA')),
 status TEXT NOT NULL CHECK(status IN ('TRAINING','READY','FAILED','ARCHIVED')),
 training_dataset_id UUID NOT NULL REFERENCES dataset_versions(id), labelset_sha256 CHAR(64) NOT NULL,
 content_sha256 CHAR(64), identity_verified BOOLEAN NOT NULL DEFAULT false,
 change_type TEXT NOT NULL CHECK(change_type IN ('TRAINING_UPDATE','MODEL_REPLACEMENT','APP_CONFIG_UPDATE','DEPLOYMENT_CHANGE','REFERENCE')),
 parent_model_version_id UUID REFERENCES model_versions(id),
 weights_sha256 CHAR(64), inference_config_sha256 CHAR(64), provenance_sha256 CHAR(64),
 provenance_status TEXT NOT NULL CHECK(provenance_status IN ('SERVER_VERIFIED','DECLARED')),
 provenance JSONB, config JSONB NOT NULL,
 CHECK(parent_model_version_id IS NULL OR parent_model_version_id<>id),
 CHECK(identity_verified=(provenance_status='SERVER_VERIFIED')),
 artifact_id UUID REFERENCES artifacts(id), environment JSONB NOT NULL DEFAULT '{}', error JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX models_project ON model_versions(project_id,status,created_at);
CREATE TABLE prediction_sets (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id),
 model_version_id UUID NOT NULL REFERENCES model_versions(id), dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id),
 scope JSONB NOT NULL, scope_hash CHAR(64) NOT NULL,
 run_id UUID NOT NULL UNIQUE, inference_config_sha256 CHAR(64) NOT NULL,
 attempt_policy TEXT NOT NULL CHECK(attempt_policy IN ('DETERMINISTIC_RESUME','WHOLE_RUN_NO_ROW_MIX')),
 coverage JSONB NOT NULL DEFAULT '{}', raw_artifact_id UUID REFERENCES artifacts(id), run_manifest JSONB,
 status TEXT NOT NULL CHECK(status IN ('AWAITING_INPUT','QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
 expected_count BIGINT NOT NULL CHECK(expected_count>=0), completed_count BIGINT NOT NULL DEFAULT 0 CHECK(completed_count>=0),
 content_sha256 CHAR(64), error JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK(completed_count<=expected_count)
);
CREATE INDEX prediction_sets_project ON prediction_sets(project_id,created_at);
CREATE TABLE predictions (
 prediction_set_id UUID NOT NULL REFERENCES prediction_sets(id), sample_id VARCHAR(160) NOT NULL,
 prediction_label VARCHAR(100) NOT NULL, latency_ms DOUBLE PRECISION CHECK(latency_ms>=0),
 raw_response_sha256 CHAR(64) NOT NULL,
 PRIMARY KEY(prediction_set_id,sample_id)
);
CREATE TABLE analyses (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id),
 dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id),
 old_prediction_set_id UUID NOT NULL REFERENCES prediction_sets(id), new_prediction_set_id UUID NOT NULL REFERENCES prediction_sets(id),
 status TEXT NOT NULL CHECK(status IN ('QUEUED','DISCOVERING','AWAITING_CONFIRMATION','CONFIRMING','SUCCEEDED','FAILED','CANCELLED')),
 config JSONB NOT NULL, config_hash CHAR(64) NOT NULL, candidate_set_hash CHAR(64),
 evidence_mode TEXT NOT NULL CHECK(evidence_mode IN ('CONFIRMATORY','DESCRIPTIVE_ONLY')),
 stability_manifest_sha256 CHAR(64), stability_artifact_id UUID REFERENCES artifacts(id),
 summary TEXT CHECK(summary IN ('REVIEW_REQUIRED','INCONCLUSIVE','NO_CONFIRMED_REGRESSION')),
 summary_reason TEXT, metrics JSONB, confusion_changes JSONB, error JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
);
CREATE INDEX analyses_project ON analyses(project_id,created_at);
CREATE TABLE slices (
 id UUID PRIMARY KEY, analysis_id UUID NOT NULL REFERENCES analyses(id), rank INTEGER NOT NULL CHECK(rank>=1),
 predicate JSONB NOT NULL, predicate_hash CHAR(64) NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PROPOSED','CONFIRMED_REGRESSION','NOT_CONFIRMED','INSUFFICIENT_SUPPORT')),
 discovery JSONB NOT NULL, confirmation JSONB,
 review_flag TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK(review_flag IN ('UNREVIEWED','NEEDS_ATTENTION','DISMISSED_WITH_NOTE')),
 review_note TEXT NOT NULL DEFAULT '', reviewed_at TIMESTAMPTZ,
 UNIQUE(analysis_id,predicate_hash), UNIQUE(analysis_id,rank)
);
CREATE TABLE confirmation_uses (
 id UUID PRIMARY KEY, dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id),
 evaluation_data_sha256 CHAR(64) NOT NULL, old_model_content_hash CHAR(64) NOT NULL, new_model_content_hash CHAR(64) NOT NULL,
 analysis_id UUID NOT NULL REFERENCES analyses(id), candidate_set_hash CHAR(64) NOT NULL,
 consumed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(evaluation_data_sha256,old_model_content_hash,new_model_content_hash), UNIQUE(analysis_id)
);
CREATE TABLE suites (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), analysis_id UUID NOT NULL REFERENCES analyses(id),
 dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id),
 status TEXT NOT NULL CHECK(status IN ('BUILDING','READY','FAILED')),
 budget INTEGER NOT NULL CHECK(budget BETWEEN 1 AND 500), algorithm TEXT NOT NULL CHECK(algorithm='coverage_diversity_v1'),
 config JSONB NOT NULL, content_sha256 CHAR(64), summary JSONB, artifact_id UUID REFERENCES artifacts(id), error JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE suite_items (
 suite_id UUID NOT NULL REFERENCES suites(id), sample_id VARCHAR(160) NOT NULL,
 rank INTEGER NOT NULL CHECK(rank>=1), text TEXT NOT NULL, gold_label VARCHAR(100) NOT NULL,
 baseline_prediction_label VARCHAR(100) NOT NULL, obligation_ids JSONB NOT NULL, selection_reason TEXT NOT NULL,
 source_text_sha256 CHAR(64) NOT NULL, PRIMARY KEY(suite_id,sample_id), UNIQUE(suite_id,rank)
);
CREATE TABLE replays (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), suite_id UUID NOT NULL REFERENCES suites(id),
 target_model_version_id UUID NOT NULL REFERENCES model_versions(id), prediction_set_id UUID REFERENCES prediction_sets(id),
 status TEXT NOT NULL CHECK(status IN ('AWAITING_INPUT','QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
 verdict TEXT CHECK(verdict IN ('PASS','FAIL','ERROR')), judge_enqueued BOOLEAN NOT NULL DEFAULT false, result JSONB, error JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
);
CREATE TABLE jobs (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id),
 kind TEXT NOT NULL CHECK(kind IN ('IMPORT_DATA','TRAIN_MODEL','PREDICT','IMPORT_PREDICTIONS','DISCOVER','CONFIRM','BUILD_SUITE','REPLAY','EXPLAIN')),
 resource_type TEXT NOT NULL, resource_id UUID NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
 input JSONB NOT NULL DEFAULT '{}', attempt_no INTEGER NOT NULL DEFAULT 0 CHECK(attempt_no>=0), attempt_token UUID,
 worker_id TEXT, lease_expires_at TIMESTAMPTZ, heartbeat_at TIMESTAMPTZ,
 progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
 cancel_requested BOOLEAN NOT NULL DEFAULT false, error JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ
);
CREATE INDEX jobs_claim ON jobs(status,created_at,id);
CREATE INDEX jobs_lease ON jobs(lease_expires_at) WHERE status='RUNNING';
CREATE UNIQUE INDEX jobs_one_active_kind_resource ON jobs(kind,resource_type,resource_id) WHERE status IN ('QUEUED','RUNNING');
CREATE TABLE explanations (
 id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), analysis_id UUID NOT NULL REFERENCES analyses(id),
 job_id UUID REFERENCES jobs(id), status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
 body JSONB, provider_usage JSONB, error JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(analysis_id)
);
CREATE TABLE audit_events (
 id UUID PRIMARY KEY, project_id UUID REFERENCES projects(id), action TEXT NOT NULL,
 resource_type TEXT NOT NULL, resource_id UUID, request_id UUID NOT NULL,
 detail JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_project_time ON audit_events(project_id,created_at);
CREATE TABLE idempotency_keys (
 scope TEXT NOT NULL, key VARCHAR(128) NOT NULL, request_hash CHAR(64) NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('IN_PROGRESS','COMPLETE')), response_status INTEGER, response_body JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(scope,key)
);
-- content_sha256 on model_versions means immutable application-version fingerprint, not raw weight identity.
-- CONFIRMATORY stability/raw artifacts are restricted; DECLARED imports remain unverified.
-- Business invariants (roles, project ownership, sealed content, one final artifact)
-- are enforced by application services in transactions; see docs 02 and 06.
COMMIT;
