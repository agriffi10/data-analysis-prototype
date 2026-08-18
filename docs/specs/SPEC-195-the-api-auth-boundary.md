# Spec: The API's Auth Boundary — Verifying the Bearer Token

**ID:** SPEC-195
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-006/007 (the Cognito User Pool and Managed Login v2 — **unchanged by this spec**), SPEC-011 (the identity is a verified claim, never a caller assertion; the tag SPEC-196 builds from it), SPEC-106 (`toUserMessage` — raw provider text is never rendered), SPEC-126 (the DLQ drain's expiry-relaxed verification, and why this boundary may not reuse it), SPEC-127/130/137/186 (`cpcommon.observability`, the field rule, the `error.stack` exemption this spec re-opens, and `env`/`version` on every record), SPEC-150 (`ServiceResult` and the catch discipline), SPEC-156 (**one** JWKS path in this repo — parameterised here, not forked), SPEC-192 (the runtime accessors, `apiBaseUrl`, and the server-side provider block), SPEC-193 (the API Lambda, its router, its deliberate absence from the VPC, and the API Gateway CORS configuration)

## Overview

Arc B moves the browser's AWS calls behind an API. Before any call can move, the API has to know who is
asking — in a way the caller cannot influence.

This spec builds that boundary and nothing else. **Sign-in is untouched**: the Cognito User Pool, Managed
Login v2, Amplify in the tab and the Hosted UI round trip all stay exactly as they are. The browser already
holds a Cognito ID token; from here it sends that token to the API as a bearer, and the API verifies it
against the pool's JWKS and takes the username from the **verified claim**. That is the trust model the seven
control-plane Lambdas have had since SPEC-011 — the token has changed transport, from an SQS message body to
an `Authorization` header, and nothing else.

It is a **verifier, not an OIDC client.** No code exchange, no refresh token, no session, no cookie. An
earlier draft of this spec did all three, as a backend-for-frontend; that work is real and deferred (see
*What the later arc inherits*), and a reader who saw it should read this paragraph as the correction. Every
requirement below names the assertion separating an **enforced** check from an unenforced one, because a
genuine token passes both — an API that skips verification entirely works perfectly for every real user.

## Scope

### In Scope

- **Token verification** — JWKS fetch and cache, RS256 signature, `iss`, `aud`, `exp`/`nbf`, the
  required-claims check (`token_use: id` on Cognito), the username from a configured claim — through **the
  repo's one JWKS path**, `cpcommon.auth`, extended rather than copied (FR-001, FR-006).
- **Provider-agnosticism in reduced form**: issuer, audience, JWKS URI, username claim and the
  required-claims map are configuration (FR-002). *Reduced in what it builds, not in what it is worth
  — see the amendment under* Premises *below.*
- **Deny by default in the router**, and the refusal surface: 401 vs 403, one indistinguishable 401 body, no
  provider text on the wire (FR-003, FR-004), plus one temporary probe route (FR-005).
- **The `error.stack` scrub**, with its own `decisions.md` entry beside the original (FR-007).
- **The SPA's half**: `lib/apiClient.ts` attaches the token, and refreshes once and retries once on a 401
  — the arc's only retry (FR-008).
- **The negative sweeps** proving the API is not a BFF (FR-009).

### Out of Scope

- **Everything the earlier draft built**: `/auth/login`, `/auth/callback`, `/auth/logout`, `/auth/session`,
  the code exchange, PKCE, the login transaction, the session cookie, CSRF tokens, the DynamoDB session store
  and its KMS key.
- **`lib/amplify.ts`, `lib/returnPath.ts`, `AuthProvider`, `useAuth`, `auth.service.ts`** — all unchanged.
  Sign-in, sign-up, sign-out and the auth gate behave exactly as today.
- **Role assumption and every AWS call the API makes** (SPEC-196 — this spec resolves a principal), and **the
  transport contract**: route shape, response envelope, error wire format, the TS↔Python agreement mechanism
  (SPEC-197). `apiClient.ts` lands here with its auth behaviour only, in one module deliberately, so 197's
  work is one edit.
- **Any ported feature.** No `*.service.ts` change, no `@aws-sdk/*` import removed; the browser keeps its
  Identity Pool credentials and keeps calling AWS directly (SPEC-198 → 202). The control-plane Lambdas keep
  verifying the token from the message body; SPEC-201 collapses the five readers.
- **Rate limiting, WAF, and any machine-facing authorizer.** Deferred with the machine-facing door.
- **Entra ID and Identity Center.** A provider swap becomes a configuration change; no second provider is
  built, and IdC is not a login provider at all.

### What happens today, and what this spec changes

| Behaviour today | After this spec |
|---|---|
| Amplify configures at module load; `signInWithRedirect()` runs the Hosted UI round trip; `lib/returnPath.ts` holds the return path in `sessionStorage` | **Unchanged.** The arc's open question 3 — what replaces `returnPath` — is void |
| `getIdToken()` (`lib/awsCredentials.ts`) returns the ID token from `fetchAuthSession()` | **Unchanged, second caller.** `enqueueFifo.ts` puts it in a queue body; `apiClient.ts` puts it in a header |
| `lib/awsCredentials.ts` mints Identity Pool credentials for the browser's AWS clients | **Unchanged.** SPEC-202 retires it |
| `cpcommon.auth` derives the issuer from `REGION` + `USER_POOL_ID` and reads `cognito:username` | FR-001 — the same functions, now callers of a configuration-driven core. Behaviour byte-identical, proved by a parity run |
| `clients.jwks(url)` builds a `PyJWKClient` with every default | FR-006 — an explicit timeout and a bounded response to an unknown `kid`; both defaults are hazards at this boundary |
| SPEC-193's router serves `GET /healthz` and 404s everything else | FR-003 — it resolves a principal before dispatch and refuses an undeclared route |

### Premises later specs must honour

1. **The identity is the verified claim, derived in exactly one place.** SPEC-196 builds its session tags from
   `Principal.username`, SPEC-200 writes it as `actor`, SPEC-201 collapses the five `cognito:username` readers
   onto it. Nothing re-derives it, and nothing anywhere reads a username the caller stated.
2. **There is no ambient credential, so there is no CSRF surface.** CSRF exists because a browser attaches
   cookies to cross-site requests automatically; a bearer header is attached only by script that can read the
   token, and cross-origin script cannot. A later spec introducing a cookie re-opens CSRF, `SameSite`, and the
   *two-origins-one-registrable-domain* constraint this design relaxes from a requirement to a preference.
   CORS is still required.
3. **`verify_id_token_ignoring_expiry` is for the DLQ drain and nothing else.** A synchronous API request is
   never late by construction; a route reaching for it has misread SPEC-126.
4. **The 401 body is deliberately uninformative, and the API's exception paths are scrubbed rather than
   exempted** (FR-004, FR-007). SPEC-197's envelope may add fields to other statuses; the unauthenticated body
   stays identical across every failure. Any later handler added to `lambdas/api/` inherits the interpolation
   sweep and the sentinel test, and neither is optional.
5. **The verifier is a module the router calls, not logic inlined in the router** (FR-001, FR-003). The
   target environment splits the gate from the worker — a Lambda authorizer returns allow/deny plus the
   resolved identity, and the BFF does the work — because there the check is a DynamoDB session read on
   every request rather than a cached-JWKS signature verify, and API Gateway's authorizer result caching is
   what makes that affordable. **This spec does not build that split** (one Lambda behind a proxy
   integration, settled in the arc entry), and it should not: caching an *allow* decision keyed on a
   credential is a revocation-latency question this arc has no reason to open. What it must leave behind is
   a verifier with no router dependencies, so the split is a wiring change. A test asserting the module
   imports nothing from the router is the cheap way to hold it.

**AMENDED 2026-08-18 — FR-002 is load-bearing, not a convenience.** `transition_plan.md` §3.3 now carries
**two variants** of the target identity plane, decided by gate G8 in Phase 0: **[A]** Entra issues OIDC
directly and **there is no Cognito anywhere**, or **[B]** Entra is SAML-only and Cognito survives as a
bridge that issues the JWT. Under **[A]**, this spec's configuration-driven verifier is the single reason
deleting Cognito is a configuration change rather than a rewrite of every auth path in the product; under
**[B]** it points at a pool that exists to be deleted later. Either way FR-002 is what makes the variant a
late-bound decision instead of an early-bound one, and **no requirement below may hard-code a Cognito
issuer, a `cognito:` claim prefix or a `token_use` value as a constant** — they are configuration with
Cognito-shaped defaults.

---

## Functional Requirements

### FR-001: One verifier, parameterised — not a second implementation

#### Description:

SPEC-156 settled that this repo has **one** JWKS path, after four copies of the claim checks existed and a fix
to any of them had to be made in all four. The API needs those same checks against a configured issuer rather
than one derived from `REGION` + `USER_POOL_ID`, and a configured username claim rather than the literal
`cognito:username`. That is a parameterisation; a second `jwt.decode` in this repo would be a new deliberate
twin and is refused.

#### Acceptance Criteria:

- [ ] `cpcommon.auth` exposes `verify_token(token, cfg) -> Principal`, and the four existing entry points
      (`verify_id_token`, `verify_id_token_ignoring_expiry`, `verified_username`,
      `verified_username_ignoring_expiry`) call it with a Cognito-derived `VerifierConfig`.
- [ ] An AST sweep over `lambdas/` asserts **exactly one** call to `jwt.decode` and **exactly one** to
      `clients.jwks` in non-test modules, both inside `cpcommon/auth.py`. It fails if a second appears
      anywhere.
- [ ] **The sweep exempts test modules, and the exemption is a stated rule rather than a convenience.**
      It has to be: `test_auth_cpcommon.py` today calls `jwt.decode` once (to read back the claims of a
      token it minted) and `clients.jwks` three times (to prove the client cache is keyed per URL), and
      three further suites rebind `clients.jwks` to a fake. A sweep run over `lambdas/**` unfiltered
      fails on the existing suite on the day it is written, and the repair a builder reaches for is to
      delete those assertions. The rule is: **the sweep's subject is every non-test module under
      `lambdas/`**, selected by module path (`test_*.py` and `conftest.py` excluded) and **not** by a
      per-file allowlist — SPEC-165's precedent is that the exemption rule is itself a decision to be
      written down, and a hand-kept allowlist rots. A guard-the-guard asserts the sweep's subject set is
      non-empty and contains `cpcommon/auth.py`, so a filter that accidentally excludes everything
      cannot read as a pass.
- [ ] The four entry points are behaviourally unchanged, proved as SPEC-156 proved its own deduplication: a
      parity run over nine token shapes (valid; expired; wrong audience; wrong issuer; bad signature; unknown
      `kid`; `token_use: access`; missing username claim; not a JWT) asserting the same exception type and
      message text before and after — **the message text measured at the entry points**, which is what
      every downstream mapper stringifies (`verified_username` → `TerminalError`,
      `shared-space-common`'s `AuthorizationError`), never `verify_token`'s own literal reason.
      FR-007 AC3 is how the text survives. Argued equivalence is not accepted — SPEC-156's own run found
      one divergent row.
- [ ] `verify_token` raises `AuthError`, never `TerminalError`: that mapping is a control-plane concern and
      the API maps to HTTP instead. A test asserts `lambdas/api/` imports no name from `cpcommon.errors` but
      `AuthError`.
- [ ] The verifier enforces `require=["exp","iss","aud"]`, `verify_exp`, `verify_nbf`, `algorithms=["RS256"]`
      and every entry in `cfg.required_claims`, and **each check is driven to failure individually** — a
      verifier applying them as a block cannot show which one it is actually applying.
- [ ] **`alg` is pinned to a list, never read from the token.** A test presents a token whose header says
      `alg: none`, and one signed `HS256` with the public key as the secret, and asserts both are refused. A
      verifier that trusts the header accepts both and is indistinguishable on every genuine token.

### FR-002: Issuer, audience, JWKS URI and the username claim are configuration

#### Description:

The API reads its provider parameters from its environment, so the target-environment arc swaps the provider
rather than the verifier. It reads **five** fields of SPEC-192's provider block; the client secret, redirect
URI and post-logout URI belong to the deferred BFF and are not provisioned here — a required variable that
reaches production unset fails far from its cause.

#### Acceptance Criteria:

- [ ] `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URI`, `OIDC_USERNAME_CLAIM` and `OIDC_REQUIRED_CLAIMS` are
      read through `apicommon.config` at **first access, never at import** — the cold-start rule SPEC-156
      FR-004 established after PR #196 took out a whole control plane.
- [ ] `OIDC_JWKS_URI` is explicit configuration and is **never derived by string concatenation** from the
      issuer. Cognito's happens to live at `{issuer}/.well-known/jwks.json`; Entra's does not, and a
      concatenation that works today is the provider assumption this FR exists to remove. A test asserts no
      module builds a JWKS URL from `OIDC_ISSUER`.
- [ ] `OIDC_REQUIRED_CLAIMS` is a JSON object of claim → expected value; the deployed Cognito value is
      `{"token_use":"id"}`, pinned by a test that **reads it from the Tofu environment map** rather than
      restating it.
- [ ] A sweep over `lambdas/api/` finds no occurrence of `cognito`, `amazonaws.com`, `cognito:username` or a
      user-pool id. The verifier must not know which provider it is verifying.
- [ ] Missing or unparseable configuration fails **closed** with a 5xx and a log record — never a successful
      verification, and never a 401, which reads to the SPA as "sign in again" for a server misconfiguration
      the user cannot fix.
- [ ] **There is exactly one wiring site, and it is Terraform's.** All five are declared in the Tofu
      environment map for the API function, four of them computed from resources Terraform already owns
      (the pool id, the app client id) and none of them an operator input today. A test asserts
      set equality between the keys `apicommon.config` reads and the keys the environment map declares —
      a variable present in code and absent from the map, or the reverse, is a hard failure.
- [ ] **`apps/portal/.env.example` gains nothing.** That file is the SPA's dev fallback and SPEC-192
      asserts a `VITE_*` key-set agreement over it; it has no non-`VITE_` line today and a "server-side
      section" would be a second, unchecked home for a value Terraform computes. If the provider swap
      later makes one of the five an operator-supplied input, it is documented in
      `infra/terraform.tfvars.example` on SPEC-186's `verification_principal_arns` precedent. A test
      asserts no `OIDC_` key appears in `apps/portal/.env.example`.

### FR-003: Deny by default in the router

#### Description:

SPEC-193's router dispatches on method and path. From here it resolves a principal **before** dispatch, and a
route that has not declared itself public does not run.

#### Acceptance Criteria:

- [ ] The router resolves the principal before invoking any handler and passes it in the request context. A
      handler receives `Principal`, never the raw event and never the `Authorization` header.
- [ ] The public exemption list is a literal in one module containing exactly one entry today, `GET /healthz`,
      asserted by value. `/healthz` requires no token and returns nothing user-identifying — a health check
      needing a token cannot be used by a load balancer.
- [ ] **A synthetic route registered with no declaration returns 401**, asserted by a test that registers one.
      This is what distinguishes deny-by-default from allow-by-default: a router defaulting to public passes
      every other test in this spec, because every other test declares its route.
- [ ] The token is read **only** from `Authorization: Bearer <token>`. A test asserts a token supplied as a
      query parameter, a cookie or a body field is ignored and the request refused — query strings reach
      access logs, and the privacy rule forbids credentials there.
- [ ] Header parsing is case-insensitive on the header name and scheme; a header carrying a second scheme or
      stray whitespace is refused rather than salvaged.

### FR-004: The refusal surface — 401 is not 403, and neither is an oracle

#### Description:

The SPA must tell "your token is no good, sign in again" from "you are who you say you are and may not do
that". Different user outcomes, different SPEC-106 wordings. Everything else the API knows about *why*
verification failed stays in `logs/`.

**This FR and FR-008 together are the arc's one 401 contract**, and every later spec defers to it rather
than restating it: one status, one code, one refresh, one retry.

#### Acceptance Criteria:

- [ ] No token, a malformed token, a bad signature, a wrong issuer, a wrong audience, a wrong `token_use`, a
      missing username claim **and an expired-but-otherwise-valid token** each return **401** with
      `WWW-Authenticate: Bearer` and a body whose machine code is **`SessionExpired`**. SPEC-197 wraps that
      body in the error envelope without changing the code, so the value is settled here and serialised
      there.
- [ ] **All eight bodies are byte-identical**, asserted by a test collecting all eight and comparing them.
      A distinct body per failure makes the API an oracle for which check failed — exactly the map an
      attacker probing the boundary wants.
- [ ] **Expiry is deliberately NOT distinguished on the wire**, and this is the criterion that says why:
      FR-008 refreshes once and retries once on **any** 401, so a discriminator buys the client nothing
      and costs the oracle AC2 forbids. The assertion that can fail is that the expired token's body is
      byte-identical to the no-token body — a builder who reaches for a `token_expired` code to drive the
      refresh has reintroduced the oracle, and this is what reddens.
- [ ] **403 is never returned by this spec**, asserted by a test over `lambdas/api/`. It becomes reachable in
      SPEC-196, for an authenticated caller refused an action — at which point this criterion stays as the
      guard that the *auth boundary* never mints one, so 401 and 403 cannot collapse into each other.
      Conflating them is what makes an app tell a user to sign in again when signing in again cannot help.
- [ ] No response body, header or status carries provider text: not a PyJWT message, not a `kid`, not an
      issuer, not the token. A test asserts a sentinel embedded in the token appears in no byte of the
      response.
- [ ] The 401 path emits a log record naming a fixed literal reason code, the request id and the route — and
      **no** token, `Authorization` header, raw event or email (the field rule).

### FR-005: `GET /_auth/whoami` — the boundary's only route

#### Description:

Nothing is ported yet, so without one route the boundary cannot be exercised against real Cognito until
SPEC-197. One probe, returning the caller's own username and nothing else.

It is temporary, and **SPEC-197 FR-014 deletes it**, alongside SPEC-196's `GET /_identity/self` and on the
same condition: only after this spec's Phase 5 verification has been run and recorded. Naming the owner
matters — a scaffold whose deletion is assigned to the arc's last spec survives the whole arc.

#### Acceptance Criteria:

- [ ] With a valid token it returns 200 and `{"username": "<verified claim>"}`.
- [ ] **A request stating a different username still resolves the token's**: the test sends `?username=bob`
      and `{"username":"bob"}` with alice's token and asserts `alice`. This is what FR-003's context-passing
      exists to make true, and a handler that reads the body passes every other test here.
- [ ] It discloses nothing about any other user — no lookup, no existence check. A test asserts the handler
      makes zero boto3 calls.

### FR-006: The JWKS client's two dangerous defaults

#### Description:

`clients.jwks(url)` builds `PyJWKClient(url)` with every default. Two are hazards at an internet-facing
boundary, and both were harmless while the only caller was a Step Functions verb.

#### Acceptance Criteria:

- [ ] The client is built with an explicit HTTP `timeout` **below API Gateway's 29-second integration
      ceiling** — PyJWT's default is `30`. A test asserts the argument is passed and asserts the inequality
      against the ceiling as a named constant, not a literal. Left at the default, a hung JWKS endpoint
      produces a gateway 504 that reads as an API fault and names nothing.
- [ ] An **unknown `kid` does not cause an unbounded JWKS refetch.** `PyJWKClient.get_signing_key` refreshes
      the key set, bypassing the cache, whenever a `kid` misses — so a stream of tokens carrying random `kid`s
      is an unauthenticated amplification against the provider's JWKS endpoint, from a request not yet
      authorized. **The bound is a per-container refresh cooldown on the refetch itself**, not a cache of
      refused `kid`s: a negative cache keyed by `kid` misses on every *distinct* unknown `kid`, which is
      exactly the traffic this criterion exists to bound, so it would pass review and fail the counter.
      While the cooldown is open the key set is not refetched and an unrecognised `kid` is refused from the
      cached set. **The test is a counter**: N requests with N distinct unknown `kid`s inside one cooldown
      window produce **at most one** refetch, and the assertion is on the fetch count, never the response —
      every one of those requests correctly returns 401 either way.
- [ ] A genuine rotation still succeeds **at the end of the window**: with `JWKS_REFRESH_COOLDOWN_SECONDS`
      elapsed, a `kid` unknown at first sight triggers exactly one refetch and then verifies. Driven by a
      test that advances the clock, and by its negative half — the same request inside the window does
      **not** refetch. The cooldown is ≤ 60 s.
- [ ] **The cost is eventual consistency, and it is accepted rather than implied:** for up to
      `JWKS_REFRESH_COOLDOWN_SECONDS` after a provider rotates its keys, this API refuses tokens signed
      with the new key. Cognito publishes both keys across a rotation and a ≤ 60 s window is far inside
      any overlap, so no real rotation is expected to reach a user; the trade is bounded refusal against
      an unauthenticated amplification vector, and refusal is the fail-closed direction. Recorded in the
      `decisions.md` entry, not only here.
- [ ] A JWKS fetch failure returns 5xx, and **no code path returns a `Principal` when the fetch raised** — the
      fail-open direction, which a `try/except` returning a default produces and which no happy-path test can
      see.

### FR-007: `error.stack`, in its reduced form — scrub, do not exempt

#### Description:

`log-foundry`'s `end_event` attaches `traceback.format_exception` to every failed span. SPEC-130 examined that
and **accepted** it — for *file contents*, on the reasoning that `logs/` is admin-only and a stack is
diagnostic metadata a failed run needs. The API handles a user's ID token, which is a bearer credential for as
long as it lives, and that reasoning was never applied to a credential.

Two facts were measured rather than inherited, and both narrow the problem. **`log-foundry` 0.6.0 exposes no
way to turn stack capture off** — `config.py` offers only `max_stack_bytes`, whose validator rejects any value
below 1 — so exemption is unavailable and scrubbing at the boundary is the only answer. And the exposure is
**not automatic**: `format_exception` renders each frame's source line, not its locals, and PyJWT's own
messages carry no token material (measured against `decode`, `get_unverified_header` and a segment-count
failure). The live route is this repo's own code interpolating the token — or the API Gateway event, whose
headers hold the bearer — into an exception message or a log field.

#### Acceptance Criteria:

- [ ] A **sentinel test**: every failure path in `lambdas/api/` is driven with a token whose payload carries a
      unique sentinel; the records are captured through `conftest.captured_events`, serialised, and the
      sentinel appears in **no byte** of any record, `error.stack` included. This test can fail, and it is the
      one that matters.
- [ ] A sweep over `lambdas/api/` forbids the raw event, its `headers`, and any variable holding a token from
      appearing in an f-string, a `%`-format, a `.format()` call or a `raise` argument.
- [ ] `verify_token` raises `AuthError` with a **fixed literal reason code**, never an interpolated provider
      message — **and chains the provider exception as `__cause__`** (`raise AuthError(REASON) from exc`).
      That is what lets both halves be true at once. The API reads the code and never touches `__cause__`;
      `cpcommon.auth`'s Cognito entry points reproduce their existing text by interpolating it —
      `AuthError(f"token verification failed: {exc.__cause__}")` — which is byte-identical to today's
      `f"token verification failed: {exc}"` raised inside `_verify`, so FR-001's parity run has something
      to be parity *with*. Their exposure is a queue body SPEC-126 already redacts. Two tests: one asserts
      `verify_token`'s own `str()` contains no provider text and no token substring; one asserts no module
      under `lambdas/api/` reads `__cause__`.
- [ ] `apicommon` sets `max_stack_bytes` explicitly rather than inheriting 32768, and a test asserts it is
      passed. It is a ceiling, not a control — a reader must not mistake it for the scrub.
- [ ] A `decisions.md` entry sits **beside** the original stack-trace entry, recording that the SPEC-130
      exemption covers file contents and **not** credentials, that the answer here is a scrub at the boundary,
      and that `log-foundry` 0.6.0 offers no opt-out. If a later version does, the decision is revisited, not
      the tests deleted.

### FR-008: The SPA attaches the token, and refreshes once

#### Description:

`lib/apiClient.ts` is the browser's one door to the API. Its auth behaviour lands here; SPEC-197 adds the
transport contract around it.

**This FR owns the arc's only retry.** SPEC-197 FR-008 sets the rule that `apiRequest` retries nothing —
under a timeout, a 429, a 503 or a network failure — and names **one** exception, which is this: a 401
triggers exactly one forced ID-token refresh and exactly one retry, and no more. SPEC-197 names the
exception and points here; SPEC-196 FR-007 defers here for the same behaviour. A builder who reads
SPEC-197's zero-retry test in isolation and deletes this path has removed the browser's only
token-refresh route, and every user is signed out at the hour mark.

#### Acceptance Criteria:

- [ ] Every request goes through `apiFetch`, which calls `getIdToken()` (`lib/awsCredentials.ts`, unchanged)
      **per call** and sets `Authorization: Bearer <token>`. The token is never held in a module variable, a
      closure or `localStorage` — Amplify owns its lifecycle including the silent refresh, and a second cache
      serves a stale token after one.
- [ ] `getIdToken()` failing returns `{success: false, error: {code: 'SessionExpired'}}` **without issuing a
      request**, asserted by a `fetch` call count of 0.
- [ ] **Any** 401 triggers **exactly one** `getIdToken(true)` and **exactly one** retry — the cause is not
      read, because FR-004 deliberately does not disclose it. A test asserts a second 401 on the retry does
      not retry again: a refresh loop against a dead refresh token is invisible in a passing test and
      obvious in production.
- [ ] A retry that still 401s resolves to `SessionExpired`; a 403 resolves to `AccessDenied`. A test
      asserts the two produce **different** `toUserMessage` outputs — one wording for both is the defect
      this criterion exists to catch, and it is the difference between "sign in again" and "signing in
      again cannot help".
- [ ] **Nothing else is retried, by this module or by anything above it.** A test asserts exactly one
      `fetch` per call for a 429, a 503, a network failure and a timeout. The 401 path is the single
      exception and it is the only one this repo has.
- [ ] `apiFetch` returns `ServiceResult<T>` and never throws, and no API or provider text reaches a rendered
      string: the `code` carries the wording (SPEC-106).
- [ ] `AuthProvider`, `useAuth`, `auth.service.ts`, `lib/amplify.ts` and `lib/returnPath.ts` are unmodified,
      asserted by the diff.
- [ ] SPEC-193's API Gateway CORS allows the `authorization` request header for the SPA origin, an exact
      configured value — never `*`, never a reflected `Origin`. **Verified in a browser, not with curl**: a
      preflight omitting `authorization` from `Access-Control-Allow-Headers` passes every server-side test and
      fails every real request.

### FR-009: What the API is not

#### Description:

**These are reintroduction guards, not evidence the design is right.** Nothing in scope can emit a
`Set-Cookie`, a PKCE parameter or an `/auth/` route, so they pass on the day they are written — which is
the point: a reader who saw the earlier BFF draft, or who ports a pattern from another codebase, will
reach for exactly these pieces, and the sweep is what reddens when they do. SPEC-193 FR-001 AC6 ("no
`aws_nat_gateway` or `aws_eip` appears in `infra/`") is the model.

#### Acceptance Criteria:

- [ ] A sweep over `lambdas/api/` finds no `Set-Cookie`, no cookie read, no CSRF token, no `code_verifier`,
      `code_challenge`, `client_secret`, `grant_type`, `authorization_code` or `refresh_token`, and no route
      path beginning `/auth/`.
- [ ] The API function's execution role holds **zero** statements naming DynamoDB, KMS, Secrets Manager, STS
      or Cognito, asserted against the rendered policy. It keeps SPEC-193's CloudWatch Logs writes and
      `sqs:SendMessage` on the logs queue and gains nothing here: **verification is offline against a cached
      JWKS and needs no AWS permission at all.** No new AWS resource type is created, so no deploy-role IAM
      expansion is required — stated as a **verified finding** against the rendered plan, not an assumption.
      This criterion **restates SPEC-193 FR-004 AC3**, which already asserts the same zero-statement set on
      the same role; it is kept here so that the auth boundary's own build cannot widen it, not as
      independent evidence.

      > **SUPERSEDED in part by SPEC-196 FR-003 (2026-08-18):** the STS clause. SPEC-196 adds exactly one
      > statement to this role — `sts:AssumeRole` and `sts:TagSession` on `${portal_role_arn}` — because
      > the API assumes the portal role to act as the caller. From SPEC-196 onward the assertion is
      > **zero statements naming DynamoDB, KMS, Secrets Manager or Cognito**, and **exactly one** naming
      > STS, whose `Resource` is the portal role ARN and nothing else. SPEC-196 owns updating this test
      > in the same commit that adds the statement; leaving it as written would make SPEC-196 red on the
      > day it lands and the repair a builder reaches for is to delete the sweep.
- [ ] Every request runs under `@observability.traced` with `observability.init(service="api")`, so records
      land in `logs/service=api/` with `env` and `version` populated (SPEC-186 FR-005); and a test asserts
      `@notifies_on_failure` appears nowhere in `lambdas/api/` — the response is the channel for a synchronous
      API, and the control-plane decorator stack is what a reader copies.

---

## Data Model

```python
# lambdas/control-plane-common/cpcommon/auth.py

@dataclass(frozen=True)
class VerifierConfig:
    """Everything the verifier needs that differs between providers."""
    issuer: str
    audience: str
    jwks_uri: str
    username_claim: str                   # "cognito:username" today
    required_claims: Mapping[str, str]    # {"token_use": "id"} on Cognito; may be empty


@dataclass(frozen=True)
class Principal:
    """The verified caller. Constructed only by `verify_token`."""
    username: str                         # the value of cfg.username_claim, verified
    claims: Mapping[str, object]          # the verified claim set, whole


def verify_token(token: str, cfg: VerifierConfig) -> Principal: ...


# lambdas/api/apicommon/context.py — what a handler receives; never the raw event.
@dataclass(frozen=True)
class RequestContext:
    principal: Principal
    route: str
    request_id: str
```

```ts
// apps/portal/src/lib/apiClient.ts

/** The auth-shaped failures. SPEC-197 widens the union; these two are settled here. */
export type ApiAuthCode = 'SessionExpired' | 'AccessDenied';

/**
 * The browser's one door to the API. Fetches the ID token per call, attaches it as a
 * bearer, refreshes once and retries once on any 401, and never throws. There is no 401
 * discriminator to read — FR-004 makes every 401 body identical on purpose. SPEC-197 owns
 * the rest of `ApiRequest` (method, body, the response envelope); only the auth half is
 * settled here, including the single retry that is SPEC-197 FR-008's one exception.
 */
export async function apiFetch<T>(request: ApiRequest): Promise<ServiceResult<T>>;
```

## Environment Variables

No new `VITE_*`; `apiBaseUrl` arrives through SPEC-192's runtime configuration document. The API Lambda's
environment (SPEC-193 provisions the function; these are the five fields this spec reads):

```
OIDC_ISSUER            https://cognito-idp.<region>.amazonaws.com/<pool-id>
OIDC_AUDIENCE          the app client id the SPA's ID token is issued to
OIDC_JWKS_URI          explicit; never concatenated from OIDC_ISSUER
OIDC_USERNAME_CLAIM    cognito:username
OIDC_REQUIRED_CLAIMS   {"token_use":"id"}
```

## File & Folder Structure

```
lambdas/control-plane-common/cpcommon/auth.py        # VerifierConfig, Principal, verify_token
lambdas/control-plane-common/test_auth_cpcommon.py   # + the nine-shape parity run

lambdas/api/
├── apicommon/{__init__,config,context,errors,principal}.py
├── routes/whoami.py
├── router.py                                        # SPEC-193's, now deny-by-default
└── test_{principal,router_auth,stack_scrub,whoami}.py

apps/portal/src/lib/{apiClient.ts,apiClient.test.ts}
docs/testing/arc-b-api-container-e2e.md
```

## Implementation Phases

### Phase 1: The verifier

- `VerifierConfig`, `Principal`, `verify_token`; the four existing entry points rewritten as callers; the
  nine-shape parity run and the AST sweep for one `jwt.decode` / one `clients.jwks`.
- FR-001's per-check failure drives, including `alg: none` and the HS256-with-the-public-key forgery.
- FR-006's timeout, negative `kid` cache, rotation test and fail-closed JWKS assertion.

### Phase 2: The boundary in the router

- `apicommon.config` / `.context`, header parsing, deny-by-default dispatch, the exemption list.
- FR-004's refusal surface: the eight byte-identical 401 bodies, the deliberate absence of an expiry
  discriminator, and the absent 403.
- `GET /_auth/whoami` and its stated-username test.

### Phase 3: The scrub, the record and the absences

- FR-007's sentinel test, the interpolation sweep, the explicit `max_stack_bytes`.
- `observability.init(service="api")`, the per-request span, the refusal record's field set, the
  `@notifies_on_failure` absence test, and FR-009's sweeps and rendered-policy assertions.

### Phase 4: The SPA's half

- `lib/apiClient.ts` and its tests: per-call token, the single refresh-and-retry (with the "does not retry
  twice" counter), the 401/403 mapping.
- The CORS `authorization` allowance in SPEC-193's API Gateway configuration. No other SPA file changes —
  asserted by the diff.

### Phase 5: Verification

Real invocations against real Cognito, as a new section of
`docs/testing/arc-b-api-container-e2e.md`.
**A signed-in pass never tests sign-in** — a request carrying a genuine token succeeds against a correct
implementation and against one that does not verify at all — so every load-bearing check below is negative.

- **The happy path, once**: a token from a real browser session against `GET /_auth/whoami` returns the
  signed-in username. It proves the wiring and nothing about the verification.
- **No token** → 401 with `WWW-Authenticate: Bearer`.
- **A Cognito *access* token for the same user, same pool** → 401. The cheapest real proof that `aud` and
  `token_use` are enforced: a genuine, correctly-signed, unexpired token from the same provider, which an
  implementation checking only the signature accepts.
- **One payload byte flipped** → 401; **a token signed by another pool's key** → 401. Both bodies
  byte-identical to the two above.
- **An expired token, exercised deliberately.** It cannot be reached incidentally — a Cognito ID token lives
  an hour. Either capture one and come back after the hour, or set a throwaway app client's ID-token validity
  to its **5-minute minimum**. Assert the body is **byte-identical** to the no-token 401 and carries
  `SessionExpired`: a real expired token is the only way to see that the verifier reaches the expiry check
  at all rather than failing earlier, which every offline test that fakes the clock cannot distinguish.
- **The refresh-once path in the browser**, which is what the expired token is really for: with the
  short-validity client, leave a tab idle past expiry, act, and confirm in the network panel exactly two
  requests — the 401 and the retry that succeeds — and that the user was not signed out. Then break the
  refresh (sign out in a second tab) and confirm the retry 401s and there is **no third request**.
- **The preflight**, in a browser: the cross-origin `OPTIONS` returns `authorization` in
  `Access-Control-Allow-Headers`. curl proves nothing here; only a browser enforces it.
- **The stack scrub against a real token**: force a verification failure with a genuine token, wait for the
  `logs/` sweep, and grep the day's `logs/service=api/` records for the token's payload segment. The offline
  test uses a synthetic sentinel; the question here is whether a real token's characters survive a real
  serialisation path.
- **The records**: `logs/service=api/` carries `env` and a real build sha, never `0.0.0`.

Nothing offline can prove three of these: that the JWKS endpoint is reachable from the API Lambda's network
placement (SPEC-193 keeps it out of the VPC precisely so it is), that the preflight allows the header, and
that a real expired token is refused by the expiry check rather than by an earlier one.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row (status only); the delivery doc at
  `docs/spec-delivery/SPEC-195-the-api-auth-boundary.md`.
- Two `decisions.md` entries, then **one line each** in CLAUDE.md's Key Decisions: (1) the API is a verifier
  and not an OIDC client — the bearer trust model, why no cookie means no CSRF surface, and that
  provider-agnosticism lives in five configuration fields; (2) FR-007's `error.stack` scrub, **beside** the
  SPEC-130 entry, recording that the original exemption covers file contents and not credentials.
- A superseded marker wherever a doc still says SPEC-195 owns a session — the `ARCS.md` arc entry's BFF
  paragraphs are **inherited by the later arc, not built here**.
- A component-inventory row for `lib/apiClient.ts` in the area file matching its path, never the router.
- `architecture.md` gains the auth boundary beside the control planes' trust model: the API and the seven
  planes now verify the same token through the same one path.
- The Help sweep: **nothing user-facing changes.** No route is ported, no screen moves, and the only new route
  is a probe. Recorded explicitly and skipped.

---

## What the later arc inherits

Deferred, not abandoned. The reasoning is in `docs/transition_plan.md` §3.5 (Identity Center) and §4.7
(backend and state) and is not restated here.

- **The BFF and its session store.** The server performs the code exchange, holds the tokens, and the browser
  gets an opaque `httpOnly` cookie — which re-opens CSRF, `SameSite` and the
  *two-origins-one-registrable-domain* constraint this spec relaxes to a preference. The session and the
  single-use login transaction live in DynamoDB under a customer-managed key, and **expiry is checked on
  read**: TTL deletes only within a few days and an expired-but-undeleted item is still returned by a read, so
  TTL is storage hygiene, never the security boundary.
- **PKCE and the login transaction.** The verifier and `state` live server-side and the SPA never constructs
  an IdP URL. `lib/returnPath.ts` is deleted then, the return path travelling beside `state` — which survives
  private browsing, where `sessionStorage` degrades.
- **The three clocks** — the provider session, the Identity Center refresh token, the browser session cookie —
  and what a user experiences at each expiry. This spec has one clock, the ID token's `exp`.
- **Identity Center.** **IdC is not a login provider for a web application**: its OIDC service implements the
  device-authorization parts the AWS CLI needs, and a customer-managed OAuth 2.0 application *requires* a
  trusted token issuer. **Entra authenticates the users; IdC propagates their identity into AWS.** The
  jwt-bearer assertion is **single-use** — exchange once at login, then use the `refresh_token` grant.
- **An Entra implementation**, which under this spec is five environment variables plus whatever claim mapping
  Entra needs. That is the entire dividend of FR-002 — and under the **[A]** variant
  (`transition_plan.md` §3.3) it is also the entire cost of deleting Cognito from the product, because
  nothing else in the codebase will name a provider by then.
- **The authorizer/BFF split** (premise 5): the gate moves to a Lambda authorizer with API Gateway result
  caching, the BFF becomes the worker, and this spec's verifier module is what the authorizer calls. That
  spec owns the question this one declines: how long an *allow* may be cached against a revoked session.
