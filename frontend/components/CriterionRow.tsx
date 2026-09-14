import type { CriterionVerdict } from "@/lib/types";
import { VerdictBadge } from "./VerdictBadge";

export function CriterionRow({ criterion }: { criterion: CriterionVerdict }) {
  return (
    <li className="border-b border-border py-4 last:border-b-0">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted">
          {criterion.criterion_type === "inclusion" ? "Inclusion" : "Exclusion"} criterion
        </p>
        <VerdictBadge verdict={criterion.verdict} />
      </div>
      <blockquote className="mt-2 border-l-2 border-accent-soft pl-3 font-mono text-sm leading-relaxed text-ink">
        &ldquo;{criterion.cited_text}&rdquo;
      </blockquote>
      <p className="mt-2 text-sm leading-relaxed text-muted">{criterion.rationale}</p>
      {!criterion.citation_validated && (
        <p className="mt-1 text-xs text-unclear">
          The model&apos;s original citation couldn&apos;t be verified against the source text, so this
          verdict was set to unclear rather than shown as a match.
        </p>
      )}
    </li>
  );
}
