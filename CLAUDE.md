# S3 File Portal — Project Memory

Loaded every session — keep it lean. **Start by reading `@docs/process.md`** (step 1 of the Session
Workflow below). Everything else is pulled **on demand**: the cross-cutting docs live in `docs/`, and
the domain rulebooks and inventories live beside the code they govern, in each tree's `info/` folder:
- `@docs/process.md` — **read at the start of every session, before any other doc**: how we work —
  spec lifecycle, session rhythm, the reviewer contract, the completion ritual, doc hygiene
- `@docs/architecture.md` — **how the system works**: the pieces, how a request travels between them,
  and the **Architecture Decision Record** indexing the decisions that shaped it. Short enough to read
  whole, and the cheapest way into a part of the system you haven't touched. It carries no rules and
  no trap lists — those live beside the code
- `@docs/decisions/INDEX.md` — **router** to the Key Decisions register, one file per area; open the
  area file, then the entry (the digest below groups by the same areas)
- `@docs/specs/INDEX.md` — the spec index + status (one row per spec)
- `@docs/specs/ARCS.md` — why an arc exists / how its specs compose (only for the arc you're in)
- `@docs/specs/SPEC-XXX-*.md` — the spec you're implementing
- `@apps/portal/info/component-inventory/INDEX.md` — **router** to the per-area inventories; read only the area(s) you need
- `@docs/spec-delivery/SPEC-XXX-*.md` — what a past spec delivered (pull only when a dependency points to one)
- `@docs/testing/e2e.md` — **the** end-to-end validation guide; `owed.md` is what it can't settle, `sessions.md` what has been run
- `@docs/best-practices/INDEX.md` — **cross-domain router** to the coding rulebooks, which live beside
  the code they govern: `apps/portal/info/best-practices/` (React, accessibility) and
  `lambdas/info/best-practices/` (Lambda shape, Python style). Route here, then load only the section(s) you need
- `@docs/transition_plan.md` — **single source of truth** for the client-environment transition (Entra ID sign-in in **two variants** — §3.3 — IdC propagation, one credential plane with S3 Access Grants, de-provisioning, LF re-keying, ODBC/JDBC driver migration); read before touching auth, provisioning or LF
- `@lambdas/info/INDEX.md` — every Lambda, grouped by control plane, with a page per plane
- `@infra/info/INDEX.md` — every Terraform module, and the README beside each one carrying its
  reasoning; `control-plane-shape.md` is the shape all seven planes share, and
  `deploy-role-iam.md` is the trap list for adding a new resource type
- `@lambdas/info/deployment.md` — the Lambda code/infra split and its deploy-time traps
- `@apps/portal/info/runtime-configuration.md` — the `/config.json` contract and its six wiring sites
- `@lambdas/info/shared-layer.md` — the long-form *why* behind `cpcommon` (sizing evidence, rejected designs, the traps); a plane's own reasoning is on its page under `lambdas/info/planes/`. Read the one entry for the area you're changing, never in full

**Context discipline:** these are pointers, not a reading list. Pull a doc when a task needs it.

---

## Project Overview

A web portal where authenticated users upload/download files to/from their own S3 prefix.
Auth is AWS Cognito (standalone User Pool + Identity Pool). Arc B has moved the object surface, the
catalog and the eight control-plane queues behind an API (`api.dataquarry.app`); what the browser
still calls directly is **presigned S3 bytes** and Cognito through Amplify. Status: greenfield, no
production users yet.

## Monorepo (npm workspaces)

- `apps/portal/` — React SPA (**all app code lives here**; paths below are relative to it)
- `infra/` — OpenTofu IaC (**all IaC paths relative to here**); bounded-context modules under `infra/modules/`
- `packages/` — reserved, currently empty
- `docs/` — architecture, specs, spec-delivery, templates

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 19 + Vite, TypeScript (strict), TailwindCSS; `focus-trap-react` (focus trapping for Modal/Drawer) |
| AWS | `aws-amplify` v6 for Cognito, and nothing else. **No `@aws-sdk/*` package may be added** — an ESLint `no-restricted-imports` clause forbids the import (tests included) and a test over `package.json` forbids the dependency; objects, bytes, the catalog and the eight queues go through the API |
| Editor | `@monaco-editor/react` + `monaco-editor` (self-hosted workers; lazy-loaded on the Query route only, SPEC-035) |
| Routing / state | `react-router` v8 (**not** `react-router-dom` — that package is gone in v8; import everything from `react-router`); TanStack Query (server state) + Context/`useReducer` (UI state); no Redux |
| Testing / lint | Vitest + React Testing Library + `@testing-library/user-event`; `@vitest/coverage-v8` (`npm run test:coverage`); `vitest-axe` (axe-core a11y assertions, SPEC-045); ESLint + Prettier. Tests are **integration-style** — **import only the component under test**, render real hooks/children, mock only the service boundary (`*.service.ts` / `lib/apiClient`); **1–3 scenarios each** (4–5 where earned; a dozen means the unit is scoped wrong), **arrange/act/assert**, happy path and failure path first; shared harness `src/test/renderWithProviders.tsx`. Rules: `apps/portal/info/best-practices/react/react.md` §21, `lambdas/info/best-practices/lambdas/lambdas.md` §11 |
| IaC | OpenTofu (HCL, S3 remote state) |
| Security | `eslint-plugin-security` + `eslint-plugin-no-unsanitized` (in `npm run lint`, **blocking**); Semgrep / `pip-audit` / gitleaks / Checkov **block** in `security.yml`; `npm audit` and the OWASP ZAP baseline **report** (SPEC-138 — the modes are the `GATE_*` block at the top of the workflow). Every scanner version-pinned — see the VERSIONS block and #311 |

Don't add dependencies without noting them here first.

## Code Conventions (apps/portal/)

- TS strict; no `any` (use `unknown` + narrow). Named exports only (default only for page-level route components). Async/await only. Never swallow errors.
- Naming: `PascalCase.tsx` components, `useCamelCase.ts` hooks, `camelCase.ts` utils, `camelCase.types.ts` types.
- Features in `src/features/<name>/`: `index.ts` barrel, `Component.tsx` (+ co-located `.test.tsx`), `useFeature.ts`, `feature.types.ts`, `feature.service.ts`.
- AWS SDK: v3 modular only; instantiate clients in `src/lib/` (never in components); all S3 ops go through service files.
- Services never throw — return `ServiceResult<T>` (`{success:true,data} | {success:false,error:{message,code?}}`).
- Vite env vars: prefix `VITE_`; document each in `apps/portal/.env.example`.
- **A comment names no spec, PR or issue number** — not `SPEC-166`, not `(#252)`, not "since SPEC-158". A reader is standing in the file, not in the project's history: write the reason ("a third copy would fork the lookup"), not the citation. Full entries live in `@docs/decisions/INDEX.md`, findable by what they say. Applies to `.ts`/`.tsx`/`.py`/`.tf`/`.tftpl`; enforced by `scripts/validate_docs.py`.
- **No verbose comments in `.ts`/`.tsx`/`.py` files.** JSDoc (TS/React) and docstrings (Python) are the primary source of context — expand those over adding narrative inline comments; comments are reserved for the non-obvious *why*, kept short. Detail: `apps/portal/info/best-practices/react/react.md` §19, `lambdas/info/best-practices/python/python.md` §14.
- **`lambdas/` carries NO inline comments at all** (only `# noqa` / `# type: ignore` directives). Every module, class, method and function — public or `_private` — has a Google-style docstring: a one-line summary of what it does *and its context*, an optional short *why* paragraph, then `Args:` / `Returns:` / `Raises:`, each written out with `None.` when the section is empty. A module's constants are documented in its docstring's `Attributes:` block. Anything longer than a paragraph of reasoning goes beside the code in `@lambdas/info/` — `shared-layer.md` for `cpcommon`, the plane's own page otherwise — not in the file. Format: `lambdas/info/best-practices/python/python.md` §14.
- When writing/refactoring code in a domain with a rulebook (React, accessibility, …), consult `@docs/best-practices/INDEX.md` first and load only the relevant section(s) — don't reinvent or guess the rules.

## Common Commands

```bash
npm run dev|build|test|lint -w apps/portal   # from repo root (or omit -w inside apps/portal/)
npm run format|format:check -w apps/portal   # Prettier (prettier.config.js); format:check gates CI before tests
tofu -chdir=infra validate|plan|apply        # init: tofu -chdir=infra init -backend-config=backend.conf
python3 scripts/watch_ci.py --pr <n>         # watch CI for ONE sha; exit 0 only if settled AND green
python3 scripts/watch_ci.py --branch main    # after a merge; --once for a single poll
```

## Specs

Status lives in `@docs/specs/INDEX.md`, narrative in `ARCS.md`, what shipped in
`@docs/spec-delivery/`, live checks in `@docs/testing/`. **This section carries only what is live and
recorded nowhere else** — when a spec closes, prune here rather than appending.

### Current work

- **API layer & containerisation (192 → 202, 192–201 done)** — "Arc B"; narrative in `ARCS.md`,
  what ran in `sessions.md`, what did not in `owed.md`. CloudFront is still production and the
  rollback. **Only 202 is left**, and two things it must not miss: it **re-points SPEC-206's
  `SenderId` boundary**, which still names the portal role it retires (`UNTRUSTED_SENDER_ID` empty
  refuses *every* notification `create`), and until it lands the browser still calls
  `cognito-identity`, so arc-b §4's "no AWS calls" negative does not pass.


## Key Decisions (settled — don't re-litigate)

**Grouped by area, not by spec.** Each block is the settled shape, then the fences and the traps —
the things that **apply green and fail later**, which is the failure mode this project keeps paying
for. **Full reasoning, and every "do NOT build" in its long form: `@docs/decisions/INDEX.md`**, findable by
what it says rather than by number. Read the entry for an area before working in it.

### Identity, access and the name that ties them together

Cognito User Pool → Identity Pool, ABAC. The `username` principal tag is stamped **server-side from
the verified claim**, so it cannot be spoofed; one shared role, isolation by
`${aws:PrincipalTag/username}`; a SHARED space is that tag **∩** a per-space role-level LF grant,
so retiring the tag alone unions every space. Hosted UI is **Managed Login v2** — the classic one broke the
post-signup redirect. The API verifies the browser's bearer and assumes that same role for it.

- **The API VERIFIES a bearer, and is not an OIDC client.** No cookie → no CSRF surface; CORS still
  required. Provider-agnosticism is **five config fields**, the JWKS URL built once at the **root**.
  **A key-retrieval fault is 5xx, never 401.** Refusals are byte-identical; **expiry is not
  disclosed**, because the browser refreshes once on any 401.
- **The API assumes the SAME role with the SAME tags from the SAME claims** — one computation over
  one input, which is why no policy is rewritten. The claim names are the only thing copied from
  `identity-pool.tf`. The role
  is **reused, never minted**: `aws:PrincipalArn` resolves to the *role's* ARN, so the
  hand-maintained bucket-policy allowlist stays correct. `DurationSeconds` 3600 is a ceiling **both
  ways** — shorter caps every presigned link, longer is refused because this is role chaining.
  Tag-key agreement is **asserted, not structural** (the templates hard-code the literal), and the
  trust statement's `sts:TagKeys` is a **ceiling that cannot require a tag was stamped**.
- **Two credential planes, user by default, declared ON THE ROUTE — the failure fails OPEN.** A wrong
  client *succeeds* against the wrong identity. One construction site (asserted as a **count**), an
  AST sweep that also forbids `cpcommon.clients` and any minted `UserIdentity`, exemptions by
  **exact module path**. The plane is a **required field on the contract's `Route`**, derived per
  call — so the old registry's set-equality guard is now a tautology, kept as a labelled tripwire,
  and the teeth are the required field plus a **raise on a plane value that is neither of the two**. The route is set on the way **IN**: a warm container has no fresh context,
  so cleanup-on-exit alone lets the next request inherit a declaration. **An assume failure is a
  FAULT, never a denial** — STS says `AccessDenied` for a wrong trust policy, so the layer *wraps*
  it; that wrap, not the classifier's ordering, is what holds.
- **The credential cache is keyed on the WHOLE tag set** — never the username alone, which freezes
  membership until the next cold start, and never nothing, which serves B the session of A. Its
  margin is the life of **one request**, derived from the function timeout; the forced re-assume is
  the skew allowance, and it retries on a **new** client because boto3 binds credentials at
  construction. **A presigned URL is not a request** and takes `signing_client(covering=…)`, which
  forces a fresh session rather than clamping against a near-dead one — otherwise the window is a
  draw from the hour. A short window is *correctly clamped*, so no clamp test can see it.

- **The API's error shape is a machine CODE plus operator text nobody renders** — the error envelope
  is the only wrapped shape and wording is chosen client-side from the code. The trap is a rule
  written to uphold it: eight `passthrough` rules
  return the service's message unchanged, so a guard intersects the generated `API_ERROR_CODES` with
  a computed `PASSTHROUGH_CODES` — **two derived sets, never two lists**. An unrecognised code
  resolves to the generic sentence: the deploy-skew case, not a fallback nobody meets. **A code rule
  wins over an engine-message match rule.**
- **The wire is declared in PYTHON and the TypeScript is GENERATED**, with two gates: CI refuses a
  regeneration diff (catching both drift directions) and `tsc -b` fails at every call site on a
  changed type. The validator and the emitter read **one** walk of one annotation. The type
  vocabulary is **closed and never falls back**: a fallback type agrees with every value, so the day
  the emitter meets a shape it cannot express is the day the contract stops being checked.
- **`apiRequest` retries NOTHING**, asserted as a call count, with exactly one exception: a 401 takes
  one forced refresh and one retry — the browser's only refresh path, so deleting it signs everyone
  out at the hour mark with a green suite. Idempotency is declared **per route**, never derived from
  the method. The client's timeout sits **above the function's**, so an abort always means a dead
  connection.
- **The API makes exactly ONE AWS call per request and never waits** — every poll and page walk stays
  in the browser, because a 5-minute query is 10× a **non-raisable** 30-second integration ceiling
  (the *function* timeout is the 29 — the two are easy to conflate and a past spec did).
  The count is on the **route's own service client**, never on botocore: the session cache fires
  `AssumeRole` on some invocations and not others, so "one botocore call" is unsatisfiable cold and
  satisfiable warm. SPEC-198's free-name route is the arc's one exception. A route may carry **path
  parameters**, and a value that is not **one segment** is refused in the browser: either spelling
  reaches a **sibling route that answers 200 with the wrong shape**. A missing one is a **compile
  error**, deliberately — as an optional field it ships the literal placeholder to the service.
- **`$default` matches OPTIONS**, so API Gateway's own CORS responder never sees a preflight and the
  router must answer one **before authentication**. Found live, and `curl` cannot see it because only
  a browser enforces CORS: every bearer-carrying `fetch` failed as an opaque `TypeError` reading as
  "the API is down". That the gateway overlays its CORS headers onto the integration's own `OPTIONS`
  200 is read from AWS's docs; if it is wrong the degraded path is **silent by design**.

- **The tag VALUES have two sources, chosen at COLD START, no fallback** — `MEMBERSHIP_SOURCE`,
  default `claims`, in no Terraform. The other is `memberships/{username}.json`, **admin** bucket:
  an authorization input, unlike the username directory, safe only because it is
  **user-unreachable, plane-written, CAS-written**. The user's own `shared-connections.json` is the
  same shape and **user-writable** — reading it is a bypass. Absence needs a
  **`s3:prefix`-conditioned `ListBucket`** or it reads as denial.

**One string is four things:** username = S3 prefix = principal tag = Glue database name, so it is
catalog-safe by construction (`^[a-z][a-z0-9_]{2,62}$`). The username directory is built from **S3,
not Cognito** — today Cognito is complete and S3 is not, and the client transition reverses exactly
that. It is readable by every authenticated user, accepted deliberately: usernames only, never
emails.

- **A feature flag is presentation, never authorization** — and the flag document lives beside the
  username directory in the **user-space** bucket, not the admin one: the admin bucket was specced
  first, and its grant would not have worked. Gating is by **registry**, not
  per-component opt-in, and one test walks every gated surface in **both** states.
- **No shared-space directory is published** — the share dialog suggests only spaces you belong to.
  A full list would be more useful and is declined as a disclosure with no equivalent.
- **A presigned URL is a BEARER TOKEN** — minted only after exactly the authorization the direct call
  would have had, signed by the **caller's own assumed session**, and in **no emitted record** (the
  span carries the key's *length*). Its lifetime is clamped to the **credential that signed**, read
  in the same call — never to `DurationSeconds`, which agrees today and will not under Access
  Grants, and never by assuming a second time (the cache refuses a near-dead session and hands back
  a fresh hour while the near-dead one signed the URL).
- **The dev-unauth path is RETIRED** — it worked by calling S3 unsigned from the browser, and no
  unsigned call is left. `s3Client.ts`, `s3Errors.ts` and five `VITE_*` variables went with it; the
  `VITE_` allowlist is now `lib/env.ts` alone. Local dev points the SPA at an API.
- **A document that belongs to no user has no space, so it gets its OWN route** — `_config/` and
  `_directory/` are not prefixes any caller's claims authorize, and leaving one on the object
  surface makes every read a 403 that falls back to defaults, which looks exactly like health.

### Storage, and the fact S3 is not a filesystem

The product presents filesystem UX over a store with **no move or rename**: every one is
`CopyObject` + `DeleteObject`, folder operations are recursive and **non-atomic**, and collisions
warn and confirm. Versioning is off, which is what makes a failure between those two steps
unrecoverable — revisit before real user data lands.

- **A received file lands in `shared_files/{sender}/`, built by ONE function** — an AST sweep forbids
  a second. Keying by item **name** forces the two refusals an overlapping selection needs.
- **Exclusion rules anchor at the listing prefix**, which is whichever item the user picked — reuse
  elsewhere silently drops files.
- **A duplicate is `(kind, key)`, never the key alone.** One key can arrive as both a file and a
  folder; collapsing on the key ships a zero-byte placeholder and reports success.
- **Saved queries are ordinary `.sql` files** in a visible folder with exactly one protection: the
  folder itself is undeletable. Every `DO_NOT_DELETE.txt` is hidden by **basename**.
- **An unreadable settings document is quarantined, never deleted and never overwritten**, and a
  **newer** schema is refused untouched — the parse is three-way, version checked before shape.
- **Bytes go to S3 presigned; small text goes through the API**, and the document route's **byte cap
  is what holds the line** — without it it is a second upload path that works perfectly to 6 MB. The
  routes never parse and never re-serialise. An upload is one `PUT` over **`XMLHttpRequest`**, which
  is a requirement, not a preference: `fetch` fires no upload-progress event, so it uploads
  correctly and leaves the bar at 0% — assert an **intermediate** value. The 5 GiB ceiling does not
  move (it is the single-`PUT` cap, and `maxUploadBytes()` clamps to it); **part-level retry is
  gone**; the URL is minted **per file**, inside `uploadFile`, never per batch.
- **The four folder-recursive browser functions are DELETED, not ported** — that loop belongs on the
  plane. So `asyncFileOperations` off means folder operations are **unavailable**, refused **per
  item** while the files beside them go through; and the refusal is also reachable with the flag ON,
  when a destination resolves to no known space.
- **The free-name probe moved to the API, not to the plane** — 999 round trips would be strictly
  worse than the loop it replaced. `numberedName` lives in Python only, and **exhaustion is now
  distinguishable from failure** (409 + `attempts`), which it was not.

### Control planes — one pattern, seven planes, and the traps are shared

Shared spaces, table builder, table share, data quality, file send, **archive** and file
operations each get:
a **FIFO SQS** queue → EventBridge Pipe → Step Functions → single-task verb Lambdas, **one execution
role per plane**, its own DLQ, and a `cpcommon` layer plus a domain layer. A plane sharing another's
DLQ lets one malformed request dead-letter someone else's work.

**The traps, every one of which ships green:**

- **No ASL state may decode an error `Cause`.** `States.StringToJson($.error.Cause)` raises
  `States.Runtime`, which is **uncatchable anywhere**. Carry raw `$.error`; decode with
  `cpcommon.errors.failure_reason`, the only decoder.
- **Every plane notifies on a pre-verb failure** — a `NotifyFailure` before `Fail`, reached on every
  path, because the no-verb-ran paths cannot be selected for in ASL.
- **A post-identity failure needs its own seed.** A catch routed to a state reading `$.raw` raises an
  uncatchable error *before* the notifier, because `$.raw` exists on no post-validate state.
- **Everything unbounded travels by pointer**, never on the state, and **a cap is not a substitute**.
- **Every cap is COMPUTED by a test**, against the budget that sized it — memory, makespan, or a
  service quota — and it names that budget. A hard-coded number hides a wrong model.
- **`TimeoutSeconds` is TOP-LEVEL and cannot notify on its own**: catchers do not cover top-level
  execution failures, so a ceiling ships **with** an EventBridge `TIMED_OUT` rule (never `FAILED`, or
  every caught failure double-notifies).
- **An expected refusal is a RETURN VALUE**; only unpredicted faults raise. A `TerminalError` cannot
  name the colliding item, and the user needs it named.
- **ONE producer says every per-recipient outcome**, at the end of the machine — not each verb.
- **Locks are objects claimed under ETag CAS**, released by **overwriting**: with `DeleteObject`
  denied, "free" is a state rather than an absence. The holder is the **execution ARN**, because a
  request id identifies the message and Pipes delivery is at-least-once.
- **A partial teardown never frees the name.** `delete_objects` returns **HTTP 200 with a per-item
  `Errors` array**, so a partial failure reads as success; raise, and leave the registry record —
  the record *is* the name lock.
- **A shared-space delete removes PEOPLE, not things**, keyed on the durable `everActive` — never
  live `status`, which moves `active → deleting → failed` over intact data, and where `deleting` is
  **not** evidence a space was usable (delete is gated on ownership alone). **One predicate**,
  `is_destroyable`, routes the delete AND refuses the add; complements written twice drift silently
  both ways. Inert because the `owner` **field** is cleared — so test it **as the original owner**.
  A name is never reusable.
- **The planes do not verify — they read the API's `identity` block**, trusted because only the API
  may write these queues (`.tftpl` sweep). Dropping a verification is NOT dropping an authorization:
  `authorize`/`authorize_source` have **zero diff**. `cpcommon.actor` **cannot verify** (no `jwt`,
  `auth`, network or env — import sweep), and the flat `actor` is **never** read: it carried a raw
  JWT, and a JWT and a username are both non-empty, so the guard is the **shape rule**.
  `assurance` fails closed on an unknown value **including an absent one**. Do **NOT** add a queue resource policy — notifications has eight writers and a blanket
  `Deny` silences seven notifying roles, invisibly. A pre-cutover message is `unauthorized` and
  does **not** dead-letter (`FIRE_AND_FORGET`), so plane allowed-field sets stay untightened.
- **The DLQ drain** sweeps all request DLQs on a schedule and notifies from **`identity.actor`**;
  its redaction blanks the two LEGACY token fields, since a stale message still carries one. The
  notifications DLQ stays undrained: circular.
- **File operations are synchronous IFF exactly one file**; the lock is per **space** and its loser
  **waits** (cross-space takes both in digest order or neither); the **space root is refused** as an
  item; the collision unit is the derived destination **key**, and a **403 counts as occupied**; the
  deletion takes **confirmed plan keys** — a prefix listing orphans an uncopied object.
- **The browser's async switchover consults the routing predicate ONCE**, above every submission
  point, in one dispatcher. The in-flight record is **session-scoped, never persisted**, and settles
  on a notification carrying its request id.
- **Table share CLONES the source definition, never re-infers it**, and pushes without consent.
- **A data-quality notification IS the completion channel** and must carry the report link, because
  the reports folder is hidden. Its runs index is appended under **ETag CAS** — S3 lists
  lexicographically, so a UUID key gives no chronology.
- **Every member sees the roster**; the join acknowledgement is display-only, since access is granted
  at add time.
- **The notifications `create` boundary is a RUNTIME check**, because no SQS condition key reaches a
  message body. It compares the **role-id half** of the `SenderId`, and a refusal **logs and drops,
  never raises** — dead-lettering per forged request would drown the one undrained DLQ. The actor
  reader replaces the `USER_ACTIONS` arm **only**: `create` is the trusted producer (body username,
  no actor, no token), and hoisting the reader above that branch refuses **every notification the
  fleet produces**, silently.
- **`cpcommon` owns the algorithm; a domain layer owns its wording.** Do **NOT** merge the domain
  layers wholesale. Where a layer is packaged by an explicit file list, a test asserts **set
  equality** with the directory — completing a flag map closes nothing.
- **A notification's optional `link` is gated by `isSafeInAppPath`**, and a route that renders one
  must not become an existence oracle: the data-quality report view takes its space **from the route,
  never derived**, and an unreachable space renders denied while issuing **no S3 request at all**.
- **Structured logging** goes through `cpcommon.observability` only; the logs queue is FIFO, swept on
  a schedule, appended under ETag CAS, retained forever. `@traced` outermost — **except the API**, where one decorator sits
  outside it to turn an unpredicted fault into a declared code: a catch INSIDE the span ends every
  failed request successfully and the fault is recorded nowhere. Messages are literals.
  The **`error.stack` exemption covers file contents, NOT credentials**, and it covers **no field a
  call site chooses to emit** — neither a **SQL statement** nor an Athena **`stateChangeReason`** may
  be one, since both quote a user's own cell values back; `sql_bytes` and `state` instead. The API
  **prevents rather than redacts**: there is no scrubber, a handler is never given a credential, and
  an AST sweep is what holds it.

### Analytics, the catalog, and two SQL dialects

An in-app Athena/Glue/Lake Formation workspace. Isolation is the `username` principal tag on the
Glue database ARN — **not** LF-Tags. Table creation is **TBAC**: LF admin does **not** grant
`CREATE_TABLE`; a `portal-managed` LF-Tag plus one tag-policy grant per execution role does.

- **The query workspace has NO active database.** Every base table is fully qualified
  `database.table`; the rail is browse-only. A space maps to exactly one database, so the picker has
  no database step.
- **Every DDL literal goes through `literal()`** — `TBLPROPERTIES` and `LOCATION` included — and
  the escapers split on **two axes that are easy to conflate**. *Values:* `ddl.literal`
  backslash-escapes (Hive/DDL), `sql._literal_dml` and the browser's `sqlLiteral` double the quote
  (Trino/DML). *Identifiers:* `sqlIdentifier` (Trino, `CREATE VIEW`), `sqlDdlIdentifier` and
  `ddl.quote` (Hive, `DROP`, inner backtick doubled — data-quality partition keys come from S3 folder
  names). **The wrong one fails SILENTLY, as a predicate that never matches**, and it matters because
  a shared space's name is format-checked **nowhere** server-side. A quoting fix is not done until
  every statement built from the same value is swept.
- **A column name is user data.** Creates refuse empty, non-`[a-z0-9_]`, over-255 and fold-collision
  names; a refresh does not, or it strands pre-rule tables.
- **A table's `LOCATION` is read recursively**, so the space root is not a data folder.
- **Results are read only at `SUCCEEDED`.** A too-early `GetQueryResults` reached users as a generic
  "contact the administrator"; the API now answers **409 `QueryNotFinished`**, classified by Athena's
  **message** — the same `InvalidRequestException` is a malformed query at submit, and a name-keyed
  mapper passes any test exercising one at a time. The client gate is **kept**, and asserts on the
  **CALL**: with the 409 in place the screen looks right either way.
- **A failed query is a 200.** `stateChangeReason` rides the body byte-identical and the browser
  picks the sentence; enveloping it retires six authored ones at a stroke. Lake Formation denies in
  **two shapes** — a Glue 403, and an execution that reaches FAILED on a 200 — and a 403 is **never**
  a re-login. `dataScannedBytes` is `null` while non-terminal, never `0`. The generic sentence is
  reserved for what a user **cannot** act on, held by a computed `USER_FIXABLE_CODES`.
- **A refresh is judged by SHAPE, not by a marker** — never by the `portal.managed` property it also
  writes, which pre-existing tables lack and users can set. Removing a column needs an opt-in, and
  **the refusal is the warning**. The apply is a read-modify-write on the live table, serialized by a
  per-table lock whose loser is **refused with a notification**, never queued.
- **Multi-statement scripts** split client-side on `;`, run sequentially, stop on first failure. No
  transactions.

### Archive and restore — the only place a mistake is unrecoverable

A separate `GLACIER` vault the browser has no relationship with. A restore is `RestoreObject` + a
3–5 hour wait + a copy.

- **The restore guard is ABSOLUTE and runs before the bill:** any occupied destination refuses the
  **whole** restore, and a **403 counts as occupied**.
- **It runs TWICE**, and the second pass is the spec correcting itself: those billed hours are spent
  telling the user a restore is in flight, so re-creating a file meanwhile is the ordinary case — and
  the copy-back would have overwritten it, reported success and swept the vault.
- **Retrieval is the point of no return.** Its Map tolerates **no** failure (the copy's tolerates
  100%): a fault means nothing copied and the archive untouched. What makes that free is that the
  **verb** tolerates two codes — `RestoreAlreadyInProgress` and `InvalidObjectState` — which is also
  what keeps the path unconditional on the storage class. **Do not "harden" the verb by removing
  them.**
- **The source is deleted only when EVERY object is confirmed copied**, and the gate is a **state** —
  the rollback arm cannot reach `DeleteSource`, asserted by walking the ASL graph, and an
  unrecognisable verdict fails closed.

### The browser

TanStack Query for server state, Context + `useReducer` for UI state, no Redux. Mobile-first, with
only `tablet:` (≥900) and `desktop:` (≥1300) compiled; one tree reflows — a `*Mobile`/`*Desktop` twin
is a smell.

- **Raw AWS/Cognito/Athena text is NEVER shown.** `lib/errorMessages.ts` is the single source of
  wording; never render `error.message`.
- **`components/` may not import from `features/`** — enforced by lint. A leaf feature that becomes a
  shared layer gets **extracted before its second consumer**, not after.
- **Dialogs:** Enter submits from **one** field, not implicitly; Escape dispatches by **tree depth**
  through one registry, and a busy modal swallows it. `cx()` returns `undefined`, never `''` — `??`
  does not fall back on the empty string, and that cost nine dialogs their width.
- **The one irreversible surface refuses the affordance that would fire it.** The archive dialog is
  built on the confirm dialog *because* the form dialog has Enter-to-submit — focus sits on Cancel,
  Enter cancels — and it never says "this can't be undone", which would be its one false sentence.
- **A palette is measured, not chosen.** Contrast is recomputed across the cross product; a colour
  that fails is measured **out**.
- **Client state is computed in the browser; billed work is not.** A selection aggregate issues
  **zero** executions, and says which page it counted.
- **A display page is not a listing page.** A pager over filtered rows keeps fetching while the
  listing is truncated — and **stops on error**, because a failed fetch leaves "has more" true, which
  is the fill's own trigger: without the guard one failure spins forever.
- **Help & guides document only what is shipped and wired end to end.**
- **Column geometry is keyed by NAME**, so geometry for a column the result no longer has is
  discarded by construction.

### Infrastructure, IAM and delivery

OpenTofu, bounded-context modules under `infra/modules/`, IAM policies as `.tftpl` rendered by
`templatefile()`. Notifications are a **single-writer** FIFO queue → writer Lambda; the browser only
only reads; the API enqueues on its behalf.

- **Deploy-role IAM is in-scope work for any spec that provisions new infra**, and **grants land in
  their own PR before the resources that need them** — every grants-only PR in Arc B applied green
  first run. That is the whole claim: it does **not** prevent a red main, which this arc hit three
  times afterwards on things no grant review would have found.
- **Scopability is MEASURED, never assumed.** `simulate-custom-policy` gives an
  `implicitDeny`/`allowed` pair before the policy is written. Actions with no resource type sit alone
  in a wildcard statement. **A simulate matches PATTERNS, not the ARN the service passes** — it
  cannot tell you that a service calls something on your behalf, or that a condition key goes
  unpopulated, which are the two traps that cost this project an apply each. Contradicting intuition: `ec2:DescribeVpcAttribute` and
  `route53:GetChange` **are** scopable; `ecs:DescribeTaskDefinition` is not, and scoping it is the
  refresh deadlock arriving by your own hand.
- **A service may call an action on your behalf that appears in no action list** — ELB calls
  `ec2:GetSecurityGroupsForVpc` inside `CreateLoadBalancer`.
- **A role that cannot LIST a bucket cannot be told an object is ABSENT** — S3 answers `NoSuchKey`
  only to a caller holding `s3:ListBucket`, so every `except NoSuchKey: return None` needs a
  covering grant or its absence branch fails as a fault. Found live: an unregistered space raised
  `AccessDenied` out of `cpcommon.registry.load` instead of refusing. **A CONDITIONED grant is
  sufficient — having no statement is what breaks**, and the simulate misleads here, returning
  `implicitDeny` with no `s3:prefix` supplied because it answers what IAM decides given your
  context, never what the service supplies. So scope the condition to the keys read; do **not**
  widen to an unconditioned admin-bucket list (that discloses every space name, then every
  roster), and do **not** read `AccessDenied` as absence, which makes a real denial look like a
  fresh request. The population is swept from the AST, never listed.
- **A condition on a key the caller does not populate fails CLOSED**, and the refusal names neither.
- **The deploy role can lock itself out**: tighten or widen one of its own grants and plan, apply and
  **revert** all fail alike. `Deploy Infrastructure` takes `skip_refresh` to break it — always follow
  with a normal run. A green plan is not proof; IAM is eventually consistent.
- **A module-level `depends_on` defers every data source in that module** — benign for a policy
  document, a hard error where the value feeds a `for_each`.
- **`COGNITO_USER_POOL_ID` is no longer fleet-wide** — a lazy `config.require` on the three planes
  resolving a recipient, so a missing one raises **mid-request**, not at cold start.
- **An empty `TF_VAR_` is not an unset one.** It satisfies a required variable *and* overrides a
  default; an unset repo variable renders as exactly that. Guard with `validation`, not with the
  absence of a default.
- **The container platform (193):** no NAT gateway anywhere — private subnets reach AWS through
  endpoints alone, the residual is a **connect timeout** (hence flow logs), and a successful pull
  proves nothing unless read beside `describe-route-tables`. The API function is **not** in the VPC
  and authorization lives in the **router**, both asserted as absences. The image
  tag is the commit sha (`IMMUTABLE` ECR, no `:latest`), `task_definition` is ignored while
  `desired_count` is not — so **CI must point the service**, and a pipeline that only registers a
  revision leaves a `CannotPullContainerError` **indistinguishable from the endpoint failure the
  platform is tested for**. A Fargate task volume arrives empty and root-owned and does **not**
  initialise from the image: writable paths are `linuxParameters.tmpfs`, one uid feeding both `user`
  and every mount option.
- **The SPA image reproduces every CloudFront job; three are DIVERGENCES** — `Server: nginx`, no
  brotli, no HSTS `preload`. **`add_header` is inherited only by a level defining none of its own**
  (hence one snippet per location, `always` throughout, and a server-level floor for errors raised
  before a location resolves); assert on **responses**, never config text; `/healthz` is
  exact-match, or a probe falls through and a broken container reads healthy.
- **Configuration is a RUNTIME document** (`/config.json`, `no-store`, refused whole on version)
  with **no production fallback**. Its key set is wired in six places, asserted across all, and the
  container **refuses to start** on a required one unset or empty. The API's **verifier** config is
  server-side, never in the browser's document — and the exclusion cuts one way: a rule forbidding
  "anything identity-shaped" takes Amplify's own Cognito keys with it.
- **Origins are admitted ADDITIVELY**, narrowed only at the cutover — an allowlist naming one
  origin makes the other a rollback nobody can exercise.
- **CSP `connect-src` IS the app's network surface** — enumerate it from the hosts the app fetches,
  not the AWS services it uses. The omitted Hosted UI domain broke fresh sign-in for a day. **Both
  CSP locals live at ROOT** — a root check cannot read a module local. The container takes
  `connect-src` from the task definition and bakes the rest; **nginx has no escaping**, so anything
  interpolated in is allowlisted — a quote truncates the policy on a container reporting healthy.
- **Static assets deploy in three prefix-scoped passes** — `--exclude` protects keys from
  `--delete`, so a pass excluding a prefix can never reconcile it. **S3 path only:** the image IS
  the file set — no reconciliation, no orphan class, an honest 404 under `/assets/`.

### Gates, scanners and tests

- **A gate blocks on a NARROWED count, never a total.** Checkov enforces check IDs measured at
  **zero** — enforcing what passes rather than suppressing what does not — and the plan scan
  accepts by check ID **and** resource. **A line matching no finding is a hard error.**
- **"Did not run" is never "clean."** A broken scanner fails the job even in report mode, and
  `--quiet` must never come back: without `passed_checks` the gate cannot tell a pass from a check
  that never ran.
- **A new finding is scoped, not accepted.** Every shipped scanner failure carries a written
  disposition; the enforce list is regenerated by **any** spec adding a resource family.
- **A refusal is the half of the system no user exercises**, and a coverage number is blind to it:
  a `raise` is one line, so deleting its test barely moves the percentage while the happy path —
  which runs on every dev run and every real action — keeps the function covered. Assert the
  **reason code by name**, never that "something raised". The check is mechanical: enumerate the
  codes raised against the codes asserted. A review samples this; a sweep counts it.
- **Mutation-test the guard whose failure would be SILENT** — not every assertion. This project
  ships assertions that pass while the thing they name is false, so one targeted break-and-revert
  when the guard is written is worth it. A **sweep** of every guard afterwards is not: it costs a
  full suite run each and finds what writing the test carefully already would. The cheaper habit
  that catches the same class: assert the **reason** — the message, the named item — never just an
  exit code or a count, since the neighbouring path usually returns the same code.
- **`ACCEPTED_` tripwires record what has NOT been verified**: pin today's behaviour, name the
  reasoning, and say *revisit the decision, don't delete the test*.
- **No silent caps.** If a check bounds coverage, say what was dropped — silent truncation reads as
  "covered everything".
- Coverage floors and `"strict": true` are **declared, never inherited**. The floors are a flat
  **85**, no longer ratchets at the measured level — a ratchet fails CI on any deliberate reduction
  in test volume, and is bought back by testing internals. Never lower one for a regression, and
  never read a floor as evidence a guard exists: four mutations of production code once passed the
  whole suite with coverage unchanged. **Mutate the guard instead.**

---

## Out of Scope (don't build)

No **second** API (one HTTP API, one `$default` route — a feature does not get its own service) ·
no **new** browser-side AWS SDK call on a path an API route already serves · no in-browser file
preview · no admin UI · no second **user-space** bucket
(several buckets exist — shared-space, admin, artifacts, static; the constraint is one bucket of
personal prefixes).

---

## Session Workflow

**Start:** (1) this file, then **`@docs/process.md` — read it every session, not once**: it is the contract this file only summarises; (2) the spec you're implementing (`@docs/specs/SPEC-XXX`); (3) for context, pull **only** what the spec touches — the matching `apps/portal/info/component-inventory/` area file(s), the `decisions/<area>.md` entry, a dependency's delivery doc; read architecture.md whole if the spec touches a part of the system you don't already hold. Never read the inventory or delivery docs in full. (4) Confirm `gh run list --branch main --limit 5` is green (esp. Deploy Infrastructure / Lambdas / App); investigate failures before building. (5) Branch from fresh `main` (`git fetch && git switch -c <branch> origin/main`). (6) Generate an implementation plan from the spec's phases, validate it against the spec (FRs + acceptance criteria covered, reuse used, nothing out of scope), **send it to a fresh-context reviewer**, then build. (7) Send the **PR grouping** to a reviewer too, before the first push — as few PRs as the dependencies allow.

**During:** those two reviews are the only gates on *starting* — **build straight through to completion**, summarizing a phase in passing but never ending the turn on it (a summary that ends the turn *is* a request for approval). Specs carry no Open Questions — triage emergent issues by kind: **reversible/technical** ones you decide in-session (update the spec if scope changes); **product-changing or ambiguous** ones you stop and escalate to the human with options + a recommendation, never silently decide.

**Review — three artifacts, one blocking gate:** a **spec** (1), an implementation **plan** (1) and a **diff** (2) each go to a reviewer in a **fresh context** (new session or subagent), never the context that produced them. A spec is not Draft-ready, a plan does not start code, and **a branch does not reach the remote**, until every finding is either **fixed** or **flagged** — a rejection costs a sentence out loud, and only goes in writing when it carries a lesson worth keeping. The diff's two framed reviews gate the PUSH, not the merge. Cap same-frame rounds at two, then rotate; exit on a new frame finding nothing — never below two on a diff. Check against the spec's acceptance criteria, not just "looks fine." Full contract: `@docs/process.md` §3 → *The reviewer contract*.

**Spec size — one slice, not a whole feature:** aim **3–6 FRs**; past **8**, write a second spec beside the first and record the pair's build order in `@docs/specs/ARCS.md` rather than growing one. The second restarts at FR-001 (IDs are spec-local). Cut on a seam the system already has — a plane, a surface, a switchover — never at the FR where the count ran out. `validate_docs.py` **ratchets the number of over-size specs**, so a new one fails CI; a genuinely indivisible spec is paid for by raising `SPEC_OVERSIZE_MAX` by one and arguing it under *Scope → In Scope*, not by cutting at FR-009 — and **splitting one lowers that constant in the same PR**, or the ratchet goes slack and the next over-size spec passes silently. Full rule: `@docs/process.md` §4.

**PRs & main:** before pushing, get the diff through the review gate above, and get the formatter, linter, unit tests **and `npm run build`**
green locally — `build` (`tsc -b`) is the only one that typechecks, and `tsc -p tsconfig.json`
silently checks nothing. CI now runs it too (#363). Watch every PR to completion and merge it as soon as CI is green — never open-and-abandon. `main` is always watched: after any merge confirm it went green, and if `main` fails, diagnose immediately and fix it with a new PR before anything else. **Watch with `scripts/watch_ci.py`, never a hand-rolled loop** — it keys on one sha and its exit condition is tested, which two hand-written watches were not.

**Infra rule:** any spec that provisions new infra must expand the deploy role's IAM (`.tftpl` under `infra/modules/base/policies/`) as in-scope work — not an afterthought, and it lands in its own PR before the resources that need it. Adding a *new resource type* trips recurring IAM/propagation traps (self-grant timing, non-scopable actions, refresh deadlocks, unknown-ARN-in-list) — read `@infra/info/deploy-role-iam.md` first, and `@lambdas/info/deployment.md` before adding or rewiring a Lambda.

**On spec completion — keep the always-loaded files lean:** run §5's ritual in `@docs/process.md` in one pass — status header, `@docs/specs/INDEX.md` row (status only), a **short** delivery doc from the template, a one-line inventory row **if** something reusable landed (in the `apps/portal/info/component-inventory/<area>.md` matching the component's **path**), the full entry in `@docs/decisions/<area>.md` **before** its one-line Key Decisions digest **if** the spec settled a new *architectural* decision (a per-feature choice is a register entry and nothing more), an `architecture.md` ADR row **only** if the system's shape changed, a prune of `## Specs` → Current work, live checks folded into `@docs/testing/e2e.md` (never a per-spec file), and a user-facing Help & guides sweep. **A digest line is never the only home of a fact**; **add a clause or replace one your decision supersedes**, never a line per spec. A superseding decision has three other dispositions: update the old **register** entry in place, and put an in-place superseded marker at every **other** doc site still stating the old claim (`ARCS.md` arcs, `architecture.md` sections). A check that cannot run from a signed-in session becomes a row in `@docs/testing/owed.md`.

**Doc-size guardrail:** `CLAUDE.md` is the always-loaded file — if an edit pushes a section past a
few lines, the detail belongs in a `docs/` file behind a pointer. Same for `INDEX.md` (status rows
only) and the inventory router. **Key Decisions is grouped by AREA and carries fences, not history** — it is not a
per-spec changelog, and `## Specs` is not one either; both regrew past 300 lines once by being
appended to.
**`scripts/validate_docs.py` enforces this on every PR** — the budgets are
ratchets at the measured level, so raise the doc's tier, never the cap. Full rule set:
`@docs/process.md` §5 → *Anti-regrowth & doc hygiene*.
