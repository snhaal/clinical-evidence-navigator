-- Clinical Evidence Navigator — Initial schema
-- Target: Postgres 15+ with pgvector (Supabase free tier compatible)
-- Run with: psql "$DATABASE_URL" -f db/migrations/0001_init.sql

begin;

-- ---------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------
create extension if not exists "uuid-ossp";
create extension if not exists vector;

-- ---------------------------------------------------------------------
-- patient_profiles
-- Free-text patient input + the structured query the Plan stage derives.
-- ---------------------------------------------------------------------
create table if not exists patient_profiles (
    id                  uuid primary key default uuid_generate_v4(),
    raw_text            text not null,
    structured_query    jsonb,                  -- {condition, stage, prior_therapy, exclusions, ...}
    clarifying_question text,                    -- set if Plan stage could not confidently extract fields
    created_at          timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- trials
-- Cached metadata for trials pulled from ClinicalTrials.gov (Act stage).
-- ---------------------------------------------------------------------
create table if not exists trials (
    nct_id          text primary key,
    title           text not null,
    status          text,                        -- e.g. RECRUITING, NOT_YET_RECRUITING
    phase           text,
    conditions      text[] default '{}',
    raw_payload     jsonb,                        -- full API response, kept for debugging/replay
    last_synced_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- trial_criteria
-- Atomic, citable eligibility statements produced by the Ground stage.
-- ---------------------------------------------------------------------
create table if not exists trial_criteria (
    id              uuid primary key default uuid_generate_v4(),
    nct_id          text not null references trials(nct_id) on delete cascade,
    criterion_type  text not null check (criterion_type in ('inclusion', 'exclusion')),
    criterion_index int not null,                 -- preserves original order within the trial
    raw_text        text not null,                -- exact source sentence, used for citation validation
    embedding       vector(1536),                 -- nullable; populated if/when embeddings are added
    created_at      timestamptz not null default now(),
    unique (nct_id, criterion_type, criterion_index)
);

create index if not exists idx_trial_criteria_nct_id on trial_criteria (nct_id);

-- ---------------------------------------------------------------------
-- match_runs
-- One row per (patient_profile, trial) evaluation — the Synthesize output.
-- ---------------------------------------------------------------------
create table if not exists match_runs (
    id                  uuid primary key default uuid_generate_v4(),
    patient_profile_id  uuid not null references patient_profiles(id) on delete cascade,
    nct_id              text not null references trials(nct_id) on delete cascade,
    overall_verdict     text check (overall_verdict in ('match', 'no_match', 'unclear')),
    satisfied_count     int not null default 0,
    unclear_count       int not null default 0,
    hard_exclusion_hit  boolean not null default false,
    latency_ms          int,
    token_cost          int,
    created_at          timestamptz not null default now()
);

create index if not exists idx_match_runs_profile on match_runs (patient_profile_id);
create index if not exists idx_match_runs_nct_id on match_runs (nct_id);

-- ---------------------------------------------------------------------
-- criterion_verdicts
-- Per-criterion Verify stage output: verdict + rationale + citation.
-- ---------------------------------------------------------------------
create table if not exists criterion_verdicts (
    id              uuid primary key default uuid_generate_v4(),
    match_run_id    uuid not null references match_runs(id) on delete cascade,
    criterion_id    uuid not null references trial_criteria(id) on delete cascade,
    verdict         text not null check (verdict in ('match', 'no_match', 'unclear')),
    rationale       text not null,
    cited_text      text not null,                -- must be an exact substring of trial_criteria.raw_text
    created_at      timestamptz not null default now()
);

create index if not exists idx_criterion_verdicts_run on criterion_verdicts (match_run_id);

-- ---------------------------------------------------------------------
-- evaluation_runs
-- Gold-set scoring records for the eval harness (Sprint 2, Day 6 / 7).
-- ---------------------------------------------------------------------
create table if not exists evaluation_runs (
    id                  uuid primary key default uuid_generate_v4(),
    gold_case_id        text not null,             -- key into evals/gold_cases.json
    predicted_verdicts  jsonb not null,
    expected_verdicts   jsonb not null,
    agreement_score     numeric(5,4),               -- fraction of criteria matching gold labels
    false_match_count   int not null default 0,
    citation_valid      boolean,
    run_at              timestamptz not null default now()
);

create index if not exists idx_evaluation_runs_gold_case on evaluation_runs (gold_case_id);

commit;
