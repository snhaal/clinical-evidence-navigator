import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";

// Mock supabase client
let authChangeCallback: ((event: string, session: any) => void) | null = null;
const mockGetSession = vi.fn();
const mockSignOut = vi.fn();
const mockUnsubscribe = vi.fn();

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: () => mockGetSession(),
      onAuthStateChange: (cb: any) => {
        authChangeCallback = cb;
        return {
          data: {
            subscription: {
              unsubscribe: mockUnsubscribe,
            },
          },
        };
      },
      signOut: () => mockSignOut(),
    },
  },
}));

function TestConsumer() {
  const { user, isLoading, isGuest, continueAsGuest, signOut } = useAuth();
  return (
    <div>
      <span data-testid="loading">{isLoading ? "loading" : "ready"}</span>
      <span data-testid="user-email">{user?.email ?? "no-user"}</span>
      <span data-testid="is-guest">{isGuest ? "guest" : "not-guest"}</span>
      <button onClick={continueAsGuest} data-testid="guest-btn">
        Continue As Guest
      </button>
      <button onClick={signOut} data-testid="signout-btn">
        Sign Out
      </button>
    </div>
  );
}

describe("AuthProvider Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    authChangeCallback = null;
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockSignOut.mockResolvedValue({ error: null });
  });

  it("initializes with unauthenticated state when no session exists", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    expect(screen.getByTestId("loading")).toHaveTextContent("loading");

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("ready");
    });

    expect(screen.getByTestId("user-email")).toHaveTextContent("no-user");
    expect(screen.getByTestId("is-guest")).toHaveTextContent("not-guest");
  });

  it("enables guest mode and persists flag in localStorage via continueAsGuest", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("ready");
    });

    await user.click(screen.getByTestId("guest-btn"));

    expect(screen.getByTestId("is-guest")).toHaveTextContent("guest");
    expect(localStorage.getItem("cen_guest_mode")).toBe("true");
  });

  it("restores guest mode on mount when localStorage flag is present", async () => {
    localStorage.setItem("cen_guest_mode", "true");

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("ready");
    });

    expect(screen.getByTestId("is-guest")).toHaveTextContent("guest");
  });

  it("updates user state when session is resolved on initial load", async () => {
    const fakeUser = { id: "u-123", email: "oncologist@clinic.org" };
    const fakeSession = { user: fakeUser, access_token: "jwt-token-123" };
    mockGetSession.mockResolvedValueOnce({ data: { session: fakeSession } });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("ready");
    });

    expect(screen.getByTestId("user-email")).toHaveTextContent("oncologist@clinic.org");
    expect(screen.getByTestId("is-guest")).toHaveTextContent("not-guest");
  });

  it("handles onAuthStateChange events to update user and reset guest mode", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("ready");
    });

    // Simulate signing in
    const fakeUser = { id: "u-456", email: "researcher@lab.org" };
    const fakeSession = { user: fakeUser, access_token: "jwt-456" };

    act(() => {
      authChangeCallback?.("SIGNED_IN", fakeSession);
    });

    expect(screen.getByTestId("user-email")).toHaveTextContent("researcher@lab.org");
    expect(screen.getByTestId("is-guest")).toHaveTextContent("not-guest");
    expect(localStorage.getItem("cen_guest_mode")).toBeNull();
  });

  it("handles signOut cleanly", async () => {
    const user = userEvent.setup();
    const fakeUser = { id: "u-789", email: "doc@health.org" };
    const fakeSession = { user: fakeUser, access_token: "jwt-789" };
    mockGetSession.mockResolvedValueOnce({ data: { session: fakeSession } });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("user-email")).toHaveTextContent("doc@health.org");
    });

    await user.click(screen.getByTestId("signout-btn"));

    expect(mockSignOut).toHaveBeenCalled();
    expect(screen.getByTestId("user-email")).toHaveTextContent("no-user");
    expect(screen.getByTestId("is-guest")).toHaveTextContent("not-guest");
  });
});
