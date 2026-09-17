import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen, act } from "@testing-library/react";
import { RotatingLoadingState } from "./RotatingLoadingState";

describe("RotatingLoadingState Component", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders stage 1 initially and displays the realistic 30-50s latency notice", () => {
    render(<RotatingLoadingState />);

    // Stage 1 (0-8s)
    expect(
      screen.getByText(/Synthesizing patient profile & extracting search parameters\.\.\./i)
    ).toBeInTheDocument();

    // 30-50s notice
    expect(
      screen.getByText(
        /In-depth multi-trial criterion verification typically takes 30–50 seconds\./i
      )
    ).toBeInTheDocument();

    expect(screen.getByText(/0s elapsed/i)).toBeInTheDocument();
  });

  it("transitions sequentially across all 4 stages as time progresses", () => {
    render(<RotatingLoadingState />);

    // Advance to 8 seconds -> Stage 2 (8-18s)
    act(() => {
      vi.advanceTimersByTime(8000);
    });
    expect(
      screen.getByText(/Querying ClinicalTrials\.gov registry for candidate protocols\.\.\./i)
    ).toBeInTheDocument();
    expect(screen.getByText(/8s elapsed/i)).toBeInTheDocument();

    // Advance to 18 seconds -> Stage 3 (18-32s)
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(
      screen.getByText(/Analyzing inclusion & exclusion criteria with Gemini Flash-Lite\.\.\./i)
    ).toBeInTheDocument();
    expect(screen.getByText(/18s elapsed/i)).toBeInTheDocument();

    // Advance to 32 seconds -> Stage 4 (32s+)
    act(() => {
      vi.advanceTimersByTime(14000);
    });
    expect(
      screen.getByText(/Synthesizing clinical rationales and compiling evidence citations\.\.\./i)
    ).toBeInTheDocument();
    expect(screen.getByText(/32s elapsed/i)).toBeInTheDocument();
  });
});
