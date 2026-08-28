# Spec: Runtime Configuration & the Provider Block

**ID:** SPEC-192
**Status:** Completed
**Last Updated:** 2026-08-24
**Depends On:** SPEC-162 (`VITE_ENVIRONMENT`, and the "an unusable document falls back silently, which is why the live check reads a 200 rather than a screen" reasoning this spec inverts), SPEC-141 (the static-asset cache passes a fourth pass now joins, and the 404→`/index.html`→**200** mapping that makes a missing document look like a served one), SPEC-140 (the response-header surface SPEC-194 inherits), SPEC-106 (`toUserMessage` is the only source of user-facing wording, including at boot), SPEC-153/186 (the `?raw` sweep technique the key-set agreement tests use)

## Overview

Every `VITE_*` variable is inlined into the bundle by Vite at build time. That was correct while the
artifact was a per-environment `dist/` synced to S3, and it is fatal once the artifact is a container
image: an image carries one environment's bucket names, queue URLs and Cognito ids everywhere it is
promoted, so `dev → prod` is a rebuild rather than a tag repoint, and a rollback is a rebuild of an
older commit rather than a repoint back.

This spec makes the SPA read its configuration at **runtime**, from a same-origin `/config.json`
rendered at container start from ECS task-definition environment variables. It ships nothing a user
can see. What it ships is the precondition for every other spec in the arc: one image, promotable,
plus the classification that says which values the browser still needs when the arc is finished and
which move server-side as each porting spec lands. The browser's document shrinking from nineteen
keys to ten is the arc's own progress bar.

It also fixes the boundary the arc's identity layer needs before anything is built on it: the OIDC
provider block. **This arc does not change how anyone signs in** — Cognito, Managed Login v2 and
Amplify in the browser all stay, and the browser keeps the four Cognito values Amplify needs for the
whole arc. What the provider block configures is the *other* side: the API's **token verifier** — the
issuer it trusts, the audience it demands and the JWKS it fetches keys from. That is
**server-side configuration for the API Lambda, and is not part of the browser's document at all**,
because a verifier's trust anchors are the server's and the browser has no use for them. It is
provider-agnostic so the later target-environment arc swaps the *provider* rather than rewriting the
*verifier*. An issuer, an audience or a JWKS URI appearing in `/config.json` is a defect, and this
spec makes that a test rather than a convention — one carefully written so it does not also forbid
the Cognito values Amplify legitimately reads.

## Scope

### In Scope

- `lib/runtimeConfig.ts`: the fetched document, its type, its version gate, the call-time accessor,
  and the `REQUIRED` / `OPTIONAL` classification carried over from `lib/env.ts`.
- The **dev fallback** to `import.meta.env`, reachable only in a dev build, and unreachable — by
  dead-code elimination, asserted on the built output — in a production build.
- The **production boot failure**: a missing, unreachable, unparseable or incomplete document is a
  named hard failure with a fixed user-facing message, never a silent `undefined`.
- The **async bootstrap** in `main.tsx`: fetch config → configure Amplify → render.
- Porting every genuine production config read (the measured inventory below) onto the accessor.
- The **OIDC provider block** — the API's token-verifier configuration: its field set, its home (the
  API Lambda's environment), and the test asserting the browser document contains none of it while
  still carrying the four Cognito values Amplify reads.
- Deploy wiring for every key, and the key-set agreement tests that make an unwired key fail in CI
  rather than in production. Includes closing the live gap: `VITE_ARCHIVE_QUEUE_URL` is wired in
  `.env.example` and in `deploy-app.yml` but is **absent from `lib/env.ts`'s classification**, so
  nothing catches it unset today.
- **Serving the document from the existing static site**, so the production app keeps working
  between this spec and SPEC-194 — see FR-008. This is the sequencing decision the arc brief did not
  make, and without it this spec breaks production the day it merges.

### Out of Scope

- **The nginx configuration and the container entrypoint that renders `/config.json` from the task
  environment — SPEC-194.** This spec owns the document's *shape*, the accessor, the fallback, the
  classification and the `no-store` requirement; SPEC-194 owns the server that satisfies them. The
  boundary is the document: anything about how bytes reach the browser after the ALB is SPEC-194's.
- Creating any infrastructure — no VPC, ALB, ECR, ECS, API Gateway or DynamoDB — **SPEC-193**. No
  deploy-role IAM expansion is needed here, because this spec adds no AWS resource type.
- Anything about how a user signs in. **Amplify keeps running in the browser for the whole arc** —
  `lib/amplify.ts` is reshaped here (FR-005) and deleted by nobody in this arc. The bootstrap this
  spec builds outlives Amplify anyway: the API base URL must be known before the first fetch, so the
  fetch-then-render shape is load-bearing whether or not Amplify is on the other side of it.
- Porting any route, moving any AWS call behind the API, or adding an API client — SPEC-197 onward.
- Retiring the dev-unauth path (`VITE_S3_DEV_UNAUTH`, `VITE_S3_BUCKET_NAME`, `VITE_S3_ROOT_PREFIX`,
  `VITE_AWS_ACCESS_KEY_ID`, `VITE_AWS_SECRET_ACCESS_KEY`) — **SPEC-198**. Those five stay on
  `import.meta.env`, behind their existing `import.meta.env.DEV` guards, untouched by this spec.
- `import.meta.env.DEV` itself. It is a build-mode flag, not configuration, and every one of its
  eleven code sites stays exactly as it is.
- Removing any key from the document. This spec **adds** the mechanism and moves every existing
  variable onto it; each later spec deletes its own entry.

