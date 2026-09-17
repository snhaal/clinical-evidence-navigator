"use client";

import { useState } from "react";
import type { DossierData } from "@/lib/types";

interface ExportDossierButtonProps {
  dossierData: DossierData;
  className?: string;
}

export function ExportDossierButton({
  dossierData,
  className = "",
}: ExportDossierButtonProps) {
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleExport() {
    if (isGenerating) return;

    setIsGenerating(true);
    setError(null);

    try {
      // Dynamic in-function import ensures jspdf & jspdf-autotable are completely
      // excluded from initial SSR and bundle payload until user explicitly triggers export
      const { generateClinicalDossier } = await import("@/lib/exportDossierPdf");
      await generateClinicalDossier(dossierData);
    } catch (err) {
      console.error("Clinical Dossier PDF generation failed:", err);
      const msg =
        err instanceof Error
          ? err.message
          : "Failed to generate PDF dossier. Please try again.";
      setError(msg);
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <div className="inline-flex flex-col items-end">
      <button
        type="button"
        onClick={handleExport}
        disabled={isGenerating}
        aria-busy={isGenerating}
        aria-label="Export match results as clinical PDF dossier"
        className={`inline-flex items-center gap-1.5 rounded-sm border border-accent/40 bg-surface px-3 py-1 text-sm font-medium text-accent shadow-xs transition-colors hover:bg-accent-soft/50 focus:outline-hidden focus:ring-1 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      >
        {isGenerating ? (
          <>
            <svg
              className="h-4 w-4 animate-spin text-accent"
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
                d="M4 12a8 8 0 018-8v8H4z"
              />
            </svg>
            <span>Compiling PDF…</span>
          </>
        ) : (
          <>
            <svg
              className="h-4 w-4 text-accent"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.75}
                d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h7a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"
              />
            </svg>
            <span>Export Dossier (PDF)</span>
          </>
        )}
      </button>

      {error && (
        <p
          role="alert"
          className="mt-1 text-xs text-nomatch"
        >
          {error}
        </p>
      )}
    </div>
  );
}

export default ExportDossierButton;
