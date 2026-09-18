"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";

export const GUEST_STORAGE_KEY = "guest_acknowledged";
const LEGACY_GUEST_STORAGE_KEY = "cen_guest_mode";

export interface AuthContextType {
  user: User | null;
  session: Session | null;
  isLoading: boolean;
  isGuest: boolean;
  signOut: () => Promise<void>;
  continueAsGuest: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGuest, setIsGuest] = useState(false);

  useEffect(() => {
    let mounted = true;

    // Check existing session
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!mounted) return;
      if (session) {
        setSession(session);
        setUser(session.user);
        setIsGuest(false);
        try {
          localStorage.removeItem(GUEST_STORAGE_KEY);
          localStorage.removeItem(LEGACY_GUEST_STORAGE_KEY);
        } catch {
          // Ignore localStorage errors (e.g. private browsing restrictions)
        }
      } else {
        setSession(null);
        setUser(null);
        try {
          const storedGuest =
            localStorage.getItem(GUEST_STORAGE_KEY) === "true" ||
            localStorage.getItem(LEGACY_GUEST_STORAGE_KEY) === "true";
          setIsGuest(storedGuest);
        } catch {
          setIsGuest(false);
        }
      }
      setIsLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!mounted) return;
      if (session) {
        setSession(session);
        setUser(session.user);
        setIsGuest(false);
        try {
          localStorage.removeItem(GUEST_STORAGE_KEY);
          localStorage.removeItem(LEGACY_GUEST_STORAGE_KEY);
        } catch {
          // ignore
        }
      } else {
        setSession(null);
        setUser(null);
        try {
          const storedGuest =
            localStorage.getItem(GUEST_STORAGE_KEY) === "true" ||
            localStorage.getItem(LEGACY_GUEST_STORAGE_KEY) === "true";
          setIsGuest(storedGuest);
        } catch {
          setIsGuest(false);
        }
      }
      setIsLoading(false);
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, []);

  const continueAsGuest = () => {
    setIsGuest(true);
    try {
      localStorage.setItem(GUEST_STORAGE_KEY, "true");
      localStorage.removeItem(LEGACY_GUEST_STORAGE_KEY);
    } catch {
      // ignore
    }
  };

  const signOut = async () => {
    try {
      await supabase.auth.signOut();
    } catch (err) {
      console.error("Sign out error:", err);
    } finally {
      setUser(null);
      setSession(null);
      setIsGuest(false);
      try {
        localStorage.removeItem(GUEST_STORAGE_KEY);
        localStorage.removeItem(LEGACY_GUEST_STORAGE_KEY);
      } catch {
        // ignore
      }
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        isLoading,
        isGuest,
        signOut,
        continueAsGuest,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
