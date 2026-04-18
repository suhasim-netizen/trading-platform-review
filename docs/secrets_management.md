# Secrets management (Phase 1 baseline)

This document defines the **environment contract**, the **per-tenant secrets model**, and the minimum standards for **storage, rotation, and leakage prevention**.

## Scope and separation of concerns

- **Platform-level settings (environment variables):**
  - Broker OAuth *application* settings: `BROKER_CLIENT_ID`, `BROKER_CLIENT_SECRET`, `BROKER_REDIRECT_URI`, and broker base URLs.
  - Infrastructure secrets: `DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`.
  - Deployment controls: `ENVIRONMENT`, `LOG_LEVEL`, `ALLOWED_TENANT_IDS`.
- **Per-tenant broker sessions (database, encrypted at rest):**
  - OAuth tokens are tenant-scoped and represented in code by `AuthToken` (includes `tenant_id`).
  - Initial auth handshake inputs are represented by `BrokerCredentials` (includes `tenant_id` and optional `authorization_code`).

This split is intentional: **the platform’s OAuth app credentials live in env/secret store; the tenant’s access/refresh tokens live encrypted in the database and are never shared across tenants.**

## Local development

- **Use `.env`** at the repo root; it is excluded via `.gitignore` and must not be committed.
- **Start from `.env.example`**; fill in only dev values.
- **Generate required secrets:**
  - `SECRET_KEY`: 32+ characters.
    - Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
  - `TOKEN_ENCRYPTION_KEY`: Fernet key (urlsafe base64, typically 44 chars).
    - Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## CI/CD

- **Inject secrets** via CI secret variables or secret-store references; never commit `.env`, `.env.*`, or raw tokens.
- **No live broker credentials in CI.**
  - Unit tests must use mocked HTTP responses.
  - Integration tests (if any) must use simulated brokers or sandbox credentials in a non-production tenant namespace.
- **Least privilege:** CI runner identities must not be able to read production secret namespaces.

## Production

Use a managed secret store and inject values into the runtime environment **without changing application code** (the app reads env vars via `src/config.py`).

Recommended options:

- **AWS Secrets Manager**
  - Store platform secrets under environment scope, e.g. `/${ENVIRONMENT}/platform/...`.
  - Use IAM policies to restrict read access to the application runtime role only.
- **HashiCorp Vault**
  - KV v2 paths under `secret/data/${ENVIRONMENT}/platform/...`.
  - Prefer short-lived identities (Kubernetes auth, AWS auth) over static Vault tokens.
- **Azure Key Vault**
  - Per-environment vault or strict secret naming conventions + RBAC.

### Migration path (flat `.env` → managed store)

- **Phase 1:** `.env` for local dev only; in hosted environments inject env vars from CI/CD.
- **Phase 2:** move platform secrets into a managed store, still delivered as environment variables at runtime (no code changes).
- **Phase 3 (optional):** enable secret-store-native fetch by sidecar/agent (e.g., Vault Agent) with templated env injection.

## Rotation policy

- **Broker OAuth tokens (tenant-scoped):**
  - Access tokens follow broker TTL; refresh via `BrokerAdapter.refresh_token`.
  - Refresh-token rotation follows broker policy; on refresh failures require tenant re-auth.
- **`BROKER_CLIENT_SECRET` (platform OAuth app):**
  - Rotate quarterly or on incident; coordinate with broker app settings; deploy new secret with overlapping validity where broker allows.
- **`SECRET_KEY` (app signing/session material):**
  - Rotate quarterly or on incident; design a session invalidation window (expect forced re-login).
- **Database credentials (`DATABASE_URL` password):**
  - Rotate quarterly or on personnel change; use managed DB auth where possible.
- **`TOKEN_ENCRYPTION_KEY`:**
  - Rotating requires re-encrypting stored broker credential ciphertext blobs.
  - Implement a controlled rewrap job and maintenance window; keep dual-decrypt capability during the cutover if required.

## NEVER (hard rules)

- Never log **access tokens**, **refresh tokens**, **client secrets**, **authorization codes**, or **ciphertext blobs**.
- Never store plaintext broker tokens in the database.
- Never include secrets in error payloads returned from APIs (no raw HTTP bodies, no headers).
- Never accept a `tenant_id` from untrusted request bodies/queries to select credentials; `tenant_id` must come from the authenticated identity context.

## Encryption-at-rest expectations (broker credential rows)

For the tenant credential table (commonly named `broker_credentials` / `tenant_broker_credentials`):

- Store **ciphertext + non-sensitive metadata only** (e.g., `tenant_id`, `broker`, `account_id`, `created_at`, `rotated_at`, `expires_at`).
- Encrypt token material using `TOKEN_ENCRYPTION_KEY` (Fernet) or a KMS envelope scheme; keys must never appear in logs.
- Decrypt **only in memory** inside the adapter/auth layer and only for the requesting tenant.
- Prefer storing **token hashes** for correlation/debugging (optional) rather than token values.

## Field name coordination note

This repo uses the env var names in `.env.example` and the aliases in `src/config.py` (e.g., `ENVIRONMENT`, `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`). If these names change, update both files together and treat it as a breaking change for deployment manifests.
