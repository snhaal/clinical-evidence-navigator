"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ExportDossierButton } from "@/components/ExportDossierButton";
import { TrialCard } from "@/components/TrialCard";
import { VerdictBadge } from "@/components/VerdictBadge";
import { fetchHistory, fetchHistoryDetail } from "@/lib/api";
import type {
  DossierData,
  HistoryDetailResponse,
  HistoryItem,
  Verdict,
} from "@/lib/types";

export default function HistoryPage() {
  const { user, isLoading: isAuthLoading } = useAuth();

  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detailData, setDetailData] = useState<HistoryDetailResponse | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

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
  }, [user]);

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

  const router = useRouter();

  // Route protection: If unauthenticated, immediately redirect to /login
  useEffect(() => {
    if (!isAuthLoading && !user) {
      router.replace("/login");
    }
  }, [isAuthLoading, user, router]);

  if (isAuthLoading || !user) {
    return (
      <main className="min-h-screen bg-bg flex items-center justify-center">
        <div className="text-sm text-muted animate-pulse font-mono">
          Redirecting to sign in…
        </div>
      </main>
    );
  }

  // 2. Authenticated user view
  return (
    <main className="min-h-screen bg-bg px-4 py-12">
      <div className="mx-auto max-w-reading">
        {selectedRunId ? (
          // Detail View
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
          // List View
          <div>
            <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2 border-b border-border pb-4 mb-6">
              <div>
                <h1 className="font-serif text-3xl font-semibold text-ink">
                  Match History
                </h1>
                <p className="text-sm text-muted mt-1">
                  Previous trial evaluations associated with your account.
                </p>
              </div>
              <span className="font-mono text-xs text-muted">
                {total} record{total === 1 ? "" : "s"}
              </span>
            </div>

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
              <div className="space-y-3">
                {items.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => handleSelectRun(item.id)}
                    className="group cursor-pointer rounded-sm border border-border bg-surface p-4 transition-all hover:border-accent/40 hover:shadow-xs"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
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
                          {item.nct_id && (
                            <span className="font-mono text-xs text-muted/60">
                              · {item.nct_id}
                            </span>
                          )}
                        </div>
                        <h2 className="font-serif text-lg font-semibold text-ink group-hover:text-accent transition-colors mt-1">
                          {item.condition}
                        </h2>
                        {item.trial_title && (
                          <p className="text-sm text-muted line-clamp-1 mt-0.5">
                            {item.trial_title}
                          </p>
                        )}
                      </div>

                      <div className="shrink-0 flex items-center gap-3">
                        {item.status && (
                          <VerdictBadge verdict={item.status as Verdict} />
                        )}
                        <span className="text-sm text-accent opacity-0 group-hover:opacity-100 transition-opacity hidden sm:inline">
                          View details →
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
