-- IllinoisLotteryTracker authentication audit queries.
-- Read-only. Queries return counts/groups only and intentionally avoid PII.

-- A01: local user status integrity. Expected 0.
SELECT count(*) AS invalid_user_status_rows
FROM app_users
WHERE NOT (
  (status = 'active' AND suspended_at IS NULL
   AND suspension_reason_code IS NULL)
  OR
  (status = 'suspended' AND suspended_at IS NOT NULL
   AND suspension_reason_code IN (
     'abuse', 'suspected_compromise', 'legal_request', 'user_request',
     'test_account', 'operator_correction'
   ))
)
   OR updated_at < created_at
   OR (last_login_at IS NOT NULL AND last_login_at < created_at)
   OR (suspended_at IS NOT NULL AND suspended_at < created_at);

-- A02: identity invariant failures. Expected 0.
SELECT count(*) AS invalid_identity_rows
FROM user_identities
WHERE provider <> 'google'
   OR issuer <> 'https://accounts.google.com'
   OR NOT email_verified
   OR NULLIF(btrim(subject), '') IS NULL
   OR subject !~ '^[!-~]+$'
   OR octet_length(subject) > 255
   OR NULLIF(btrim(email), '') IS NULL
   OR email <> btrim(email)
   OR last_authenticated_at < created_at;

-- A03: duplicate canonical identities. Constraint-backed; expected 0.
SELECT count(*) AS duplicate_identity_groups
FROM (
  SELECT 1
  FROM user_identities
  GROUP BY issuer, subject
  HAVING count(*) > 1
) duplicate_groups;

-- A04: more than one identity for a user's provider. Expected 0.
SELECT count(*) AS duplicate_user_provider_groups
FROM (
  SELECT 1
  FROM user_identities
  GROUP BY user_id, provider
  HAVING count(*) > 1
) duplicate_groups;

-- A05: digest-length failures. Expected 0.
SELECT
  (SELECT count(*) FROM oidc_login_attempts
   WHERE octet_length(state_digest) <> 32
      OR octet_length(browser_binding_digest) <> 32
      OR octet_length(nonce_digest) <> 32) AS invalid_attempt_digests,
  (SELECT count(*) FROM user_sessions
   WHERE octet_length(token_digest) <> 32) AS invalid_session_digests;

-- A06: attempt lifecycle/time inconsistencies. Expected 0.
SELECT count(*) AS invalid_attempt_lifecycle_rows
FROM oidc_login_attempts
WHERE provider <> 'google'
   OR return_path NOT IN ('/', '/account')
   OR NULLIF(btrim(pkce_verifier_ciphertext), '') IS NULL
   OR pkce_verifier_ciphertext !~ '^v1[.][A-Za-z0-9_-]{152}$'
   OR char_length(pkce_verifier_ciphertext) <> 155
   OR expires_at <= created_at
   OR intent NOT IN ('login', 'reauth_delete')
   OR ((intent = 'login') <> (expected_user_id IS NULL))
   OR ((intent = 'login') <> (expected_session_id IS NULL))
   OR NOT (
     (status = 'pending' AND claimed_at IS NULL AND completed_at IS NULL
      AND failure_code IS NULL)
     OR
     (status = 'exchanging' AND claimed_at IS NOT NULL AND completed_at IS NULL
      AND failure_code IS NULL)
     OR
     (status = 'succeeded' AND claimed_at IS NOT NULL
      AND completed_at IS NOT NULL AND failure_code IS NULL)
     OR
     (status IN ('failed', 'denied') AND claimed_at IS NOT NULL
      AND completed_at IS NOT NULL AND failure_code IS NOT NULL)
     OR
     (status IN ('expired', 'superseded') AND claimed_at IS NULL
      AND completed_at IS NOT NULL AND failure_code IS NOT NULL)
   )
   OR (claimed_at IS NOT NULL AND claimed_at < created_at)
   OR (completed_at IS NOT NULL AND completed_at < created_at)
   OR (claimed_at IS NOT NULL AND completed_at IS NOT NULL
       AND completed_at < claimed_at)
   OR (failure_code IS NOT NULL AND failure_code NOT IN (
     'user_denied', 'attempt_expired', 'attempt_superseded',
     'invalid_callback', 'provider_unavailable', 'token_exchange_failed',
     'token_validation_failed', 'attempt_decryption_failed',
     'exchange_abandoned', 'identity_mismatch', 'account_unavailable'
   ));

-- A06b: a reauthentication attempt references a session for another user.
-- Foreign keys cover missing rows; expected 0.
SELECT count(*) AS mismatched_reauth_session_users
FROM oidc_login_attempts attempt
JOIN user_sessions session ON session.id = attempt.expected_session_id
WHERE attempt.intent = 'reauth_delete'
  AND session.user_id <> attempt.expected_user_id;

-- A07: session lifecycle/time inconsistencies. Expected 0.
SELECT count(*) AS invalid_session_lifecycle_rows
FROM user_sessions
WHERE last_seen_at < created_at
   OR last_seen_at > idle_expires_at
   OR idle_expires_at <= created_at
   OR idle_expires_at > absolute_expires_at
   OR ((revoked_at IS NULL) <> (revocation_reason IS NULL))
   OR (revoked_at IS NOT NULL AND revoked_at < created_at)
   OR (revocation_reason IS NOT NULL AND revocation_reason NOT IN (
     'logout', 'logout_all', 'session_limit', 'account_suspended',
     'account_deleted', 'security_event', 'replaced', 'expired_idle',
     'expired_absolute'
   ));

