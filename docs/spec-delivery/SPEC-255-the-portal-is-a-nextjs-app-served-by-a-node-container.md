# Completed Spec — SPEC-255: The Portal Is a Next.js App Served by a Node Container

The spec merged as PR #967 and the build as PR #971 (`65516853`), both on 2026-11-13. The build's
apply destroyed exactly the nine `module.static_portal[0]` resources (*"0 added, 0 changed, 9
destroyed"*). The deploy role's static-portal grant came off in the closing pull request that
carries this document, after that destroy had applied, because the destroy needed the grant. The live
checks ran the same evening on the web tier switched on through CI, and the tier was switched off
again through CI afterwards: Deploy Infrastructure run 43540336336 destroyed 46 resources, every one
under `module.network[0]` or `module.spa[0]`, and `portal.dataquarry.app` then answered NXDOMAIN.

## What was completed?

- `apps/portal` builds with `tsc -b && next build` (Next.js 16.4.6, standalone output) and serves
  from Next's Node server. The existing app mounts client-only in the optional catch-all
  `src/app/[[...slug]]/`, whose `PortalMount` loads `src/PortalBoot.tsx` through `next/dynamic` with
  `ssr: false`; react-router is untouched. `main.tsx` and `index.html` are gone, and the root layout
  forces dynamic rendering so every page carries a nonce.
- Monaco's worker is a `new Worker(new URL(…))`, Tailwind runs through `@tailwindcss/postcss`, and
  the `VITE_*` fallback answers only under `MODE === 'test'`. `check:bundle` reads `.next/static/`.
  `import.meta.env.DEV` stays where it guards a dev-only diagnostic, as the spec says: Turbopack supports it.
- The server renders `/config.json` from `CONFIG_<key>` (`src/server/runtimeDocument.ts`), and
  `src/instrumentation.ts` exits 1 at start naming any required variable unset, empty or unsafe. The
  wiring sites went from five to four.
- The request proxy (`src/proxy.ts`) mints a per-request nonce for an enforcing CSP and sets the seven
  security headers; `/healthz` and an honest `/_next/` 404 are route handlers.
- The image is `node:24-bookworm-slim` by digest, running `node apps/portal/server.js` as uid 1000 on
  a read-only root with one tmpfs at `/tmp`. `.github/scripts/spa-image-matrix.sh` asserts it on
  responses.
- The web tier is the only front door: `static-portal`, `deploy-spa-static.yml` and their guards are
  deleted, the weekly ZAP baseline skips loudly while the tier is off, and the deploy role's grant
  and its two accepted Checkov plan findings are gone.

### Deliberate deviations

The spec was amended during the build for the first three, so they are deviations from it as drafted.

- **A request carrying a body skips the proxy.** The SPEC-257 session found that a proxied request
  with a body makes Next wait for the whole body before anything answers; measured here, a declared
  gigabyte held every path. The proxy's matcher excludes `Content-Length` and `Transfer-Encoding`,
  and `next.config.ts` gives those requests the headers and a lockdown policy.
- **The headers are two modules, at the paths SPEC-257 names**: the nonce-free `src/lib/securityHeaders.ts`,
  shared with `next.config.ts` and so free of `server-only`, and the nonce-carrying
  `src/server/contentSecurityPolicy.ts`, imported by the proxy alone.
- **`lambdas/test_csp_policy.py` was not deleted.** Its byte-identity test and recorded literal moved
  to TypeScript, but its test that `connect-src` names both Cognito hosts, and its parser's own test,
  outlive the deleted local.
- **`CKV2_AWS_40` joined the enforced Checkov list.** The re-measurement that retired the ten
  CloudFront-era IDs found it passing with no failure (`docs/security-baseline.md`).
- **`npm run dev` signs in but cannot call the API.** The API's CORS never admitted
  `http://localhost:5173`, under Vite or now. SPEC-257's same-origin `/api/` pass-through removes the
  gap; the production API's CORS is not widened for it.

## What changed from earlier specs?

- SPEC-192's runtime document is rendered by the Next.js server instead of nginx's entrypoint, and
  its fallback became the test runner's alone. SPEC-194's nginx image, its header snippets and its
  `Server: nginx` divergence are gone. The CloudFront path of 2026-11-02 is retired. Eight register
  entries were rewritten in place, listed in the spec's Scope.

## Verification

- Live, on image `65516853` (task-definition revision 265), with Andrew's help in his signed-in
  Chrome; every result and run ID is in `docs/testing/sessions.md` (2026-11-13). Deploy SPA image
  run 43518664168 settled the service; the policy enforced `connect-src` with a same-origin control;
  a fresh sign-in, an upload, deep links, Back and Forward, the Monaco editor and the dark theme all
  passed; `npm run dev` signed in at `localhost:5173`. ZAP run 43538730372 scanned the server with the
  tier on, and run 43516167248 skipped with it off; the diff is in `docs/security-baseline.md`.
- The first-frame paint of the dark theme cannot be captured; the evidence is the blocking, nonced
  `theme-init.js` in `<head>`. Nothing user-facing changed, so there is no Help & guides update.
