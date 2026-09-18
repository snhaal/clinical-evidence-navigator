"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { useAuth } from "./AuthProvider";

interface AuthFormProps {
  initialMode: "login" | "signup";
}

export function AuthForm({ initialMode }: AuthFormProps) {
  const [mode, setMode] = useState<"login" | "signup">(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const router = useRouter();
  const { user, isLoading, continueAsGuest } = useAuth();

  // Already authenticated users are redirected to home; guests remain on login
  useEffect(() => {
    if (!isLoading && user) {
      router.replace("/");
    }
  }, [isLoading, user, router]);

  const handleGuest = () => {
    continueAsGuest();
    router.push("/");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);

    const cleanEmail = email.trim();
    if (!cleanEmail) {
      setError("Please enter your email address.");
      return;
    }

    // Basic format check on submission only - no live regex on keystroke
    if (!cleanEmail.includes("@") || !cleanEmail.includes(".")) {
      setError("Please enter a valid email address.");
      return;
    }

    if (!password) {
      setError("Please enter your password.");
      return;
    }

    if (mode === "signup") {
      if (password.length < 6) {
        setError("Password must be at least 6 characters long.");
        return;
      }
      if (password !== confirmPassword) {
        setError("Passwords do not match.");
        return;
      }
    }

    setIsSubmitting(true);
    try {
      if (mode === "login") {
        const { error: signInError } = await supabase.auth.signInWithPassword({
          email: cleanEmail,
          password,
        });
        if (signInError) {
          if (
            signInError.message.toLowerCase().includes("invalid login credentials")
          ) {
            setError(
              "Invalid email or password. Please check your credentials and try again."
            );
          } else {
            setError(signInError.message);
          }
          return;
        }
        router.push("/");
      } else {
        const { data, error: signUpError } = await supabase.auth.signUp({
          email: cleanEmail,
          password,
        });
        if (signUpError) {
          if (signUpError.message.toLowerCase().includes("already registered")) {
            setError("An account with this email already exists. Try signing in.");
          } else {
            setError(signUpError.message);
          }
          return;
        }

        if (data.session) {
          router.push("/");
        } else {
          setNotice(
            "Account created! If email confirmation is enabled, please check your inbox before logging in."
          );
        }
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : "An unexpected error occurred. Please try again.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-sm rounded-sm border border-border bg-surface p-6 shadow-xs">
      <div className="flex border-b border-border mb-6">
        <button
          type="button"
          onClick={() => {
            setMode("login");
            setError(null);
            setNotice(null);
          }}
          className={`flex-1 pb-3 text-center text-sm font-medium transition-colors border-b-2 ${
            mode === "login"
              ? "border-accent text-accent font-semibold"
              : "border-transparent text-muted hover:text-ink"
          }`}
        >
          Sign In
        </button>
        <button
          type="button"
          onClick={() => {
            setMode("signup");
            setError(null);
            setNotice(null);
          }}
          className={`flex-1 pb-3 text-center text-sm font-medium transition-colors border-b-2 ${
            mode === "signup"
              ? "border-accent text-accent font-semibold"
              : "border-transparent text-muted hover:text-ink"
          }`}
        >
          Create Account
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-sm border border-nomatch/30 bg-nomatch-soft p-3 text-xs text-nomatch"
        >
          {error}
        </div>
      )}

      {notice && (
        <div
          role="status"
          className="mb-4 rounded-sm border border-accent/30 bg-accent-soft p-3 text-xs text-accent"
        >
          {notice}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div>
          <label
            htmlFor="email-input"
            className="block text-xs font-medium text-muted uppercase tracking-wider mb-1"
          >
            Email Address
          </label>
          <input
            id="email-input"
            name="email"
            type="email"
            autoComplete="email"
            spellCheck={false}
            autoCapitalize="none"
            autoCorrect="off"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={isSubmitting}
            placeholder="physician@hospital.org"
            className="w-full rounded-sm border border-border bg-bg px-3 py-2 text-sm text-ink placeholder:text-muted/50 focus:border-accent focus:bg-surface focus:outline-hidden"
          />
        </div>

        <div>
          <label
            htmlFor="password-input"
            className="block text-xs font-medium text-muted uppercase tracking-wider mb-1"
          >
            Password
          </label>
          <input
            id="password-input"
            name="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={isSubmitting}
            placeholder="••••••••"
            className="w-full rounded-sm border border-border bg-bg px-3 py-2 text-sm text-ink placeholder:text-muted/50 focus:border-accent focus:bg-surface focus:outline-hidden"
          />
        </div>

        {mode === "signup" && (
          <div>
            <label
              htmlFor="confirm-password-input"
              className="block text-xs font-medium text-muted uppercase tracking-wider mb-1"
            >
              Confirm Password
            </label>
            <input
              id="confirm-password-input"
              name="confirmPassword"
              type="password"
              autoComplete="new-password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              disabled={isSubmitting}
              placeholder="••••••••"
              className="w-full rounded-sm border border-border bg-bg px-3 py-2 text-sm text-ink placeholder:text-muted/50 focus:border-accent focus:bg-surface focus:outline-hidden"
            />
          </div>
        )}

        <button
          type="submit"
          data-testid="auth-submit-btn"
          disabled={isSubmitting}
          className="w-full rounded-sm bg-accent py-2 text-sm font-medium text-surface shadow-xs transition-colors hover:bg-accent/90 disabled:opacity-60 focus:outline-hidden"
        >
          {isSubmitting
            ? mode === "login"
              ? "Signing in…"
              : "Creating account…"
            : mode === "login"
            ? "Sign In"
            : "Create Account"}
        </button>
      </form>

      <div className="relative my-5">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-border" />
        </div>
        <div className="relative flex justify-center text-xs uppercase">
          <span className="bg-surface px-2 text-muted">or</span>
        </div>
      </div>

      <button
        type="button"
        onClick={handleGuest}
        className="w-full rounded-sm border border-border bg-surface py-2 text-sm font-medium text-muted transition-colors hover:border-accent/40 hover:bg-accent-soft/30 hover:text-ink focus:outline-hidden"
      >
        Continue as Guest
      </button>

      <p className="mt-2 text-center text-xs text-muted/80 leading-normal">
        Guest mode allows full trial matching, but search history and saved patient dossiers will not be saved.
      </p>
    </div>
  );
}

export default AuthForm;
