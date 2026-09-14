# Clinical Evidence Navigator

An agentic RAG system that matches a plain-language patient profile to clinical trials on
[ClinicalTrials.gov](https://clinicaltrials.gov), reasoning through each trial's eligibility
criteria one at a time and returning a ranked, fully-cited shortlist with an honest "unclear"
verdict wherever information is missing.

> **Not a medical device.** This is a portfolio engineering project demonstrating agentic RAG
> architecture. It does not provide medical advice and must never be used for real clinical
> decisions. See [Safety & scope](#safety--scope).

## How it works

```
Browser → FastAPI /match → Plan → Act → Ground → Verify → Synthesize → render
```

| Stage | What it does | Failure mode it isolates |
|---|---|---|
| **Plan** | Converts free-text patient profile into a structured, schema-validated query (LLM call). | Ambiguous input → asks one clarifying question, never guesses. |
| **Act** | Calls the ClinicalTrials.gov API v2 with the structured query. | API timeout/error → visible error state, never a silent empty result. |
| **Ground** | Splits each trial's eligibility text into atomic, numbered, citable criteria. No LLM call — deterministic, unit-tested. | Bad split → caught by unit tests before it ever reaches the model. |
| **Verify** | One constrained LLM call per criterion: match / no_match / unclear + rationale + citation. | Fabricated citation → downgraded to `unclear` in code, never displayed as trusted. |
| **Synthesize** | Ranks trials, surfaces hard exclusions, assembles the cited response. Pure aggregation, no LLM call. | A matched exclusion criterion always overrides an otherwise high match score. |

The core trust guarantee: **every verdict cites the exact source sentence it's based on, and that
citation is checked as a real substring of the criterion text before it's ever trusted** — see
`backend/app/pipeline/verify.py`. A citation that fails this check is downgraded to `unclear` in
code, not just discouraged by the prompt.

## Repository structure

```
backend/
  app/
    adapters/       # thin wrappers over ClinicalTrials.gov and the LLM provider
    pipeline/        # Plan, Act, Ground, Verify, Synthesize + shared schemas
    repositories/    # plain SQL (SQLAlchemy Core, no ORM) reads/writes
    api/             # the /match route and its request/response contracts
    config.py, db.py, main.py, rate_limit.py
  evals/             # gold_cases.json, scoring.py, run_eval.py, reports/
  tests/             # unit tests for every module above (pytest)
db/
  migrations/0001_init.sql   # Postgres + pgvector schema
frontend/
  app/, components/, lib/    # Next.js 14 (App Router) + TypeScript + Tailwind
.github/workflows/ci.yml     # lint + test + typecheck + build on every PR
render.yaml                  # backend deploy blueprint (Render, free tier)
```

**Deviation from the original plan worth noting:** the plan's suggested structure splits `agent/`
and `api/` at the top level; this build consolidates both under `backend/app/` (with `pipeline/`
standing in for `agent/`) since the API layer is a thin wrapper directly over the pipeline stages
and a solo build benefits from one importable package rather than two.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 14 + TypeScript + Tailwind CSS |
| Backend | FastAPI (Python 3.11) |
| Trial data | ClinicalTrials.gov API v2 (public, no key) |
| Database | Postgres + pgvector (Supabase free tier) |
| LLM | One provider behind a swappable adapter (Anthropic by default), usage-capped |
| Hosting | Vercel (frontend) + Render (backend) + Supabase (DB) — all free tier |

No message queue, no Docker/Kubernetes, no second vector database, no multi-agent framework with
hidden control flow — every hop in the request path is explainable from memory.

## Setup

### 1. Database

Run the migration against a Supabase (or any Postgres 15+ with `pgvector` available) instance:

```bash
psql "$DATABASE_URL" -f db/migrations/0001_init.sql
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in DATABASE_URL and LLM_PROVIDER_API_KEY
uvicorn app.main:app --reload
```

Visit `http://localhost:8000/health` to confirm DB connectivity, and `http://localhost:8000/docs`
for the interactive API docs.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL, defaults to localhost:8000
npm run dev
```

Visit `http://localhost:3000`.

## Testing

```bash
cd backend
pytest -v
```

62 unit tests cover every pipeline stage, the rate limiter, and the eval-scoring math — all fully
offline (faked LLM/API calls, no real credentials needed). Ground-stage tests in particular exist
to catch a bad criterion split *before* it ever reaches the model, per the architecture's isolation
principle.

```bash
cd frontend
npx tsc --noEmit && npm run build
```

## Evaluation

```bash
cd backend
python -m evals.run_eval              # full run: Plan/Act retrieval-recall + Ground/Verify scoring
python -m evals.run_eval --skip-retrieval   # skip the retrieval-recall check
python -m evals.run_eval --persist          # also write evaluation_runs rows to Postgres
```

Reports five metrics: **criterion agreement rate**, **false-match rate** (the single most
important number — minimized above all), **citation validity**, **retrieval recall**, and an
abstention proxy (see caveat below). Prints a summary and writes a timestamped JSON report to
`backend/evals/reports/`.

**Honest gap:** `backend/evals/gold_cases.json` ships with 4 starter cases (11 labeled criteria) —
2 fully real-format, 2 templated with `REPLACE WITH...` placeholders. The project plan calls for
30–50 hand-labeled criteria, verified by a human against real, live ClinicalTrials.gov listings —
that verification step is deliberately not something this codebase does for you. Growing the gold
set is the single highest-leverage hour to spend before calling this "evaluated" rather than
"demoed."

Abstention *precision* (is "unclear" used only when information is genuinely missing?) also can't
be fully automated from labels alone — `run_eval.py` reports a proxy (does the model's "unclear"
agree with the gold label's "unclear"?) and flags it explicitly as needing manual sampling on top.

## Deployment

- **Frontend:** connect the repo to Vercel, set the root directory to `frontend/`, add
  `NEXT_PUBLIC_API_BASE_URL` pointing at the deployed backend.
- **Backend:** `render.yaml` is a ready-to-use Blueprint — connect the repo in the Render
  dashboard, it auto-detects the file. Fill in `DATABASE_URL`, `LLM_PROVIDER_API_KEY`, and `APP_URL`
  (your Vercel URL, for CORS) in the dashboard after first deploy.
- **Database:** Supabase free tier; run the migration once against the connection string.

Cold-start latency on Render's free tier is a known limitation — warm the backend with a health
check before a live demo.

## Known limitations

- **Ground-stage parsing** handles bulleted/numbered eligibility text well; a trial with pure
  unbulleted paragraph criteria falls back to treating the whole block as one inclusion criterion
  (safe — never misparses polarity — but low-value for per-criterion reasoning). Worth revisiting
  with an LLM-assisted splitter if the gold set shows this is common.
- **Trials are verified sequentially** within one `/match` request (criteria *within* a trial run
  concurrently, bounded by a semaphore). For 5–10 trials this should stay within the ~12s target,
  but hasn't been load-tested against that number in production.
- **Rate limiting is in-memory, single-instance.** Fine for a solo free-tier demo; move to
  Postgres/Redis-backed counting before running more than one backend worker.
- **Frontend dependency audit** flags Next.js 14.x advisories (`npm audit`); pinned to the latest
  14.2.x patch since the plan specifies Next 14 and a jump to Next 16 is a breaking-change
  upgrade out of scope here.
- **Gold evaluation set** needs expansion by a human against real trial listings — see
  [Evaluation](#evaluation) above.
- **DB repository layer** (`app/repositories/`) has no integration tests against a real Postgres
  instance in this build — the SQL is straightforward and reviewed by hand, but that's a
  conscious trade-off against effort budget, not an oversight to gloss over.

## Safety & scope

- Synthetic or hypothetical patient profiles only, in all demos and screenshots — never real PHI.
- Trial data itself is public by design (ClinicalTrials.gov). No privacy concern on that side.
- The disclaimer banner is present on every screen of the frontend, unconditionally.
- Never claim HIPAA compliance or clinical validation — this project makes neither claim.
- Out of scope for this release: real EHR integration, multi-language support, automated trial
  enrollment, any write-action against a third-party system, clinical-grade regulatory validation.

## Sign-off checklist (from the project plan)

- [x] A user can paste a profile and receive a ranked, cited shortlist (target: ~12s)
- [x] Every verdict cites the exact source sentence, validated against retrieved text before display
- [x] The system abstains ("unclear") rather than guesses when information is missing
- [x] A gold evaluation set + automated scoring script exist (started; needs expansion — see above)
- [ ] Deployed on free-tier infrastructure with a working public demo link — deployment configs are
      in place (`render.yaml`, Vercel-ready frontend); an actual live deploy is the next step
- [x] Disclaimer visible on every screen
- [x] Architecture and every design trade-off documented above
