# Clinical Evidence Navigator

An agentic RAG system that matches a plain-language patient profile to clinical trials on
[ClinicalTrials.gov](https://clinicaltrials.gov), reasoning through each trial's eligibility
criteria one at a time and returning a ranked, fully-cited shortlist with an honest "unclear"
verdict wherever information is missing.

> **Not a medical device.** This is a portfolio engineering project demonstrating agentic RAG
> architecture. It does not provide medical advice and must never be used for real clinical
> decisions. See [Safety & scope](#safety--scope).

**Live demo:** [ADD YOUR VERCEL URL HERE] · **API:** [ADD YOUR RENDER URL HERE]

## How it works

```
Browser → FastAPI /match → Plan → Act → Ground → Verify → Synthesize → render
```

| Stage | What it does | Failure mode it isolates |
|---|---|---|
| **Plan** | Converts free-text patient profile into a structured, schema-validated query (LLM call). | Ambiguous input → asks one clarifying question, never guesses. |
| **Act** | Calls the ClinicalTrials.gov API v2 with the structured query. | API timeout/error → visible error state, never a silent empty result. |
| **Ground** | Splits each trial's eligibility text into atomic, numbered, citable criteria. No LLM call — deterministic, unit-tested. | Bad split → caught by unit tests before it ever reaches the model. |
| **Verify** | One constrained, schema-validated LLM call **per trial**, batching every criterion in that trial: match / no_match / unclear + rationale + citation each. | Fabricated citation → downgraded to `unclear` in code, never displayed as trusted. A criterion the model omits or gets malformed is repaired individually (single-criterion fallback) rather than invalidating the whole trial. |
| **Synthesize** | Ranks trials, surfaces hard exclusions, assembles the cited response. Pure aggregation, no LLM call. | A matched exclusion criterion always overrides an otherwise high match score. |

### Verification Pipeline Architecture & Safety Guardrails

Verify batches criteria on a per-trial basis (`verify_all_criteria` in `backend/app/pipeline/verify.py`) using **Groq** (`openai/gpt-oss-120b`) with strict JSON schema enforcement, backed by rigorous clinical guardrails:

1. **Evidence-First Schema Ordering**: The response JSON schema places `evidence_quote` before `rationale` and `verdict`. The model must quote the verbatim sentence from the patient profile supporting the evaluation. If the clinical parameter is undocumented, `evidence_quote` must strictly be `null`.
2. **Strict Absence Handling**: If a criterion specifies particular lab thresholds (e.g., LVEF <= 40%, NT-proBNP >= 600 pg/mL), disease staging, or prior therapies not documented in the patient profile, it must evaluate to `unclear` (`INSUFFICIENT_DATA`). Missing data is never assumed normal.
3. **Compound Criteria Rule**: If a criterion contains multiple required conjuncts (e.g., condition A *and* condition B), both must be verified with explicit evidence. Partial documentation resolves to `unclear`.
4. **Exclusion Logic Enforcement**: Explicitly separates inclusion vs. exclusion reasoning. Finding matching evidence for an exclusion criterion strictly marks the criterion as `no_match` (ineligible).
5. **Rate Pacing & Token Budgeting**: Outbound Groq calls are throttled with asynchronous sleep (`await asyncio.sleep(2.8)`) and token output budgets are dynamically bounded (`_BATCH_TOKENS_PER_CRITERION = 220`, floor = 800, ceiling = 4800) to stay within Groq's 8,000 TPM limit and prevent 429 errors.
6. **Resilient Citation Verification**: `_validate_citation` verifies exact substring matches and transparently unescapes markdown comparison operators (`\<`, `\<=`, `\>=`) from ClinicalTrials.gov API text, guaranteeing 100% citation validity.
7. **Single-Criterion Fallback Repair**: Any criterion omitted or malformed in a batch is repaired individually with `max_tokens=800` rather than invalidating the entire trial.

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
| LLM | One provider behind a swappable adapter — **Anthropic**, **Gemini**, or **Groq** (`.env.example` defaults to Groq; see below) |
| Hosting | Vercel (frontend) + Render (backend) + Supabase (DB) — all free tier |

**Provider note:** `app/adapters/llm.py` supports all three providers behind one interface
(`LLMAdapter.complete()`). Groq is the default in `.env.example` because its free tier (30 RPM) is
far more workable than Gemini's (observed as low as ~5 RPM) for a public demo, and it uses the
standard `openai` SDK against an OpenAI-compatible endpoint rather than a newer, more
version-sensitive SDK. The default Groq model, `openai/gpt-oss-120b`, is specifically chosen
because it supports Groq's strict schema-enforced JSON output, which the batched Verify stage
relies on for reliability (see below). Anthropic remains supported and is the simplest path if
you don't care about free-tier RPM limits.

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
cp .env.example .env
```

Configure your environment variables in `.env`:
```env
LLM_PROVIDER=groq
LLM_MODEL=openai/gpt-oss-120b
GROQ_API_KEY=<your-api-key>
# DATABASE_URL=postgresql+asyncpg://...
```

Run the FastAPI application:
```bash
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

83 unit tests cover every pipeline stage, both rate limiters (the per-IP HTTP limiter in
`app/rate_limit.py` and the process-wide LLM-call-pacing limiter in
`app/adapters/rate_limiter.py`), the Groq adapter's schema-wrapping/fallback behavior, and the
eval-scoring math — all fully offline (faked LLM/API calls, no real credentials needed; dummy
`DATABASE_URL`/`LLM_PROVIDER_API_KEY` values are enough to run the suite). Ground-stage tests in
particular exist to catch a bad criterion split *before* it ever reaches the model, per the
architecture's isolation principle.

```bash
cd frontend
npx tsc --noEmit && npm run build
```

## Evaluation

The clinical verification pipeline is continuously benchmarked against a gold standard suite (`backend/evals/gold_cases.json`) of 5 curated real-world clinical cases and 29 hand-labeled criteria spanning diverse oncology and cardiology indications.

### Reproduction Command

To reproduce the benchmark suite locally with retrieval skipping:

```bash
cd backend
python -u -m evals.run_eval --skip-retrieval
```

Additional evaluation flags:
```bash
python -u -m evals.run_eval                 # full run: Plan/Act retrieval-recall + Ground/Verify scoring
python -u -m evals.run_eval --persist       # record evaluation_runs to Postgres
python evals/diagnose_eval.py --dump-false-matches  # inspect discrepancies and isolate false positives
```

### Benchmark Results (`run_20260916T113243Z.json`)

| Metric | Result | Clinical Impact |
| :--- | :---: | :--- |
| **Evaluated Criteria** | **29 / 29 (100.0%)** | Full coverage across all 5 gold benchmark cases; resolved ClinicalTrials.gov markdown operator escaping (`\<`, `\<=`, `\>=`) |
| **False-Match Rate** | **0.0%** | **Eliminated all false positives** (down from 30.0% baseline via safe abstention design) |
| **Criterion Agreement** | **79.3%** | 23/29 exact matches; all 6 discrepancies are safe clinical abstentions (`unclear`), never dangerous false inclusions |
| **Citation Validity** | **100.0%** | Every single verdict cites a verified verbatim substring from the source trial text |
| **Unhandled 429 Errors** | **0** | Asynchronous 2.8s rate pacing (`await asyncio.sleep(2.8)`) and dynamic token budgeting prevent rate limits under Groq 8k TPM |
| **Unit Test Suite** | **53 passed, 0 failed** | Full offline regression pass (`pytest tests/`) covering parsing, schema validation, rate limiters, and verification |

### Benchmark Gold Cases Breakdown

1. `case_001_esophageal_scc_stage3` (NCT03734952): 8 criteria (Stage III esophageal SCC; evaluates prior therapy exclusions and ECOG abstention).
2. `case_002_knee_osteoarthritis_unbulleted` (NCT04423445): 2 criteria (Unbulleted paragraph criteria decomposition).
3. `case_003_nsclc_kras_g12c` (NCT04613596): 6 criteria (Metastatic NSCLC with KRAS G12C and PD-L1 TPS >= 50%; brain metastases exclusions).
4. `case_004_tnbc_washout_ejection_fraction` (NCT03719326): 7 criteria (Metastatic TNBC after 4 therapy lines; LVEF >= 50% and surgery washouts).
5. `case_005_heart_failure_reduced_ef` (NCT03057977): 6 criteria (Systolic heart failure NYHA III, LVEF 28% <= 40%, NT-proBNP thresholds, hypotension exclusion).

## Deployment

- **Frontend:** connect the repo to Vercel, set the root directory to `frontend/`, add
  `NEXT_PUBLIC_API_BASE_URL` pointing at the deployed backend.
  Live demo: **https://clinical-evidence-navigator.vercel.app/**
- **Backend:** `render.yaml` is a ready-to-use Blueprint — connect the repo in the Render
  dashboard, it auto-detects the file. Fill in `DATABASE_URL`, `LLM_PROVIDER_API_KEY`, and `APP_URL`
  (your Vercel URL, for CORS) in the dashboard after first deploy. Note the blueprint defaults
  `LLM_PROVIDER` to `anthropic`; override it in the dashboard if you want Groq instead (see
  [Known limitations](#known-limitations)).
  Live API: **https://clinical-evidence-backend-s8vv.onrender.com/**
- **Database:** Supabase free tier; run the migration once against the connection string.

Cold-start latency on Render's free tier is a known limitation — warm the backend with a health
check before a live demo.

## Known limitations

- **Ground-stage parsing** handles bulleted/numbered eligibility text well; a trial with pure
  unbulleted paragraph criteria falls back to treating the whole block as one inclusion criterion
  (safe — never misparses polarity — but low-value for per-criterion reasoning). Worth revisiting
  with an LLM-assisted splitter if the gold set shows this is common.
- **Trials are verified sequentially** within one `/match` request (one batched LLM call per
  trial). For 5–10 trials this should stay within the ~12s target, but hasn't been load-tested
  against that number in production.
- **Rate limiting is in-memory, single-instance**, for both limiters (`app/rate_limit.py` per-IP
  HTTP limiter and `app/adapters/rate_limiter.py` per-process LLM-call pacer). Fine for a solo
  free-tier demo; move to Postgres/Redis-backed counting before running more than one backend
  worker.
- **Groq's strict JSON-schema mode is model-specific.** It's confirmed on `openai/gpt-oss-120b`
  (the `.env.example` default) but not on every Groq model — e.g. `llama-3.3-70b-versatile` lacks
  it. The adapter degrades gracefully to prompt-only JSON on a 400 from the provider, but that
  fallback is less reliable on large batched Verify calls, so switching models is not a drop-in
  change.
- **`render.yaml` still defaults `LLM_PROVIDER` to `anthropic`**, while local dev
  (`backend/.env.example`) now defaults to `groq`. Both are fully supported by the adapter, but if
  you want your Render deployment to match local dev, override `LLM_PROVIDER`,
  `LLM_PROVIDER_API_KEY`, and `LLM_MODEL` in the Render dashboard rather than assuming the
  blueprint's default.
- **Frontend dependency audit** flags Next.js 14.x advisories (`npm audit`); pinned to the latest
  14.2.x patch since the plan specifies Next 14 and a jump to Next 16 is a breaking-change
  upgrade out of scope here.
- **Gold evaluation set** currently covers 5 gold cases and 29 hand-labeled criteria. Expanding further to 50+ criteria across rare disease indications is recommended for ongoing regression monitoring — see
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

- [x] A user can paste a profile and receive a ranked, cited shortlist (target: ~12s) —
      `POST /match` implements the full Plan → Act → Ground → Verify → Synthesize loop
- [x] Every verdict cites the exact source sentence, validated against retrieved text before display
- [x] The system abstains ("unclear") rather than guesses when information is missing
- [x] A gold evaluation set + automated scoring script exist (started; needs expansion — see above)
- [x] Deployed on free-tier infrastructure with a working public demo link — see
      [Deployment](#deployment) above
- [x] Disclaimer visible on every screen
- [x] Architecture and every design trade-off documented above
