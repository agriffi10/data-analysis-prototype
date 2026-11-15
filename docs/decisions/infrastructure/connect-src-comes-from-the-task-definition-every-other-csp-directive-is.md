---
type: Decision
title: "`connect-src` comes from the task definition; every other CSP directive is a property of the bundle (SPEC-194, SPEC-255)"
description: "**CSP `connect-src` IS the app's network surface** — enumerate it from the hosts the app fetches, not the AWS services it uses; the omitted Hosted UI domain broke fresh sign-in for a day. **Since SPEC-262 it is exactly `'self'` and the two buckets**: the browser signs in and calls the API through its own origin. **Prove enforcement with a POSITIVE `securitypolicyviolation`** (`effectiveDirective: \"connect-src\"`, `disposition: \"enforce\"`) plus a same-origin negative control. It reaches the server as `PORTAL_CSP_CONNECT_SRC`, built at root as `csp_connect_src`; every other directive is `src/server/contentSecurityPolicy.ts`, and each page's policy carries a fresh nonce. **The server allowlists the source list at start and exits 1 naming the variable**: a quote or `;` in it would end or add directives on a server that still answers."
---

**The seam.** `connect-src` **is** the app's network surface and the only environment-shaped
directive, so it arrives as one environment variable the task definition supplies,
`PORTAL_CSP_CONNECT_SRC`, which the request proxy reads at request time. `default-src`, `style-src`,
`img-src`, `font-src`, `worker-src`, `object-src`, `base-uri`, `form-action`, `frame-ancestors` and
`upgrade-insecure-requests` all describe the **bundle** — what it may style, fetch a font from, spawn
a worker as — and live in `src/server/contentSecurityPolicy.ts`, which ships in the image.
`script-src` describes the bundle too, and since the move to Next.js it also carries the page's
nonce, built per request beside `connect-src`. Baking the whole policy would carry one environment's
hosts everywhere, which is exactly the build-time-configuration failure the runtime-configuration
document exists to end; supplying the whole policy from the task definition would put the bundle's
own properties in the hands of whoever edits an environment map.

**The source list is built at root, and the rest of the policy is the server module's alone.**
`csp_connect_src` in `infra/main.tf` assembles the list from the region, the two buckets, the Cognito
hosts and the API origin; the root `content_security_policy` local lost its last consumer with the
distribution and was deleted. The move of the other directives into TypeScript was proved to be a
move: the module's test holds the pre-move directives as a recorded literal, in order and with their
`"; "` join separator, with `script-src` the one directive allowed to differ, because an expectation
re-derived from the module itself would only assert that the file equals itself. Two mutations once
escaped a guard of this kind and are worth keeping in mind for any similar check: an element regex
reading **quoted strings only** was blind to an unquoted reference appended to the list, and nothing
asserted the **join separator**, without which a policy joined on a space is one malformed directive
with every other directive dropped by the browser and every element still present.

**The interpolated value is validated at start, against what it may contain.** The source list is
pasted into a header, and a `"` or a `;` in it would end the directive it sits in or append one of
the sender's choosing, on a server that starts and answers. So `src/instrumentation.ts` checks it once
at server start against the allowlist `A–Z a–z 0–9 ' : / . space _ * -`, as the nginx entrypoint did
before it, and **exits 1** naming `PORTAL_CSP_CONNECT_SRC` when it is unset, empty or carries anything
else. It exits rather than throws: a throw there was measured to leave a server up answering 500 to
every path, which a load balancer probes as an unhealthy target indefinitely rather than as a task
that stopped. An allowlist cannot be outflanked by a character nobody thought of.

**The Cognito hosts stay, and a test names them separately.** On the day the container shipped,
`connect-src` was every host the response-headers policy enumerated **plus the API host**. It shrank
one entry at a time as the porting specs landed and reached its end state at SPEC-202 — `'self'`,
`cognito-idp`, the Hosted UI host, both buckets, the API — and **it did not lose the Cognito hosts**:
Amplify runs in the browser, so the User Pool endpoint and the Hosted UI domain are still fetched from.
**Since SPEC-262 neither Cognito host nor the API is in the list.** The portal server signs in and
calls the API, so the browser reaches Cognito only by navigation, which `connect-src` does not govern,
and fetches its own origin and presigned bytes. `lambdas/test_csp_policy.py` now refuses the two
Cognito hosts and the API's origin by name, inverted from the test that once required them, so a reader
restoring them on the old reasoning fails a test rather than widening the surface.
That is the highest-consequence mistake available here, and the reason
`lambdas/test_csp_policy.py` names those two entries separately from any set comparison: a reader
holding the arc's end state in mind deletes them on purpose, and would then update a whole-list
assertion to match the mistake. The failure is **invisible to an already-signed-in session**: the
authorization-code exchange is the only fetch to the Hosted UI host, a warm tab never makes it, so the
portal looks perfect to whoever is testing while every new sign-in sits signed out over a live session.

## History

### 2026-11-15

- **Changed:** SPEC-262 narrowed `connect-src` to `'self'` and the two buckets, and inverted the test
  that named the Cognito hosts.

### 2026-11-13

- **Changed:** SPEC-255 replaced nginx with the Next.js server. The source list still comes from the
  task definition, now read by the request proxy per request, and the policy carries a per-request
  nonce. The bundle's directives moved from the root `content_security_policy` local, deleted with its
  last consumer, to `src/server/contentSecurityPolicy.ts`, and the recorded pre-move literal moved
  with them into its test. The start-time allowlist moved from nginx's entrypoint to
  `src/instrumentation.ts`, which exits rather than throws.

### 2026-08-27

- **Settled:** SPEC-194. `connect-src` came from the task definition and every other directive was
  baked in the nginx image; both CSP locals moved to root, because a check at root cannot read a
  module's local. nginx has no escaping mechanism, so the interpolated value was allowlisted at
  container start.
