import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AuthForm } from "./AuthForm";

const mockPush = vi.fn();
const mockReplace = vi.fn();
const mockContinueAsGuest = vi.fn();
const mockSignInWithPassword = vi.fn();
const mockSignUp = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
  }),
}));

vi.mock("./AuthProvider", () => ({
  useAuth: () => ({
    user: null,
    isLoading: false,
    continueAsGuest: mockContinueAsGuest,
  }),
}));

let mockIsSupabaseConfigured = true;

vi.mock("@/lib/supabase", () => ({
  get isSupabaseConfigured() {
    return mockIsSupabaseConfigured;
  },
  SUPABASE_CONFIG_ERROR:
    "Configuration error: Supabase environment variables are missing on this deployment. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Vercel and redeploy.",
  supabase: {
    auth: {
      signInWithPassword: (...args: any[]) => mockSignInWithPassword(...args),
      signUp: (...args: any[]) => mockSignUp(...args),
    },
  },
}));

describe("AuthForm Component - Keystroke & Input Stability", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsSupabaseConfigured = true;
    mockSignInWithPassword.mockResolvedValue({ data: { session: {} }, error: null });
    mockSignUp.mockResolvedValue({ data: { session: {} }, error: null });
  });

  it("handles typing an email containing '@' without freezing or recursion", async () => {
    const user = userEvent.setup();
    render(<AuthForm initialMode="login" />);

    const emailInput = screen.getByLabelText(/email address/i) as HTMLInputElement;
    expect(emailInput.value).toBe("");

    // Type full email including '@'
    await user.type(emailInput, "oncologist@hospital.org");
    expect(emailInput.value).toBe("oncologist@hospital.org");

    // Clear and type multiple '@' characters directly
    await user.clear(emailInput);
    await user.type(emailInput, "test@@example.com");
    expect(emailInput.value).toBe("test@@example.com");
  });

  it("validates email presence and structure only upon submission", async () => {
    const user = userEvent.setup();
    render(<AuthForm initialMode="login" />);

    const submitBtn = screen.getByTestId("auth-submit-btn");
    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/^password$/i);

    // 1. Submit empty email
    await user.click(submitBtn);
    expect(screen.getByRole("alert")).toHaveTextContent(/please enter your email address/i);

    // 2. Type invalid email without '@'
    await user.type(emailInput, "invalid-email-address");
    await user.type(passwordInput, "password123");
    await user.click(submitBtn);

    expect(screen.getByRole("alert")).toHaveTextContent(/please enter a valid email address/i);
    expect(mockSignInWithPassword).not.toHaveBeenCalled();

    // 3. Fix email to valid format
    await user.clear(emailInput);
    await user.type(emailInput, "valid.physician@hospital.org");
    await user.click(submitBtn);

    await waitFor(() => {
      expect(mockSignInWithPassword).toHaveBeenCalledWith({
        email: "valid.physician@hospital.org",
        password: "password123",
      });
    });
    expect(mockPush).toHaveBeenCalledWith("/");
  });

  it("allows switching between login and signup modes smoothly", async () => {
    const user = userEvent.setup();
    render(<AuthForm initialMode="login" />);

    expect(screen.queryByLabelText(/confirm password/i)).not.toBeInTheDocument();

    const signupTab = screen.getByRole("button", { name: /create account/i });
    await user.click(signupTab);

    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
  });

  it("handles Continue as Guest click cleanly", async () => {
    const user = userEvent.setup();
    render(<AuthForm initialMode="login" />);

    const guestBtn = screen.getByRole("button", { name: /continue as guest/i });
    await user.click(guestBtn);

    expect(mockContinueAsGuest).toHaveBeenCalledTimes(1);
    expect(mockPush).toHaveBeenCalledWith("/");
  });

  it("displays explicit warning banner when Supabase environment variables are missing", async () => {
    mockIsSupabaseConfigured = false;
    render(<AuthForm initialMode="login" />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      /configuration error: supabase environment variables are missing on this deployment/i
    );
  });

  it("surfaces network error guidance when sign in returns 'Failed to fetch'", async () => {
    const user = userEvent.setup();
    mockSignInWithPassword.mockResolvedValueOnce({
      data: { session: null },
      error: { message: "Failed to fetch", name: "TypeError" },
    });

    render(<AuthForm initialMode="login" />);

    await user.type(screen.getByLabelText(/email address/i), "doc@hospital.org");
    await user.type(screen.getByLabelText(/^password$/i), "secret123");
    await user.click(screen.getByTestId("auth-submit-btn"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /network error: unable to connect to supabase\. verify next_public_supabase_url/i
      );
    });
  });

  it("surfaces network error guidance when sign in throws a TypeError network exception", async () => {
    const user = userEvent.setup();
    mockSignInWithPassword.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    render(<AuthForm initialMode="login" />);

    await user.type(screen.getByLabelText(/email address/i), "doc@hospital.org");
    await user.type(screen.getByLabelText(/^password$/i), "secret123");
    await user.click(screen.getByTestId("auth-submit-btn"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /network error: unable to connect to supabase\. verify next_public_supabase_url/i
      );
    });
  });

  it("shows green confirmation notice when account is created with email confirmation required", async () => {
    const user = userEvent.setup();
    mockSignUp.mockResolvedValueOnce({
      data: { user: { id: "new-user-123" }, session: null },
      error: null,
    });

    render(<AuthForm initialMode="signup" />);

    await user.type(screen.getByLabelText(/email address/i), "newdoc@hospital.org");
    await user.type(screen.getByLabelText(/^password$/i), "secret123");
    await user.type(screen.getByLabelText(/confirm password/i), "secret123");
    await user.click(screen.getByTestId("auth-submit-btn"));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Account created! Please check your email to confirm your account before logging in."
      );
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("navigates immediately to home when account is created and session is granted", async () => {
    const user = userEvent.setup();
    mockSignUp.mockResolvedValueOnce({
      data: { user: { id: "new-user-456" }, session: { access_token: "tok" } },
      error: null,
    });

    render(<AuthForm initialMode="signup" />);

    await user.type(screen.getByLabelText(/email address/i), "authed@hospital.org");
    await user.type(screen.getByLabelText(/^password$/i), "secret123");
    await user.type(screen.getByLabelText(/confirm password/i), "secret123");
    await user.click(screen.getByTestId("auth-submit-btn"));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/");
    });
  });
});
