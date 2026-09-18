import { supabase } from "./supabase";
import type {
  ApiErrorShape,
  HistoryDetailResponse,
  HistoryListResponse,
  MatchResponse,
} from "./types";

export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (envUrl) {
    return envUrl.replace(/\/$/, "");
  }
  if (process.env.NODE_ENV === "production") {
    throw new ApiError(
      "Configuration error: NEXT_PUBLIC_API_BASE_URL is not configured on this deployment. Please set NEXT_PUBLIC_API_BASE_URL in your hosting provider settings.",
      500
    );
  }
  return "http://localhost:8000";
}

export type BackendStatus = "connecting" | "ready" | "error";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/**
 * Retrieves Authorization header containing Bearer token if an active
 * Supabase session exists. If unauthenticated or in guest mode, returns empty object.
 */
async function getAuthHeaders(): Promise<Record<string, string>> {
  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (session?.access_token) {
      return { Authorization: `Bearer ${session.access_token}` };
    }
  } catch {
    // Guest mode or error reading session
  }
  return {};
}

/**
 * Lightweight background ping to wake up the backend and probe status.
 * Checks GET /health, falling back to GET / if needed.
 */
export async function pingBackend(): Promise<boolean> {
  let baseUrl: string;
  try {
    baseUrl = getApiBaseUrl();
  } catch {
    return false;
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60000); // 60s cold-start grace period
    const response = await fetch(`${baseUrl}/health`, {
      method: "GET",
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response.ok;
  } catch {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);
      const res = await fetch(`${baseUrl}/`, {
        method: "GET",
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      return res.ok;
    } catch {
      return false;
    }
  }
}

/**
 * Calls POST /match. Attaches Bearer token if logged in, or omits for guest mode.
 * Throws ApiError with a specific, user-facing message on non-2xx response.
 */
export async function matchPatientProfile(patientProfile: string): Promise<MatchResponse> {
  const baseUrl = getApiBaseUrl();
  let response: Response;
  const authHeaders = await getAuthHeaders();

  try {
    response = await fetch(`${baseUrl}/match`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
      },
      body: JSON.stringify({ patient_profile: patientProfile }),
    });
  } catch {
    throw new ApiError(
      "Couldn't reach the matching service. Check your connection and try again.",
      0,
    );
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;
    try {
      const errorBody = (await response.json()) as ApiErrorShape;
      if (errorBody?.detail) detail = errorBody.detail;
    } catch {
      // Response body wasn't JSON — fall back to the generic status message above.
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as MatchResponse;
}

/**
 * Fetches paginated history for the authenticated user.
 */
export async function fetchHistory(limit = 20, offset = 0): Promise<HistoryListResponse> {
  const baseUrl = getApiBaseUrl();
  const authHeaders = await getAuthHeaders();
  if (!authHeaders.Authorization) {
    throw new ApiError("You must be signed in to view match history.", 401);
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/v1/history?limit=${limit}&offset=${offset}`, {
      method: "GET",
      headers: {
        ...authHeaders,
      },
    });
  } catch {
    throw new ApiError("Failed to connect to history service.", 0);
  }

  if (!response.ok) {
    let detail = `Failed to fetch history (Status ${response.status}).`;
    try {
      const errorBody = (await response.json()) as ApiErrorShape;
      if (errorBody?.detail) detail = errorBody.detail;
    } catch {
      // non-json response
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as HistoryListResponse;
}

/**
 * Fetches full details for a specific historical match run.
 */
export async function fetchHistoryDetail(matchRunId: string): Promise<HistoryDetailResponse> {
  const baseUrl = getApiBaseUrl();
  const authHeaders = await getAuthHeaders();
  if (!authHeaders.Authorization) {
    throw new ApiError("You must be signed in to view match run details.", 401);
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/v1/history/${matchRunId}`, {
      method: "GET",
      headers: {
        ...authHeaders,
      },
    });
  } catch {
    throw new ApiError("Failed to connect to history service.", 0);
  }

  if (!response.ok) {
    let detail = `Failed to load match run details (Status ${response.status}).`;
    try {
      const errorBody = (await response.json()) as ApiErrorShape;
      if (errorBody?.detail) detail = errorBody.detail;
    } catch {
      // non-json response
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as HistoryDetailResponse;
}
