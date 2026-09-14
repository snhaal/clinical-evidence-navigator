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
}

export interface CriterionVerdict {
  nct_id: string;
  criterion_type: "inclusion" | "exclusion";
  criterion_index: number;
  verdict: Verdict;
  rationale: string;
  cited_text: string;
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

export interface ApiErrorShape {
  detail: string;
}
