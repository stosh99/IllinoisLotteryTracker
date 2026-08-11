import type {
  AccountResponse,
  AuthProblem,
  AuthSessionResponse,
  ManagedSession,
  SessionListResponse,
} from "../types/auth";

const AUTH_ROOT = "/api/v1/auth";
const ACCOUNT_PATH = "/api/v1/account";

export class AuthRequestError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.name = "AuthRequestError";
    this.status = status;
    this.code = code;
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${AUTH_ROOT}${path}`, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
}

async function accountRequest(init: RequestInit = {}): Promise<Response> {
  return fetch(ACCOUNT_PATH, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
}

async function problem(response: Response): Promise<never> {
  let code = "AUTH_UNAVAILABLE";
  try {
    const document = (await response.json()) as Partial<AuthProblem>;
    if (typeof document.code === "string" && document.code.length <= 64) {
      code = document.code;
    }
  } catch {
    // Public UI uses a bounded local fallback and never renders response text.
  }
  throw new AuthRequestError(response.status, code);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).sort().join("|") === [...keys].sort().join("|");
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && !Number.isNaN(Date.parse(value));
}

function parseSession(document: unknown): AuthSessionResponse {
  if (
    !isRecord(document) ||
    !exactKeys(document, [
      "authenticationAvailable",
      "authenticated",
      "user",
      "session",
      "csrfToken",
    ])
  ) {
    throw new AuthRequestError(503, "AUTH_UNAVAILABLE");
  }
  if (document.authenticationAvailable === false && document.authenticated === false) {
    if (document.user === null && document.session === null && document.csrfToken === null) {
      return document as unknown as AuthSessionResponse;
    }
  }
  if (document.authenticationAvailable === true && document.authenticated === false) {
    if (document.user === null && document.session === null && document.csrfToken === null) {
      return document as unknown as AuthSessionResponse;
    }
  }
  if (
    document.authenticationAvailable === true &&
    document.authenticated === true &&
    isRecord(document.user) &&
    exactKeys(document.user, ["id", "email", "emailVerified"]) &&
    typeof document.user.id === "string" &&
    typeof document.user.email === "string" &&
    document.user.emailVerified === true &&
    isRecord(document.session) &&
    exactKeys(document.session, ["authenticatedAt", "idleExpiresAt", "absoluteExpiresAt"]) &&
    isTimestamp(document.session.authenticatedAt) &&
    isTimestamp(document.session.idleExpiresAt) &&
    isTimestamp(document.session.absoluteExpiresAt) &&
    typeof document.csrfToken === "string" &&
    document.csrfToken.length <= 128
  ) {
    return document as unknown as AuthSessionResponse;
  }
  throw new AuthRequestError(503, "AUTH_UNAVAILABLE");
}

export async function loadAuthSession(signal?: AbortSignal): Promise<AuthSessionResponse> {
  const response = await request("/session", { signal });
  if (!response.ok) return problem(response);
  return parseSession(await response.json());
}

function unsafe(csrfToken: string, method: "POST" | "DELETE", body?: string): RequestInit {
  const headers: Record<string, string> = { "X-CSRF-Token": csrfToken };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return { method, headers, body };
}

export async function logoutSession(csrfToken: string): Promise<void> {
  const response = await request("/logout", unsafe(csrfToken, "POST", "{}"));
  if (!response.ok) return problem(response);
}

export async function logoutAllSessions(csrfToken: string): Promise<void> {
  const response = await request("/logout-all", unsafe(csrfToken, "POST", "{}"));
  if (!response.ok) return problem(response);
}

export async function listSessions(signal?: AbortSignal): Promise<ManagedSession[]> {
  const response = await request("/sessions", { signal });
  if (!response.ok) return problem(response);
  const document = (await response.json()) as Partial<SessionListResponse>;
  if (!Array.isArray(document.sessions) || !document.sessions.every(isManagedSession)) {
    throw new AuthRequestError(503, "AUTH_UNAVAILABLE");
  }
  return document.sessions;
}

function isManagedSession(value: unknown): value is ManagedSession {
  return (
    isRecord(value) &&
    exactKeys(value, [
      "id",
      "current",
      "createdAt",
      "lastSeenAt",
      "idleExpiresAt",
      "absoluteExpiresAt",
    ]) &&
    typeof value.id === "string" &&
    typeof value.current === "boolean" &&
    isTimestamp(value.createdAt) &&
    isTimestamp(value.lastSeenAt) &&
    isTimestamp(value.idleExpiresAt) &&
    isTimestamp(value.absoluteExpiresAt)
  );
}

export async function revokeSession(sessionId: string, csrfToken: string): Promise<void> {
  const response = await request(
    `/sessions/${encodeURIComponent(sessionId)}`,
    unsafe(csrfToken, "DELETE"),
  );
  if (!response.ok) return problem(response);
}

export async function loadAccount(signal?: AbortSignal): Promise<AccountResponse> {
  const response = await accountRequest({ signal });
  if (!response.ok) return problem(response);
  const document = (await response.json()) as unknown;
  if (
    !isRecord(document) ||
    !exactKeys(document, ["id", "email", "emailVerified", "createdAt"]) ||
    typeof document.id !== "string" ||
    typeof document.email !== "string" ||
    document.emailVerified !== true ||
    !isTimestamp(document.createdAt)
  ) {
    throw new AuthRequestError(503, "AUTH_UNAVAILABLE");
  }
  return document as unknown as AccountResponse;
}

export function validateGoogleAuthorizationUrl(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > 4096) {
    throw new AuthRequestError(503, "AUTH_UNAVAILABLE");
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new AuthRequestError(503, "AUTH_UNAVAILABLE");
  }
  if (
    url.protocol !== "https:" ||
    url.hostname !== "accounts.google.com" ||
    (url.port !== "" && url.port !== "443") ||
    url.pathname !== "/o/oauth2/v2/auth" ||
    url.username !== "" ||
    url.password !== "" ||
    url.hash !== "" ||
    url.search === ""
  ) {
    throw new AuthRequestError(503, "AUTH_UNAVAILABLE");
  }
  return value;
}

export async function startDeleteReauthentication(csrfToken: string): Promise<string> {
  const response = await request(
    "/google/reauth-delete",
    unsafe(csrfToken, "POST", "{}"),
  );
  if (!response.ok) return problem(response);
  const document = (await response.json()) as unknown;
  if (!isRecord(document) || !exactKeys(document, ["authorizationUrl"])) {
    throw new AuthRequestError(503, "AUTH_UNAVAILABLE");
  }
  return validateGoogleAuthorizationUrl(document.authorizationUrl);
}

export async function deleteAccount(confirmation: string, csrfToken: string): Promise<void> {
  const response = await accountRequest({
    ...unsafe(csrfToken, "DELETE", JSON.stringify({ confirmation })),
  });
  if (!response.ok) return problem(response);
}
