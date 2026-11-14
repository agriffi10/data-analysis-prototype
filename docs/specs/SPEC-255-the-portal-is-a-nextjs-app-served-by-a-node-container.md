---
type: Spec
id: SPEC-255
title: "The Portal Is a Next.js App Served by a Node Container"
description: "Moves the portal from a Vite build behind nginx and CloudFront to a Next.js app on a Node server: the existing app mounts client-only in one catch-all route, the server renders the runtime document and the per-request CSP, and the Fargate web tier becomes the only front door."
spec_status: Completed
depends_on: []
arc: nextjs
arc_order: 1
---

**Charter:** `docs/specs/ARCS.md`, *Next.js arc (SPEC-255 → 263)*. Its decisions are settled and
not restated here: a Node runtime, one codebase, shell first, the Fargate tier as the only front
door switched on only while working, and the server holding the session (257, not this spec).

**What was measured before this spec was written.** Next.js 16.4.6 was added to `apps/portal` in
a scratch worktree off `origin/main` at `45237489`, built, served from its standalone output and
from a container, and driven in a browser. Every design choice below that rests on Next's
behaviour rests on one of these runs; the full record is in the arc's shared notes as
`spec-255-measurements.md`. The ones that shaped a requirement:

- **`next build`'s own type check is vacuous here.** Next 16.4 runs the workspace's TS 7 binary as
  `tsc --project tsconfig.json`, and our root `tsconfig.json` is a solution file (`files: []` plus
  references), so a planted type error passed `next build` and `tsc -b` caught it.
- **A `?worker` import fails the Turbopack build.** `new Worker(new URL(…, import.meta.url))`
  builds, and Monaco's worker starts under `worker-src 'self' blob:` with no violation.
- **Turbopack supports `import.meta.env.DEV`, `PROD` and `MODE` natively** (the vendor reference
  shipped in `node_modules/next/dist/docs`), and does not support custom `VITE_*` names.
- **The optional catch-all answers a missing `/_next/static/…` chunk with a 200 `text/html` page.**
  A route handler at `src/app/%5Fnext/[...rest]/route.ts` restores an honest plain-text 404.
- **Response headers set by the request proxy override everything**, including a route handler's
  `Cache-Control` and Next's `immutable` on hashed assets.
- **A `throw` in `instrumentation.ts`'s `register()` leaves the server up answering 500 to every
  path**; `process.exit(1)` stops it. `next build` never runs `register()`.
- **react-router's push, Back and Forward inside the catch-all** neither reload the page nor re-run
  the boot: Next copies its own history state into react-router's entries, and `/config.json` was
  fetched once across the whole sequence.

## Overview

The client environment the portal is moving to requires Next.js. This spec moves the live portal
onto it without changing what any user sees: the whole existing application runs inside Next.js
exactly as it runs today, react-router and all, and the areas move onto the App Router in later
specs. What does change is what serves it. A Node server replaces nginx in the web tier's container:
it renders the runtime configuration document, refuses to start without it, and stamps every page
with a Content-Security-Policy carrying a fresh nonce. Because a Node app has no static fallback,
the CloudFront path that serves the portal while the web tier is switched off is retired, and the
tier becomes the only way the portal is served. With the tier off, the portal is down, as the
charter accepts.

## Scope

### In Scope

- Next.js 16.4.6 as the portal's build and server, with the existing app mounted client-only in
  one optional catch-all route and react-router left intact.
- The Vite-only constructs in production code replaced; Vite stays as Vitest's engine only.
- The runtime configuration document rendered by the Next.js server from the task environment, and
  a start-time refusal when a required value is unset, empty or unsafe.
- The request proxy: a per-request nonce in an enforcing CSP, the security headers on every
  response, the cache classes, the health route and an honest 404 for a missing hashed asset.
- A Node standalone image in place of the nginx one, its behaviour matrix rewritten against
  responses, and the task definition changed to match.
- The web tier as the only front door: the `static-portal` module, `deploy-spa-static.yml` and
  their guards deleted, the weekly ZAP scan made to skip loudly while the tier is off, and the
  deploy role's static-portal grant narrowed once the destroy has applied.
- The live checks below, run on the web tier switched on through CI and then switched off.
- The documents that describe what this replaces, brought up to date in the build:
  `apps/portal/info/runtime-configuration.md` (the wiring sites), the runtime-config boot-failure
  row of `docs/testing/owed.md` (whose procedure is nginx, `jq` and the entrypoint),
  `infra/modules/spa/README.md`, `docs/architecture.md`'s front-door passage, `docs/testing/e2e.md`'s
  container checks, `docs/process/ci-and-deploy-traps.md`'s wiring-site bullet, and
  `docs/security-baseline.md` for the Checkov removal.
