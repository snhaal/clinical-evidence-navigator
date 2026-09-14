import type { Verdict } from "@/lib/types";

const VERDICT_STYLES: Record<Verdict, { label: string; classes: string }> = {
  match: { label: "Match", classes: "bg-match-soft text-match" },
  no_match: { label: "No match", classes: "bg-nomatch-soft text-nomatch" },
  unclear: { label: "Unclear", classes: "bg-unclear-soft text-unclear" },
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const style = VERDICT_STYLES[verdict];
  return (
    <span className={`inline-flex items-center rounded-sm px-2 py-0.5 text-sm font-medium ${style.classes}`}>
      {style.label}
    </span>
  );
}
