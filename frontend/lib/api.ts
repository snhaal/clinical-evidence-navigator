import type { ApiErrorShape, MatchResponse } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
 * Lightweight background ping to wake up the backend and probe status.
 * Checks GET /health, falling back to GET / if needed.
 */
export async function pingBackend(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60000); // 60s cold-start grace period
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response.ok;
  } catch {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);
      const res = await fetch(`${API_BASE_URL}/`, {
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
 * Calls POST /match. Throws ApiError with a specific, user-facing message
 * on any non-2xx response — the UI must show that message rather than a
 * generic failure, per the backend's "visible, specific error state" NFR.
 */
export async function matchPatientProfile(patientProfile: string): Promise<MatchResponse> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}/match`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
