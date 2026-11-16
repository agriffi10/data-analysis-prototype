---
type: Spec
id: SPEC-267
title: "The API Assumes the Carrier Role from a Sealed Context"
description: "Gives the API a third credential plane, declared per route: it unseals the identity context the portal server forwards, using the subject of the bearer it has just verified, assumes the carrier role with it, caches the session on the sealed value and the subject, answers a missing, refused or stale context with codes of its own and never 401, and keeps the context out of every record. No route declares the plane yet."
spec_status: Draft
depends_on: [SPEC-266]
arc: carrier
arc_order: 2
---

**Dependency notes:**
- **SPEC-266** creates the carrier role, the sealing key and the API's two environment variables.
  This spec builds after SPEC-266's second PR merges.
- **SPEC-268, the Phase 5 server-exchange spec** (sibling, being written) seals and forwards the context. The
  two specs meet at the *API / Interface Contract* below, which both sessions agreed on 2026-11-16.
  Either can merge first, because a request with neither header changes nothing and no route
  declares the plane. Andrew decided on 2026-11-16 that a refused Identity Center refresh leaves the
  context absent until the next sign-in. The server signals that case with `absent: signin`, and
  this spec answers it with `IdentitySignInRequired`.

## Overview

From Phase 5, a user's access to core datasets and to their own storage follows their Identity
Center identity rather than a tag on a shared role. The portal server exchanges the user's sign-in
for an Identity Center **identity context** and forwards it, sealed to that user, with each API
request. The API turns it into AWS credentials that carry the user's identity: it assumes one
shared **carrier role**, presenting the context, and Lake Formation and S3 Access Grants then decide
per user (`transition_plan.md` §3.5 steps 2 and 3, §3.6, §4.7). This spec builds that turn:
- A route can declare that it wants the carrier session.
- The API unseals the context only with the subject of the bearer it has just verified, so one
  user's context cannot ride another user's request.
- It reuses a session while that is safe.
- It answers a missing or stale context in a way the browser never mistakes for a lapsed sign-in.

No route declares the plane in this spec, so nothing a user sees changes. The specs that move
queries and storage onto the carrier flip routes one at a time.

## Scope

### In Scope

- `"carrier"` as a third value of a route's `plane`, the layer that serves it, and the rewrite of the
  *Two credential planes* decision that says there are two.
- Reading the two forwarded headers, unsealing with KMS under the verified bearer's `sub`, and
  calling `AssumeRole` with `ProvidedContexts`.
- The carrier-session cache, keyed on the sealed value and the subject.
- Three new error codes, their statuses, the generated TypeScript and the browser's wording.
- Keeping the sealed value and the plaintext context out of every span, log line and stack, and the
  decision record that §4.7's `error.stack` paragraph asks for.
- The image's build-time check that its botocore accepts `ProvidedContexts`.

### Out of Scope

- **Declaring the plane on any real route.** Queries on the Identity Center workgroup, the catalog on
  Lake Formation and presigning from `GetDataAccess` credentials each move in a later spec, each
  with its own premise to clear. For queries, that premise is SPEC-266 FR-003's owed probe. For
  presigning, it is the presign fence's clamp: a carrier session can have five minutes left while a
  presigned URL wants 900 seconds, so **`signing_client` refuses on a carrier route in this spec**
  (FR-001).
- **Sealing, forwarding, refreshing and stripping the headers at the pass-through**, and what a
  refused refresh does: the server-exchange spec.
- **Any IaC.** SPEC-266 owns the role, the key, the grant and the environment.
- **Retiring the portal role and its tags.** The user plane is unchanged.

---

## Functional Requirements

### FR-001: A route may declare the carrier plane, and a carrier route never falls back

#### Description:

