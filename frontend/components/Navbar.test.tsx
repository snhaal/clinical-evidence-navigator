import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Navbar } from "./Navbar";

const mockPush = vi.fn();
const mockSignOut = vi.fn();
const mockClearGuest = vi.fn();
let mockAuthState = {
  user: null as any,
  isLoading: false,
  isGuest: false,
  signOut: mockSignOut,
  clearGuest: mockClearGuest,
};

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

vi.mock("./AuthProvider", () => ({
  useAuth: () => mockAuthState,
}));

describe("Navbar Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      user: null,
      isLoading: false,
      isGuest: false,
      signOut: mockSignOut,
      clearGuest: mockClearGuest,
    };
  });

  it("renders Guest Mode badge and Sign In / Register button for guest visitors", () => {
    mockAuthState.isGuest = true;
    render(<Navbar />);

    expect(screen.getByText("Guest Mode")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in \/ register/i })).toBeInTheDocument();
    expect(screen.getByText("History")).toHaveAttribute("aria-disabled", "true");
  });

  it("clears guest mode and redirects to /login when Sign In / Register is clicked", async () => {
    const user = userEvent.setup();
    mockAuthState.isGuest = true;
    render(<Navbar />);

    const signInBtn = screen.getByRole("button", { name: /sign in \/ register/i });
    await user.click(signInBtn);

    expect(mockClearGuest).toHaveBeenCalledTimes(1);
    expect(mockPush).toHaveBeenCalledWith("/login");
  });

  it("renders user email and active History link when authenticated", () => {
    mockAuthState.user = { email: "physician@hospital.org" };
    render(<Navbar />);

    expect(screen.getByText("physician@hospital.org")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "History" })).toHaveAttribute("href", "/history");
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });

  it("invokes signOut and redirects to /login when Sign Out is clicked", async () => {
    const user = userEvent.setup();
    mockAuthState.user = { email: "physician@hospital.org" };
    render(<Navbar />);

    const signOutBtn = screen.getByRole("button", { name: /sign out/i });
    await user.click(signOutBtn);

    expect(mockSignOut).toHaveBeenCalledTimes(1);
    expect(mockPush).toHaveBeenCalledWith("/login");
  });
});