> **CORRECTED AT IMPLEMENTATION (2026-08-24).** The inventory below was measured before Arc A's last
> merges and is stale in five places. `VITE_ARCHIVE_QUEUE_URL` is **already** in `lib/env.ts`, so
> FR-008's "this test fails today" no longer holds — the agreement test ships green and keeps the gap
> closed. `VITE_FILE_OPS_QUEUE_URL` has landed, making the document **20** keys, not nineteen (it
> joins group (b), so the end-of-arc figure of ten is unchanged). There are **eight** enqueue services
> and **10** `notConfiguredMessage` paths, not seven of each; **three** ternary bucket picks, not two;
> and **25** moving code lines, not 23. A sixth `import.meta.env.VITE_*` site existed outside FR-006
> AC1's five files — a JSDoc `@example` in `lib/enqueueFifo.ts` — updated rather than exempted.
> Details in `spec-delivery/SPEC-192`.

### What is read today, and what replaces it — measured, not grepped

`grep -c import.meta.env` over `apps/portal/src` returns 86. That number is worthless and every
prior estimate of it in `transition_plan.md` §4.6 is low. The real figure, measured 2026-08-18:

| Cut | Count |
|---|---|
| All occurrences, `src/**` | 86 |
| …excluding `*.test.*` | 79 occurrences on **73 lines** across **26 files** |
| …minus the 19 comment lines (most explaining the call-time-read rule) | 54 code lines |
| …minus 11 `import.meta.env.DEV` lines, and 3 dev-only reads not on a `DEV` line | −14 |
| Genuine production config reads | 40 code lines across 18 files |
| …minus `lib/env.ts`'s own 17-entry `readEnv()` table, which this spec **keeps** as the dev fallback | −17 |
| **Reads that actually move onto the accessor — what FR-006 ports** | **23 code lines across 17 files** |

The 23 that move break down as: `lib/amplify.ts` (5), the `queueUrl:` reads inside **seven** enqueue
services (9 lines — `archive` and `table-builder` read theirs twice), the two ternary bucket picks in
`archive.service.ts:31` and `fileSend.service.ts:26` (2 lines, 4 reads), five `region:` reads across
`s3Client`/`athenaClient`/`glueClient`/`sqsClient`, `athena.service.ts:56`'s `WorkGroup`, and
`fileBrowser.types.ts:67`'s upload cap. The remaining 17 are `readEnv()`'s literal member expressions,
which stay exactly as they are: after this spec that table **is** the dev fallback, and its literals are
load-bearing for the reason its own docstring gives — a computed index emits the whole env object into
the bundle.

**Most of the convention already exists**, which is why this is mostly mechanical. `lib/env.ts`'s own
docstring states the rule — *EVERY READ IS AT CALL TIME, never at module load* — and `lib/userSpace.ts`
and the seven `queueUrl:` reads already obey it. Those call sites change their **source**, not their
shape.

**Three sites do not obey it, and its docstring names only one of them.** Measured 2026-08-18:

| Module-load site | What it reads | Mechanism it gets |
|---|---|---|
| `lib/amplify.ts` (5 reads) | the four Cognito values + the Identity Pool id, at import, so `Amplify.configure()` runs before anything renders | becomes `configureAmplify()`, called by the bootstrap **after** the load resolves (FR-005) |
| `lib/s3Client.ts`'s exported `s3Client` const | `region: import.meta.env.VITE_AWS_REGION` in a `new S3Client({…})` evaluated at import | becomes a call-time builder (FR-006); its two dev-unauth credential reads stay on `import.meta.env` behind their `DEV` guard |
| `fileBrowser.types.ts`'s `MAX_UPLOAD_BYTES` const | `Number(import.meta.env.VITE_MAX_UPLOAD_BYTES)` at module scope | becomes `maxUploadBytes()` (FR-006), with its four production call sites moved |

This matters more than a tidiness point, and it is the architecturally interesting part of the spec.
`configValue` throws before the document is in hand (FR-002 AC3), and `main.tsx`'s static import graph
is evaluated **before its first statement runs** — so a production build with any module-load read left
in that graph throws before it renders. That is why FR-005's bootstrap reaches the app through a
**dynamic import**, and why these three sites are converted as well: the dynamic import keeps the graph
out of the pre-load window, and the accessors keep the call-time rule uniform so a future static import
of one of them is not a boot failure waiting to happen.

### The classification — the spine of the rest of the arc

Every value is a **string**. The ECS task environment is strings, and a JSON number would introduce a
second parse path with a different failure mode for one key (`maxUploadBytes`, already `Number()`-parsed
at its call site). `version` is the sole exception.

**(a) What the browser still needs when the arc is finished — ten keys:**

| Key | From | Class | Note |
|---|---|---|---|
| `apiBaseUrl` | *new* | optional → **required in SPEC-197** | Nothing reads it in this spec. Optional now so a build predating SPEC-193's API does not hard-fail. |
| `appUrl` | `VITE_APP_URL` | required | Amplify's `redirectSignIn` / `redirectSignOut`. |
| `environment` | `VITE_ENVIRONMENT` | optional | SPEC-162's flag document block. Degraded path is total and silent — the reason FR-004's hard failure excludes it. |
| `maxUploadBytes` | `VITE_MAX_UPLOAD_BYTES` | optional | |
| `cognitoUserPoolId` | `VITE_COGNITO_USER_POOL_ID` | required | Amplify. |
| `cognitoUserPoolClientId` | `VITE_COGNITO_USER_POOL_CLIENT_ID` | required | Amplify. |
| `cognitoDomain` | `VITE_COGNITO_DOMAIN` | required | The Hosted UI host. Amplify. |
| `awsRegion` | `VITE_AWS_REGION` | required | Removed by nobody in this arc — see below. |
| `userSpaceBucket` | `VITE_S3_USER_SPACE_BUCKET` | required | As above. |
| `sharedSpaceBucket` | `VITE_S3_SHARED_SPACE_BUCKET` | optional | As above. |

