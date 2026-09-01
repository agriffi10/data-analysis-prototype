# API — the HTTP plane

One HTTP API, one `$default` route, one Lambda. It is **not** a control plane: no queue, no Step
Function, no verb fan-out. It verifies a bearer token and serves routes directly.

Arc B is porting the browser's direct AWS calls behind it. Today it serves `/healthz`, the username
directory, the feature-flag document, the whole **object surface** (list, metadata, exists, content
read and write, copy, move, delete, free-name and the two presign routes) and the **catalog
surface** — Athena start, status, results and stop, plus Glue get-database and list-tables.
CloudFront is still production and the rollback.

**A route may name a resource in its path.** `/v1/queries/{queryExecutionId}` and
`/v1/catalog/databases/{database}` are matched segment-wise against the contract's templates, and
two declarations that could match one path are refused where a route is declared rather than
arbitrated where a request arrives. The gateway hands the function a percent-**decoded** path
(measured: `GET /health%7A` answers 200), so the browser encodes each segment, nothing here decodes,
and a value that is not one path segment is refused in the browser — decoded, it would address a
sibling template rather than fail.

**File bytes do not pass through it.** An upload is a presigned `PUT` and a download a presigned
`GET`, minted here and redeemed by the browser directly against S3.

## The shape

`lambdas/api/`

| Path | Holds |
|---|---|
| `handler.py` | the entry point — one span per request, and a name on the wire for every fault |
| `router.py` | matching, authentication, and the preflight answer |
| `routes/` | one module per route |
| `apicommon/` | the layer: contract, envelope, errors, identity, memberships, planes, principal, context, config |

## The fences

- **The API VERIFIES a bearer; it is not an OIDC client.** No cookie means no CSRF surface, but CORS
  is still required. Provider-agnosticism is five config fields, and the JWKS URL is built once at
  the **root**.
- **A key-retrieval fault is 5xx, never 401.** Refusals are byte-identical, and **expiry is not
  disclosed** — the browser refreshes once on any 401.
- **Where the memberships come from is a COLD-START choice, and there is no fallback.**
  `MEMBERSHIP_SOURCE` is `claims` (the default, and what every environment runs) or `index`, read
  once at import, and an unrecognised value raises there — a typo must be a dead container, not a
  running one on the other authorization model. The two implementations sit behind one call in
  `apicommon/memberships.py`, so the tag builder, the route-level space check and the parity test
  cannot tell them apart. The interface is **slot to space name**, not a set: the claims source has
  to keep the Cognito slot index it read, because renumbering would change which tag name carries
  which value.
- **The index read is an API-plane call that sits outside the route registry, deliberately.** The
  tags are computed before the caller's credentials exist, so it runs on the execution role — and
  `planes.require` answers per route while this runs for every route, so declaring `Plane.API` per
  route would invert the registry's fail-closed default for the whole API. It goes through the
  private constructor in the one module the credential sweep exempts by exact identity, and the
  sweep still sees the call. A test asserts no other module names the door, because it takes a
  username and a route holding it could read somebody else's memberships.
- **Under the index source an absent index is an ANSWER and every other failure is a fault.** A
  caller with no index is a member of no space, which is correct for anyone never added to one.
  Anything else — throttle, denial, parse failure, an index naming more spaces than there are slots
  — fails the request as `IdentityUnavailable`, mints nothing and caches nothing. The tempting
  alternative is to stamp what resolved and continue: it fails closed in the permissions sense,
  which reads as safe, and it is the worst option available — the caller is refused a space they
  genuinely belong to and told it is a denial.
- **That failure is answered in the router's PRE-DISPATCH clause**, not by `errors.for_exception`.
  `for_request` runs before dispatch, so a failure it raises never reaches the guard that
  classifies a route's exceptions and would arrive as a bare `InternalError`.
- **It assumes the SAME role with the SAME tags from the SAME claims** as the identity pool, which
  is why no policy was rewritten. The role is **reused, never minted**. `DurationSeconds` 3600 is a
  ceiling **both ways**: shorter caps every presigned link, longer is refused because this is role
  chaining.
- **Two credential planes, user by default, declared ON THE ROUTE — the failure fails OPEN.** A
  wrong client *succeeds* against the wrong identity. The plane is a **required field** on the
  contract's `Route`, derived per call, and a value that is neither of the two raises. The route is
  set on the way **in**: a warm container has no fresh context, so cleanup-on-exit alone lets the
  next request inherit a declaration.
- **An assume failure is a FAULT, never a denial.** STS says `AccessDenied` for a wrong trust
  policy, so the layer *wraps* it — that wrap, not the classifier's ordering, is what holds.
- **The credential cache is keyed on the WHOLE tag set** — never the username alone, which freezes
  membership until the next cold start, and never nothing, which serves B the session of A. Its
  margin is the life of one request, and it retries on a **new** client because boto3 binds
  credentials at construction. **Presigning does not take that margin** — a URL outlives the
  invocation, so `signing_client` takes `covering=` and forces a fresh session when the cached one
  cannot span the window. Clamping against a near-dead session is *correct* and therefore invisible
  to every clamp test.
- **The error shape is a machine CODE plus operator text nobody renders.** Wording is chosen
  client-side from the code; an unrecognised code resolves to the generic sentence.
- **The wire is declared in Python and the TypeScript is GENERATED.** CI refuses a regeneration
  diff, and the type vocabulary is **closed and never falls back**.
