"use client";

import { useState } from "react";
import { DocumentDropzone } from "./DocumentDropzone";

const SAMPLE_PROFILE =
  "64-year-old female, Stage III esophageal squamous cell carcinoma, completed neoadjuvant " +
  "chemoradiation, no distant metastasis.";

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