**The four Cognito keys are in group (a), not group (b), and that is the re-scope's load-bearing
consequence for this spec.** Arc B keeps Cognito sign-in exactly as it is: Amplify configures itself
in the browser, performs the Hosted UI round trip and holds the ID token that SPEC-195 sends to the
API as a bearer. No spec in this arc removes these keys — the later target-environment arc does, when
it replaces the provider. A spec, a test or a `.env.example` note asserting that the browser stops
needing Cognito configuration during Arc B is wrong.

**The region and the two bucket names stay too, and no spec in this arc removes them.** SPEC-198 ports
the S3 surface onto presigned bytes but **freezes the service signatures that take a bucket**, so the
browser keeps naming both buckets and the region they live in for the whole arc. A spec, a test or an
end-state type declaring a seven-key browser document is wrong; the arc ends at ten.

**(b) What moves server-side as each porting spec lands — nine keys:**

| Key | From | Class | Removed by |
|---|---|---|---|
| `athenaWorkgroup` | `VITE_ATHENA_WORKGROUP` | required | SPEC-199 |
| `cognitoIdentityPoolId` | `VITE_COGNITO_IDENTITY_POOL_ID` | optional | SPEC-202 — the Identity Pool, **not** the User Pool. It keeps minting browser credentials until then, which is why no feature is degraded mid-arc. |
| `sharedSpaceQueueUrl` | `VITE_SHARED_SPACE_QUEUE_URL` | optional | SPEC-200 |
| `notificationsQueueUrl` | `VITE_NOTIFICATIONS_QUEUE_URL` | optional | SPEC-200 |
| `tableBuildQueueUrl` | `VITE_TABLE_BUILD_QUEUE_URL` | optional | SPEC-200 |
| `tableShareQueueUrl` | `VITE_TABLE_SHARE_QUEUE_URL` | optional | SPEC-200 |
| `dataQualityQueueUrl` | `VITE_DATA_QUALITY_QUEUE_URL` | optional | SPEC-200 |
| `fileSendQueueUrl` | `VITE_FILE_SEND_QUEUE_URL` | optional | SPEC-200 |
| `archiveQueueUrl` | `VITE_ARCHIVE_QUEUE_URL` | optional | SPEC-200 |

Nineteen keys today, ten at the end of the arc. **If Arc A has landed, SPEC-187's
`VITE_FILE_OPS_QUEUE_URL` is a twentieth** —
and FR-008's key-set test is what forces its addition rather than leaving it to be noticed in
production. The classification is not documentation; it is the input to FR-004's hard failure, so
moving a key between REQUIRED and OPTIONAL changes what boots.

### Premises later specs must honour

1. **`/config.json` is same-origin and boots without the API.** The SPA must render its own error
   states while the API is down, so the document is served by the SPA's own container and never
   proxied to API Gateway. SPEC-194 must not satisfy `/config.json` with a proxy pass.
2. **`Cache-Control: no-store`, and the failure looks exactly like success.** A promoted image whose
   `/config.json` is served from a cache populated in the previous environment renders a working,
   fully-functional portal pointed at the wrong account. Nothing on screen distinguishes it. The
   assertion that does is FR-008's: change one task-environment value, redeploy with an unchanged
   image, and read the new value back on the **first** request.
3. **A key is added in five places, and four of them are outside `lib/`.** FR-008 enumerates them.
   SPEC-193 adds the fifth (the ECS task definition) and must re-point FR-008's agreement test at it.
4. **The provider block never crosses into the browser, and the browser's Cognito keys never cross
   into it.** SPEC-195 builds the API's verifier against FR-007's field set; the moment the SPA needs
   an issuer, an audience or a JWKS URI, the design has gone wrong — the browser sends a token it
   already has and verifies nothing. The converse holds too: the verifier must not be configured by
   reading the browser's document, or the trust anchor becomes client-supplied.

---

## Functional Requirements

### FR-001: The runtime configuration document

#### Description:

A JSON document served at `/config.json`, same-origin, carrying every key in the classification
table. It is the SPA's only source of production configuration.

#### Acceptance Criteria:

- [ ] `GET /config.json` returns a JSON object with a numeric `version` and string values for every
      other key. A non-string value for any key is treated as absent.
- [ ] `version` is `1`. A document whose `version` is anything else is refused **whole** — not
      partially read, not merged with defaults — on SPEC-162's precedent, and reported as
      `unsupported-version`.
- [ ] An empty-string value reads as **unset**, matching `envVar`'s existing rule (an unset GitHub
      repository variable and an unset ECS task variable both interpolate to `""`).
- [ ] A key present in the document but absent from the classification is **ignored**, not an error:
      a task definition ahead of the image must not break the image.
