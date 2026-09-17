"use client";

import React from "react";
import type { BackendStatus } from "@/lib/api";

interface BackendStatusBadgeProps {
  status: BackendStatus;
  onRetry?: () => void;
}

export function BackendStatusBadge({ status, onRetry }: BackendStatusBadgeProps) {
  if (status === "connecting") {
    return (
      <div
        className="inline-flex items-center gap-2 rounded-full border border-unclear/30 bg-unclear-soft px-3 py-1 text-xs font-medium text-unclear shadow-sm transition-all"
        role="status"
        aria-label="Backend status: waking up"
      >
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-unclear opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-unclear" />
        </span>
        <span>Waking up backend (~30–50s cold start)...</span>
      </div>
    );
  }

  if (status === "ready") {
    return (
      <div
        className="inline-flex items-center gap-2 rounded-full border border-match/30 bg-match-soft px-3 py-1 text-xs font-medium text-match shadow-sm transition-all"
        role="status"
        aria-label="Backend status: active"
      >
        <span className="inline-flex h-2 w-2 rounded-full bg-match" />
        <span>Backend Active</span>
      </div>
    );
  }

  return (
    <div
      className="inline-flex items-center gap-2 rounded-full border border-nomatch/30 bg-nomatch-soft px-3 py-1 text-xs font-medium text-nomatch shadow-sm transition-all"
      role="status"
      aria-label="Backend status: unavailable"
    >
      <span className="inline-flex h-2 w-2 rounded-full bg-nomatch" />
      <span>Backend Unavailable</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="ml-1 rounded px-1.5 py-0.5 font-semibold text-nomatch underline transition hover:bg-nomatch/10 focus:outline-none focus:ring-1 focus:ring-nomatch"
          aria-label="Retry connecting to backend"
        >
          Retry
        </button>
      )}
    </div>
  );
}
