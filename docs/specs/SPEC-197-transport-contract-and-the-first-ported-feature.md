# Spec: The Transport Contract & the First Ported Feature

**ID:** SPEC-197
**Status:** Completed
**Last Updated:** 2026-08-18
**Depends On:** SPEC-192 (`lib/runtimeConfig.ts` — `apiBaseUrl`, the call-time accessor, `seedRuntimeConfig`), SPEC-193 (the HTTP API, the `$default` proxy integration, the single Lambda and its internal router, and the CORS block this spec adds one header to), SPEC-195 (the API's auth boundary — the verified bearer, the claims the router hands on, the SPA's token provider, and the `error.stack` treatment this spec inherits), SPEC-196 (the credential planes, `ROUTE_PLANES`, and the three failure conditions whose statuses and codes this spec serialises), SPEC-106 (`toUserMessage` is the only source of user-facing wording — the constraint the error shape is built around), SPEC-146/147/158 (the username directory: the published document, the forgiving reader, and the `SuggestionSource` prop lift), SPEC-153/163/186 (the set-equality guard, the registry-walked-in-both-states discipline, and the `?raw` sweep), SPEC-127/137/186 (`cpcommon.observability`, the field rule, and `env`/`version` on every record)

## Overview

Seventeen `*.service.ts` files call AWS from the browser. Each one of them will be rewritten to call
an HTTP API instead, and the only thing that makes that a mechanical exercise rather than seventeen
separate designs is a transport contract decided once. This spec decides it: how a route is named and
versioned, what a success body looks like, what an error body looks like, which status each condition
produces, how a Python API and a TypeScript SPA are held in agreement without either one being trusted
to match the other by hand, and what the browser's single API client does and — more importantly —
refuses to do.

It then ports one feature end to end, to prove the shape against real code rather than against a
diagram. **`features/user-directory/` is the right first subject precisely because it writes nothing:**
one `GetObject` of `_directory/usernames.json`, three dialogs consuming it, advisory by decision, and a
forgiving reader whose whole promise is that an unavailable list produces no suggestions and no error
banner. A defect in the port shows up as suggestions that stop appearing — not as a lost file.

**This is the arc's spine, and five specs copy whatever it sets.** A defect here is a defect eleven
times, so each requirement below names the assertion that separates an enforced rule from an
unenforced one. Two of those are the whole point of the spec: the error shape must not quietly hand
user-facing wording back to the server (SPEC-106), and `ServiceResult<T>` must not change at the
service boundary (which is why the other sixteen services can be ported without touching a hook or a
component).

## Scope

### In Scope

- **The route contract**: `/v1/` naming, the versioning rule, the closed status set, and what an
  unregistered route does (FR-001).
- **The success envelope** and the pagination shape, including the opaque continuation token
  (FR-002).
- **The error envelope**: a stable machine `code`, an operator `detail` that is never rendered, and
  the correlation id (FR-003).
- **What the SPA does with a code it does not recognise**, and the guard that keeps the server out of
  the wording business (FR-004).
- **The two-language agreement mechanism**: the contract is declared in Python, the TypeScript is
  **generated** from it, and CI fails on a regeneration diff (FR-005).
- **The router/contract/plane set-equality guard** — a route cannot exist without a handler and a
  credential plane (FR-006).
- **`lib/apiClient.ts`**: base URL, bearer, timeout, correlation id, abort, and the mapping of every
  non-envelope failure (FR-007).
- **The retry rule**, declared per route and enforced in one place (FR-008).
- **`ServiceResult<T>` unchanged**, asserted rather than assumed (FR-009).
- **CORS**: the one header this spec adds, and the guards on the two things it must not narrow
  (FR-010).
- **Observability**: one span per request through `cpcommon.observability`, the correlation trap, and
  the field rule applied to a service that handles a bearer token (FR-011).
- **`GET /v1/user-directory`** (FR-012) and the ported client (FR-013), with a named disposition for
  every existing assertion.
- Removing **both** temporary probe routes — SPEC-195's `GET /_auth/whoami` and SPEC-196's
  `GET /_identity/self` — and saying what that costs (FR-014).

### Out of Scope

Everything a reader would reasonably assume travels with "we built the API contract":

- **Every other service.** Sixteen `*.service.ts` files keep calling AWS directly, and every
  `@aws-sdk/*` import stays. The S3 surface is SPEC-198, the catalog SPEC-199, the queues SPEC-200.
- **All bytes.** No presigned URL, no upload, no download, no `lib-storage`, no progress reporting.
  SPEC-198.
- **All queues.** No enqueue route, no `{actor, delegated_by, assurance}`, no change to any control
  plane's message contract. SPEC-200/201.
- **Retiring anything.** `lib/awsCredentials.ts`, `lib/s3Client.ts`, `lib/s3Json.ts`,
  `infra/modules/app`, the Identity Pool, the dev-unauth path and every `@aws-sdk/*` dependency are
  untouched. `lib/s3Json.ts` keeps six other callers after this spec and is not edited.