- [ ] The loader fetches with `cache: 'no-store'` **and** the document is served with
      `Cache-Control: no-store` (the header is SPEC-194's to emit; asserting the client's request
      option is this spec's).
- [ ] **A 200 carrying HTML is `unparseable`, not a success.** The current distribution maps
      `403/404 → /index.html` with a **200** (SPEC-141), so a missing document arrives as a
      successful response full of markup. A test fixtures the real `index.html` body as the response
      and asserts the loader reports `unparseable`. A loader that keys on `response.ok` passes every
      other test in this file and fails this one.

### FR-002: The accessor

#### Description:

`lib/runtimeConfig.ts` replaces `lib/env.ts` as the single door to configuration, keeping every
property `lib/env.ts`'s docstring already claims — one typed read, at call time, per key.

#### Acceptance Criteria:

- [ ] `configValue(name: RuntimeConfigKey): string | undefined` reads from the loaded document at
      **call time**. No module-level capture of a value anywhere in the module.
- [ ] `REQUIRED_CONFIG` and `OPTIONAL_CONFIG` are exported `as const` arrays and `RuntimeConfigKey` is
      their union — the **single** declaration of the document's key set, which is why no criterion
      here compares it with the document (both operands would be that one declaration). The agreement
      that can fail is against the wiring points, and it lives in FR-008.
      `missingRequiredConfig()` and `isPortalConfigured()` behave as `lib/env.ts`'s namesakes do.
- [ ] In a **production** build, `configValue` called before `loadRuntimeConfig()` has resolved throws
      a named `RuntimeConfigNotLoadedError`. It does **not** return `undefined`: a silent `undefined`
      is the exact failure mode — "a generic SDK error about a bucket named undefined" — that
      `lib/env.ts` was written to prevent, and re-introducing it here would make the whole spec
      decorative. In a **dev** build the same call answers from the fallback with no load having
      happened (FR-003 AC1), which is the arm the existing suite runs on.
- [ ] `lib/env.ts` retains **only** the dev-fallback table and `warnIfMisconfigured`; every other
      export is removed and its callers moved. `lib/userSpace.ts` exports four functions, three of
      which read configuration (`userSpaceBucket`, `sharedSpaceBucket`, `spaceBuckets`;
      `userSettingsKey` reads none) — all four keep their signatures and the file changes one import
      line.

### FR-003: The dev fallback, and its absence from production builds

#### Description:

Local development runs with no container and no server able to render `/config.json`. The accessor
falls back to `import.meta.env` in a dev build only.

#### Acceptance Criteria:

- [ ] With `import.meta.env.DEV` true and `/config.json` absent or unparseable, `loadRuntimeConfig()`
      succeeds and every `configValue` resolves from the corresponding `VITE_*` variable — **including
      when `loadRuntimeConfig()` was never called at all**. That is not a convenience: it is what makes
      FR-002 AC3's throw compatible with the existing suite, which imports modules and reads
      configuration without any bootstrap.
- [ ] With `import.meta.env.DEV` false, the fallback is **never consulted** — including when the
      document is present but incomplete. A document missing `userSpaceBucket` fails FR-004 even
      though `VITE_S3_USER_SPACE_BUCKET` is set in the process that built the bundle.
- [ ] The existing test suite passes **without changing a single `vi.stubEnv` call site**: under
      Vitest `import.meta.env.DEV` is true, so every read lands on the fallback arm above — no load has
      happened, nothing throws, and the stubbed `VITE_*` value answers. Tests that need the document
      path use `seedRuntimeConfig(partial)` from `src/test/`, and only the tests that stub `DEV` false
      can see `RuntimeConfigNotLoadedError` at all.
- [ ] The prod-only branch is tested by stubbing the mode (`vi.stubEnv('DEV', false)`), so FR-004's
      criteria are exercised rather than merely written down.
- [ ] **The fallback is eliminated from the production bundle, and this is asserted on the built
      output**: after `npm run build`, no `VITE_` variable *name* appears as a string literal in
      `dist/assets/*.js`. Vite substitutes each `import.meta.env.VITE_X` with its value, so a
      surviving name means the fallback's key table survived, which means the branch was not
      eliminated. Precedent: `lib/s3Client.ts` records the same technique, measured rather than
      argued, for the computed-index hazard.
- [ ] **`apps/portal/public/config.json` does not exist**, and a test asserts its absence. Files in
      `public/` are copied verbatim into `dist/`, so a committed one would be baked into the image
      and served in preference to nothing — a build-time config wearing the runtime mechanism's
      clothes, which is this spec's failure inverted. It is also added to `.gitignore` so a
      developer may create one locally; SPEC-194 must exclude it from the image build context.

### FR-004: A production boot with bad configuration fails hard, and says so

#### Description:

In a production build, a document that cannot be fetched, parsed, versioned or completed is a
terminal boot failure. The app does not render.

#### Acceptance Criteria:

- [ ] `loadRuntimeConfig()` returns a discriminated result whose failure arm carries one of exactly
      four reasons: `unreachable`, `unparseable`, `unsupported-version`, `missing-required`.
      `missing-required` also carries the offending key names.
- [ ] On failure in a production build, `main.tsx` renders `<BootFailure />` into `#root` and
      **never** mounts `AuthProvider`, `QueryClientProvider`, `BrowserRouter` or `App`. A test
      asserts no route renders.
- [ ] `<BootFailure />`'s wording comes from `lib/errorMessages.ts` (a new `RuntimeConfigUnavailable`
      entry), not a string literal at the boot site — SPEC-106's rule holds at boot as everywhere
      else. The rendered text names no key and no value.
- [ ] The boot failure writes **one** `console.error` naming the reason and, for `missing-required`,
      the missing key **names**. A test asserts that no *value* from the document appears in any
      console output. `lib/env.ts`'s "production stays silent" rule is deliberately narrowed here:
      it exists so a deployed app does not print its configuration, and a key name is not
      configuration — it is the only diagnostic an operator staring at a failed task has.
- [ ] An **optional** key being absent never triggers the failure. `environment` absent boots, and
      the flags feature resolves the document's own `defaults`, exactly as SPEC-162 specifies.

### FR-005: The async bootstrap, and the import graph it must not evaluate

#### Description:

`main.tsx` becomes: load config, configure Amplify, render. `lib/amplify.ts` stops configuring itself
at import.

**Awaiting the load is not enough on its own.** A module's static imports are evaluated before its
first statement runs, so `import App from './App.tsx'` — and the four provider imports beside it —
evaluate the whole application graph before `loadRuntimeConfig()` is even called. Every module-scope
configuration read in that graph then fires against an unloaded document and throws (FR-002 AC3), in
production only. `main.tsx` therefore keeps a **deliberately tiny** static import set and reaches the
application through `await import(...)` once the document is in hand. FR-006 converts the three
module-load reads as well; the two mechanisms are belt and braces, and the dynamic import is the one
that also protects a read a later spec adds without thinking about boot order.

