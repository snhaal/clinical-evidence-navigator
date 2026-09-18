import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

if (!supabaseUrl || !supabaseAnonKey) {
  console.error("CRITICAL: NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY is not defined.");
}

export const SUPABASE_CONFIG_ERROR =
  "Configuration error: Supabase environment variables are missing on this deployment. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Vercel and redeploy.";

export const isSupabaseConfigured = Boolean(
  supabaseUrl &&
    supabaseAnonKey &&
    !supabaseUrl.includes("placeholder-project") &&
    supabaseAnonKey !== "placeholder-anon-key"
);

// Fallback to placeholder values to prevent createClient from throwing on initial import during build/tests
export const supabase = createClient(
  supabaseUrl || "https://placeholder-project.supabase.co",
  supabaseAnonKey || "placeholder-anon-key"
);

