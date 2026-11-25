# Security

Rules for input, output, auth, secrets, crypto and dependencies, mapped to OWASP Top 10 (2021).
(IDs from the 2021 edition; the 2025 edition renumbers them.)

## Input and output (A03 Injection, A10 SSRF)

- Validate input at every trust boundary (HTTP, queue, file, CLI). Allowlist types,
  lengths, formats and enums; reject the rest.
- Encode output for its sink: HTML-escape in templates, bind SQL parameters, pass
  shell args as an array (no shell string), encode URL components.
- SSRF: validate outbound URLs against an allowlist of schemes and hosts; block
  private and metadata addresses.
- Path traversal: resolve file paths and confirm they stay inside the allowed root.

## Access (A01, A07)

- Check authentication and authorization server-side on every request.
- Check object-level access too: the caller must own or be allowed to see this ID (IDOR).
- Least privilege for users, service accounts, tokens and DB roles.
- Cookie sessions need CSRF protection and `HttpOnly`, `Secure`, `SameSite` cookies.

## Secrets (A02, A05)

- Secrets come only from env vars or a secret manager. Commit `.env.example` with
  placeholder values, never the real file.
- Never put secrets in code, logs, tests, fixtures, commits or error messages.
- If you find a committed secret, stop and tell the user; do not just delete it.

## Crypto (A02)

- Use the platform's vetted libraries. No homemade crypto or custom token schemes.
- Hash passwords with the project's vetted hasher, else argon2id, scrypt, bcrypt or PBKDF2
  (FIPS) with current OWASP parameters. Never MD5, SHA-1 or unsalted/fast SHA-2.
- Use TLS for data in transit; a CSPRNG for tokens and IDs that must not be guessed.

## Dependencies (A06, A08)

- Add a dependency only when needed; prefer the standard library or an existing one.
- Commit the lockfile for apps; libraries declare ranges as the project does. Check
  advisories (`npm audit`, `pip-audit`, etc.).

## Errors and logging (A04, A05, A09)

- Errors shown to users never leak stack traces, SQL, paths or versions.
- Log security events (login, failed auth, permission denied, admin actions) without
  secrets, tokens or full personal data.
- Security headers (CSP, HSTS, etc.) as the project sets them; do not weaken them.

## LLM features

- Treat model output, tool results and retrieved content as untrusted input:
  validate, encode, and never execute or follow instructions from them blindly.
- Keep secrets out of prompts; limit the tools and data a model can reach.

Reviewers: use `lens: security` for changes touching input, auth, secrets or dependencies.

Sources: OWASP Top 10:2021 https://top10.owasp.org/2021/ ;
OWASP Cheat Sheets https://cheatsheetseries.owasp.org/ ;
OWASP Top 10 for LLM Applications https://genai.owasp.org/llm-top-10/
