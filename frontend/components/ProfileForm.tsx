"use client";

import { useState } from "react";
import { DocumentDropzone } from "./DocumentDropzone";

export const SAMPLE_PROFILE = `62-year-old male.
Diagnosis: Stage IV Non-Small Cell Lung Cancer (metastatic lung adenocarcinoma, Stage IVB).
Biomarkers: EGFR Exon 19 deletion detected (positive). Secondary resistance biomarker: c-Met amplification confirmed via re-biopsy / NGS. ALK negative, KRAS wild-type, ROS1 negative, PD-L1 TPS 30%. Archived FFPE tumor tissue available for central c-Met IHC testing.
Treatment History: Previously treated with first-line Osimertinib (third-generation EGFR TKI) for 14 months, with documented radiographic disease progression per RECIST v1.1. No prior chemotherapy lines or anti-PD-1 immunotherapy.
Performance Status: ECOG Performance Status 1.
Measurable Disease: Measurable lung lesion measuring 2.8 cm in the right lower lobe per RECIST v1.1.
Laboratory Evaluation:
- Absolute Neutrophil Count (ANC): 3.2 x 10^9/L (>= 1.5 x 10^9/L)
- Platelet count: 210 x 10^9/L (>= 100 x 10^9/L)
- Hemoglobin: 12.6 g/dL (>= 9.0 g/dL)
- Total Bilirubin: 0.8 mg/dL (<= 1.5x ULN)
- AST: 24 U/L, ALT: 28 U/L (<= 2.5x ULN)
- Serum Creatinine: 0.9 mg/dL, CrCl: 84 mL/min (>= 50 mL/min)
Exclusions Absent: Contrast-enhanced brain MRI negative for central nervous system or brain metastases. No active autoimmune disease. No history of interstitial lung disease (ILD) or pneumonitis. Life expectancy > 12 weeks. No other clinically significant medical conditions or co-morbidities that would interfere with trial participation.`;

interface ProfileFormProps {
  onSubmit: (profile: string) => void;
  isSubmitting: boolean;
}

export function ProfileForm({ onSubmit, isSubmitting }: ProfileFormProps) {
  const [profile, setProfile] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (profile.trim().length === 0) return;
    onSubmit(profile.trim());
  }

  return (
    <form onSubmit={handleSubmit}>
      <label htmlFor="patient-profile" className="block font-serif text-lg font-semibold text-ink">
        Describe the patient
      </label>
      <p className="mt-1 text-sm text-muted">
        Include the diagnosis, stage, and any prior treatment or exclusions you know.
      </p>
      <div className="mt-4">
        <DocumentDropzone onExtracted={setProfile} disabled={isSubmitting} />
      </div>
      <textarea
        id="patient-profile"
        value={profile}
        onChange={(e) => setProfile(e.target.value)}
        placeholder={SAMPLE_PROFILE}
        rows={5}
        maxLength={4000}
        disabled={isSubmitting}
        className="mt-3 w-full resize-y rounded-sm border border-border bg-surface p-3 text-sm leading-relaxed text-ink placeholder:text-muted/70 disabled:opacity-60"
      />
      <div className="mt-3 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setProfile(SAMPLE_PROFILE)}
          disabled={isSubmitting}
          className="text-sm text-accent underline decoration-accent-soft underline-offset-4 hover:decoration-accent disabled:opacity-60"
        >
          Use a sample profile
        </button>
        <button
          type="submit"
          disabled={isSubmitting || profile.trim().length === 0}
          className="rounded-sm bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? "Finding trials…" : "Find matching trials"}
        </button>
      </div>
    </form>
  );
}
