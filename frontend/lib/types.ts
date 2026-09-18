// Mirrors app/api/schemas.py and app/pipeline/schemas.py on the backend.
// Kept as a single source of truth for the frontend's view of the API shape.

export type Verdict = "match" | "no_match" | "unclear";

export interface StructuredQuery {
  condition: string;
  stage: string | null;
  prior_therapy: string[];
  exclusions: string[];
  biomarkers: string[];
  status_filter: string;
  age?: number | null;
  sex?: string | null;
}

export interface CriterionVerdict {
  nct_id: string;
  criterion_type: "inclusion" | "exclusion";
  criterion_index: number;
  verdict: Verdict;
  rationale: string;
  cited_text: string;
  evidence_quote?: string | null;
  citation_validated: boolean;
}

export interface TrialMatchSummary {
  nct_id: string;
  title: string;
  overall_verdict: Verdict;
  satisfied_count: number;
  unclear_count: number;
  hard_exclusion_hit: boolean;
  criterion_verdicts: CriterionVerdict[];
  phase?: string[] | string;
  status?: string;
}

export interface MatchResponse {
  patient_profile_id: string;
  needs_clarification: boolean;
  clarifying_question: string | null;
  structured_query: StructuredQuery | null;
  trials: TrialMatchSummary[];
  latency_ms: number;
  disclaimer: string;
}

export type DossierData = MatchResponse;

export interface HistoryTrialSummary {
  match_run_id: string;
  nct_id: string;
  trial_title: string;
  overall_verdict: Verdict;
  satisfied_count: number;
  unclear_count: number;
  hard_exclusion_hit: boolean;
  criterion_verdicts?: CriterionVerdict[];
}

export interface HistoryItem {
  id: string;
  patient_profile_id?: string;
  created_at: string;
  condition: string;
  biomarkers?: string[];
  stage?: string | null;
  patient_profile?: string | null;
  trials?: HistoryTrialSummary[];

  // Backwards compatibility fields
  trial_title?: string | null;
  nct_id?: string | null;
  top_trials: string[];
  status: string;
  overall_verdict?: string | null;
}

export interface HistoryListResponse {
  items: HistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface HistoryDetailResponse {
  id: string;
  patient_profile_id: string;
  created_at: string;
  patient_profile: string;
  structured_query: StructuredQuery | null;
  nct_id: string;
  trial_title: string;
  overall_verdict: Verdict;
  satisfied_count: number;
  unclear_count: number;
  hard_exclusion_hit: boolean;
  latency_ms?: number | null;
  token_cost?: number | null;
  criterion_verdicts: CriterionVerdict[];
  trials: TrialMatchSummary[];
  disclaimer: string;
}

export interface ApiErrorShape {
  detail: string;
}
