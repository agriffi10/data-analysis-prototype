---
type: Spec
id: SPEC-257
title: "The Next.js Server Holds the Session"
description: "The portal's Next.js server becomes an OIDC client that holds each browser's session in DynamoDB behind an opaque httpOnly cookie and forwards same-origin API calls with the session's token, built beside Amplify and not yet used by the browser, so SPEC-262 can switch the browser onto it."
spec_status: Completed
depends_on: [SPEC-255]
arc: nextjs
arc_order: 3
---

**Dependency notes:** SPEC-255 (the Next.js toolchain, the App Router at `apps/portal/src/app/`,
the `src/server/` convention with `import 'server-only'`, the Node container in the `spa` module and
its task definition). Arc reasoning and the contracts this spec implements: `ARCS.md` → *Next.js
arc (SPEC-255 → 263)*. Recheck SPEC-255's landed spec and code before planning: where its task
definition renders its environment is where FR-002 and FR-003 add to it.

## Overview

Today the browser signs in through Amplify, holds its tokens in the tab, and sends the ID token to
the API as a bearer. The client environment requires a Next.js server, and the arc puts the session
there: the browser will hold only an opaque cookie, and the server will hold the tokens, refresh
them, and attach them to the browser's API calls on the way through. This spec builds that server
side completely and proves it live, while the browser keeps signing in through Amplify exactly as it
does now. Nothing in the browser calls the new routes until SPEC-262 switches it over, so this spec
changes nothing a user sees.

## Scope

### In Scope

- A NAT gateway on the web tier's switch, so the server can reach Cognito's token endpoint and the
  API, and a DynamoDB gateway endpoint so session traffic does not cross it (FR-001).
- A confidential Cognito app client, its secret delivered to the container, and its Managed Login
  branding (FR-002).
- A session store in DynamoDB under a customer-managed key, outside the switch, with expiry checked
  on read and a refresh that two concurrent requests cannot corrupt (FR-003).
- The session routes and the two cookies (FR-004).
- The `/api/` route handler, and the `Origin` check on every unsafe method under `/api/` and
  `/auth/` (FR-005).
- The API's verifier accepting both clients' audiences (FR-006).
- The `@aws-sdk/*` ban narrowed to the browser bundle, with `CLAUDE.md`'s AWS row (FR-007).
- The deploy role's IAM for the five new resource types (a NAT gateway, an Elastic IP, a DynamoDB
  table, a KMS key and an SSM parameter), landed in its own PR before the resources that need it
  (`infra/info/deploy-role-iam.md`).

### Out of Scope

- **The browser using any of it** (SPEC-262): `AuthProvider`, `apiClient`, the landing page reading
  `?signin=failed`, the sign-up entry point, Amplify and the public client's retirement, and
  `connect-src` losing the Cognito hosts and the API origin. The browser's document keeps
  `apiBaseUrl` and the Amplify keys.
- **Narrowing the verifier** to the confidential client (SPEC-262).
- **Signing in through the server from a local dev server.** The confidential client admits only
  the deployed origin's callback, because a localhost callback is only useful with the client secret
  on a laptop. How local development signs in once Amplify is gone is SPEC-262's call.
- **An idle timeout.** Today a tab stays signed in for the refresh token's 30 days with no idle
  limit, and this spec keeps that ceiling: the session ends when the refresh token's lifetime ends,
  or at sign-out. A shorter idle limit is a product change, not part of moving the session.
- **Refresh-token rotation.** It is pinned off (FR-002), for the reason FR-003 gives.
- **Identity Center token exchange** (`transition_plan.md` Phase 1), which extends this store rather
  than building another.
- **A second NAT gateway or a regional one.** One zonal gateway serves a tier with no users that is
  on only while someone works; the pinned provider (5.100.0) has no regional mode.
- **Client-secret rotation, a "sign out everywhere", or a list of a user's sessions.**
- **Any route in the Next.js server beyond the session routes and the pass-through.** A business
  route there is a second API (`CLAUDE.md`, Out of Scope).

---

## Functional Requirements

### FR-001: The web tier reaches Cognito and the API through a NAT gateway on its switch

#### Description:

The `network` module gains one zonal NAT gateway, with its Elastic IP, in the public subnet of the
first sorted availability zone, and every private route table gains a `0.0.0.0/0` route to it. The
server needs it for two destinations that have no VPC endpoint: the Cognito domain's token and
revocation endpoints, and the API's public custom domain. A DynamoDB **gateway** endpoint,
associated with every private route table, carries the session store's traffic instead, so it
neither crosses the NAT nor bills per gigabyte there. The task security group gains egress on 443 to
`0.0.0.0/0`, because neither destination has a fixed address range, and to the DynamoDB prefix list.

**Task start stays on endpoints.** FR-002 delivers the client secret through the task definition's
`secrets`, which the ECS agent fetches from SSM through the task's own network interface at start.
An `ssm` interface endpoint joins the three the module already has, so the agent fetches the
parameter the way it already pulls the image and opens the log stream. Starting a task never
depends on the NAT, and the NAT carries only the two destinations above. It is one more interface
endpoint per zone, billed only while the tier is on.

Everything here lives in `network` or `spa`, so it is on `web_tier_enabled` and costs nothing while
the tier is off. Flow logs stay: they are now the record of what the task reached, not only of what
was refused. **A change to the IAM in `network` or `spa` goes unplanned and unscanned while the tier
is off** (`infra/info/web-tier.md`), so this spec's infrastructure PR opens with the tier already
switched on (Implementation Phases).

#### Acceptance Criteria:

- [ ] `aws_nat_gateway` and `aws_eip` are each declared exactly once under `infra/`, both in
      `modules/network`. The repo-wide no-NAT test in `lambdas/test_network_module.py` is replaced
      by one asserting exactly that, which fails naming the file when either appears elsewhere or
      twice.
