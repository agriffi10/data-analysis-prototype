# Completed Spec — SPEC-262: The Browser Signs In Through the Server

The spec merged as PR #973. The build landed in two merges on 2026-11-15: #1003 (`71a659e3`), which
moved the browser onto the portal server and kept the way back, and #1013 (`72740d1d`), which
retired the public client and narrowed every allowlist. Between them the rollback to the image the
service ran before #1003 (`c0bbacb1`) was rehearsed live. `main` was green on both merges.

## What was completed?

- **The browser holds no token.** `auth.service` and `AuthProvider` run over the server's session
  routes: sign-in visits `/auth/login`, the signed-in user comes from `/auth/session`, and sign-out
  posts `/auth/logout` and follows the provider's logout URL. `apiRequest` calls the API on the
  page's own origin under `/api/`, names the tab's user in `x-dq-user`, and retries nothing; a 401
  re-reads the session once. `getIdToken` asks the server to refresh (`POST /auth/refresh`).
  `lib/documentNavigation.ts` is the seam for leaving the app, because jsdom cannot observe
  `location.assign` or `reload`.
- **The server.** `/api/` refuses a request naming no user or another user before any store read. A
  session load, a sign-out and a callback's replacement leave alone a session whose ID token another
  client created, so a dev cookie replayed against production does nothing. Under `next dev` the
  cookies drop `__Host-` and `Secure`, and the dev server listens on localhost only.
- **Local development** signs in through its own confidential client. `npm run dev:session-env`
  writes the server's environment for that client into `apps/portal/.env.local` from an SSM
  SecureString rendered from the task definition's own locals, and prints only names.
- **Amplify is gone** from the code, the manifest and the bundle, and so is the public Cognito
  client. The API's `OIDC_AUDIENCE` is the server and dev clients; the API has no CORS and the
  router no preflight branch, so an `OPTIONS` takes the ordinary refusal; `connect-src` is `'self'`
  and the two buckets' endpoints; `/config.json` carries four keys.
- **The register.** Merge 1 rewrote twelve decisions in place, among them
  `cognito-tokens-are-held-per-tab-not-per-browser` (one session per browser now), the API
  verifier's, the provider block's and the SDK ban's; merge 2 rewrote six for the narrowing, among
  them the cutover decision, `no-backend`, the runtime document's and the CSP's. The Help guide's
  session sentence changed.

### Deliberate deviations

- **`dev:session-env` also writes every `CONFIG_` key and `PORTAL_CSP_CONNECT_SRC`** (amended during
  the build), so one script gives a developer everything the server's start check requires.
- **A sign-out also leaves a foreign-client session alone** (amended during the build), or a
  replayed dev cookie could end the dev session through production's sign-out.
- **Five of the six retiring keys' Terraform outputs stay** (amended during the build). They are
  read by the live-check guide, the ZAP workflow and the branding step; only
  `cognito_user_pool_client_id` went, with its client.
- **The public client's Managed Login style was deleted by hand before merge 2.** The deploy role
  can create a style and not delete one, and AWS documents neither a cascade nor a refusal when a
  client with a style is deleted; deleting it first removed the question.

## What changed from earlier specs?

- SPEC-257's routes are now the only sign-in path, and `/api/` requires `x-dq-user`.
- The browser's direct path to the API, and the API's CORS that served it, are gone.
- `connect-src` no longer names Cognito or the API.
- The runtime document (SPEC-192, SPEC-255) lost `apiBaseUrl`, `appUrl`, `awsRegion` and the three
  Cognito keys.

## Verification

Locally on each merge: Prettier, ESLint, `tsc -b`, Vitest with coverage, the analyze build and
`check:pages`, the bundle check, ruff, mypy, pytest, `tofu validate`, the docs gate, and the image
matrix against a locally built image. Two fresh-context diff reviews per merge, in the execution and
security frames, each planting defects in the guards it changed. Live on 2026-11-15, in the
desktop app's browser pane: three cold sign-ins, each landing on its deep link; a second tab;
cross-tab sign-out; the refused callback; a local sign-in and upload through the dev client; the
rollback rehearsal through Amplify; after merge 2 the positive proofs of every removal, and a fresh
sign-in and upload. The fresh sign-ins ran in the pane's own profile, signed out and with Managed
Login cold, not in a new browser profile, which the pane cannot open. `docs/testing/sessions.md` has
the record.
