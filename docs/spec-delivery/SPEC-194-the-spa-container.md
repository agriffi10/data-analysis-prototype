# Completed Spec — SPEC-194: The SPA Container

## What was completed?

`portal.dataquarry.app` serves the **real SPA** from a container behind the load balancer, built
and deployed on every push to `main`. CloudFront is still production and still the rollback; both
delivery paths run side by side, deliberately, until the cutover.

Nothing a user can see changes. What ships is the second delivery path, proved.

- **`apps/portal/Dockerfile`** — a Node build stage and an `nginx-unprivileged` runtime, both
  digest-pinned, plus a pinned scratch stage supplying `jq`. Non-root by construction, runs
  unchanged under `readonlyRootFilesystem` writing only `/tmp` and `/var/cache/nginx`, and
  pre-compresses every asset at build time.
- **`apps/portal/docker/`** — `nginx.conf`, the server template, the shared security-headers
  snippet template, and one entrypoint that refuses, then renders `/config.json` and the two nginx
  documents before nginx binds a port.
- **`.github/scripts/spa-image-matrix.sh`** — **189 checks** on responses, against a container
  started the way ECS starts it.
- **`.github/workflows/spa-image.yml`** (pull-request gate, path-filtered) and
  **`deploy-spa-image.yml`** (build → matrix → push → register → point → wait → assert).
- **`local.content_security_policy` moved to root**, joining `csp_connect_src`. `modules/app` takes
  the assembled string as an input.
- `push-placeholder-image.yml` and `Dockerfile.placeholder` are **deleted** — the pipeline replaced
  them, after it had run green on `main` once.

## The defect that mattered most, and it was found by review

**`PORTAL_CSP_CONNECT_SRC` and `PORTAL_LOG_LEVEL` were interpolated into nginx configuration
unvalidated**, and nginx configuration has no escaping mechanism the way `jq --arg` does. Measured:

```
connect-src: 'self"; add_header X-Pwned yes always; #'
→ Content-Security-Policy: … connect-src self
  X-Pwned: yes
```

`object-src`, `base-uri`, `form-action`, `frame-ancestors` and `upgrade-insecure-requests` silently
gone, an arbitrary header appended — on a container that **starts, reports healthy and enters the
target group**. The entrypoint's own comment argued for `jq -n --arg` over a heredoc for exactly
this reason and then did the unguarded thing thirty lines later. Both values are now validated
against what they may contain rather than scanned for what they may not.

## What was measured rather than reasoned

Every one of these contradicted a plausible expectation, and two contradicted a reviewer.

1. **`add_header` without `always`** leaves the `/assets/` 404 carrying **no** `Cache-Control` and
   **not one** security header, while the 200 beside it carries all of them.
2. **Responses generated before a location is resolved** — a malformed request line, a malformed
   header, an over-long URI — carried nothing at all. The set is a server-level floor now; the
   inheritance rule works in our favour there, so every per-location cache class is unchanged.
3. **`return 404;` with no body string** emits nginx's stock HTML page and ignores `default_type`.
4. **A 404's content-type follows the request's extension** (`application/javascript` for a `.js`),
   because nginx fixes it before `error_page` runs. So the criterion is "not HTML" — asserting "is
   `text/plain`" would redden truthfully and get weakened.
5. **`GET /assets/` returns 404, not 403** — a reviewer predicted 403. `try_files $uri =404` fails
   the slash-terminated file test and routes to the named location.
6. **A failing `/docker-entrypoint.d/*.sh` does abort the container**, despite the
   `find | while read` pipeline — so the refusal needs no escalation, and the kill-PID-1 fallback
   that had been drafted would have replaced a clean exit with SIGKILL of init.
7. **The base image ships a default site that also listens on 8080** with no security headers.
   Whichever parses first becomes the default server, so the file is deleted **and** the `conf.d`
   include dropped — either alone leaves it to include ordering.

## Deliberate deviations

- **`/.dockerignore`, not `apps/portal/.dockerignore`** (the spec's File & Folder Structure is
  wrong here). The build context is the repository root, so a file beside the Dockerfile is read by
  **nothing** — the secret-leak criterion would have been true on paper and false in fact, forever,
  with a green gate. The build stage asserts the exclusions from inside the context, where they can
  be seen; asserting on the final image cannot fail, because the runtime stage copies only `dist/`.
- **The security-headers snippet is a template**, not the static file the spec's layout shows. It
  must carry the CSP, and nginx cannot read an environment variable into a config value (`env` sets
  the worker's environment, not the parser's) while the root filesystem is read-only.
- **The base image's envsubst step is bypassed** — templates live outside `/etc/nginx/templates`,
  so it is a clean no-op — and the entrypoint substitutes an **explicit** list. That is what makes
  "`$uri` survives the render" a property of the code rather than of an undocumented base filter.