- [ ] Every private route table's one default route targets that NAT gateway, and no route table in
      any other module carries a default route, asserted by a test over the HCL.
- [ ] A new test asserts that both gateway endpoints, S3's and DynamoDB's, take their route tables
      from `aws_route_table.private` by expression, never as a list of names. No test asserts this
      for S3 today.
- [ ] The interface endpoints' set is exactly `ecr.api`, `ecr.dkr`, `logs` and `ssm`, asserted by a
      test, and the task's egress to them stays the existing security-group rule.
- [ ] With the tier on, `describe-route-tables` for each private table shows the local route, the
      S3 and DynamoDB prefix-list routes and `0.0.0.0/0` to the NAT gateway, read beside a sign-in
      on the deployed tier that completed (the token endpoint was reached through it).
- [ ] The switch-off that ends the live checks is a dispatch, and a dispatch applies with no plan
      job, so its apply log is the record: it destroys only addresses under `module.network[0]` and
      `module.spa[0]`, the NAT gateway and the Elastic IP among them, and touches nothing under
      `module.session_store` or `module.auth`.
- [ ] `infrastructure/there-is-no-nat-gateway-and-the-endpoints-are-the-whole-outbound-story` is
      rewritten in place with a dated History entry, and every other live site stating the no-NAT
      design carries a supersede marker or is corrected: `docs/architecture.md`,
      `infra/modules/network/README.md`, the comments in `infra/modules/network/main.tf` and
      `endpoints.tf`, `infra/modules/analytics/README.md`, `lambdas/info/planes/table-builder.md`
      and `docs/testing/owed.md` (re-grep `NAT` before closing; the list was taken while authoring).
      `infrastructure/the-web-tier-has-an-off-switch-and-the-balancer-gave-up-its-deletion` names
      what the switch now holds and what deliberately sits outside it.

### FR-002: A confidential app client, its secret in the container, and its login page

#### Description:

The `auth` module gains a second app client beside the public one. It **mirrors the public
client's sign-in settings** (the `code` flow, the `openid email profile` scopes, `COGNITO` as the
only identity provider, `prevent_user_existence_errors`, the explicit auth flows, and no
`read_attributes` or `write_attributes` list) and differs in four ways only: it generates a secret,
its one callback URL is `<portal origin>/auth/callback`, its one sign-out URL is the portal origin,
and it declares what the public client leaves to defaults: `enable_token_revocation = true`,
`refresh_token_rotation { feature = "DISABLED" }`, and ID and access tokens valid for 60 minutes with
a refresh token valid for 30 days. Those validities come from one local, which also renders the
server's `SESSION_MAX_AGE_SECONDS`, so the session cannot outlive the token that keeps it alive.

The mirror matters most for `read_attributes`: a list that omits a `custom:shared_space_k` attribute
drops that claim from the confidential client's ID tokens, and a missing membership claim presents
as the documented propagation delay rather than as a fault.

The secret is written to an SSM `SecureString` parameter in the `auth` module, outside the switch,
and reaches the container as `OIDC_CLIENT_SECRET` through the task definition's `secrets`, read at
task start by the execution role. Every server-only setting (Environment Variables, below) is a
server environment variable and never a `CONFIG_*` key, so none can reach the browser's runtime
document.

Managed Login's pages do not render for an app client with no branding style, and
`deploy-infra.yml`'s *Ensure Managed Login default branding* step brands only the client it names.
It brands both.

#### Acceptance Criteria:

- [ ] A test over the HCL asserts the two clients agree on every mirrored setting and differ on the
      secret, the callback list and the sign-out list, and that neither declares `read_attributes`
      or `write_attributes`.
- [ ] The confidential client declares rotation `DISABLED` and revocation `true`, asserted by a
      test, and on the deployed account `describe-user-pool-client` for it shows both, run with
      `--query 'UserPoolClient.[EnableTokenRevocation,RefreshTokenRotation]'`. The unprojected
      response carries `ClientSecret`, which must not reach a transcript, a log or a PR.
- [ ] `SESSION_MAX_AGE_SECONDS` and the client's `refresh_token_validity` are rendered from the same
      local, asserted by a test that fails when either is a literal.
- [ ] The secret appears in no task definition `environment` entry, no `CONFIG_*` key, no module or
      root output, and no rendered runtime document: a test asserts the task definition's `secrets`
      names the parameter and no `environment` name contains `SECRET`, and the runtime-document test
      asserts none of the server-only names in *Environment Variables* is a document key.
- [ ] The execution role's grant names that one parameter's ARN for `ssm:GetParameters`, and the task
      role holds no SSM permission, asserted by a test over the policy templates.
- [ ] `deploy-infra.yml` ensures default branding for each of the two client ids, and on the deployed
      tier `GET /auth/login` lands on a rendered Managed Login sign-in page for the confidential
      client.

### FR-003: The session store

#### Description:

A new module, `session-store`, called from the root **outside** the switch, holds an on-demand
DynamoDB table and the customer-managed KMS key it is encrypted with. Outside the switch, turning
the tier off neither schedules the key for deletion nor drops every session. The table has hash key
`pk`, TTL on `expiresAt`, deletion protection on, and point-in-time recovery deliberately **off**: a
backup would keep refresh tokens past the sessions they belong to. The key has rotation on, a
30-day deletion window, an alias, and a key policy that delegates to the account's IAM and names no
other principal. A key policy naming the task role would make a resource outside the switch read a
role inside it, which the switch decision forbids.

The task role (in `spa`) gains the item actions the server uses on that table's ARN and nothing
else, and whatever KMS use DynamoDB makes on the caller's behalf, conditioned on
`kms:ViaService`. That KMS grant is measured by a live write and read, not inferred: DynamoDB
decrypts the table key with the accessing principal's credentials, and an absent grant is an
`AccessDenied` on the first request.

