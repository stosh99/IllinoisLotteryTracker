# IllinoisLotteryTracker Authentication Blueprint

Status: code complete; production enablement pending the recorded external release gate

Design cutoff: 2026-08-10

Scope: Google account sign-in, local user identity, revocable web sessions,
authorization boundaries, privacy/security operations, and the frontend
authentication seam

## Authority and terminology

This directory is the implementation specification for the first user
authentication system. When an implementation choice conflicts with an older
project note, this blueprint wins unless the user explicitly changes the
requirement.

"Gmail credentials" means **Sign in with Google using OpenID Connect (OIDC)**.
The application never asks for, receives, or stores a Gmail password. The
initial release accepts any Google Account with a verified email; it does not
require an `@gmail.com` address and does not restrict users to a Google
Workspace domain.

## Scope

The blueprint includes:

- Google OIDC authorization-code flow with `state`, `nonce`, and PKCE S256;
- immutable provider identity keyed by Google's issuer plus `sub` claim;
- local application users with explicit active/suspended status;
- opaque, database-backed, revocable browser sessions;
- CSRF protection for every authenticated state-changing request;
- login, callback, session, logout, session-management, and account-deletion
  contracts;
- exact cookie, CORS, redirect, secret, retention, and logging rules;
- a threat model and fail-closed behavior;
- unit, PostgreSQL, route-contract, and browser-level test requirements;
- ordered work packets for a lower-effort implementation agent.

It explicitly excludes:

- passwords, password recovery, magic links, or security questions;
- Gmail, Drive, Calendar, Contacts, or any other Google API access;
- storing Google access tokens, refresh tokens, authorization codes, or raw ID
  tokens;
- using email as an account key or silently linking accounts by email;
- administrator login or a browser-accessible administrator panel;
- personal ticket/outcome tracking tables and features;
- making rankings private or requiring login to view public data;
- native mobile application authentication.

## Core decisions

1. Use OIDC for authentication, not OAuth scopes for Google data access.
2. Use the backend authorization-code flow. No provider token is exposed to
   React, browser storage, or application cookies.
3. Add PKCE S256 even though the backend is a confidential client. `state`,
   `nonce`, a browser-binding cookie, exact redirects, and one-time database
   consumption remain mandatory defense in depth.
4. Request only `openid email`. Do not request `profile`, `offline_access`, or
   any Gmail scope in version 1.
5. Canonical identity is `(issuer, subject)`, where the persisted issuer is
   `https://accounts.google.com` and subject is Google's case-sensitive `sub`.
   Email is verified display/contact metadata and is never unique.
6. Never auto-link or merge accounts by email. A future second provider needs
   an explicit, recently reauthenticated account-linking design.
7. Issue a 256-bit random opaque application session token. Store only its
   SHA-256 digest in PostgreSQL.
8. Put the session token only in a host-only `Secure`, `HttpOnly`,
   `SameSite=Lax` cookie. Never use `localStorage`, `sessionStorage`, a URL, or
   a JavaScript-readable cookie for the session credential.
9. Serve frontend and API from one public origin. In development, proxy
   `/api` through Vite rather than normalizing a credentialed cross-origin
   deployment into the product architecture.
10. Rankings and methodology remain public. Authentication is needed only for
    future user-owned resources.
11. Provider failure, malformed claims, stale login attempts, unavailable
    secrets, and database uncertainty fail closed. There is no local-password
    fallback.
12. Account deletion removes identities, sessions, and future user-owned
    records. Security events may remain only after their user/session foreign
    keys have been nulled.
13. No database transaction remains open during a Google network request.
14. Recent-authentication initiation is an authenticated, CSRF-protected POST;
    it is not a state-changing GET.
15. Authentication ships disabled and can be enabled only through validated
    server configuration after the release gate; public rankings never depend
    on that flag.
16. Implementation follows the work packets in `07_implementation_work_packets.md`
    one at a time.

## Baseline product policy

The initial session policy is intentionally finite:

| Setting | Initial value |
|---|---:|
| OIDC login-attempt lifetime | 10 minutes |
| Session idle lifetime | 24 hours |
| Session absolute lifetime | 7 days |
| Session database touch interval | 5 minutes |
| Maximum active sessions per user | 5 |
| Recently authenticated window for account deletion | 10 minutes |
| Terminal login-attempt retention | 24 hours |
| Revoked/expired session retention | 30 days |
| Authentication-event retention | 90 days |

These are server-enforced limits, not values trusted from the browser. Any
future "remember me" option requires an explicit security and privacy design;
it is not a configuration-only change.

## Document map

1. [Architecture and decisions](01_architecture_and_decisions.md)
2. [Schema and lifecycle](02_schema_and_lifecycle.md)
3. [OIDC and session flows](03_oidc_and_session_flows.md)
4. [API and frontend contract](04_api_and_frontend_contract.md)
5. [Security, privacy, and operations](05_security_privacy_and_operations.md)
6. [Testing and acceptance](06_testing_and_acceptance.md)
7. [Implementation work packets](07_implementation_work_packets.md)
8. [Read-only authentication audit SQL](auth_audit_queries.sql)

## Integration rule while the API is being built

Do not create a second web server or independently choose a competing API
framework. When implementation starts, first inspect the API files produced by
the live-data integration work and attach the auth router to that application.
The provider, crypto, repository, and session services must remain isolated
from framework-specific request/response code.

At this design cutoff, the FastAPI application is the module
`src/illinois_lottery_tracker/api.py`, not an `api/` package. If that remains
true when implementation begins, add sibling modules such as `auth_api.py`,
`account_api.py`, and `api_dependencies.py`, then include their routers from
`api.py`. Do **not** create `src/illinois_lottery_tracker/api/` beside
`api.py`; that would create a Python import-name collision. If the integration
work has deliberately converted the API into a package by then, follow the new
layout and record the mapping in the implementation status.

The next Alembic revision is chosen at implementation time. If the repository
head is still `0008_review_remediations`, the suggested revision is
`0009_authentication`; if another migration has landed, create the next linear
revision from the then-current head. Never create a second Alembic head.

## Standards basis

- [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)
  defines the server flow, exact redirect, `state`, `nonce`, and ID-token
  processing.
- [Google's ID-token claim reference](https://developers.google.com/identity/openid-connect/reference)
  requires using `sub`, rather than email, as the durable Google identity.
- [RFC 9700: OAuth 2.0 Security Best Current Practice](https://datatracker.ietf.org/doc/html/rfc9700)
  recommends authorization code plus PKCE S256 for web applications and rejects
  open redirects.
- [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
  is the basis for opaque high-entropy session IDs, server-side state,
  expiration, rotation, and cookie attributes.
- [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
  is the basis for session-bound CSRF tokens, origin checks, and custom headers.
- [Google OAuth policy](https://developers.google.com/identity/protocols/oauth2/policies)
  governs production branding, secrets, scopes, homepage, privacy policy, and
  domain ownership.
