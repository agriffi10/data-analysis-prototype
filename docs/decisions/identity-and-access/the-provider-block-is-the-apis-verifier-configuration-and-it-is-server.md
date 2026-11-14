---
type: Decision
title: "The provider block is the API's verifier configuration, and it is server-side (SPEC-192)"
description: "The `OIDC_*` verifier configuration is API Lambda environment variables and never appears in the browser's document; `OIDC_JWKS_URI` is a field, not derived from the issuer, and the exclusion must not catch the Cognito values Amplify reads. **`OIDC_AUDIENCE` is a set** (257): a comma-separated list of app client ids, a token's `aud` must be one of them, and an empty element is refused at both ends, because an empty set refuses every token and the join is on commas."
---

`OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URI`, `OIDC_USERNAME_CLAIM` — API Lambda environment
variables, provisioned by the infrastructure spec and consumed by the auth-boundary spec. **None of
it appears in the browser's document**, because the browser verifies nothing: it sends the ID token
Amplify already holds. The converse holds too — a verifier configured by reading the browser's
document has a client-supplied trust anchor.

**This is a VERIFIER, not an OIDC client.** No code exchange, no PKCE verifier, no client secret, no
redirect URI, no scope list: those belong to Amplify, in the browser, unchanged by this arc. Building
a client here is the shape of error the small field set exists to prevent. *(Marked 2026-11-13:
since SPEC-257 the portal's Next.js server is also an OIDC client, a confidential one with its own
secret, and the browser's Amplify stays one until SPEC-262. The API is still neither: it verifies.)*

**`OIDC_AUDIENCE` is a set of app client ids** (rewritten 2026-11-13 for SPEC-257). The portal
server signs in with a confidential client of its own, so its ID tokens carry that client's id in
`aud`, while the browser's carry the public client's. The API accepts both: the `api` module takes
a list and renders it comma-separated, and the verifier splits it back into a set and passes it to
the JWT library as the accepted audiences. Both ends refuse an empty element. Plan-time validation
refuses an empty list and an id that is empty or holds a comma, and the verifier's configuration
refuses an empty element at cold start, because an empty set refuses every token and a stray comma
would split one id into two. The merge that widens the list waits until the function runs code that
reads a list, because the old code compared `aud` to the whole string.

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

### 2026-11-13

- **Changed:** SPEC-257 made `OIDC_AUDIENCE` a set of app client ids, so the API accepts the portal
  server's confidential client beside the browser's, and marked the verifier-not-client paragraph
  now that the portal server is an OIDC client.

### 2026-08-24

- **Settled:** SPEC-192.