**Encryption is the table's, not the server's.** Measured while authoring, by signing an ID token
with Cognito's claim set and a 2048-bit RSA key: 1,450 characters with no memberships, 2,651 with
ten 63-character `custom:shared_space_k` claims, and 5,224 at the pool schema's 256-character
bound. KMS `Encrypt` takes at most 4,096 bytes of plaintext, so tokens cannot be encrypted
client-side in one call, and the table's at-rest encryption under the customer-managed key is what
satisfies `transition_plan.md` §4.7.

**The item.** `pk` is `session#` followed by the SHA-256 hex digest of the cookie's session id, so
the table never holds a usable cookie. It holds the ID token and the refresh token, and not the
access token, which nothing uses. It records the ID token's expiry, the session's absolute expiry
(the sign-in time plus `SESSION_MAX_AGE_SECONDS`), the TTL attribute set to that absolute expiry, and
a `version` number.

**Expiry is checked on read.** DynamoDB deletes an expired item within days, and until then reads
return it, so every read treats an item at or past its absolute expiry as absent and deletes it. The
TTL is storage hygiene and never the boundary.

**A refresh is a compare-and-set.** Every read is strongly consistent. A refresh calls Cognito's
token endpoint with the stored refresh token, then writes the new ID token with the condition
`attribute_exists(pk) AND version = :read_version`, incrementing `version`. The loser of a race gets
`ConditionalCheckFailedException`, re-reads, and uses the winner's token; if the re-read finds no
item, the session ended while it refreshed, and the answer is a 401. The condition is what stops a
refresh that races a sign-out from bringing the session back, because `UpdateItem` creates an
absent item. Either clause alone refuses an absent item, since a comparison on a missing attribute
is false; `attribute_exists(pk)` is kept as the explicit statement of that intent, not because the
version clause would let the write through.

**A forced refresh never adopts an older token.** A `POST /auth/refresh` exists to pick up a
membership granted a moment ago, and the request it lost to may have called Cognito before that
grant. So a forced refresh that loses re-reads the item and compares the two ID tokens' `iat`: when
the stored one was issued in the same second as its own or later, it uses that one; when the stored
one is older, it writes its own against the version it re-read. A refresh made only because the token
was near expiry uses the stored token whatever its age, which serves it as well as its own. So the
stored token only moves forward, and a burst of refreshes on one cookie settles on one write, with
every request answered. Five writes are a backstop, not a limit a burst reaches: every write after
the first follows another refresh's write of a token issued in an earlier whole second than this
one's, so losing five times takes five concurrent refreshes issued in five distinct earlier seconds,
each landing between this one's read and its write. A refresh still losing after five answers 503.
`iat` counts whole seconds, so a token issued in the same second as the forced refresh's own counts
as fresh even if Cognito issued it a moment before the grant; the next forced refresh issues a later
second's token and stores it. (Measured in the execution review: the first design, where a forced
loser always wrote its own token up to three times, answered 503 to 6 to 13 of 20 concurrent forced
refreshes on one cookie, and could write an older token over a newer one.)

**Two tabs refreshing at once** are two requests carrying one cookie, possibly on two tasks.
Measured while authoring: the live public client reports no `RefreshTokenRotation`, and Cognito
documents that with rotation off a refresh returns new ID and access tokens and the original refresh
token *"remains valid"*. So both refresh calls succeed, the compare-and-set keeps one stored token,
and neither request fails. Rotation is pinned off rather than left to a default because with it on,
a refresh whose process dies between Cognito's answer and its write leaves the store holding a
refresh token Cognito revokes after its grace period, which signs the user out for no reason they
can see. The refresh token never leaves the server, so rotation's protection against a stolen token
would buy little here.

**The server keeps no session in memory.** No module-scoped value holds a session, a token or a
store result between requests, so a second task or a restart serves the same session (`§4.7`).

**Three clocks.** The refresh token's 30 days end the session, and the next request answers 401.
The cookie ends when the browser session does, and the next visit signs in again (a warm Managed
Login cookie makes that one click within its hour). The ID token's 60 minutes are invisible, because
the server refreshes ahead of them.

#### Acceptance Criteria:

- [ ] `session-store` takes no input from `network` or `spa`, and its key policy's only principal is
      the account root, both asserted by tests over the HCL.
- [ ] The table and key pass Checkov `CKV_AWS_119` and `CKV_AWS_7`, which join
      `.github/checkov-enforced.txt`; `CKV_AWS_28` fails on the table by decision and is accepted
      with the backup reason above in `docs/security-baseline.md`'s Checkov table, which is how this
      repo records an accepted finding (it suppresses none inline).
- [ ] A store read that returns an item at or past its absolute expiry yields no session, a 401 from
      the route, and a delete of that item, asserted against a store double.
- [ ] **The offline harness.** Against a store double that evaluates the condition as DynamoDB does
      (a comparison on a missing attribute is false, and an unconditional update creates the item),
      with the interleaving forced (both requests read, then each writes): two near-expiry refreshes
      of one session both return a valid ID token, the stored `version` advances once per successful
      write, and the losing request uses the winner's token with no 401. A sign-out forced between a
      refresh's read and its write leaves the item absent and answers that refresh with 401.
- [ ] Against the same double: a forced refresh that loses to an older token's write stores its own;
      one that loses to a token issued in the same second or later uses that token and writes no
      more; and one that keeps losing to older tokens answers 503 after exactly five writes.
- [ ] The DynamoDB adapter sends exactly the condition expression the double enforces, asserted on
      the command's input. Removing the whole condition expression from the adapter makes the
      sign-out interleaving fail, because the write recreates the item; run once and reverted (plant
      and run, not argued).
- [ ] A test serves a session through one store double and then asks for the same cookie, in the
      same module, through an empty one, and finds nothing; an in-memory cache planted in
      `loadSession` fails it when the test runs alone. (A module-registry reset was the first shape,
      and it passed with the cache planted, because the fresh module brought a fresh, empty cache.)
