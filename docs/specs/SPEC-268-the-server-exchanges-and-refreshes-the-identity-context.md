---
type: Spec
id: SPEC-268
title: "The Server Exchanges and Refreshes the Identity Context"
description: "At sign-in the Next.js server exchanges the user's Cognito ID token for an Identity Center identity context, keeps it fresh with Identity Center's refresh grant, seals it to the user with KMS and forwards it to the API, so the API can act with that person's own Lake Formation and Access Grants entitlements."
spec_status: Draft
depends_on: [SPEC-257, SPEC-262, SPEC-266, SPEC-267]
---

**Dependency notes:** SPEC-257 (the session item, its compare-and-set refresh, the 300-second margin,
the fault rules: a provider fault answers `unavailable` and never signs the user out). SPEC-262 (the
browser signs in through the server, so every signed-in request crosses the pass-through). SPEC-266
(the member-account IaC: the `identity_center_enabled` flag, the Identity Center input variables, and
the sealing key with its whole key policy, output as `identity_context_key_arn`). SPEC-267 (the API's
half: the unseal, the carrier role, the credential cache, the codes the API answers and their browser
wording). SPEC-267 lands first and is inert while no request carries the header. The design is
`docs/transition_plan.md` §3.5 (steps 1 and 1r), §4.7 (the split, the seal, the state rules) and §5.5
(*What Phase 0 measured*).

**A Phase 0 gate in the client environment stands between this spec and going live.** Phase 0's
G10 ran on an Identity Center **account** instance, with the application in our own account. The
client has one **organization** instance under LZA, and its customer-managed application lives in the
management or delegated-admin account, so our member-account task role calls `CreateTokenWithIAM` on
another account's application. That cross-account exchange is untested. This spec builds and merges
inert; it is switched on in an environment only after that gate passes there (FR-001).

## Overview

From Phase 5, Lake Formation and S3 Access Grants decide what each person may read, keyed on their
Identity Center user rather than on a shared role. For AWS to know who that person is, the portal
must present an **identity context** with each data call. This spec makes the portal's Next.js
server obtain that context when the user signs in, keep it fresh for as long as the portal session
lasts and Identity Center allows, and hand it to the API in a form only the API can open and only for
the same user. When Identity Center cannot supply a context, the user stays signed in and keeps
everything that does not need one; when Identity Center stops refreshing it, the portal asks them to
sign in again rather than quietly starting a new Identity Center session.

## Scope

### In Scope

- The server's configuration from SPEC-266's inputs, and an inert state while the flag is off
  (FR-001).
- The JWT-bearer exchange in the sign-in callback (FR-002).
- The refresh, the retry after a failed exchange, and what a refused refresh does (FR-003).
- The seal: one KMS `Encrypt` per context, under an encryption context naming the bearer's `sub`
  (FR-004).
- The forward: the sealed context, or the reason there is none, on the `/api/` pass-through (FR-005).
- The task role's `sso-oauth:CreateTokenWithIAM` grant, the two new server-side AWS clients and their
  fences, and the deploy-role IAM if the build finds the role cannot already write that grant
  (Phase 1).

### Out of Scope

- **Any Identity Center infrastructure.** The instance, the customer-managed application, its access
  scopes, its refresh grant, the trusted token issuer pointing at our pool, the assignment settings
  and the actor policy naming our task role all belong to the client's Identity Center
  administrators. Our IaC takes their values as inputs (SPEC-266) and creates none of it.
- **The input variables, the flag and the sealing key** (SPEC-266), and **the API's half**
  (SPEC-267): unsealing, the carrier role, `sts:SetContext`, the credential cache, choosing per route
  between the carrier session and the portal role, the codes it answers, and their wording.
- **A region of its own for Identity Center.** SPEC-266 requires the instance, Access Grants, the
  workgroup and Lake Formation to share `aws_region` (§4.4), so both new clients use `AWS_REGION`.
- **Re-exchanging after a refused refresh.** Decided below (FR-003): absent until the next sign-in.
- **The leaver window.** Andrew decided on 2026-11-15 that it is not a concern for this client
  (`transition_plan.md` §4.7), so nothing here shortens a session or checks Entra.
- **The driver path** (§3.10), whose tokens never touch this server.

---

## Functional Requirements

### FR-001: The exchange is configured from SPEC-266's inputs, and is inert while the flag is off

#### Description:

The server reads three new variables (*Environment Variables*). The application ARN and the trusted
token issuer's audience are two of the four Identity Center values the client's administrators hand
over; the other two (the instance ARN and the identity store id) feed SPEC-266's member-account
consumers and are not the server's. `IDC_CONTEXT_KEY_ARN` is SPEC-266's sealing key.

