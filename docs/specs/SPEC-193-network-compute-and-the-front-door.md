# Spec: The Network, the Compute and the Front Door

**ID:** SPEC-193
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-012 (the Lambda code/infra split every new function obeys), SPEC-107/125/137 (the `cpcommon` layer, and why a missing attachment is only visible at cold start), SPEC-138/139 (the scanner gates and the rendered-plan IAM scan this spec must not redden), SPEC-140/141 (the CloudFront response-headers policy and cache scheme SPEC-194 must reproduce — named here only so the boundary is explicit), SPEC-164 (`infra/modules/file-send/` as the module-shape model), SPEC-186 (`ENV_NAME` + the in-package `BUILD_VERSION` stamp the placeholder API must carry), SPEC-192 (the runtime-configuration accessors that will consume this spec's two origins)

## Overview

The portal is a static bundle on CloudFront whose browser calls AWS directly. The client environment
will not permit either half, so the SPA becomes a container behind a load balancer and every SDK call
moves behind an API. This spec builds **none of that application change**. It builds the ground it
stands on: a VPC, an ECS Fargate runtime, an Application Load Balancer, an ECR repository, an API
Gateway HTTP API in front of one Lambda, two subdomains of one registrable domain with their
certificates, and the deploy-role IAM that lets a `tofu apply` create all of it.

The API in this spec is a **placeholder** — `GET /healthz` and a router that 404s everything else. The
container image is a placeholder too. That is deliberate and it is the whole argument for this spec
existing separately. This repo's recurring production failures are IAM and propagation traps that
appear only on a real apply (SPEC-137's missing layer, SPEC-139's deploy-role lockout, the refresh
deadlock, the unknown-ARN-in-list drop), and five new AWS resource types land here at once.
Discovering those while also porting seventeen service files confuses two problems and makes the
second one's failures unreadable.

**No user reaches anything this spec builds, and the live application keeps working throughout.** It is
not quite untouched: three **additive** allowlist changes land here (FR-006), because the origins come
into existence here and every later spec's live checks need them. Both origins go on the Cognito app
client, `api_origin` joins CloudFront's `connect-src`, and API Gateway's CORS admits both. Nothing is
removed, so the CloudFront-served portal is exactly as capable after this spec as before it — and
without them there is no origin on which a ported feature works until SPEC-202, which is a rollback
that cannot be exercised and a container that cannot complete a sign-in.

## Scope

### In Scope

- `infra/modules/network/`: a VPC across two AZs, public subnets for the ALB, private subnets for the
  tasks, **no NAT gateway**, and the VPC endpoints that replace it (FR-001).
- The explicit decision that the **API Lambda is not in the VPC**, with an assertion that keeps it out
  (FR-002).
- `infra/modules/api/`: an API Gateway **HTTP API**, a proxy integration to one Lambda, CORS, access
  logging, a regional custom domain and its mapping (FR-003).
- The placeholder API function `lambdas/api/`, its `cpcommon` layer attachment, its deploy-matrix row
  and its structured-logging record (FR-004).
- `infra/modules/spa/`: ECR repository, ECS Fargate cluster, task definition, service, target group,
  ALB, HTTPS listener, HTTP→HTTPS redirect and health check (FR-005).
- Two subdomains of one registrable domain as Terraform variables, two regional ACM certificates,
  their DNS validation and the two alias records — plus the three **additive** allowlist changes that
  make the new origin usable and keep the old one working (FR-006).
- **Deploy-role IAM expansion as in-scope work** (FR-007) — five new resource families, so
  `architecture.md` → *Deploy-role IAM — adding a new resource type* and *Lambda code/infra split* are
  required reading before the first `.tf` line.
- The scanner re-baseline: the Checkov enforce list, the rendered-plan accept list, and
  `docs/security-baseline.md` (FR-008).

### Out of Scope

Everything a reader would reasonably assume travels with "we built the container platform":

- **Any SPA image content.** No Dockerfile beyond a placeholder, no nginx config, no SPA fallback, no
  SPEC-141 cache headers, no SPEC-140 security headers, no compression, no `connect-src` derivation.
  All of it is **SPEC-194**, and FR-005 carries the ownership table so neither spec assumes the other
  did it.
- **The image build/push/deploy pipeline.** SPEC-194 owns the workflow. This spec's placeholder image
  is pushed **by hand**, from the Verification script.
- **The BFF.** No session, no cookie, no OIDC, no DynamoDB session store, no KMS key, no
  `lib/returnPath.ts` change — SPEC-195.
- **Role assumption and the SigV4 call path** — SPEC-196. The placeholder function's role holds no
  `sts:AssumeRole` and no data-plane grant of any kind, and FR-004 asserts that.
- **The transport contract** — route shape, error shape, the TS↔Python agreement mechanism and the
  SPA's API client are SPEC-197. This spec's 404 body is a placeholder SPEC-197 may replace outright.
- **Any ported route or service.** Seventeen `*.service.ts` files keep calling AWS directly.
- **Retiring CloudFront, the Identity Pool, or `infra/modules/app`** — SPEC-202. There is no cutover in
  this spec, and the old stack keeps serving production the whole time.
- **A WAF, a rate limit, and a machine-facing authorizer.** Deferred by the arc.
- **Re-pointing `app_url`, or *narrowing* any allowlist.** Root `var.app_url` still names the
  CloudFront origin and is not changed here. FR-006's three changes are additive only — they widen
  three lists so both origins work at once; **SPEC-202 narrows all three** to the container origin at
  the cutover, and is where the CloudFront values are removed.

### What exists today, and which spec replaces it

| Today | Owner |
|---|---|
| `infra/modules/app` — S3 origin + CloudFront distribution + OAC | Untouched here; deleted in **SPEC-202** |
| SPEC-140's response-headers policy on the distribution | `connect-src` gains `api_origin` here (FR-006); reproduced in nginx by **SPEC-194**; removed with the distribution in SPEC-202 |
| SPEC-141's three prefix-scoped upload passes and cache classes | Reproduced in nginx by **SPEC-194** |
| `deploy-app.yml` (build → `s3 sync` → invalidate) | Replaced by SPEC-194's build → push → `update-service`; runs unchanged until then |
| Root `var.app_url` = the CloudFront domain, feeding the Cognito callback/logout lists and both buckets' CORS | Unchanged here; the app client's lists **gain** `spa_origin` beside it (FR-006). **SPEC-202** re-points `var.app_url` and removes the CloudFront entries |
| No VPC, ALB, ECR, ECS or API Gateway anywhere in `infra/` | **This spec** |

### Premises later specs must honour

Stated here because those specs are not yet written, and each is a decision rather than a detail.

1. **The API Lambda stays out of the VPC** (FR-002), and the reason is the endpoint set rather than any
   single unreachable host. SPEC-195 verifies a bearer token the browser already holds — there is no
   code exchange and no IdP token endpoint — so what it fetches on the public internet is the JWKS
   document, which unlike a third-party token endpoint *does* have an AWS interface endpoint available.
   The argument therefore rests on FR-002's three surviving grounds: an endpoint per AWS service the
   API calls, ENI attachment on the cold-start path, and the provider swap the later arc makes, after
   which the JWKS host is not an AWS one at all.
2. **ECR tags are immutable, so the tag is the git sha and `:latest` does not exist** (FR-005).
   SPEC-194's pipeline must tag by sha and repoint the task definition; a second push of one tag is
   refused by the registry, not silently accepted.
3. **The container listens on 8080 and runs as a non-root user with a read-only root filesystem.**
   nginx as root on port 80 is not available to SPEC-194 — the target group and the health check are
   already written against 8080.
4. **CORS is owned by API Gateway alone** (FR-003). No handler this arc writes may emit an
   `Access-Control-Allow-*` header; two sources produce two headers and the browser rejects the
   response while `curl` looks fine.

   > **Corrected while building.** The rule stands; this reason does not. AWS documents that *"If
   > you configure CORS for an API, API Gateway **ignores** CORS headers returned from your backend
   > integration."* So a handler-emitted header produces no duplicate and no browser rejection — it
   > is silently discarded, which is worse for a reader who checks: nothing fails, and the handler
   > grows a second source of truth that never reaches anyone. The rule's real ground is that two
   > places able to answer one question is how they come to disagree, and the one that wins here is
   > not the one a reader is looking at. Asserted in `lambdas/api/test_router.py`.
   >
   > Also true, and worth not re-deriving: the `$default`-route-catches-`OPTIONS` caveat applies
   > only when an **authorizer is attached**. There is none here, so "the handler is not invoked"
   > is correct as written.
5. **Authorization lives in the router, not in an API Gateway authorizer** (FR-008). SPEC-195 resolves
   the bearer to a principal before dispatch and denies by default, and SPEC-196 has to resolve that
   principal to a role inside the handler anyway — so an authorizer would be a **second reader of the
   same token**, able to disagree with the first about the very claim the role assumption is scoped by.
   The `$default` route compounds it: one integration serves every path, so a per-route authorizer
   cannot express the arc's route table without duplicating it.
6. **`spa_origin` and `api_origin` are constructed in root `locals` from the domain variables, never
   literals**, and re-exported as outputs. Root is where they must live: FR-006's Cognito list, FR-003's
   CORS list and SPEC-194's `connect-src` all consume them, and a module *output* fed into another
   module's list attribute is FR-007's unknown-ARN-in-a-list trap — a constructed string is known at
   plan time and cannot be. SPEC-192's runtime accessors, SPEC-194's `connect-src` and nginx copy,
   SPEC-195's audience wiring and SPEC-198's bucket CORS all take them from here.

---

## Functional Requirements

### FR-001: `infra/modules/network/` — a VPC with no route to the internet from private subnets

#### Description:

A VPC across **two** availability zones. Public subnets carry only the ALB and have a default route to
an internet gateway. Private subnets carry the ECS tasks and have **no default route at all** — there
is no NAT gateway in this design. The three destinations a task actually needs are reached by VPC
endpoints: interface endpoints for `ecr.api`, `ecr.dkr` and `logs`, and a **gateway** endpoint for S3.

**The S3 gateway endpoint is not optional and not an optimisation.** ECR stores image layers in S3, so
a pull fails with `CannotPullContainerError` when both ECR interface endpoints are present and the
gateway endpoint is missing — a failure that reads like an authorization problem and is not.

**The trade-off.** Interface endpoints bill per-AZ-hour plus data processed, a NAT gateway per-hour
plus per-GB; across two AZs at this traffic level the endpoint set is the cheaper of the two. That is
not the deciding argument. The deciding argument is that *no route to the internet* is a property a
reviewer checks in a route table, where *a NAT gateway nobody uses* is a claim someone re-argues.

**The residual.** Any future destination with no VPC endpoint is unreachable from a task, and it fails
as a **connect timeout**, not a 403 — the slowest failure to diagnose. Foreclosed today: ECS Exec
(`ssmmessages`, `ssm`, `ec2messages`), Secrets Manager, SSM Parameter Store, any runtime package fetch,
any non-AWS host. The remedy for an AWS destination is another interface endpoint; for a non-AWS one
there is none short of a NAT gateway, and that is a spec, not a patch. The BFF is unaffected because
FR-002 keeps it out of the VPC.

#### Acceptance Criteria:

- [ ] The VPC has `enable_dns_support` and `enable_dns_hostnames` both **true** — `private_dns_enabled`
      on an interface endpoint silently resolves to nothing without them.
- [ ] Two public and two private subnets exist, in two distinct AZs, keyed in `for_each` by **AZ name**
      so a reordering of `aws_availability_zones` does not recreate them.
- [ ] Public subnets set `map_public_ip_on_launch = false`.
- [ ] No private route table carries a `0.0.0.0/0` entry of any kind, and each carries the S3 gateway
      endpoint's **prefix-list** route. Asserted against the applied state, not the plan. Both halves
      matter and the count does not: associating the gateway endpoint *adds* a route, so "exactly one
      route" fails at the same step that proves the ECR pull works, and the repair a reader reaches for
      — dropping the association — breaks the pull the endpoint exists to enable.
- [ ] `aws_vpc_endpoint` resources exist for `com.amazonaws.${region}.ecr.api`,
      `…​.ecr.dkr` and `…​.logs`, all `Interface`, all `private_dns_enabled = true`, all placed in the
      private subnets, all attached to an endpoint security group that allows 443 **from the task
      security group only**.
- [ ] An `aws_vpc_endpoint` of type `Gateway` for `com.amazonaws.${region}.s3` exists and its
      `route_table_ids` set **equals** the set of private route-table ids. A gateway endpoint
      associated with the wrong table applies green and does nothing.
- [ ] There is no `aws_nat_gateway` and no `aws_eip` anywhere in `infra/` — a repo-wide grep asserts it,
      so a later "quick fix" cannot reintroduce one without deleting the assertion.

### FR-002: The API Lambda is not in the VPC

#### Description:

A reader arrives expecting the backend to sit in the private subnets. It does not, and the reason has
to be written where the next person finds it.

Every service the API calls — DynamoDB, S3, STS, SQS, Athena, Glue, Cognito — is reachable on a public
endpoint from a Lambda with no `vpc_config`. Attaching it would need a further interface endpoint per
service (or the NAT gateway FR-001 declines) and would put ENI attachment on the cold-start path, for a
function whose only non-AWS fetch today is SPEC-195's JWKS read. **That fetch is not the argument** —
Cognito's JWKS is served from a host an interface endpoint covers, so it would survive VPC attachment.
The argument is the endpoint-per-service cost, the cold start, and the provider swap the later
target-environment arc makes: after it, the JWKS host is a third party with no AWS endpoint at all, and
a function inside these subnets would stop verifying tokens with no code change to blame. The VPC
exists for the **container**, not for the function.

#### Acceptance Criteria:

- [ ] `aws_lambda_function` in `infra/modules/api/` has **no** `vpc_config` block, asserted by a test
      that greps the module rather than by reading the plan — adding one later applies cleanly and
      shows up only as latency, until the provider swap turns it into a JWKS fetch that times out.
- [ ] `infra/modules/api/` declares **no** variable fed by any `infra/modules/network/` output, and root
      `main.tf` passes none. The two modules are unrelated by construction.
- [ ] No `aws_security_group` appears anywhere under `infra/modules/api/` — a grep asserts it, on
      FR-001 AC6's model. A function outside the VPC has nothing to attach one to, so a security group
      appearing there is the first half of an attachment somebody started; the guard makes that
      visible instead of leaving a resource nobody can explain.

### FR-003: `infra/modules/api/` — the HTTP API, its integration, CORS and its custom domain

#### Description:

An API Gateway **HTTP API** with a `$default` route to an `AWS_PROXY` integration (payload format
2.0) targeting one Lambda function, a `$default` stage with `auto_deploy` and access logging, CORS
configured on the API, a **regional** custom domain, and an API mapping at the empty path.

One function serves every route (arc decision); routing is internal. The 29-second integration ceiling
is **not raisable** on an HTTP API — restated here so nobody spends a session on it.

**CORS admits both origins and no credentials.** Both, because the container and the CloudFront bundle
are each a real origin for the length of the arc — the container is where the ported features are
proved and CloudFront is the rollback, and an allowlist naming one of them makes the other an app that
loads and can do nothing. No credentials, because the arc's re-scope removed the session cookie the
credentialed configuration was written for: SPEC-195 sends the ID token as an `Authorization` bearer,
which is not a credential in the CORS sense, so `allow_credentials = true` would grant a capability
nothing uses while forcing the exact-origin echo to be load-bearing for a browser rule that no longer
applies. SPEC-202 narrows the list to `spa_origin` alone.

#### Acceptance Criteria:

- [ ] `cors_configuration` sets `allow_origins = [spa_origin, var.app_url]` — exact origins, never
      `"*"`, and `var.app_url` omitted when it is `""` (its default), matching the ternary
      `modules/auth/cognito.tf` and `modules/data/s3.tf` already use for the same variable.
      `allow_credentials = false`, `allow_methods` covering the verbs the arc will use, `allow_headers`
      including `content-type` and `authorization`, and a non-zero `max_age`. `allow_credentials` with
      `allow_origins = ["*"]` is rejected by every browser while applying green — the pairing is the
      defect, and this configuration avoids it on both counts.
- [ ] The Lambda permission is scoped with `source_arn = "${aws_apigatewayv2_api.api.execution_arn}/*/*"`,
      not `"*"`.
- [ ] Access logs are written to a dedicated CloudWatch log group with 14-day retention, matching the
      control planes. HTTP APIs need **no** account-level CloudWatch Logs role — a reader arriving from
      REST APIs will look for one and must not add it.
- [ ] `aws_apigatewayv2_domain_name` uses a **regional** endpoint type with a certificate in
      `var.aws_region`. The us-east-1-only certificate rule is CloudFront's and does not apply here.
- [ ] A live `OPTIONS` preflight carrying `Origin: <spa_origin>` returns exactly **one**
      `access-control-allow-origin` header, equal to that origin, and **no**
      `access-control-allow-credentials` header. Repeating it with `Origin: <var.app_url>` returns one
      header equal to *that* origin — the echo proving both entries are live, where a single-origin
      list answers only one of the two.
- [ ] The same preflight carrying a foreign `Origin` returns **no** `access-control-allow-origin`
      header. This is the criterion that can fail: a `"*"` configuration passes the previous one.

### FR-004: The placeholder API function

#### Description:

`lambdas/api/handler.py` — Python 3.12, the `cpcommon` layer attached, an internal router, and nothing
else. `GET /healthz` returns a fixed body; every other path returns 404. It performs **no AWS call**,
holds **no session**, and contains **no business logic**.

It is not inert, and that is the point of building it now: it proves the Lambda pipeline this arc
leans on — deploy matrix, layer attachment, env contract, log record. SPEC-137 shipped instrumented
code whose layer attachment was missing while every offline gate passed (`conftest.py` puts the layer
on `sys.path`; `update-function-code` succeeds against a function that cannot import). Only a real
invocation sees it.

#### Acceptance Criteria:

- [ ] `GET /healthz` returns 200 with `{"status": "ok", "version": "<build sha>"}`, where the sha comes
      from the in-package `BUILD_VERSION` file (SPEC-186 FR-005), not from an environment variable.
- [ ] Any other method or path returns 404 with a JSON body. SPEC-197 may replace the shape; this spec
      claims only that the router exists.
- [ ] The function's execution role holds **exactly** the CloudWatch Logs write grants and
      `sqs:SendMessage` on the logs queue — zero statements naming S3, DynamoDB, STS, Athena, Glue,
      Cognito or any other queue. Asserted against the rendered policy.
- [ ] The function's environment carries the six `cpcommon._REQUIRED_VARS` values, `LOGS_QUEUE_URL`,
      and `ENV_NAME` from `var.environment`. `cpcommon.config` resolves lazily, so an unset one fails at
      first read rather than at import — the env is complete anyway, so SPEC-195 inherits no surprise.
- [ ] A row `{ name: api, layer: false, polars: false, tbcommon: false, cpcommon: true }` exists in
      `deploy-lambdas.yml`'s matrix, and `lambdas/test_deploy_matrix*.py` passes — that test joins the
      matrix against what each function imports and is the gate SPEC-137 lacked.

> **Corrected while building — the file and the shape are both wrong.** The function table moved out
> of `deploy-lambdas.yml` into **`.github/lambda-functions.json`**, and its rows are
> `{"name", "layers": [...]}`, not the five-flag shape above. The row this spec adds is
> `{"name": "api", "layers": ["cpcommon"]}`. `lambdas/test_deploy_matrix.py` reads the JSON file, so
> the criterion's *gate* is intact — only its description of where the row goes was stale. A session
> handoff recorded this correction as already written into the spec; it was not, which is why it
> survived to be found here.
- [ ] One invocation produces one span in `logs/service=api/…/data.jsonl` with `env` and `version`
      populated and neither empty nor `0.0.0`.
- [ ] `lambdas/api/` is added to `pyproject.toml`'s **blocking** `[tool.mypy]` path, not the
      report-only one. It is new code with no legacy to ratchet through, and that block is the only
      home of the ratchet path.
- [ ] `ruff check lambdas/` is clean, and the module carries **no inline comments** and a Google-style
      docstring on every callable (`best-practices/python/python.md` §14).

### FR-005: `infra/modules/spa/` — the container runtime and the load balancer

#### Description:

ECR repository, ECS Fargate cluster, task definition, service, target group, ALB, an HTTPS listener,
an HTTP listener that only redirects, and a health check. The image is a placeholder.

**Who owns which half** — written out because a gap here is invisible until a deploy.

| Half | Owner |
|---|---|
| ECR repository, its lifecycle policy, immutability, scanning | **SPEC-193** |
| Cluster, task definition, task + execution roles, service, autoscaling absent | **SPEC-193** |
| ALB, listeners, redirect, target group, health-check *configuration* | **SPEC-193** |
| Security groups and subnet placement | **SPEC-193** |
| The `Dockerfile`, the nginx config, and what `/healthz` actually serves | **SPEC-194** |
| The build → push → `update-service` workflow | **SPEC-194** |
| The port (8080), the non-root user and the read-only root filesystem | **SPEC-193 decides; SPEC-194 must honour** |
| The task-level `volumes` and container `mountPoints` for the writable paths | **SPEC-193**, at the pair SPEC-194 declares (`/tmp`, `/var/cache/nginx`) |
| The task definition's `environment` **block** — the keys, and their values from Terraform | **SPEC-193** |
| What the entrypoint *does* with those variables, and its refusal when one is missing | **SPEC-194** |
| Repointing the task definition's image tag on each deploy | **SPEC-194** |

#### Acceptance Criteria:

- [ ] The ECR repository sets `image_tag_mutability = "IMMUTABLE"`, `scan_on_push = true` and AES256
      encryption, and carries a lifecycle policy retaining a bounded number of images.
- [ ] The task definition declares **two distinct roles** — an execution role holding only the ECR
      pull and log-write grants, and a task role holding **nothing at all**, because the SPA container
      makes no AWS call. A single role used for both is a finding, not a simplification.
- [ ] The container definition sets `readonlyRootFilesystem: true` and a non-root user, and the two
      paths the image must write are supplied as task-level `volumes` with matching container
      `mountPoints`. **`linuxParameters.tmpfs` is not available here** — it is rejected on the Fargate
      launch type and `RegisterTaskDefinition` fails outright, so the mechanism is `volumes` +
      `mountPoints`, not a tmpfs block.
- [ ] The mounted pair is exactly **`/tmp` and `/var/cache/nginx`**, equal to the writable-path set
      SPEC-194 FR-001 AC7 declares, asserted by a test reading both specs' values — the same agreement
      SPEC-194 FR-010 AC3 makes for the health-check path. A mount set that misses one of them produces
      a container that never starts under `readonlyRootFilesystem: true`, and the ECS event reads as a
      generic essential-container exit.
- [ ] The task definition carries an `environment` block holding SPEC-192's runtime-configuration key
      set plus `PORTAL_CSP_CONNECT_SRC`. **This spec owns the block; SPEC-192 owns which keys are in it
      and SPEC-194 owns what the entrypoint does with them** — it is the fifth wiring point SPEC-192
      FR-008 names, and its agreement test is re-pointed at this resource. `PORTAL_CSP_CONNECT_SRC` is
      the root local SPEC-194 FR-006 moves out of `infra/modules/app/cloudfront.tf`, passed through the
      same block, so one computation feeds both delivery paths.
- [ ] **`appUrl` in that block takes `local.spa_origin`, never `var.app_url`** — the one key whose
      value this spec must state, because both are plausible URLs and the wrong one fails only in the
      browser. Amplify builds `redirectSignIn`/`redirectSignOut` from it (`lib/amplify.ts`), so a
      container serving `appUrl = var.app_url` sends a sign-in *started on the container* back to the
      CloudFront domain: the container never receives the `?code=`, which is exactly the fresh
      sign-in-against-the-container-origin step SPEC-194's verification calls unsubstitutable. Root
      `var.app_url` is unchanged and keeps feeding the CloudFront build (FR-006 adds `spa_origin` to
      the app client's lists beside it, so both origins complete a round trip); SPEC-202 FR-002 reads
      this value back as a precondition and calls a disagreement a defect in this spec.
- [ ] `platform_version = "1.4.0"` (or later) is pinned explicitly. On 1.3.0 the image pull used a
      separate Amazon-owned ENI to which VPC endpoints did not apply, so FR-001's whole design silently
      does not hold.
- [ ] The service runs in the **private** subnets with `assign_public_ip = false`; the load-bearing
      assertion is FR-001's route table, not this flag.
- [ ] The deployment circuit breaker is **enabled with rollback disabled**. With rollback enabled and
      no previous good task set, a missing image reads as a rollback rather than as
      `CannotPullContainerError`. SPEC-194 may enable rollback once a good task set exists.
- [ ] `var.spa_desired_count` defaults to **0**, so the first apply creates a service before any image
      exists; Verification pushes the placeholder and raises it.
- [ ] The ALB is internet-facing in the public subnets with `drop_invalid_header_fields = true`,
      `enable_deletion_protection = true`, and access logging to the existing admin bucket under
      `alb-access-logs/`. That prefix requires the **first** bucket policy on the admin bucket, granting
      only the principal from the `aws_elb_service_account` data source; it must contain **no** `Deny`,
      or the deploy role's refresh read stops working and every plan proposes a destructive recreate.
- [ ] The HTTPS listener uses `ELBSecurityPolicy-TLS13-1-2-2021-06` or stricter and the SPA
      certificate; the HTTP listener's only action is a 301 redirect to HTTPS.
- [ ] The target group is `target_type = "ip"` on port 8080, health check path `/healthz`, matcher 200.
- [ ] The ALB security group allows 80 and 443 inbound and egresses **only** to the task security group
      on 8080; the task security group ingresses **only** from the ALB security group on 8080 and
      egresses 443 to the endpoint security group and to the S3 gateway endpoint's **managed prefix
      list** (a CIDR egress rule does not match gateway-endpoint traffic).

### FR-006: Two subdomains, two certificates, two records — and the three allowlists that admit them

#### Description:

The SPA and the API are separate hosts, and they are subdomains of **one** registrable domain. That is
now a **preference, not a requirement**: the arc's re-scope removed the session cookie whose
`SameSite=Lax` reach was the original argument, and SPEC-195 sends a bearer token which is same-site
about nothing. What survives is ordinary — one certificate authority relationship, one zone to
delegate, one name for a client's DNS team to reason about, and a `spa_origin`/`api_origin` pair that
differs in one label. The parent domain is an environment fact and arrives as a Terraform variable —
never a literal in a `.tf` file.

**The coupling this spec exists to unblock.** `transition_plan.md` §4.6 records it as the hosting
workstream's one hard dependency on the auth phases: the Cognito app client's callback and logout URLs
must match the new origin **exactly**, and `appUrl` carries the same value — so the final origin must
be known before auth configuration is finalised. This spec makes it known.

**And it admits it, in three places, additively.** The origins existing as outputs is not enough: until
something allows them, the container cannot complete a sign-in and the CloudFront bundle cannot reach
the API, which leaves the five specs between here and SPEC-202 with no origin on which a ported feature
works. All three changes **add** an entry beside the existing one and remove nothing, so CloudFront
keeps working exactly as it does today and stays a real rollback. Root `var.app_url` is unchanged; the
narrowing is SPEC-202's, and it is deliberately the last thing that happens in the arc.

#### Acceptance Criteria:

- [ ] Root variables `parent_domain`, `route53_zone_id`, `spa_subdomain` (default `portal`) and
      `api_subdomain` (default `api`) exist; `parent_domain` and `route53_zone_id` have **no default**,
      so an unset value fails at plan rather than building something against an empty string.

> **Measured on the real run.** The absent default does not do this, and the criterion's own mechanism
> is what fails. A missing default fails only when the variable is genuinely *absent* — and an unset
> GitHub repo variable does not arrive absent. `${{ vars.X }}` renders as the **empty string**, which
> satisfies a required variable. Measured on OpenTofu: unset → `not set, and has no default value`;
> `TF_VAR_parent_domain=""` → **plans clean**, `var.parent_domain == ""`. The workflow always produces
> the second case, so the guard never fires and the failure lands at apply, where ACM rejects a
> certificate for a bare `portal.`.
>
> **It is worse for the two defaulted variables**, which the criterion does not guard at all: an empty
> env var **overrides a default**, so `TF_VAR_spa_subdomain=""` yields `https://.{parent_domain}` —
> plausible enough to be requested, and refused only by ACM, in a message naming no repo variable.
>
> Both halves need a **`validation` block**, on all four variables, plus a `|| 'portal'` / `|| 'api'`
> fallback in both workflow env blocks so an unset repo variable never arrives empty. The validation
> is the durable half: the workflow is one careless edit away from losing the fallback.
>
> `route53_zone_id`'s pattern is **load-bearing beyond this criterion**. The id is rendered into the
> deploy role's Route 53 grant as well as into the records, and IAM matches ARNs literally — so the
> `/hostedzone/`-prefixed form the API returns yields a grant matching **nothing**, and every record
> write is denied for a reason the value does not look like it could cause.
>
> The corollary is worth stating because it is the opposite of the intuition: an unset variable
> does **not** redden the branch. The plan goes green and the apply fails later.
- [ ] All four are supplied as `TF_VAR_*` repo variables in **both** the `plan` and the `apply` env
      blocks of `deploy-infra.yml`. Adding them to only one makes the plan job — and therefore the
      plan-scan gate — evaluate a configuration that will never be applied.
- [ ] `terraform.tfvars.example` documents them, following `verification_principal_arns`'s precedent:
      the values are set as repo variables because no human identity here can apply locally.
- [ ] Two `aws_acm_certificate` resources in `var.aws_region` with `validation_method = "DNS"`,
      `lifecycle { create_before_destroy = true }`, their validation records in
      `var.route53_zone_id`, and an `aws_acm_certificate_validation` for each.
- [ ] Two A-alias records: the SPA name to the ALB, the API name to the API Gateway regional domain's
      `regional_domain_name` / `regional_zone_id`.

> **Corrected while building.** `regional_domain_name` / `regional_zone_id` are
> `aws_api_gateway_domain_name` — the **v1** REST-API resource. This spec builds an **HTTP API**, so
> the attributes are `aws_apigatewayv2_domain_name.<n>.domain_name_configuration[0].target_domain_name`
> and `.hosted_zone_id`. Named here because the v1 spellings do not exist on the v2 resource, so the
> criterion as written cannot be satisfied by the thing the spec asks for.
- [ ] `spa_origin` (`https://{spa_subdomain}.{parent_domain}`), `api_origin`, `spa_host` and `api_host`
      are constructed in root `locals` from the four domain variables, passed **into** the modules that
      need them, and re-exported from root `outputs.tf` — Premise 6's rule, and the reason FR-007's
      unknown-ARN trap cannot bite the three lists below.
- [ ] **The Cognito app client lists both origins.** `local.callback_urls` in
      `infra/modules/auth/cognito.tf` — which feeds `callback_urls` *and* `logout_urls` on the one app
      client — gains `spa_origin` beside `http://localhost:5173` and the existing `var.app_url` entry,
      keeping the same "omit when empty" ternary shape. `describe-user-pool-client` then returns **two**
      deployed callback URLs and two logout URLs (three of each with localhost). Removing either is
      SPEC-202's work; doing it here deletes the rollback.
- [ ] **CloudFront's `connect-src` names `api_origin`.** The bundle in the static bucket is HEAD, so
      once SPEC-197 → 200 land it fetches the API — and an origin whose CSP omits the API host is a
      portal that loads and can do nothing. `curl -sSI` against the distribution shows `api_origin`
      inside `connect-src`. This is a state that looks fine until it is needed, which is why it is a
      criterion in the spec that creates the host rather than a note in the one that retires the
      distribution.
- [ ] All three additions are **verified to remove nothing**: the deployed callback list still contains
      `var.app_url`, the deployed `connect-src` still contains every term it carried before, and
      FR-003's CORS list still answers the CloudFront origin. A "replace" where an "add" was intended
      applies green and is invisible until a rollback is attempted.
- [ ] **A wrong or foreign `route53_zone_id` makes `aws_acm_certificate_validation` hang until its
      timeout, not fail fast** — the apply looks stuck rather than broken. If the parent zone is
      delegated outside this account, the validation CNAMEs and both A records must be created in the
      authoritative zone before this applies. Recorded as a prerequisite in the Verification script.

### FR-007: Deploy-role IAM expansion

#### Description:

Five new resource families land at once, and this is the riskiest part of the spec. A new
`infra/modules/base/policies/github-actions-deploy-platform.json.tftpl` covers all three modules in one
file — they apply as one unit and share the `${project_name}-${environment}-` prefix.

> **Corrected while building (2026-08-24): it is TWO files, and the fourteenth and fifteenth managed
> policies rather than the thirteenth.** `infra/modules/base/iam.tf` already carried **thirteen**
> `aws_iam_policy` resources when this was written, and one document would not have fitted: a
> customer-managed policy has its own **6,144**-character budget and the halves measure **5,095** and
> **3,985**. The split is `…-platform` (ec2, elasticloadbalancing, ecs, ecr, the ECS/ELB
> service-linked roles) and `…-platform-frontdoor` (apigateway, acm, route53, every log group the
> platform creates, the API function, and the four roles it passes). `aws_iam_policy.deploy_platform`
> keeps that name because FR-008 AC5 names it. The attachment count goes 13 → 15 against a **default
> quota of 20** managed policies per role — raisable to **25** in Service Quotas and auto-approved, so
> the ceiling is a decision rather than a wall. A test counts them and names both numbers, because
> sending the next person to consolidate a quota they could simply raise is its own wrong answer.

**It ships as a thirteenth customer-managed `aws_iam_policy`, not as more inline JSON**, and that is
forced rather than stylistic. The deploy role's inline policy
(`github-actions-deploy.json.tftpl`, rendered by `aws_iam_role_policy.github_actions_deploy`) measures
**9,256 non-whitespace characters** against IAM's **10,240-character aggregate limit for a role's
inline policies** — under a kilobyte of headroom, for five resource families. Every per-plane addition
since SPEC-125 has taken the same route for the same reason (twelve today, each an `aws_iam_policy` +
`aws_iam_role_policy_attachment`, each `depends_on` `time_sleep.wait_for_self_grant`, each with a
description recording that it is "kept off the role's inline-policy aggregate limit"). This one is
`aws_iam_policy.deploy_platform` with attachment `deploy_platform`, and **FR-008's accept-list entries
name that resource**, not the inline one — a line matching no finding is a hard error under the settled
gate rule, so accepting on the wrong resource accepts nothing while reading as an acceptance.

Services to enumerate: `ec2` (VPC, subnets, route tables, IGW, security groups, VPC endpoints, tags),
`elasticloadbalancing`, `ecs`, `ecr`, `apigateway`, `acm`, `route53`, `logs`, `lambda` for the
placeholder function, `iam` for the three new roles, and `iam:PassRole` for the task role, the task
execution role and the API Lambda role.

**The traps, each with what it looks like when it bites:**

- **Non-scopable actions.** `ec2:Describe*` is the canonical family — it authorizes only on
  `Resource: "*"`, and a narrower ARN is an implicit deny that reads like a missing grant.
  `elasticloadbalancing:Describe*`, `acm:RequestCertificate`, `acm:ListCertificates`,
  `route53:GetChange` and `logs:DescribeLogGroups` are the others expected here. Each goes in its own
  `"*"` statement, and each is checked with `aws iam simulate-custom-policy --action-names <a>
  --resource-arns <arn>` **before** spending a CI round.
- **`iam:PassRole` needs its own condition.** Scope it by role ARN **and** `iam:PassedToService`
  (`ecs-tasks.amazonaws.com` for the two task roles, `lambda.amazonaws.com` for the function role).
- **Self-grant propagation.** `module.base` attaches the policy in the same apply that first uses it, so
  the first apply can `AccessDenied`. A `time_sleep` with no `triggers` fires once at creation and never
  again, so depending on an existing sleep buys **zero** delay. Expect one first-apply failure and a
  clean re-run — and do not let that expectation excuse a real denial: the **same action failing twice
  is a policy defect**, not propagation.
- **Unknown ARN inside a list silently drops the change.** The ALB, target group, API and role ARNs are
  all created in this apply. Anything feeding one into a list attribute must be a **constructed string
  in root `locals`**, known at plan time; ordering stays with `depends_on`.
- **Refresh deadlock.** Once these resources are in state, `tofu apply` refreshes them with the role's
  *current* policy before applying a fix — so a scope fix the refresh itself needs can never land, and
  **tightening deadlocks exactly like widening**. Break-glass is `Deploy Infrastructure` dispatched with
  `skip_refresh=true`, **always followed by a normal run**, because an apply that skipped refresh has
  proved nothing about drift.
- **A green `plan` is not proof the apply will work.** IAM is eventually consistent.

#### Acceptance Criteria:

- [ ] The grants ship as `aws_iam_policy.deploy_platform` in `infra/modules/base/` plus its role
      attachment, rendered from `github-actions-deploy-platform.json.tftpl`, on the twelve existing
      per-plane policies' pattern — **not** appended to `github-actions-deploy.json.tftpl`, which has
      under a kilobyte of the 10,240-character aggregate left. A test measures the inline policy's
      rendered non-whitespace length and fails above 10,240, so the next addition cannot discover the
      ceiling on an apply.
- [ ] Every action the three modules require is granted, scoped to an ARN pattern wherever the action
      accepts one, and grouped by service with a `Sid` naming the module.
- [ ] Every action placed in a `Resource: "*"` statement has a recorded `simulate-custom-policy` result
      showing `implicitDeny` under a scoped ARN and `allowed` under `"*"`. An `implicitDeny` **alone**
      proves nothing — it reads identically to a wrong ARN — so each is paired with an `allowed`
      control, on SPEC-149's and SPEC-157's precedent.
- [ ] `iam:PassRole` names the three role ARNs explicitly and carries the `iam:PassedToService`
      condition. A `PassRole` on `"*"` is a defect.

> **Corrected while building (2026-08-24), and both halves were measured rather than reasoned about.**
>
> **The two ACs above conflate two different reasons a grant carries `Resource: "*"`, and only one of
> them can produce the evidence AC3 asks for.** *Non-scopable by IAM* means the service defines no
> resource type for the action at all — `ec2:Describe*`, `elasticloadbalancing:Describe*`,
> `acm:RequestCertificate`/`ListCertificates`, `ecs:DescribeTaskDefinition`
> /`DeregisterTaskDefinition`/`ListTaskDefinitions`, and the **eight** `logs:` delivery actions an HTTP
> API stage needs for access logging. **38 were measured and 37 ship** — `ecr:GetAuthorizationToken`
> was in the measured set and was then dropped with its grant, because the deploy role creates the
> registry and never writes to it. Every one of the 37 produced the pair.
> *Scopable in principle but unknowable at plan* is the different case the EC2 **mutators** are in: an
> EC2 ARN carries a generated id, so there is no name to match — but the action does accept an ARN, so
> a wildcard-ARN simulate returns **`allowed`**, there is no `implicitDeny` leg, and the pair cannot
> exist. They are therefore scoped by resource **type** (`vpc/*`, `subnet/*`, `route-table/*`, …)
> rather than parked on `"*"`, which is strictly what AC2 asks for and is what AC3 could not have
> expressed.
>
> **`iam:PassRole` names FOUR roles, not three, across THREE statements.** The fourth is the VPC
> flow-logs delivery role — flow logs to CloudWatch are delivered *as* a role, and FR-008 takes flow
> logs as a scoped fix rather than a disposition, so the role exists even though no resource list in
> this spec names it. Three statements because a statement carries one condition block and the four
> roles go to three different services; one `iam:PassedToService` listing all three would let the
> flow-logs role be handed to ECS.
>
> **And the grants ship as TWO managed policies.** One document would not have fitted: the halves
> measure **4,823** and **3,879** non-whitespace characters against a customer-managed policy's own
> **6,144** limit. `aws_iam_policy.deploy_platform` keeps that name, because FR-008 AC5 names it.
- [ ] No cross-module ARN reaches a list attribute except as a root-`locals` constructed string.
- [ ] `Deploy Infrastructure` reaches green from a clean `main`, at worst on a second run whose first
      run failed only with `AccessDenied` on actions granted in the same apply.

### FR-008: The scanners

#### Description:

New resource families produce new Checkov findings. The settled rule is that a gate blocks on a
**narrowed count** — an enforce list of check IDs measured at zero on `infra/`, and a rendered-plan
accept list keyed by check ID **and** resource, which exists only for findings with no scopable
alternative. **A new finding is scoped, not accepted.**

#### Acceptance Criteria:

- [ ] `.github/checkov-enforced.txt` is regenerated by the recipe in its own header — not pasted over
      unthinkingly, because an ID that *disappears* has started failing and deleting the line is how a
      gate gets quietly switched off. Every newly-passing ID joins the list.
- [ ] Each of these is **fixed, not dispositioned**, because a scoped fix is cheap and the resource is
      new: ECR immutability / scan-on-push / encryption, ALB TLS policy, `drop_invalid_header_fields`,
      deletion protection, ALB access logging, VPC flow logs (to a CloudWatch group with 14-day
      retention), the default security group restricting all traffic, ECS Container Insights,
      read-only root filesystem, non-root user, distinct task and execution roles, and
      `map_public_ip_on_launch = false`.

> **One resource on that list's edge is deliberately NOT declared (2026-08-24): the default network
> ACL.** The default *security group* is fixed as the criterion says; `aws_default_network_acl` is its
> usual companion and is left out, because the criterion does not name it and nothing measured has
> asked for it. If the regenerated enforce list turns one up, the fix is the resource **plus** a
> widening of both EC2 statements in `github-actions-deploy-platform.json.tftpl` — `network-acl/*` in
> the mutator and tagging resource lists, and `ec2:CreateNetworkAclEntry` /`DeleteNetworkAclEntry`
> /`ReplaceNetworkAclAssociation` among the actions. Widening is safe where tightening is not: the
> refresh does not need the new grant, so it cannot deadlock on it.
- [ ] Each finding **not** fixed carries a written disposition row in `docs/security-baseline.md` naming
      the reason. The two expected: **WAF** on the ALB and the API (deferred by the arc — the client
      environment's edge is a later decision), and **`$default` route authorization**, which Premise 5
      settles: the request carries an `Authorization` bearer that SPEC-195's router verifies and
      resolves to a principal before dispatch, denying by default, and that SPEC-196 then resolves to a
      role — so an authorizer would be a second reader of the same token, able to disagree with the
      first about the claim the role assumption is scoped by, and a `$default` route means one
      integration serves every path so a per-route authorizer would have to duplicate the route table
      to say anything at all. **This row is the wording that lands in the audit trail**, so it must not
      rest on the session cookie the arc's re-scope removed.
- [ ] `docs/security-baseline.md` gains a section for this spec's resources with the measured counts,
      dated, in the shape the existing findings use.
- [ ] The rendered-plan scan: each new `Resource: "*"` statement on
      `module.base.aws_iam_policy.deploy_platform` will fire `CKV_AWS_356` / `CKV_AWS_111` /
      `CKV_AWS_49`, and that resource has no accepted findings today (the two permanent rows are on
      `module.base.aws_iam_role_policy.github_actions_deploy`, which this spec does not touch). The
      additions to `.github/checkov-plan-accepted.txt` are verified against a **real plan-scan run**,
      never guessed —
      a line that matches no finding is a hard error, and reads as an acceptance while accepting
      nothing. Each addition names the specific non-scopable actions that forced it.

> **Measured on the real run (2026-08-24), and the prediction was wrong: the additions are NONE.**
> The `plan` job on the PR that adds both policies reported `IAM resources in plan: 85; IAM checks
> evaluated: 674; IAM findings: 2` under `GATE_CHECKOV_PLAN: block` — the two being the same
> permanent rows on `github_actions_deploy`. Neither new policy fired anything, so
> `.github/checkov-plan-accepted.txt` is **unchanged**, and writing the rows this criterion predicts
> would have turned the gate red for precisely the reason its own header gives: a line matching no
> finding is a hard error. This is not a scan that skipped — the job's coverage assertion (IAM
> resources present but no IAM check evaluated) is what would have caught that, and it passed. **The
> rule the criterion exists to enforce is what produced the zero:** a new finding is scoped, not
> accepted, and these grants were scoped.
- [ ] The `.tf` scan reports a non-zero `passed_checks` count for every newly-enforced ID. Without
      `passed_checks` the gate cannot tell "this check passed" from "this check never ran" — which is
      why `--quiet` must never come back.

---

## Data Model

**This spec is infra-heavy, so this section is Terraform variable and output shapes rather than
TypeScript interfaces.** No TypeScript type is added or changed anywhere in the repo by this spec; the
only TS that will ever touch it is SPEC-192's runtime accessors, which consume the two origins below.

```hcl
# infra/variables.tf — new root variables (all supplied as TF_VAR_* repo variables)

variable "parent_domain"    { type = string }                      # no default — e.g. "example.com"
variable "route53_zone_id"  { type = string }                      # no default — the public hosted zone
variable "spa_subdomain"    { type = string, default = "portal" }
variable "api_subdomain"    { type = string, default = "api" }
variable "vpc_cidr"         { type = string, default = "10.0.0.0/16" }
variable "spa_desired_count" { type = number, default = 0 }        # raised to 1 once an image exists

# infra/main.tf — root locals (constructed strings, known at plan time; Premise 6).
# Consumed by module.auth's callback list, module.api's CORS list, module.app's CSP and
# module.spa's task-definition environment, and re-exported from outputs.tf.
#
#   spa_origin = "https://${var.spa_subdomain}.${var.parent_domain}"
#   api_origin = "https://${var.api_subdomain}.${var.parent_domain}"
#   spa_host / api_host = the same without the scheme

# module outputs (type in the comment; all re-exported from root outputs.tf)

# network/  vpc_id, public_subnet_ids, private_subnet_ids (list, one per AZ),
#           private_route_table_ids (the S3 gateway endpoint's association set),
#           vpc_endpoint_security_group_id
# api/      api_origin ("https://api.example.com"), api_host, api_function_name
#           (the deploy-lambdas.yml matrix target), api_execution_arn (scopes the
#           lambda permission)
# spa/      spa_origin ("https://portal.example.com"), spa_host, ecr_repository_url
#           (SPEC-194's push target), ecs_cluster_name, ecs_service_name, alb_dns_name
```

---

## API / Interface Contract

The placeholder API. SPEC-197 owns the real transport contract and may replace the error shape.

```
GET  /healthz            -> 200 {"status": "ok", "version": "<build sha>"}
ANY  /<anything else>    -> 404 {"error": {"code": "not_found"}}
OPTIONS <any>            -> handled by API Gateway's cors_configuration; the handler is not invoked
```

## Environment Variables

**No `VITE_*` variable is added by this spec, deliberately.** CLAUDE.md requires every `VITE_*` to
reach four wiring points (the build env, the GitHub repo variable, `.env.example` and `lib/env.ts`'s
classification), and the browser has no use for either origin until SPEC-194 serves the image and
SPEC-197 gives it a client. This spec's job is to make the origins **exist as outputs**.

New Lambda environment (set by Terraform on the placeholder function): the six
`cpcommon._REQUIRED_VARS` values, `LOGS_QUEUE_URL`, `NOTIFICATIONS_QUEUE_URL` (optional, unset),
`ENV_NAME`. New root Terraform variables are in the Data Model above.

New **task** environment (set by Terraform on the SPA task definition, FR-005): SPEC-192's
runtime-configuration key set — whose membership is SPEC-192's to declare and whose agreement test is
re-pointed here — plus `PORTAL_CSP_CONNECT_SRC` from the root local **this spec's PR 4 moved**
(SPEC-194 moves only `local.content_security_policy`). None of these is a
`VITE_*` variable; that is the whole point of SPEC-192.

## File & Folder Structure

```
infra/modules/network/        {main.tf, endpoints.tf, outputs.tf, variables.tf}
infra/modules/api/            {apigateway.tf, lambda.tf, iam.tf, dns.tf, outputs.tf, variables.tf,
                               policies/}
infra/modules/spa/            {ecr.tf, ecs.tf, alb.tf, iam.tf, dns.tf, security-groups.tf,
                               outputs.tf, variables.tf, policies/}
infra/modules/base/policies/github-actions-deploy-platform.json.tftpl
infra/certificates.tf                       # the two ACM certificates + validation, at root
lambdas/api/                  {handler.py, router.py, test_handler.py, test_router.py}
apps/portal/Dockerfile.placeholder          # deleted by SPEC-194, which writes the real one
docs/testing/arc-b-api-container-e2e.md
```

## Implementation Phases

### Phase 1: Deploy-role IAM, the domain variables and the certificates

- `github-actions-deploy-platform.json.tftpl`, rendered by a thirteenth `aws_iam_policy` plus its
  attachment, with every non-scopable action verified by `simulate-custom-policy` and paired with an
  `allowed` control before it is written.
- The inline-policy length guard, measured against IAM's 10,240-character aggregate.
- The four domain variables through `deploy-infra.yml`'s **two** env blocks and
  `terraform.tfvars.example`; `spa_origin` / `api_origin` / `spa_host` / `api_host` as root locals and
  outputs.
- The two regional certificates, their validation records and validations. Longest lead time, and it
  fails independently of everything else.

### Phase 2: The network

- VPC, subnets, IGW, route tables, security groups.
- The three interface endpoints and the S3 gateway endpoint, with the route-table association set
  asserted equal to the private route tables.
- The repo-wide no-NAT assertion.

### Phase 3: The front door

- `infra/modules/api/`: HTTP API, `$default` route and integration, CORS, access-log group, regional
  custom domain, mapping, A-alias record.
- `lambdas/api/`: handler, router, tests, docstrings, the deploy-matrix row, the blocking mypy path.
- FR-002's absence assertions.
- FR-006's three additive allowlist changes, each with its removes-nothing check: both origins on
  `local.callback_urls`, `api_origin` in CloudFront's `connect-src`, both origins in the CORS list.

### Phase 4: The container runtime

- `infra/modules/spa/`: ECR, cluster, task definition (including its `environment` block and the two
  `volumes`/`mountPoints` for `/tmp` and `/var/cache/nginx`), the two roles, service, target group,
  ALB, both listeners, security groups, A-alias record.
- The admin bucket's first bucket policy, for ALB access-log delivery.
- `apps/portal/Dockerfile.placeholder`.

### Phase 5: The scanner re-baseline

- Regenerate the enforce list by its own recipe; take the cheap scoped fixes rather than dispositioning
  them.
- Disposition rows in `docs/security-baseline.md` for WAF and `$default` route authorization.
- The plan-accept-list additions, verified against a real plan-scan run.

### Phase 6: Verification — a real apply, not a plan

The script is the relevant section of `docs/testing/arc-b-api-container-e2e.md`. **A plan proves
nothing here**: every trap in
FR-001 and FR-007 plans and applies green and fails at runtime.

1. `Deploy Infrastructure` on the branch, watched to green. A first-run `AccessDenied` on a
   newly-granted action is expected once; the **same action failing twice is a defect**.
2. `dig` both names — both resolve. `openssl s_client` shows the ACM certificate for the right name on
   each host.
3. `curl -i https://<api_host>/healthz` → 200, and `version` **equal to HEAD's sha**. That single
   assertion covers the deploy matrix, the package build and SPEC-186's `BUILD_VERSION` stamp.
4. Preflight with the SPA origin: exactly **one** `access-control-allow-origin`, equal to it, and **no**
   `access-control-allow-credentials`. Repeat with the CloudFront origin: one header, equal to *that*
   one. Repeat with a foreign origin: **no** ACAO header. Count the header rather than reading one — a
   duplicated header passes a casual `curl` read and fails only in a browser.
5. `logs/service=api/…/data.jsonl` carries the invocation's span with `env` and `version` populated.
   This is the cold-start assertion; nothing offline can make it.
6. Build and push `Dockerfile.placeholder` by hand (commands in the script), tagged with the git sha —
   `:latest` is impossible under FR-005's immutability. Then raise `spa_desired_count` to 1 and apply.

   > **Prerequisite nothing in this repo provisions (recorded 2026-08-24).** That push needs an
   > identity holding `ecr:GetAuthorizationToken` (account-wide — it takes no ARN) plus
   > `BatchCheckLayerAvailability`, `InitiateLayerUpload`, `UploadLayerPart`, `CompleteLayerUpload`
   > and `PutImage` on the repository. **The deploy role deliberately holds none of them** — it
   > creates the registry and never writes to it, and the pipeline that pushes on every commit
   > arrives with SPEC-194, which owns those grants. So this step runs as a human identity that must
   > be checked *before* the step is reached, not at it.
7. `describe-services` → `runningCount == 1` and **no `CannotPullContainerError`** in the event log.
   Pair it with `describe-route-tables` showing the private tables carry only the local route: without
   that pairing a pull that succeeded through a route somebody added would read as proof of the
   endpoints, and the whole of FR-001 would be unverified.
8. `describe-vpc-endpoints` → the S3 gateway endpoint's `RouteTableIds` equals the private route-table
   ids.
9. `curl -i https://<spa_host>/healthz` → 200 through the ALB; `describe-target-health` → `healthy`.
10. `curl -i http://<spa_host>/` → 301 to the `https://` URL.
11. `describe-user-pool-client` lists **both** deployed origins in `callback_urls` and in `logout_urls`,
    and `curl -sSI $CLOUDFRONT_URL` shows `api_origin` inside `connect-src` — the two additive changes
    nothing else in this spec exercises, and the two whose absence is invisible until a later spec's
    live check or a rollback needs them.

**What nothing offline can prove:** that the `cpcommon` layer attaches at cold start; that an ECR pull
completes with no NAT (three endpoints, a security group, private DNS and the Fargate platform version
must all be right, and every one of them applies green when wrong); that DNS validation completes in
the zone the variable names; and that a browser accepts the CORS response.

> **One item was removed from that list while building (2026-08-24): scopability is answerable
> offline.** `simulate-custom-policy` evaluates a policy **document** that is supplied to it, so it
> needs `iam:SimulateCustomPolicy` and has no relationship with the deployed role — the 38 pairs were
> produced on a laptop before a single line of the policy was written, which is what the word
> "**before**" in FR-007 AC3 asks for. Nothing here waits on a deploy.

**What is deliberately not claimed:** nothing here is evidence about session, auth, the real SPA, or
any ported route. Production is still served by CloudFront and is untouched.

### Phase 7: Completion ritual

- `Status: Completed`; the `INDEX.md` row; a delivery doc at
  `docs/spec-delivery/SPEC-193-network-compute-and-the-front-door.md`, recording the **actual**
  non-scopable action list, whether the first apply failed and on what, and the endpoint set the pull
  really needed.
- `decisions.md` entries, then **one line each** in CLAUDE.md's Key Decisions: (1) no NAT gateway —
  endpoints, the cost/blast-radius trade and the connect-timeout residual; (2) the API Lambda is not in
  the VPC; (3) authorization lives in the router, not in an API Gateway authorizer — resolved from the verified
  bearer, with the `$default` route as the compounding reason; (4) immutable ECR tags mean the tag is
  the git sha and `:latest` does not exist; (5) the origins are admitted additively where they are
  created and narrowed only at the cutover, because an allowlist naming one origin makes the other a
  rollback that cannot be exercised.
- `architecture.md`: a new *Infrastructure & Deployment → The container platform* subsection (the
  resources exist from here on and a reader needs them; SPEC-202 amends it when CloudFront goes), and
  the *Deploy-role IAM — adding a new resource type* list extended with the non-scopable actions this
  spec actually found. That list is explicitly a running record.
- `ARCS.md`: the arc entry updated with what the apply found, since the arc file is where a later
  reader looks for how the eleven specs compose.
- `docs/component-inventory/`: **no row.** There is no infra area file and this spec adds no reusable
  service, hook or component. Recorded rather than left ambiguous.
- Help sweep: **nothing user-facing changes.** The live portal is still the CloudFront-served bundle;
  the two new hosts serve a placeholder no user is pointed at. Recorded explicitly and skipped.