- [ ] **The live harness.** On the deployed tier, with one signed-in cookie, 20 concurrent
      `POST /auth/refresh` and 20 concurrent `GET /auth/session` all succeed, and `GET /auth/session`
      answers 200 afterwards. Neither route runs a Lambda. Calls through `/api/` in the harness run at
      most five at once, because each is an API Lambda invocation and the account's Lambda
      concurrency is small (10 when this spec was written; `aws lambda get-account-settings` reads
      it), and a throttle relayed as 503 would read as a session fault. A sign-in, a session read, a
      refresh and a sign-out on the deployed tier each succeed, which is the proof the task role's
      grants are enough.

### FR-004: The session routes and the cookies

#### Description:

Route handlers under `apps/portal/src/app/auth/`, using modules in `src/server/session/`:

- **`GET /auth/login`** generates `state`, a PKCE verifier (S256) and an OIDC `nonce`, sets the
  sign-in cookie `__Host-dq_signin` holding the three (`httpOnly`, `Secure`, `SameSite=Lax`,
  `Path=/`, `Max-Age=3600`, no `Domain`), and redirects to the authorize URL with
  `redirect_uri=<portal origin>/auth/callback`. An hour, because a sign-up or a password reset in
  Managed Login waits on an emailed code, and a transaction that expired while the user fetched it
  would land a newly confirmed user on `/?signin=failed`, signed out. The transaction rides in the
  cookie rather than the table, so an unauthenticated flood of `/auth/login` writes nothing. Nothing can plant the cookie
  in a victim's browser, because the `__Host-` prefix refuses a sibling subdomain's `Domain` cookie
  and `Secure` refuses the network. That holds only while the server reads a cookie's name exactly:
  it trims space and tab and nothing else. `String.prototype.trim` also strips U+00A0, which Node
  reads from a 0xA0 header byte, so a cookie named 0xA0 followed by `__Host-dq_signin` would read as
  the real one while the browser, checking the prefix against the name it stored, gave it none of the
  prefix's protection. (Found by the security review against the real server and Chrome: a sibling
  subdomain planted a sign-in this way, and the victim's next upload reached the API as the
  attacker.)
