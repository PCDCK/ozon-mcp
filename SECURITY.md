# Security policy

## Supported versions

ozon-mcp is in active development. Security fixes are applied to the latest
minor release on `main` only.

| Version | Supported |
|---------|-----------|
| 0.6.x   | ✅        |
| < 0.6   | ❌        |

## Reporting a vulnerability

If you discover a security issue, **please do not open a public GitHub issue**.

Instead, open a private report via the GitHub Security Advisory workflow:
<https://github.com/PCDCK/ozon-mcp/security/advisories/new>. Include:

1. A description of the issue and its potential impact
2. Steps to reproduce
3. The affected version(s)
4. Any suggested mitigation

We aim to respond within 5 business days and to issue a patch release within
14 days for critical issues.

## Threat model

ozon-mcp is invoked locally by an AI agent over MCP stdio. Its threat surface
is small but worth being explicit about:

- **Credentials in env vars** — Seller and Performance API credentials are
  read from environment variables and wrapped in `pydantic.SecretStr`. They
  are never logged, never returned in tool responses, and only ever sent to
  `https://api-seller.ozon.ru` and `https://api-performance.ozon.ru` in the
  Authorization headers / OAuth token request body.
- **No persistent storage** — the server reads bundled OpenAPI specs and
  YAML knowledge files from package resources. It writes nothing to disk and
  caches OAuth tokens only in process memory.
- **stdout vs stderr** — all log output goes to stderr because stdout is
  reserved for the MCP framing protocol. Mixing them up is a real DoS risk
  for stdio servers; we use `logging.basicConfig(stream=sys.stderr, force=True)`.
- **Schema-driven validation before execution** — `ozon_call_method` validates
  every payload against the resolved JSON Schema using `jsonschema` Draft
  2020-12 before sending. This catches typos and wrong types early but does
  NOT stop a maliciously valid request from being sent. Treat the agent's
  decisions as you would any code that holds your credentials.
- **Rate limit enforcement** — the client-side limiter (`aiolimiter`)
  protects Ozon and your account, not against compromise. It will not stop
  an attacker who has access to your credentials.

## Out of scope

- Attacks that require local code execution on the machine running the
  server (the credentials are already accessible to such an attacker)
- Misuse of the agent itself (prompt injection that causes the LLM to call
  destructive endpoints) — this is a higher-level concern and should be
  handled by the agent platform's permission model

## Best practices for operators

- Use a dedicated Ozon API key with the minimum permissions needed
- Rotate keys at least quarterly
- Run ozon-mcp under your own user account, not as root
- Review the curated knowledge YAML files (`workflows.yaml`, `quirks.yaml`)
  in this repo before relying on them for production decisions
