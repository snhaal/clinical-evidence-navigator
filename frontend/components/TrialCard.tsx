"use client";

import { useState } from "react";
import type { TrialMatchSummary } from "@/lib/types";
import { CriterionRow } from "./CriterionRow";
import { VerdictBadge } from "./VerdictBadge";

export function TrialCard({ trial }: { trial: TrialMatchSummary }) {
  const [expanded, setExpanded] = useState(false);
  const totalCriteria = trial.criterion_verdicts.length;

  return (
    <li className="border-b border-border py-6 last:border-b-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        className="flex w-full items-start justify-between gap-4 text-left"
      >
        <div>
          <p className="font-mono text-xs text-muted">{trial.nct_id}</p>
          <h3 className="mt-1 font-serif text-lg font-semibold leading-snug text-ink">{trial.title}</h3>
          <p className="mt-1 text-sm text-muted">
            {trial.satisfied_count} of {totalCriteria} criteria satisfied
            {trial.unclear_count > 0 && ` · ${trial.unclear_count} unclear`}
            {trial.hard_exclusion_hit && " · excluded on a hard criterion"}
          </p>
        </div>
        <VerdictBadge verdict={trial.overall_verdict} />
      </button>

      {expanded && (
        <div className="mt-4">
          <a
            href={`https://clinicaltrials.gov/study/${trial.nct_id}`}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-accent underline decoration-accent-soft underline-offset-4 hover:decoration-accent"
          >
            View the live trial record on ClinicalTrials.gov
          </a>
          <ul className="mt-3">
            {trial.criterion_verdicts.map((criterion) => (
              <CriterionRow
                key={`${criterion.criterion_type}-${criterion.criterion_index}`}
                criterion={criterion}
              />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}
