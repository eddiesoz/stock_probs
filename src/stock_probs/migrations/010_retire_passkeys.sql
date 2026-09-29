-- Schema v10 retires WebAuthn credentials after the application moves to authenticator codes.
-- Credential rows remain as historical audit records, but no active credential or passkey-issued
-- session survives the cutover. The migration runner wraps this script in BEGIN IMMEDIATE.
UPDATE passkeys
SET revoked_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE revoked_at IS NULL;

UPDATE sessions
SET revoked_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'),
    revocation_reason = 'passkey-retired'
WHERE revoked_at IS NULL
  AND (
      auth_method = 'passkey'
      OR mfa_method = 'passkey'
      OR last_passkey_at IS NOT NULL
  );
