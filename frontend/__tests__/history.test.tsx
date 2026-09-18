import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import HistoryPage from "../app/history/page";
import * as api from "@/lib/api";

const mockFetchHistory = vi.fn();
const mockFetchHistoryDetail = vi.fn();
const mockDeleteHistorySession = vi.fn();

vi.mock("@/lib/api", () => ({
  fetchHistory: (...args: any[]) => mockFetchHistory(...args),
  fetchHistoryDetail: (...args: any[]) => mockFetchHistoryDetail(...args),
  deleteHistorySession: (...args: any[]) => mockDeleteHistorySession(...args),
}));

const mockReplace = vi.fn();
const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
  }),
}));

const mockUser = { id: "user-123", email: "user@example.com" };

vi.mock("@/components/AuthProvider", () => ({
  useAuth: () => ({
    user: mockUser,
    isLoading: false,
    isGuest: false,
  }),
}));

vi.mock("@/components/VerdictBadge", () => ({
  VerdictBadge: ({ verdict }: { verdict: string }) => (
    <span data-testid="verdict-badge">{verdict}</span>
  ),
}));

vi.mock("@/components/ExportDossierButton", () => ({
  ExportDossierButton: () => <button>Export Dossier</button>,
}));

vi.mock("@/components/TrialCard", () => ({
  TrialCard: ({ trial }: { trial: any }) => (
    <div data-testid="trial-card">{trial.title}</div>
  ),
}));

const mockSessionItems = [
  {
    id: "profile-1",
    patient_profile_id: "profile-1",
    created_at: new Date().toISOString(),
    condition: "Non-Small Cell Lung Cancer",
    stage: "Stage IV",
    biomarkers: ["EGFR L858R", "T790M"],
    patient_profile: "Patient with metastatic NSCLC",
    top_trials: ["NCT01234567 - Osimertinib Study"],
    status: "evaluated",
    trials: [
      {
        match_run_id: "run-101",
        nct_id: "NCT01234567",
        trial_title: "Osimertinib Study",
        overall_verdict: "match" as const,
        satisfied_count: 4,
        unclear_count: 0,
        hard_exclusion_hit: false,
      },
      {
        match_run_id: "run-102",
        nct_id: "NCT07654321",
        trial_title: "Sotorasib Study",
        overall_verdict: "no_match" as const,
        satisfied_count: 1,
        unclear_count: 0,
        hard_exclusion_hit: true,
      },
    ],
  },
];

describe("HistoryPage Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders grouped session cards with biomarkers and match summary breakdown", async () => {
    mockFetchHistory.mockResolvedValue({
      items: mockSessionItems,
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<HistoryPage />);

    expect(
      await screen.findByText("Non-Small Cell Lung Cancer", {}, { timeout: 3000 })
    ).toBeInTheDocument();
    expect(screen.getByText("Stage IV")).toBeInTheDocument();
    expect(screen.getByText("EGFR L858R")).toBeInTheDocument();
    expect(screen.getByText("T790M")).toBeInTheDocument();

    // 2 trials evaluated · 1 Match, 1 Excluded
    expect(
      screen.getByText(/2 trials evaluated · 1 Match, 1 Excluded/i)
    ).toBeInTheDocument();
  });

  it("expands and collapses sibling trials accordion", async () => {
    const user = userEvent.setup();
    mockFetchHistory.mockResolvedValue({
      items: mockSessionItems,
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<HistoryPage />);

    expect(
      await screen.findByText("Non-Small Cell Lung Cancer", {}, { timeout: 3000 })
    ).toBeInTheDocument();
    expect(screen.queryByText("Osimertinib Study")).not.toBeInTheDocument();

    const accordionBtn = screen.getByRole("button", {
      name: /view 2 evaluated trials/i,
    });
    await user.click(accordionBtn);

    expect(screen.getByText("Osimertinib Study")).toBeInTheDocument();
    expect(screen.getByText("Sotorasib Study")).toBeInTheDocument();
    expect(screen.getByText("Hard Exclusion")).toBeInTheDocument();

    // Toggle collapse
    await user.click(screen.getByRole("button", { name: /hide evaluated trials/i }));
    expect(screen.queryByText("Osimertinib Study")).not.toBeInTheDocument();
  });

  it("performs optimistic deletion on confirmation and calls deleteHistorySession", async () => {
    const user = userEvent.setup();
    mockFetchHistory.mockResolvedValue({
      items: mockSessionItems,
      total: 1,
      limit: 50,
      offset: 0,
    });
    mockDeleteHistorySession.mockResolvedValueOnce(undefined);

    render(<HistoryPage />);

    expect(
      await screen.findByText("Non-Small Cell Lung Cancer", {}, { timeout: 3000 })
    ).toBeInTheDocument();

    const deleteIconBtn = screen.getByRole("button", {
      name: /delete evaluation for non-small cell lung cancer/i,
    });
    await user.click(deleteIconBtn);

    // Confirmation dialog appears
    expect(screen.getByText("Delete Evaluation Session?")).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: /delete session/i });
    await user.click(confirmBtn);

    // Optimistically removed
    await waitFor(() => {
      expect(screen.queryByText("Non-Small Cell Lung Cancer")).not.toBeInTheDocument();
      expect(screen.getByText("0 evaluations")).toBeInTheDocument();
    });
    expect(mockDeleteHistorySession).toHaveBeenCalledWith("profile-1");
  });

  it("rolls back optimistic removal and displays error alert if delete fails", async () => {
    const user = userEvent.setup();
    mockFetchHistory.mockResolvedValue({
      items: mockSessionItems,
      total: 1,
      limit: 50,
      offset: 0,
    });
    mockDeleteHistorySession.mockRejectedValueOnce(
      new Error("Server error deleting record")
    );

    render(<HistoryPage />);

    expect(await screen.findByText("Non-Small Cell Lung Cancer")).toBeInTheDocument();

    const deleteIconBtn = screen.getByRole("button", {
      name: /delete evaluation for non-small cell lung cancer/i,
    });
    await user.click(deleteIconBtn);

    const confirmBtn = screen.getByRole("button", { name: /delete session/i });
    await user.click(confirmBtn);

    // Rolled back
    await waitFor(() => {
      expect(screen.getByText("Non-Small Cell Lung Cancer")).toBeInTheDocument();
      expect(screen.getByText("Server error deleting record")).toBeInTheDocument();
    });
  });
});
