import type { ApiErrorCode, ApiErrorEnvelope } from "./types";

const API_VERSION_PATH = "/api/v1";

/**
 * The compose file may hand us either an origin (`http://api:8000`) or a base
 * that already carries the version prefix. Normalising both ways means the app
 * boots against whichever convention the operator wrote in .env.
 */
function normaliseBase(raw: string): string {
  const trimmed = raw.replace(/\/+$/, "");
  return trimmed.endsWith(API_VERSION_PATH) ? trimmed : `${trimmed}${API_VERSION_PATH}`;
}

export function apiBaseUrl(): string {
  return `${apiOrigin()}${API_VERSION_PATH}`;
}

/** /healthz and /readyz sit outside the versioned surface. */
export function apiOrigin(): string {
  // Server components run inside the compose network and use the service name;
  // the browser cannot resolve `api`, so it gets the public URL instead.
  const raw =
    typeof window === "undefined"
      ? process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL || "http://api:8000"
      : process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  return normaliseBase(raw).slice(0, -API_VERSION_PATH.length);
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly detail: unknown;

  constructor(status: number, code: ApiErrorCode, message: string, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }

  get isUnauthorized(): boolean {
    return this.status === 401 || this.code === "unauthorized";
  }

  get isNotFound(): boolean {
    return this.status === 404 || this.code === "not_found";
  }
}

export type ApiRequest = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | null | undefined>;
  cache?: RequestCache;
};

function buildUrl(path: string, query: ApiRequest["query"]): string {
  const url = new URL(`${apiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** Unversioned probe used by the sandbox banner: GET /readyz. */
export async function fetchReadiness<T>(path: "/healthz" | "/readyz"): Promise<T> {
  const response = await fetch(`${apiOrigin()}${path}`, { credentials: "include", cache: "no-store" });
  // 503 carries the same body shape as 200, and the banner needs to read it.
  const text = await response.text();
  if (!text) throw new ApiError(response.status, "internal_error", "empty readiness response");
  return JSON.parse(text) as T;
}

/**
 * Auth endpoints are exempt from the redirect: /auth/me is how the shell probes
 * for a session, and bouncing an anonymous visitor off the public catalogue
 * would reintroduce the signup wall the contract explicitly removes.
 */
function shouldRedirectOn401(path: string): boolean {
  return typeof window !== "undefined" && !path.startsWith("/auth/");
}

export function loginUrlForCurrentLocation(): string {
  const next = `${window.location.pathname}${window.location.search}`;
  return `/login?next=${encodeURIComponent(next)}`;
}

async function readError(response: Response): Promise<ApiError> {
  let code: ApiErrorCode = response.status === 404 ? "not_found" : "internal_error";
  let message = `${response.status} ${response.statusText || "request failed"}`;
  let detail: unknown = null;
  try {
    const parsed = (await response.json()) as Partial<ApiErrorEnvelope>;
    if (parsed?.error) {
      code = parsed.error.code ?? code;
      message = parsed.error.message ?? message;
      detail = parsed.error.detail ?? null;
    }
  } catch {
    // A proxy or a crashed worker can answer with HTML; keep the status message.
  }
  return new ApiError(response.status, code, message, detail);
}

export async function apiFetch<T>(path: string, request: ApiRequest = {}): Promise<T> {
  const { method = "GET", body, headers, signal, query, cache = "no-store" } = request;

  const response = await fetch(buildUrl(path, query), {
    method,
    // The session lives in the httpOnly `learnos_session` cookie. No token is
    // ever read or written by JS, so there is nothing for XSS to steal.
    credentials: "include",
    cache,
    signal,
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await readError(response);
    if (error.isUnauthorized && shouldRedirectOn401(path)) {
      window.location.assign(loginUrlForCurrentLocation());
    }
    throw error;
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

/** Distinguishes "the API said no" from "the network fell over" for empty states. */
export function describeError(error: unknown): { title: string; message: string; code?: ApiErrorCode } {
  if (error instanceof ApiError) {
    return { title: error.code.replace(/_/g, " "), message: error.message, code: error.code };
  }
  if (error instanceof Error) return { title: "request failed", message: error.message };
  return { title: "request failed", message: "Unknown error" };
}