- **Sign-in.** Cognito, Amplify, Managed Login v2 and `lib/returnPath.ts` are exactly as they are (the
  arc's 2026-08-18 re-scope). This spec's 401 hands off to a callback SPEC-195 registers; it decides
  nothing about what that callback does.
- **A user-visible request id.** `ServiceResult`'s error carries `{message, code}` and gains no third
  field — see FR-009. The correlation id reaches the developer console and `logs/`, not the UI.
- **A parameterised error message.** The envelope carries no field the SPA renders. A later spec that
  needs "already exists: `notes.txt`" adds a typed `params` object to the contract and formats it
  **client-side**; it does not send a sentence. See Premise 4.
- **Server-side caching, an authorizer, a WAF, a rate limit, an idempotency-key mechanism.** Deferred
  by the arc; the retry rule (FR-008) is what stands in for the last one.
- **Any change to SPEC-146's builder.** `lambdas/user-directory-build` and its no-Cognito tripwire are
  not touched, read, or re-specified here.

### What exists today, and which spec replaces it

| Today | Owner |
|---|---|
| `userDirectory.service.ts` → `readJsonDocument` → `GetObjectCommand` in the tab | **This spec**, FR-013 — same signature, same `ServiceResult`, `fetch` inside |
| The document's `version` gate, `usernames` array check, `CATALOG_IDENTIFIER_RE` filter, in TypeScript | **This spec**, FR-012 — moved to Python, with the entry re-check kept on **both** sides |
| `useUserDirectory`, `usernameTrie`, `UsernameCombobox`, `UsernameChipsField`, the three dialogs | **Unchanged**, byte for byte. That is the claim FR-009 exists to make checkable |
| SPEC-193's placeholder 404 body | Replaced by FR-003's envelope |
| SPEC-195's `GET /_auth/whoami` and `routes/whoami.py`; SPEC-196's `GET /_identity/self` and `routes/identity_self.py` | **Both deleted**, FR-014 |
| `apiBaseUrl` classified **optional** in `lib/runtimeConfig.ts` (SPEC-192) | **Required**, FR-007 |
| Every other AWS call in the browser | SPEC-198 → 200 |

### Premises later specs must honour

1. **A route is named in the contract, never in a call site.** `apiRequest` takes a route id, not a
   URL. A service that builds a path string is outside every guard in FR-005 and FR-008 at once.
2. **The API never phrases a user-facing message.** `detail` is operator text in English, read in a
   devtools panel and in `logs/`, and rendered nowhere. Wording is `lib/errorMessages.ts` and only
   `lib/errorMessages.ts` (SPEC-106). FR-004's disjointness guard is what keeps that true as codes
   are added.
3. **Additive-only within `/v1/`.** The API and the SPA deploy through different workflows onto
   different runtimes, and a loaded tab keeps its old bundle across an API deploy. Removing or
   renaming a response field is a `/v2/`, not a patch.
4. **The envelope has no free-text field the SPA renders**, and no later spec may add one. A message
   needing specifics gets typed `params` in the contract and a client-side formatter.
5. **Every route declares a credential plane** (SPEC-196's `ROUTE_PLANES`) and an `idempotent` flag.
   Both are part of the route declaration, not of the handler, so FR-006's guard can see them.
6. **The bearer never reaches a handler.** The router verifies it (SPEC-195) and discards it before
   dispatch; handlers receive verified claims. That is what makes FR-011's field rule structural
   rather than a habit.
7. **`ServiceResult<T>` is frozen for the arc.** Sixteen ports depend on it. A spec that wants a
   third field on the error object is proposing to touch every service, hook and consumer in the app
   and must say so out loud.


---

## Functional Requirements

### FR-001: Route naming, versioning and the closed status set

#### Description:

One naming rule, one version, one finite set of statuses the router may emit — so a reader of the
seventeenth ported route learns nothing new from it.

#### Acceptance Criteria:

- [ ] Every route path is `/v1/{noun}[/{segment}]…`, lower-case kebab, plural for a collection. A test
      walks the generated route table and fails on any path not matching `^/v1/[a-z0-9-]+(/[^/]+)*$`.
- [ ] `GET /healthz` (SPEC-193) is the **only** unversioned path and is excluded by exact match, never
      by a prefix rule.
- [ ] `v1` versions the **whole API**, never a route. There is no `/v1/x` beside a `/v2/x`, and no
      route carries a version in a header or a query parameter.
- [ ] An **unregistered** `(method, path)` pair returns **404 `NotFound`** — not 405. One rule, and a
      405 would advertise which paths exist to a caller who may not use them. A test asserts
      `POST /v1/user-directory` (a registered path, an unregistered method) returns 404, which is the
      case a reader assumes is a 405.
- [ ] The router may emit exactly these statuses and no others: **200, 400, 401, 403, 404, 409, 413,
      415, 429, 500, 503**. A test enumerates the code→status map (FR-003) and asserts its image is a
      subset of that set, and that the map is **total** — every declared code has exactly one status.
- [ ] **No 204 and no 3xx.** A route producing no data returns 200 with `{}`, so the client has one
      parse path. A test asserts no handler returns a body-less response.
- [ ] The statuses API Gateway produces **above** the router — its own 413 at the 10 MB payload limit,
      429 under account throttling, 502/504 on an invocation failure or timeout — are **not**
      envelope-shaped and are outside this set. They are the client's problem, and FR-007 AC7 is where
      they are handled. Naming them here is the point: a reader who assumes every non-2xx is an
      envelope writes a client that throws a `SyntaxError` the first time the gateway answers.

### FR-002: The success envelope and pagination

#### Description:

Success bodies are the payload itself. The error envelope is the only wrapped shape in the API, and
that asymmetry is deliberate: a `{data: …}` wrapper adds a level every one of seventeen services must
strip and buys nothing the status code does not already carry.

#### Acceptance Criteria:

- [ ] Every 200 body is a JSON **object** — never a bare array, string, number or `null` — so an
      additive field (Premise 3) always has somewhere to go. A test asserts every declared response
      type in the contract is an object type; a route declaring `list[str]` as its whole response
      fails the generator (FR-005).
- [ ] `Content-Type: application/json; charset=utf-8` on every response, success and failure.
- [ ] `Cache-Control: no-store` on every API response. These are authorized reads; a caching layer
      between the browser and the API is a cross-user disclosure, and the failure is silent because
      the first user sees exactly the right answer.
- [ ] **`nextToken` is the paging contract; `items` is not.** Every paged route's response object
      declares `nextToken: str | None`, and `nextToken` is **opaque** — the client stores and returns
      it unmodified and never parses, decodes, or compares it. A paged route whose page is a
      homogeneous collection names that collection `items` (SPEC-198's `GET /v1/objects` is
      `{items: ObjectEntry[], nextToken}`); a paged route whose page is **not** a bare collection
      carries its own payload keys beside `nextToken` instead — SPEC-199's results route is
      `{columns, rows, nextToken}`, because a tabular page is two parallel shapes and wrapping it as
      `items` would either lose the column list or nest the rows a level deeper for every consumer.
      Fixing `items` as universal here would put this spec in conflict with SPEC-199 on the day it
      lands. The test is on the contract: every route declaring a `nextToken` field declares it as
      `str | None`, and no route declares a paging field under any other name.
- [ ] `nextToken` is carried as a query parameter and is **URL-encoded by the client**. S3's
      `NextContinuationToken` is base64 and routinely contains `+`, `/` and `=`; unencoded, `+` decodes
      to a space server-side and the next page silently restarts from the beginning rather than
      erroring. A test round-trips a token containing all three characters through `apiRequest` and
      asserts the value the handler receives is byte-identical to the value the API emitted.
- [ ] There is **no offset or page-number pagination** anywhere in the contract, and no `total`. S3
      reports no total (SPEC-174 already lives with that); inventing one here would be a second lie in
      a second language.

### FR-003: The error envelope — a machine code, and operator text nobody renders

#### Description:

The single decision this spec cannot get wrong. SPEC-106 makes `lib/errorMessages.ts` `toUserMessage`
the only source of user-facing wording, and forbids rendering raw AWS/Cognito/Athena text. An API that
returns a sentence for the SPA to display reverses that — quietly, because the sentence would look
fine in every screenshot.

#### Acceptance Criteria:

- [ ] A failure body is exactly `{"error": {...}}` — one wrapped object, nothing beside it — and the
      inner object's key set is `{code, requestId}` plus the optional `detail`. **The test asserts the
      emitted key set against the error type declared in `contract.py`, not against a literal written
      in the test**, because Premise 4 reserves the right to add a typed `params` object here and a
      frozen literal would make that a contradiction rather than an addition. What is frozen is the
      *character* of the fields, and FR-004 is what enforces it: no key the SPA renders as prose. A
      later spec adding `params` adds it to the declaration, so the generated TypeScript, the
      validator and this assertion all move in one edit; a spec adding a free-text `message` is
      refused by Premise 4, not by this criterion.
- [ ] `code` is drawn from a **closed** enum declared in the contract (Data Model). The v1 set is
      `InvalidRequest`, `SessionExpired`, `AccessDenied`, `NotFound`, `Conflict`, `PayloadTooLarge`,
      `UnsupportedMediaType`, `RateLimited`, `IdentityUnavailable`, `InternalError`, `ApiUnavailable`.
- [ ] `detail` is **operator text authored at the raise site**, in English, optional, and never a
      stringified exception. A test raises a botocore `ClientError` whose message contains a role ARN
      and an account id, and asserts neither string appears anywhere in the response body — the same
      assertion SPEC-196 FR-007 makes, now at the layer that serialises it.
- [ ] `requestId` is the API Gateway request id (FR-011), echoed so a user-reported failure is findable
      in `logs/`.
- [ ] **Every bearer failure is 401 `SessionExpired`** — missing, malformed, expired, wrong issuer,
      wrong audience, wrong `token_use`, missing username claim. **SPEC-195 FR-004 owns that
      contract**, including the deliberate absence of an expiry discriminator and the byte-identical
      bodies; this spec's job is to serialise it into the envelope without adding a distinction, and
      the test is that `SessionExpired` is the **only** 401 code the enum admits. A downstream
      `AccessDenied`, including every Lake Formation denial, is **403 `AccessDenied`** and must never
      trigger a re-login: it is the isolation model working. A test asserts the two produce different
      statuses **and** different codes; a mapper collapsing them passes any test that exercises one at
      a time (SPEC-196 FR-007).
- [ ] 403 says "this request was refused" and never "that thing exists and you may not have it".
      SPEC-113's no-existence-oracle rule survives the move: a route asked about a space this caller
      cannot reach refuses **without probing AWS**, so the 403 discloses nothing. Per-route work lands
      in SPEC-198/199; the contract-level rule is fixed here.
- [ ] The router **never** emits a code outside the enum, including on an unhandled exception: the
      outermost handler maps anything unrecognised to `InternalError` (500) with a `detail` naming the
      exception **type** and no message. A test raises a bare `RuntimeError('secret value')` inside a
      handler and asserts `secret value` appears in no response body.
- [ ] 409 `Conflict` and 413 `PayloadTooLarge` are declared in v1 and produced by no route in this
      spec. They are reserved deliberately, so SPEC-198 adds a route rather than a status class.

### FR-004: What the SPA does with a code it does not recognise

#### Description:

The other half of FR-003. A server that does not phrase messages only helps if the client does not
render what the server sent — and this repo has a mechanism that would render it by accident.

#### Acceptance Criteria:

- [ ] `apiClient` builds a failure `ServiceResult` whose `error.code` is the server's `code` **verbatim**
      and whose `error.message` is chosen **client-side**, from a table owned by
      `lib/errorMessages.ts`. The server's `detail` goes to `logOriginal` (dev builds only) and
      nowhere else. A test puts a distinctive marker in `detail` and asserts it appears in no
      `ServiceResult.error.message` and in no rendered DOM.
- [ ] An **unrecognised** code — one this build has no rule for — resolves through `toUserMessage` to
      the existing generic `Something went wrong. Contact the Administrator.` A test sends
      `code: "SomeCodeFromANewerApi"` and asserts exactly that string renders. This is the deploy-skew
      case: the API deploys before the SPA image, so an old bundle **will** meet a new code.
- [ ] **The passthrough trap is closed by a derived guard.** `CODE_RULES` contains eight `passthrough`
      rules (`Collision`, `ProtectedObject`, `InvalidName`, `InvalidDestination`, `TooLarge`,
      `NotConfigured`, `SelectionTooLarge`, `SavedQueryNotFound`) whose whole behaviour is *return the
      service `message` unchanged*. If the API ever returns one of those codes and the client puts
      server text into `error.message`, SPEC-106 is reversed through a rule written to uphold it.
      `errorMessages.ts` exports `PASSTHROUGH_CODES` (computed from `CODE_RULES`, not hand-listed), and
      a test asserts `API_ERROR_CODES ∩ PASSTHROUGH_CODES = ∅` from the generated table and the
      computed set — **two derived sets, never two lists**. Verified by adding a passthrough code to
      the Python contract and watching the test fail.
- [ ] Every code in `API_ERROR_CODES` has a rule in `lib/errorMessages.ts`, asserted by set equality
      in the same test. A missing rule is not a crash — it is the generic fallback, which is the
      *right* behaviour for an unknown code and the *wrong* behaviour for a known one, and only a guard
      tells them apart.
- [ ] `apiClient` mints two codes the server can never produce — `RequestTimeout` and
      `NetworkUnavailable` — declared in `lib/apiClient.ts`. They are deliberately **not** in the
      generated enum, and the disjointness guard covers all three sets.

### FR-005: The two-language agreement mechanism — derived, not hand-maintained

#### Description:

The API is Python and the SPA is TypeScript, and the arc settled that something must hold them in
agreement. **The contract is declared once, in Python, and the TypeScript is generated from it.** Two
hand-edited copies rot; a contract test both sides hand-wrote against each other is agreement between
two guesses, and it agrees most confidently exactly when both were written by the same session on the
same afternoon.

Python is the source rather than TypeScript because the runtime request validator and the wire types
must read one declaration — a validator written against a separate schema is a third copy.

#### Acceptance Criteria:

- [ ] `lambdas/api/apicommon/contract.py` is the single declaration: the `Route` records (id, method,
      path, `idempotent`, `plane`, request type, response type), the `ErrorCode` literal union, and the
      code→status map. Nothing about the wire is declared anywhere else in Python.
- [ ] `scripts/generate_api_contract.py` emits
      `apps/portal/src/types/apiContract.generated.ts` — the response/request types, `API_ROUTES`,
      `API_ERROR_CODES` — from `typing.get_type_hints`, in a **deterministic** order. A test runs the
      generator twice and asserts byte-identical output.
- [ ] **The supported type vocabulary is closed**: `str`, `int`, `float`, `bool`, `None`,
      `list[X]`, `X | None`, `Literal[...]` over strings, references to other declared `TypedDict`s,
      and **optional keys** — a `TypedDict` declared `total=False`, or a field annotated
      `NotRequired[X]` — which emit as `key?: X`. Optionality is in the vocabulary because the
      contract needs it on the day it ships: the error envelope's `detail` is optional (FR-003), and
      SPEC-198 declares an `ErrorParams(TypedDict, total=False)`. Leaving it out would make the
      generator raise on this spec's own error type, and the repair a builder reaches for is a
      fallback type. `X` inside an optional key is itself drawn from this vocabulary, recursively.
      Anything else **raises and fails the generator**. It never emits `unknown` and never emits `any`.
      This is the requirement that can silently succeed: a fallback type agrees with every possible
      value, so the day the generator meets a shape it does not understand is the day the contract
      stops being checked, and nothing goes red. A test feeds a fixture contract carrying a
      `dict[str, object]` field and asserts the generator raises.
- [ ] `ci.yml`'s `lambdas` job runs the generator and then `git diff --exit-code` on the generated
      file. That is gate one, and it catches **both** directions of drift: a Python type edited without
      regenerating, and the generated TypeScript hand-edited.
- [ ] `npm run build` (`tsc -b`, the only real typecheck — SPEC-150/#363) is gate two: a field removed
      or renamed in Python regenerates into a changed TS type and fails at every call site. A test is
      not what catches this; the compiler is.
- [ ] The generated file carries a `// GENERATED by scripts/generate_api_contract.py — do not edit.`
      header, is listed in `apps/portal/.prettierignore`, and is excluded from ESLint. Without the
      first, `format:check` reddens a PR for a file no human wrote; without the exclusion the fix is to
      hand-format a generated file, which gate one then rejects.
- [ ] `scripts/generate_api_contract.py` is inside `ruff check lambdas/ scripts/`'s existing scope and
      carries the `lambdas/` docstring standard.
- [ ] **The runtime validator reads the same declaration.** `apicommon.contract.validate_request(route,
      body)` validates against the route's declared request type and returns 400 `InvalidRequest`;
      there is no second schema. A test asserts a body with an unknown key, a missing key and a
      wrong-typed key are each refused, and that the validator's supported vocabulary is the
      generator's (one shared walker, asserted by identity, not by resemblance).
- [ ] Rejected alternatives, recorded so they are not re-proposed: two hand-maintained copies (rots,
      and this repo's rule is that a hand-maintained list rots); a hand-written contract test on both
      sides (compares a copy of the answer with itself — SPEC-162's validator problem exactly); OpenAPI
      plus an off-the-shelf codegen (a new pinned toolchain and a new scanner surface, for a vocabulary
      whose emitter is under a hundred lines).

### FR-006: A route cannot exist without a handler and a plane

#### Description:

Three declarations must agree — the contract's routes, the router's handlers, and SPEC-196's
`ROUTE_PLANES`. The registry discipline (SPEC-163) is that the guard checks **set equality**, both
directions, and is verified by a deliberate violation rather than by reading the config.

#### Acceptance Criteria:

- [ ] A test asserts `{route ids in ROUTES} == {route ids the router has handlers for}`. Both
      directions can fail: a route with no handler (a 404 the contract promises works) and a handler
      with no route (dead code the router will never dispatch, which is what FR-014's deletion would
      otherwise leave behind).
- [ ] A test asserts `{route ids in ROUTES} == {keys of ROUTE_PLANES}`. A new route cannot be added
      without choosing `user` or `api`, and SPEC-196's guard fails closed on an unknown plane.
- [ ] Both guards are verified by committing a violation in each direction during the build and
      confirming red — recorded in the delivery doc, not asserted from the config file (SPEC-176's
      rule: a guard written in the working rule's shape resolved onto the right files and caught
      nothing).
- [ ] The router dispatches on `(method, path)` from the contract table, not from a chain of `if`
      statements over `event["rawPath"]`. A test asserts adding a row to `ROUTES` with a registered
      handler makes the route reachable with no other edit.

### FR-007: `lib/apiClient.ts`

#### Description:

One module, one door. Everything the browser sends to the API goes through it, and it is in `lib/`,
which under SPEC-155's ESLint rule **may not import from `features/`** — so both of the things it
needs from the auth feature are injected, not imported.

#### Acceptance Criteria:

- [ ] `apiRequest(route, opts)` takes a **route id** from the generated table, never a URL. Its return
      type is `Promise<ServiceResult<ResponseOf<typeof route>>>`, so a call site cannot mis-type the
      response.
- [ ] The base URL is `configValue('apiBaseUrl')` read **at call time**, never captured at module load
      (SPEC-192's convention). `apiBaseUrl` moves from `OPTIONAL_CONFIG` to `REQUIRED_CONFIG`, and its
      deploy wiring (the ECS task environment, the repo variable, `.env.example`) is checked by
      SPEC-192's key-set agreement tests with no new mechanism.
- [ ] The bearer comes from a provider registered once: `setAuthTokenProvider(() => Promise<string |
      null>)`, called by SPEC-195's SPA half. `lib/apiClient.ts` imports nothing from `features/`, and
      the existing ESLint rule is what enforces it.
- [ ] **No provider registered, or the provider returns `null` → the client returns `SessionExpired`
      and issues ZERO network requests**, asserted by a `fetch` call count of 0. Every consuming hook
      already gates on a signed-in user (`enabled: !!user`), and an unauthenticated burst on mount is
      a real pattern in this app.
- [ ] Headers: `authorization: Bearer …`, `x-request-id` (FR-011), and `content-type: application/json`
      **only when there is a body**. `credentials: 'omit'` is set explicitly, so a cookie that appears
      on this domain for any reason is never sent.
- [ ] **Timeout is 30,000 ms**, via `AbortController`, and the constant is pinned by a test against a
      declared `API_GATEWAY_INTEGRATION_TIMEOUT_SECONDS = 29`. It is deliberately **above** API
      Gateway's ceiling — which is not raisable on an HTTP API — so the *server's* timeout always fires
      first and a client abort means a genuinely dead connection. A shorter client timeout aborts
      requests the server then completes, which for a write is a mutation the user believes failed.
- [ ] An abort produces `RequestTimeout`; a `fetch` rejection produces `NetworkUnavailable`. **A CORS
      failure is indistinguishable from a network failure** — the browser hands `fetch` an opaque
      `TypeError` — so a mis-set allowed origin presents to a user as "the API is down". That is why
      FR-010's assertion is a header read from `curl` and not "the app worked".
- [ ] **A non-envelope failure body is mapped by status, never parsed for text.** A test feeds API
      Gateway's own `{"message":"Forbidden"}`, an HTML error page, and an empty body, at statuses 413,
      429, 502 and 504, and asserts each produces a mapped code (`PayloadTooLarge`, `RateLimited`,
      `ApiUnavailable`, `ApiUnavailable`), that nothing throws, and that `Forbidden` reaches no
      `error.message`.
- [ ] A 401 first takes SPEC-195 FR-008's single refresh-and-retry (FR-008's one exception). Only a
      401 that **survives** the retry invokes the handler registered by `setUnauthenticatedHandler`
      and returns `SessionExpired` — so an ordinary hourly expiry never reaches the handler at all.
      `apiRequest` itself **never navigates**: a service that navigates makes every test touching a
      401 a navigation test, and makes a background refetch able to throw the user out of a form.
- [ ] A sweep asserts no module under `apps/portal/src/features/**` calls global `fetch`, and no
      module outside `lib/apiClient.ts` constructs a URL from `apiBaseUrl`.
- [ ] `renderWithProviders` seeds a runtime config containing `apiBaseUrl` (SPEC-192's
      `seedRuntimeConfig`). Without it every ported feature's test throws `RuntimeConfigNotLoadedError`
      from the accessor, and the first spec to discover that is the one whose diff is largest.

### FR-008: The retry rule

#### Description:

`apiRequest` retries **nothing**, with exactly one named exception — SPEC-195's single refresh-and-retry
on a 401. Whether a call may be retried *above* the client is a property of the route, declared in the
contract, and consulted in one place.

This is explicit because the repo has already paid for it: a failing apply in the Data Explorer issued
**two** `StartQueryExecution` calls ~1.1 s apart, which read as a double-subscribe and was
`retry: 1` — a retry on something that looks like a read and is a billed, stateful action. On the
write side, SPEC-167 mints a `requestId` per **submit** precisely so a retry is not a silent no-op;
which means a retried enqueue is either a duplicate request or nothing at all, depending on a field the
transport layer does not control.

#### Acceptance Criteria:

- [ ] `apiRequest` performs zero retries under every condition, including a timeout, a 429, a 503 and
      a network failure. A test asserts exactly one `fetch` call per `apiRequest` call in each case.
      Retrying a 429 amplifies the condition that caused it.
- [ ] **There is exactly ONE exception, it is named here, and it is SPEC-195's:** a **401** triggers
      one forced ID-token refresh (`getIdToken(true)`) and one retry — and no more, so a second 401 on
      the retry resolves to `SessionExpired` without a third request. SPEC-195 FR-008 owns that
      behaviour and its tests; this criterion exists so the zero-retry rule above cannot be read as
      contradicting it. **This is a live hazard, not a tidiness point:** that refresh is the browser's
      only token-refresh path, so a builder who implements the zero-retry test literally and deletes
      it signs every user out at the hour mark, with a green suite. The test that says so is a count:
      a 401-then-200 sequence issues exactly **two** `fetch` calls, and a 401-then-401 sequence issues
      exactly two as well.
- [ ] Each route declares `idempotent: bool` **explicitly** in the contract. It is **not derived from
      the method**: a `POST` that resolves a free name is a read, and a `PUT` that appends is not.
- [ ] `apiRetryPolicy(routeId)` in `lib/apiClient.ts` is the only source of a TanStack Query `retry`
      value for an API-backed hook, and returns `false` for every route whose `idempotent` is false. A
      test enumerates the generated `API_ROUTES` and asserts it — so a route added later is covered
      without the test being edited.
- [ ] A `?raw` sweep over `apps/portal/src/features/**` fails on any file that imports `apiRequest`
      and also passes a `retry:` option that is not `apiRetryPolicy(...)` or `false`.
- [ ] `userDirectory`'s route is `idempotent: true`, and `useUserDirectory` keeps `retry: false` — its
      existing value, for its existing reason (a missing document is already the empty success, so
      anything reaching the hook is a real fault and retrying only delays the fallback to free text).
      The port does not change it.

### FR-009: `ServiceResult<T>` is unchanged at the service boundary

#### Description:

The reason sixteen further services can be ported without touching a hook, a component or a test. It
is worth an explicit requirement because it is exactly the kind of thing a port erodes one convenience
field at a time.

#### Acceptance Criteria:

- [ ] `apps/portal/src/types/service.types.ts` is **not edited by this spec**. Asserted in the diff,
      and by a test that the failure arm's error object has exactly the keys `message` and `code`.
- [ ] `getUserDirectory()` keeps its exact signature — `(): Promise<ServiceResult<UserDirectory>>` —
      takes no new parameter, and still never throws (a test throws from `fetch` itself and asserts a
      resolved failure result).
- [ ] `useUserDirectory.ts`'s **exported behaviour is unchanged**, and `useUserDirectory.test.ts` is
      unchanged **byte for byte**. It mocks `./userDirectory.service`, so it cannot see the transport
      at all — which is the property being demonstrated, and the cheapest possible proof of it.
- [ ] `usernameTrie.ts`, `comboboxPlacement.ts`, `UsernameCombobox.tsx`, `UsernameChipsField.tsx`,
      `useUsernameSuggestions.ts`, `userDirectoryKeys.ts` and all five of their test files are unchanged.
- [ ] The **three** consuming dialogs — `AddMembersDialog`, `TableShareDialog`, `SendFilesDialog` —
      and their tests are unchanged. (Three, not two: `SendFilesDialog` joined at SPEC-165 and is
      missed by any inventory written before it.)
- [ ] No new field, wrapper, or error subclass is introduced between `apiRequest` and a service. A
      service converts an `ApiFailure` to its own `ServiceResult` failure and adds nothing.

### FR-010: CORS — one header added, and two things this spec must not narrow

#### Description:

SPEC-193 ships the CORS block this spec builds on, and it already ships it in the shape the bearer
design needs: `allow_credentials = false` (there is no cookie and so no credentialed-CORS requirement,
and no CSRF surface to go with it), and `allow_origins = [spa_origin, var.app_url]` — **both** origins,
deliberately, for the arc's duration.

So this spec's CORS work is one additive header. The rest of this FR is written as guards, because the
two tempting edits here are both regressions: narrowing the origin list orphans the CloudFront rollback
that every live check between here and SPEC-202 depends on, and neither failure is visible to `curl`
from the surviving origin.

#### Acceptance Criteria:

- [ ] **`allow_origins` is left exactly as SPEC-193 shipped it — both origins.** This spec removes
      neither. `var.app_url` (the CloudFront domain) is what makes the CloudFront bundle a working
      rollback while the container is being proved, which is the whole point of SPEC-193 FR-006's
      additive change; dropping it here would leave five specs with a rollback that cannot reach the
      API. **SPEC-202 narrows the list to `spa_origin` alone**, as the last thing that happens in the
      arc, and both specs state that same end state. A test asserts this spec's diff removes no entry
      from the list.
- [ ] **`allow_credentials` stays `false`** — SPEC-193 ships it that way, so there is nothing here to
      amend and no superseded marker to write. The criterion is a reintroduction guard: a test asserts
      the value is still `false`, and the client's explicit `credentials: 'omit'` (FR-007) is the
      browser half of the same decision.
- [ ] **`allow_headers` gains `x-request-id`** — the one CORS change this spec makes, because FR-007
      mints that header and SPEC-193's list carries only `content-type` and `authorization`. A missing
      entry fails the **preflight**, so the request never reaches the API and the browser reports a
      generic network error — the CORS failure mode named in FR-007, which is why this is asserted on
      the configured list and then observed on a live `OPTIONS`, not inferred from the app working.
- [ ] `allow_methods` covers every method in the contract. A test reads the configured list back from
      the Terraform that declares it (`infra/modules/api/`) and asserts it is a superset of
      `{r.method for r in ROUTES}` — the read-back technique SPEC-166 already uses, rather than two
      hand-kept lists.
- [ ] `max_age` is set (600 s). Every API request carries `Authorization`, so **every** request is
      preflighted; the cache duration is a latency decision, not a nicety.
- [ ] The negative control: a preflight carrying a **foreign** `Origin` returns **no**
      `access-control-allow-origin` header. A `"*"` configuration passes the positive check and fails
      only this one.
- [ ] No handler emits an `Access-Control-Allow-*` header (SPEC-193 Premise 4). Two sources produce
      two headers, the browser rejects the response, and `curl` looks fine. A sweep over
      `lambdas/api/` asserts the string appears nowhere.

### FR-011: Observability, correlation, and the field rule for a token-handling service

#### Description:

One span per request through `cpcommon.observability` — the only door (SPEC-127) — landing in
`logs/service=api/` beside the seven control planes, with `env` and `version` populated (SPEC-186
FR-005). The field rule binds here more sharply than anywhere else in the fleet: **user metadata in,
file contents out, tokens and emails always out**, and this service holds a bearer token on every
single request.

#### Acceptance Criteria:

- [ ] The entry point is wrapped in `@observability.traced(...)` with `observability.init(service="api")`,
      and the route travels as a **stamped field** (`route_id`), not as the span name — `traced` names
      the span at decoration time and there is exactly one entry point, so a per-route span name is not
      available and a field is what a `WHERE` clause wants anyway.
- [ ] Each request stamps `route_id`, `method`, `status`, `code` (on failure), `duration_ms` and
      `actor` (the verified username — user metadata, allowed).
- [ ] **The correlation id is the API Gateway request id, taken from `requestContext.requestId`, and
      the router stamps it explicitly.** `cpcommon.observability._extract_request_id` reads a top-level
      `requestId` and then falls back to parsing `body` as JSON — and an API Gateway v2 event's `body`
      **is** a JSON string, which for SPEC-167's submit shape carries a browser-supplied `requestId`.
      Left implicit, this service's correlation key would be an untrusted value chosen by the caller.
      A test posts a body containing `{"requestId": "spoofed"}` and asserts no emitted record carries
      `spoofed` as the correlation field. This assertion can fail today and would have failed a naive
      implementation.
- [ ] The client-supplied `x-request-id` is recorded separately as `client_request_id`, **validated
      against a UUID pattern** and recorded as `null` when it does not match. It is never used to build
      a key, a path or a dedup token — it is a log field the caller controls.
- [ ] `requestId` in the error envelope (FR-003) is the API Gateway id, so a user quoting it finds the
      right record.
- [ ] **The bearer never reaches a handler.** The router verifies and discards it before dispatch
      (Premise 6). A sweep asserts no module under `lambdas/api/routes/` names `authorization`,
      `Authorization`, `bearer` or `id_token`.
- [ ] A test issues a request whose bearer is a distinctive literal, forces a failure inside the
      handler, and asserts that string appears in **no** emitted record — including `error.stack`,
      which `log-foundry` attaches to every failed span and which SPEC-195 owns the treatment of. This
      spec inherits that treatment and asserts it at the transport layer; it does not re-decide it.
- [ ] **The directory's `usernames` array is never logged.** It is the contents of an S3 object, which
      the field rule puts out of bounds; the span carries `username_count` instead. The obvious wrong
      implementation is a helper that stamps the response body, and it would look like good telemetry.
- [ ] No email address is emitted by any field, on any path.

### FR-012: `GET /v1/user-directory`

#### Description:

The first ported route. One `GetObject`, no write, and the forgiving semantics of SPEC-147 preserved
exactly — moved from TypeScript into Python, not re-decided.

#### Acceptance Criteria:

- [ ] `GET /v1/user-directory` returns 200 with `{usernames: string[], generatedAt: string | null}`.
      The wire shape carries no `version` and no `count`: the document's shape is the server's business
      now.
- [ ] The route reads `_directory/usernames.json` from the user-space bucket **through the user
      plane** (`ROUTE_PLANES['userDirectory.get'] == 'user'`, SPEC-196), so the portal role's existing
      `ReadTheUsernameDirectory` grant is what authorizes it and **no IAM changes**. A test asserts the
      plane, and a test asserts this spec adds no statement to `portal-role-permissions.json.tftpl`.
- [ ] The forgiving path moves intact: a **missing** object, an unparseable body, an unsupported
      `version`, and a non-array `usernames` each return **200** with `{usernames: [], generatedAt:
      null}` — never a 404 and never a 5xx. This deliberately inverts the usual S3-404 → API-404
      mapping, and the reason is SPEC-147 FR-005: an unavailable suggestion list means no suggestions,
      not an error banner. An unsupported version emits an `observability.warning` naming the version
      it saw and the one it supports (the `console.warn` moved, not deleted).
- [ ] Every entry is re-checked against the catalog-safe rule server-side, and `generatedAt` is
      dropped to `null` when it is not a string.
- [ ] A real fault maps through SPEC-196 FR-007: `AccessDenied` → 403, an assume-role or downstream
      failure → 500/503. The client collapses all of them to `'unavailable'`, exactly as today.
- [ ] **No server-side cache.** One `GetObject` per request; the SPA's one-hour `staleTime` is
      unchanged, so request volume is unchanged.
- [ ] The response size is **computed, not assumed**: `MAX_INDEXED_USERNAMES` (20,000) names at the
      63-character catalog maximum, JSON-encoded, is ~1.3 MB — inside Lambda's 6 MB synchronous
      response payload with more than 4× headroom, and inside API Gateway's 10 MB. The route therefore
      does **not** truncate: truncating server-side would silence the client's existing cap warning,
      which is the only signal that the directory has outgrown the index.
- [ ] `Cache-Control: no-store` (FR-002), even though the document is identical for every user — the
      rule is per-API, not per-route, and a per-route exception is how the next route gets it wrong.

### FR-013: The ported client, and every assertion accounted for

#### Description:

`userDirectory.service.ts` keeps its name, its signature and its docstring's promise; its innards go
from `readJsonDocument` + `getS3Client` + `userSpaceBucket()` to one `apiRequest`. The measure of a
good port is that no assertion is quietly lost on the way, so each of the ten existing
`userDirectory.service` assertions is *kept*, *moved to `lambdas/api/test_user_directory_route.py`
with its reasoning carried over*, or *kept on both sides* — and the disposition is written down,
because "we moved the tests" is exactly the claim nobody can check a year later.

| Existing assertion | Disposition |
|---|---|
| reads the key SPEC-146 publishes, from the user-space bucket | **moved** to Python |
| reads the bucket name at call time, not module load | **moved**; replaced in kind on the client by *reads the API base URL at call time* |
| missing document → empty state | **both** (Python: S3 404 → 200 empty; TS: 200 empty → empty success) |
| corrupt document → empty state | **moved** |
| unsupported version, and names it | **moved** (as an `observability.warning`) |
| non-array `usernames` → empty | **moved** |
| re-checks every entry against the catalog-safe rule | **both** — the API is now a second producer, and a producer guarantee is still not a runtime guarantee |
| a real fault is a failure | **kept** (a 503 envelope → `{success: false}`) |
| never throws | **kept**, extended to a non-envelope gateway body |
| drops a non-string `generatedAt` | **both** |

#### Acceptance Criteria:

- [ ] `getUserDirectory()` issues **exactly one** `apiRequest` for route `userDirectory.get` and no
      other network call; it imports nothing from `@aws-sdk/*`, `lib/s3Client`, `lib/s3Json` or
      `lib/userSpace`.
- [ ] **No assertion in the existing suite is deleted**, and the table above is honoured row by row.
      The delivery doc reproduces it: it is the artefact the next five ports copy.
- [ ] Two new client assertions: the route id is the one in the generated table (a typo cannot compile,
      but a wrong-but-valid id can), and a `SessionExpired` failure carries `code: 'SessionExpired'`
      so the hook's `'unavailable'` collapse still holds.
- [ ] `UserDirectoryDocument` (the S3 document's TypeScript shape) is **deleted** from
      `userDirectory.types.ts` and the barrel — the browser no longer sees the document — and the
      component-inventory row is updated in the same change. `UserDirectory`, `UserDirectoryStatus`,
      `UsernameSearchResult`, `UsernameIndex` and `SuggestionSource` are unchanged.
- [ ] `npm run test:coverage` still meets the portal floors (91/86/89/93) and `pytest lambdas/` the 95
      floor. A port moves logic across languages, so it must move coverage with it; a floor met by
      deleting the tests that moved would pass on one side and sink the other.

### FR-014: Both scaffolds come down, and what that costs

#### Description:

The arc has **two** temporary probe routes, not one, and both are deleted here: SPEC-195's
`GET /_auth/whoami` (the boundary's only route, built because nothing was ported yet) and SPEC-196's
`GET /_identity/self`. They come down together, on the same condition, because they are the same kind
of thing and a scaffold with no named owner survives the arc — SPEC-195 originally assigned its
deletion to SPEC-202's final sweep, which is six specs of an unauthenticated-username probe living in
production for no reason.

SPEC-196 Premise 2 says the scaffold is removed here "when the ported user-directory route makes the
same proof against a real feature". **The first half is right and the second half is not**, and saying
so is part of this spec.

#### Acceptance Criteria:

- [ ] `GET /_identity/self` and `lambdas/api/routes/identity_self.py` are deleted. A repo grep for
      `_identity/self` returns nothing, and FR-006's set-equality guard is what would have caught a
      handler left behind.
- [ ] `GET /_auth/whoami` and `lambdas/api/routes/whoami.py` are deleted, with their tests. A repo
      grep for `_auth/whoami` returns nothing. Both probes leave FR-001's route table with **no**
      unversioned path but `GET /healthz`, which is what that criterion's exact-match exclusion then
      asserts against a real absence rather than vacuously.
- [ ] Each deletion happens **only after the live verification that route existed for has been run and
      recorded** — SPEC-196 Phase 5 for `_identity/self`, SPEC-195 Phase 5 for `_auth/whoami`. Those
      are where the isolation proof and the boundary proof are made; this spec removes the scaffolds,
      it does not repeat either proof. A delivery-doc line names the two dates.
- [ ] **`GET /v1/user-directory` cannot demonstrate isolation and does not claim to.** The
      `ReadTheUsernameDirectory` statement is unconditioned — no `${aws:PrincipalTag/username}` — and
      the document is identical for every caller, so a route that returns the same bytes to everyone
      can never show that a principal tag was applied. What it *does* prove live is the plane: an
      assumed-role credential reaching S3 through the API at all. **The isolation proof passes to
      SPEC-198's first per-user route**, and is recorded as owed in the Verification phase and in
      `ARCS.md` rather than quietly assumed discharged.
- [ ] The negative control this route *can* carry: a request with an absent, expired or wrong-issuer
      bearer returns 401 and makes **zero** AWS calls — no `AssumeRole`, no `GetObject` — asserted by
      call count, because a 401 issued *after* a successful downstream read looks identical from the
      outside.

---

## Data Model

### The wire

```jsonc
// 200 — the payload itself, always a JSON object, never wrapped.
{"usernames": ["alice", "bob_smith"], "generatedAt": "2026-08-05T04:00:11Z"}

// 200 — a paged route (no route in this spec is paged; the shape is fixed here for SPEC-198).
{"items": [/* … */], "nextToken": "<opaque continuation token>" }

// Any failure — the only wrapped shape in the API.
{"error": {"code": "AccessDenied", "requestId": "Nq3rPFyGoAMEJfQ=", "detail": "portal role denied s3:GetObject"}}
```

### Python — the single declaration

```python
# lambdas/api/apicommon/contract.py

ErrorCode = Literal[
    "InvalidRequest", "SessionExpired", "AccessDenied", "NotFound", "Conflict",
    "PayloadTooLarge", "UnsupportedMediaType", "RateLimited",
    "IdentityUnavailable", "InternalError", "ApiUnavailable",
]

ERROR_STATUS: Final[dict[ErrorCode, int]] = {...}   # total; image ⊆ FR-001's status set

class UserDirectoryResponse(TypedDict):
    usernames: list[str]
    generatedAt: str | None

@dataclass(frozen=True)
class Route:
    id: str                       # "userDirectory.get" — the id every call site names
    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str                     # "/v1/user-directory"
    idempotent: bool              # declared, NEVER derived from the method (FR-008)
    plane: Literal["user", "api"] # SPEC-196's ROUTE_PLANES key
    request: type | None
    response: type

ROUTES: Final[tuple[Route, ...]] = (
    Route("userDirectory.get", "GET", "/v1/user-directory", True, "user", None, UserDirectoryResponse),
)
```

### TypeScript — generated, never edited

```ts
// apps/portal/src/types/apiContract.generated.ts
// GENERATED by scripts/generate_api_contract.py — do not edit.

export type UserDirectoryResponse = {usernames: string[]; generatedAt: string | null};

export const API_ERROR_CODES = ['InvalidRequest', 'SessionExpired' /* … */] as const;
export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

export const API_ROUTES = {
  'userDirectory.get': {method: 'GET', path: '/v1/user-directory', idempotent: true}
} as const;

export type ApiRouteId = keyof typeof API_ROUTES;
export type ResponseOf<R extends ApiRouteId> = /* … */;
export type RequestOf<R extends ApiRouteId> = /* … */;
```

## API / Interface Contract

```ts
// apps/portal/src/lib/apiClient.ts

export type ApiClientCode = 'RequestTimeout' | 'NetworkUnavailable'; // client-minted; never on the wire

export function apiRequest<R extends ApiRouteId>(
  route: R,
  opts?: {body?: RequestOf<R>; query?: Record<string, string>; signal?: AbortSignal}
): Promise<ServiceResult<ResponseOf<R>>>;

export function apiRetryPolicy(route: ApiRouteId): false | number;

export function setAuthTokenProvider(provider: () => Promise<string | null>): void;   // SPEC-195
export function setUnauthenticatedHandler(handler: () => void): void;                 // SPEC-195

// The service boundary is UNCHANGED — same signature, same type, same promise.
export async function getUserDirectory(): Promise<ServiceResult<UserDirectory>>;
```

## Environment Variables

No new `VITE_*`. `apiBaseUrl` moves from `OPTIONAL_CONFIG` to `REQUIRED_CONFIG` in
`lib/runtimeConfig.ts` (SPEC-192 anticipated this); its deploy wiring is already in place and is
checked by SPEC-192's key-set agreement tests.

The API Lambda gains one required variable, on SPEC-196's convention — no default, raises at first
read:

```
USER_SPACE_BUCKET=<the user-space bucket name>   # var.user_space_bucket_name
```

## File & Folder Structure

```
lambdas/api/
├── apicommon/
│   ├── contract.py                       # NEW — ROUTES, ErrorCode, ERROR_STATUS, validate_request
│   └── envelope.py                       # NEW — success/error serialisation, the status map
├── router.py                             # extended — dispatch from ROUTES, correlation, plane hook
├── routes/
│   ├── identity_self.py                  # DELETED (FR-014)
│   ├── whoami.py                         # DELETED (FR-014)
│   └── user_directory.py                 # NEW
├── test_contract_generation.py           # NEW — determinism, the closed vocabulary, the raise
├── test_envelope_and_statuses.py         # NEW — FR-001/002/003
├── test_router_registry.py               # NEW — FR-006's two set-equality guards
├── test_api_observability.py             # NEW — FR-011, incl. the spoofed-requestId case
└── test_user_directory_route.py          # NEW — the moved assertions

scripts/
└── generate_api_contract.py              # NEW

apps/portal/src/
├── lib/
│   ├── apiClient.ts                      # NEW
│   ├── apiClient.test.ts                 # NEW
│   └── errorMessages.ts                  # + API code rules, + exported PASSTHROUGH_CODES
├── types/
│   └── apiContract.generated.ts          # NEW — generated
└── features/user-directory/
    ├── userDirectory.service.ts          # rewritten innards, unchanged signature
    ├── userDirectory.types.ts            # − UserDirectoryDocument
    └── userDirectory.test.ts             # service block rewritten; trie block untouched
```

## Implementation Phases

### Phase 1: The contract, the generator and the gates

- `contract.py`: `Route`, `ROUTES`, `ErrorCode`, `ERROR_STATUS`, the shared type walker.
- `generate_api_contract.py`, the closed vocabulary, the deterministic emitter, `.prettierignore`.
- `validate_request` over the same walker; the determinism and unsupported-type tests.
- The `ci.yml` regeneration-diff step.

### Phase 2: The transport half of the router

- `envelope.py`; the closed status set; the 404-for-unregistered rule; the outermost `InternalError`
  mapping and the raw-AWS-text assertion.
- Dispatch from `ROUTES`; FR-006's two set-equality guards, each verified by a violation in both
  directions.
- FR-011: correlation stamping (including the spoofed-`requestId` test), the field rule, the
  `routes/` sweep, the `error.stack` inheritance assertion.
- FR-010's one added header, the `allow_methods` read-back, and the guards on the origin list and
  `allow_credentials`.

### Phase 3: The API client and the wording boundary

- `apiClient.ts`: route-id call shape, call-time base URL, injected token provider and 401 handler,
  `credentials: 'omit'`, the 30 s abort, the non-envelope status mapping.
- `apiRetryPolicy` and the `?raw` retry sweep; the zero-retry tests.
- `errorMessages.ts`: the API code rules, `PASSTHROUGH_CODES`, and FR-004's disjointness and
  set-equality guards, verified by adding a passthrough code and watching it fail.
- `renderWithProviders` seeds `apiBaseUrl`.

### Phase 4: The ported feature, and the scaffold down

- `routes/user_directory.py` and the moved assertions, with the forgiving path intact.
- `userDirectory.service.ts` rewritten; the disposition table honoured; `UserDirectoryDocument`
  deleted; `useUserDirectory.test.ts` confirmed unchanged byte for byte.
- Delete `identity_self.py` and `whoami.py` — each after its own spec's Phase 5 verification is
  recorded — and their route rows.

### Phase 5: Verification

Written as a new section of `docs/testing/arc-b-api-container-e2e.md`. What nothing offline can
prove:
that the `cpcommon` layer attaches at **cold start** (SPEC-137 shipped instrumented code whose
attachment was missing while every offline gate passed), that a real browser's preflight is satisfied
by the deployed CORS block, and that an assumed-role credential minted inside a Lambda actually reaches
S3 against the deployed portal role.

- **Sign in fresh, signed out to start.** A signed-in pass never tests the token path.
- Open a dialog that suggests usernames — **`AddMembersDialog`, `TableShareDialog` and
  `SendFilesDialog`** — and confirm suggestions render. In the network panel: **one** request to
  `GET {api_origin}/v1/user-directory`, status 200, `access-control-allow-origin` **exactly** the SPA
  origin, `cache-control: no-store`, and a preflight preceding it. Rendered suggestions are the only
  proof the whole path worked; a `200` with an empty array looks identical to a healthy but empty
  directory, so **assert on the rendered names**, from a fixture you know is in the document.
- `curl` with **no** `Authorization` → 401, envelope-shaped, `code: SessionExpired`, a `requestId`
  present. Repeat with an expired token and with a token from another issuer: all three 401.
- `curl -H 'Origin: https://example.invalid'` on the preflight → **no** `access-control-allow-origin`.
  This is the assertion a `"*"` configuration fails and the positive one passes.
- `curl -X POST {api_origin}/v1/nope -d '{"requestId":"spoofed"}'` → **404**, envelope-shaped; then
  read the record in `logs/service=api/` and confirm the correlation field is the API Gateway id and
  **not** `spoofed`.
- `curl -X POST {api_origin}/v1/user-directory` (registered path, unregistered method) → **404**, not
  405.
- Read one record back from `logs/service=api/…/data.jsonl`: `env: "prod"`, `version` equal to the
  build sha and neither empty nor `0.0.0`, `route_id`, `status`, `actor`; and **absent**: any bearer
  substring, any email, the `usernames` array. Records arrive on the 10-minute log sweep — wait for it
  rather than concluding from an empty query.
- Confirm the **first** invocation after a deploy succeeds (cold start, layer attachment).
- **Safari** at desktop, since that is the browser in use; a Chromium pass corroborates and cannot
  discharge (record it as such).
- **Recorded as OWED, not discharged:** the isolation proof (FR-014 — this route's grant is
  unconditioned and its bytes are identical for every user), and a live 403 on this plane, which
  cannot be staged for a bucket-wide grant. Both pass to SPEC-198's first per-user route.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row; the delivery doc — carrying FR-013's disposition table,
  which is the artefact the next five ports copy.
- `decisions/` entries, then **one line each** in CLAUDE.md's Key Decisions: (1) the error shape —
  a machine code plus operator text nobody renders, and the passthrough disjointness guard that keeps
  SPEC-106 from being reversed through one of its own rules; (2) the contract is declared in Python
  and the TypeScript is **generated**, with the two CI gates and the closed type vocabulary that
  refuses to emit `any`; (3) `apiRequest` retries nothing and idempotency is declared per route, with
  the `retry: 1`/`StartQueryExecution` incident as the reason it is a rule rather than a habit.
- A **superseded marker** on the arc entry in `ARCS.md` where it still says `credentials: 'include'`.
  Nothing in SPEC-193 needs one: it already ships `allow_credentials = false` and both origins.
- Component-inventory rows: `foundations.md` for `lib/apiClient.ts`; `shared-types.md` for
  `apiContract.generated.ts`; `user-directory-feature.md`'s `getUserDirectory` row rewritten and its
  `UserDirectoryDocument` entry removed.
- The `ARCS.md` arc entry updated with what this spec found — including the isolation proof passing to
  SPEC-198, so a later reader does not read SPEC-196 Premise 2 as discharged.
- Help sweep: **nothing user-facing changes.** The same three dialogs suggest the same names with the
  same wording, and no error text moves. Record that explicitly and skip.