The dynamically-imported module is the whole provider tree, not `App` alone — `AuthProvider`,
`QueryClientProvider`, `BrowserRouter` and `ToastProvider` are imported by `main.tsx` today and pull
exactly the graph the boundary exists to defer, so they move into `AppRoot.tsx` with `App` and
`main.tsx` imports that.

#### Acceptance Criteria:

- [ ] `lib/amplify.ts` exports `configureAmplify(): void` and `isAmplifyConfigured(): boolean` — a
      **function**, where it is a `const` today. `lib/env.ts`'s docstring, which cites that const as
      the counter-example to its own call-time rule, is corrected in the same change.
- [ ] `main.tsx` no longer carries a bare `import './lib/amplify'` with an ordering comment. The
      ordering is expressed by `await`, so it cannot be broken by an import reorder or by a linter.
- [ ] `main.tsx`'s **static** imports are exactly `react-dom/client`, `./index.css`,
      `./lib/runtimeConfig`, `./lib/amplify` and `./components/BootFailure`; `AppRoot` is reached only
      by `await import('./AppRoot')`, after the load resolves. A `?raw` sweep asserts that set and
      **fails if it grows** — re-adding `import App from './App.tsx'` is the specific regression, and
      it is invisible in dev because the fallback answers there.
- [ ] A test with `DEV` stubbed false and `/config.json` unreachable asserts that **no module in the
      application graph was evaluated**: `BootFailure` renders, `configValue` is never called, and no
      `RuntimeConfigNotLoadedError` escapes. Without the dynamic import this test throws instead of
      rendering, which is what makes it able to fail.
- [ ] `Amplify.configure()` runs before `createRoot(...).render(...)` — asserted by call order, not
      by reading the file.
- [ ] `loadRuntimeConfig()` is called exactly once per page load. It runs **before** `createRoot`, so
      `StrictMode`'s double-render cannot double-fetch; a test counts the `fetch` calls.
