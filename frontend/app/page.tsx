"use client";

import { useState } from "react";
import { Disclaimer } from "@/components/Disclaimer";
import { ProfileForm } from "@/components/ProfileForm";
import { TrialCard } from "@/components/TrialCard";
import { ApiError, matchPatientProfile } from "@/lib/api";
import type { MatchResponse } from "@/lib/types";

type ViewState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "result"; data: MatchResponse }
  | { status: "error"; message: string };

export default function Home() {
  const [state, setState] = useState<ViewState>({ status: "idle" });

  async function handleSubmit(profile: string) {
    setState({ status: "submitting" });
    try {
      const data = await matchPatientProfile(profile);
      setState({ status: "result", data });
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Something unexpected went wrong. Please try again.";
      setState({ status: "error", message });
    }
  }

  return (
    <main className="min-h-screen bg-bg">
      <Disclaimer />

      <div className="mx-auto max-w-reading px-4 py-12">
        <h1 className="font-serif text-3xl font-semibold leading-tight text-ink">
          Clinical Evidence Navigator
        </h1>
        <p className="mt-2 text-base leading-relaxed text-muted">
          Paste a patient profile and get a ranked shortlist of clinical trials, with every verdict
          traced to the exact eligibility sentence it&apos;s based on.
        </p>

        <div className="mt-8 rounded-sm border border-border bg-surface p-5">
          <ProfileForm onSubmit={handleSubmit} isSubmitting={state.status === "submitting"} />
        </div>

        {state.status === "submitting" && (
          <p className="mt-6 text-sm text-muted" role="status">
            Extracting a structured query, retrieving candidate trials, and reasoning through each
            eligibility criterion — this can take up to about 12 seconds.
          </p>
        )}

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
            <p className="text-sm text-muted">
              {state.data.trials.length} candidate trial{state.data.trials.length === 1 ? "" : "s"} ·
              {" "}
              {(state.data.latency_ms / 1000).toFixed(1)}s
            </p>
            <ul className="mt-2">
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