- At completion, the decision rewrites the charter assigns to 255: under `infrastructure/`,
  `cloudfront-serves-the-portal-again-because-the-vpc-was-the-bill`,
  `the-nginx-configuration-reproduces-cloudfronts-jobs-and-three-are`, `response-headers-csp`,
  `the-image-is-the-file-set-which-retires-a-reconciliation-pass-and-an`,
  `connect-src-comes-from-the-task-definition-every-other-csp-directive-is`,
  `configuration-is-a-runtime-document-and-a-production-build-has-no` and
  `the-origins-are-admitted-additively-and-narrowed-only-at-the-cutover` (the development origin
  stays `localhost:5173` because the dev script pins Next's port); under `gates-and-tests/`,
  `security-scanning`; and `CLAUDE.md`'s Project Overview and Tech Stack rows.

### Out of Scope

- **Moving any area onto the App Router**, the navigation seam, hoisting providers into layouts
  and splitting the route table (256, 258–261). The boot stays a client component under the
  catch-all.
- **The server-held session** (257): no NAT gateway, no session store, no `/auth/` or `/api/`
  route handlers, no confidential client. The Next.js server in this spec makes no outbound call.
- **Removing Amplify, `apiBaseUrl` or the Cognito hosts from `connect-src`** (262).
- **Removing react-router** (263).
- **A holding page while the tier is off**, and any change to the tier's switch beyond what the
  retired static side leaves behind.
- **Brotli.** Next compresses with gzip per request, as nginx effectively did; the divergence from
  CloudFront stands and is restated, not fixed.
- **Renaming the test suite's `VITE_*` stubs.** About a hundred `vi.stubEnv('VITE_…')` call sites
  keep their names; under Vitest those names are still Vite's own, and only the dev server stops
  reading them.
- **Server rendering of any data**, any visual change and any API change.

---

## Functional Requirements

### FR-001: The portal builds and serves on Next.js, with the existing app mounted client-only

#### Description:

`apps/portal` builds with `next build` and serves with Next's standalone server. Following Next's
Vite migration guide, a root layout replaces `index.html`, and one optional catch-all route,
`src/app/[[...slug]]/page.tsx`, renders a client component that loads the boot through
`next/dynamic` with `ssr: false`, so no module of the application graph is evaluated on the server.
The boot keeps today's order: fetch `/config.json`, configure Amplify, then import `AppRoot`
(`BrowserRouter` and everything inside it) and render it, or render `BootFailure` with the one
console line naming the reason. `main.tsx` and `index.html` are deleted, and the boot's
static-import sweep moves to the new boot module. The root layout, not the boot, imports
`index.css`, so the stylesheet is linked in the server's HTML rather than injected after the boot;
the guard that pins the one stylesheet import (`colourLiterals.test.ts`) follows it there. The
layout's `<html>` carries `suppressHydrationWarning`, because `theme-init.js` stamps `data-theme`
on it before hydration and React otherwise reports the mismatch (measured under `next dev`).

`npm run build` is `tsc -b && next build`, and `next.config.ts` sets
`typescript.ignoreBuildErrors: true`, because the measured `next build` check reads the solution
file and checks nothing; `tsc -b` stays the type gate. The root layout opts every route into dynamic
rendering (`export const dynamic = 'force-dynamic'`), which the charter requires so that every page
carries a nonce. `npm run dev` runs `next dev --port 5173`, so the development origin that Cognito's
callback list and both buckets' CORS rules already admit does not change. `next.config.ts` also sets
`output: 'standalone'`, `outputFileTracingRoot` at the repository root, `poweredByHeader: false`
and `agentRules: false` (measured: without it `next dev` writes an `AGENTS.md` into the app).

#### Acceptance Criteria:

- [ ] `npm run build -w apps/portal` exits 0, and its route table lists `/[[...slug]]`,
      `/config.json`, `/healthz`, `/_next/[...rest]` and `/_not-found`, every one marked dynamic.
- [ ] A type error planted in a file under `src/app/` makes `npm run build` exit non-zero from
      `tsc -b`; reverted, it exits 0.
- [ ] `apps/portal/index.html` and `apps/portal/src/main.tsx` do not exist, and no file under
      `apps/portal/src` imports from `vite` or `vite/client` outside test files and `*.d.ts`.
- [ ] The boot's test renders the boot module and asserts the order configure-then-render, that
      `AppRoot` is never evaluated when the document fails to load, and that a failed dynamic import
      renders `BootFailure`; its static-import sweep reads the boot module and fails if the set grows.
- [ ] The page module imports nothing from `src/features/`, `src/components/`, `src/routes/` or
      `AppRoot` statically: the only path from the route to the application graph is the
      `ssr: false` dynamic import (asserted by a source sweep over the `[[...slug]]` directory).
- [ ] `npm run dev` serves the portal at `http://localhost:5173`, and a sign-in through the Hosted
      UI returns to it (live, on a developer's machine with `.env.local` filled in).
- [ ] **Live:** on the deployed tier, a deep link to `/files` loads the app signed in; a reload of
      `/query` keeps the user on `/query`; and after navigating Files → Query → Explore through the
      app's own links, Back and then Forward change the page without a document reload and without
      a second request for `/config.json` (Resource Timing shows one).
- [ ] `.next/` and `next-env.d.ts` are gitignored, and ESLint and Prettier ignore `.next/`.

### FR-002: The Vite-only constructs are replaced

#### Description:

Production code stops depending on anything only Vite provides. Monaco's editor worker is created
with `new Worker(new URL('monaco-editor/editor/editor.worker', import.meta.url), {type: 'module'})`
in place of the `?worker` import. Tailwind v4 runs through `@tailwindcss/postcss` in a
`postcss.config.mjs` instead of `@tailwindcss/vite`; the Google Fonts `@import` in `index.css`
stays as it is, measured to survive the build unchanged. `public/theme-init.js` stays an external
blocking script in `<head>` and now carries the request's nonce; its comment stops claiming the
policy has no nonce.

The `VITE_*` fallback becomes the test runner's alone. Today it answers whenever
`import.meta.env.DEV` is true, which under `next dev` would read names Turbopack does not supply
and warn about every one. It now answers only when `import.meta.env.MODE === 'test'`, and so does
the loader's tolerance of a failed load; `warnIfMisconfigured` retires, because the server's
start-time refusal (FR-003) names the missing variables to a developer at `npm run dev`.
`import.meta.env.DEV` itself stays wherever it guards a dev-only diagnostic: Turbopack supports it
natively, so it is no longer a Vite-only construct. `apps/portal/.env.example` documents the
server's variables, `CONFIG_<key>` and `PORTAL_CSP_CONNECT_SRC`, for `.env.local`, with the
measured dotenv trap: a single-quoted `'self'` loses its quotes and becomes a host named `self`.

`npm run check:bundle` keeps its rule, that no `VITE_` name survives in the browser bundle, and
reads `.next/static/` instead of `dist/assets/`, failing hard when that directory is missing or
holds no JavaScript.

#### Acceptance Criteria:

- [ ] No file under `apps/portal/src` outside tests contains `?worker`, `?raw` or `?url`, and
      `SqlEditor.test.tsx` carries no mock of a worker path.
- [ ] `npm run check:bundle` exits 0 after `npm run build`; with a planted unguarded
      `devFallbackValue('appUrl')` call in a module the app imports (which keeps the `VITE_` name
      table alive in the bundle, the thing the script is documented to catch) it exits non-zero
      naming a `VITE_` name; with `.next/static` removed it exits non-zero.
- [ ] A unit test with `MODE` stubbed to `production` asserts that a configuration read before
      the document loads throws `RuntimeConfigNotLoadedError`, and one with `MODE` stubbed to
      `development` asserts the same, so the fallback cannot answer under `next dev`.
- [ ] The existing suites that read configuration through `vi.stubEnv('VITE_…')` pass unchanged
      in their stubs.
- [ ] `apps/portal/package.json` no longer lists `@tailwindcss/vite`, and lists `next` at exactly
      `16.4.6`, `@tailwindcss/postcss` at exactly `4.3.3` and `server-only` at exactly `0.0.1`.
- [ ] **Live:** on the deployed tier, the Query page's editor opens, highlights SQL and runs a
      statement, and the page records no `securitypolicyviolation` event while it does.
- [ ] **Live:** with the dark theme saved, a hard reload of `/files` paints dark from the first
      frame (no light flash), and the Inter typeface is applied (`document.fonts` reports it loaded).

### FR-003: The server renders the runtime document and refuses to start without it

#### Description:

`src/server/runtimeDocument.ts` (beginning `import 'server-only'`) builds the document from the
task environment: `{version: 1}` plus one key per entry of the browser's own classification,
`REQUIRED_CONFIG` and `OPTIONAL_CONFIG` in `src/types/runtimeConfig.types.ts`, read from
`CONFIG_<key>`, with empty values dropped. It reads the named keys only, never a `CONFIG_*` sweep,
because the document is world-readable. The route handler `src/app/config.json/route.ts` serves it
as JSON with `Cache-Control: no-store`. Reading the classification the browser reads collapses two
of today's five wiring sites (the classification and the entrypoint's own `KEYS`/`REQUIRED` lists)
into one. The four left are the classification, `apps/portal/.env.example` (now its `CONFIG_`
names), `.github/config-outputs.json` with its genuine inputs, and Terraform's runtime map. Because
the server imports the classification, the risk that replaces the entrypoint's drift is the server
module growing a key list of its own, and that is what its guard asserts against.

`src/instrumentation.ts` checks the environment once at server start, on the Node runtime only.
Every required `CONFIG_<key>` that is unset or empty, and `PORTAL_CSP_CONNECT_SRC` when it is unset,
empty or carries a character outside the CSP source-list allowlist the entrypoint uses today
(`A–Z a–z 0–9 ' : / . space _ * -`), is collected and reported together on stderr by variable name,
never by value, and the process exits 1. It exits rather than throws, because a throw was measured
to leave a server answering 500 to every path, which a load balancer probes as an unhealthy target
indefinitely rather than as a task that stopped. The check runs under `next dev` too, so a developer
missing a variable hears its name at start.

#### Acceptance Criteria:

- [ ] With every required variable set, `GET /config.json` answers 200, `application/json`,
      `Cache-Control: no-store`, and a body of exactly `version` plus each key whose `CONFIG_`
      variable is set and non-empty, and nothing else: a `CONFIG_notAKey` in the environment does
      not appear.
- [ ] A value carrying a double quote and a backslash round-trips through the document byte for
      byte.
- [ ] With one required variable unset, the server exits 1 within ten seconds and stderr names it;
      the same holds with it set to the empty string; with two unset, one run names both.
- [ ] With `PORTAL_CSP_CONNECT_SRC` unset, empty, or carrying `"` or `;`, the server exits 1 and
      stderr names `PORTAL_CSP_CONNECT_SRC`; no stderr line in any refusal contains a variable's value.
- [ ] `next build` with no `CONFIG_` variable set exits 0 (the check is start-time only).
- [ ] The guards that compared the entrypoint's lists now compare the four remaining sites: a key
      planted in the classification alone fails them, and so does one planted in `.env.example`
      alone (the `.env.example` check in `runtimeConfig.test.ts` reads `CONFIG_` assignments).
- [ ] `src/server/runtimeDocument.ts` contains no string literal naming a configuration key, and a
      guard fails when one is planted there.
- [ ] **Live:** on the deployed tier, `/config.json` carries the production values and the portal
      boots signed in.

### FR-004: The request proxy owns the nonce, the security headers and the cache classes

#### Description:

`src/proxy.ts` runs on every request that carries no body. It mints a nonce from 16
cryptographically random bytes, base64-encoded, and builds the policy in
`src/server/contentSecurityPolicy.ts`: today's directives
unchanged except `script-src 'self' 'nonce-<nonce>'`, with `'unsafe-eval'` added only when
`NODE_ENV` is `development` (React's dev build needs it, and production does not), and
`connect-src` taken from `PORTAL_CSP_CONNECT_SRC` at request time. `style-src` carries no nonce,
because a nonce switches off `'unsafe-inline'`, which Monaco's injected styles need. The proxy sets
the policy and `x-nonce` on the request, overwriting anything the client sent under those names, so
Next stamps the nonce on every script and stylesheet it emits and the root layout reads it for
`theme-init.js`; it sets the policy and the security headers on the response: HSTS without
`preload`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, the current `Permissions-Policy`
list, COOP and CORP, and still no COEP.

**A request carrying a body never reaches the proxy.** When the proxy matches such a request, Next
clones the body for it and then awaits the whole body before any page or handler answers
(`finalize()` in `next-server.js`, in a `finally`, whatever the proxy returns), so a client that
declares a 1 GB body and sends one byte held every path, `/healthz` included, with no answer in six
seconds (measured, after the SPEC-257 session found it). `proxyClientMaxBodySize` caps only how much
is buffered, not how long the connection waits. So the proxy's matcher is `/:path*` with
`missing` conditions on `Content-Length` and `Transfer-Encoding`, and `next.config.ts`'s `headers()`
gives exactly those requests a floor: the same seven security headers and a lockdown policy
(`default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`), because no
page takes a body and none should run script for one. Measured, the same 1 GB declaration is
answered in milliseconds on every path, and a body-less GET still carries exactly one policy, the
proxy's. The residual is a body-less GET that a client sends with `Content-Length: 0`: it gets the
lockdown policy and a page that cannot boot, which no browser does on its own.

The nonce-free definitions, the seven headers and the lockdown policy, live in one plain module,
`src/lib/securityHeaders.ts`, that the proxy and `next.config.ts` both import. It does not import
`server-only`, because `next.config.ts` runs in plain Node and a server-only import fails the build
there (measured by the SPEC-257 session; 255 measured the package's throw under Vitest). The
nonce-carrying policy builder is `src/server/contentSecurityPolicy.ts`, which does begin with
`import 'server-only'` and is imported by the proxy alone (measured to build and serve). These are
the two paths the SPEC-257 spec names: its nonce-free headers for `/api/` and `/auth/` import the
first.

The proxy sets no `Cache-Control`, because a header it sets overrides every other source. Each class
takes its value from its owner: Next marks pages `private, no-cache, no-store, max-age=0,
must-revalidate` and hashed assets `public, max-age=31536000, immutable`, serves `public/` files
`public, max-age=0`, and the three route handlers set `no-store`. `src/app/healthz/route.ts` answers
`200 text/plain` `ok`. `src/app/%5Fnext/[...rest]/route.ts` answers any `/_next/` path that matched
no built file with `404 text/plain`, where the catch-all would otherwise answer 200 with the app
shell.

The proxy is now the one home of the policy's bundle directives. Terraform's root
`content_security_policy` local loses its last consumer with the distribution and is deleted;
`csp_connect_src` stays at root and reaches the container as today. Two Python guards parse that
local and go with it: `lambdas/test_csp_policy.py`'s byte-identity test, which holds today's
directives as a recorded literal (`ACCEPTED_PRE_MOVE_DIRECTIVES`) with its separator, and
`test_spa_image.py`'s baked-policy test. The file's other two tests stay, because their subject
outlives the local: that `csp_connect_src` still names both Cognito hosts, and the parser's own test.
The recorded literal and the separator move into the TypeScript test of
`contentSecurityPolicy.ts`, with `script-src` the one directive allowed to differ; an expectation
re-derived from the module itself would only assert that the file equals itself.

#### Acceptance Criteria:

- [ ] Two requests for `/` carry different nonces; in each, the HTML holds at least one
      `<script>` and at least one `<link rel="stylesheet">`, every one of them carries exactly the
      nonce in that response's policy, and the `theme-init.js` script is among them.
- [ ] A request sending its own `x-nonce` and `Content-Security-Policy` headers gets a page whose
      nonce is not the one it sent.
- [ ] The production policy's `script-src` is exactly `'self' 'nonce-<nonce>'`; the development
      policy's adds `'unsafe-eval'`; `style-src` carries no `nonce-` source in either; every other
      directive equals the literal carried over from `test_csp_policy.py`, in order, with the join
      separator asserted too; and `test_csp_policy.py` no longer holds the literal or its
      byte-identity test, while its Cognito-host and parser tests still pass.
- [ ] Every response class in FR-005's matrix carries the policy and all seven security headers,
      none carries `X-Powered-By`, `Server` or `Cross-Origin-Embedder-Policy`, and HSTS carries no
      `preload`.
- [ ] Cache classes, read off responses: the shell and a deep link as Next's page class, a hashed
      asset `immutable`, `theme-init.js` `public, max-age=0`, and `/config.json`, `/healthz` and a
      missing `/_next/static/chunks/x.js` `no-store`; the last answers 404 with a non-HTML type.
- [ ] `/healthz` answers 200, `text/plain`, body exactly `ok`.
- [ ] A request declaring `Content-Length: 1073741824` and sending one byte, and one sending a
      chunked body that never ends, are each answered within one second on `/`, `/files`,
      `/config.json`, `/healthz` and a missing `/_next/static` chunk, with the seven security
      headers and the lockdown policy; and a planted matcher without the `missing` conditions makes
      the same check fail.
- [ ] A body-less GET of `/` carries exactly one `Content-Security-Policy` header.
- [ ] `infra/main.tf` has no `content_security_policy` local, and still builds `csp_connect_src`
      with the Cognito User Pool host and the Hosted UI host as separate, named entries.
- [ ] **Live:** on the deployed tier, an evaluated `fetch` to a host outside `connect-src` raises a
      `securitypolicyviolation` with `effectiveDirective` `connect-src` and `disposition`
      `enforce`, and a same-origin `fetch('/healthz')` in the same run succeeds.
- [ ] **Live:** a fresh sign-in in a new browser profile completes (the Hosted UI token exchange is
      the one fetch a warm session never makes), and a file upload to the user's space succeeds.

### FR-005: The image is a Node standalone server, and its behaviour matrix asserts it

#### Description:

`apps/portal/Dockerfile` builds in a `node:24-bookworm-slim` stage pinned by the digest already in
use (`npm ci`, `npm run build -w apps/portal`, the build-context assertions kept), and runs from the
same pinned base: the standalone output, `.next/static` and `public/` copied in, `NODE_ENV=production`,
`PORT=8080`, `HOSTNAME=0.0.0.0`, `NEXT_TELEMETRY_DISABLED=1`, the `BUILD_VERSION` label and variable
kept, `USER 1000`, and `node apps/portal/server.js` as the command. The nginx configuration, its
templates, the entrypoint script and the `jq` stage are deleted; `PORTAL_LOG_LEVEL` retires.
`.dockerignore` excludes `**/.next`. The task definition runs as uid `1000` with a read-only root
filesystem and one tmpfs at `/tmp` (the `/var/cache/nginx` mount goes), on port 8080 with the
`/healthz` health check unchanged.

`.github/scripts/spa-image-matrix.sh` is rewritten to assert the container on responses, as
before: the image's static properties, every response class with its status, type, cache class and
security headers, the document, the refusals, and that one digest emits a second environment's
`connect-src`. `spa-image.yml` runs it on every pull request that touches the portal, and
`deploy-spa-image.yml` runs it before pushing.

#### Acceptance Criteria:

- [ ] Every `FROM` in the Dockerfile is pinned by digest, the image's configured user is `1000`,
      and the image holds no `.env` file, no `.git`, no test file, no `next-env.d.ts` and no source
      under `src/`.
- [ ] Run with `--read-only`, `--user 1000` and one tmpfs at `/tmp`, the container serves every
      class in FR-004's cache list and writes nowhere else (no write error in its log).
- [ ] The matrix asserts, by response: the shell and a deep link 200 HTML; a hashed asset 200 and
      gzip-encoded when asked, never brotli; a missing hashed asset 404 non-HTML; `/config.json`'s
      exact key set and version 1; `/healthz`; `theme-init.js`; and a removed root-level file
      answering 200 HTML, pinned as the catch-all's preserved trap; and FR-004's bodied-request
      check, so the bound is proven on the image that ships.
- [ ] The matrix asserts each FR-003 refusal as a container that exits non-zero naming the
      variable, and that one image digest emits each of two `PORTAL_CSP_CONNECT_SRC` values.
- [ ] `docker stop` stops the container within three seconds, and the image's revision label
      equals `BUILD_VERSION`.
- [ ] `spa-image.yml` is green on the pull request.
- [ ] **Live:** after the tier is switched on, `deploy-spa-image.yml` builds `main`, its matrix is
      green, and the service settles on that revision with its target healthy.

### FR-006: The web tier is the only front door, and the static path is retired

#### Description:

`infra/modules/static-portal`, its module block in `infra/main.tf`, `deploy-spa-static.yml` and
`lambdas/test_static_portal_module.py` are deleted, and every workflow and guard that referred to
them stops doing so (`deploy-infra.yml` names the static side only in comments). The module test's
one assertion that outlives it, that `network` and `spa` are both counted on `web_tier_enabled`,
moves into a web-tier test, since no other guard holds it. Switching the tier off now removes
`network` and `spa` and builds nothing in their place. The pull request is planned and merged with
the tier off, as it is today, so its plan shows the static side's destroy and nothing under
`module.spa`.

The ten IDs `.github/checkov-enforced.txt` gained when CloudFront came back leave it in the same
change: the nine CloudFront checks and `CKV_AWS_70`, whose one evaluated resource is the portal
bucket's policy (the file's header records both the addition and, from the last retirement, that
`CKV_AWS_70` went with the distribution). The list is re-measured with the regeneration command
the header gives, because an enforced ID that matches nothing is a
hard error. `docs/security-baseline.md` records the removal, which that file's header requires. `infra/info/web-tier.md` is rewritten
for a switch with one side: off means the portal does not resolve, and on means the apply and
then the image deploy. It also records a trap the retirement creates. The portal's certificate
stays outside the switch, but with the distribution gone it is in use only while the load balancer
exists, and ACM renews a certificate only while it is in use, starting 60 days before it expires.
So the page says how to read the certificate's expiry (`aws acm describe-certificate`), that the
tier must be switched on inside that window for the renewal to happen, and that a certificate which
lapsed while the tier was off must be re-issued by a reviewed infrastructure change (`deploy-infra.yml`
has no replace input today) before the tier can serve.

The weekly ZAP baseline has no target while the tier is off. Its job reads
`vars.TF_VAR_web_tier_enabled`: when it is `false` it skips the scan with a `::warning` annotation and
a job-summary section stating that nothing was scanned because the web tier is off, and the job
stays green; any other value scans as today. A scan dispatched while the tier is on is the way to
get a baseline, and this spec's live check dispatches one.

The deploy role's grant for the static portal (`modules/base/iam.tf` and its policy template) and
the two `.github/checkov-plan-accepted.txt` entries it carried are removed in a separate pull request
after the destroy has applied, because the destroy needs those permissions and Terraform would
otherwise apply the narrowing and the destroy in parallel.

#### Acceptance Criteria:

- [ ] `git grep` for `static-portal`, `static_portal` and `deploy-spa-static` outside `docs/specs/`,
      `docs/spec-delivery/` and History entries returns only supersede markers.
- [ ] Planned with the tier off, the pull request's infrastructure plan destroys only resources
      under `module.static_portal[0]` and changes nothing else.
- [ ] A web-tier test asserts that `network` and `spa` are both counted on `web_tier_enabled`,
      and fails when either count is planted to a constant.
- [ ] `checkov-enforced.txt` lists none of the ten IDs and no ID that now evaluates nothing, the
      Checkov job is green, and `docs/security-baseline.md` records the removal.
- [ ] `infra/info/web-tier.md` names the certificate's renewal-while-in-use window, the command
      that reads its expiry, and the recovery for one that expired while the tier was off.
- [ ] A `security.yml` run with the tier variable `false` ends green, carries the warning
      annotation and the summary section, and starts no ZAP container; the skip compares against
      the exact string `false`, as Deploy SPA image does, so a `0` scans rather than skips.
- [ ] After the narrowing pull request, the deploy role holds no CloudFront or static-bucket grant,
      and its plan touches exactly `module.base.aws_iam_policy.deploy_portal_static` and
      `module.base.aws_iam_role_policy_attachment.deploy_portal_static` (destroyed) and `module.base.time_sleep.wait_for_platform_grant` (replaced,
      because its triggers name that policy).
- [ ] **Live:** with the tier switched on through CI, `https://portal.dataquarry.app` is served by
      the Next.js container; with it switched off again through CI, the host does not resolve
      after the negative-caching window and every resource under `module.network` and
      `module.spa` is gone from the apply's log.
- [ ] **Live:** one `security.yml` dispatch while the tier is on scans the Next.js server, and its
      alerts are diffed per alert ID against `docs/security-baseline.md`, with each new one fixed or
      recorded there.

---

## Data Model

The document's shape does not change; the server now reads the type the browser reads.

```ts
// src/types/runtimeConfig.types.ts — unchanged, now imported by the server too
export const REQUIRED_CONFIG = ['apiBaseUrl', 'appUrl', 'awsRegion', 'userSpaceBucket',
  'cognitoUserPoolId', 'cognitoUserPoolClientId', 'cognitoDomain'] as const;
export const OPTIONAL_CONFIG = ['environment', 'maxUploadBytes', 'sharedSpaceBucket'] as const;
export type RuntimeConfigDocument = {version: number} & Partial<Record<RuntimeConfigKey, string>>;
```

```ts
// src/server/runtimeDocument.ts
import 'server-only';

/** One reason the server will not start, named by variable and never by value. */
export type StartupProblem = {
  variable: string;
  reason: 'unset-or-empty' | 'invalid-characters';
};
```

---

## API / Interface Contract

```ts
// src/server/runtimeDocument.ts
export function renderRuntimeDocument(env?: NodeJS.ProcessEnv): RuntimeConfigDocument;
export function startupProblems(env?: NodeJS.ProcessEnv): StartupProblem[];

// src/server/contentSecurityPolicy.ts — imported by src/proxy.ts only
import 'server-only';
export function newNonce(): string; // 16 random bytes, base64
export function contentSecurityPolicy(options: {
  nonce: string;
  connectSrc: string;
  development: boolean;
}): string;

// src/lib/securityHeaders.ts — imported by src/proxy.ts and next.config.ts; no 'server-only'
export const SECURITY_HEADERS: Readonly<Record<string, string>>; // the seven, no CSP
export const LOCKDOWN_POLICY: string; // the floor's policy for a request with a body

// src/proxy.ts
export function proxy(request: NextRequest): NextResponse;

// src/instrumentation.ts — exits 1 on any StartupProblem, on the Node runtime only
export async function register(): Promise<void>;

// src/app/config.json/route.ts, src/app/healthz/route.ts, src/app/%5Fnext/[...rest]/route.ts
export function GET(): Response;
```

The boundary the charter fixes: nothing under `src/features/`, `src/components/` or `src/lib/`
imports `src/server/`, held by an ESLint `no-restricted-imports` clause and its shape test. The
Vitest configuration aliases `server-only` to the package's `empty.js`, because its default export
throws outside a server bundle (measured), so the server modules' own tests can import them.

## Environment Variables

The server's, set in the task definition and, for `next dev`, in `apps/portal/.env.local`:

```
CONFIG_<key>=…                     # one per classified key, unchanged names
PORTAL_CSP_CONNECT_SRC="'self' …"  # unchanged; double-quote it in .env.local
```

The image's own: `NODE_ENV=production`, `PORT=8080`, `HOSTNAME=0.0.0.0`,
`NEXT_TELEMETRY_DISABLED=1`, `BUILD_VERSION`. Retired: `PORTAL_LOG_LEVEL`, and the `VITE_*` entries
of `.env.example` (the names survive only as the test suite's stubs).

## File & Folder Structure

```
apps/portal/
├── next.config.ts                     new
├── postcss.config.mjs                 new
├── Dockerfile                         rewritten
├── docker/                            deleted
├── index.html                         deleted
├── vite.config.ts                     Vitest only: no Tailwind plugin, a server-only alias
├── scripts/assert-bundle-has-no-vite-names.mjs   reads .next/static
└── src/
    ├── main.tsx                       deleted
    ├── PortalBoot.tsx                 new: the boot, from main.tsx
    ├── bootstrap.test.tsx             rewritten against PortalBoot
    ├── proxy.ts                       new
    ├── instrumentation.ts             new
    ├── lib/securityHeaders.ts         new: the nonce-free headers, shared with next.config.ts
    ├── server/
    │   ├── runtimeDocument.ts         new
    │   └── contentSecurityPolicy.ts   new: the nonce-carrying policy
    └── app/
        ├── layout.tsx                 new: the root layout, from index.html
        ├── [[...slug]]/page.tsx       new
        ├── [[...slug]]/PortalMount.tsx  new: 'use client', ssr: false
        ├── config.json/route.ts       new
        ├── healthz/route.ts           new
        └── %5Fnext/[...rest]/route.ts new
.github/workflows/deploy-spa-static.yml      deleted
.github/scripts/spa-image-matrix.sh          rewritten
infra/modules/static-portal/                 deleted
lambdas/test_static_portal_module.py         deleted (its switch-count assertion moves to a web-tier test)
lambdas/test_csp_policy.py                   loses its byte-identity test (its recorded directives move to the TypeScript test)
lambdas/test_spa_image.py                    rewritten for the Node image
lambdas/test_config_outputs.py               compares the four remaining wiring sites
```

## Implementation Phases

### Phase 1: The toolchain and the client-only mount

- Add `next`, `@tailwindcss/postcss` and `server-only`; drop `@tailwindcss/vite`; write
  `next.config.ts` and `postcss.config.mjs`; reduce `vite.config.ts` to Vitest's needs.
- Write the root layout, the catch-all page and its client mount, and `PortalBoot.tsx`; delete
  `main.tsx` and `index.html`; retarget the boot test and every guard that read them.
- Replace the worker import, gate the fallback on `MODE`, rewrite `.env.example`, retarget
  `check:bundle`, and update ignores.

### Phase 2: The server

- `src/server/runtimeDocument.ts`, the `/config.json` route and the start-time refusal.
- `src/lib/securityHeaders.ts`, `src/server/contentSecurityPolicy.ts`, the proxy with its
  body-less matcher, the `next.config.ts` floor, the health route and the `/_next/` 404.
- The ESLint clause for `src/server/` and the Vitest alias; delete the root
  `content_security_policy` local; retarget the wiring-site guards.

### Phase 3: The image

- Rewrite the Dockerfile, delete `docker/`, add `**/.next` to `.dockerignore`.
- Change the task definition's user and mounts; rewrite the behaviour matrix.

### Phase 4: The static path retired

- Delete the module, the workflow and the module test, moving its switch-count assertion into a
  web-tier test; update `deploy-infra.yml`'s comments, the enforced Checkov list with its baseline
  entry, the ZAP job, `web-tier.md` and the documents In Scope names.

### Phase 5: After the destroy has applied

- Narrow the deploy role's static-portal grant and its two accepted Checkov entries.
- Switch the tier on through CI, run the live checks, dispatch the ZAP scan, and switch it off.
