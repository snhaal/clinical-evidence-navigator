"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { BackendStatusBadge } from "@/components/BackendStatusBadge";
import { Disclaimer } from "@/components/Disclaimer";
import { ExportDossierButton } from "@/components/ExportDossierButton";
import { ProfileForm } from "@/components/ProfileForm";
import { RotatingLoadingState } from "@/components/RotatingLoadingState";
import { TrialCard } from "@/components/TrialCard";
import { ApiError, type BackendStatus, matchPatientProfile, pingBackend } from "@/lib/api";
import type { MatchResponse } from "@/lib/types";

type ViewState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "result"; data: MatchResponse }
  | { status: "error"; message: string };

export default function Home() {
  const { user, isGuest, isLoading: isAuthLoading } = useAuth();
  const router = useRouter();

  const [state, setState] = useState<ViewState>({ status: "idle" });
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("connecting");

  // Route protection: First-time unauthenticated visitors are redirected to /login
  useEffect(() => {
    if (!isAuthLoading && !user && !isGuest) {
      router.replace("/login");
    }
  }, [isAuthLoading, user, isGuest, router]);

  const checkBackendStatus = useCallback(async () => {
    setBackendStatus("connecting");
    const isOnline = await pingBackend();
    setBackendStatus(isOnline ? "ready" : "error");
  }, []);

  // Pre-warm the backend on initial page mount to mitigate Render cold starts
  useEffect(() => {
    checkBackendStatus();
  }, [checkBackendStatus]);

  async function handleSubmit(profile: string) {
    setState({ status: "submitting" });
    try {
      const data = await matchPatientProfile(profile);
      setState({ status: "result", data });
      // If the match call succeeded, backend is confirmed active
      setBackendStatus("ready");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Something unexpected went wrong. Please try again.";
      setState({ status: "error", message });
    }
  }

  if (isAuthLoading || (!user && !isGuest)) {
    return (
      <main className="min-h-screen bg-bg flex items-center justify-center">
        <div className="text-sm text-muted animate-pulse font-mono">
          Verifying access credentials…
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-bg">
      <Disclaimer />

      <div className="mx-auto max-w-reading px-4 py-12">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="font-serif text-3xl font-semibold leading-tight text-ink">
              Clinical Evidence Navigator
            </h1>
            <p className="mt-2 text-base leading-relaxed text-muted">
              Paste a patient profile and get a ranked shortlist of clinical trials, with every verdict
              traced to the exact eligibility sentence it&apos;s based on.
            </p>
          </div>
          <div className="shrink-0 self-start sm:pt-1">
            <BackendStatusBadge status={backendStatus} onRetry={checkBackendStatus} />
          </div>
        </div>

        <div className="mt-8 rounded-sm border border-border bg-surface p-5">
          <ProfileForm onSubmit={handleSubmit} isSubmitting={state.status === "submitting"} />
        </div>

        {state.status === "submitting" && <RotatingLoadingState />}

        {state.status === "error" && (
          <div className="mt-6 rounded-sm border border-nomatch/30 bg-nomatch-soft p-4">
            <p className="text-sm font-medium text-nomatch">Couldn&apos;t complete that request</p>
            <p className="mt-1 text-sm text-ink">{state.message}</p>
          </div>
        )}

        {state.status === "result" && state.data.needs_clarification && (
          <div className="mt-6 rounded-sm border border-unclear/30 bg-unclear-soft p-4">
            <p className="text-sm font-medium text-unclear">One more detail needed</p>
            <p className="mt-1 text-sm text-ink">{state.data.clarifying_question}</p>
          </div>
        )}

        {state.status === "result" && !state.data.needs_clarification && state.data.trials.length === 0 && (
          <div className="mt-6 rounded-sm border border-border bg-surface p-4">
            <p className="text-sm text-ink">
              No candidate trials were found on ClinicalTrials.gov for this profile. Try adding more
              detail about the condition, or broadening the description.
            </p>
          </div>
        )}

        {state.status === "result" && !state.data.needs_clarification && state.data.trials.length > 0 && (
          <div className="mt-8">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-sm text-muted">
                {state.data.trials.length} candidate trial{state.data.trials.length === 1 ? "" : "s"} ·
                {" "}
                {(state.data.latency_ms / 1000).toFixed(1)}s
              </p>
              <ExportDossierButton dossierData={state.data} />
            </div>
            <ul className="mt-3">
              {state.data.trials.map((trial) => (
                <TrialCard key={trial.nct_id} trial={trial} />
              ))}
            </ul>
          </div>
        )}
      </div>
    </main>
  );
}