-- A08: active sessions attached to suspended users. Expected 0 after the
-- suspension transaction and maintenance.
SELECT count(*) AS active_suspended_user_sessions
FROM user_sessions session
JOIN app_users app_user ON app_user.id = session.user_id
WHERE app_user.status = 'suspended'
  AND session.revoked_at IS NULL
  AND session.idle_expires_at > now()
  AND session.absolute_expires_at > now();

-- A09: users exceeding the initial five-active-session policy. Expected 0.
-- If the reviewed production setting changes, update this policy constant in
-- the audit runner and its recorded evidence at the same time.
SELECT count(*) AS users_over_active_session_limit
FROM (
  SELECT 1
  FROM user_sessions
  WHERE revoked_at IS NULL
    AND idle_expires_at > now()
    AND absolute_expires_at > now()
  GROUP BY user_id
  HAVING count(*) > 5
) violating_users;

-- A10: maintenance backlog counts. Review; expected 0 immediately after a
-- successful maintenance run.
SELECT
  count(*) FILTER (
    WHERE (status = 'pending' AND expires_at <= now())
       OR (status = 'exchanging'
           AND expires_at + interval '30 seconds' <= now())
  ) AS overdue_attempts,
  count(*) FILTER (
    WHERE status IN ('succeeded', 'failed', 'denied', 'expired', 'superseded')
      AND completed_at < now() - interval '24 hours'
  ) AS terminal_attempts_past_retention
FROM oidc_login_attempts;

-- A11: session retention backlog. Review; expected 0 after maintenance.
SELECT count(*) AS terminal_sessions_past_retention
FROM user_sessions
WHERE (
    revoked_at IS NOT NULL
    OR idle_expires_at <= now()
    OR absolute_expires_at <= now()
  )
  AND LEAST(
    COALESCE(revoked_at, 'infinity'::timestamptz),
    idle_expires_at,
    absolute_expires_at
  ) < now() - interval '30 days';

-- A12: event retention backlog. Expected 0 after maintenance.
SELECT count(*) AS auth_events_past_retention
FROM auth_events
WHERE occurred_at < now() - interval '90 days';

-- A13: forbidden/suspicious event detail keys. Expected 0.
SELECT count(*) AS forbidden_event_detail_keys
FROM auth_events
WHERE details ?| ARRAY[
  'email', 'subject', 'hosted_domain', 'ip', 'ip_address', 'user_agent',
  'cookie', 'set_cookie', 'authorization', 'code', 'state', 'nonce',
  'pkce_verifier', 'code_verifier', 'code_challenge', 'id_token',
  'access_token', 'refresh_token', 'client_secret', 'session_token'
];

-- A13b: event detail keys outside the positive allowlist. Expected 0.
SELECT count(*) AS unexpected_event_detail_keys
FROM auth_events event
WHERE jsonb_typeof(event.details) = 'object'
  AND EXISTS (
  SELECT 1
  FROM jsonb_object_keys(event.details) AS detail_key(key)
  WHERE detail_key.key NOT IN (
    'provider', 'intent', 'sessions_revoked', 'http_status_class',
    'duration_bucket_ms'
  )
);

-- A14: event-shape invariant failures. Expected 0.
SELECT count(*) AS invalid_auth_event_rows
FROM auth_events
WHERE event_type NOT IN (
    'login_started', 'login_succeeded', 'login_failed',
    'reauth_started', 'reauth_succeeded', 'reauth_failed',
    'logout', 'logout_all', 'session_revoked', 'session_rejected',
    'account_suspended', 'account_reactivated', 'account_deleted'
  )
  OR outcome NOT IN ('success', 'failure', 'info')
  OR (reason_code IS NOT NULL AND NULLIF(btrim(reason_code), '') IS NULL)
  OR (reason_code IS NOT NULL AND reason_code NOT IN (
    'user_denied', 'attempt_expired', 'attempt_superseded',
    'invalid_callback', 'provider_unavailable', 'token_exchange_failed',
    'token_validation_failed', 'attempt_decryption_failed',
    'exchange_abandoned', 'identity_mismatch', 'account_unavailable',
    'session_limit', 'account_suspended', 'security_event', 'replaced',
    'expired_idle', 'expired_absolute', 'session_invalid', 'csrf_invalid',
    'rate_limited', 'abuse', 'suspected_compromise', 'legal_request',
    'user_request', 'test_account', 'operator_correction', 'review_cleared',
    'test_complete'
  ))
  OR details IS NULL
  OR jsonb_typeof(details) <> 'object'
  OR octet_length(details::text) > 2048;

-- A15: duplicate attempt browser bindings. Constraint-backed; expected 0.
SELECT count(*) AS duplicate_browser_binding_groups
FROM (
  SELECT 1
  FROM oidc_login_attempts
  GROUP BY browser_binding_digest
  HAVING count(*) > 1
) duplicate_groups;

-- A16: aggregate event counts for operational review; no PII.
SELECT event_type, outcome, COALESCE(reason_code, '(none)') AS reason_code,
       count(*) AS event_count
FROM auth_events
WHERE occurred_at >= now() - interval '24 hours'
GROUP BY event_type, outcome, COALESCE(reason_code, '(none)')
ORDER BY event_type, outcome, reason_code;
