"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ExportDossierButton } from "@/components/ExportDossierButton";
import { TrialCard } from "@/components/TrialCard";
import { VerdictBadge } from "@/components/VerdictBadge";
import { deleteHistorySession, fetchHistory, fetchHistoryDetail } from "@/lib/api";
import type {
  DossierData,
  HistoryDetailResponse,
  HistoryItem,
  Verdict,
} from "@/lib/types";

function formatTrialBreakdown(item: HistoryItem): string {
  const trials = item.trials || [];
  if (trials.length === 0) {
    return item.status ? `Status: ${item.status}` : "Evaluated";
  }

  let matches = 0;
  let noMatches = 0;
  let unclears = 0;

  for (const t of trials) {
    if (t.overall_verdict === "match") matches++;
    else if (t.overall_verdict === "no_match") noMatches++;
    else if (t.overall_verdict === "unclear") unclears++;
  }

  const parts: string[] = [];
  if (matches > 0) parts.push(`${matches} Match${matches > 1 ? "es" : ""}`);
  if (noMatches > 0) parts.push(`${noMatches} Excluded`);
  if (unclears > 0) parts.push(`${unclears} Unclear`);

  const summary = parts.length > 0 ? parts.join(", ") : "Evaluated";
  return `${trials.length} trial${trials.length === 1 ? "" : "s"} evaluated · ${summary}`;
}

