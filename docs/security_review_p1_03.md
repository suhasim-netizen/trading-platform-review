# Security sign-off checklist — P1-03 (concrete adapter authentication)

The Tech Lead implements OAuth in the vendor-specific package only. Sign-off when **all** are true:

1. **Isolation (broker abstraction)**  
   - No broker vendor name, URL, or SDK type appears outside `src/brokers/<vendor>/`.  
   - No strategy/OMS/API logic imports `brokers/<vendor>` modules directly (registry + `BrokerAdapter` only).

2. **Secrets (platform OAuth app settings)**  
   - `BROKER_CLIENT_ID`, `BROKER_CLIENT_SECRET`, `BROKER_REDIRECT_URI`, and broker base URLs are loaded only via `Settings` / environment injection.  
   - No secrets are hard-coded in source, tests, examples, or docs.  
   - `.env` is excluded by `.gitignore` and no `.env.*` files with real values are committed.

3. **Transport security (TLS-only)**  
   - All OAuth and API calls use HTTPS/WSS (TLS).  
   - Certificate validation is not disabled; no `verify=False` patterns or equivalent.  
   - Redirect URI matches the broker-registered value **exactly** (scheme/host/path).

4. **Token handling (never leak)**  
   - Access tokens, refresh tokens, authorization codes, and client secrets are never logged (including debug logs).  
   - Tokens are never included in exception messages returned to API callers.  
   - Any HTTP tracing/redaction middleware is configured to redact `Authorization`, cookies, and broker-specific token fields.

5. **Tenant scope (hard boundary)**  
   - Every auth operation receives or resolves `tenant_id`; no cross-tenant token reuse is possible.  
   - Adapter loads and persists token material **only** by `(tenant_id, broker, account_id)` (or equivalent tenant-linked key).  
   - No global/singleton token cache without a `tenant_id` prefix.

6. **Storage security (encrypted at rest)**  
   - Token material persisted only through the tenant-scoped credential path and is encrypted at rest using `TOKEN_ENCRYPTION_KEY` (Fernet) or KMS envelope encryption.  
   - Database rows store ciphertext + non-sensitive metadata only; no plaintext token columns.  
   - Decryption occurs only in-memory inside the adapter/auth layer for the requesting tenant.

7. **Error hygiene (typed, non-leaky)**  
   - Failures raise typed errors (`BrokerAuthError`, `BrokerTokenExpiredError`, `BrokerNetworkError`, etc.).  
   - No raw HTTP response bodies/headers are surfaced to API callers.  
   - Retry/backoff does not amplify rate-limit failures or leak request data in logs.

8. **CI/testing gates (mock-based)**  
   - Unit tests mock HTTP; they do not call real broker endpoints.  
   - CI runs with fake responses only; no real broker credentials in VCS or pipeline logs.  
   - Contract tests verify two-tenant isolation: tenant A cannot read/refresh tenant B tokens and cannot place orders with tenant B credentials.

9. **Operational controls (minimum)**  
   - Rate limiting is keyed by `tenant_id` for auth endpoints to prevent abuse.  
   - Audit logs include `tenant_id` for every auth/token write event; entries without `tenant_id` are rejected.  
   - Any manual “break-glass” admin path is out-of-band, separately authenticated, and audited (not part of default tenant flow).

**Security Architect:** Security Architect — reviewed post-implementation — 2026-04-15

*Retrospective sign-off. All checklist items verified against code and test execution results.*

