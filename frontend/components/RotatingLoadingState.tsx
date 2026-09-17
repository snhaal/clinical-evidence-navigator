"use client";

import { useEffect, useState } from "react";

export const MATCH_STAGES = [
  {
    threshold: 0,
    text: "Synthesizing patient profile & extracting search parameters...",
  },
  {
    threshold: 8,
    text: "Querying ClinicalTrials.gov registry for candidate protocols...",
  },
  {
    threshold: 18,
    text: "Analyzing inclusion & exclusion criteria with Gemini Flash-Lite...",
  },
  {
    threshold: 32,
    text: "Synthesizing clinical rationales and compiling evidence citations...",
  },
];

export function RotatingLoadingState() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Determine the active pipeline stage based on elapsed seconds
  let activeIndex = 0;
  for (let i = MATCH_STAGES.length - 1; i >= 0; i--) {
    if (elapsed >= MATCH_STAGES[i].threshold) {
      activeIndex = i;
      break;
    }
  }

  const currentStage = MATCH_STAGES[activeIndex];

  return (
    <div
      className="mt-6 rounded-sm border border-border bg-surface p-4 text-sm shadow-sm"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        {/* Animated spinner */}
        <div className="pt-0.5">
          <svg
            className="h-5 w-5 animate-spin text-accent"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="font-medium text-ink transition-opacity duration-300">
              {currentStage.text}
            </p>
            <span className="text-xs font-mono text-muted">
              {elapsed}s elapsed
            </span>
          </div>

          <p className="mt-1 text-xs text-muted">
            In-depth multi-trial criterion verification typically takes 30–50 seconds.
          </p>

          {/* 4-step progress visualizer */}
          <div className="mt-3 flex gap-1.5" aria-hidden="true">
            {MATCH_STAGES.map((stage, idx) => {
              const isDone = idx < activeIndex;
              const isCurrent = idx === activeIndex;
              return (
                <div
                  key={stage.threshold}
                  className={`h-1.5 flex-1 rounded-full transition-all duration-500 ${
                    isDone
                      ? "bg-accent"
                      : isCurrent
                      ? "animate-pulse bg-accent"
                      : "bg-border"
                  }`}
                />
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
