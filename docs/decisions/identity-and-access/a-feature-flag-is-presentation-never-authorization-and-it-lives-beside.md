---
type: Decision
title: "A feature flag is presentation, never authorization — and it lives beside the username directory (SPEC-162)"
description: "**A feature flag is presentation, never authorization** — and the flag document lives beside the username directory in the **user-space** bucket, not the admin one: the admin bucket was specced first, and its grant would not have worked. Gating is by **registry**, not per-component opt-in, and one test walks every gated surface in **both** states. **A document that belongs to no user has no space, so it gets its OWN route** — `_config/` and `_directory/` are not prefixes any caller's claims authorize, and leaving one on the object surface makes every read a 403 that falls back to defaults, which looks exactly like health. **The flags resolve first on the Next.js server and are sent with the page** (one held set per process, refreshed in the background with a session's token); the browser's read is the second line, for a page sent with no set and a stale tab. **The API pass-through never consults the flags** — a route handler, the proxy or a session module reaching them would make a flag authorization — and one set serves every user only because the document is bucket-wide."
---

**The document is `_config/feature-flags.json` in the USER-SPACE bucket**, published by
`.github/workflows/deploy-config.yml` from `config/feature-flags.json` in git. Four flags — `files`,
`query`, `sharedWorkspaces`, `dataQuality` — a total `defaults` block and per-environment partial
overrides, resolved ~~in the browser~~ against ~~`VITE_ENVIRONMENT`~~ **— superseded by SPEC-192:**
`/config.json`'s `environment`, since a production bundle reads no `VITE_` name. Since SPEC-198 the
browser reads the document through `GET /v1/feature-flags`, not from S3. **— Superseded in part by
SPEC-264 (2026-11-17):** the Next.js server resolves it first, below.

**The server resolves the flags first, and the browser's read is the second line.** The root layout
sends the set the server holds with the page, and the boot seeds it into the query cache dated by
when the API answered, so a signed-in tab renders its gated surfaces from the first frame and makes
no request for the flags when it starts. The server reads the document through the same route with
the requesting session's ID token, in the background and never on a page's critical path: a page
costs one session-store read, and a set that is stale or missing is refreshed for a later page. One
resolver serves both callers, so a document cannot resolve one way on each side. A page sent with no
set, and a tab whose set has aged past the hour, read it in the browser as before, which is why
`FeatureRoute` stays. Each signed-in area also has a server layout that answers a disabled area with
the "not available" page from the held set, so that area's view is never loaded — but only from a
set younger than five minutes, because a layout never refreshes it and another task's older "off"
would otherwise override a tab's newer "on" for up to an hour; one route row, the
shared-space report, stays in the browser because a layout reads no `params`.

**Two traps the server side creates.** The held set is shared by every user on a task, which is
correct **only because the document is bucket-wide**: a per-user flag would have to leave the held
set. And **nothing a request to the API passes through may consult the flags** — a route handler,
the request proxy or a session module that read them could gate a request, which is authorization by
another name. `featureFlagsFence.test.ts` walks every one of them through its imports and fails if
one reaches the server's flag module.

**A FLAG HIDES A SURFACE AND REVOKES NOTHING.** Turning Query off hides the tab and its entry points;
the portal role's Athena, Glue and S3 grants are byte-identical either way. This is SPEC-146's
advisory rule for the username directory applied to a second document, for the same reason: the
moment someone treats an advisory document as a boundary, it becomes one, badly. The fence is not a
convention — `featureFlags.service.test.ts` enumerates every `*.service.ts` under `features/` and
every module under `lib/` and fails if one imports the flags module. It was verified against a
deliberate violation rather than trusted; the sweep named the offending file. The realistic failure
it forbids is not exotic: `if (flags.query) return` inside a service reads like a guard and is a
client-side access control, which is no control at all.

