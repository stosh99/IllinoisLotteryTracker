# Architecture and Decisions

## Goals

The authentication system must answer four questions reliably:

1. Did Google authenticate this browser for this application?
2. Which stable local user owns the authenticated Google identity?
3. Is the presented application session current, unexpired, and unrevoked?
4. Is the authenticated user authorized to access the requested user-owned
   object?

The design optimizes for a small public web application with one deployment,
one PostgreSQL database, and no payment or administrative interface. It still
treats personal play history as private user data.

## Recommended deployment topology

Production uses one browser origin:

```text
Browser: https://tracker.example/
                    |
              TLS reverse proxy
               /             \
       static Vite build    /api/v1/*
                              |
                        Python API
                         /       \
                  PostgreSQL    Google OIDC
```

The exact domain is deliberately not selected in this blueprint. It must be a
domain the operator owns and can verify with Google.

One origin materially simplifies session cookies, CSRF, CORS, and browser
privacy behavior. Production must not use wildcard CORS, cross-site session
cookies, or tokens copied between origins.

Development also presents one browser origin. Vite proxies `/api` to the local
API process:

```text
Browser -> http://localhost:5173
              /          \
       Vite assets      /api proxy -> http://127.0.0.1:8000
```

Use one host spelling consistently. `localhost` and `127.0.0.1` must not be
mixed in browser URLs, redirect URIs, or cookie tests.

## Trust boundaries

| Boundary | Trusted facts | Never trust directly |
|---|---|---|
| Browser to API | TLS transport; browser-enforced cookie attributes | user ID, email, role, return URL, session token contents |
| Google callback to API | nothing until state/PKCE/token validation succeeds | query `code`, `state`, `iss`, or error text |
| Google ID token | verified signature and validated standard claims | decoded-but-unverified claims, email as identity, arbitrary extra claims |
| API to PostgreSQL | constraints and committed rows | data read before checking status/expiry/ownership |
| Reverse proxy to API | forwarded headers only from configured proxy hops | arbitrary `Host`, `X-Forwarded-*`, or client IP headers |
| Logs/telemetry | allowlisted reason codes and correlation IDs | secrets, tokens, OAuth codes, state, nonce, email, provider payloads |

## Authentication versus authorization

Authentication maps a verified Google identity to `app_users.id` and creates
a local session. Authorization is separate:

- public rankings require no user and perform no authentication lookup merely
  because an auth cookie is present;
- a separate session request or a future optional-principal route can
  personalize chrome without changing public ranking data;
- future ticket/outcome endpoints require an active principal;
- every user-owned query includes `user_id = principal.user_id`;
- a resource owned by another user returns `404`, not an existence-revealing
  `403`;
- no client-supplied `userId` can override the principal;
- no browser-accessible administrator role or route is added in version 1.

## Component boundaries

The implementation should use an `auth` package beneath the existing Python
package. Names may be adjusted to the API structure that lands first, but the
responsibilities may not be collapsed into route functions.

```text
src/illinois_lottery_tracker/
  auth/
    config.py          validated authentication settings
    types.py           claims, principals, and result value objects
    crypto.py          random tokens, digests, PKCE, HMAC, key derivation
    provider.py        provider protocol and fake-provider seam
    google_oidc.py     Google-specific OIDC client
    repository.py      authentication persistence only
    service.py         login/session/account orchestration
    csrf.py            session-bound CSRF derivation and validation
  auth_models.py       SQLAlchemy models imported into Base metadata
  auth_api.py          FastAPI authentication router
  account_api.py       FastAPI account router
  api_dependencies.py current/required principal dependencies
  api.py               existing app; includes the new routers
```

This tree matches the repository at the design cutoff. Because `api.py`
already owns the import name `illinois_lottery_tracker.api`, do not also create
an `api/` directory unless a prior integration packet has intentionally moved
the module into a package and updated every caller/test. Route filenames may
follow a newer established layout, but there must still be one FastAPI app.

Frontend additions should likewise remain narrow:

```text
frontend/src/
  types/auth.ts
  services/auth.ts
  context/AuthSessionProvider.tsx
  hooks/useAuthSession.ts
  components/SignInControl.tsx
  components/AccountMenu.tsx
  pages/AccountPage.tsx
```

Do not place Google client logic in React. The sign-in control navigates to the
backend start endpoint.

At the design cutoff the frontend has no client router. AU-06 should add the
current stable `react-router-dom` (or reuse a router deliberately introduced by
the integration work), with exactly these initial application routes:

```text
/          public rankings
/account   authenticated account, sessions, and deletion controls
```

The deployment serves `index.html` for those frontend routes and static 404s,
but never rewrites `/api/*` failures to HTML. Do not add a placeholder
`/my-tickets` route during authentication work.

## OIDC client library decision