- **No `github-actions-deploy-spa-image.json.tftpl`.** Every action the pipeline calls is already
  granted, scoped and simulate-measured by the platform spec; a fourth policy restating them would
  be a second owner of one set of grants. A presence test replaces it, so a later narrowing reddens
  in review rather than at a registry push on `main`. FR-012 AC6's "no `Resource: "*"` beyond
  `ecr:GetAuthorizationToken`" is **replaced in writing** by the repo's measured-non-scopability
  rule, already discharged by the existing wildcard and PassRole tests.
- **`deployment_circuit_breaker.rollback` was NOT flipped**, and the plan's reasoning for flipping
  it was backwards. With `rollback = false` a tripped breaker leaves the deployment FAILED, so the
  wait never settles and the workflow is **red by default** — which is what the criterion wants.
  `rollback = true` would return the service to stable on the *old* revision and make the wait
  **succeed**. It is also the platform spec's resource.
- **FR-006 AC6's "superset" is now identity plus the API host.** `csp_connect_src` had already
  moved to root *with* `api_origin` in it, so the container's value is the CloudFront value, not a
  superset of it. Asserted as identity rather than assumed to degenerate.
- **The deploy workflow has no `paths:` filter.** The container must track `main` exactly as the
  bundle does, or "which commit is in production" stops having an answer. The PR gate is filtered.

## Did anything ship green and wrong?

**Yes — repeatedly, and every instance was caught by a fresh-context review rather than by the
gates.** Recorded because the pattern is the point:

- `absolute_redirect off` could be **deleted** with both gates green: the check asserted the absence
  of `:8080`, which `port_in_redirect off` suppresses independently. The real regression was an
  `http://` scheme downgrade behind an HTTPS-terminating balancer — invisible under the fixture's
  own `Host`, which is the one value that hides it.
- The CSP had **2 of 12** directives asserted; dropping `frame-ancestors` stayed 151/151 green.
- **Six of seven** required configuration keys were never proved required — the refusals fixed on
  one of them.
- Four probes handed the comparison a `${X:-clean}` default, so a docker command that **never ran**
  compared "clean" to "clean" and passed.
- Four workflow guards survived a `#` in front of the line they guarded, including the wait, the
  zero-count refusal and the settled-revision check.
- The byte-identity guard for the CSP move read **quoted strings only** (blind to an interpolated
  local appended to the list) and asserted no **join separator** — joined on a space, the policy is
  one malformed directive with every other one dropped by the browser and all twelve still present.
- The pipeline never checked its own **image swap**. `map` over a predicate that matches nothing
  returns the list unchanged with no error: register succeeds, the task is healthy, the wait
  returns, and every assertion passes — a green deploy of the placeholder.

Two defects were also found in the gate's own machinery: `refusal()` ran Docker in the
**foreground**, so a container that failed to refuse hung until the job timeout instead of
reporting — the failure a check exists to catch must not be the one that stops it reporting — and a
pid-suffixed container name let an interrupted run hold the port, surfacing as exit 1 with no
failing check.

## Verification

Offline: `pytest lambdas/` exit 0, `ruff`, `mypy`, `validate_docs.py`, eslint, prettier, and the
189-check matrix, green on a CI runner in ~65s. The CSP move planned as **"No changes"** against
real state.

Deployed and read back from `https://portal.dataquarry.app`: the full header set on five response
classes, HSTS without `preload`, no COEP, `server: nginx` with no version, all four cache classes,
`/config.json` at 21 keys and `version: 1`, `/healthz` returning exactly `ok`, the honest 404, gzip
served and brotli refused, and **all ten `connect-src` terms, the two whose loss a signed-in tester cannot see among them — the User Pool endpoint and the Hosted UI domain**. The
deploy reported `desired=1 running=1 rollout=COMPLETED` on the revision it registered, carrying 20
configuration keys. **The load balancer adds and strips nothing** — the one assertion no offline
gate can make.

Owed, and not dischargeable from this session: a fresh sign-in from a private window, the CSP's
negative control, Safari, a watched rolling deployment, and a deliberately broken deploy going red.
All in `arc-b-api-container-e2e.md` §C and `owed.md`.

> **Read this beside the ledger, not on its own (2026-09-02).** The arc script was deleted when Arc B closed; its durable checks are `docs/testing/e2e.md` §4.18 and its results are in `docs/testing/sessions.md`. **[`owed.md`](../testing/owed.md) is authoritative for what has since been run** — several of the items below have been discharged, and this doc is a record of the day it shipped rather than a live status.


## Component inventory

**No row.** This spec adds no service, hook or component — it ships a Dockerfile, nginx
configuration, a shell entrypoint and two workflows. Recorded explicitly rather than left
ambiguous.

## Help & guides

**Nothing to update, checked rather than assumed.** The container serves the same bundle at the
same routes; the origin change is invisible to a user until the cutover moves the domain. No label,
route, flag or affordance moved, and `helpContent.ts` names no origin, header or cache class.
