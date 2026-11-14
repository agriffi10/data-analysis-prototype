---
type: Decision
title: "Configuration is a runtime document, and only the test runner has a fallback (SPEC-192, SPEC-255)"
description: "**Configuration is a RUNTIME document** (`/config.json`, rendered per request by the Next.js server, `no-store`, refused whole on version) with **no fallback outside the test runner** (`MODE === 'test'`). Its key set is wired in **four** places, asserted across all, and the server **exits 1 at start** naming a required variable unset or empty: it exits rather than throws, because a throw leaves a server answering 500 to every path. **The deploy READS the values from Terraform state** through `.github/config-outputs.json`, refusing an absent *or empty* output by name; only a genuine **input** is a repository variable, so retiring an origin means **re-pointing that map**. The API's **verifier** config is server-side, never in the browser's document — and the exclusion cuts one way: a rule forbidding \"anything identity-shaped\" takes Amplify's own Cognito keys with it."
---

The browser reads `/config.json` at startup instead of the `VITE_*` values Vite inlined at build
time. The whole point is promotion: an artifact carrying one environment's bucket names and Cognito
ids can only reach the next environment through a rebuild, and a rollback through a rebuild of an
older commit. Every value is a **string** — the task environment that renders the document is
strings, and a JSON number would add a second parse path with its own failure mode for one key. The
key set was twenty when this was written and is **ten** now: the browser's control-plane enqueues
moved behind the API, so the eight queue URLs became the API function's configuration and left the
document entirely.

**The Next.js server renders the document, from the classification the browser reads.**
`src/server/runtimeDocument.ts` builds `{version: 1}` plus one key per entry of `REQUIRED_CONFIG` and
`OPTIONAL_CONFIG`, read from `CONFIG_<key>`, empty values dropped, and the route handler
`src/app/config.json/route.ts` serves it. It reads the named keys only, never a `CONFIG_*` sweep,
because the document is world-readable, and a guard fails if the module grows a key list of its own,
which is the drift that replaced the entrypoint's.

**A key is wired in four places, and a test compares them**: the classification in
`types/runtimeConfig.types.ts`, `apps/portal/.env.example` under its `CONFIG_` name, its source —
`.github/config-outputs.json` for a value Terraform computes, a repository variable for a genuine
input — and the task definition's `local.spa_runtime_config` at root. The full list and its reasons
are `apps/portal/info/runtime-configuration.md`; *A value Terraform computes is read from state, never
copied into a settings page* is the entry for the third site.

**The server refuses to start without its configuration.** `src/instrumentation.ts` runs once at
server start, on the Node runtime only: every required `CONFIG_<key>` unset or empty, and
`PORTAL_CSP_CONNECT_SRC` unset, empty or outside its allowlist, is reported together on stderr **by
variable name, never by value**, and the process **exits 1**. It exits rather than throws, because a
throw there was measured to leave a server up answering 500 to every path, which a load balancer
probes as an unhealthy target indefinitely rather than as a task that stopped. It runs under
`next dev` too, so a developer missing a variable hears its name; `next build` never runs it.

**Only the test runner has a fallback, and `configValue` THROWS before the load resolves anywhere
else.** Returning `undefined` is the failure the classification exists to prevent — a generic SDK
error about a bucket named "undefined", surfacing far from its cause. Vitest has no server, so under
`import.meta.env.MODE === 'test'` a read answers from `import.meta.env`, which is what lets the suite
read configuration with no bootstrap and without changing a single `vi.stubEnv('VITE_…')` call site.
`next dev` and a production build both read the document: Turbopack supplies no custom `VITE_*` name,
so a development fallback would read nothing and warn about every key. The consequence is that **the
suite exercises an arm that exists nowhere else**, which is why unit tests stub `MODE` to
`production` and to `development` and assert the throw, and why the live checks are not optional.