**All three unset is the inert state, and it is what merges.** The exchange is off: no session item
gains an identity, no request carries either header (FR-005), and sign-in, refresh and the
pass-through behave exactly as SPEC-257 left them. **Some set and some unset is a configuration
fault**, reported by the start-time check (`instrumentation.ts`), which names every problem and exits
the process, as it does for SPEC-257's variables. **The audience must equal `OIDC_CLIENT_ID`.** The
trusted token issuer checks the assertion's `aud`, and the assertion is this server's own ID token,
so any other value means every exchange will be refused; the start-time check reports it as
`unusable` rather than letting it surface as a refusal on every sign-in.

The `spa` module sets the three variables in the task definition, and grants the task role
`sso-oauth:CreateTokenWithIAM` on exactly the application ARN, only when SPEC-266's
`identity_center_enabled` is `"true"`. A `precondition` on that wiring refuses the plan when the flag
is on and the application ARN or the audience is empty, so a half-configured environment fails at
plan rather than as a task that will not start. The flag is turned on in an environment only after
the client-environment Phase 0 gate on the cross-account exchange has passed there (*Dependency
notes*). No `kms:Encrypt` statement is added to the task role: SPEC-266's key policy names the role
directly.

#### Acceptance Criteria:

- [ ] With the three variables unset, a sign-in, a refresh and a forwarded request each make no
      Identity Center or KMS call and send neither `x-identity-context` nor
      `x-identity-context-absent`, asserted by tests with client doubles that fail the test if
      called.
- [ ] With any one of the three set and another unset, the start-time check reports each unset one
      by name, asserted for each of the three as the missing one.
- [ ] With `IDC_TOKEN_ISSUER_AUDIENCE` set to anything but `OIDC_CLIENT_ID`, the start-time check
      reports `IDC_TOKEN_ISSUER_AUDIENCE` as `unusable`.
- [ ] A test over the HCL asserts that with the flag `"false"` the task role gains no statement and
      the task definition no `IDC_*` entry; with it `"true"`, the new statement's `Resource` is
      exactly the application ARN and its `Action` exactly `sso-oauth:CreateTokenWithIAM`; and the
      precondition refuses the flag on with an empty application ARN and, separately, with an empty
      audience.

### FR-002: The sign-in callback exchanges the Cognito ID token, once

#### Description:

After the provider's code exchange succeeds and before the session item is written, the callback
calls `CreateTokenWithIAM` with `grantType` `urn:ietf:params:oauth:grant-type:jwt-bearer`, `clientId`
the application ARN, and `assertion` the ID token the code exchange just returned. Under Variant B
that token carries `entra_object_id`, the claim the administrators' trusted token issuer maps to the
Identity Center user's `externalId`; the server sends the token as it is and reads no claim of it for
the exchange. It sends **no
`scope`**: Identity Center then grants every scope the administrators configured on the application.
The server checks the granted `scope` against AWS's documented set for an Identity Center workgroup,
`lakeformation:query`, `athena:workgroup:read_write` and `s3:access_grants:read_write`, plus
`sts:identity_context`, and logs a configuration line naming each one missing, and another naming
each granted scope outside that set together with `openid` and `aws`, which Identity Center adds by
default. A broader grant widens what any leaked context reaches, so the administrators should hear
of it. Neither blocks the context: Phase 0 measured `athena:workgroup:read_write` as required and
`lakeformation:query` as not needed for a query, so the call that needs a missing scope fails at AWS
and the log has said why. Scopes are not requested by name, because naming one the administrators
have not configured fails the whole exchange.

