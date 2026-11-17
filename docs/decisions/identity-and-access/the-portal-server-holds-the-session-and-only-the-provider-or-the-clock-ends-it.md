---
type: Decision
title: "The portal server holds the session, and only the provider or the clock ends it (SPEC-257)"
description: "**The portal's Next.js server holds the session** in DynamoDB under the SHA-256 of an opaque `__Host-dq_session` cookie, **read by a name trimmed of space and tab only**: `trim()` strips U+00A0, and a cookie named 0xA0 then `__Host-` carries none of the prefix's protection. **Expiry is checked on every read**: the TTL deletes within days and DynamoDB returns the item until then. **A refresh is a compare-and-set** on `version` with `attribute_exists(#pk)`; without the condition `UpdateItem` recreates a session a sign-out deleted. A losing refresh **uses the stored token**, unless it was forced and the stored one has an earlier `iat`; a forced loser that always wrote its own answered 503 to as many as 13 of a burst of 20. **Only `invalid_grant`, a missing item or the session's expiry end a session**: a store fault, a timeout or `invalid_client` answers 503 and leaves the item. Every unsafe method under `/auth/` and `/api/` needs `Origin` equal to the portal, checked before any store read, because `SameSite=Lax` admits a sibling subdomain. **Nothing about a session lives in module scope**; the one thing held between requests is the feature-flag set, which is not session state, and **no token is ever kept there**."
---

The client environment requires a Next.js server, and the arc puts the session there: the browser
will hold only an opaque cookie, and the server holds the tokens. So the portal's server became a
confidential OIDC client with its own Cognito app client and secret. It keeps each session in a
DynamoDB table and hands the browser only an opaque cookie. Until SPEC-262 nothing the browser calls
used it, so it stood beside Amplify, tested but idle. *(Marked 2026-11-15: since SPEC-262 every
sign-in and every API call goes through it; see `cognito-tokens-are-held-per-tab-not-per-browser`.)*

**The cookie names the session, and the table never holds a usable cookie.** The cookie is 32 random
bytes, base64url, set `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, with no `Max-Age`. The store's
key is the SHA-256 of it, so a read of the table yields nothing a browser could present. A value
that is not 43 base64url characters is refused before any store call.

**The prefix protects only a name read exactly.** The cookie reader trims space and tab and nothing
else. `String.prototype.trim` also strips U+00A0, which Node reads from a 0xA0 header byte, so with
it a cookie named 0xA0 followed by `__Host-dq_signin` read as the real one, while the browser,
checking the prefix against the name it stored, let any sibling subdomain set it. The security
review drove that against the server and Chrome: a planted sign-in cookie turned the victim's next
callback into a session for the attacker's account, and the victim's uploads reached the API as the
attacker.

**The sign-in transaction lives in a second cookie, not in the store.** `__Host-dq_signin` holds the
`state`, the PKCE verifier and the nonce for an hour. The callback clears it only when the `state`
matched: a stray or replayed callback must not cancel a sign-in that is still in progress.

**Expiry is checked on every read.** DynamoDB deletes an expired item within days and returns it
until then, so the TTL is hygiene and never the boundary. A read at or past the absolute expiry
deletes the item and answers as if there were none.

**A refresh is a compare-and-set, and the condition is what stops a resurrection.** Each refresh
writes against the `version` it read, with `attribute_exists(#pk)` beside it. `UpdateItem` creates
an item it does not find, so without the condition a refresh racing a sign-out brings the session
back. Every read is strongly consistent, because the version it returns is compared a moment later.

**Losers use the stored token, and the stored token only moves forward.** Two requests carrying one
cookie may refresh at once, on one task or two. Refresh token rotation is pinned off, so both
provider calls succeed and one write wins. A loser re-reads and uses the stored token. A forced
refresh, which exists to pick up a membership granted a moment ago, uses it only when its `iat` is
the same second as its own or later, and otherwise writes its own against the version it re-read.
The first design had a forced loser always write its own, up to three times: driven against the real
server, it answered 503 to 6 to 13 of 20 concurrent forced refreshes on one cookie, and a slow loser
could write an older token over a newer one. Five writes remain as a backstop that a burst does not
reach. `iat` counts whole seconds, so a token from the same second counts as fresh; the next forced
refresh picks up a grant that one missed.

**A fault is not a sign-out.** Only a refresh token the provider refuses (`invalid_grant`), a missing
item or the session's own expiry end a session. A store that does not answer within two seconds,
a token endpoint that does not answer within five, and `invalid_client` all answer 503
`ApiUnavailable` and leave the item where it is. A near-expiry refresh that fails serves the token
it still has while that token is valid.

**The `Origin` check runs before anything else.** Every `POST`, `PUT`, `PATCH` and `DELETE` under
`/auth/` and `/api/` must carry `Origin` equal to `PORTAL_ORIGIN`, and a missing one is refused.
`SameSite=Lax` sends the cookie from a sibling subdomain such as the API's, which is why the check
exists. `/auth/callback` is a cross-site `GET` by design, protected by `state` and the sign-in
cookie.

**Nothing about a session lives in module scope**, so a second task or a restart serves the same
session. A test serves a session through one store and then asks for the same cookie through an
empty one; a module-registry reset was the first shape of that test, and it passed with a cache
planted, because the fresh module brought a fresh, empty cache.

**One thing is held between requests, and it is not session state** (since SPEC-264, 2026-11-17): the
resolved feature-flag set, with the time the API answered it, the time of the last failed refresh and
whether a refresh is in flight. It is the same document for every signed-in user, so it serves them
all, and it lives on the process's global object rather than in a module, so every route entry reads
the copy the root layout warmed. **No token is held there**: a refresh takes the requesting
session's token as a local and drops it. Reading it costs a page one store read through
`peekSession`, which checks what `loadSession` checks and never refreshes, deletes or writes.

**Do NOT** trim a cookie name with `trim()`, derive a redirect or `redirect_uri` from the request's host, keep a session or a token
in memory between requests, end a session on a fault, drop the update's condition, let a forced
refresh write over a newer token, or turn refresh token rotation on.

Detail: `docs/specs/SPEC-257-the-nextjs-server-holds-the-session.md`.

## History

### 2026-11-17

- **Changed:** The held feature-flag set is named as the one thing kept between requests, not session state, with no token in it; `peekSession` reads a session without changing it (SPEC-264).

### 2026-11-13

- **Settled:** SPEC-257.
