---
type: Decision
title: "The provider block is the API's verifier configuration, and it is server-side (SPEC-192)"
description: "The `OIDC_*` verifier configuration is API Lambda environment variables and never appears in the browser's document; `OIDC_JWKS_URI` is a field, not derived from the issuer, and the exclusion must not catch the Cognito values Amplify reads."
---

`OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URI`, `OIDC_USERNAME_CLAIM` — API Lambda environment
variables, provisioned by the infrastructure spec and consumed by the auth-boundary spec. **None of
it appears in the browser's document**, because the browser verifies nothing: it sends the ID token
Amplify already holds. The converse holds too — a verifier configured by reading the browser's
document has a client-supplied trust anchor.

**This is a VERIFIER, not an OIDC client.** No code exchange, no PKCE verifier, no client secret, no
redirect URI, no scope list: those belong to Amplify, in the browser, unchanged by this arc. Building
a client here is the shape of error the small field set exists to prevent.

**`OIDC_JWKS_URI` is a field, not a derivation of `OIDC_ISSUER`.** The well-known path is a
convention, not a guarantee, and hard-coding it makes the verifier provider-specific in the one place
that would fail closed and silently.

**The exclusion cuts ONE way only, and that is the whole subtlety.** A test intersects the document's
key set with the verifier's field names plus a case-insensitive substring rule over `oidc`, `issuer`,
`audience`, `jwks` and `secret`. It is guarded in **both** directions: a synthetic key set containing
`issuer` must be flagged (a checker that flags nothing passes the first case forever), and the four
Cognito values Amplify actually reads must **not** be. That third case can fail today. Adding
`clientId` to the forbidden set is the specific mistake — `cognitoUserPoolClientId` survives an
exact-match rule and dies under a substring one — and the visible result is not a failing test but a
Hosted UI round trip that never completes. `cognitoDomain` is likewise **not** a provider-block field:
Amplify POSTs the code exchange to it. The forbidden set is about *the API's trust anchors*, not about
the word Cognito.

Detail: `spec-delivery/SPEC-192`.

## History

### 2026-08-24

- **Settled:** SPEC-192.
