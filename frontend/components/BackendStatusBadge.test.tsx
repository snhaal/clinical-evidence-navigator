import { describe, it, expect, vi } from "vitest";
import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { BackendStatusBadge } from "./BackendStatusBadge";

describe("BackendStatusBadge Component", () => {
  it("renders connecting state with cold-start warning and pulse indicator", () => {
    render(<BackendStatusBadge status="connecting" />);

    expect(
      screen.getByText(/Waking up backend \(~30–50s cold start\)\.\.\./i)
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-label",
      "Backend status: waking up"
    );
  });

  it("renders ready state when backend is active", () => {
    render(<BackendStatusBadge status="ready" />);

    expect(screen.getByText(/Backend Active/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-label",
      "Backend status: active"
    );
  });

  it("renders error state with retry button and fires onRetry when clicked", () => {
    const onRetryMock = vi.fn();
    render(<BackendStatusBadge status="error" onRetry={onRetryMock} />);

    expect(screen.getByText(/Backend Unavailable/i)).toBeInTheDocument();
    const retryBtn = screen.getByRole("button", { name: /retry connecting to backend/i });
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);
    expect(onRetryMock).toHaveBeenCalledTimes(1);
  });
});