**The fallback is ELIMINATED from the browser bundle, and that is asserted on the built output.**
Guarding it is not enough: `readEnv`'s table and the key-to-variable map are tables of `VITE_` names as
*strings*, and they disappear only if every reference to them sits inside a branch the build drops.
`npm run check:bundle` fails if any `VITE_` name survives in `.next/static/`, and it hard-fails when
that directory is missing or holds no JavaScript, because "did not run" is never "clean". It detects
the *table*, not an unported call site, so a source sweep pins separately which files may call it.

**A 200 carrying HTML is `unparseable`, not a success.** The optional catch-all answers any path no
route matched with the app shell under a 200, so a server that lost its `/config.json` route would
hand the loader a successful response full of markup. A loader keyed on `response.ok` passes every
other test and fails that one; the fixture is a markup string.

**The document and the feature-flag document look alike and their failure semantics are OPPOSITE.**
The flag document's degraded path is total and silent by design — an unusable one resolves the
compiled-in defaults and still reports ready. This one is a **hard boot failure**: `BootFailure`
renders, no route mounts, and one `console.error` carries the reason and, for a missing required key,
the key **NAMES** — never a value. That narrows the "production stays silent" rule deliberately: the
rule exists so a deployed app does not print its configuration, and a key name is not configuration,
it is the only diagnostic an operator staring at a failed boot has.

**`no-store` is the route handler's, and nothing may override it.** A document answered from a cache
populated in the previous environment renders a working, fully functional portal pointed at the wrong
account, and nothing on screen distinguishes it. The handler sets `Cache-Control: no-store`; the
request proxy sets no `Cache-Control` of its own, because one it set would replace the handler's; and
the image's behaviour matrix reads the header off a response.

**The boot is a DYNAMIC import, behind a client-only mount.** A module's static imports are evaluated
before its first statement runs, so a static import of the app would evaluate the whole application
graph before the document is fetched, and any module-scope read in it would throw before the app
could render its own failure — in production only, because the test runner's fallback answers. The
catch-all route's `PortalMount` loads `src/PortalBoot.tsx` through `next/dynamic` with `ssr: false`,
so no module of the app is evaluated on the server; the boot fetches the document, configures Amplify,
and only then reaches the app through `await import('./AppRoot')`, and a sweep fails if its static
imports **grow**. A **deadline** on the fetch ships with it, because nothing renders until the load
settles, and an origin that accepts the connection and never answers would otherwise be a blank page
with an empty console.

Detail: `spec-delivery/SPEC-192` and `spec-delivery/SPEC-255`.

## History

### 2026-11-13

- **Changed:** SPEC-255. The Next.js server renders the document per request from the browser's own
  classification, so the nginx entrypoint's key lists left and the wiring sites went from five to
  four. The start-time refusal moved to `src/instrumentation.ts` and exits rather than throws. The
  fallback became the test runner's alone (`MODE === 'test'`), because Turbopack supplies no `VITE_*`
  name under `next dev`. `check:bundle` reads `.next/static/`, the boot moved from `main.tsx` to
  `PortalBoot.tsx` behind a client-only mount, and the 200-with-HTML case is live again through the
  optional catch-all.

### 2026-09-14

- **Changed:** Marked for SPEC-194 and SPEC-202: nginx answers `/config.json` with the document or a
  404, so a missing document reads as `unreachable`, not `unparseable`.
- **Changed:** Marked for SPEC-194 and SPEC-202: the CloudFront behaviours went with the distribution,
  and `no-store` is now nginx's own header on `location = /config.json`.

### 2026-09-01

- **Changed:** SPEC-215 replaced the repository-variable wiring site with `.github/config-outputs.json`;
  only a genuine input is still a variable.

### 2026-08-24

- **Settled:** SPEC-192. A production build had no fallback and a development build fell back to
  `import.meta.env`; the distribution needed its own `Managed-CachingDisabled` behaviour for
  `/config.json`, because CloudFront's 1 s MinTTL applies even against an origin `no-store`.
