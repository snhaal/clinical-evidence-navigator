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

vi.mock("@/lib/supabase", () => ({
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
});
