# Completed Spec — SPEC-197: The Transport Contract & the First Ported Feature

## What was completed?

The wire is decided once and declared once. `lambdas/api/apicommon/contract.py` holds the routes,
the closed error enum, the code-to-status map and one type walker; `scripts/generate_api_contract.py`
emits `apps/portal/src/types/apiContract.generated.ts` from it, and CI fails on a regeneration diff.
The browser gained one door — `lib/apiClient.ts`, taking a **route id** rather than a URL — and one
feature went through it end to end.

- **`apicommon/contract.py`** — `Route` (every field required, so a route cannot be declared without
  choosing a credential plane and an idempotency flag), `ERROR_STATUS` (total, image inside the
  closed status set), the shared `walk`, and `validate_request` reading that same walk.
- **`apicommon/envelope.py`** — success is the payload itself; the error envelope is the only
  wrapped shape. `no-store` and a charset on every response.
- **`apicommon/errors.py`** — rewritten onto the envelope. **`ServerError` is retired**: it was not
  in the enum, and `for_exception` returned it for a `ConfigError` raised by a route, so
  "the router never emits a code outside the enum" would have shipped green and false.
- **`router.py`** — dispatch resolved from the contract **per call**, a 404 for an unregistered
  `(method, path)` including a registered path with an unregistered method, and the correlation key
  stamped explicitly.
- **`routes/user_directory.py`** and the ported **`userDirectory.service.ts`** — same signature, same
  promise, one `apiRequest` inside.
- **Both probe routes deleted** — `_auth/whoami` and `_identity/self`, after the live pass of
**2026-08-27** (`sessions.md`) that made that legitimate. FR-014 asks for the two dates: there is one
date, because both sections were run in the same session. **What that pass did NOT cover** is
recorded rather than rounded up: §D.3, §D.5 and §D.6 did not run, and their vehicle is deleted — §D
now carries a status block re-pointing all three at `/v1/user-directory`, which serves them
identically because every one is refused before dispatch.
- **`apiBaseUrl` is required**, across seven wiring sites.

## The defect the live run found, which no offline gate could

**No browser could reach this API with a bearer.** `infra/modules/api/apigateway.tf` declares only
`$default`, which matches `OPTIONS`; AWS auto-answers a preflight only when *no* route matches, so
preflights reached the Lambda and were refused deny-by-default. Browsers require a 2xx preflight, so
every bearer-carrying `fetch` failed as an opaque `TypeError` — the exact failure FR-010 describes,
arriving from a cause the spec does not name.

Isolated from the page: `fetch(API + '/healthz')` → **200**; the same URL with an `authorization`
header → **threw**. Invisible to `curl`, which does not enforce CORS, and to every offline test.
The router now answers `OPTIONS` before authentication, with an empty 200 identical for a path that
exists and one that does not.

## FR-013's disposition table — the artefact the next five ports copy

Ten assertions covered `userDirectory.service.ts`. None was deleted.

| Existing assertion | Disposition |
|---|---|
| reads the key SPEC-146 publishes, from the user-space bucket | **moved** to Python |
| reads the bucket name at call time, not module load | **moved**; replaced in kind on the client by *reads the API base URL at call time* |
| missing document → empty state | **both** (Python: S3 404 → 200 empty; TS: 200 empty → empty success) |
| corrupt document → empty state | **moved** |
| unsupported version, and names it | **moved**, as an `observability.warning` |
| non-array `usernames` → empty | **moved** |
| re-checks every entry against the catalog-safe rule | **both** — the API is now a second producer, and a producer guarantee is still not a runtime guarantee |
| a real fault is a failure | **kept** (a 503 envelope → `{success: false}`) |
| never throws | **kept**, extended to a non-envelope gateway body |
| drops a non-string `generatedAt` | **both** |

FR-009's unchanged list was verified by an empty `git diff` over all **seventeen** files it names,
including `useUserDirectory.test.ts` and the three dialogs. (FR-009 says "all five of their test
files"; only three exist — `AddMembersDialog` has no test file of its own, and is covered by
`members.test.tsx`.)

## Four deviations from the spec as written, each forced

**`apiBaseUrl` gained `VITE_API_BASE_URL`**, against the spec's "No new `VITE_*`". Measured: seeding
the harness the way FR-007 describes reds **69 tests in 3 files**, because `configValue` consults the
dev fallback only while no document is loaded — a one-key seed switches twenty-plus `vi.stubEnv`
suites onto the document path. Keeping the `null` fallback instead needs an exception in `env.ts`,
and the dev-boot warning then prints `missing required variables:` followed by nothing, forever
(`[null].join(', ')` is the empty string). A fallback gives every required key one shape and needs no
exception. Approved by Andrew before the change.

**The plane is derived from `Route.plane`, per call, and the guard's teeth moved.** The spec's
set-equality between the route table and `ROUTE_PLANES` becomes a tautology once one derives from
the other, so it is **retained as a regression tripwire and labelled as one**. What carries the
guarantee instead: `plane` is a required `Literal` field, and an unrecognised value **raises at
derivation** — the half a set equality could never carry, because a typo resolving quietly to
user-only is indistinguishable from a correct user-only route.

**The token provider takes `forceRefresh`.** FR-008 requires the 401 path to force a refresh, and a
no-argument provider cannot express it. Registered from `AppRoot.tsx`, not `main.tsx`, whose static
import set is asserted by equality both directions.

**The timeout constant in the spec names the wrong thing.** `API_GATEWAY_INTEGRATION_TIMEOUT_SECONDS
= 29` conflates two values: the integration's ceiling is **30,000 ms** and the *function's* timeout
is **29 s**. The repo already carries the correct pair in `cpcommon.jwks`; the client mirrors those
names and pins the ordering against them.

