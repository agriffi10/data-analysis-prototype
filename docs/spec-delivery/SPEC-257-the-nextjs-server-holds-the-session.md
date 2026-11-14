# Completed Spec — SPEC-257: The Next.js Server Holds the Session

The spec merged as PR #968. The build landed in two PRs on 2026-11-14: #976 (`36174146`, the deploy
role's session grant, the verifier's audience list and a scrubbed Checkov artifact) and #978
(`b0d7734b`, the infrastructure and the server together). #978's apply failed creating the
confidential client, and #979 (`568c3d76`) fixed it; `main` was green again on that merge. #975
(`799b5655`) went first, because the Lambda image push had become an OCI index Lambda refuses. The
live checks ran on 2026-11-14 with the web tier switched on through CI, and nothing the browser
calls uses the new routes until SPEC-262.

## What was completed?

- **Infrastructure.** One zonal NAT gateway and its Elastic IP in `network`, both waiting for the
  internet gateway, with every private table's default route to it; a DynamoDB gateway endpoint and
  an `ssm` interface endpoint, so task start still uses only endpoints. `session-store` holds the
  table and its customer-managed key, outside the web tier's switch. `auth` holds the confidential
  client (rotation off, revocation on, validities from one local) and its secret in an SSM
  SecureString, which the `spa` task definition injects through `secrets`. The root passes both
  clients' ids to the API as `OIDC_AUDIENCE`, and `deploy-infra.yml` brands both.
- **Server.** `apps/portal/src/server/session/` (`config`, `cookies`, `oidc`, `session`, `store`,
  `forward`, `origin`, `refusal`, `deadline`, `handlers`) and six route handlers under
  `src/app/auth/` and `src/app/api/[...path]/`. Sessions are keyed by the SHA-256 of an opaque
  `__Host-dq_session` cookie, the sign-in transaction rides in `__Host-dq_signin`, a refresh is a
  compare-and-set, expiry is checked on read, and a fault answers 503 rather than signing anyone out.
- **The SDK ban narrowed.** `src/server/` may import `@aws-sdk/client-dynamodb` and nothing else,
  the manifest names exactly that package, and `npm run check:bundle` fails on `DynamoDB_20120810` in
  any static chunk.
- **The decision register.** A new identity-and-access decision for the session's design; the no-NAT
  decision rewritten in place; the web-tier, provider-block and SDK-ban decisions updated;
  architecture row 57 superseding row 34 in part.

### Deliberate deviations

The spec was amended during the build for the first three, so they depart from it as drafted.

- **A losing refresh uses the stored token unless it was forced and that token is older by `iat`.**
  The drafted rule, a forced loser always writing its own up to three times, answered 503 to 6 to 13
  of 20 concurrent forced refreshes when the execution review drove the real server. Five writes
  remain as a backstop.
- **The cookie reader trims only space and tab.** The security review showed in Chrome that `trim()`
  let a 0xA0-prefixed name read as `__Host-dq_signin`, so a sibling subdomain could plant a sign-in.
- **The token, revoke and API URLs must be HTTPS**, or HTTP to a loopback host for a local harness,
  because the server sends its secret there and skips the ID token's signature check only over TLS.
- **Phases 2 and 3 landed in one PR (#978)**, as the spec allowed.
- **The switch-off check did not run here.** SPEC-256 still held the web tier when these checks
  finished, so the tier stayed on. Reading the next switch-off's apply log was a row in `owed.md`,
  settled on 2026-11-14 by dispatch 43607397695 (`docs/testing/sessions.md`).
- **Lambda builds stay on for the arc**, by Andrew's decision, and go off when the arc ends.

## What changed from earlier specs?

- **SPEC-193's no-NAT design is reversed in part.** AWS services stay on endpoints, and one NAT
  gateway carries the server's two internet destinations.
- **SPEC-192's provider block takes a set of audiences.** `OIDC_AUDIENCE` is comma-separated, and a
  single id stays valid.
- **SPEC-255's ESLint config gains a last clause for `src/server/`**, which keeps the react-router
  ban that SPEC-256 added beside its own narrowed SDK ban.
- **Every image build turns off Docker's provenance and SBOM attestations** (#975), and both Lambda
  image workflows check that the image is one manifest; the deploy workflow checks before its push.

## Verification

Local: ruff, mypy, pytest, `tofu validate`, Prettier, ESLint, Vitest, `next build`, `check:bundle` and
`validate_docs.py`, all green before each push (#979 touched no portal file, so it ran the Python,
OpenTofu and doc gates). Each PR had two fresh-context reviews in different
frames: execution and security for #978, and execution and claims for #979.

Live, on 2026-11-14:

- **Network.** Both private route tables show local, the S3 and DynamoDB prefix lists and
  `0.0.0.0/0` to the NAT gateway.
- **The client.** `describe-user-pool-client`, projected, shows revocation on and rotation
  `DISABLED`; the client has Managed Login branding; the API's audience names both clients.
- **Sign-in and the store.** `/auth/login` landed on a rendered Managed Login page, and a sign-in
  through the token endpoint completed. Two runs of 20 concurrent `POST /auth/refresh` and 20
  concurrent `GET /auth/session` on one cookie answered 204 and 200 throughout.
- **The pass-through and sign-out.** Five `/api/v1/feature-flags` calls answered 200 with the API's
  body, `POST /auth/logout` answered the Cognito logout URL, and `/auth/session` and `/auth/refresh`
  then answered 401.
- **Refusals and routing.** `POST /auth/refresh` with the API's `Origin`, or none, answered 403, and
  `/api/x` and `/auth/session` answered JSON rather than the portal's page. The server logged no
  session error.
