import type { Metadata } from "next";
import { AuthForm } from "@/components/AuthForm";

export const metadata: Metadata = {
  title: "Create Account · Clinical Evidence Navigator",
  description: "Create an account to save and track your clinical trial match history.",
};

export default function SignupPage() {
  return (
    <main className="min-h-screen bg-bg px-4 py-16">
      <div className="mx-auto max-w-reading text-center mb-8">
        <h1 className="font-serif text-3xl font-semibold text-ink">
          Create Account
        </h1>
        <p className="mt-2 text-sm text-muted">
          Register to automatically archive trial evaluations and export historical dossiers.
        </p>
      </div>
      <AuthForm initialMode="signup" />
    </main>
  );
}