`Route.plane` becomes `Literal["user", "api", "carrier"]`. **What the carrier needs travels on the
identity, never in a request-scoped global**, which `identity.py`'s own docstring forbids. The
router passes the request's headers to `for_request(caller, headers)`, and `UserIdentity` gains
three fields: `sub` (the verified bearer's `sub`, or `None`), `sealed_context` (the forwarded value,
or `None`) and `context_absent` (`"signin"`, `"unavailable"` or `None`). `sealed_context` is declared
`field(repr=False)`. `for_request` sets it on every route, and a frozen dataclass's default repr
prints every field, so any message that formats the identity would otherwise log a value that,
beside its own user's bearer, is an hour of that user's data. On a route that declares
`"carrier"`:
- `user_client` and `_RetryingClient`'s single expiry retry resolve to the carrier session from
  those fields;
- `signing_client` raises `PlaneViolationError`, a fault, for the reason Out of Scope gives;
- the plane is read from the current route, exactly as `planes.require` reads it today.

**A carrier route never falls back to the portal role.** With no usable context it answers one of
FR-004's codes. A silent fallback would serve data under the interim plane's rules on a route whose
owner moved it, and nothing would show it. The KMS `Decrypt` and the carrier `AssumeRole` are made
inside the identity layer on the execution role, as the portal-role assumption is, so no route gains
the API plane for them. `CARRIER_ROLE_ARN` and `IDENTITY_CONTEXT_KEY_ARN` are required **lazily**, on
the first carrier request, so an empty value (SPEC-266's switch off) never fails a cold start.
`errors.for_exception` maps each new exception explicitly, because an unmapped type falls through to
`InternalError`. **The *Two credential planes* decision is rewritten in place** for three planes,
with a dated History entry, and so is the `planes.py` module docstring.

#### Acceptance Criteria:

- [ ] A test asserts that every route in `contract.ROUTES` declares `"user"` or `"api"`, so this spec
  moves no route. The test names itself as the guard a route-moving spec edits.
- [ ] With a fixture route declaring `"carrier"`, a call on it is made with the carrier session's
  credentials. The test asserts that the STS stub saw an `AssumeRole` for `CARRIER_ROLE_ARN` and
  **none** for the portal role.
- [ ] On the same fixture route with neither header, no portal-role assumption is attempted, and the
  response is `IdentityContextUnavailable`.
- [ ] `signing_client` on the fixture route answers `IdentityUnavailable` (500), and no `Decrypt`
  is attempted.
- [ ] A plane value outside the three still raises on `planes_for`.
- [ ] With `CARRIER_ROLE_ARN` empty, the module imports, a user-plane route serves normally, and a
  carrier route answers `IdentityUnavailable` with a span reason naming the unset variable.
- [ ] Each new exception type has its own clause in `errors.for_exception`. A test raises each one
  through the router and asserts the code it maps to, so none falls through to `InternalError`.
- [ ] The decision file and `planes.py` describe three planes, the History entry is dated, and
  `sh scripts/gen-index.sh` has run.

### FR-002: The context is unsealed only with the subject of the bearer just verified

#### Description:

On a carrier route the API reads the headers in this order:
1. `x-identity-context-absent: signin` answers `IdentitySignInRequired`.
2. `absent: unavailable`, any other `absent` value, or neither header answers
   `IdentityContextUnavailable`.
3. A value in `x-identity-context` must be standard base64 of at most 4,096 characters. API
   Gateway's version 2 payload joins a repeated header into one comma-separated value, which then
   fails as not base64.
4. The bearer must carry a non-empty string `sub`. The verifier requires only `exp`, `iss` and
   `aud`, so this check is new, and it applies on a carrier route only.
5. The API calls `kms:Decrypt` with `KeyId` set to `IDENTITY_CONTEXT_KEY_ARN` and an
   `EncryptionContext` of exactly `{"purpose": "identity-context", "sub": <the verified sub>}`.

A value sealed for any other subject fails with `InvalidCiphertextException`, as KMS documents for a
mismatched encryption context. A value sealed under another key fails with `IncorrectKeyException`,
because `KeyId` is pinned. **Neither is ever 401**: the browser answers a 401 with a refresh and
then a sign-out.

| What happened | Code | Span reason |
|---|---|---|
| `absent: signin` | `IdentitySignInRequired` (403) | `context_absent_signin` |
| `absent: unavailable`, an unknown `absent` value, or neither header | `IdentityContextUnavailable` (503) | `context_absent` |
| Over 4,096 characters, empty, or not base64 (a comma-joined repeat included) | `IdentityContextMismatch` (403) | `context_malformed` |
| The bearer has no string `sub`, or an empty one | `IdentityContextMismatch` | `bearer_without_sub` |
| `InvalidCiphertextException`, `IncorrectKeyException` | `IdentityContextMismatch` | `context_unseal_refused` |
| Throttling, `KMSInternalException`, `DependencyTimeoutException`, a connection error | `ApiUnavailable` (503) | `context_key_unavailable` |
| **Any other** KMS error, including `AccessDeniedException`, `NotFoundException`, `DisabledException`, `KMSInvalidStateException` and `KeyUnavailableException` | `IdentityUnavailable` (500) | `context_key_fault` |

#### Acceptance Criteria:

- [ ] The KMS stub asserts the exact `Decrypt` parameters: the pinned `KeyId`, and the two-key
  encryption context with the verified `sub`.
- [ ] A bearer for user B with a value sealed for user A answers `IdentityContextMismatch`, and no
  `AssumeRole` is attempted.
- [ ] Each row of the table is driven once, and the test asserts both the code and the span
  reason. The last row is driven by an error code the table does not list by name, so the default
  is what is tested.
- [ ] A bearer without `sub` is still served on a user-plane route (asserted), so the new check
  narrows nothing outside the carrier plane.
- [ ] The raw sealed value is never a cache key or a logged value: the cache holds its SHA-256
  (FR-003), and FR-004 covers the logs.

### FR-003: The carrier session is assumed with the context and cached on the sealed value and the subject

#### Description:

The API calls `sts:AssumeRole` on the execution role with these parameters:
- `RoleArn`: `CARRIER_ROLE_ARN`;
- `RoleSessionName`: from the existing `role_session_name(username)`;
- `DurationSeconds`: 3600, the cap that role chaining sets;
- `ProvidedContexts`:
  `[{"ProviderArn": "arn:aws:iam::aws:contextProvider/IdentityCenter", "ContextAssertion": <plaintext>}]`;
- no `Tags` and no `Policy`.

Phase 0 measured that STS sets the session's expiry to the context's own when that comes first, so a
session is often minutes long. The code reads `Expiration` from the response and never assumes
3600.

**The cache key is `(sha256(sealed value), sub)`.** The server seals once per context, so the
sealed value is stable for a context's life and changes at each refresh. A refreshed context
therefore misses the cache, and a refresh that narrowed entitlements is honoured at once (§4.7). A
leaked sealed value presented with another user's bearer also misses, and it meets `Decrypt`. A hit
skips both `Decrypt` and `AssumeRole`. An entry is usable under the existing `_usable` rule. Expired
entries are evicted on each insert, so a warm container holds only live sessions. Contexts rotate
hourly, so without eviction the cache would grow with every user's every hour. The single expiry
retry re-assumes once, from the identity's fields, on an expired-credentials error.

| STS answered | Code | Span reason |
|---|---|---|
| `InvalidContextAssertion` | `IdentityContextUnavailable` (503): the server's next refresh fixes it | `context_expired` |
| Throttling, a connection error | `ApiUnavailable` (503) | `carrier_assume_unavailable` |
| **Any other** STS error, including `AccessDenied` and `RegionDisabledException` | `IdentityUnavailable` (500). STS says `AccessDenied` for a wrong trust policy, so it is a fault, never a denial (*Two credential planes*) | `carrier_assume_refused` |

#### Acceptance Criteria:

- [ ] The STS stub asserts the exact `AssumeRole` parameters, including that `Tags` and `Policy` are
  absent and `DurationSeconds` is 3600.
- [ ] Given a response `Expiration` four minutes out, the next plain request on the same identity
  reuses the entry with no STS call. Given an `Expiration` inside the `_usable` margin, it
  re-assumes. Both outcomes are asserted by STS call count.
- [ ] Three requests on one container: user A with context A, then user B with context A (refused,
  no cache hit), then user A with a new sealed value (a fresh assumption). The test asserts the STS
  and KMS call counts after each request, and the harness keeps one container's cache across all
  three.
- [ ] After an insert, no expired entry remains, asserted by count.
- [ ] Each row of the STS table is driven once, the last by an unlisted error code, and the test
  asserts both the code and the span reason.
- [ ] `lambdas/Dockerfile`'s build-time botocore check also asserts that `ProvidedContexts` is a
  member of STS `AssumeRole`'s input shape, so an image whose botocore predates it fails the build
  rather than every carrier request.

### FR-004: Three codes of their own, never a 401, and the context in no record

#### Description:

`ErrorCode` gains three codes:
- `IdentityContextMismatch` (403): the context cannot belong to this bearer, and a retry cannot fix
  it.
- `IdentitySignInRequired` (403): Identity Center refused a refresh, and only a new sign-in restores
  the context.
- `IdentityContextUnavailable` (503): not ready yet, or lapsed. The server retries or refreshes on
  its own.

None is 401, because a lapsed or absent context is not a lapsed session (§4.7). The existing
`IdentityUnavailable` keeps its 500 and its meaning, a fault in the identity layer's own
configuration. The TypeScript is regenerated from the contract, and the browser chooses its sentence
from the code:
- *Mismatch*: "Your data access couldn't be confirmed. Sign out and sign in again; if this keeps
  happening, contact your administrator."
- *SignInRequired*: "Your data access has ended for this session. Sign out and sign in again to
  restore it."
- *ContextUnavailable*: "Your data access isn't ready yet. Try again in a moment."

**The context is scrubbed, not merely unlogged.** `log-foundry`'s `end_event` attaches the formatted
exception chain to every failed span, walking `__cause__`, and a botocore error message can echo a
request parameter. So the identity layer catches every exception from the header parse, the
`Decrypt` and the carrier `AssumeRole`. It reads the AWS error code with `aws_error_code`, then
raises a fixed-message error **`from None`**, which breaks the chain so no original message reaches
a stack. This is the decision §4.7 asks for ("exempt that path, or scrub it explicitly"): **scrub
explicitly**. It is recorded as a new file under `docs/decisions/identity-and-access/`, which names
the accepted `error.stack` decision it narrows.

#### Acceptance Criteria:

- [ ] `contract.ERROR_STATUS` maps the three codes as stated, and `IdentityUnavailable` stays 500.
  The generated TypeScript carries the three codes, and the generation check is clean.
- [ ] A test asserts that no path in the carrier layer answers 401.
- [ ] The browser's wording table has the three sentences, and its exhaustiveness guard
  (`apiContract.guard.test.ts`) passes.
- [ ] A containment test is modelled on `test_stack_scrub.py`. It plants a recognisable sealed value
  and a recognisable plaintext context, and makes the KMS and STS stubs raise errors whose messages
  **echo both**. It drives every fault row of FR-002's and FR-003's tables, and **first asserts that
  a stack was captured on the span**, so the check cannot pass on a span that failed without one. It
  then asserts that neither string appears in any emitted log line, span attribute or stack, and
  that the AWS error code does appear. The refusal rows, which return rather than raise, are driven
  too, with the same absence assertions.
- [ ] That test is mutation-tested once: remove the `from None`, watch it redden on the echoed
  message, then revert.
- [ ] `repr(identity)` and `str(identity)` for an identity carrying the planted sealed value do not
  contain it (asserted).
- [ ] The scrub decision file exists, and `sh scripts/gen-index.sh` has run.

---

## API / Interface Contract

**Agreed with the server-exchange spec's session on 2026-11-16.** Once merged, this section is the
authority for the API's side.

```python
# lambdas/api/apicommon/carrier.py (new)
IDENTITY_CONTEXT_HEADER = "x-identity-context"          # standard base64 of the KMS CiphertextBlob
IDENTITY_CONTEXT_ABSENT_HEADER = "x-identity-context-absent"  # "signin" | "unavailable"
MAX_SEALED_CHARS = 4096
ENCRYPTION_CONTEXT_PURPOSE = "identity-context"         # EncryptionContext == {"purpose": ..., "sub": bearer_sub}
IDENTITY_CENTER_PROVIDER_ARN = "arn:aws:iam::aws:contextProvider/IdentityCenter"

# lambdas/api/apicommon/identity.py
@dataclass(frozen=True)
class UserIdentity:
    ...                                   # existing fields unchanged
    sub: str | None
    sealed_context: str | None = field(repr=False)   # never in a repr, an f-string or an assertion message
    context_absent: Literal["signin", "unavailable"] | None

def for_request(caller: Principal, headers: Mapping[str, str]) -> UserIdentity: ...

# Raised by the carrier layer, each mapped in errors.for_exception:
#   IdentityContextMismatchError    -> IdentityContextMismatch    (403)
#   IdentitySignInRequiredError     -> IdentitySignInRequired     (403)
#   IdentityContextUnavailableError -> IdentityContextUnavailable (503)
#   ApiUnavailableError             -> ApiUnavailable             (503, existing)
#   IdentityUnavailableError        -> IdentityUnavailable        (500, existing)
```

What the server side does (the server-exchange spec owns these):
- It seals with `kms:Encrypt` on SPEC-266's key, once per context, under exactly
  `{"purpose": "identity-context", "sub": <sub of the Cognito ID token it forwards as the bearer>}`.
  The plaintext is the raw identity context, `awsAdditionalDetails.identityContext`.
- It sends `x-identity-context` only while the session holds an unexpired context and the provider
  token is valid.
- Otherwise it sends `x-identity-context-absent`, and while the exchange is switched off it sends
  neither header.
- Its pass-through forwards only an allow-list of request headers, so a browser can set neither.
- The bearer and the headers stay within API Gateway's 10,240-byte limit on the request line and
  headers.

## Implementation Phases

### Phase 1: The plane

- `Route.plane` gains `"carrier"`; `UserIdentity`'s three fields, set in `for_request` from the
  headers; `planes_for` and the identity layer's resolution; `signing_client`'s refusal; the
  no-route-moves guard and the fixture route; the rewrite of the *Two credential planes* decision.

### Phase 2: Unseal, assume, cache

- `carrier.py`: the header order, `Decrypt`, `AssumeRole`, the cache and its eviction, both failure
  tables with their defaults, lazy configuration, the `errors.for_exception` clauses, and the
  Dockerfile check.

### Phase 3: Codes, wording, scrub, record

- The three codes, regenerated TypeScript, the browser wording; the scrub with `from None`; the
  containment test and its mutation run; the scrub decision file.
- One PR. It is inert: no route declares the plane.

### Phase 4: Record the end-to-end check as owed

- Nothing deployed can exercise the plane until a real route declares it, and only `main` deploys.
  So the end-to-end check is a row in `docs/testing/owed.md`, and it **gates the first spec that
  declares `"carrier"` on a real route**. The check runs with SPEC-266 applied with its switch on,
  against the stand-in instance or the client's test environment, and with the server-exchange spec
  landed. It passes when a signed-in request on that route comes back identity-enhanced
  (`ListCallerAccessGrants` answers on the session), and when a second user's bearer carrying the
  first user's sealed value answers `IdentityContextMismatch`. It is also the run that proves STS
  populates the trust policy's two Identity Center keys.