## What was measured rather than argued

- **Mutation-tested, twenty-two times.** Every guard was broken and watched to redden: the walker
  falling back, a second walker in the generator, a non-deterministic emitter, the correlation stamp
  dropped, an unvalidated client id, the response body stamped as telemetry, the echo bound removed,
  the decorator order swapped, a passthrough code added to the contract, a feature calling `fetch`,
  the route truncating, a denial read as the empty state, the version gate dropped, browser-wide
  token storage, the storage set before `configure`, a renamed client header, `configValue` reached
  from `lib/`, a dotted `window.fetch`, a drifted timeout copy, `apiRetryPolicy` always retrying,
  and a plane arm resolving through a stub of the function under test.
- **One plant found a bug in my own test rather than in the code**, which is why the step exists: a
  failed `cd` meant the file was never written and I was re-running the original suite.
- **`tsc -b` caught what 2938 passing tests could not** — a mock's inferred arity.
- Coverage: portal **92.88 / 89.11 / 92.39 / 94.81** against floors of 91/86/89/93; `pytest lambdas/`
  **97.35%** against 95.

## What the two diff reviews found, and what changed because of them

Both reviewers ran the gates and planted their own mutations; between them they confirmed 28 guards
hold and found nine that did not, four of which were **functional gaps rather than test defects**:

- **FR-011's `status`, `code` and `actor` were never stamped.** Every enveloped failure is
  *returned* rather than raised, so the span's own status read `"ok"` for a 401, a 403 and a 404
  alike — and Phase 5's live check, which says to read `status` and `actor` back, would have read
  as satisfied while carrying no information. Now stamped on every return path.
- **`validate_request` was on no runtime path.** Unit-tested and called by nothing: the AC was true
  of the function and false of the system, and SPEC-198's first `POST` would have inherited an
  unvalidated body with no way to notice. The body is now parsed at the entry point, checked in the
  router, and still never reaches a handler.
- **The generator read the error enum by field POSITION**, so reordering `ApiErrorDetail` — which
  Premise 4 explicitly invites — emitted `API_ERROR_CODES = []` and both wording guards passed over
  an empty set. It reads the enum's own declaration now, and refuses to emit an empty one.
- **`NoSuchBucket` was folded into "the document is missing"**, so a wrong bucket name answered 200
  with an empty list — a misconfiguration wearing the costume of the ordinary pre-builder state,
  which is precisely what the live check cannot tell apart. Removed; it is a fault.

And three guards that were green while measuring nothing: `apiRetryPolicy`'s false arm (one route
exists and it is idempotent, so `return 1` passed), the two one-door sweeps (scoped to `features/`,
so a `fetch` in `lib/` passed — proved by planting one; and `window.fetch(` walked past the regex),
and a comment claiming the client's timeout constants were pinned to the Python when nothing read
them. All four are now driven, and each fix was re-verified by planting the original mistake.

The blocking finding was an ordering one: the first commit referenced a module the second creates,
so PR 1 would have failed CI and never merged. The CORS commit is now infrastructure alone.

## Three guards that had to move rather than be weakened

**The 403-minting guard** named `apicommon/errors.py` as the one place a 403 is written. A status is
now decided once in the contract's map, so the guard names `contract.py` — the property and its
reason are unchanged, and only the "one place" moved.

**The echo bound** was asserted on a response body that no longer echoes the path. It is re-pointed
at the **log record**, which the module docstring always said was the half that mattered — and which
nothing recorded until this spec added a record for an unserved route, so the claim had been true
and unchecked.

**The directory tripwire** forbids any Lambda naming the directory document, because it is advisory
and never an authorization input. The serving route legitimately reads it, so it is allowlisted with
a written reason **and** a new test asserting the route reaches no authorization helper — "it only
serves it" is a claim that stops being true one convenience check later. The guard also had to be
made AST-based: matched against raw text it tripped on the route's own docstring, and a tripwire that
fires on its own explanation is one somebody deletes.

## Also in this branch, at Andrew's direction

**Cognito tokens moved to tab-scoped storage**, as its **own commit**. Amplify defaults to
`localStorage`, where an ID token survives a browser restart and is readable by anything on the
origin. Out of SPEC-197's scope — sign-in is explicitly untouched — and included because Andrew asked
for it with this work. The cost is deliberate and visible: closing the tab ends the session, and a
second tab signs in again.

**It touches the one thing a warm session cannot exercise**, so it ships with owed rows rather than
a claim: that the Hosted UI redirect still completes with tab-scoped storage, and that a second tab
signs in cleanly. SPEC-192's fresh-sign-in-in-a-private-window check is **re-invalidated** by it.

## Help & guides: nothing for the PORT, and one thing for the session change

**The port changes nothing user-facing.** The same three dialogs suggest the same names with the
same wording, and no error text moved: every code this spec adds resolves to a sentence already in
`errorMessages.ts` or to the generic fallback.

**The tab-scoped token change IS user-visible**, and saying "nothing user-facing" of this branch as a
whole would have been false. Closing the tab ends the session; a second tab signs in again; a link
opened in a new tab lands on sign-in. `helpContent.ts` documents no session-lifetime behaviour at
all — there is no "stay signed in" promise to correct — so nothing in it became untrue and no guide
was added for a behaviour whose live verification is still owed. Both halves are recorded in
`owed.md`, and the change ships as **its own commit** so it can be reverted without the port.

## Owed

`arc-b-api-container-e2e.md` **§F** is written and **not run**; every item is a row in `owed.md`.
The isolation proof and a live 403 pass to **SPEC-198** — this route's grant is unconditioned and its
bytes are identical for every caller, so it cannot demonstrate isolation and does not claim to.
`setUnauthenticatedHandler` ships with no handler registered, deliberately.
