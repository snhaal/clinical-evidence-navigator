-- Clinical Evidence Navigator — Supabase Auth and User History Migration
-- Target: Postgres 15+ (Supabase compatible)
-- Run with: psql "$DATABASE_URL" -f db/migrations/0002_auth_and_history.sql

begin;

-- Safe check for auth schema if executed on a standalone non-Supabase PostgreSQL instance
create schema if not exists auth;
create table if not exists auth.users (
    id uuid primary key
);

-- Alter patient_profiles to associate queries with an authenticated user (nullable for guest mode)
alter table patient_profiles
    add column if not exists user_id uuid references auth.users(id) on delete set null;

-- Alter match_runs to associate trial evaluations with an authenticated user (nullable for guest mode)
alter table match_runs
    add column if not exists user_id uuid references auth.users(id) on delete set null;

-- Index for per-user query history sorted by most recent first
create index if not exists idx_patient_profiles_user_created
    on patient_profiles (user_id, created_at desc);

create index if not exists idx_match_runs_user_created
    on match_runs (user_id, created_at desc);

commit;
