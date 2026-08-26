# Spec: The SPA Container

**ID:** SPEC-194
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-192 (the runtime configuration document — its shape, its accessor and its required/optional classification; this spec renders and serves it, and defines none of it), SPEC-193 (the ECR repository, ECS cluster/service/task definition, target group and ALB listener this image runs inside), SPEC-140 (the response-headers policy and enforcing CSP this container must reproduce, and its verification rules), SPEC-141 (the per-class cache scheme, and the orphan class this spec retires), SPEC-186 (the `BUILD_VERSION` stamping convention — the stamp travels in the artefact, never in the environment), SPEC-138 (the ZAP baseline and `security-baseline.md`, the measuring stick for the header set), SPEC-162 (`VITE_ENVIRONMENT` — the flag document's environment key becomes a runtime value here)

## Overview

The SPA moves from CloudFront over an S3 origin to a container behind an ALB. Producing the image is
trivial — a Vite build served by nginx — and that triviality is the trap. **CloudFront was doing more
than serving files**, each job configured once in `infra/modules/app/cloudfront.tf` and then
invisible, and **every one of them fails silently when it is wrong**: a missing SPA fallback breaks
only deep links and only on reload; a wrong cache header lets a warm browser run last week's bundle
intermittently; a CSP whose `connect-src` omits one host breaks one flow days later (SPEC-140's own
record: the omitted Hosted UI domain broke fresh sign-in for a day); a health check that falls through
to `index.html` makes the load balancer call a broken container healthy and keep it in rotation.

This spec ships the Dockerfile, the nginx configuration, the entrypoint and the build/push/deploy
workflow — and for each CloudFront job either reproduces it or names the divergence out loud rather
than letting a reader assume parity. Two are deliberate divergences (`Server` removal, brotli). One is
a genuine improvement retiring a settled decision: the image **is** the file set, so SPEC-141's
`--delete` reconciliation pass and its accepted stale-root-object orphan class both cease to exist.

## Scope

### In Scope

- A **multi-stage Dockerfile** — Node build → nginx runtime — non-root, digest-pinned, `.dockerignore`.
- The **nginx configuration**: SPA fallback, per-class cache headers, SPEC-140's full security header
  set, gzip, the health endpoint, and the `include`-per-location discipline the `add_header`
  inheritance rule forces.
- The **entrypoint**: rendering `/config.json` and the CSP's `connect-src` from ECS task-definition
  environment variables at container start; refusing to start when a required variable is unset **or
  empty**.
- **Moving the CSP computation to root Terraform locals** (FR-006). `local.csp_connect_src` and
  `local.content_security_policy` live in `infra/modules/app/cloudfront.tf` today; they move to
  `infra/main.tf` and are passed into `module.app` and into SPEC-193's task-definition environment, so
  one computation feeds both delivery paths.
- The four **re-decisions** this move forces, each with its cost: HSTS `preload`, the `Server` header,
  brotli, and the honest 404 on `/assets/`.
- A **CI header/behaviour matrix** run against the freshly built image before it is pushed — the gate
  that makes every criterion above able to fail.
- `.github/workflows/deploy-spa-image.yml`: build, stamp, tag by commit sha, push to ECR, register a
  task-definition revision, update the service, **fail on a rolled-back deployment**.
- The **deploy-role IAM expansion** for the push/deploy half, as in-scope work per the CLAUDE.md infra
  rule — `architecture.md` → *Deploy-role IAM — adding a new resource type* is required reading first.
- Superseded markers at every site still claiming SPEC-141's orphan class and its "exactly one sync
  pass carries `--delete`" criterion.

> **Superseded by SPEC-193 PR 4 (2026-08-26).** `local.csp_connect_src` has ALREADY moved to
> root, with `api_origin` added, because the API's origin comes into existence there and the
> CloudFront bundle needs it before this spec runs. **Only `local.content_security_policy`
> remains to move.** `modules/app` now takes `csp_connect_src` as an input.

### Out of Scope

- **The VPC, ALB, ECR repository, ECS cluster, service, task definition, target group, ACM
  certificate and DNS record — SPEC-193.** The split is below; read it before assuming either half.
- **The runtime configuration document.** SPEC-192 owns its shape, its keys, the browser-side accessor
  and which keys are required. This spec renders and serves it and **must not add, rename or
  reinterpret a field**.
- The API, its token verification, role assumption, and any ported route — SPEC-195 → 200.
- Anything about how a user signs in. **Cognito, Managed Login v2 and Amplify-in-the-browser are
  unchanged by this arc**, which is why FR-006's `connect-src` still carries the Cognito hosts.
- **Bucket CORS for the new origin** — SPEC-198, with the presigned-bytes path it exists for. Until
  then, the browser's *existing* direct S3 calls fail preflight from the container origin, because
  both bucket CORS configurations allowlist `var.app_url` (the CloudFront origin) and localhost and
  nothing else. That is expected during this spec, not a container defect: CloudFront stays the
  working portal, and Phase 5's checks against the container are boot, headers, routing and sign-in —
  not file operations.
- **Retiring CloudFront.** `infra/modules/app`, the distribution, the static bucket and
  `deploy-app.yml` stay live and keep deploying on every push to `main` until **SPEC-202**. Two deploy
  workflows run side by side for the length of this arc, deliberately: the CloudFront origin stays the
  working portal while the container is being proved.
- Autoscaling, capacity providers, WAF, and the availability work `transition_plan.md` §4.6 warns the
  portal acquires with a load balancer. Real, and not this spec.
- Any change to the SPA's own source beyond what SPEC-192 made. This spec ships the bundle SPEC-192
  produces; it does not edit a component.

### Which half each spec owns

**SPEC-193 owns** the ECR repository, the ECS cluster/service/task-definition **resources**, the task
and execution roles, the ALB/target group/listener/ACM/DNS, `readonlyRootFilesystem` and the task-level
`volumes` + container `mountPoints` that make it survivable, the task definition's `environment`
**block**, the health-check **path** configured on the target group, the deploy-role grants to
**create** those resource types, and the placeholder API image that proves the pipeline.

**SPEC-194 owns** the SPA image, its nginx config and entrypoint, what the entrypoint *does* with those
environment variables and the container's refusal when one is unset or empty, the health-check
**endpoint** and the assertion that it matches 193's path, the writable-path **pair** the image needs
and the assertion that 193 mounts exactly it, the CSP computation's move to root locals, and the
deploy-role grants to **push an image and update the service**.

**SPEC-192 owns** which keys are in that environment block and what each means. Three specs touch the
same block and none of them owns all of it: 192 the key set, 193 the resource, 194 the rendering.

### What CloudFront does today, and who owns it after this spec

The cheapest defence against a silent loss. Every row is live in
`infra/modules/app/cloudfront.tf` today.

| CloudFront job | Owner | Parity? |
|---|---|---|
| 403/404 → `/index.html` with **200** | FR-002 | Reproduced at the root; **deliberately not** under `/assets/` |
| `Cache-Control` per class (SPEC-141, set by `deploy-app.yml`) | FR-003 | Reproduced exactly |
| `--delete` reconciliation + the stale-root-object orphan class | FR-003 | **Retired** — the image is the file set |
| Enforcing CSP | FR-005/006 | Reproduced; `connect-src` re-derived as a **superset** (+ the API host), shrinking per porting spec |
| HSTS | FR-007 | Reproduced **without `preload`** — re-decided |
| `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP, CORP | FR-005 | Byte-identical |
| COEP deliberately absent (ZAP 90004 accepted) | FR-005 | Still absent, still accepted |
| `Server` stripped | FR-008 | **Divergence.** `Server: nginx` remains, with `server_tokens off` |
| `x-amz-server-side-encryption` stripped | Nothing — **moot** | The S3 origin emitted it; there is no S3 origin and no route by which nginx could |
| gzip **and** brotli, automatic | FR-009 | gzip only — **divergence**, not papered over |
| TLS termination, HTTP→HTTPS redirect | SPEC-193 | Moves, not lost |
| Distribution invalidation on deploy | Nothing — **retired** | An image has no cache to invalidate |

---

## Functional Requirements

### FR-001: The image

#### Description:

A Node stage that installs and builds the workspace, and an nginx runtime stage carrying only `dist/`,
the nginx configuration and the entrypoint. Both base images pinned **by digest**, not tag — a tag is
mutable, so a rebuild of an unchanged commit can produce a different image, which makes "the sha
identifies what is running" false.

The runtime base is `nginxinc/nginx-unprivileged`, not stock `nginx` plus a hand-written `USER`: the
stock image's entrypoint writes `/var/cache/nginx` and binds `:80` as root before dropping privileges,
so a bare `USER` produces a container that fails at start for reasons that read as configuration
errors. The unprivileged image listens on **8080** as uid 101 by construction.

#### Acceptance Criteria:

- [ ] `docker build` succeeds from a clean checkout with no network access to anything but the pinned
      registries and the npm registry.
- [ ] Both `FROM` lines name an image **and a `sha256:` digest**. A build whose `FROM` carries a tag
      alone fails the CI matrix job (FR-011).
- [ ] `docker inspect` reports a non-root `User`, and `id -u` inside a running container is not 0.
- [ ] The final image contains no `node_modules`, no `.git`, no `*.env`, no `.env.example` and no test
      file. Asserted by a filesystem sweep in FR-011, not by reading the Dockerfile.
- [ ] `.dockerignore` exists and excludes `node_modules`, `.git`, `**/.env*`, `infra/`, `lambdas/` and
      `docs/`. A `.env` reaching the build context is a secret leak that no unit test can see.
- [ ] The image declares `org.opencontainers.image.revision` = the commit sha, from a build arg.
- [ ] The writable paths the image needs are exactly **`/tmp` and `/var/cache/nginx`** — rendered
      config output goes under `/tmp` and nginx's cache under the other — and the image runs unchanged
      with `readonlyRootFilesystem: true`.
- [ ] That pair equals SPEC-193 FR-005's mounted set, asserted by a test reading both — the same
      agreement FR-010 AC3 makes for the health-check path, and for the same reason: a mismatch applies
      green and produces a container that never starts, reported as a generic essential-container exit.
      The mounts are task-level `volumes` + `mountPoints`, SPEC-193's to write; `linuxParameters.tmpfs`
      is rejected on the Fargate launch type and is not an option for either spec.

### FR-002: SPA routing fallback, and the 200 that cannot be believed

#### Description:

Client-side routes must survive a direct load and a reload: `try_files $uri $uri/ /index.html;` at the
root, reproducing CloudFront's 403/404 → `/index.html` with a **200**.

**Carry the trap forward and say what changed.** Because that mapping answers 200, a *deleted* asset
still answers 200 — which is why CLAUDE.md forbids verifying a removal by status code and directs the
reader to `content-type` instead. The container **preserves that at the root** (a removed
`favicon.svg` still answers 200 with `text/html`) and **deliberately does not under `/assets/`**,
which gets `try_files $uri =404;` so a missing hashed chunk returns an honest 404. Today that chunk
returns `index.html` as `text/html` to a `<script type="module">` request, which fails the MIME check
anyway — more confusingly, and with no way to tell "removed" from "never existed".

**One accepted residual changes shape, and for the worse.** SPEC-141 records an open tab that
lazy-imports a chunk the delete pass removed. On CloudFront the bucket held the union of old and new
until that pass ran; a task serves exactly one image's file set, so during a rolling deployment a
browser holding the **old** shell routed to a **new** task 404s immediately and deterministically. The
`no-cache` shell means a reload recovers, as today. Accepted, and named here so it is not rediscovered
as a container bug.

#### Acceptance Criteria:

- [ ] `GET /files?prefix=alice/` returns **200** with `content-type: text/html` and the SPA shell.
- [ ] `GET /assets/index-DEADBEEF.js` (no such file) returns **404**, and the response is not HTML.
- [ ] `GET /nope.svg` returns **200** with `content-type: text/html` — the trap, preserved and pinned
      by a test so a later change to the fallback is visible rather than silent.
- [ ] `GET /index.html` and `GET /` return the same bytes.
- [ ] `absolute_redirect off` and `port_in_redirect off`: no response carries a `Location` naming
      `:8080`. A container behind an ALB that redirects to its own listen port sends the browser to a
      dead address.

### FR-003: SPEC-141's per-class cache headers, and the orphan class that ceases to exist

#### Description:

Reproduce SPEC-141's scheme exactly: content-hashed assets under `/assets/` get
`public, max-age=31536000, immutable`; the shell and every root-level file get `no-cache`;
`/config.json` gets `no-store` (FR-004). The rule is unchanged — **a content-hashed URL is immutable,
a stable URL must revalidate** — and so is the failure it prevents: with no `Cache-Control`, browsers
apply heuristic freshness to `index.html` and a returning user asks for a chunk that no longer exists,
producing a **white screen, not stale content**, on exactly the users whose cache is warm.
**Scope by path prefix, never by extension** — `dist/assets/` carries a `.ttf` a js/css rule would
miss, SPEC-141's own finding.

**The genuine improvement, and the settled decision it retires.** `deploy-app.yml` needs three
prefix-scoped sync passes because one pass cannot both write a single `--cache-control` and reconcile
deletions, and its single `--delete` is scoped to `assets/` — leaving an accepted orphan class of
stale **root-level** objects removable only by hand (`icons.svg`, removed by hand 2026-08-05, is the
first). **A container has neither problem.** The image is the file set: nothing to reconcile, no key
surviving a build, no pass ordering. Both the `--delete` pass and the orphan class disappear with
CloudFront — a settled decision retired by shipping, which needs saying at the sites that still claim
it (FR-012 AC7).

#### Acceptance Criteria:

- [ ] `GET /assets/<any hashed file>` returns `cache-control: public, max-age=31536000, immutable`.
- [ ] `GET /` and `GET /index.html` return `cache-control: no-cache`.
- [ ] `GET /favicon.svg` returns `cache-control: no-cache` — a root file is a stable URL.
- [ ] A deep-link fallback response (`GET /files`) returns `cache-control: no-cache`, not the assets
      value. The fallback is an internal redirect; a header set only in the root `location` and not
      inherited by the serving one is the exact silent failure FR-005 describes.
- [ ] No path returns an **absent** `Cache-Control`. The matrix job asserts presence per class, not
      merely correctness where present — an absent header is the original bug.
- [ ] `docs/decisions.md` § *Static-asset caching* and CLAUDE.md's SPEC-141 bullet each carry a
      superseded-in-part marker naming SPEC-194 (the container never had the class) and SPEC-202 (when
      the S3 delivery path carrying it is retired).

### FR-004: `/config.json`, rendered at container start

#### Description:

The entrypoint renders `/config.json` from ECS task-definition environment variables before nginx
binds its port, and nginx serves it with `Cache-Control: no-store`. **SPEC-192 owns the document** —
its keys, their meaning, the browser accessor and which are required. This FR owns rendering and
serving, nothing else. Three mechanics are load-bearing, each with a silent failure:
**(1)** render with `jq -n --arg`, never a heredoc — a heredoc produces a document that parses today
and breaks on the first value carrying a `"`, a `\` or a newline, presenting as a blank app;
**(2)** refuse to start on unset *or empty*, because shell expansion and `envsubst` both turn an
undefined variable into an empty string without complaint, and a container starting with an empty
required value serves a shell that fails every call; **(3)** render **before** nginx starts, so a
container that cannot render never becomes healthy and never enters the target group.

#### Acceptance Criteria:

- [ ] `GET /config.json` returns 200, `content-type: application/json`, and `cache-control: no-store`.
- [ ] The body parses as JSON and contains exactly the keys SPEC-192 specifies — no more, no fewer.
- [ ] A value containing `"` and `\` round-trips: the container is started with such a value and the
      served document still parses and yields the original string.
- [ ] With one SPEC-192-required variable **unset**, the container exits non-zero, its stderr names
      that variable, and nginx never listens.
- [ ] With that variable set to the **empty string**, the container behaves identically to unset. A
      check written as `[ -z "${VAR+x}" ]` passes the empty case and is the defect this criterion
      catches.
- [ ] `/config.json` is not reachable through the SPA fallback: with the rendered file removed, the
      path returns 404, not the shell with a 200.

### FR-005: SPEC-140's security headers, in nginx

#### Description:

Move the shipped response-headers policy into nginx: the enforcing CSP (FR-006), HSTS (FR-007),
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`, the `Permissions-Policy` string, COOP
`same-origin` and CORP `same-origin`. **`Cross-Origin-Embedder-Policy` stays deliberately absent** —
`require-corp` buys cross-origin isolation this app cannot use, at real risk to subresource loads.
ZAP alert 90004 therefore stays open **by the same decision**, already recorded in
`security-baseline.md`; do not "fix" it here.

**The trap that will otherwise eat these headers, silently.** nginx `add_header` directives are
inherited from the enclosing level **only when the current level defines none of its own**. FR-003
puts a `Cache-Control` `add_header` inside `location /assets/` — which, on its own, wipes every
security header from every asset response while the shell still looks perfect. Every location block
therefore `include`s one shared `security-headers.conf` snippet, and every `add_header` carries
`always` so the set survives the honest 404 FR-002 introduces.

#### Acceptance Criteria:

- [ ] The full header set is present on **each** of: `/`, a deep link, `/assets/<hashed file>`,
      `/config.json`, `/healthz`, and a 404 from `/assets/`. Six classes, asserted independently.
- [ ] Deleting the `include security-headers.conf` line from **any one** location block turns the
      FR-011 matrix job red. Verified by committing the violation, not by reading the config.
- [ ] `Permissions-Policy`, COOP and CORP values are byte-identical to
      `infra/modules/app/cloudfront.tf`'s, asserted against the strings in that file at the time of
      the build — not retyped from memory.
- [ ] No response carries `Cross-Origin-Embedder-Policy`.

### FR-006: The CSP `connect-src`, derived from Terraform and rendered at start

#### Description:

`connect-src` **is** the app's network surface, and on the day this container ships that surface is
**every host SPEC-140 enumerates, plus the API host** — because nothing has been ported yet. It
shrinks one entry at a time as the porting specs land, and **it never loses the Cognito hosts in this
arc**: Amplify keeps running in the browser, so the User Pool endpoint and the Hosted UI domain are
still fetched from. It must be **derived from Terraform variables** and must not be frozen into the
image: a baked `connect-src` carries one environment's hosts everywhere, which is exactly the
build-time-configuration failure SPEC-192 exists to end.

**Every entry, and the spec that removes it.** A reader who takes the end state for the start state
breaks sign-in; a reader with no removal owner leaves an entry in forever.

| Entry | Why the browser fetches it | Removed by |
|---|---|---|
| `'self'` | `/config.json`, the bundle | never |
| the API host | every ported route | never |
| `https://cognito-idp.<region>.amazonaws.com` | Amplify: token refresh, `RevokeToken`, User Pool API | **not in this arc** — the target-environment arc, with the provider |
| `https://<hosted-ui-domain>` | Amplify's authorization-code exchange `POST`s to `/oauth2/token` | **not in this arc** — as above |
| `https://cognito-identity.<region>.amazonaws.com` | the Identity Pool minting browser credentials | SPEC-202 |
| the two S3 bucket endpoints | SDK calls now; presigned bytes after SPEC-198 | never (presigned bytes stay) |
| `https://athena.<region>.amazonaws.com` | `features/catalog/` | SPEC-199 |
| `https://glue.<region>.amazonaws.com` | `features/catalog/` | SPEC-199 |
| `https://sqs.<region>.amazonaws.com` | the seven enqueue paths | SPEC-200 |

The seam: **the image owns the directives describing its own content** — `default-src 'self'` (the
live policy's first directive, and the one a reader enumerating "the interesting ones" drops),
`script-src`, `style-src`, `img-src`, `font-src`, `worker-src`, `object-src`, `base-uri`,
`form-action`, `frame-ancestors` and `upgrade-insecure-requests`, all properties of the bundle and
unchanged from SPEC-140 including Monaco's `style-src 'unsafe-inline'` and `worker-src blob:` — and
**the task definition supplies `connect-src`** as one variable, `PORTAL_CSP_CONNECT_SRC`.

**Both CSP locals move to root, and this spec is where they move.** `local.csp_connect_src` and
`local.content_security_policy` live in `infra/modules/app/cloudfront.tf` today; root `main.tf` passes
only their inputs (`aws_region`, the two bucket names, the Hosted UI domain). That placement was
already at odds with SPEC-140's own rule — *CSP built from **variables**, root locals, never module
outputs* — and it becomes untenable here for two concrete reasons: a root-level check cannot read a
local inside a module, so the byte-identity and superset criteria below would have no readable
referent; and **SPEC-202 deletes `infra/modules/app` outright**, which would orphan the computation the
container depends on. So this spec **moves** both locals to `infra/main.tf`, passes the assembled
policy string into `module.app` and the `connect-src` string into SPEC-193's task-definition
environment. It is a move, not a re-derivation: the strings are unchanged on the day it lands, the
CloudFront-served policy is byte-identical to what it emits today, and after SPEC-202 the surviving
referent is the same one both origins shared.

> **Superseded by SPEC-193 PR 4 (2026-08-26).** `local.csp_connect_src` has ALREADY moved to
> root, with `api_origin` added, because the API's origin comes into existence there and the
> CloudFront bundle needs it before this spec runs. **Only `local.content_security_policy`
> remains to move.** `modules/app` now takes `csp_connect_src` as an input.

SPEC-140's record is why this is an FR and not a line, and this arc does not retire that record — it
inherits it. **The omitted Hosted UI domain broke fresh sign-in for a day**, because the code exchange
is a `fetch`, not a navigation, and because **the failure is invisible to an already-signed-in
session**: a warm tab never redeems a `?code=`, so the portal looks perfect to whoever is testing it
while every new sign-in sits signed-out over a live Cognito session. That host is still fetched from
after this spec. Losing it while "verifying the CSP" against a signed-in browser is the single
highest-consequence mistake available in this file.

**Enumerate from the hosts the app fetches, not the AWS services it uses.** The corollary in the
other direction: the two Hosted UI *redirects* (`/oauth2/authorize` and `/logout`) are navigations,
which neither `connect-src` nor `form-action` governs — `form-action` restricts form submissions, and
Amplify assigns `window.location`. Do not infer a wider need from them than the one `fetch`.

#### Acceptance Criteria:

- [ ] **The image's nginx configuration, its templates, its snippets and its entrypoint contain no
      `amazonaws.com` literal, no bucket name, no region and no API hostname** — a `grep` over
      `/etc/nginx/**` and `/docker-entrypoint.d/**` in the built image finds none. Scoped to those
      paths deliberately: the bundle still ships `@aws-sdk/*` and `aws-amplify`, whose endpoint
      rulesets embed `amazonaws.com` by the thousand, so a whole-filesystem grep is unsatisfiable for
      the whole arc and would be "fixed" by deleting it. These are the files that could freeze a host
      into the image, which is what makes the criterion checkable and able to fail.
- [ ] Starting the container with two different `PORTAL_CSP_CONNECT_SRC` values produces two
      different `Content-Security-Policy` response headers from the same image digest.
- [ ] With `PORTAL_CSP_CONNECT_SRC` **empty**, the container exits non-zero and nginx never listens —
      not "starts and serves `connect-src ;`", which is a CSP that blocks every fetch and presents as
      a network outage.
- [ ] **The move is a move**: after it, `infra/modules/app/cloudfront.tf` declares neither local and
      `infra/main.tf` declares both; the policy string the distribution emits is byte-identical to the
      one it emitted before the move, asserted against the pre-change value rather than against a
      retyped copy of itself.
- [ ] The rendered policy's non-`connect-src` directives are byte-identical to root
      `local.content_security_policy`'s, `connect-src` excepted — one referent, readable from root,
      shared by the distribution and the container and surviving SPEC-202.
- [ ] **The value Terraform computes for the deployed task is a superset of root
      `local.csp_connect_src`**, asserted term by term against that local rather than against a
      retyped list — every host in it, plus the API host. A term dropped from it is a feature that
      stops working; the two Cognito terms are the ones whose loss a signed-in tester cannot see.
- [ ] A test asserts the deployed policy's `connect-src` contains **both** the `cognito-idp` host
      **and** the Hosted UI domain, by name. Stated separately from the superset check because they
      are the two entries a reader with the arc's end state in mind deletes on purpose, and the
      superset check would then be updated to match the mistake.
- [ ] The Hosted UI term agrees with `module.auth.user_pool_domain`. `infra/outputs.tf` already
      carries a drift check with exactly this reasoning (*"Sign-in would be blocked"*); the container
      path must be covered by it or by its own equivalent, so a domain change cannot leave one
      delivery path correct and the other broken.
- [ ] `envsubst` substitutes only the variables the entrypoint declares. `$uri`, `$host` and every
      other nginx runtime variable survive the render untouched — asserted by starting a container
      with an environment variable named `uri` set to a sentinel and confirming routing still works.

### FR-007: HSTS `preload` — re-decided

#### Description:

CloudFront emits `max-age=31536000; includeSubDomains; preload`. `preload` was flipped on to clear
Checkov `CKV_AWS_259` and is recorded as **inert** — browsers act on the preload list, entry needs a
manual hstspreload.org submission, and this repo's record says never to submit the `*.cloudfront.net`
name. Re-decide it for the real domain.

**SETTLED: `preload` is dropped**, `max-age=31536000; includeSubDomains` kept. Three reasons in order
of weight. (1) Emitting `preload` claims a submission this deployment has not made and does not
intend; a directive the deployment does not keep is the exact class of silent divergence this spec
exists to catch. (2) Preload is granted against the **registrable domain** and is close to
irreversible; the SPA and API are subdomains of a parent this repo does not own, so the claim commits
sibling services nobody asked. (3) The cost is zero — `CKV_AWS_259` is a **CloudFront** check and
after this spec no Terraform resource carries an HSTS setting at all, so dropping `preload` clears no
scanner and regresses none.

#### Acceptance Criteria:

- [ ] Every response carries `strict-transport-security: max-age=31536000; includeSubDomains` and the
      string `preload` appears nowhere in any response header.
- [ ] `security-baseline.md` gains a row recording the drop, its reasoning and the fact that it costs
      no finding — so a future reader does not re-flip it to clear a check that no longer exists.

### FR-008: The `Server` header — the divergence, named

#### Description:

SPEC-140 strips two headers at CloudFront, and only one of them is a decision here.
`x-amz-server-side-encryption` was the S3 origin's banner and there is no S3 origin: it has no route
into an nginx response, so it needs no directive and no criterion — an assertion about it could not
fail, and stating it as evidence would misrepresent a consequence as a control. `Server` is the real
one. SPEC-140 strips it at CloudFront (the S3 origin's banner reached viewers as `server: AmazonS3`).
**nginx cannot reproduce that with stock configuration.** `server_tokens off` hides the *version* and
nothing more — nginx still sends `Server: nginx`. Removing the header needs the third-party
`headers-more` module, which the official images do not ship.

**SETTLED: the header is not removed. `server_tokens off` is set and `Server: nginx` is accepted.**
The alternative is a third build stage compiling `ngx_http_headers_more_filter_module` against the
runtime base's exact nginx source, recompiled in lockstep with every base-image bump, where an ABI
mismatch stops nginx from starting. That is real maintenance coupling bought for a header that, with
`server_tokens off`, discloses only "nginx" — and the ZAP alert that motivated the CloudFront strip
(*Server Leaks Version Information*) fires on a **version**, so it does not regress.

Stated as an FR rather than a footnote precisely because a reader would otherwise assume parity. The
re-open trigger: if the client's security review objects to the banner, `headers-more` is the path and
FR-009's decision moves with it — both are the same "no third-party module compile stage" call.

#### Acceptance Criteria:

- [ ] `server_tokens off` is set, and no response header contains an nginx version number.
- [ ] Every response carries exactly `server: nginx`. Pinned by a test, so the divergence is a
      recorded fact rather than an assumed parity — and so that a later switch to `headers-more`
      is a visible diff.
- [ ] `security-baseline.md` carries the divergence as an accepted finding with this reasoning, and
      the ZAP diff in Phase 5 is read **per alert ID** to confirm no new *Server Leaks Version
      Information* row appeared.

### FR-009: Compression — gzip, and the brotli residual

#### Description:

CloudFront gzipped and brotli'd automatically. nginx must be told to, and **brotli is not in the
stock nginx build**.

**SETTLED: `gzip on` for dynamic responses, plus `gzip_static on` over `.gz` files produced in the
build stage; no brotli.** `ngx_http_gzip_static_module` ships in the official images (confirm with
`nginx -V` at build time; AC2 asserts the *behaviour*, not the build flag, so an absent module fails
loudly rather than silently re-compressing), so pre-compressing at build time costs one Dockerfile line and gives every asset a maximum-ratio artefact
with no per-request CPU. Brotli needs the same third-party compile stage FR-008 rejected, and
rejecting it once while accepting it once would be incoherent.

**The residual, stated rather than papered over:** brotli-capable browsers — effectively all of them —
receive gzip, so the JS bundle transfers roughly 15–20% larger than through CloudFront today. A
measurable regression in first-load bytes, accepted; it is not parity and this spec does not claim it.
The fix, if it matters later, is a brotli-capable image, arriving with FR-008's re-open.

#### Acceptance Criteria:

- [ ] A request for a `/assets/` JS file with `Accept-Encoding: gzip` returns
      `content-encoding: gzip`, and its body decompresses to the on-disk file.
- [ ] A `.gz` sibling exists in the image for every `/assets/` `.js` and `.css` file, and the served
      gzip body is byte-identical to that sibling — proving `gzip_static` is serving the
      pre-compressed artefact rather than re-compressing per request.
- [ ] A request with `Accept-Encoding: br` returns **no** `content-encoding: br`. The residual is
      pinned, so a future brotli-capable image is a deliberate change with a failing test to update.
- [ ] `/config.json` is **not** pre-compressed (it is rendered at start) and is still gzipped
      dynamically.

### FR-010: The health endpoint

#### Description:

The ALB probes an endpoint to decide whether a task enters and stays in rotation. It **must not fall
through to the SPA fallback**: with `try_files … /index.html`, any path the balancer probes returns
200 with the shell, so an entirely broken container reads as healthy and stays in service forever.
That failure mode is why this is its own FR. The endpoint is an **exact-match** location
(`location = /healthz`) returning a literal `ok` as `text/plain`, with `access_log off`.

#### Acceptance Criteria:

- [ ] `GET /healthz` returns 200 with `content-type: text/plain` and a body of exactly `ok`.
- [ ] `GET /healthz/` and `GET /healthzz` return `content-type: text/html` — the fallback, proving
      `/healthz` is a real endpoint and not a lucky 200. A criterion that only asserts
      "`/healthz` returns 200" passes on a container with no health endpoint at all.
- [ ] The path this FR serves and the target group's `health_check.path` in SPEC-193's module are the
      **same literal**, asserted by a test reading both. A mismatch means the ALB probes `/`, reads
      `index.html`'s 200 and calls every container healthy.
- [ ] A container started with a required configuration variable missing (FR-004) never answers
      `/healthz` at all, because nginx never starts.
- [ ] `/healthz` carries `cache-control: no-store` and the FR-005 header set.

### FR-011: The image behaviour matrix, in CI

#### Description:

Every criterion above is a response header or a status code, and nothing in the existing suites
observes either — no Vitest test sees nginx, no `pytest` sees a Dockerfile. Without a gate, all twelve
FRs are documentation. The build workflow therefore **builds the image, starts it with a fixture
environment, and asserts the full matrix — before pushing to ECR**, so a wrong cache header never
reaches a registry.

The matrix is a table of (path, expected status, `content-type`, `Cache-Control`, required header set)
over the six path classes in FR-005 AC1, plus the filesystem sweep (FR-001), the two-value CSP render
(FR-006) and the refusal cases (FR-004, FR-006).

#### Acceptance Criteria:

- [ ] The job runs on every PR touching the image, its config, the entrypoint or the workflow — not
      only on `main`. A gate that runs after merge cannot block anything.
- [ ] The job fails when any single one of these mutations is committed: an `include
      security-headers.conf` removed from one location; `/assets/`'s `try_files` changed to the
      fallback; the shell's `Cache-Control` removed; `= /healthz` changed to `/healthz`;
      a `FROM` digest replaced by a tag. **Each verified by committing the violation**, per this
      repo's rule that a guard is proved by making it fail, never by reading it.
- [ ] The job asserts on the **response**, never on the config file's text. Grepping the nginx config
      for `add_header` passes on a config nginx never loaded.
- [ ] The container under test is started with the same entrypoint the deployed one uses. A test that
      runs `nginx -t` and stops has not exercised FR-004 or FR-006.

### FR-012: Build, stamp, push, deploy

#### Description:

A new `.github/workflows/deploy-spa-image.yml`: build the image, stamp it, run FR-011's matrix, push
to ECR tagged by **commit sha only**, register a task-definition revision pointing at that tag, update
the ECS service, and wait for the deployment to stabilise.

**Never a mutable tag.** `latest` makes the running revision unidentifiable, makes a rollback a
rebuild, and makes "which commit is in production" unanswerable — the question SPEC-186 FR-005 built
the whole `BUILD_VERSION` mechanism to answer.

**`BUILD_VERSION` follows SPEC-186's rule, not its mechanism.** The rule is that the stamp travels **in
the artefact**, because an environment-borne version races whoever owns the environment map and names
the wrong commit when the infra workflow is path-filtered. Here the artefact is the image: the sha
arrives as a build **arg**, is baked as an image label (FR-001) and a `BUILD_VERSION` environment
variable inside the image, and the entrypoint passes it to the config renderer. Whether the served
document surfaces it is **SPEC-192's** call; this FR guarantees the value is present and correct.

**The deployment must be able to fail the workflow.** `ecs update-service` returns success the moment
the API accepts the request, so a container crashing at start rolls back while the workflow stays
green — a deploy reporting success over a service still running last week's image. The workflow waits
for `services-stable` and fails on a rollback.

**Deploy-role IAM is in scope** for the push/deploy half: ECR auth and layer/image push,
`ecs:RegisterTaskDefinition`, `ecs:UpdateService`, `ecs:DescribeServices`, and `iam:PassRole`
condition-scoped to `ecs-tasks.amazonaws.com`. `ecr:GetAuthorizationToken` **cannot be
resource-scoped** — the same non-scopable class as SPEC-139's two permanent plan-scan findings — so if
the rendered-plan Checkov scan flags it, it joins the accept list **keyed by check ID and resource**,
as a stated decision, never as a blanket widening.

#### Acceptance Criteria:

- [ ] The pushed image is tagged `${GITHUB_SHA}` and no other tag. `latest` appears nowhere in the
      workflow.
- [ ] The registered task-definition revision references the image by that sha tag.
- [ ] A deliberately broken image (entrypoint exits 1) makes the workflow **red**, not green — the
      criterion that distinguishes waiting for stability from firing and forgetting.
- [ ] `BUILD_VERSION` inside a running container equals the commit sha that built it, and equals the
      image's `org.opencontainers.image.revision` label.
- [ ] The workflow is serialized with a `concurrency` group and `cancel-in-progress: false`, on
      `deploy-app.yml`'s reasoning: two overlapping deploys of one service is the last-writer-wins
      outcome, and cancelling one mid-flight leaves a half-rolled service.
- [ ] The deploy role's rendered policy grants exactly these actions and no `Resource: "*"` beyond
      `ecr:GetAuthorizationToken`; `iam:PassRole` carries the `iam:PassedToService` condition. A
      `PassRole` without it lets the deploy role attach **any** role to a task.
- [ ] `deploy-app.yml` is **unmodified** and still deploys to CloudFront on every push to `main`. Its
      comment block gains one superseded-in-part note: the orphan class it documents is real for that
      workflow and does not exist for the container (FR-003 AC6), and both retire at SPEC-202.

---

## Data Model

The container's contract with its environment. **These are not `VITE_*` variables** — they arrive at
runtime from the ECS task definition (SPEC-193's resource), which is the whole point of SPEC-192.

```
# Required — the entrypoint exits non-zero, naming the variable, when unset OR empty.
PORTAL_CSP_CONNECT_SRC   # space-separated source list, from root local.csp_connect_src (moved there
                         # by FR-006) as a SUPERSET of its pre-move value: every host it carries,
                         # incl. both Cognito ones, plus the API host. Shrinks per porting spec.
                         # FR-006 names the removal owner for each entry.
<SPEC-192's required set> # rendered into /config.json. SPEC-192 names and classifies them; SPEC-193's
                         # task definition carries the block; this spec renders and refuses.

# Baked into the image at build time, not supplied by the task definition.
BUILD_VERSION            # the commit sha; FR-012.

# Optional, with a default in the image.
PORTAL_LOG_LEVEL         # nginx error_log level; default `warn`.
```

```
# Image layout (runtime stage). Rendered output lives under /tmp so the image runs
# unchanged with readonlyRootFilesystem: true (FR-001).
/usr/share/nginx/html/                      # the Vite dist/, plus .gz siblings
/tmp/config.json                            # rendered at start; served at /config.json
/tmp/nginx-conf/default.conf                # rendered from the template (NGINX_ENVSUBST_OUTPUT_DIR)
/etc/nginx/nginx.conf                       # includes /tmp/nginx-conf/*.conf
/etc/nginx/snippets/security-headers.conf   # included by EVERY location block (FR-005)
/etc/nginx/templates/default.conf.template  # connect-src is the only interpolation
/docker-entrypoint.d/40-render-config-json.sh
```

---

## Environment Variables

No new `VITE_*` variable. This spec removes the *need* for the build-time ones in this delivery path —
the image is built once and configured per environment — but deletes none of them, because
`deploy-app.yml` keeps building the CloudFront bundle from them until SPEC-202.
`apps/portal/.env.example` gains a note pointing at the runtime set above, so a reader landing there
does not conclude the container is configured the same way.

## File & Folder Structure

```
apps/portal/Dockerfile
apps/portal/.dockerignore
apps/portal/docker/nginx.conf
apps/portal/docker/default.conf.template
apps/portal/docker/snippets/security-headers.conf
apps/portal/docker/docker-entrypoint.d/40-render-config-json.sh
infra/main.tf                                                # + the two CSP locals, moved (FR-006)
infra/modules/app/cloudfront.tf                              # − the two CSP locals, + the policy input
.github/workflows/deploy-spa-image.yml
.github/scripts/spa-image-matrix.sh                          # FR-011's assertion table
infra/modules/base/policies/github-actions-deploy-spa-image.json.tftpl
docs/testing/arc-b-api-container-e2e.md                            # Phase 5
```

## Implementation Phases

### Phase 1: The image and the static half of nginx

- Multi-stage Dockerfile, digest-pinned, unprivileged runtime, `.dockerignore`, gzip pre-compression.
- `nginx.conf` + `default.conf.template`: fallback, the `/assets/` location and its honest 404, the
  cache classes, the health endpoint, `server_tokens off`, `absolute_redirect off`.
- `snippets/security-headers.conf` and its `include` in every location block.

### Phase 2: The entrypoint, `/config.json` and the CSP render

- `40-render-config-json.sh`: the required-variable check (unset **and** empty), the `jq -n --arg`
  render, the ordering guarantee, the `no-store` and not-reachable-through-the-fallback rules.
- The two CSP locals moved to `infra/main.tf`, passed into `module.app` and into SPEC-193's
  task-definition environment, with the byte-identity check against the pre-move policy string.
- The `connect-src` interpolation and the `envsubst` variable-scoping trap.

### Phase 3: The matrix gate

- `spa-image-matrix.sh`: the six path classes, the header set, the filesystem sweep, the two-value CSP
  render, the refusal cases. Wired in **before** the push step.
- Prove it by committing each of FR-011 AC2's five mutations in turn and confirming the job reddens.

### Phase 4: The pipeline and the deploy-role IAM

- `deploy-spa-image.yml`: build → stamp → matrix → push (sha tag only) → register revision → update
  service → wait for stable.
- `github-actions-deploy-spa-image.json.tftpl`, the `iam:PassRole` condition, and the plan-scan
  disposition for `ecr:GetAuthorizationToken` if it flags.

### Phase 5: Verification

Nothing offline observes a response header, a rolling deployment or a load balancer's opinion of a
container. These are real invocations against the deployed service, as a new section of
`docs/testing/arc-b-api-container-e2e.md` with exact paths, exact expected header values and the
fixture
environment.

- **Every FR-005 header on all six path classes, against the deployed ALB origin**, not a locally-run
  container. A local container proves the image; only the deployed one proves nothing between it and
  the browser rewrites, adds or strips a header.
- **The CSP, verified SPEC-140's way, rules unchanged.** A **report-only pass proves nothing about
  enforcement** — it never blocks, so a flow that "reported no violations" may have succeeded
  *because* the policy was inert. Verify with a **same-origin page script and a negative control**
  proving enforcement is live: CDP `Runtime.evaluate` bypasses page CSP entirely and reported
  `new Function` as allowed under `script-src 'self'`.
- **A fresh sign-in against the container origin, in a private window, is a required step and cannot
  be substituted.** **A signed-in pass never tests sign-in**: the code exchange is the only fetch to
  the Hosted UI host, a warm session never makes it, and a `connect-src` missing that host produces a
  portal that works for everyone already signed in and for nobody else — SPEC-140's recorded outage,
  exactly. Sign out, close the window, open a private one, complete the Hosted UI round trip, and
  confirm **zero CSP violations in the console** across the redirect back. A pass that begins at an
  authenticated `/files` has not tested this and must not be recorded as having done so.
- **Safari, once.** It refuses to evaluate a report-only policy naming no reporting endpoint — the
  blind spot no Chromium harness can surface. The tooling here is Chromium, so this step names the
  browser.
- **A deep link, cold, in a private window** — `/files?prefix=…`, `/explore`, `/query` — each
  returning the SPA, not a 404. Plus a `curl -I` per cache class, because devtools reports *effective*
  freshness rather than the header.
- **A rolling deployment observed**: deploy a change, keep an old tab open, confirm the shell
  revalidates and the app recovers on reload. FR-002's residual, watched rather than assumed.
- **The health check doing its job**: deploy an image whose entrypoint exits 1, confirm the ECS
  deployment rolls back **and the workflow goes red** — FR-012 AC3, live.
- **A ZAP baseline against the container origin**, diffed against `security-baseline.md` **per alert
  ID, never by total** (SPEC-140's rule, from the run where `CKV2_AWS_32` clearing and `CKV_AWS_259`
  appearing cancelled out at 305). Expect the `style-src 'unsafe-inline'` Medium and the COEP Info to
  persist by decision, and no new *Server Leaks Version Information* row (FR-008).
- **Owed, not discharged, because nothing offline can prove it:** that the ALB adds or drops no header
  of its own; that a browser honours `immutable` across a real deployment; and that a warm-cache user
  of the CloudFront origin is unaffected while both delivery paths run.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row; a delivery doc at
  `docs/spec-delivery/SPEC-194-the-spa-container.md`.
- **Three `decisions.md` entries**, then one digest line each in CLAUDE.md's Key Decisions:
  (1) *the nginx config reproduces CloudFront's jobs and three are divergences* — `Server` (FR-008),
  brotli (FR-009), `preload` (FR-007), each with its cost and re-open trigger, plus the `add_header`
  inheritance rule that makes the header set fragile in a way no config review catches;
  (2) *the image is the file set* — SPEC-141's `--delete` pass and orphan class retired, with the
  honest-404 improvement and the reshaped residual race;
  (3) *`connect-src` is supplied by the task definition, every other CSP directive is a property of
  the bundle and lives in the image* — the seam, why baking the whole policy would re-create the
  build-time-configuration problem SPEC-192 exists to end, why both CSP locals moved from
  `infra/modules/app/cloudfront.tf` to root (SPEC-140's own rule, a referent a root-level check can
  read, and a module SPEC-202 deletes), and the removal-owner table: the list starts as SPEC-140's
  plus the API host and shrinks per porting spec, the Cognito hosts surviving this whole arc because
  Amplify does.
- **Superseded markers**, in place, at every site still stating the old claim: `decisions.md`
  § *Static-asset caching* and § *Response headers / CSP* (the latter also for the CSP locals' new
  home); CLAUDE.md's SPEC-141 and SPEC-140 bullets;
  `docs/transition_plan.md` §4.6's table (its CloudFront-job rows now have owners); SPEC-141's own
  file for the "exactly one sync pass carries `--delete`" criterion; and `deploy-app.yml`'s comment
  block (FR-012 AC7).
- `ARCS.md`'s arc entry updated with what this spec found — in particular that the arc's open question
  2 (the `connect-src` derivation) is answered here and asserted finally in SPEC-202.
- `security-baseline.md` gains the FR-007 and FR-008 rows.
- No `component-inventory` row: this spec adds no service, hook or component. Record that explicitly
  rather than leaving it ambiguous.
- **Help sweep: nothing user-facing changes.** The container serves the same bundle at the same
  routes; the origin change is invisible to a user until SPEC-202 moves the domain. Recorded and
  skipped, not left ambiguous.
