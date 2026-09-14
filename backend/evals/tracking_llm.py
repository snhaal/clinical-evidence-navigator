"""
Re-exported from app.adapters.tracking, which is now the shared
implementation used by both the eval harness and the production /match
route (app/api/routes.py populates match_runs.latency_ms / token_cost
using the same class). Kept as a separate import path here so existing
`from evals.tracking_llm import TrackingLLMAdapter` usage doesn't break.
"""

from app.adapters.tracking import CallRecord, TrackingLLMAdapter

__all__ = ["CallRecord", "TrackingLLMAdapter"]