- [ ] The identity-pool branch of `configureAmplify` keeps both literal object shapes. Collapsing
      them into one object with an optional `identityPoolId` is what the current file's comment
      forbids, and the reason (Amplify's strict union defeats the inference) is unchanged by moving
      the source of the values.
- [ ] No new loading UI: the pre-mount state is whatever `#root` already holds, and the fetch is one
      same-origin request against a document served by the same server as the bundle.

### FR-006: Every production config read goes through the accessor

#### Description:

The 23 measured reads that move (the 40 production reads minus `readEnv()`'s 17-entry table, which
stays as the dev fallback) move onto `configValue` and its wrappers. Sixteen already read at call time
and change only their **source**. The other seven are the module-load reads, across the three sites the
inventory names, and they change **shape** — this FR says which shape each gets.

#### Acceptance Criteria:

- [ ] After this spec, the only files in `apps/portal/src` naming `import.meta.env.VITE_*` are
      `lib/env.ts` (the fallback table) and the four dev-unauth files
      (`lib/s3Client.ts`, `components/ProtectedLayout.tsx`, `routes/FilesPage.tsx`,
      `features/file-browser/fileBrowser.service.ts`). A `?raw` sweep asserts that set exactly, and
      **fails if it grows** — SPEC-153's bypass-guard technique, which already asserts the dev-unauth
      set and must be updated in step rather than duplicated.
- [ ] `lib/userSpace.ts`, `athena.service.ts`, `fileBrowser.types.ts`, the four SDK clients and all
      seven enqueue services read through the accessor. No behavioural change: the seven
      `notConfiguredMessage` degraded paths still fire on an unset queue URL, and a test per service
      still proves it.
- [ ] The two ternary bucket picks (`archive.service.ts:31`, `fileSend.service.ts:26`) route through
      `spaceBuckets()` rather than re-reading raw keys, so the bucket names keep exactly one home.
- [ ] `lib/s3Client.ts`'s exported `s3Client` **const** becomes a call-time builder. It is the one file
      holding both kinds of read: its `region:` reads move to `configValue('awsRegion')`, while
      `VITE_AWS_ACCESS_KEY_ID` and `VITE_AWS_SECRET_ACCESS_KEY` stay on `import.meta.env` behind the
      existing `DEV` guard — the gate-at-the-READ rule that file documents is unchanged and must not be
      collapsed into the accessor.
- [ ] `fileBrowser.types.ts`'s `MAX_UPLOAD_BYTES` **const** becomes `maxUploadBytes()`, and its four
      production call sites (`UploadQueueProvider.tsx`, `fileBrowser.service.ts` twice, and the
      `features/file-browser/index.ts` re-export) move with it. `MULTIPART_PART_SIZE` and
      `PART_CONCURRENCY` are literals, not configuration, and stay consts.
- [ ] No module outside the five files AC1 names reads configuration at **module scope**. The three
      sites in the inventory are the whole set today; a test asserts each of the three exports is a
      function rather than a captured value, so a later re-collapse to a const is a failing test rather
      than a production boot failure.
- [ ] `import.meta.env.DEV` appears at the same eleven code sites, unchanged. A diff touching one of
      them is out of scope for this spec.

### FR-007: The provider block is the API's verifier configuration, and the browser document excludes it

#### Description:

The API Lambda's token-verifier configuration is provider-agnostic — the same field set describes
Cognito today and Entra later — and it arrives as Lambda environment variables. It is what the API
needs to decide that a bearer token is genuine: the issuer it trusts, the audience it demands, the
JWKS it fetches keys from, and which verified claim becomes `actor`. None of it is in the browser's
document, because the browser verifies nothing — it sends the ID token Amplify already holds.

**This is not an OIDC *client*.** No code exchange, no PKCE verifier, no client secret, no redirect
URI, no scope list: those belong to Amplify, in the browser, unchanged by this arc. Building a client
here is the shape of error this FR exists to prevent, and it is why the field set is small.

The exclusion cuts **one way only**, and the distinction is the whole subtlety of this FR: the four
Cognito values in classification group (a) are Amplify's, they are legitimately browser-side, and a
test written to forbid "anything that smells of identity" would delete them and break sign-in.

#### Acceptance Criteria:

- [ ] The block's field set is specified here (Data Model) and named in `docs/architecture.md`. It is
      **consumed** by SPEC-195 and **provisioned** by SPEC-193; this spec creates no infrastructure
      and no Python module.
- [ ] The block is provider-agnostic in the strong sense: no field name contains `cognito` or
      `entra`, and swapping providers is a change of **values only**. A field that only one provider
      can supply is a design error, not a spec detail. `OIDC_JWKS_URI` is a field rather than a
      derivation of `OIDC_ISSUER` for exactly this reason — the well-known path is a convention, not
      a guarantee, and hard-coding it makes the verifier provider-specific in the one place that
      would fail closed and silently.
- [ ] A test intersects `REQUIRED_CONFIG ∪ OPTIONAL_CONFIG` with a forbidden set —
      `issuer`, `oidcIssuer`, `audience`, `oidcAudience`, `jwksUri`, `discoveryUrl`, `authorizeUrl`,
      `tokenUrl`, `clientSecret`, `usernameClaim`, `identityCenterApplicationArn`,
      `trustedTokenIssuerArn` — plus a case-insensitive substring rule over `oidc`, `issuer`,
      `audience`, `jwks` and `secret`. The intersection must be empty.
- [ ] **That test is guarded against passing vacuously**: a second case runs the same checker over a
      synthetic key set containing `issuer` and asserts it is flagged. A checker that flags nothing
      passes the first case forever, and this repo's review history records exactly that defect
      shape more than once.
- [ ] **The checker is guarded in the other direction too, and this criterion can fail today.** A
      third case runs it over the real group-(a) keys — `cognitoUserPoolId`,
      `cognitoUserPoolClientId`, `cognitoDomain`, `appUrl` — and asserts **none** is flagged. These
      are the values `Amplify.configure()` reads; a forbidden set that grew a `client`, `clientId`,
      `domain` or `redirect` rule would flag one of them, and the visible result is not a failing
      test in the browser but a Hosted UI round trip that never completes. Adding `clientId` to the
      forbidden set is the specific mistake: `cognitoUserPoolClientId` survives an exact-match rule
      and dies under a substring one.
- [ ] `cognitoDomain` — the Hosted UI host — is **not** a provider-block field. It stays in the
      browser's document for the whole arc, because Amplify POSTs the code exchange to it. The
      forbidden set is about *the API's trust anchors*, not about the word Cognito.

### FR-008: Deploy wiring, and serving the document before the container exists

#### Description:

Every key needs a source in every environment, and production must keep working between this spec and
SPEC-194.

#### Acceptance Criteria:

- [ ] **`deploy-app.yml` writes `config.json` from the same repository variables it feeds the build**,
      and uploads it to the static site as a **fourth** sync pass with `--cache-control no-store`.
      SPEC-141's single `--delete` is scoped to `assets/`, so a root-level `config.json` is safe from
      it; the object is at the root, not under `assets/`.
- [ ] The build env in `deploy-app.yml` keeps every `VITE_*` it has today. The bundle no longer reads
      them in production (FR-003), but the workflow now uses the same values to render the document,
      and removing them would be a second change riding on this one.
- [ ] The key set agrees across every wiring point, asserted by test rather than by review. This is
      the agreement FR-002 AC2 defers to: `RuntimeConfigKey` is one declaration, so the only comparison
      that can fail is against something outside it —
      `REQUIRED_CONFIG ∪ OPTIONAL_CONFIG` ↔ the `VITE_*` names in `apps/portal/.env.example`
      (read with `?raw`) ↔ the `VITE_*` names in `deploy-app.yml`'s build env, modulo one named
      dev-only exemption list. **This test fails today** against the live gap:
      `VITE_ARCHIVE_QUEUE_URL` is in `.env.example` and in the workflow but absent from `lib/env.ts`,
      so nothing currently reports it unset. Closing that gap is part of this FR.
- [ ] The five wiring points are named in `.env.example`'s header comment: the runtime document, the
      classification in `lib/runtimeConfig.ts`, `.env.example` itself, the GitHub repository
      variable, and — from SPEC-193 — the ECS task definition. Four exist today; SPEC-193 adds the
      fifth and re-points this test at it.
- [ ] **The distribution gets a cache behaviour for `config.json` (`Managed-CachingDisabled`),
      carrying the response-headers policy explicitly.** Added during implementation, and it
      qualifies the Out of Scope line above: this spec still creates no *new resource type*, but
      the `no-store` header alone cannot deliver FR-001 AC5 on the interim static site.
      `Managed-CachingOptimized` applies its **1 s MinTTL even when the origin sends `no-store`**,
      and an object that ever reaches the edge without a `Cache-Control` header takes the
      **24-hour DefaultTTL** — one environment's account ids served to another's users, as a
      portal that looks entirely healthy. `response_headers_policy_id` is **per-behaviour and not
      inherited**, so omitting it would serve the document with no CSP, no HSTS and no `Server`
      stripping. No deploy-role IAM change: `cloudfront:GetCachePolicy` and `ListCachePolicies`
      are already granted.
- [ ] The consequence for Phase 5: the **`no-store` negative control is withdrawn**, because after
      this behaviour lands the edge caches nothing whether or not the object carries the header,
      and the loader's own `cache: 'no-store'` stops the browser either way. The header is verified
      by a **direct read**; edge freshness is a property of the cache policy. A check that cannot
      redden is not a check.
- [ ] A live check (Phase 5) proves the promotion property: change one repository variable, re-run
      Deploy App with **no source change**, and read the new value from `GET /config.json` on the
      first request. A cached response returning the old value fails this criterion, and is the only
      thing that distinguishes a working `no-store` from a broken one — the app looks identical
      either way.

---

## Data Model

```ts
// apps/portal/src/types/runtimeConfig.types.ts

/** The served document. Every value is a string; `version` is the sole number. */
export type RuntimeConfigDocument = {
  version: number;
} & Partial<Record<RuntimeConfigKey, string>>;

/** The classification table above, as code. The arrays are the single home of the key set. */
export const REQUIRED_CONFIG = [
  'appUrl', 'awsRegion', 'userSpaceBucket', 'athenaWorkgroup',
  'cognitoUserPoolId', 'cognitoUserPoolClientId', 'cognitoDomain'
] as const;

export const OPTIONAL_CONFIG = [
  'apiBaseUrl', // required from SPEC-197
  'environment', 'maxUploadBytes', 'sharedSpaceBucket', 'cognitoIdentityPoolId',
  'sharedSpaceQueueUrl', 'notificationsQueueUrl', 'tableBuildQueueUrl',
  'tableShareQueueUrl', 'dataQualityQueueUrl', 'fileSendQueueUrl', 'archiveQueueUrl'
] as const;

export type RequiredConfigKey = (typeof REQUIRED_CONFIG)[number];
export type OptionalConfigKey = (typeof OPTIONAL_CONFIG)[number];
export type RuntimeConfigKey = RequiredConfigKey | OptionalConfigKey;

export type RuntimeConfigLoadFailure =
  | {reason: 'unreachable'}
  | {reason: 'unparseable'}
  | {reason: 'unsupported-version'; found: unknown}
  | {reason: 'missing-required'; missing: RequiredConfigKey[]};

export type RuntimeConfigLoad = {ok: true} | ({ok: false} & RuntimeConfigLoadFailure);
```

`RuntimeConfigLoad` is deliberately **not** a `ServiceResult`. `ServiceResult`'s error carries a
user-facing `message`, and the boot failure's wording must come from `toUserMessage` at the render
site (FR-004), not from the loader. What the loader returns is a machine reason.

```
# The OIDC provider block — API Lambda environment variables (SPEC-193 provisions,
# SPEC-195 consumes). It configures a token VERIFIER, not an OAuth client.
# Provider-agnostic: Cognito today, Entra later, values only.
#
# OIDC_ISSUER          the `iss` a token must carry, compared exactly
#                      (Cognito today: https://cognito-idp.<region>.amazonaws.com/<userPoolId>)
# OIDC_AUDIENCE        the `aud`/`client_id` a token must carry (the User Pool client id today)
# OIDC_JWKS_URI        where signing keys are fetched from; a field, not a derived path (FR-007)
# OIDC_USERNAME_CLAIM  which verified claim becomes `actor` (SPEC-201's five-reader collapse)
#
# There is deliberately no client id/secret, redirect URI, scope list or PKCE state here:
# the browser performs the code exchange through Amplify, exactly as it does today, and the
# API only ever inspects a token it is handed.
#
# None of these appears in the browser's document, and none of the browser's four Cognito
# values appears here. FR-007's test enforces both directions.
```

---

## API / Interface Contract

```ts
// apps/portal/src/lib/runtimeConfig.ts

/** Called exactly once, from main.tsx, before createRoot. Never throws. */
export function loadRuntimeConfig(): Promise<RuntimeConfigLoad>;

/** One typed read, at call time. Empty string reads as undefined. */
export function configValue(name: RuntimeConfigKey): string | undefined;

export function missingRequiredConfig(): RequiredConfigKey[];
export function isPortalConfigured(): boolean;
```

```ts
// apps/portal/src/lib/amplify.ts  (shape after this spec)
export function configureAmplify(): void;
export function isAmplifyConfigured(): boolean;

// apps/portal/src/test/seedRuntimeConfig.ts
export function seedRuntimeConfig(partial?: Partial<RuntimeConfigDocument>): void;
```

## Environment Variables

No new `VITE_*` variable. `.env.example` is rewritten so each entry states that it is the **dev
fallback only**, names its runtime-document key, and names all five wiring points in its header.
`VITE_ARCHIVE_QUEUE_URL` gains its missing classification entry (FR-008).

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   ├── runtimeConfig.ts
│   ├── runtimeConfig.test.ts
│   ├── env.ts                 (dev fallback + warnIfMisconfigured only)
│   ├── amplify.ts             (configureAmplify / isAmplifyConfigured)
│   └── errorMessages.ts       (+ RuntimeConfigUnavailable)
├── components/
│   ├── BootFailure.tsx
│   └── BootFailure.test.tsx
├── types/
│   └── runtimeConfig.types.ts
├── test/
│   └── seedRuntimeConfig.ts
├── AppRoot.tsx                (the provider tree + App; dynamically imported)
└── main.tsx                   (async bootstrap; five static imports, no app graph)

.github/workflows/deploy-app.yml   (+ render config.json, + fourth sync pass)
docs/testing/arc-b-api-container-e2e.md
```

## Implementation Phases

### Phase 1: The document, the accessor and the classification

- `runtimeConfig.types.ts`, `runtimeConfig.ts`, the version gate, the four failure reasons.
- `REQUIRED_CONFIG` / `OPTIONAL_CONFIG` carried over from `lib/env.ts`, plus the archive gap closed.
- The dev fallback, and the `vi.stubEnv('DEV', false)` tests that exercise the production arm.
- FR-001's HTML-body fixture, taken from the real `index.html`.

### Phase 2: The bootstrap and the boot failure

- `configureAmplify` / `isAmplifyConfigured` as functions; the `lib/env.ts` docstring correction.
- `main.tsx`: load → configure → `await import('./AppRoot')` → render, with the single-fetch,
  call-order and static-import-set assertions; the provider tree moves to `AppRoot.tsx`.
- `BootFailure`, its `errorMessages.ts` entry, and the "no value reaches the console" test.

### Phase 3: The call-site port

- The 23 moving reads, service by service, with the seven degraded paths re-proved — including the
  three module-load sites, each converted to the shape FR-006 names.
- The `?raw` sweep pinning the surviving `import.meta.env.VITE_*` sites to exactly five files.
- The built-output assertion that no `VITE_` name survives in `dist/assets/*.js`.
- `seedRuntimeConfig` for the tests that want the document path.

### Phase 4: The provider block and the wiring

- FR-007's field set in `architecture.md`; the exclusion test and its guard-the-guard.
- `.env.example` rewrite; the three-way key-set agreement test.
- `deploy-app.yml`: render `config.json`, fourth sync pass with `--cache-control no-store`.

### Phase 5: Verification

Nothing offline proves any of this. The dev fallback is active under Vitest, which means the entire
suite exercises the arm that will not exist in production — the mirror of SPEC-137, where
instrumented code shipped whose layer attachment was missing while every offline gate passed. These
are real invocations against the deployed app, as a new section of
`docs/testing/arc-b-api-container-e2e.md`.

- The deployed app boots and `GET /config.json` returns **200 with `application/json`** and
  `Cache-Control: no-store`. Read it from the network panel; do not infer it from the app working.
- **The promotion check (FR-008).** Change one repository variable — `VITE_MAX_UPLOAD_BYTES` is the
  cheapest, being visibly enforced client-side — re-run Deploy App with no source change, and read
  the new value back on the **first** `GET /config.json`. A stale value here is the failure this
  whole spec exists to prevent, and it is invisible from the UI.
- **The `no-store` header, read directly** — not inferred from a reload. > **SUPERSEDED during
  implementation:** this was a *negative control* (reload twice, expect the second request to reach
  the origin). FR-008's `CachingDisabled` behaviour makes the edge cache nothing either way, so no
  observation distinguishes a present from a missing origin header. Read the header off the
  response; edge freshness is guaranteed by the cache policy. SPEC-141 records that this
  distribution answers a *deleted* asset with a **200** carrying `index.html`, so a status code
  still proves nothing here — check `content-type` too.
- **The hard-failure path, staged deliberately.** Publish a `config.json` with `userSpaceBucket`
  removed, load the app, and confirm: `BootFailure` renders, no route mounts, the console names the
  key, and **no value from the document appears in the console**. Then restore it. This is the only
  way to see FR-004 in a production build — the dev fallback hides it everywhere else.
- **The unparseable path**, staged by publishing HTML at the key: the app must report the same
  boot failure rather than rendering with everything undefined.
- **A fresh sign-in, from a private window, end to end** — proving FR-005's ordering against real
  Cognito. A bootstrap that configures Amplify after the first render produces a *sometimes*-working
  sign-in, and a warm session never exercises it: the browser reaches the app already authenticated
  and the ordering defect is invisible. This is the same shape as SPEC-140's Hosted-UI omission that
  broke fresh sign-in for a day. Sign out and back in; do not accept an already-signed-in tab as
  evidence.
- **Not observable and recorded as owed, not discharged:** anything about the container. Until
  SPEC-194 the document is a static object, so the entrypoint's rendering of it, nginx's `no-store`
  header and the image-promotion property itself are proven by SPEC-194's own checks, not by these.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row; the delivery doc at
  `docs/spec-delivery/SPEC-192-runtime-configuration-and-the-provider-block.md`.
- A `decisions.md` entry for **runtime configuration**: the document, the string-only rule, the
  dev-only fallback and why it must be dead-code-eliminated rather than merely guarded, the four
  failure reasons, and the boot failure being hard where SPEC-162's flag document is deliberately
  silent — the two documents look alike and their failure semantics are opposite. Then **one line**
  in CLAUDE.md's Key Decisions.
- A second `decisions.md` entry for **the provider block being the API's verifier configuration and
  server-side**: the field set, why it is a verifier and not an OAuth client while Amplify keeps
  performing the code exchange in the browser, why `OIDC_JWKS_URI` is a field rather than a derived
  path, and the two-directional test that enforces the boundary — including the one that would have
  taken Amplify's own keys out of the document. One line in Key Decisions.
- One-line inventory rows in the area files matching each path, never the router:
  `apps/portal/info/component-inventory/foundations.md` for `lib/runtimeConfig.ts` (and the reshaped
  `lib/env.ts` and `lib/amplify.ts` rows), `shared-components.md` for `BootFailure`, and
  `shared-types.md` for `runtimeConfig.types.ts`.
- `docs/architecture.md` → *Infrastructure & Deployment* gains the provider block's field set and the
  `/config.json` contract. `docs/transition_plan.md` §4.6 gains a superseded marker: its measured
  figure ("roughly 30 genuine production config reads across ~18 files") is **wrong at the read
  count** — 40 measured, of which 23 move and 17 stay as the dev fallback, not "roughly 30" — and its
  "you do not have to decide now" advice is now decided.
- The `ARCS.md` arc entry updated with what this spec found, including the sequencing decision
  (FR-008's static-site `config.json`) that the arc scoping did not anticipate.
- **Help sweep: nothing user-facing changes in this spec.** No label, route, flag or affordance moves;
  the one new surface (`BootFailure`) is reachable only when the app cannot boot, and documenting it
  in an in-app guide would put the explanation behind the failure it explains. Recorded explicitly
  and skipped, rather than left ambiguous.
