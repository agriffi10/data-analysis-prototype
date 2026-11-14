---
type: Spec
id: SPEC-262
title: "The Browser Signs In Through the Server"
description: "The browser stops holding tokens: it signs in, signs out and calls the API through the Next.js server's session routes and /api/ pass-through, Amplify and the public Cognito client retire, local development signs in through its own client, and every allowlist that served the old path narrows in a second merge."
spec_status: Draft
depends_on: [SPEC-256, SPEC-257, SPEC-258, SPEC-259, SPEC-260, SPEC-261]
arc: nextjs
arc_order: 8
---

**Dependency notes:** SPEC-257 (the session routes, the `/api/` route handler, the session store,
the confidential client, and the verifier reading an audience list). SPEC-256 (the boot in
`PortalBoot`, the shell's leave guard that `signOut` disarms, and the split route table and tests).
SPEC-258 to SPEC-261 (the area moves): the forced-refresh callers and the tests that mock Amplify or
`lib/idToken` sit in their areas, so this spec builds after them and no area move edits a file this
one rewrites. Arc reasoning and contracts: `ARCS.md` → *Next.js arc (SPEC-255 → 263)*, and its
dated SPEC-257 note. The file paths below are as they stand when this spec was written; the area
moves rename some, and the build re-finds each by its role.

## Overview

Today the browser signs in through Amplify, keeps its Cognito tokens in the tab, and calls the API
on another origin with the ID token as a bearer. After this spec the browser holds no token at all.
It signs in by visiting the server's `/auth/login`, learns who is signed in from `/auth/session`,
and calls the API through its own origin's `/api/`, where the server attaches the token. One
sign-in covers every tab in the browser. Amplify and the public Cognito app client retire, local
development signs in through a client of its own, and the allowlists that served the old path
narrow. The narrowing is a second merge, because it is the step that removes the way back.

## Scope

### In Scope

- The auth provider and the auth service on the session routes, with the sign-in failure message,
  the return path and the leave guard kept (FR-001).
- The API client on `/api/`, retrying nothing, and `lib/idToken.ts`'s forced-refresh export
  reimplemented over `POST /auth/refresh` at the same path (FR-002).
- Local development signing in through a dev client (FR-003).
- Amplify out of the code, the manifest, the bundle and the browser's document (FR-004).
- The second merge: the public client destroyed, the verifier narrowed, the API's CORS removed,
  `connect-src` narrowed, and the retired keys' wiring removed (FR-005).
- The decisions the charter assigns to this spec rewritten, and the Help guides swept (FR-006).

### Out of Scope

- **Gating pages on the server.** The sign-in gate stays in the browser and decides by path, as
  SPEC-256 left it; pages stay client components (charter).
- **An idle timeout, client-secret rotation, a "sign out everywhere", or a session list.** SPEC-257
  set the session's ceiling at the refresh token's 30 days, and this spec keeps it.
- **Telling other open tabs the moment one signs out.** A tab learns at its next request, whose 401
  moves it to signed-out. Presigned URLs it already holds stay valid until they expire, as today.
- **The buckets' CORS.** Uploads and downloads still redeem presigned URLs from the browser, so
  both rules keep `http://localhost:5173` and the portal origin.
- **Identity Center or Entra ID** (`transition_plan.md` Phase 1).
- **The landing page, the 404 and react-router** (SPEC-263).

---

## Functional Requirements

### FR-001: The browser's session comes from the server

#### Description:

`auth.service.ts` keeps its four exports and their `ServiceResult` shapes, with new bodies:

- `getCurrentAuthUser()` calls `GET /auth/session`: 200 is the user and 401 is signed out. A 503 or
  a network failure is signed out as well, but carries the `ApiUnavailable` failure, so the
  provider shows that wording rather than nothing. SPEC-257 holds that a fault is not a sign-out,
  and a developer whose AWS credentials have expired should read "unavailable", not "signed out".
- `startSignIn()` and `startSignUp()` call the same return-path helper as today
  (`setReturnPathIfAbsent`) and navigate the document to `/auth/login`. Managed Login's sign-in
  page links to sign-up, which is how sign-up is reached today.
- `startSignOut()` calls `POST /auth/logout` and, **only on a 200**, navigates the document to the
  `logoutUrl` it answers. On any failure the user stays signed in, the provider shows the error as
  it does today for a failed sign-out, and the leave guard is armed again. Navigating anyway would
  reload the page, find the session the failed call left alive, and sign the user back in while
  they believe they signed out.

`AuthProvider` drops the Hub listener and `ALREADY_AUTHENTICATED`. It reads the session once on
mount. On the landing page, `?signin=failed` sets today's message, *"Sign-in failed or was
cancelled."*, and is removed from the address with a replace, so a reload does not show it again.
**`signOut` disarms SPEC-256's leave guard synchronously before it starts the sign-out**, as it does
today before Amplify's, because the navigation to the provider's logout page would otherwise raise
the guard's prompt. `PortalBoot` no longer configures Amplify, and its static-import sweep loses
that import.

**When a session ends under a page** (Andrew, 2026-11-13, which closes the `owed.md` row *What
`setUnauthenticatedHandler` should DO*). `AuthProvider` registers the API client's unauthenticated
handler on mount. On a 401 it re-reads `/auth/session`. A 401 there moves the tab to signed-out, as
if it had signed out itself, and the landing page's sign-in returns to the page the user was on. A
200 naming **another** user reloads the document, so one person's page never acts as another's. A
200 naming the same user leaves the tab signed in, and the call that failed reports
`SessionExpired`.

**A tab never acts as another user.** One cookie serves the whole browser, so if Alice signs out in
one tab and Bob signs in there, Alice's other tab would send Bob's cookie on its next request: a
window-focus refetch or a poll would act as Bob under Alice's name. So `apiRequest` sends the
username the tab holds as `x-dq-user`, and the `/api/` route handler (SPEC-257 FR-005) answers 401
`SessionExpired`, before forwarding, when that header is present and differs from the session's
`cognito:username`. The header is consumed there and is not on the forwarded allowlist.

One session now covers the browser: a second tab, or a link opened in a new tab, is signed in
already, and a sign-out in one tab signs the others out at their next request.

#### Acceptance Criteria:

- [ ] `getCurrentAuthUser` returns the user for a 200 from `/auth/session`, signed-out with no
      failure for a 401, and signed-out with `ApiUnavailable` for a 503 and for a network failure,
      each asserted against a fetch double; the provider shows that failure's wording.
- [ ] `startSignIn` and `startSignUp` call `setReturnPathIfAbsent` with the same argument as today
      and assign `/auth/login`. `startSignOut` posts `/auth/logout` and assigns the answered
      `logoutUrl` on a 200; on a 503 and on a network failure it assigns nothing, the provider
      stays signed in and shows the error, and the leave guard is armed again.
- [ ] The provider shows *"Sign-in failed or was cancelled."* when the landing page carries
      `?signin=failed`, and after mounting the address no longer carries the parameter.
- [ ] With the provider mounted, an API 401 followed by a 401 from `/auth/session` moves the tab to
      signed-out; one followed by a 200 naming another user reloads the document; and one followed
      by a 200 naming the same user leaves it signed in. Each is asserted against doubles, which
      is the offline proof the handler is registered.
- [ ] `apiRequest` sends `x-dq-user` with the held username. The `/api/` route handler answers 401
      with no forward when the header differs from the session's username, forwards when it
      matches, and never forwards the header.
- [ ] `signOut` disarms the leave guard before the request to `/auth/logout` starts, asserted on
      call order, and with an upload running no leave prompt is raised (SPEC-256's own test,
      re-pointed at the new sign-out).
- [ ] `PortalBoot`'s static imports are SPEC-256's set without the Amplify module, asserted by
      equality, and no boot path calls anything named `configureAmplify`.
- [ ] **Live, on the deployed tier, in a new browser profile:** a sign-in from `/` completes and
      lands on the page the user started from (a deep link); a second tab opened on `/files` is
      signed in without a prompt; signing out in the first tab, then acting in the second, moves
      the second to signed-out; and visiting `/auth/callback?error=access_denied` lands on `/`
      showing the failure message (Managed Login has no cancel control that returns an error, so
      the error is supplied directly).

### FR-002: The API client goes through `/api/` and retries nothing

#### Description:

`apiRequest` builds `/api` + the route's filled path + its query, on the page's own origin, and sends
it with `credentials: 'same-origin'` and no `authorization` header. The token provider, the
forced-refresh retry and `MAX_AUTH_RETRIES` are deleted: refreshing is the `/api/` route handler's
job now (SPEC-257 FR-005), so a 401 that reaches the browser means the session is gone. `apiRequest`
calls the unauthenticated handler once and returns `SessionExpired`, with no second request. The
one-segment refusal and the per-route retry policy are unchanged.

**The timeout moves above the server's.** `TIMEOUT_MS` is 30 seconds today, set from the API
Gateway integration's ceiling so that the server always gives up first. The `/api/` route handler
now sits in between: it may read the session, refresh within SPEC-257's 5-second token-endpoint
bound, and wait 35 seconds for the API. So `TIMEOUT_MS` becomes 45 seconds. A test pins it above
the sum of the server's forward deadline and its token-endpoint bound, read from the server's own
constants, so a write the server completes is never reported to the user as `RequestTimeout`.

`lib/idToken.ts` keeps `getIdToken` at its path, so the three forced-refresh call sites (in the
Files and Connections areas) are untouched. A forced call posts `POST /auth/refresh` and returns
success on 204 or the failure the response maps to; an unforced call resolves success without a
request, because the browser has no token to fetch. The function's result becomes
`ServiceResult<void>`, which every call site already ignores, and its documentation says the name
is kept for the callers' sake.

#### Acceptance Criteria:

- [ ] A call to a route whose path is `/v1/x/{id}` with `id` `a b` fetches `/api/v1/x/a%20b` on the
      page's origin, with `credentials: 'same-origin'` and no `authorization` header.
- [ ] A 401 issues exactly one fetch, calls the unauthenticated handler exactly once, and returns
      `SessionExpired`; a 503, a 429, a timeout and a network failure each issue exactly one fetch
      as well, so no status retries.
- [ ] `getIdToken(true)` posts `/auth/refresh` with no body and resolves success on 204 and failure
      on 401; `getIdToken()` makes no request.
- [ ] `TIMEOUT_MS` exceeds the server's forward deadline plus its token-endpoint bound, asserted by a
      test that imports both server constants; lowering it to 39 seconds fails that test.
- [ ] The non-test source files of the three forced-refresh callers are byte-identical before and
      after this spec, asserted on the diff.
- [ ] `identity-and-access/apirequest-retries-nothing-and-idempotency-is-declared-per-route` is
      rewritten: no retry under any status, and the refresh it used to describe lives in the
      `/api/` route handler.

### FR-003: Local development signs in through a dev client

#### Description:

Andrew chose this on 2026-11-13 over no local sign-in and over reusing the production client. The
`auth` module gains a third app client, the **dev client**, which mirrors the server client
(SPEC-257 FR-002) except that its one callback is `http://localhost:5173/auth/callback` and its one
sign-out URL is `http://localhost:5173`. Its own secret means a laptop can be cut off without
touching production, and the production client's lists never name localhost. The verifier's list
gains its id (FR-005 keeps it).

Terraform renders every session variable a local server needs, the dev client's secret included,
into one SSM `SecureString` parameter, `/<project>-<environment>/portal/dev-session-env`, from the
same locals that render the task definition's, so the two cannot drift. `npm run dev:session-env`
reads it with the developer's AWS credentials and writes the variables into `apps/portal/.env.local`
between two marker lines. It replaces only that block, keeps every other line, and prints only
variable names. `.env.local` is already ignored by `*.local`. The local server then uses the real
session table with the same credentials; the key's policy delegates to IAM, so any identity with the
item actions can, and Andrew's local identity holds `AdministratorAccess`.

**Under `next dev`, the two cookies are named `dq_session` and `dq_signin`, without the `__Host-`
prefix and without `Secure`.** `next dev` serves plain `http://localhost:5173`, and a `__Host-`
cookie needs `Secure`, which each browser honours over plain http only through its own localhost
exception. The branch reads `NODE_ENV`, which a built server always sets to `production`.

Because every page now signs in through the session routes, the session variables join SPEC-255's
start-time check (`src/instrumentation.ts`): a server missing one exits naming it, under `next dev`
as well, which is what tells a developer to run the script. The image's behaviour matrix
(`.github/scripts/spa-image-matrix.sh`) starts its containers from a fixture environment, so that
fixture gains a value for each session variable, and the matrix gains one refusal row per variable;
otherwise every container in it exits at start.

**The deploy role.** The dev client is a resource type SPEC-257 already granted. The dev-session
parameter is a second SSM parameter under the same `/<project>-<environment>/portal/` path, which
SPEC-257's build scopes its SSM grant to. The build reads the grant as it landed before planning,
and if it names only the first parameter's ARN, the widening lands in its own PR before merge 1
(`infra/info/deploy-role-iam.md`): the provider's refresh of a `SecureString` reads its value, so a
missing read grant fails the apply after the create, as well as the create itself.

#### Acceptance Criteria:

- [ ] The HCL test from SPEC-257 FR-002 holds the three clients to the same mirrored settings; the
      dev client's callback and sign-out lists are exactly the two localhost URLs, and the server
      client's lists name no localhost. The public client keeps `http://localhost:5173` until
      merge 2 destroys it, and after merge 2 only the dev client names localhost.
- [ ] The image matrix passes with the fixture's session values, and each of its new refusal rows
      fails when its variable is unset, with the variable's name on stderr.
- [ ] The dev-session parameter is rendered from the same locals as the task definition's session
      variables, asserted by a test that fails when either side names a literal; it is a
      `SecureString`, and no Terraform output exposes it.
- [ ] Run twice against a stubbed `aws` command, `dev:session-env` leaves exactly one marked block,
      preserves a line outside it, writes every variable the start check requires, and prints no
      value, asserted on captured output.
- [ ] A cookie test with `NODE_ENV` set to `production` gets the `__Host-` names with `Secure`, and
      one with `development` gets the unprefixed names without `Secure`.
- [ ] With one session variable unset, the server exits 1 and names it, as SPEC-255's check does
      for a `CONFIG_*` key.
- [ ] **Live, on Andrew's laptop:** after `npm run dev:session-env`, `npm run dev` signs in at
      `http://localhost:5173`, lists the user's files through `/api/`, and uploads one through a
      presigned URL. Signing in at Managed Login is Andrew's to do if no warm session makes it one
      click.
- [ ] The README's *Running it locally* section describes this, and no longer tells a reader to set
      `VITE_COGNITO_*` or an API base URL.

### FR-004: Amplify leaves the code, the manifest and the bundle

#### Description:

`aws-amplify` leaves `package.json`, and `lib/amplify.ts` is deleted. Every test that mocks
`aws-amplify` mocks `auth.service.ts` or the fetch boundary instead. The manifest sweep's
guard-the-guard, which required the manifest to name `aws-amplify` so that a parse that read nothing
could not pass, is re-anchored on `next`. `npm run check:bundle` gains a rule that fails on
`AWSCognitoIdentityProviderService`, Amplify's Cognito protocol target. Measured while authoring:
it is in Amplify's installed code and in a chunk of a built portal bundle today, so its absence
from `.next/static/` is the positive proof that Amplify left the bundle.

**The browser's document keeps all six of its retiring keys in this merge**: `apiBaseUrl`,
`appUrl`, `awsRegion`, `cognitoUserPoolId`, `cognitoUserPoolClientId` and `cognitoDomain`. Only
their readers go: `lib/amplify.ts` with Amplify, and `apiClient`'s read of `apiBaseUrl`.
(`awsRegion` has had no reader at all; only Amplify read the other four.) The keys stay classified,
wired and served until FR-005 removes them from every site at once. Two reasons decide this. The
rollback image reads them and refuses to start without them. And three guards hold the wiring sites
equal to one another (`runtimeConfig.test.ts` over Terraform's runtime map,
`lambdas/test_config_outputs.py` over `.github/config-outputs.json`, and the image matrix's pinned
document key list), so a key removed from one site and left in another turns the suite red. The
cheapest way back to green would be deleting the task-definition entries, which is exactly what
breaks the rollback.

#### Acceptance Criteria:

- [ ] No file under `apps/portal/src/` names `aws-amplify` or `@aws-amplify/`, and neither does
      `apps/portal/package.json`, asserted by a test that reads every source and test file.
- [ ] The manifest sweep fails on an empty manifest, now because `next` is absent; planted once and
      reverted.
- [ ] `npm run check:bundle` passes on this branch, and fails naming the chunk when a client
      component calls a planted `fetchAuthSession` from `aws-amplify/auth` (a bare import could be
      tree-shaken away); planted once and reverted.
- [ ] No module outside tests calls `configValue` with any of the six keys, asserted by a sweep,
      while `/config.json` on `next start` still carries all six and the wiring guards pass
      unchanged.

### FR-005: The second merge retires the public client and narrows every allowlist

#### Description:

This is the merge after which there is no rollback, so it lands on its own, after FR-001 to FR-004
have merged and been checked live with the old path still intact
(`infrastructure/a-cutover-is-two-merges-and-only-the-second-one-destroys-the-rollback`). Between
the two merges, the rollback is the image the service ran before merge 1, read off the task
definition before merge 1 lands and recorded in its PR, because SPEC-255's image deploy builds
only commits that change an image input and refuses a tag the registry does not hold. That image
still signs in through Amplify because nothing it needs has gone. It is rehearsed once by
re-pointing the service at that tag through the image deploy, signing in through Amplify and
listing files, then re-pointing at the current image.

The second merge:

- sets `OIDC_AUDIENCE` to the server client and the dev client. Lambda builds are on for the arc, so
  the frozen-fleet guard passes;
- destroys the public client, removes its id from the branding step and its output, and removes
  its callback list with it;
- removes the API's `cors_configuration`, because no browser calls the API any more, and with it
  the router's preflight branch (`lambdas/api/router.py`, `PREFLIGHT_METHOD`), whose stated reason
  is that CORS is configured on the API. An `OPTIONS` then takes the ordinary unauthenticated
  refusal;
- narrows `csp_connect_src` to `'self'` and the two buckets' endpoints. The test that names the
  Cognito entries separately, so that nobody could delete them on purpose, inverts: it now
  asserts that neither they nor the API origin appear;
- removes the six retiring keys (FR-004) from every wiring site at once: the classification, their
  dev-fallback entries in `lib/env.ts`, `.env.example`, Terraform's runtime map and so the task
  definition, their Terraform outputs, `.github/config-outputs.json`, and the image matrix's pinned
  key list. The equality guards and the matrix's own refusal rows for those keys change with them.

The fresh sign-in is the check this merge needs and a signed-in session cannot see, so it runs after
the merge from a new browser profile, and is not waived. Every removed thing is proved gone
positively, not by its absence from a plan.

#### Acceptance Criteria:

- [ ] Before this merge opens: FR-001's and FR-003's live checks have passed against the first
      merge, and the rollback rehearsal, on the tag recorded in merge 1's PR, signed in through
      Amplify and listed files.
- [ ] `describe-user-pool-client` for the retired client's id fails with
      `ResourceNotFoundException`; `aws apigatewayv2 get-api` shows no `CorsConfiguration`; an
      `OPTIONS` to the API from the portal origin gets no `access-control-allow-origin`; the API
      function's configuration (`get-function-configuration`) carries an `OIDC_AUDIENCE` of exactly
      the server and dev client ids; and the running task definition has no `CONFIG_` entry for
      any of the six keys.
- [ ] `/config.json` on the deployed tier carries none of the six keys, and every wiring guard
      passes with all six removed.
- [ ] The router has no preflight branch, and an `OPTIONS` request in its tests gets the
      unauthenticated refusal.
- [ ] Through the verifier, a token for the retired client's id is refused with bytes identical to
      the no-token refusal, and tokens for the server and dev clients are accepted.
- [ ] The served policy's `connect-src` is exactly `'self'` and the two bucket endpoints, read off a
      response on the deployed tier, and the inverted test passes.
- [ ] After the merge, from a new browser profile, a sign-in completes and an upload succeeds.
- [ ] The CI plan for this merge shows the client's destroy and changes nothing in `session-store`,
      the buckets' CORS or the server or dev client.

### FR-006: The register and the guides say one session per browser

#### Description:

Each decision the charter assigns to this spec is rewritten in place with a dated History entry,
in the merge that makes its new claim true, and every other live site still stating the old claim
gets a supersede marker (`completion-ritual.md`).

- **Merge 1:** `identity-and-access/cognito-tokens-are-held-per-tab-not-per-browser` (one session per
  browser), `the-api-is-a-verifier-not-an-oidc-client` (its verifier half stands, and its "no
  cookie, so no CSRF surface" half now describes the API alone, with the server's cookie carrying
  SPEC-257's `Origin` check), `apirequest-retries-nothing-and-idempotency-is-declared-per-route`
  (no retry under any status, and the timeout now above the server's), `hosted-ui-managed-login-v2`
  (sign-in and sign-up go through `/auth/login`), and
  `the-provider-block-is-the-apis-verifier-configuration-and-it-is-server` (its Amplify passages).
  The `owed.md` row *What `setUnauthenticatedHandler` should DO* is closed with Andrew's answer.
- **Merge 2:** `identity-and-access/no-backend` (the browser reaches presigned bytes and its own
  origin, and nothing else), `infrastructure/connect-src-comes-from-the-task-definition-every-other-csp-directive-is`,
  `infrastructure/the-origins-are-admitted-additively-and-narrowed-only-at-the-cutover` (the API's
  CORS and the public client's lists retire, and the dev client holds the localhost callback), and
  `infrastructure/configuration-is-a-runtime-document-and-a-production-build-has-no` (the six keys
  leave the document and every wiring site).

The *Move between pages* guide's account-menu step gains one sentence, *"Signing in once covers
every Data Quarry tab in this browser, and Sign out signs out all of them."* The sweep found no
guide promising per-tab sign-in. The three shared-space sentences about refreshing access without
signing out, and about access lasting until a session refreshes (up to about an hour), stay true:
the server refreshes the ID token within its 60 minutes.

#### Acceptance Criteria:

- [ ] Each decision above carries a History entry dated by its merge, and a grep for `per tab`,
      `per-tab`, `Amplify` and `signInWithRedirect` across `docs/` and `apps/portal/info/` finds each
      remaining hit either marked superseded or describing history.
- [ ] The *Move between pages* guide carries the sentence, asserted by a test over `helpContent.ts`
      (no existing test pins real guide text).
- [ ] `python3 scripts/validate_docs.py` passes after each merge.

---

## Data Model

```ts
// apps/portal/src/features/auth/auth.types.ts — unchanged
export type AuthUser = {username: string; email?: string};

// apps/portal/src/lib/idToken.ts — same path and name, new result type
export function getIdToken(forceRefresh?: boolean): Promise<ServiceResult<void>>;

// apps/portal/src/server/session/cookies.ts (SPEC-257) — the names now depend on the build
export const SESSION_COOKIE = process.env.NODE_ENV === 'development' ? 'dq_session' : '__Host-dq_session';
export const SIGNIN_COOKIE = process.env.NODE_ENV === 'development' ? 'dq_signin' : '__Host-dq_signin';
```

## API / Interface Contract

```ts
// apps/portal/src/features/auth/auth.service.ts — same four exports, new transport
getCurrentAuthUser(): Promise<ServiceResult<AuthUser>>;   // GET /auth/session
startSignIn(): Promise<ServiceResult<void>>;              // saves the return path, assigns /auth/login
startSignUp(): Promise<ServiceResult<void>>;              // the same
startSignOut(): Promise<ServiceResult<void>>;             // POST /auth/logout, assigns logoutUrl

// apps/portal/src/lib/apiClient.ts — same signature; fetches `/api${path}${query}`, same-origin,
// sending `x-dq-user: <held username>`; TIMEOUT_MS = 45_000
apiRequest<R extends ApiRouteId>(route: R, ...args: ApiRequestArgs<R>): Promise<ServiceResult<ResponseOf<R>>>;
```

## Environment Variables

**Removed in merge 2 from the browser's document, `.env.example` and every other wiring site:**
`CONFIG_apiBaseUrl`, `CONFIG_appUrl`, `CONFIG_awsRegion`, `CONFIG_cognitoUserPoolId`,
`CONFIG_cognitoUserPoolClientId`, `CONFIG_cognitoDomain`.

**Written into `apps/portal/.env.local` by `npm run dev:session-env`** (SPEC-257's server variables,
for the dev client): `PORTAL_ORIGIN=http://localhost:5173`, `API_ORIGIN`, `OIDC_ISSUER`,
`OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, the four `OIDC_*_URL` fields, `SESSION_TABLE_NAME`,
`SESSION_MAX_AGE_SECONDS` and `AWS_REGION`.

## File & Folder Structure

```
apps/portal/
├── package.json                         # - aws-amplify; + dev:session-env
├── .env.example                         # + a pointer to dev:session-env; - the six CONFIG_ keys (merge 2)
├── scripts/dev-session-env.mjs          # new (FR-003)
├── scripts/assert-bundle-*.mjs          # + the Amplify marker (FR-004)
└── src/
    ├── PortalBoot.tsx                   # no Amplify configuration
    ├── instrumentation.ts               # + the session variables
    ├── features/auth/auth.service.ts    # rewritten over /auth/
    ├── features/auth/AuthProvider.tsx   # no Hub; ?signin=failed; registers the 401 handler
    ├── lib/amplify.ts                   # deleted
    ├── lib/idToken.ts                   # over POST /auth/refresh
    ├── lib/apiClient.ts                 # /api/, same-origin, x-dq-user, no retry, 45 s
    ├── lib/env.ts                       # - six dev-fallback entries (merge 2)
    ├── types/runtimeConfig.types.ts     # - six keys (merge 2)
    ├── app/api/[...path]/route.ts       # + the x-dq-user check (SPEC-257's handler)
    └── server/session/cookies.ts        # dev cookie names
infra/
├── modules/auth/                        # + dev client and dev-session parameter; then - public client
├── modules/api/apigateway.tf            # - cors_configuration (merge 2)
└── main.tf                              # verifier list; connect-src; the six keys' runtime map and outputs (merge 2)
lambdas/api/router.py                    # - the preflight branch (merge 2)
.github/config-outputs.json              # - six lines (merge 2)
.github/scripts/spa-image-matrix.sh      # + session fixture and refusal rows; - the six keys (merge 2)
.github/workflows/deploy-infra.yml       # branding: + dev client, then - public client
```

## Implementation Phases

### Phase 1: The first merge, which keeps the way back

- Read the deploy role's SSM grant as SPEC-257 landed it, and land any widening in its own PR
  first (FR-003). Record in merge 1's PR the image tag the service runs, which is the rollback.
- FR-001 to FR-004, and merge 1's decision rewrites and the Help sentence (FR-006). The dev client,
  its parameter and the verifier's third id are additive, and the six retiring keys stay wired,
  so this merge changes nothing the old path needs.
- Switch the web tier on through the repository variable and CI, run FR-001's and FR-003's live
  checks, and rehearse the rollback (FR-005). The tier stays on into Phase 2.

### Phase 2: The second merge, which removes it

- FR-005 and merge 2's decision rewrites. Run the fresh sign-in from a new profile and the
  positive proofs of removal, then switch the tier off through the repository variable and CI.
- The completion ritual, with `docs/testing/owed.md` rows for any live check that could not run.
