import type { Verdict } from "@/lib/types";

interface VerdictBadgeProps {
  verdict: Verdict;
  matchTier?: string | null;
  unclearCount?: number;
}

export function VerdictBadge({ verdict, matchTier, unclearCount }: VerdictBadgeProps) {
  let effectiveTier: string = matchTier || verdict;
  if (verdict === "match" && (!matchTier || matchTier === "candidate_match") && unclearCount && unclearCount > 0) {
    effectiveTier = "candidate_match";
  }

  let label = "Eligible Match";
  let classes = "bg-match-soft text-match border border-match/20";

  switch (effectiveTier) {
    case "candidate_match":
    case "likely_match":
      label = "Candidate Match";
      classes = "bg-match-soft text-match border border-match/20";
      break;
    case "eligible":
    case "match":
      label = "Eligible Match";
      classes = "bg-match-soft text-match border border-match/20";
      break;
    case "no_match":
      label = "No match";
      classes = "bg-nomatch-soft text-nomatch border border-nomatch/20";
      break;
    case "unclear":
    default:
      label = "Unclear";
      classes = "bg-unclear-soft text-unclear border border-unclear/20";
      break;
  }

  return (
    <span
      className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs sm:text-sm font-medium ${classes}`}
    >
      {label}
    </span>
  );
}
