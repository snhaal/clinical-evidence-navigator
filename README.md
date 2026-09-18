# Clinical Evidence Navigator

> **Automated oncology trial matching engine bridging unstructured EHR notes with ClinicalTrials.gov via a two-stage agentic RAG pipeline.**

[![CI](https://github.com/snhaal/clinical-evidence-navigator/actions/workflows/ci.yml/badge.svg)](https://github.com/snhaal/clinical-evidence-navigator/actions/workflows/ci.yml)
[![Live Demo](https://img.shields.io/badge/demo-online-brightgreen.svg)](https://clinical-evidence-navigator.vercel.app)
[![API Status](https://img.shields.io/badge/api-active-blue.svg)](https://clinical-evidence-backend-s8vv.onrender.com/health)
[![Release: v1.3.0](https://img.shields.io/badge/release-v1.3.0-blue.svg)](https://github.com/snhaal/clinical-evidence-navigator/releases/tag/v1.3.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Live Web Application:** [https://clinical-evidence-navigator.vercel.app](https://clinical-evidence-navigator.vercel.app)  
**Production API:** [https://clinical-evidence-backend-s8vv.onrender.com](https://clinical-evidence-backend-s8vv.onrender.com)

---

## Overview

Matching cancer patients to clinical trials is traditionally a manual, labor-intensive bottleneck for oncologists and clinical research coordinators (CRCs). Unstructured electronic health record (EHR) notes contain complex surgical pathology reports, staging acronyms (e.g. `ypT2N1M0`), multi-line biomarker panels, prior systemic therapy lines, and lab values that fail naive keyword search. Conversely, trial protocols on [ClinicalTrials.gov](https://clinicaltrials.gov) contain dozens of dense, compound eligibility criteria that standard retrieval models misinterpret.

**Clinical Evidence Navigator** solves this with a **hardened, two-stage Agentic RAG architecture** designed to run at **$0.00 monthly infrastructure cost**. It converts clinical notes or uploaded documents into normalized MeSH retrieval queries, fetches actively recruiting trials with automated query relaxation fallback, and executes deep, zero-shot verification audits across up to 20 criteria per study with verbatim citation validation and clinical domain equivalence logic.

---

## v1.3.0 Key Capabilities

### 1. Supabase Auth & Multi-Tenant Data Isolation
- **Session Tokens & User Isolation**: Integrated Supabase Auth supporting email authentication and persistent session management.
- **Cryptographic Backend Verification**: Backend verifies both ES256 and RS256 JWT tokens from incoming `Authorization: Bearer <token>` headers to enforce secure tenant boundary isolation.
- **Guest Mode Support**: Unauthenticated clinicians can evaluate trial eligibility immediately in Guest Mode without sign-in barriers while maintaining zero client-data persistence.

### 2. Per-User Search History & Cascade Deletion
- **Isolated Query Logs**: Authenticated search executions and criteria verdicts are securely stored in Supabase with user isolation via Row Level Security (RLS).
- **Evaluation Session Timeline**: Historical trial matches are grouped by evaluation run and timestamp for rapid clinical review and comparison.
- **Cascade Deletion**: Full user control allowing clinicians to permanently delete entire evaluation sessions and cascade delete all associated trial match records.

### 3. Deterministic Biomarker Retrieval & Evaluation
- **Biomarker-Targeted Registry Search**: Injects detected actionable driver mutations and biomarkers (e.g., `EGFR`, `HER2`, `KRAS`, `PD-L1`) directly into ClinicalTrials.gov REST v2 parameters (`query.cond` and `query.term`), avoiding generic un-targeted cohort retrievals.
- **Stage-Aware Candidate Pre-Filtering**: Upstream candidate scoring penalizes early-stage / neoadjuvant trials for Stage IV metastatic patients and excludes trials targeting contradictory driver biomarkers.
- **Zero-Temperature Evaluation Determinism**: Enforced `temperature=0.0` and fixed seeds (`seed=42`) across Gemini and Groq model adapters, with stable JSON key ordering for reproducible, auditable criteria evaluation across runs.

### 4. Validated Golden-Path Sample Profile
- **Post-Osimertinib EGFR NSCLC Case**: Default sample profile updated to a verified 62-year-old Stage IV metastatic lung adenocarcinoma patient with EGFR Exon 19 deletion, secondary c-Met amplification, and progression on first-line Osimertinib.
- **Direct Protocol Matching**: Calibrated against active clinical trials (including NCT07155187) with complete systemic treatment history, RECIST v1.1 measurements, organ function lab thresholds, and documented absence of CNS metastases.

### 5. UI Re-Alignment & Minimalist Clinical Layout
- **Full-Width Navigation**: Top navigation bar spans 100% viewport width with "Clinical Evidence Navigator" anchored on the far left and auth controls ("History", active email / guest badge, "Sign Out") grouped on the far right.
- **Relocated Clinical Disclaimer**: Removed top banner and placed a clean, persistent disclaimer in the footer: *"Not a medical device. Not a substitute for clinical judgment."*
- **Client-Side Document Ingestion & Dossier Export**: Retains zero-token client-side `.pdf`/`.docx`/`.txt` extraction and multi-page tumor board PDF export with automated table pagination.

---

## Architecture & Privacy Design

Raw medical records (pathology reports, discharge summaries, molecular diagnostic sheets) often contain protected health information (PHI) and verbose hospital administrative metadata. Sending entire multi-page clinical documents directly to backend LLMs would:
1. Compromise patient privacy by transmitting unvetted raw PHI over the network.
2. Rapidly deplete free-tier token budgets (~3,500+ tokens per raw document before matching begins).
3. Introduce prompt injection vectors and confuse query retrieval with irrelevant hospital administrative boilerplate.

### The Client-Side Ingestion Boundary
```mermaid
%%{init: {'flowchart': {'wrappingWidth': 340}}}%%
flowchart TD
    subgraph Browser["🔒 Client-Side Browser Boundary (Zero-Token, Private)"]
        DOC["`**📁 Clinical Record**
        PDF, DOCX, TXT (up to 15MB)`"]
        PARSE["`**⚙️ Deterministic Parser**
        pdfjs-dist / mammoth + clinical regex`"]
        AUTH["`**🔐 Supabase Auth & History**
        Session Tokens & Search History`"]
        EDIT["`**📝 Patient Profile Form**
        Extracted Diagnosis, Staging,
        Biomarkers, Prior Therapies`"]
        EXPORT["`**📄 Dossier PDF Export**
        jspdf + jspdf-autotable`"]
    end

    subgraph Backend["☁️ Two-Stage Agentic Matcher (FastAPI + Render)"]
        AUTH_VAL["`**🛡️ Auth & JWT Verification**
        ES256 / RS256 Bearer Token`"]
        PLAN["`**🧠 Stage 1: Planner Agent**
        Pydantic v2 StructuredQuery
        MeSH Normalization & Sanitization`"]
        ACT["`**🔍 ClinicalTrials.gov API v2**
        Recruiting Filter & 3-Tier Relaxation`"]
        VERIFY["`**✅ Stage 2: Verifier Agent**
        Gemini 3.5 Flash-Lite (JSON Schema)
        20 Criteria/Trial + Equivalence Axioms`"]
        SYNTH["`**📊 Evidence Synthesizer**
        Verbatim Citations & Match Scoring`"]
    end

    AUTH <--> EDIT
    DOC --> PARSE
    PARSE --> EDIT
    EDIT -->|"POST /match (Bearer JWT)"| AUTH_VAL
    AUTH_VAL --> PLAN
    PLAN --> ACT
    ACT --> VERIFY
    VERIFY --> SYNTH
    SYNTH -->|"MatchResponse JSON"| EDIT
    EDIT --> EXPORT

    style Browser fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff
    style Backend fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#fff
    style DOC fill:#1e293b,stroke:#64748b,color:#fff
    style PARSE fill:#0369a1,stroke:#38bdf8,color:#fff
    style AUTH fill:#0369a1,stroke:#38bdf8,color:#fff
    style EDIT fill:#047857,stroke:#34d399,color:#fff
    style EXPORT fill:#047857,stroke:#34d399,color:#fff
    style AUTH_VAL fill:#4338ca,stroke:#818cf8,color:#fff
    style PLAN fill:#4338ca,stroke:#818cf8,color:#fff
    style ACT fill:#15803d,stroke:#4ade80,color:#fff
    style VERIFY fill:#701a75,stroke:#f472b6,color:#fff
    style SYNTH fill:#b45309,stroke:#fbbf24,color:#fff
```

**Key Architectural Invariants:**
- **Zero Raw Document Transmission**: Files never leave the clinician's machine. Only the user-inspected and editable clinical summary string is sent to `POST /match`.
- **Deterministic Heuristics**: Biomarker panels, TNM stages, and prior regimens are parsed with zero LLM inference cost.
- **Fail-Safe Retrieval**: If ClinicalTrials.gov rejects complex queries with HTTP 400, the backend search adapter automatically cleans illegal punctuation and gracefully falls back to condition-level retrieval (`query.cond`), ensuring continuous uptime.

---

## Two-Stage Agentic RAG Architecture

The system decouples **retrieval query planning** from **deep criterion-level verification**, guaranteeing high recall during discovery and strict factual accuracy during evaluation.

### Pipeline Execution Stages

1. **Plan (Stage 1)**: Converts unstructured clinical narratives into a validated `StructuredQuery` schema. Normalizes conditions to standard MeSH entities while explicitly discarding staging notations (TNM, AJCC), lab thresholds, and surgical details to prevent over-constraining the search. Sanitizes search terms to ≤ 4 keywords and ≤ 60 characters to comply with ClinicalTrials.gov parser limits.
2. **Act**: Queries the ClinicalTrials.gov REST API v2 with `filter.overallStatus=RECRUITING`. If the initial query returns HTTP 400 or 0 results, the relaxation engine sanitizes query terms and iteratively broadens the search across 3 tiers.
3. **Ground**: Deterministically splits multi-paragraph eligibility text into numbered, polarity-tagged (inclusion vs. exclusion) criteria. Uses unit-tested regex heuristics — no non-deterministic LLM calls in the parsing loop.
4. **Verify (Stage 2)**: Evaluates up to 20 criteria per trial in a single batch using Gemini 3.5 Flash Lite with native JSON schema constraints (`response_mime_type="application/json"`). Grounds reasoning against today's UTC date and enforces clinical equivalence axioms.
5. **Synthesize**: Aggregates criteria verdicts, computes match eligibility scores, verifies verbatim citation substring containment against source texts, and formats output for the UI.

---

## Core Failure Modes & Production Solutions

### 1. Token Starvation & Quota Ceiling
* **Failure Mode**: Multi-paragraph trial criteria consume ~3,500 prompt tokens. When using Groq (`openai/gpt-oss-120b`), an output reservation ceiling of 4,800 tokens exceeded Groq's 8,000 TPM limit (`prompt + max_tokens > 8000`), triggering immediate HTTP 429 rejections before inference began. Concurrently, Gemini 2.5 Flash free tier enforced an unworkable 20 Requests Per Day (RPD) quota, locking out testing after 4–5 searches.
* **Production Solution**: Migrated the primary LLM adapter to `gemini-3.5-flash-lite`, which provides **250,000 TPM** and **500 RPD** on the free tier. Configured sliding-window request pacing via an in-memory rate limiter calibrated to **14 RPM**, added an explicit 2-second cooldown between consecutive trial evaluations, and implemented dynamic backoff parsing `retry-after` headers. Retained Groq with fallback plain-JSON completion as an automatic failover.

### 2. Query Over-Constraining & Zero-Result Recovery
* **Failure Mode**: When given a comprehensive surgical pathology note (e.g. *"Stage III esophageal squamous cell carcinoma post-trimodality ypT2N1M0"*), naive LLMs generated queries containing the full pathology string or illegal syntax (`Stage IVB platinum doublet chemotherapy %25`). Because ClinicalTrials.gov uses strict boolean keyword matching, this yielded 0 candidate trials or triggered HTTP 400 "Too complicated query" errors.
* **Production Solution**: 
  1. **Planner Sanitization**: System instructions strictly enforce extracting *only* concise search tokens (2–4 words), explicitly forbidding punctuation, percentages (`%`), or full sentences.
  2. **Adapter Word Limiting**: In `clinicaltrials.py`, query terms are truncated to ≤ 5 words and ≤ 60 characters with punctuation stripped.
  3. **Automated 400 Fallback & Relaxation**: If ClinicalTrials.gov responds with 400 or 0 results, the system drops `query.term` and falls back through 3 condition relaxation tiers (`"esophageal squamous cell carcinoma"` -> `"esophageal cancer"` -> `"esophagus"`), recovering recall without user disruption.

### 3. Clinical Syntactic Literalism
* **Failure Mode**: LLMs evaluated clinical criteria with syntactic rigidity rather than medical semantics. For instance:
  * A patient with *"diagnosed esophageal squamous cell carcinoma"* was marked ineligible for criteria requiring *"histologically or pathologically confirmed carcinoma"* because the word "biopsy" or "pathology" was not explicitly repeated in the same sentence.
  * A patient with *"Stage III"* cancer was failed against criteria seeking *"locally advanced or Stage II-III"*.
* **Production Solution**: Injected explicit **Clinical Domain Equivalence Axioms** directly into the verification prompt:
  * **Histological Equivalence**: A definitive diagnosis of a histological subtype (e.g. squamous cell carcinoma, adenocarcinoma) inherently satisfies requirements for pathological/histological confirmation.
  * **Staging Subsumption**: Explicit documented stages satisfy broader bracket criteria (Stage III satisfies Stage II-III / locally advanced / non-metastatic).
  * **TNM Notation**: Node-positive staging (N1, N2) implies regional lymph node involvement; absence of distant metastasis (M0) satisfies non-metastatic requirements.

### 4. Recency & Temporal Grounding
* **Failure Mode**: Without status filtering, retrieval frequently pulled completed or terminated trials from 2012–2018. Additionally, criteria with relative washout periods (e.g. *"prior radiation therapy completed at least 4 weeks prior to enrollment"*) produced hallucinated or inconsistent verdicts without an epoch reference point.
* **Production Solution**:
  1. Mandated `filter.overallStatus=RECRUITING` in all API queries to guarantee all evaluated studies are actively enrolling.
  2. Injected dynamic UTC date anchoring (`Today's date is YYYY-MM-DD`) into the verification prompt, giving the model an immutable reference point to evaluate time windows against dates in the clinical narrative.

---

## Baseline vs. Hardened Production Comparison

| Dimension | Baseline Prototype | Hardened Production System (v1.3.0) |
|---|---|---|
| **Authentication & History** | None (ephemeral anonymous sessions) | **Supabase Auth (ES256/RS256 JWT), user-isolated history, cascade deletion** |
| **Biomarker Prioritization** | Naive condition query (unrelated driver trials) | **Biomarker-aware API queries, stage pre-filtering, temperature=0.0 determinism** |
| **Document Ingestion** | None (manual profile typing only) | **Client-side PDF, DOCX, TXT parser (up to 15MB, 100% private)** |
| **Clinical Dossier Export** | None | **Tumor-board ready multi-page PDF export with pagination logic** |
| **Cold-Start Handling** | Silent failure / ~50s unannounced freeze | **Background pre-warming ping + live header status badge** |
| **Loading Experience** | Static 12-second text | **4-stage rotating progress bar + elapsed timer + 30–50s notice** |
| **Primary LLM Provider** | Groq (`openai/gpt-oss-120b`) / Gemini 2.5 Flash | **Google Gemini (`gemini-3.5-flash-lite`)** |
| **Token Budget (TPM)** | 8,000 TPM (frequent pre-allocation 429s) | **250,000 TPM** (zero pre-allocation drops) |
| **Daily Request Quotas (RPD)** | 20 RPD (Gemini 2.5 Flash lockout) | **500 RPD** (supports sustained continuous evaluation) |
| **Outbound LLM Pacing** | None (burst calls exhausted quotas) | **14 RPM global cap + 2.0s inter-trial cooldown** |
| **Criteria Evaluated / Trial** | Restrictive cap at 5 criteria | **Up to 20 criteria per study in a single pass** |
| **Retrieval Recall on Dense EHR** | ~0% (query over-constrained by pathology text) | **100%** (Planner sanitization + 3-tier auto-relaxation + 400 fallback) |
| **Medical Reasoning** | Syntactic literalism (false negatives on staging) | **Domain equivalence axioms (histology, TNM, stage bounds)** |
| **Protocol Status Filtering** | Unfiltered (returned completed/closed studies) | **Strict `filter.overallStatus=RECRUITING`** |
| **Citation Verification** | Vulnerable to escaped markdown (`\<`, `\<=`) | **Verbatim substring check with markdown unescaping** |
| **Monthly Infrastructure Cost** | $0.00 | **$0.00 (Render + Vercel + Google AI Studio Free Tier)** |

---

## Tech Stack

| Layer | Technologies | Role & Purpose |
|---|---|---|
| **Frontend Framework** | [Next.js 14](https://nextjs.org/) (App Router), React 18 | Client & Server Components, fast hydration, static export |
| **Language & Styling** | TypeScript, [Tailwind CSS](https://tailwindcss.com/) | Strict type safety, clinical design system, responsive badge states |
| **Authentication & DB** | [Supabase](https://supabase.com/) Auth & Postgres | Session tokens, Row Level Security (RLS), history cascade deletion |
| **Document Processing** | `pdfjs-dist` (v3.11), `mammoth` (v1.8) | In-browser parsing for `.pdf`, `.docx`, and `.txt` clinical records |
| **Dossier Generation** | `jspdf` (v4.0), `jspdf-autotable` (v5.0) | Client-side tumor board dossier PDF export with pagination logic |
| **Testing (Frontend)** | Vitest, React Testing Library | 50 passing unit and component tests across 9 suites |
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/), Python 3.11 / 3.12, Uvicorn | Asynchronous high-throughput REST API |
| **Data Validation** | [Pydantic v2](https://docs.pydantic.dev/) | Strict JSON schema definitions and type coercion |
| **LLM Inference** | [Google GenAI SDK](https://github.com/google/generative-ai-python) (`gemini-3.5-flash-lite`) | Native structured JSON generation (250,000 TPM / 500 RPD free tier) |
| **LLM Failover** | Groq SDK (`openai/gpt-oss-120b`) | Automatic fallback provider with rate pacing |
| **Trial Registry** | [ClinicalTrials.gov REST API v2](https://clinicaltrials.gov/data-api/about-api) | Live protocol retrieval with automated relaxation fallbacks |
| **HTTP Client** | [HTTPX](https://www.python-httpx.org/) | Asynchronous connection pooling and query dispatch |
| **Testing (Backend)** | Pytest, Pytest-Asyncio, Ruff | 91 unit tests with offline mock fixtures; strict Ruff linter gating |
| **Hosting & CI/CD** | Vercel, Render, GitHub Actions | Automated GitHub Actions CI for frontend & backend verification |

---

## Local Development Setup

### Prerequisites
* Python 3.11+
* Node.js 18+ and npm
* A free [Google AI Studio API Key](https://aistudio.google.com/) (or [Groq API Key](https://console.groq.com/))

### 1. Clone the Repository

```bash
git clone https://github.com/snhaal/clinical-evidence-navigator.git
cd clinical-evidence-navigator
```

### 2. Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements-dev.txt

# Configure environment variables
cp .env.example .env
```

Edit `backend/.env` with your credentials:

```
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=your_gemini_api_key_here
# Optional fallback:
# GROQ_API_KEY=your_groq_api_key_here
LLM_MAX_REQUESTS_PER_MINUTE=14
MAX_TRIALS_PER_QUERY=3
REQUEST_TIMEOUT_SECONDS=60
```

Start the backend server:

```bash
uvicorn app.main:app --reload --port 8000
```

* Interactive API Documentation: http://localhost:8000/docs
* Health Check: http://localhost:8000/health

### 3. Frontend Setup

```bash
cd ../frontend

# Install dependencies
npm install

# Configure environment variables
cp .env.example .env.local
```

Start the Next.js development server:

```bash
npm run dev
```

Open http://localhost:3000 in your browser.

### 4. Running Tests

#### Backend Test Suite (91 tests)
Run the offline pytest suite covering all pipeline stages, adapters, schema constraints, and rate limiters:

```bash
cd backend
pytest tests/ -v
```
*(91 passed unit tests, running fully offline with mocked external fixtures.)*

#### Frontend Test Suite (50 tests)
Run Vitest covering client-side document parsers, dropzone, loading states, auth provider, history management, and status badges:

```bash
cd frontend
npm run test
```
*(50 passed unit and component tests across 9 suites.)*

### Benchmark Evaluation

The verification pipeline is evaluated against a curated suite of real-world clinical oncology cases (`backend/evals/gold_cases.json`):

```bash
cd backend
python -u -m evals.run_eval --skip-retrieval
```

* **False-Match Rate**: 0.0% (zero dangerous false inclusions; unknown or unmentioned parameters strictly resolve to unclear).
* **Citation Validity**: 100.0% (every verdict is backed by an exact verbatim substring match from the source protocol text).
* **Criterion Agreement**: 79.3% (discrepancies are safe clinical abstentions on ambiguous clinical bounds).

---

## Roadmap & Future Improvements

* [x] **Client-Side Document Ingestion**: In-browser parsing of `.pdf`, `.docx`, and `.txt` clinical records (15MB limit) with zero token leakage.
* [x] **Client-Side Match Dossier Export**: Downloadable, professional multi-page PDF summaries for oncology multidisciplinary tumor boards.
* [x] **Cold-Start Resilience**: Proactive backend pre-warming ping and header status badge for serverless/free-tier hosting.
* [x] **Supabase Authentication & History**: Multi-tenant session tokens, user-isolated search logs, and cascade history deletion.
* [x] **Biomarker-Aware Registry Search**: Precision targeting for driver mutations (EGFR, HER2, KRAS) with zero-temperature determinism.
* [ ] **Semantic Vector Search**: Integrate pgvector embeddings for criteria-level cosine similarity to complement keyword retrieval.
* [ ] **Cross-Trial Criterion Deduplication**: Cluster recurring baseline eligibility criteria (e.g. ECOG scores, organ function lab cutoffs) across multi-center trials to optimize LLM token usage.
* [ ] **FHIR / USCDI Ingestion**: Direct ingestion of FHIR R4 Patient and Condition resources from sandbox EHR systems.

---

## Safety & Scope Disclaimer

**IMPORTANT DISCLAIMER**: This application is developed for technical demonstration and research exploration purposes. It is not a medical device, has not undergone clinical validation, and is not a substitute for professional clinical judgment, diagnosis, or treatment planning. All demo profiles use synthetic or anonymized clinical data. Real-world trial enrollment decisions must always be made by licensed healthcare professionals in consultation with patients and trial investigators.

---

## License & Attribution

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

If you build upon, upgrade, or reference this architecture in your work, please preserve original copyright attribution:

```bibtex
@software{clinical_evidence_navigator_2026,
  author = {snhaal},
  title = {Clinical Evidence Navigator: Agentic RAG for Clinical Trial Eligibility Verification},
  year = {2026},
  url = {https://github.com/snhaal/clinical-evidence-navigator}
}
```
