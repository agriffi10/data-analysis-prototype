# Completed Spec — SPEC-195: The API's Auth Boundary

## What was completed?

The API knows who is asking, in a way the caller cannot influence. **Sign-in is untouched** — the
User Pool, Managed Login v2, Amplify in the tab and the Hosted UI round trip all behave exactly as
before — and **no feature is ported**: the browser still calls AWS directly.

It is a **verifier, not an OIDC client**. No code exchange, no refresh token, no session, no
cookie. The browser already holds an ID token; it now sends that token as an `Authorization`
bearer and the API takes the username from the verified claim. An earlier draft of this spec built
a backend-for-frontend with all three — that work is real and deferred, and a reader who saw it
should read this as the correction.

- **`cpcommon.auth`** — `VerifierConfig`, `Principal`, `verify_token`, and one private core holding
  the repo's single `jwt.decode`. The four Cognito entry points became callers of it, byte-identical.
- **`cpcommon.jwks`** — `CooldownJWKClient`: an explicit HTTP timeout, and a per-container cooldown
  on the cache-bypassing refetch an unknown `kid` triggers.
- **`lambdas/api/apicommon/`** and **`routes/`** — configuration, request context, the refusal
  surface, principal resolution, and the temporary `GET /_auth/whoami` probe.
- **`router.py`** — deny-by-default: a principal is resolved before any handler runs, and a route
  that has not declared itself public does not run, *including one that does not exist*.
- **`apps/portal/src/lib/apiClient.ts`** — the browser's one door: token per call, one refresh, one
  retry, and the arc's only retry.
- **Five `OIDC_*` environment values**, computed at root from resources Terraform already owns.
- **`.github/scripts/deploy-lambda.sh`** — packaging made to carry a subpackage. Out of scope as
  specced, and a prerequisite: `lambdas/api/` is this repo's first package-shaped function.

## The four defects that mattered, and every one was found by running something

**A provider outage answered 401.** `PyJWKClientConnectionError` subclasses `PyJWKClientError`, so
one broad handler folded an outage into "your token is bad". Worse, PyJWT raises that transport
type for exactly two causes — so a provider answering a proxy page, a JSON array, an empty key set
or failing TLS *all* arrived as ordinary verification failures. Measured at the router: four
provider faults, four 401s. Classification is now by what failed, not by exception type.

**The packaging dropped the package.** `cp lambdas/$NAME/*.py` is a flat glob. Reproduced before
fixing: a function laid out with `apicommon/` and `routes/` produced a package containing
`handler.py`, `router.py` and `conftest.py`. Green tests, green deploy, `ModuleNotFoundError` at
cold start — the shape that once broke real signups. The prune also never matched `conftest.py`,
so two functions had been shipping their pytest bootstrap.

**A Lambda could leave the fleet silently.** A directory is recognised as a Lambda by globbing it
*flat* for a top-level `handler`. Move that module into a subpackage — the layout this arc just
enabled — and every per-function assertion stops covering it. Measured: `api`'s handler moved into
`api/app/`, carrying an import of a layer its row does not attach, suite passed 188, exit 0.

**Guards that named a property they did not test.** Seven, across four review rounds: a validation
test that checked a block was *present* (weakening every condition to `true` left 21 tests green);
an instrumentation test that a `#` defeated; a header table using the placeholder `"x"`, so every
row refused because the *token* was bad rather than the header; a stack-scrub assertion that was
vacuous because no 401 path raises through the span; a credential-absence test that asserted about
a token it never sent; an algorithm pin measuring PyJWT's own defences rather than ours; and the
`ApiUnavailable` wording, whose rule could be deleted with the whole 2917-test suite still green.

## What was measured rather than argued

- **Parity: byte-identical across 40 cells** — four entry points by ten token shapes, captured from
  the pre-change module before it was touched, and re-verified after every later edit.
- **The built package cold-starts.** The real deploy block was run against the real `lambdas/api`,
  and the result imported with only the layer on `sys.path`: `/healthz` 200, an unknown path
  **401 not 404**, the refusal record carrying `reason`, `route`, `request_id` and no credential.
- **No function in the fleet imports a layer only from a sibling**, which is why the layer-scan
  wiring guard is structural — no behavioural test can distinguish the two scans today.

## Deliberately not done

**403 is never minted here** (SPEC-196 makes it reachable), **expiry is not distinguished on the
wire**, and **`verify_id_token_ignoring_expiry` is unreachable from `lambdas/api/`** — a synchronous
request is never late by construction. `GET /_auth/whoami` is scaffolding; SPEC-197 deletes it,
together with SPEC-196's probe, once §D of the acceptance script has been run.

## Help & guides: nothing to sweep, and that is verified rather than assumed

Everything this spec changed in the SPA is four files under `lib/` — `apiClient.ts`, its test,
`errorMessages.ts` and one guard. No feature, no screen, no route a user can reach; the only new
API route is a probe that SPEC-197 deletes. `helpContent.ts` is untouched, and nothing in it
became untrue.

## Owed

§D of `docs/testing/arc-b-api-container-e2e.md` is **not yet run** — and its load-bearing checks are
all negative, because a genuine token succeeds against an API that does not verify at all. Three
cannot be reached offline at any price: that the JWKS endpoint is reachable from the function's
network placement, that a browser preflight allows the bearer header, and that a genuinely expired
token is refused by the expiry check rather than by something earlier.