Use a maintained OIDC/OAuth client library; do not hand-write JWT signature or
JWK rotation logic. For a FastAPI/Starlette API, the preferred implementation
is the current stable Authlib release compatible with the selected framework,
using its OIDC metadata and token-validation support plus HTTPX for the token
exchange.

Important constraints:

- use the lower-level/provider adapter behind `GoogleOidcProvider`;
- do not use Starlette's signed-cookie `SessionMiddleware` as the application
  session store;
- persist OIDC attempt state in the tables specified by this blueprint;
- keep the current synchronous FastAPI/SQLAlchemy execution model unless the
  API integration has deliberately changed it; a callback must use separate,
  short database contexts on either side of the bounded provider call;
- pin the resolved dependency versions and run a dependency audit in CI;
- tests use a fake provider and local fake OIDC metadata/JWKS; CI never calls
  Google.

If the API integration selects another maintained OIDC library, changing the
library is acceptable only if every flow and negative test in this blueprint
still passes. The security protocol is not negotiable.

## Google data minimization

The authorization request contains only:

```text
response_type=code
scope=openid email
state=<one-time random value>
nonce=<one-time random value>
code_challenge=<S256 challenge>
code_challenge_method=S256
client_id=<configured client ID>
redirect_uri=<exact configured callback>
```

Do not request:

- `access_type=offline`;
- `include_granted_scopes=true`;
- `profile` in version 1;
- `hd` restrictions;
- Gmail or other Google API scopes.

The token endpoint necessarily returns a short-lived Google access token with
the ID token. The provider adapter discards it after validating the ID token.
It is never returned, persisted, logged, cached, or attached to the local
session. No refresh token should be returned because offline access is not
requested; receiving one unexpectedly is treated as sensitive data and it is
discarded without logging.

Do not call Google's UserInfo, token-info, Gmail, or any other Google API. The
validated ID token supplies the only provider identity metadata version 1
needs.

## Stable identity decision

Persist this canonical identity tuple:

```text
provider = "google"
issuer   = "https://accounts.google.com"
subject  = verified ID-token `sub`
```

Google's legacy issuer spelling `accounts.google.com` may be accepted by the
OIDC validator if the library supports it, but it is canonicalized before
persistence. `subject` is case-sensitive and may be up to 255 ASCII
characters; require 1–255 printable non-whitespace ASCII bytes (`0x21` through
`0x7e`) and never trim/case-normalize it.

Email must be present and `email_verified` must be true. Email is retained for
account display and support only. It is not unique, is never used to merge two
users, and cannot be used to recover or assume an account.

The product accepts non-Gmail Google Accounts because the authenticated
identity is the Google `sub`, not Google's continuing authority over the
mailbox. The application must not use the displayed email for security alerts
or sensitive recovery without a separate email-verification design.

Version 1 has no identity-rebinding or provider-loss recovery path. Support
must never attach a different Google subject merely because its email matches.
An externally verified privacy/support process may use the guarded UUID-only
operator controls to suspend or delete an account, but linking a replacement
identity requires a separate, recently authenticated design and migration.

Claim validation rejects leading/trailing Unicode whitespace; Unicode control,
format, or surrogate characters (`Cc`, `Cf`, `Cs`); an empty value; or a value
longer than 320 Unicode code points. Store the verified value for display after
Unicode NFC normalization, applying the same checks again after normalization.
Do not apply a narrow historical email regex: the value is display metadata,
not an address used for local authentication or delivery. Do not store a
second normalized/search email column in version 1. React's normal text
escaping remains mandatory.

## Session decision

The application session is not a JWT. It is an opaque random credential:

```text
raw token:       32 CSPRNG bytes, base64url without padding
browser stores:  raw token in session cookie only
database stores: SHA-256(raw token), exactly 32 bytes
```

The digest needs no password hash because the source token has 256 bits of
entropy. A database leak does not reveal active browser credentials. The
server can revoke a single session, all sessions, or every session for a
suspended/deleted user immediately.

The principal is reconstructed from the session and current user/identity
rows on each protected request. It is not trusted from frontend state.

The application does not poll Google during local-session use. Google account
closure, provider-side app disconnection, or a newly changed Google security
state therefore does not invalidate an already-issued local session in real
time; the seven-day absolute deadline and local revocation controls bound that
tradeoff. A future requirement for immediate provider revocation awareness
needs a separate provider-session design.

## Framework integration decision

The other integration agent owns the initial API framework and rankings route.
Authentication must attach to that server. Before AU-01 begins, record:

- API application object/factory location;
- router/module conventions;
- request-scoped SQLAlchemy session convention;
- error envelope convention;
- correlation/request ID convention;
- production reverse-proxy/static-file plan.

If any are missing, AU-01 may define the narrow shared convention, but it
must not create a second process or duplicate database configuration.
