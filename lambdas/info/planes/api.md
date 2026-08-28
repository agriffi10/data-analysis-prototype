# API — the HTTP plane

One HTTP API, one `$default` route, one Lambda. It is **not** a control plane: no queue, no Step
Function, no verb fan-out. It verifies a bearer token and serves routes directly.

Arc B is porting the browser's direct AWS calls behind it. Today it serves `/healthz` and
`GET /v1/user-directory`; CloudFront is still production and the rollback.

## The shape

`lambdas/api/`

| Path | Holds |
|---|---|
| `handler.py` | the entry point — one span per request, and a name on the wire for every fault |
| `router.py` | matching, authentication, and the preflight answer |
| `routes/` | one module per route |
| `apicommon/` | the layer: contract, envelope, errors, identity, planes, principal, context, config |

## The fences

- **The API VERIFIES a bearer; it is not an OIDC client.** No cookie means no CSRF surface, but CORS
  is still required. Provider-agnosticism is five config fields, and the JWKS URL is built once at
  the **root**.
- **A key-retrieval fault is 5xx, never 401.** Refusals are byte-identical, and **expiry is not
  disclosed** — the browser refreshes once on any 401.
- **It assumes the SAME role with the SAME tags from the SAME claims** as the identity pool, which
  is why no policy was rewritten. The role is **reused, never minted**. `DurationSeconds` 3600 is a
  ceiling **both ways**: shorter caps every presigned link, longer is refused because this is role
  chaining.
- **Two credential planes, user by default, declared ON THE ROUTE — the failure fails OPEN.** A
  wrong client *succeeds* against the wrong identity. The plane is a **required field** on the
  contract's `Route`, derived per call, and a value that is neither of the two raises. The route is
  set on the way **in**: a warm container has no fresh context, so cleanup-on-exit alone lets the
  next request inherit a declaration.
- **An assume failure is a FAULT, never a denial.** STS says `AccessDenied` for a wrong trust
  policy, so the layer *wraps* it — that wrap, not the classifier's ordering, is what holds.
- **The credential cache is keyed on the WHOLE tag set** — never the username alone, which freezes
  membership until the next cold start, and never nothing, which serves B the session of A. Its
  margin is the life of one request, and it retries on a **new** client because boto3 binds
  credentials at construction.
- **The error shape is a machine CODE plus operator text nobody renders.** Wording is chosen
  client-side from the code; an unrecognised code resolves to the generic sentence.
- **The wire is declared in Python and the TypeScript is GENERATED.** CI refuses a regeneration
  diff, and the type vocabulary is **closed and never falls back**.
- **`$default` matches OPTIONS**, so API Gateway's own CORS responder never sees a preflight and the
  router must answer one **before authentication**. Only a browser enforces CORS, so `curl` cannot
  see this failing.
- **`@traced` is outermost everywhere EXCEPT here**: one decorator sits outside it, to turn an
  unpredicted fault into a declared code. A catch *inside* the span ends every failed request
  successfully and records the fault nowhere.

`cpcommon.jwks` is imported only by this plane's tests directly, but it is a lazy dependency of
`cpcommon.auth`, which ten planes use — it belongs to `cpcommon`, not here.

Full reasoning: `docs/architecture.md` → *The API's auth boundary*; the arc narrative is in
`docs/specs/ARCS.md`.