export default function HistoryPage() {
  const { user, isLoading: isAuthLoading } = useAuth();
  const router = useRouter();

  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  // Detail view state
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detailData, setDetailData] = useState<HistoryDetailResponse | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Grouped session accordion & deletion states
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());
  const [confirmDeleteProfileId, setConfirmDeleteProfileId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    let mounted = true;

    async function loadHistory() {
      setIsLoadingList(true);
      setListError(null);
      try {
        const data = await fetchHistory(50, 0);
        if (!mounted) return;
        setItems(data.items);
        setTotal(data.total);
      } catch (err) {
        if (!mounted) return;
        setListError(
          err instanceof Error ? err.message : "Failed to load history."
        );
      } finally {
        if (mounted) setIsLoadingList(false);
      }
    }

    loadHistory();

    return () => {
      mounted = false;
    };
  }, [user?.id]);

  // Route protection: redirect unauthenticated visitor to /login
  useEffect(() => {
    if (!isAuthLoading && !user) {
      router.replace("/login");
    }
  }, [isAuthLoading, user, router]);

  function toggleSessionExpanded(profileId: string) {
    setExpandedSessions((prev) => {
      const next = new Set(prev);
      if (next.has(profileId)) {
        next.delete(profileId);
      } else {
        next.add(profileId);
      }
      return next;
    });
  }

  async function handleSelectRun(runId: string) {
    setSelectedRunId(runId);
    setDetailData(null);
    setIsLoadingDetail(true);
    setDetailError(null);

    try {
      const data = await fetchHistoryDetail(runId);
      setDetailData(data);
    } catch (err) {
      setDetailError(
        err instanceof Error ? err.message : "Failed to load run details."
      );
    } finally {
      setIsLoadingDetail(false);
    }
  }

  async function handleDelete(profileId: string) {
    const previousItems = [...items];
    const previousTotal = total;

    // Optimistic UI removal
    setItems((prev) =>
      prev.filter((it) => it.id !== profileId && it.patient_profile_id !== profileId)
    );
    setTotal((prev) => Math.max(0, prev - 1));
    setConfirmDeleteProfileId(null);
    setDeleteError(null);
    setIsDeleting(true);

    try {
      await deleteHistorySession(profileId);
    } catch (err) {
      // Rollback on failure
      setItems(previousItems);
      setTotal(previousTotal);
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete evaluation session."
      );
    } finally {
      setIsDeleting(false);
    }
  }

  if (isAuthLoading || !user) {
    return (
      <main className="min-h-screen bg-bg flex items-center justify-center">
        <div className="text-sm text-muted animate-pulse font-mono">
          Redirecting to sign in…
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-bg px-4 py-12">
      <div className="mx-auto max-w-reading">
        {selectedRunId ? (
          // ================= DETAIL VIEW =================
          <div>
            <button
              type="button"
              onClick={() => {
                setSelectedRunId(null);
                setDetailData(null);
                setDetailError(null);
              }}
              className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline mb-6 focus:outline-hidden"
            >
              ← Back to Match History
            </button>

            {isLoadingDetail && (
              <div className="rounded-sm border border-border bg-surface p-8 text-center text-muted">
                Loading trial evaluations…
              </div>
            )}

            {detailError && (
              <div
                role="alert"
                className="rounded-sm border border-nomatch/30 bg-nomatch-soft p-4 text-sm text-nomatch"
              >
                {detailError}
              </div>
            )}

            {detailData && (
              <div className="space-y-6">
                <div className="rounded-sm border border-border bg-surface p-5">
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                    <div>
                      <span className="font-mono text-xs text-muted">
                        {new Date(detailData.created_at).toLocaleDateString(undefined, {
                          year: "numeric",
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                      <h2 className="font-serif text-2xl font-semibold text-ink mt-1">
                        {detailData.structured_query?.condition ?? "Clinical Evaluation"}
                      </h2>
                      {detailData.structured_query?.stage && (
                        <p className="text-sm text-muted mt-0.5">
                          Stage: {detailData.structured_query.stage}
                        </p>
                      )}
                    </div>
                    {detailData.trials.length > 0 && (
                      <ExportDossierButton
                        dossierData={{
                          patient_profile_id: detailData.patient_profile_id,
                          needs_clarification: false,
                          clarifying_question: null,
                          structured_query: detailData.structured_query,
                          trials: detailData.trials,
                          latency_ms: detailData.latency_ms ?? 0,
                          disclaimer: detailData.disclaimer,
                        } as DossierData}
                      />
                    )}
                  </div>

                  <div className="mt-4 border-t border-border pt-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">
                      Patient Clinical Note
                    </h3>
                    <p className="mt-1 text-sm text-ink font-sans leading-relaxed whitespace-pre-wrap bg-bg p-3 rounded-sm border border-border/60">
                      {detailData.patient_profile}
                    </p>
                  </div>
                </div>

                <div>
                  <h3 className="font-serif text-xl font-semibold text-ink mb-2">
                    Evaluated Studies ({detailData.trials.length})
                  </h3>
                  <ul className="rounded-sm border border-border bg-surface px-5 divide-y divide-border">
                    {detailData.trials.map((trial) => (
                      <TrialCard key={trial.nct_id} trial={trial} />
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        ) : (
          // ================= GROUPED LIST VIEW =================
          <div>
            <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2 border-b border-border pb-4 mb-6">
              <div>
                <h1 className="font-serif text-3xl font-semibold text-ink">
                  Match History
                </h1>
                <p className="text-sm text-muted mt-1">
                  Evaluated clinical matching sessions associated with your account.
                </p>
              </div>
              <span className="font-mono text-xs text-muted">
                {total} evaluation{total === 1 ? "" : "s"}
              </span>
            </div>

            {deleteError && (
              <div
                role="alert"
                className="rounded-sm border border-nomatch/30 bg-nomatch-soft p-4 text-sm text-nomatch mb-4"
              >
                {deleteError}
              </div>
            )}

            {isLoadingList && (
              <div className="rounded-sm border border-border bg-surface p-8 text-center text-muted">
                Loading history…
              </div>
            )}

            {listError && (
              <div
                role="alert"
                className="rounded-sm border border-nomatch/30 bg-nomatch-soft p-4 text-sm text-nomatch"
              >
                {listError}
              </div>
            )}

            {!isLoadingList && !listError && items.length === 0 && (
              <div className="rounded-sm border border-border bg-surface p-8 text-center">
                <p className="text-sm text-muted">
                  No previous match evaluations recorded yet.
                </p>
                <Link
                  href="/"
                  className="mt-4 inline-block rounded-sm bg-accent px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent/90"
                >
                  Start New Match
                </Link>
              </div>
            )}

            {!isLoadingList && items.length > 0 && (
              <div className="space-y-4">
                {items.map((item) => {
                  const profileId = item.patient_profile_id || item.id;
                  const isExpanded = expandedSessions.has(profileId);
                  const trials = item.trials || [];
                  const defaultRunId = trials[0]?.match_run_id || item.id;

                  return (
                    <div
                      key={profileId}
                      className="rounded-sm border border-border bg-surface transition-all hover:border-accent/40 hover:shadow-xs"
                    >
                      {/* Card Header / Summary */}
                      <div className="p-5">
                        <div className="flex items-start justify-between gap-4">
                          <div className="space-y-1.5 flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-xs text-muted">
                                {new Date(item.created_at).toLocaleDateString(undefined, {
                                  year: "numeric",
                                  month: "short",
                                  day: "numeric",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })}
                              </span>
                              {item.stage && (
                                <span className="inline-flex items-center px-2 py-0.5 rounded-xs text-xs font-mono bg-bg text-muted border border-border">
                                  {item.stage}
                                </span>
                              )}
                            </div>

                            <h2 className="font-serif text-xl font-semibold text-ink">
                              {item.condition}
                            </h2>

                            {/* Biomarker Pill Tags */}
                            {item.biomarkers && item.biomarkers.length > 0 && (
                              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                                {item.biomarkers.map((bm, i) => (
                                  <span
                                    key={i}
                                    className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-mono bg-accent/10 text-accent border border-accent/20"
                                  >
                                    {bm}
                                  </span>
                                ))}
                              </div>
                            )}

                            {/* Match Breakdown Summary */}
                            <p className="text-xs font-medium text-muted pt-1">
                              {formatTrialBreakdown(item)}
                            </p>
                          </div>

                          {/* Action Buttons: Delete & Full Dossier */}
                          <div className="shrink-0 flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteProfileId(profileId)}
                              title="Delete this evaluation session"
                              aria-label={`Delete evaluation for ${item.condition}`}
                              className="p-1.5 text-muted hover:text-nomatch hover:bg-nomatch-soft/60 rounded-xs transition-colors focus:outline-hidden"
                            >
                              <svg
                                xmlns="http://www.w3.org/2000/svg"
                                width="15"
                                height="15"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                aria-hidden="true"
                              >
                                <path d="M3 6h18" />
                                <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                                <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                                <line x1="10" y1="11" x2="10" y2="17" />
                                <line x1="14" y1="11" x2="14" y2="17" />
                              </svg>
                            </button>

                            <button
                              type="button"
                              onClick={() => handleSelectRun(defaultRunId)}
                              className="rounded-sm bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent hover:bg-accent/20 transition-colors focus:outline-hidden"
                            >
                              Full Dossier →
                            </button>
                          </div>
                        </div>

                        {/* Accordion Toggle */}
                        {trials.length > 0 && (
                          <div className="mt-4 pt-3 border-t border-border flex items-center justify-between">
                            <button
                              type="button"
                              onClick={() => toggleSessionExpanded(profileId)}
                              aria-expanded={isExpanded}
                              className="text-xs font-medium text-muted hover:text-ink inline-flex items-center gap-1.5 focus:outline-hidden transition-colors"
                            >
                              <span>
                                {isExpanded
                                  ? "Hide evaluated trials"
                                  : `View ${trials.length} evaluated trial${trials.length === 1 ? "" : "s"}`}
                              </span>
                              <span className="text-[10px]">{isExpanded ? "▲" : "▼"}</span>
                            </button>

                            <span className="font-mono text-[11px] text-muted/70">
                              Session ID: {profileId.slice(0, 8)}…
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Expanded Sibling Trials List */}
                      {isExpanded && trials.length > 0 && (
                        <div className="border-t border-border bg-bg/50 px-5 py-3 divide-y divide-border/60">
                          {trials.map((trial) => (
                            <div
                              key={trial.match_run_id}
                              className="py-3 first:pt-1 last:pb-1 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                            >
                              <div className="space-y-1">
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-xs text-muted font-medium">
                                    {trial.nct_id}
                                  </span>
                                  {trial.hard_exclusion_hit && (
                                    <span className="px-1.5 py-0.5 rounded-xs text-[10px] font-mono bg-nomatch-soft text-nomatch border border-nomatch/20">
                                      Hard Exclusion
                                    </span>
                                  )}
                                  {trial.satisfied_count > 0 && (
                                    <span className="font-mono text-[11px] text-muted">
                                      {trial.satisfied_count} satisfied
                                    </span>
                                  )}
                                </div>
                                <h3 className="text-sm font-semibold text-ink line-clamp-1">
                                  {trial.trial_title}
                                </h3>
                              </div>

                              <div className="shrink-0 flex items-center gap-3">
                                <VerdictBadge
                                  verdict={trial.overall_verdict as Verdict}
                                  matchTier={trial.match_tier}
                                  unclearCount={trial.unclear_count}
                                />
                                <button
                                  type="button"
                                  onClick={() => handleSelectRun(trial.match_run_id)}
                                  className="text-xs text-accent hover:underline focus:outline-hidden"
                                >
                                  Details →
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Delete Confirmation Modal */}
        {confirmDeleteProfileId && (
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-delete-title"
            className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-xs"
          >
            <div className="w-full max-w-md rounded-md border border-border bg-surface p-6 shadow-lg">
              <h2 id="modal-delete-title" className="font-serif text-xl font-semibold text-ink">
                Delete Evaluation Session?
              </h2>
              <p className="mt-2 text-sm text-muted">
                Are you sure you want to delete this clinical evaluation session and all associated trial match records? This action cannot be undone.
              </p>
              <div className="mt-6 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setConfirmDeleteProfileId(null)}
                  disabled={isDeleting}
                  className="rounded-sm border border-border bg-surface px-3.5 py-1.5 text-xs font-medium text-ink hover:bg-bg focus:outline-hidden disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(confirmDeleteProfileId)}
                  disabled={isDeleting}
                  className="rounded-sm bg-nomatch px-3.5 py-1.5 text-xs font-medium text-surface hover:bg-nomatch/90 focus:outline-hidden disabled:opacity-50"
                >
                  {isDeleting ? "Deleting…" : "Delete Session"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
