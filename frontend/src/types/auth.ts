export interface AuthUser {
  id: string;
  email: string;
  emailVerified: true;
}

export interface AuthSessionTimes {
  authenticatedAt: string;
  idleExpiresAt: string;
  absoluteExpiresAt: string;
}

export interface DisabledAuthSession {
  authenticationAvailable: false;
  authenticated: false;
  user: null;
  session: null;
  csrfToken: null;
}

export interface AnonymousAuthSession {
  authenticationAvailable: true;
  authenticated: false;
  user: null;
  session: null;
  csrfToken: null;
}

export interface AuthenticatedAuthSession {
  authenticationAvailable: true;
  authenticated: true;
  user: AuthUser;
  session: AuthSessionTimes;
  csrfToken: string;
}

export type AuthSessionResponse =
  | DisabledAuthSession
  | AnonymousAuthSession
  | AuthenticatedAuthSession;

export type AuthViewState =
  | { status: "loading" }
  | { status: "disabled"; session: DisabledAuthSession }
  | { status: "anonymous"; session: AnonymousAuthSession }
  | { status: "authenticated"; session: AuthenticatedAuthSession }
  | { status: "unavailable" };

export interface ManagedSession {
  id: string;
  current: boolean;
  createdAt: string;
  lastSeenAt: string;
  idleExpiresAt: string;
  absoluteExpiresAt: string;
}

export interface SessionListResponse {
  sessions: ManagedSession[];
}

export interface AuthProblem {
  type: "about:blank";
  title: string;
  status: number;
  code: string;
  requestId: string;
}

export interface AccountResponse {
  id: string;
  email: string;
  emailVerified: true;
  createdAt: string;
}
