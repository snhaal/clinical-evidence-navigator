"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "./AuthProvider";

export function Navbar() {
  const { user, isLoading, isGuest, signOut, clearGuest } = useAuth();
  const router = useRouter();

  const handleSignOut = async () => {
    await signOut();
    router.push("/login");
  };

  const handleSignIn = () => {
    clearGuest();
    router.push("/login");
  };

  return (
    <header className="w-full px-6 py-3 flex items-center justify-between border-b border-stone-200 bg-surface">
      <Link
        href="/"
        className="font-serif text-lg font-semibold tracking-tight text-ink hover:text-accent transition-colors"
      >
        Clinical Evidence Navigator
      </Link>

      <div className="flex items-center gap-3 sm:gap-4">
        {isLoading ? (
          <div className="h-6 w-24 animate-pulse rounded bg-border/40" />
        ) : user ? (
          <>
            <Link
              href="/history"
              className="text-sm font-medium text-ink transition-colors hover:text-accent focus:outline-hidden"
            >
              History
            </Link>
            <div className="hidden sm:flex items-center gap-1.5 border-l border-border pl-3">
              <span
                className="max-w-[160px] truncate font-mono text-xs text-muted"
                title={user.email ?? "Signed In"}
              >
                {user.email}
              </span>
            </div>
            <button
              type="button"
              onClick={handleSignOut}
              className="rounded-sm border border-border px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:border-nomatch/40 hover:bg-nomatch-soft hover:text-nomatch focus:outline-hidden"
            >
              Sign Out
            </button>
          </>
        ) : (
          <>
            <span
              className="inline-flex items-center rounded-sm bg-accent-soft px-2 py-0.5 font-mono text-xs font-medium text-accent"
              title="You are browsing as a guest. Searches will not be saved."
            >
              Guest Mode
            </span>

            <span
              className="cursor-not-allowed select-none text-sm font-medium text-muted/40"
              title="Sign in to save and review past match history"
              aria-disabled="true"
            >
              History
            </span>

            <button
              type="button"
              onClick={handleSignIn}
              className="rounded-sm bg-accent px-3 py-1 text-xs font-medium text-surface shadow-xs transition-colors hover:bg-accent/90 focus:outline-hidden"
            >
              Sign In / Register
            </button>
          </>
        )}
      </div>
    </header>
  );
}

export default Navbar;
