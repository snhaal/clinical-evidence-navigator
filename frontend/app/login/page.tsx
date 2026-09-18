import type { Metadata } from "next";
import { AuthForm } from "@/components/AuthForm";

export const metadata: Metadata = {
  title: "Sign In · Clinical Evidence Navigator",
  description: "Sign in to access your clinical trial match history.",
};

export default function LoginPage() {
  return (
    <main className="min-h-screen bg-bg px-4 py-16">
      <div className="mx-auto max-w-reading text-center mb-8">
        <h1 className="font-serif text-3xl font-semibold text-ink">
          Sign In
        </h1>
        <p className="mt-2 text-sm text-muted">
          Access your clinical evaluation history and saved trial dossiers.
        </p>
      </div>
      <AuthForm initialMode="login" />
    </main>
  );
}