On success the server seals `awsAdditionalDetails.identityContext` (FR-004) and writes the session
with an identity in state `present`: the sealed context, when it was issued and when it expires (the
call's time, and that plus `expiresIn`), and the Identity Center refresh token. A response with no
`identityContext`, or with an `expiresIn` that is missing, not a positive whole number or above
`IDC_MAX_CONTEXT_SECONDS` (7,200, twice the hour Phase 0 measured), is a fault: a wrong expiry would
either forward a context STS has already ended or never refresh it.
A response with no `refreshToken` means the administrators have not enabled the refresh grant: the
context is stored, a configuration line is logged on every such exchange, and FR-003 says what
happens when it lapses.

**The assertion is presented once.** Phase 0 measured that a second exchange of one ID token is
refused with `InvalidGrantException`, whichever principal presents it. So the callback never retries
the call, and **the `sso-oidc` client is built with `maxAttempts: 1`**: the SDK's default of three
attempts would re-send an assertion Identity Center may already have consumed after a reset
connection, and its refusal would read as a real one. Every later attempt uses a newer ID token
(FR-003).

**A failed exchange never fails the sign-in.** Every failure in the *Refusals and faults* table, a
refusal or a fault, writes the session with the identity `pending` and `retryAt` now plus
`IDC_EXCHANGE_RETRY_SECONDS` (300), so the user reaches everything the context does not gate and the
server retries (FR-003). The exchange and the seal each have the deadline `IDC_CALL_TIMEOUT_MS` (5
seconds, as the provider's token call has), so Identity Center and KMS together delay a sign-in by
at most twice that, and never hang it.

**Logging.** Each failure logs a fixed string naming its row in the table and nothing else: no part
of the assertion, of the response, of an error's message or of its stack.

#### Acceptance Criteria:

- [ ] A sign-in whose exchange succeeds stores an item whose identity is `present`, with
      `contextIssuedAt` the call's time, `contextExpiresAt` that plus `expiresIn`, the refresh token,
      and a `sealedContext` equal to the base64 of the KMS double's `CiphertextBlob`; and no stored
      attribute contains the raw context or its base64, asserted by a test that searches every
      attribute for both.
- [ ] An `expiresIn` that is missing, 0, negative, fractional or 7,201 is a fault row, and 7,200 is
      accepted, asserted per value.
- [ ] The exchange request carries the callback's ID token as `assertion`, the application ARN as
      `clientId`, the JWT-bearer grant type and no `scope`, asserted against the recorded input.
- [ ] The `sso-oidc` client's resolved configuration has `maxAttempts` 1, asserted on the client the
      module builds, not on a double.
- [ ] For each row of the *Refusals and faults* table, a sign-in whose exchange fails that way still
      sets the session cookie and redirects to `/`, and stores `pending` with `retryAt` 300 seconds
      on, asserted per row.
- [ ] An exchange that does not answer within `IDC_CALL_TIMEOUT_MS`, and separately a seal that does
      not, completes the callback within `2 × IDC_CALL_TIMEOUT_MS` plus the store write, asserted
      with a fake clock.
- [ ] A granted `scope` missing `athena:workgroup:read_write` still stores `present` and logs one
      configuration line naming that scope; one with an extra `sso:account:access` logs one line
      naming it; one of exactly the four plus `openid` and `aws` logs nothing.
- [ ] A success with no `refreshToken` stores `present` with no refresh token and logs one
      configuration line.
- [ ] No log line written on any path of this spec contains a substring of the assertion, the
      Identity Center refresh token, the response's other tokens or the raw context, asserted by
      capturing `console.*` with distinctive values across every table row on the exchange, on the
      refresh and on the retry, including the retry's claim and outcome writes.

### FR-003: The refresh, the retry, and a refused refresh

#### Description:

`loadSession` keeps the identity fresh in the same pass that keeps the provider's token fresh.
**Ordering invariant (§4.7):** an Identity Center call is made only after the provider's token in
that load is valid. If that token was due and its refresh faulted while it is still valid, the
refresh grant may proceed, because it needs no ID token, but no exchange is attempted, because an
exchange needs a fresh ID token this load does not have. A load that ends the session (the provider
refused its refresh) makes no Identity Center call.

**Two writes, one version.** The identity is written by its own conditional write, `replaceIdentity`,
under the same `version` the token writes compare and advance. A token write never carries the
identity and an identity write never carries the tokens. So SPEC-257's forced re-write cannot roll
the identity back, and an identity write cannot roll a newer provider token back. Two rules govern an
identity write that loses: it re-reads, and it writes against the new version only if the stored
identity is still the one it acted on (the same state, and for `present` the same `contextIssuedAt`
or an earlier one; for `pending` the same `retryAt`). Otherwise it adopts what is stored. Two
exceptions, both toward `ended`: **a refused refresh writes `ended` over any `present`**, however
new its context, so a revocation racing a successful refresh is never lost; and **`ended` is never overwritten**,
so once a refresh has been refused, only a new sign-in, which writes a new item, brings a context
back.

**The transitions, as one table the write enforces.** Every identity write goes through one function
that refuses any transition not listed here, whatever the caller intended; the losing-write rules
above decide *whether* to write, and this table decides *what* may be written over what.

| From | To | Only by |
|---|---|---|
| no attribute | `pending` (jittered `retryAt`) | the first load that sees it |
| `pending` | `pending` with a later `retryAt` | a retry's claim |
| `pending` | `present` | a retry's successful exchange |
| `present` | `present` with a new context and a later `contextIssuedAt` | a successful refresh |
| `present` | `present`, same context, with `retryAt` | a refresh fault, a seal fault, or a refreshed ID token with no `sub` |
| `present` | `ended` | a refused refresh, however new the stored context; or a lapse with no refresh token |
| `unreadable` | `ended` | the load that reads it |
| `ended` | anything | never: only a new sign-in, on a new item |

A sign-in writes a new item with `present` or `pending` and is not a transition. Nothing returns to
`pending` from `present`: a context that lapses after a refresh fault stays `present`, is forwarded as
`unavailable` (FR-005), and is refreshed past its `retryAt`. Nothing goes from `pending` to `ended`:
an exchange refusal is retried (*Refusals and faults*). **A failed retry writes nothing**: its claim
has already moved `retryAt`, which is the only thing a failure changes. `unreadable` is what the store
adapter returns for an identity attribute that is present but does not parse; it is forwarded as
`ended` and written over with `ended` by the load that reads it, so a container that cannot read a
newer schema's attribute ends the context rather than leaving it for one that re-exchanges. **While
the exchange is off**, no identity write is made, whatever the item holds.

**An item with no identity attribute while the exchange is configured** (a session from before the
flag was turned on) is given one: the first load that sees it writes `pending` with `retryAt` now
plus a uniformly random 0 to `IDC_EXCHANGE_RETRY_SECONDS`, so turning the flag on spreads the first
exchanges over five minutes instead of spending the instance-wide quota at once. **An identity
attribute that is present but does not parse is `unreadable`, and becomes `ended`**, never
`pending`: a parse failure must not
become the re-exchange this FR declines, whether it comes from a marshalling bug or a rolling deploy
across a schema change. Neither case makes the item absent: the session still loads.

**Refresh (`present`).** When `contextExpiresAt - now <= REFRESH_MARGIN_SECONDS` (SPEC-257's 300),
or the load is forced and the context was issued more than `IDC_FORCED_REFRESH_FLOOR_SECONDS` (60)
ago, and `retryAt` (if set) has passed, the server calls `CreateTokenWithIAM` with
the `refresh_token` grant and the stored refresh token. Phase 0 measured that this returns a **new**
context, good for an hour from the refresh, and the **same** refresh token, so the JWT-bearer quota
of 10 requests per second per instance stays a sign-in limit, and the refresh grant's 80 per second
per application carries the hourly load. **The floor on a forced refresh** exists because
`POST /auth/refresh` needs only a same-origin request and a session, and nothing in front of it
limits the rate: without the floor, one user looping it would spend the refresh grant's
per-application quota and KMS's `Encrypt` quota for everyone. With it, a session costs at most one
refresh a minute however it is driven. A forced refresh exists to pick up a membership granted a
moment ago, and Lake Formation reads grants at query time, so a context a minute old serves it. The
new context is sealed (FR-004) and written. Two
containers refreshing at once both succeed, because the token is not rotated, and the loser adopts
the stored context, which is no older than its own. The 300-second margin stands, and it also bounds
the carrier session, because STS ends that session when its context expires.

- **Refused** (a refusal row): the identity becomes `ended`, with its refresh token removed. **It
  stays `ended` until the next sign-in.** The portal session is untouched.
- **A fault** (a fault row): the identity keeps its context and gains `retryAt` now plus
  `IDC_RETRY_SECONDS` (60), so an outage costs each session one call a minute rather than one a
  request. The stored context is forwarded while `contextExpiresAt > now`; once it has lapsed, the
  forward answers `unavailable` (FR-005) until a later refresh succeeds.
- **No refresh token** (the refresh grant is off): the context lives out its hour, and at
  `contextExpiresAt` the identity becomes `ended`, for the same reasons a refused refresh does
  (below). Each lapse logs a configuration line, because the remedy is the administrators enabling
  the grant, which the request list for the client's administrators asks for.

**Why a refused refresh is not re-exchanged — decided 2026-11-16 by Andrew, on this recommendation.**
Phase 0 measured that a refreshed Cognito ID token exchanges, so re-running step 1 would recover
silently. It is declined for three reasons. First, a refused refresh means Identity Center no longer
honours this user's refresh token, whether its lifetime ran out or the administrators ended the
session; a re-exchange would mint a new Identity Center session past the session duration the client
set, and past a revocation if revocation refuses a refresh. A new sign-in is the right gate after
either, because it passes through Entra again. Second, the JWT-bearer quota is 10 per second across
the whole instance, shared with sign-ins and with every other application the client runs on it, and
refresh tokens issued in a login storm would expire together. Third, two containers re-exchanging at
once collide, and the loser's replay refusal looks exactly like a real refusal. **The cost:** after
the refresh token stops working, a user sees data routes answer "sign in again" until they do. Its
lifetime is undocumented (Phase 0 saw at least 3 hours 4 minutes, unrotated), and in the client's
instance it is likely bounded by the session duration its administrators set. **Reversible:**
re-exchange would replace the `ended` transition in one function, if that prompt proves too frequent.

**One premise is unmeasured, and the decision does not rest on it alone.** Phase 0 did not probe
whether deleting a user's Identity Center session refuses a refresh; it measured only that removing
the application's refresh grant did not stop tokens already issued. That probe is owed by the
client-environment Phase 0 run. If revocation turns out not to refuse a refresh, the administrators'
revocation does not reach the portal's context until the refresh token's own lifetime ends, and the
decision still stands on the quota and the collision. Phase 2 records which it is.

**Retry after a failed exchange (`pending`).** Past `retryAt`, and only when the
provider's token is valid, the load first **claims** the retry: a `replaceIdentity` that moves
`retryAt` to now plus `IDC_EXCHANGE_RETRY_SECONDS` (300). A load that loses the claim does nothing
more for the identity. The winner then refreshes the provider's token, which gives it an ID token
issued to this call alone and never presented, and exchanges **that** token as FR-002 does, whether
or not its token write then wins under SPEC-257's rules. A successful exchange writes `present` by
`replaceIdentity` under the two rules above, keyed on the claim's `retryAt`; a failed one writes
nothing. If the provider refresh faults, or its ID token has no `sub`, no exchange is made and the
claim's `retryAt` stands. A stored ID token is never exchanged by a retry, so no ID
token is ever presented twice. An exchange refused at sign-in is retried the same way, because the
commonest refusal then is a user SCIM has not provisioned yet, which resolves on its own. **The
quota:** one JWT-bearer call per retrying session per 300 seconds, so 300 sessions retrying at once
spend one call a second of an instance-wide 10 that sign-ins and the client's other applications
share. Each retry logs a line, so the spend is visible rather than assumed to fit.

**Sign-out** deletes the item, which ends the portal's use of the context, because Identity Center's
OIDC API has no revocation. It does not end a copy of the refresh token taken earlier. That token is
the longer exposure (it is not rotated, and removing the grant does not stop it), and *What the
refresh token at rest exposes*, in FR-004, states it.

#### Acceptance Criteria:

- [ ] A load with `contextExpiresAt - now` of 301 seconds makes no Identity Center call; one of 300
      refreshes, stores a `sealedContext` equal to the base64 of the KMS double's new
      `CiphertextBlob` with its expiry, forwards the new one, and stores neither the raw context nor
      its base64, asserted with a fake clock.
- [ ] A forced load refreshes both the provider's token and a context issued 61 seconds earlier, and
      refreshes the provider's token but not a context issued 60 seconds earlier; fifty forced loads
      within one minute make at most one refresh-grant call and one `Encrypt` call.
- [ ] A load whose provider refresh is refused deletes the item and makes no Identity Center call; a
      load whose provider token was due, faulted and is still valid refreshes a `present` context
      but makes no exchange for a `pending` one.
- [ ] Each refusal row on a refresh leaves the identity `ended` with no refresh token, keeps the
      session `active`, and no later load makes an Identity Center call, asserted per row.
- [ ] A refresh fault stores `retryAt` 60 seconds on and keeps the context; a load before `retryAt`
      makes no Identity Center call and forwards the old context while it is valid and `unavailable`
      once it has lapsed; a load past `retryAt` calls the refresh grant, not the JWT-bearer grant.
- [ ] A `present` identity with no refresh token makes no Identity Center call before
      `contextExpiresAt` and is `ended` at it, logging one configuration line.
- [ ] An item with no identity attribute loads as `active`, makes no Identity Center call on that
      load, and stores `pending` with `retryAt` between now and 300 seconds on. An item whose identity
      attribute is present but does not parse (an unknown `state`, a `present` with no
      `sealedContext`, an `ended` with an extra field) loads as `active`, reads as `unreadable`,
      forwards `signin`, is written over with `ended` by that load, and no later load makes an
      Identity Center call. Both are asserted through the real store adapter's unmarshalling, not the
      double's. With the exchange off, an item holding any identity forwards neither header and is
      not written.
- [ ] An execution harness that interleaves two loads of one session at each write asserts, for
      each pairing: two proactive context refreshes advance to one stored context that both
      forward; a forced load racing a retry makes at most one JWT-bearer call, whose assertion is
      the ID token the claim's winner obtained; an outcome write racing a forced provider refresh
      leaves the newer provider token stored and the outcome's identity stored; and a refusal racing
      a successful refresh leaves `ended` whichever write lands first.
- [ ] A table-driven test runs the transition function over every pair of (stored state, proposed
      state), including `unreadable` and no attribute, and asserts it writes
      exactly the pairs the transitions table lists and refuses every other, naming the pair.
- [ ] A failed retry makes no identity write after its claim, so `retryAt` stays at the claim's
      value, and a load before it makes no Identity Center call and no provider refresh; a refresh
      returning a context whose expiry is earlier than the stored one, but issued later, is
      stored.

### FR-004: The context is sealed to its bearer, once

#### Description:

The server seals each new context with KMS `Encrypt` on the sealing key, with the encryption context
`{"purpose": "identity-context", "sub": <sub>}`, where `sub` is the `sub` claim of the ID token stored
in the same item, the very bearer the pass-through forwards with it. Cognito's `sub` is stable for
the user across refreshes, so one seal serves every bearer the provider issues during the context's
hour. The encryption context never holds the username, because CloudTrail records it in plain text.
The stored value is the ciphertext, base64-encoded, and the raw context is dropped once sealed.

**One `Encrypt` per context.** The server seals at the exchange and at each refresh, and every
request forwards the stored value. KMS ciphertext differs on every call, so sealing per request would
give the API a different value each time and defeat its cache, which is keyed on the sealed value and
the verified `sub`. The KMS client has the deadline `IDC_CALL_TIMEOUT_MS`. **A seal that fails or
times out is a fault**: it is handled as the exchange or refresh having faulted (FR-002, FR-003),
never as a refusal. An ID token with no `sub` makes no exchange or refresh at all, because a context
sealed to nothing could not be opened.

**The key's policy is SPEC-266's, and this spec holds the server to it:** the task role alone may
`Encrypt`, the API's role alone may `Decrypt`, and everyone else is denied by `aws:PrincipalArn`.
The task role's existing statement for the session table's key grants `kms:Decrypt` on `key/*`, but
only through DynamoDB and only for the session table, and the sealing key's own policy denies the
task role `Decrypt` regardless. So the server cannot open what it stored, and a sealed context opens
only at the API beside its own user's bearer.

**What the refresh token at rest exposes, stated rather than glossed.** The Identity Center refresh
token is stored in the item, encrypted at rest only by the session table's key, whose policy
delegates to the account's IAM (SPEC-257). A stolen item alone does not yield a context: the refresh
grant works only for a principal the application's actor policy names, which is the task role. A
thief holding the task role's credentials as well can refresh it to a **raw** context, past the seal,
and keep doing so after the user signs out, for as long as the token lives. That is the same reach
those credentials and that table already give through the provider's 30-day refresh token and the
client secret in the same container, which mint the user's bearer; so this spec adds no new principal
that can reach a user's data. Narrowing who may read the session table and use its key, which §4.7
requires before the client's security review, applies to both tokens and is its own change, not this
spec's.

#### Acceptance Criteria:

- [ ] The `Encrypt` request carries the sealing key's ARN and exactly the encryption context
      `{"purpose":"identity-context","sub":<the stored ID token's sub>}`, asserted against the
      recorded input, and no encryption-context value equals the username claim.
- [ ] One sign-in followed by ten forwarded requests within the context's hour makes exactly one
      `Encrypt` call, and all ten requests carry the identical header value.
- [ ] An ID token with no `sub` makes no `CreateTokenWithIAM` and no `Encrypt` call and logs a fixed
      line: at sign-in it stores `pending`, on a refresh it takes the fault branch, and on a retry it
      writes nothing past the claim, asserted for all three.
- [ ] An `Encrypt` that throws, and one that times out, store `pending` on a sign-in and follow the
      fault branch on a refresh, asserted for both.
- [ ] A test over the HCL asserts the task role gains no `kms:` statement from this spec, and that
      every statement on it granting a decrypt-capable action (`kms:Decrypt`, `kms:ReEncrypt*`,
      `kms:ReEncryptFrom`, `kms:CreateGrant`, `kms:*`) carries both the `kms:ViaService` DynamoDB
      condition and the session table's name; it fails naming the statement when either is
      removed.

### FR-005: The pass-through forwards the sealed context or the reason there is none

#### Description:

`forward` takes the session's identity and sets, beside the bearer:

| Identity | Header sent |
|---|---|
| anything, with the exchange off (FR-001) | neither |
| `present`, `contextExpiresAt > now` | `x-identity-context: <stored sealed value>` |
| `present` but lapsed, `pending`, or no attribute yet | `x-identity-context-absent: unavailable` |
| `ended` or `unreadable` | `x-identity-context-absent: signin` |

The browser cannot set either header: the request-header allow-list stays exactly `content-type`,
`accept` and `x-request-id`, and the server sets both after copying it. The API's answer is relayed
unchanged, as today. **The server never answers 401 for an Identity Center reason**: the browser
answers a 401 with one forced refresh and then a sign-out, so a lapsed context must not read as a
lapsed session. SPEC-267's answers to these headers are listed under *API / Interface Contract*, and
none is 401.

**Size.** The bearer and the sealed context share the HTTP API's 10,240-byte limit on the request
line and headers, which cannot be raised. Phase 0's contexts were 1,588 to 1,668 characters, and AWS
documents up to 2,048; sealed and base64-encoded, 2,048 characters is about 3 KB.

#### Acceptance Criteria:

- [ ] Each row of the table sends exactly the header it names and not the other, asserted per row
      against the forwarded request.
- [ ] A browser request carrying `x-identity-context` and `x-identity-context-absent` of its own
      reaches the API with neither of its values, in each identity state.
- [ ] A forwarded request with a 2,000-character request line, a 4,096-byte bearer and a sealed
      value the base64 of 2,560 bytes (a 2,048-byte context plus a deliberate 512-byte allowance for
      KMS's undocumented ciphertext overhead) has a request line and headers under 10,240 bytes. The
      allowances are stated in the test beside the reason for each, and Phase 2 checks the real
      sealed value and ID token against them.
- [ ] No path through `/api/` or `/auth/` answers 401 because of the identity's state, asserted
      across the four states with a valid provider session.
- [ ] `GET /auth/session` and `POST /auth/refresh` answer as SPEC-257 left them in every identity
      state: the identity is never part of the browser's session shape.

---

## Refusals and faults

`CreateTokenWithIAM` errors, by the SDK's exception name. A **refusal** is Identity Center declining
this user or this token; a **fault** is anything the user did not cause. Configuration faults are
faults, logged as `configuration`, because signing in again cannot fix them.

| Exception, or condition | Kind | On the sign-in exchange (FR-002); a failed retry writes nothing | On a refresh (FR-003) |
|---|---|---|---|
| `InvalidGrantException` | refusal | `pending`, retried | `ended` |
| `ExpiredTokenException` | refusal | `pending`, retried | `ended` |
| `AccessDeniedException` | refusal | `pending`, retried | `ended` |
| `InvalidClientException`, `UnauthorizedClientException`, `InvalidRequestException`, `InvalidScopeException`, `UnsupportedGrantTypeException`, `InvalidRequestRegionException` | configuration fault | `pending`, retried | fault branch |
| `InternalServerException`, `SlowDownException`, throttling, any other name | fault | `pending`, retried | fault branch |
| no answer within `IDC_CALL_TIMEOUT_MS`, or a network error | fault | `pending`, retried | fault branch |
| a success with no `identityContext` | fault | `pending`, retried | fault branch |
| an `expiresIn` that is missing, not a positive whole number, or above `IDC_MAX_CONTEXT_SECONDS` | fault | `pending`, retried | fault branch |
| a seal that fails or times out (FR-004) | fault | `pending`, retried | fault branch |
| the ID token has no `sub` (FR-004) | fault | `pending`, retried | fault branch |

`AccessDeniedException` is a refusal on a refresh even though an IAM denial of the task role would
raise it too. Failing closed means a broken grant sends users to sign in again, where the exchange
then fails as `pending` and recovers on its own once the grant is fixed. Failing open would let an
administrator's denial of a user read as an outage that never ends that user's access.

---

## Data Model

```ts
// apps/portal/src/server/session/session.types.ts

/** The Identity Center half of a session. Absent from the item while the exchange is off. */
export type SessionIdentity =
  | {
      state: 'present';
      /** Base64 of the KMS ciphertext. The raw context is never stored. */
      sealedContext: string;
      /** Epoch seconds: the exchange's or refresh's call time; the forced-refresh floor reads it. */
      contextIssuedAt: number;
      /** Epoch seconds: `contextIssuedAt` plus `expiresIn`. */
      contextExpiresAt: number;
      /** Absent when the application's refresh grant is off. */
      refreshToken?: string;
      /** Epoch seconds: set after a refresh fault; no refresh before it. */
      retryAt?: number;
    }
  | {
      state: 'pending';
      /** Epoch seconds: no exchange before this. A `pending` identity always retries by exchange. */
      retryAt: number;
    }
  | {state: 'ended'};

export type SessionItem = {
  // ...SPEC-257's fields, unchanged...
  identity?: SessionIdentity;
};

/** What the store adapter reads: an identity attribute that is present but does not parse is `unreadable`. */
export type StoredIdentity = SessionIdentity | {state: 'unreadable'};

/** One row of the Refusals and faults table, as the log line names it. */
export type IdentityFailure = 'refused' | 'configuration' | 'fault' | 'timeout' | 'no-context' | 'seal' | 'no-sub' | 'bad-expiry';

export type LoadedSession =
  | {status: 'active'; pk: string; idToken: string; user: SessionUser; identity?: StoredIdentity}
  | {status: 'absent'}
  | {status: 'unavailable'};

export type SessionStore = {
  // ...SPEC-257's get, put, replaceTokens and delete, unchanged; replaceTokens never writes `identity`...
  /** Writes `identity` alone under `attribute_exists(pk) AND version = :expectedVersion`, advancing it. */
  replaceIdentity(pk: string, expectedVersion: number, identity: SessionIdentity): Promise<boolean>;
};
```

## API / Interface Contract

**The interface with the API, agreed with SPEC-267's author; SPEC-267 states the same from its side:**

| | Value |
|---|---|
| Context header | `x-identity-context`: standard base64 of the KMS `CiphertextBlob` |
| Absence header | `x-identity-context-absent`: `signin` (only a new sign-in restores it) or `unavailable` (the server is retrying) |
| Neither header | the exchange is off |
| Encryption context | `{"purpose": "identity-context", "sub": <the forwarded bearer's sub>}` |
| Stability | one sealed value per context: constant for its life, new at each refresh |
| Length | at most 4,096 characters, which SPEC-267 refuses above; FR-005's allowance (3,416) sits under it |
| The API's cache key | a digest of the sealed value and the verified `sub` (SPEC-267's to build) |
| Key policy | `Encrypt`: the web task role only. `Decrypt`: the API's role only. Everyone else denied by `aws:PrincipalArn` (SPEC-266) |

SPEC-267's answers on a route that needs a context, none of them 401:

| Condition | Code |
|---|---|
| `InvalidCiphertext` or `IncorrectKey` on `Decrypt`, a malformed header, or a bearer with no `sub` | `IdentityContextMismatch` (403) |
| `x-identity-context-absent: signin` | `IdentitySignInRequired` (403) |
| `x-identity-context-absent: unavailable`, no header, or STS `InvalidContextAssertion` | `IdentityContextUnavailable` (503) |
| KMS or STS throttling or outage | `ApiUnavailable` (503) |
| a configuration fault in the identity layer | `IdentityUnavailable` (500) |

```ts
// apps/portal/src/server/session/identity.ts — with store.ts, the only modules that import an
// @aws-sdk client: @aws-sdk/client-sso-oidc and @aws-sdk/client-kms here.
export type IdentityConfig = {applicationArn: string; keyArn: string; region: string};

/** Exchange, then seal. Never throws: every outcome is a SessionIdentity. */
export function exchange(config: IdentityConfig, idToken: string, now: number): Promise<SessionIdentity>;
/** Refresh, then seal. Never throws. */
export function refresh(config: IdentityConfig, current: SessionIdentity & {state: 'present'}, idToken: string, now: number): Promise<SessionIdentity>;
```

## Environment Variables

Server variables of the portal's container, set in the `spa` task definition only while
`identity_center_enabled` is `"true"` (FR-001). None is a `CONFIG_*` key or reaches the browser. Both
new clients use the existing `AWS_REGION`.

```
IDC_APPLICATION_ARN=<var.identity_center_application_arn>          # from the client's admins
IDC_TOKEN_ISSUER_AUDIENCE=<var.identity_center_token_issuer_audience>  # must equal OIDC_CLIENT_ID
IDC_CONTEXT_KEY_ARN=<SPEC-266's identity_context_key_arn>
```

Constants in code: `IDC_CALL_TIMEOUT_MS = 5_000`, `IDC_RETRY_SECONDS = 60`,
`IDC_EXCHANGE_RETRY_SECONDS = 300`, `IDC_FORCED_REFRESH_FLOOR_SECONDS = 60`,
`IDC_MAX_CONTEXT_SECONDS = 7_200`; `REFRESH_MARGIN_SECONDS` stays SPEC-257's 300.

**Dependencies.** `@aws-sdk/client-sso-oidc` (at a version whose model carries
`awsAdditionalDetails`; Phase 0 found botocore 1.35.x drops it, and its Node exchanger read it) and
`@aws-sdk/client-kms` join the server. `CLAUDE.md`'s Tech Stack *AWS* row, the server's
`no-restricted-imports` clause in `apps/portal/eslint.config.js`, `eslintConfigShape.test.ts` and
`check:bundle` change in the same PR. The ESLint clause is per directory, so a test scans
`apps/portal/src` and asserts that `identity.ts` is the only importer of the two new packages and
`store.ts` (with its test support) of DynamoDB's; the browser bundle still holds no AWS client.

## File & Folder Structure

```
apps/portal/src/server/session/
├── identity.ts            # new: exchange, refresh, seal, the refusal/fault table
├── identity.test.ts       # new
├── config.ts              # + the three IDC_ variables and the audience check
├── session.ts             # loadSession refreshes, retries and claims; createSession stores the identity
├── session.types.ts       # + SessionIdentity, replaceIdentity
├── store.ts               # + the identity attribute and replaceIdentity, under the existing condition
├── forward.ts             # + the two headers
└── handlers.ts            # the callback exchanges before createSession
apps/portal/src/instrumentation.ts  # the start-time check covers the new variables
infra/modules/spa/         # + the task role's statement, the IDC_ environment and the precondition
```

## Implementation Phases

### Phase 1: Inert, and merged before any environment turns the flag on

- The configuration, the audience check and the inert state (FR-001), with their tests.
- `identity.ts` with the table, the seal and both grants, tested against client doubles, and the
  client's `maxAttempts` asserted on the real client (FR-002, FR-004).
- `replaceIdentity`, `loadSession`'s refresh, claim and retry, and the execution harness for the
  races (FR-003).
- The pass-through's headers (FR-005).
- The `spa` wiring, the conditional task-role statement and the precondition. Read
  `infra/info/deploy-role-iam.md` first: if the deploy role cannot already write a statement with
  the `sso-oauth` prefix on the task role, that grant lands in its own PR before this one. The web
  tier must be switched on for the infrastructure PR, because a change to `spa`'s IAM goes unplanned
  while it is off (`infra/info/web-tier.md`).

### Phase 2: Live in an environment, after the gate

- Only after the client-environment Phase 0 gate on the cross-account exchange has passed there, and
  SPEC-266's key and SPEC-267's API half are deployed: turn the flag on, sign in, and record in
  `docs/testing/e2e.md` that a sign-in stores `present`, a forwarded request carries the header and
  the API's carrier session runs, a forced refresh renews the context, and the outcome of an
  administrator deleting the test user's Identity Center session: whether the next refresh is refused
  (the identity goes `ended` and data routes answer `IdentitySignInRequired`) or keeps refreshing.
  Measure the sealed value's length and the ID token's there, and confirm both are inside FR-005's
  allowances. A check no signed-in session can run
  becomes a row in `docs/testing/owed.md`.