- **`$default` matches OPTIONS**, so API Gateway's own CORS responder never sees a preflight and the
  router must answer one **before authentication**. Only a browser enforces CORS, so `curl` cannot
  see this failing. The gateway then overlays its configured CORS headers onto the integration's own
  `OPTIONS` 200 — the router itself emits none (`envelope._headers` returns `content-type` and
  `cache-control` only), so the `access-control-*` headers on a live preflight can only be the
  gateway's. **No offline test asserts that overlay**; it is read from AWS's documentation and
  confirmed only by a live browser run — `testing/sessions.md`, in Chromium, with Safari still owed.
  If it ever stops holding, the failure is **silent on this side**: the router keeps answering 200,
  no preflight carries CORS headers, and every cross-origin request fails the way they all did on
  2026-08-27.
- **`@traced` is outermost everywhere EXCEPT here**: one decorator sits outside it, to turn an
  unpredicted fault into a declared code. A catch *inside* the span ends every failed request
  successfully and records the fault nowhere.
- **A space is resolved from CLAIMS, and the key is still the caller's.** `spaces.resolve` refuses a
  personal space that is not the verified username and a shared one with no membership claim —
  **before any AWS call**, asserted by call count against both the S3 client and the identity door,
  because a refusal issued after a successful `AssumeRole` is indistinguishable from an IAM denial.
  `protected.contained_key` then contains the key, and it **wraps** `cpcommon.paths.assert_inside_root`
  rather than calling it bare: that raises `TerminalError`, which the classifier does not recognise,
  so an unwrapped call answers 500 where the requirement is 403. It fails *safely*, so a test
  asserting "no AWS call happened" passes over it — **assert the reason code**.
- **A prefix is not a key.** `assert_inside_root(root, "")` raises, and an empty prefix is the file
  browser's very first listing request — so a listing prefix and an object key have different
  containment rules.
- **No route waits, sleeps or polls.** A five-minute query against a 30-second gateway ceiling does
  not fail at the margin, it fails always — so the four loops that poll an execution and page its
  results stay in the browser, and the API makes exactly one AWS call per request — with one
  deliberate exception, SPEC-198's free-name probe, which heads up to `FREE_NAME_MAX_ATTEMPTS`
  candidates because the alternative was that many browser round trips.
- **Neither the SQL statement nor Athena's `stateChangeReason` may be a log field.** Both routinely
  quote a user's own cell values back, so the span carries `sql_bytes`, `state`, `row_count` and
  `column_count` instead. The reason still travels on the response body, where the browser's
  authored wording is chosen from it.
- **A failed query is a 200 and a too-early results read is a 409.** The second is classified by
  Athena's MESSAGE, never by its exception name: `InvalidRequestException` is also what a malformed
  query raises at submit, and a name-keyed mapper turns a syntax error into "still running".
- **No route lists more than ONE page.** Every `list_objects_v2` passes `Delimiter='/'` and a bounded
  `MaxKeys`, and no module imports `get_paginator`. A route that walks a subtree recreates the loop
  Arc A moved off the browser, one layer down, under a 29-second ceiling — and it works, for small
  folders, in every test anyone writes. Enforced by `test_api_thinness.py`.
- **The document routes never PARSE and never re-serialise.** Parsing works for every healthy
  document and turns an unparseable one into a 500, which puts the browser's quarantine path out of
  reach. `MAX_DOCUMENT_BYTES` is what keeps the content route from being a second upload path.
- **A presigned URL is a BEARER TOKEN**, signed by the caller's own assumed session and clamped to
  **that credential's** remaining life, read in the same call — `user_client()` assumes internally,
  so clamping from a second read returns a fresh hour while a near-dead session signed the URL. It
  appears in no emitted record: the span carries the key's **length**.
- **A document belonging to no user gets its OWN route.** `_directory/usernames.json` and
  `_config/feature-flags.json` are prefixes no caller's claims authorize, so the space resolver
  refuses them — correctly. Teaching it about them would hand every object route the exemption.

## Adding a route

The wire is declared once, in Python, and the TypeScript is generated from it — so the order matters:
declare, generate, then wire both ends.

1. **Declare it** in `apicommon/contract.py`'s `ROUTES` tuple: an `id` (`noun.verb`), `method`,
   `path`, `idempotent`, `plane`, and the `request`/`response` dataclasses. **`plane` is required and
   has no default** — `"user"` acts as the caller, `"api"` as the service, and getting it wrong
   *succeeds* against the wrong identity.
2. **Write the handler** as a module under `routes/`, and register it in `router.py`'s `HANDLERS`
   dict under the same route id. A route that authenticates is *not* added to `PUBLIC_ROUTES`; that
   set holds `/healthz` and nothing else.
3. **Regenerate the TypeScript**: `python3 scripts/generate_api_contract.py`, which rewrites
   `apps/portal/src/types/apiContract.generated.ts`. Never hand-edit that file.
4. **Call it** through `apiRequest(routeId)` — never a URL — and take the query's `retry` from
   `apiRetryPolicy(routeId)`.

**Three gates fail if you get it wrong**, and each catches a different half: CI reruns the generator
and **refuses a diff**, so a regenerated file that was not committed reddens; `tsc -b` fails at every
call site whose shape changed; and a response annotation outside the closed type vocabulary raises
`UnsupportedTypeError` at generation rather than emitting a permissive type.

`cpcommon.jwks` is imported only by this plane's tests directly, but it is a lazy dependency of
`cpcommon.auth`, which ten planes use — it belongs to `cpcommon`, not here.

Full reasoning: `docs/architecture.md` → *The API's auth boundary*; the arc narrative is in
`docs/specs/ARCS.md`.