- **`GET /auth/callback`** requires the sign-in cookie and a `state` equal to the cookie's, exchanges
  the code at the token endpoint with the verifier and the client secret (`client_secret_basic`),
  and checks the returned ID token's `iss`, `aud` (the confidential client), `token_use` (`id`),
  `nonce` and `exp`. The token comes straight from the token endpoint over TLS, so its signature is
  not re-verified here (OIDC Core §3.1.3.7, item 6); the API verifies it on every forwarded call. On
  success it deletes any session the request's existing session cookie named, creates a session
  under a **fresh** random id (32 bytes, base64url), sets `__Host-dq_session` exactly as the
  charter names it (`httpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, no `Max-Age`, no `Domain`),
  clears the sign-in cookie, and redirects to `/`. Any failure, including a provider `error`
  parameter, a missing or mismatched cookie, a failed exchange and a failed claim check, redirects
  to `/?signin=failed`. It clears the sign-in cookie only when the cookie's `state` matched: a
  mismatch means the cookie belongs to another sign-in still in flight, from a second tab or a
  replayed old callback, and clearing it would fail that one too.
- **`POST /auth/logout`** deletes the session item, then revokes the refresh token at the revocation
  endpoint (a failed revocation is logged by its code and does not fail the sign-out), clears the
  session cookie, and answers 200 with `{logoutUrl}`, the provider's logout URL with the
  confidential client's id and the portal origin as `logout_uri`. With no session it still clears
  the cookie and answers the same.
- **`GET /auth/session`** answers `{username, email?}` from the stored ID token's `cognito:username`
  and `email`, refreshing first when the token is near expiry as FR-005 does, or 401.
- **`POST /auth/refresh`** refreshes whatever the expiry, so newly granted shared-space claims
  arrive, and answers 204, or 401 when the session is gone.

**A fault is not a sign-out.** A 401 means the session is gone. Every call to the token and
revocation endpoints is bounded at 5 seconds, and every session-store call at 2 seconds; SPEC-262's
browser timeout is pinned above the sum these bounds and the forward deadline make. A store failure, an unreachable token endpoint, or an `invalid_client` answer (the server's
secret is wrong, which no user can fix)
answers 503 `ApiUnavailable`. Only an `invalid_grant` answer to a refresh ends the session, by
deleting it. Every refusal the server mints uses the API's failure envelope and a code the API's
contract declares, so a browser cannot tell the server's 401 from the API's.

**Configuration is read when a route runs, never at import or at startup.** A server that reads a
session setting while booting fails to start whenever one is unset, and takes every page down with
it rather than only the session routes. SPEC-255's start-time check (`src/instrumentation.ts`)
exits on a missing `CONFIG_*` key because every page needs those; the session variables stay out of
it, because no page uses them until SPEC-262, which decides whether they join it.

**No credential reaches a log or a response body.** Error messages are fixed strings. No log line
carries a token, the session id, its digest, the client secret, an authorization code, a PKCE
verifier, a nonce, or a token-endpoint response body.

Every response under `/auth/` carries `Cache-Control: no-store`. Every redirect target and the
`redirect_uri` are built from `PORTAL_ORIGIN`, never from the request's `Host` or `X-Forwarded-*`
headers. The load balancer's access log records whole request URLs, so two things now land there
that did not before. The authorization code arrives as part of the callback URL; it is single-use,
short-lived, and useless without both the secret and the verifier. Every `/api/` query string
arrives too (object keys, prefixes, query ids), where API Gateway's own log format records only the
path; none of it is a credential, and the log sits in the admin-only bucket.

#### Acceptance Criteria:

- [ ] `/auth/login` sets `__Host-dq_signin` with exactly the attributes above and redirects to a URL
      carrying `response_type=code`, the confidential client id, the `redirect_uri` built from
      `PORTAL_ORIGIN`, `code_challenge_method=S256`, and a `code_challenge` that is the S256 of the
      cookie's verifier, asserted by parsing both.
- [ ] A callback with no sign-in cookie, a mismatched `state`, an `error` parameter, a failed
      exchange, or an ID token whose `aud`, `iss`, `token_use`, `nonce` or `exp` is wrong each
      redirect to `/?signin=failed` and create no session: one test per exit, each asserting that
      the token endpoint was or was not called, as its exit requires. Every exit whose `state`
      matched the cookie clears the sign-in cookie, and the mismatched-`state` exit leaves it set.
- [ ] A cookie whose name is either cookie's name with a U+00A0 before or after it reads as absent,
      and one padded with spaces and tabs reads as present, asserted on the cookie reader.
- [ ] A successful callback sets `__Host-dq_session` with exactly the charter's attributes, to an id
      that differs from any session cookie the request carried, deletes the session that cookie
      named, and redirects to `/`.
- [ ] `/auth/logout` deletes the item before calling the revocation endpoint (asserted on call
      order), answers `{logoutUrl}` with a `logout_uri` equal to `PORTAL_ORIGIN`, clears the cookie
      with `Max-Age=0`, and still answers 200 when revocation fails or no session exists.
- [ ] `/auth/session` answers `{username, email}` for a session, and 401 with the API's
      `SessionExpired` envelope for no cookie, a malformed cookie (no store call), an unknown id and
      an expired item.
- [ ] `/auth/refresh` calls the token endpoint when the ID token is far from expiry, answers 204,
      and answers 401 after an `invalid_grant`, with the item deleted.
- [ ] A store failure, a token-endpoint timeout and an `invalid_client` answer each produce 503
      `ApiUnavailable` and leave the item in place.
- [ ] With every session variable unset, the server starts and serves `/` and a signed-in page, and
      `/auth/session` answers 503, asserted by a test that imports the route modules with an empty
      environment.
- [ ] A sentinel test drives every failure exit above with a distinctive value in each token, the
      code, the verifier, the secret and the session id, captures all console output and every
      response body, and finds none of the sentinels.
- [ ] A request whose `Host` and `X-Forwarded-Host` name another origin still gets redirects and a
      `redirect_uri` built from `PORTAL_ORIGIN`.

### FR-005: The `/api/` route handler, and the `Origin` check

#### Description:

`apps/portal/src/app/api/[...path]/route.ts` exports `GET`, `HEAD`, `POST`, `PUT`, `PATCH` and
`DELETE`. It loads the session (FR-003), refreshing first when the ID token expires within 300
seconds, which covers the API Gateway integration's 30 seconds and clock skew with room to spare.
It then forwards the request to the API and returns the API's answer.

**The target is pinned to the API's origin.** `/api/<rest>?<query>` is forwarded to
`API_ORIGIN + "/" + <rest>?<query>`, with `<rest>` exactly as received, so today's `/v1/...` paths
arrive unchanged. The target is built by concatenation and then checked to have `API_ORIGIN` as its
origin. It is never built with `new URL(rest, API_ORIGIN)`, which resolves `//evil.example/x` to
another host and would hand it the session's token.

**Headers are allowlisted both ways.** The request carries `content-type`, `accept` and
`x-request-id` from the browser, plus `authorization: Bearer <ID token>`; never the browser's
`cookie` or `authorization`. The response carries the API's status, its body as received, and its
`content-type`, `cache-control` and `www-authenticate`, which are the headers the API sets; never a
`set-cookie`. The allowlist also keeps the forwarded request no larger than the one the browser
sends the API today, under the HTTP API's header quota with a worst-case ID token.

**Bounds.** A request body over the HTTP API's 10 MB payload quota answers 413 `PayloadTooLarge`
without being forwarded. For an unsafe method the order is the `Origin` check, then a declared
`content-length` over the cap (refused from the header alone, before any session is read), then the
session, then the body, whose read counts bytes and stops past the cap for a body that declared
none. Neither a forged request nor an oversized one costs a store read.

**A request with a body never waits for the proxy.** When the request proxy matches a request that
has a body, Next.js clones the body for it and then waits for the **whole** body to arrive before
any route handler runs, discarding what lies past `proxyClientMaxBodySize` but still reading it.
Then neither the `Origin` check nor the session check nor the 413 could answer before an attacker's
body ended. Measured while authoring on `next start` (Next.js 16.4.6) with a request declaring 1 GB
and sending one byte: with the proxy matching every path, no answer came within four seconds; with
the proxy not matching, the handler answered 403 in 16 ms without `Origin` and 413 in 3 ms with it.
**SPEC-255's build closes this for every path, and this spec relies on it rather than adding a path
exclusion of its own:** the proxy's `matcher` is `/:path*` with `missing` on `content-length` and
`transfer-encoding`, so a request carrying a body skips the proxy, and `next.config.ts`'s
`headers()` gives exactly those requests the security headers and the lockdown policy, both from
`src/lib/securityHeaders.ts` (`SECURITY_HEADERS`, `LOCKDOWN_POLICY`). That module is plain, not
`server-only`, and must stay so: measured, a `next.config.ts` that imports a module beginning
`import 'server-only'` fails `next build` with *"This module cannot be imported from a Client
Component module"*. A request with no body to `/api/` or `/auth/` passes through the proxy like any
other and takes its headers and policy; the nonce stays the proxy's, as the charter says.

**Redirects are not followed.** The forward uses `redirect: 'manual'`, and an API answer in the 3xx
range yields 503 `ApiUnavailable`. Measured on Node 25: a followed cross-origin 307 drops the
`authorization` header but re-sends the body to the other host and hands its answer to the browser,
and a same-origin redirect keeps the bearer. The API answers nothing in that range today, so this
closes a door rather than a hole. A
forward that has not answered after 35 seconds, past the API Gateway integration's 30, answers 503
`ApiUnavailable`. An API 401 passes through as the API sent it, and the session is left alone.

**The `Origin` check.** Every `POST`, `PUT`, `PATCH` and `DELETE` under `/api/` and `/auth/`
requires an `Origin` header equal to `PORTAL_ORIGIN`, and answers 403 `AccessDenied` otherwise,
before any store read. A missing `Origin` is refused too, because browsers send it on every
cross-origin request and on every same-origin request that is not `GET` or `HEAD`. `SameSite=Lax`
does not stop a request from a sibling subdomain such as the API's, which is why this check exists.
`GET` and `HEAD` change nothing and are not checked; `/auth/callback` is a cross-site `GET` by
design and is protected by `state` and the sign-in cookie.

#### Acceptance Criteria:

- [ ] `GET /api/v1/x?y=1` reaches the fetch double as `<API_ORIGIN>/v1/x?y=1` with the session's
      ID token as the bearer, and a request with no session answers 401 `SessionExpired` without
      calling the fetch double.
- [ ] `/api//evil.example/x`, `/api/%2F%2Fevil.example/x` and `/api/https:%2F%2Fevil.example/x`
      each either reach the fetch double with a URL whose origin is `API_ORIGIN` or answer 404,
      and never reach any other host, asserted on the URL the double received.
- [ ] A browser `cookie` and `authorization` header never reach the double, an API `set-cookie`
      never reaches the browser, and the forwarded header names equal the allowlist exactly.
- [ ] A session whose ID token expires within 300 seconds is refreshed before the forward, and one
      expiring later is not, asserted on the token-endpoint double's call count.
- [ ] A body over 10 MB answers 413 with no forward, both with a `content-length` and chunked
      without one; an API that does not answer in 35 seconds yields 503 (driven with fake timers);
      an API 401 reaches the browser unchanged and the item is not deleted.
- [ ] Against `next start` with SPEC-255's request proxy in place, not in Vitest, which runs no
      proxy: a `POST` to `/api/x` and one to `/auth/refresh`, each declaring a 1 GB body and sending
      one byte, answer 403 within one second with no `Origin`; with `Origin: PORTAL_ORIGIN`, the
      `/api/x` one answers 413 within one second, before any session is read. A `POST` through
      `/api/` of exactly 10 MB is forwarded whole, its byte count asserted at the API double, in the
      handler suite: a session needs a store `next start` does not have, and once the proxy skips a
      bodied request (the rows above), nothing between the socket and the handler can cut the body.
- [ ] Against `next start`, every response under `/api/` and `/auth/` carries SPEC-255's
      `SECURITY_HEADERS`: one to a request with a body carries `LOCKDOWN_POLICY` as its CSP, and
      one to a request without a body carries the proxy's policy. This spec changes neither the
      proxy's `matcher` nor `next.config.ts`'s `headers()`, asserted by its diff.
- [ ] An API answer of 302 and one of 307 each yield 503 `ApiUnavailable`, and the fetch double
      records exactly one request, so no redirect was followed.
- [ ] Every unsafe method under `/api/` and on each `/auth/` route answers 403 `AccessDenied` with
      `Origin` absent, with `Origin` set to the API's origin, and with `Origin` set to
      `PORTAL_ORIGIN` plus a port, in each case before any store read. The same request with
      `Origin: PORTAL_ORIGIN` passes the check.
- [ ] On the deployed tier, `POST /auth/refresh` with `Origin: <API origin>` answers 403, and a `GET`
      through `/api/` with a confidential-client session answers 200 with the API's body.
- [ ] `/api/x` and `/auth/session` are served by their route handlers and not by the optional
      catch-all page: a request to each returns JSON, not the portal's HTML. Next.js's precedence
      between them is not stated in its docs, so this is measured.

### FR-006: The API's verifier accepts both clients

#### Description:

`VerifierConfig.audience: str` becomes `audiences: frozenset[str]`, and `jwt.decode` receives it as
a list. `OIDC_AUDIENCE` keeps its name and becomes a comma-separated list, so today's single client
id is still a valid value of the new format. The loader refuses an empty list or an empty element
as `ConfigError` (a 5xx). That is the fail-closed direction that does not sign everyone out:
measured while authoring, PyJWT refuses every token when given an empty list, which would answer 401
to every request and tell every user to sign in again for a fault none of them can fix. The `api`
module's variable becomes a list of client ids, validated non-empty with no empty or
comma-containing element, and rendered with `join(",", …)`. The root passes the public and the
confidential client.

**What was measured** (`cpcommon.auth._verify_claims` with the key set doubled): a list accepts a
token whose `aud` is any member and refuses one that is not, a comma-joined *string* is treated as
one audience and refuses everything, and a tuple or frozenset behaves as a list. The parsing
therefore lives in the loader, and nothing hands PyJWT the raw variable.

**Order.** The code that reads a list lands in a PR that leaves `OIDC_AUDIENCE` unchanged, and that
code is running in the fleet before a later PR sets it to two ids. In the other order, a function
still running the old code reads `a,b` as one exact audience and refuses every token. **Lambda
builds must be on for both merges**: while `LAMBDA_BUILDS_ENABLED` is not `true`, no image is built
or pointed, and `.github/scripts/frozen_fleet_guard.py` refuses any plan that changes a function's
`environment`. Unless they are already on, the build switches Lambda builds on through the
repository variable, following `.github/workflows/README.md` (*Turning Lambda builds back on*),
before the first of those merges, and confirms after the second that the API function runs the
commit that set both audiences. Its report says when it turned them on. Andrew approved them staying
on for the arc's build-out (2026-11-13); they go off when the arc ends, not when this spec does.

#### Acceptance Criteria:

- [ ] Through the verifier, with the provider's key set doubled: a token for the confidential client
      and one for the public client are both accepted under the two-id configuration, and a token for
      a third client is refused with bytes identical to the no-token refusal.
- [ ] The loader turns `a` into `{a}` and `a,b` into `{a, b}`, and raises `ConfigError` for the
      empty string, `a,`, `,b` and `a,,b`; a request under that configuration answers 5xx, not 401.
- [ ] The `api` module's variable refuses an empty list and an element that is empty or contains a
      comma, asserted by plan-time validation tests in `lambdas/test_api_module.py`, and the root's
      list names both clients' ids.
- [ ] The PR that changes `OIDC_AUDIENCE` merges only after the API function runs an image holding
      the list-reading code, confirmed by reading the function's image tag before that merge, and
      its plan passes the frozen-fleet guard because Lambda builds are on.
- [ ] `identity-and-access/the-provider-block-is-the-apis-verifier-configuration-and-it-is-server`
      is rewritten in place for an audience set, with a dated History entry.

### FR-007: The AWS SDK stays out of the browser bundle

#### Description:

The session store is the first server-side AWS call in `apps/portal`, so the ban narrows to what it
was always for: the browser. `@aws-sdk/client-dynamodb` becomes the one `@aws-sdk` package the
manifest may name, and the one importable from `src/server/**` only. ESLint flat config replaces a
rule's value rather than merging it, so the `src/server/**` clause re-declares
`no-restricted-imports` with every group the `src/**` clauses carry except the SDK's, and every other
clause governing `src/` still forbids it. Every module under `src/server/` begins with
`import 'server-only'`, which makes `next build` fail when a client module imports it. A second
rule in `npm run check:bundle`, which CI already runs over `.next/static/` after the build (SPEC-255
FR-002), proves the chain end to end: it looks for `DynamoDB_20120810`, the protocol
target every DynamoDB request carries, because a search for `@aws-sdk` would hit the copies Amplify
vendors until SPEC-262. Measured while authoring: the string is in `@aws-sdk/client-dynamodb`
3.1168.0's `runtimeConfig.shared.js` and `commandBuilder.js`, and in nothing `aws-amplify` installs
(the same search finds Amplify's own Cognito protocol target, so it reached those files).

#### Acceptance Criteria:

- [ ] `eslintConfigShape.test.ts` requires the SDK group in every clause governing `src/` except the
      `src/server/**` clause, requires that clause to carry every other group the `src/**` clause
      carries, and holds the manifest's `@aws-sdk/` names to exactly `['@aws-sdk/client-dynamodb']`.
- [ ] An `@aws-sdk/client-dynamodb` import in a file under `src/features/` fails `npm run lint`, and
      the same import under `src/server/` passes.
- [ ] A test asserts that every `.ts` file under `src/server/` begins with `import 'server-only'`.
- [ ] `npm run check:bundle` fails naming the chunk when any file under `.next/static/` contains
      `DynamoDB_20120810`, keeps its existing `VITE_` rule, and passes on this branch. Importing a
      `src/server/` module that lacks `server-only` from a client component makes it fail; run once
      and reverted.
- [ ] `CLAUDE.md`'s AWS row says the browser uses `aws-amplify` for Cognito and nothing else, and the
      server uses `@aws-sdk/client-dynamodb` for the session store and nothing else; its *Code
      Conventions* AWS line still holds. `browser/the-aws-sdk-ban-is-a-lint-rule-and-a-manifest-sweep-because-amplify`
      is rewritten in place for the narrowed ban, with a dated History entry.

---

## Data Model

```ts
// apps/portal/src/server/session/session.types.ts

/** One session item. The key is a digest of the cookie, so the table never holds a usable cookie. */
export type SessionItem = {
  /** `session#` + SHA-256 hex of the cookie's session id. */
  pk: string;
  idToken: string;
  refreshToken: string;
  /** Epoch seconds: the stored ID token's `exp`. */
  tokenExpiresAt: number;
  /** Epoch seconds: sign-in time + SESSION_MAX_AGE_SECONDS. The boundary, checked on every read. */
  sessionExpiresAt: number;
  /** Epoch seconds: the TTL attribute, equal to sessionExpiresAt. Hygiene, never the boundary. */
  expiresAt: number;
  /** Incremented by every write; the compare-and-set's subject. */
  version: number;
};

/** What the sign-in cookie carries between /auth/login and /auth/callback. */
export type SignInTransaction = {
  state: string;
  codeVerifier: string;
  nonce: string;
};

/** The existing browser shape (src/features/auth/auth.types.ts), answered by GET /auth/session. */
export type SessionUser = {username: string; email?: string};
```

## API / Interface Contract

```ts
// apps/portal/src/server/session/store.ts — the only module that imports @aws-sdk/client-dynamodb.
export type SessionStore = {
  /** Strongly consistent. Returns null for an absent item; expiry is the caller's check. */
  get(pk: string): Promise<SessionItem | null>;
  put(item: SessionItem): Promise<void>;
  /** Condition: attribute_exists(pk) AND version = :expectedVersion. False when the condition failed. */
  replaceTokens(pk: string, expectedVersion: number, next: Pick<SessionItem, 'idToken' | 'tokenExpiresAt'>): Promise<boolean>;
  delete(pk: string): Promise<void>;
};

// apps/portal/src/server/session/session.ts
export type LoadedSession =
  | {status: 'active'; pk: string; idToken: string; user: SessionUser}
  | {status: 'absent'}
  | {status: 'unavailable'};
export function loadSession(
  store: SessionStore,
  config: SessionConfig,
  cookieValue: string | undefined,
  options: {forceRefresh: boolean},
  now?: number
): Promise<LoadedSession>;
```

| Route | Method | Success | Failure |
|---|---|---|---|
| `/auth/login` | GET | 302 to the authorize URL, sets `__Host-dq_signin` | 503 if unconfigured |
| `/auth/callback` | GET | 302 to `/`, sets `__Host-dq_session` | 302 to `/?signin=failed` |
| `/auth/logout` | POST | 200 `{logoutUrl: string}`, clears the cookie | 403 on `Origin` |
| `/auth/session` | GET | 200 `SessionUser` | 401 `SessionExpired`, 503 `ApiUnavailable` |
| `/auth/refresh` | POST | 204 | 401, 403, 503 |
| `/api/<rest>` | GET HEAD POST PUT PATCH DELETE | the API's answer | 401, 403, 413, 503 |

## Environment Variables

Server environment variables of the portal's container, set in the `spa` task definition. None is a
`CONFIG_*` key, and none appears in the browser's runtime document. Each is read when a route runs.
`API_ORIGIN`, `OIDC_TOKEN_URL` and `OIDC_REVOKE_URL` must be `https:`, or `http:` to a loopback host
for a local harness, and any other value answers 503 as an unset one does: the server sends the
client secret and the bearer to them, and skips the ID token's signature check only because the
token arrives over TLS.

```
PORTAL_ORIGIN=https://<portal domain>                  # redirect targets, redirect_uri, the Origin check
API_ORIGIN=https://<api domain>                        # the /api/ target; not the browser's apiBaseUrl
OIDC_ISSUER=<the user pool's issuer>
OIDC_CLIENT_ID=<the confidential client's id>
OIDC_CLIENT_SECRET=<from the SSM parameter, via the task definition's secrets>
OIDC_AUTHORIZE_URL=<Cognito domain>/oauth2/authorize   # fields, not derived from a domain: the
OIDC_TOKEN_URL=<Cognito domain>/oauth2/token           # concatenation appears once, at the
OIDC_REVOKE_URL=<Cognito domain>/oauth2/revoke         # composition root, as the verifier's
OIDC_LOGOUT_URL=<Cognito domain>/logout                # JWKS URI does
SESSION_TABLE_NAME=<session-store table>
SESSION_MAX_AGE_SECONDS=2592000                        # from the client's refresh_token_validity
AWS_REGION=<region>
```

## File & Folder Structure

```
apps/portal/src/
├── app/
│   ├── api/[...path]/route.ts             # FR-005
│   └── auth/
│       ├── login/route.ts                 # FR-004
│       ├── callback/route.ts
│       ├── logout/route.ts
│       ├── session/route.ts
│       └── refresh/route.ts
└── server/session/                        # every file begins with import 'server-only'
    ├── config.ts                          # lazy reads of the variables above
    ├── store.ts                           # the DynamoDB adapter
    ├── oidc.ts                            # authorize URL, code exchange, refresh, revoke, claim checks
    ├── session.ts                         # loadSession and the compare-and-set refresh
    ├── cookies.ts                         # the two cookies' attributes
    ├── origin.ts                          # the Origin check
    ├── forward.ts                         # the /api/ target, header allowlists and bounds
    ├── refusal.ts                         # the API's failure envelope
    └── session.types.ts
infra/
├── modules/session-store/                 # table and key, outside the switch
├── modules/network/                       # + NAT gateway, Elastic IP, DynamoDB endpoint
├── modules/auth/                          # + confidential client, SSM parameter
├── modules/spa/                           # + environment, secrets, task-role and execution-role grants
└── modules/base/policies/                 # + the deploy role's grants, in their own PR
apps/portal/scripts/assert-bundle-*.mjs    # check:bundle gains the DynamoDB rule (FR-007)
```

## Implementation Phases

### Phase 1: The deploy role's grants and the verifier's list (inert)

- Expand the deploy role's IAM for the NAT gateway, the Elastic IP, the DynamoDB table, the KMS key
  and its alias, and SSM parameters under the `/<project>-<environment>/portal/` path (SPEC-262 adds
  a second one there), working through `infra/info/deploy-role-iam.md`'s traps:
  `kms:CreateKey` and SSM's `DescribeParameters` are not resource-scopable, DynamoDB creates KMS
  grants on the creator's behalf, the provider's refresh of an SSM `SecureString` reads its value,
  and the guard sleep must re-fire for a modified policy.
- Change the verifier and its loader to an audience list, leaving `OIDC_AUDIENCE` at one id.
- This phase is its own PR, merged and applied before Phase 2's, with Lambda builds switched on
  before it merges (FR-006).

### Phase 2: The infrastructure

- **Switch the tier on through the repository variable and CI before this phase's PR opens**, so its
  plan holds `network` and `spa` and the plan-time IAM scan reads their new policies. Opened with
  the tier off, the PR's plan would hold neither, and its apply would be the first time those
  policies were evaluated (`infra/info/web-tier.md`).
- `network`: the NAT gateway, its Elastic IP, the private default routes, the DynamoDB endpoint, the
  `ssm` interface endpoint;
  `spa`: the task's egress, environment, `secrets`, and both roles' grants; `auth`: the confidential
  client and the SSM parameter; `session-store`: the table and key; the root: `OIDC_AUDIENCE` set to
  both clients; `deploy-infra.yml`: branding for both clients.
- The HCL tests of FR-001, FR-002, FR-003 and FR-006, and the Checkov list.

### Phase 3: The server

- `src/server/session/` and the six route handlers, the offline harness, the sentinel test, the
  narrowed SDK ban and the bundle check.

### Phase 4: Live, then off

- With the tier still on from Phase 2, run FR-001's, FR-002's, FR-003's and FR-005's live checks,
  then switch the tier off through the repository variable and CI, and read that apply's log
  (FR-001).
- The completion ritual: the four decisions rewritten in place, a new `identity-and-access/`
  decision for the session's design (the cookie-held sign-in transaction, the compare-and-set
  refresh, expiry on read, faults that are not sign-outs, the `Origin` check), and `owed.md` rows
  for any live check that could not run.
- The PR grouping is the build's to propose and review: Phase 1 stands alone because the grant must
  apply first and the verifier's code must be running before its environment changes, and Phases 2
  and 3 may land together or apart, since nothing the browser calls depends on either.