**The document was specced into the ADMIN bucket first and moved before any code was written.** That
would have given the portal role its first grant on a bucket admin-only since SPEC-032 — and the
grant would not have worked. The admin bucket carries an explicit "never read by the browser" comment
in place of a CORS configuration, and its host is absent from the enforcing CSP `connect-src`. Two
infra gates on the exact surface SPEC-140 records breaking fresh sign-in for a day, for nothing
`_config/` beside `_directory/` does not already have. **The generalisation is the useful part: for a
browser-read advisory document, the bucket that already serves one is the cheap answer** — and it is
`_config/*`, one `s3:GetObject`, ~~no `ListBucket` widening,~~ no write, no deploy-role change, no
CORS, CSP or bucket-policy change. This is now the precedent for a third such document. **—
superseded in part (2026-08-30, #555):** the portal role may now list `_config/*`, which is what lets
the API report a never-published document as absent rather than denied.

**"It already works" is a claim about three files this spec does not touch, so all three are
asserted.** `lambdas/test_feature_flags_config.py` checks the user-space CORS rule still allows `GET`
from the app origin, that the bucket host is still in `csp_connect_src`, and that the portal role is
still on the bucket policy's hand-maintained principal allowlist — plus the deploy role's existing
`s3:*` on `${user_space_bucket_arn}/*`, which is why the publish adds no IAM. If one of these ever
fails it is a **finding to raise, not a licence to widen infra inside this spec**. **— Superseded:**
those assertions were cut on 2026-08-28 (#540), and since SPEC-198 the read goes through the API,
so the bucket's CORS rule and its CSP entry are no longer on its path.

**AN UNUSABLE DOCUMENT FALLS BACK TO ALL-ON, AND THE FALLBACK IS SILENT.** Missing, unreadable,
unparseable or a version this build has no reader for: the compiled-in defaults take over and the
hook reports `'fallback'`. No banner, no toast — the user is not the audience for that failure.
Failing closed was the alternative and is worse: one S3 blip would strip the app to Files for
everyone. **The accepted cost is stated rather than hidden: during an outage a deliberate "off" does
not take effect.**

**That silence is exactly why the read had to be made observable.** Every default is `true`, so a
permanently-blocked fetch renders *identically* to a healthy environment — no user would report it
and no screenshot would show it. Hence FR-009: a dev-only `console.debug` naming `ready` vs
`fallback` (stripped from production, as `warnIfMisconfigured` is), and a live check whose pass
condition is a **200 in the network panel**, not an app that looks right.

**Two tolerances, deliberately different.** A wrong VERSION or top-level SHAPE is refused whole —
this build has no reader for it, and guessing at an unknown shape is how a flag comes to mean
something nobody wrote. A single malformed VALUE inside an otherwise-fine document falls back **for
that key only**; one bad line must not discard three good ones. The resolver walks the compiled-in
KEY LIST rather than the document's keys, which is what guarantees all four are present and boolean
whatever the document said.

**The service is stricter than `getUserDirectory()`, and that divergence is the load-bearing part.**
There, absent and corrupt collapse into the empty state because "no suggestions" is an honest answer.
Here the equivalent answer is all-on, which is indistinguishable from success — so the distinction
has to survive the return or `'fallback'` could never be reported. A MISSING object is a failure for
the same reason: it means the publish workflow has never reached this bucket, which is a deploy
defect and not a starting state.

**The validator reads the publish workflow's matrix rather than being handed a target list.** FR-002
requires the environment/target check in both directions — a block nobody publishes, and a target
that publishes nothing but defaults — and a list passed in by the same workflow that declares it
would compare a copy of the answer with itself. `deploy-config.yml`'s `environment_name:` entries are
the single declaration; a matrix that parses to nothing is a hard error, not an empty set, because
that is how this stops checking (a rename, not a deletion). The key is `environment_name` and not
`environment` precisely so a GitHub Actions job keyword cannot masquerade as an upload target.

**The publish addresses ONE EXACT KEY — no `sync`, no `--delete`.** `_directory/usernames.json` lives
one prefix over in the same bucket; a mis-scoped reconcile would break username typeahead everywhere
(SPEC-146/147) for a feature nothing user-facing depends on yet. It is also a separate workflow from
the app deploy (`Deploy App` then, `Deploy SPA image` now) on purpose: flipping a flag must not be a
rebuild, which is why the upload carries `Cache-Control: no-cache`.

**A document that belongs to no user has no space, so it gets its OWN route.** `_config/` and `_directory/` are not prefixes any caller's claims authorize, and leaving one on the object surface makes every read a 403 that falls back to defaults, which looks exactly like health.

## History

### 2026-11-17

- **Changed:** The Next.js server resolves the flags first and sends them with the page; the area layouts answer a disabled area on the server; the API pass-through never consults them (SPEC-264).

### 2026-08-30

- **Changed:** The portal role may now list `_config/*`, so the API can report a never-published document as absent rather than denied (#555).

### 2026-08-28

- **Changed:** The assertions on the bucket's CORS rule, CSP entry and principal allowlist were cut (#540).

### 2026-08-10

- **Settled:** SPEC-162.
