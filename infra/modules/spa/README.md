# `spa` — the portal's only front door

The portal's Next.js server, run from a Fargate container behind an internet-facing ALB and pulled
from the [`spa-image`](../spa-image/README.md) registry. **It is the only thing that serves the
portal, and only while the web tier is on**; with it off, nothing does (`infra/info/web-tier.md`).

| File | Holds |
|---|---|
| `ecs.tf` | the cluster, the task definition and the service |
| `alb.tf` | the load balancer, target group, both listeners, **and the admin bucket's first policy** |
| `security-groups.tf` | the ALB's group, and **every rule that names the task group** |
| `iam.tf` | the execution role, and the task role with its one grant, the session store |
| `dns.tf` | the A-alias record |
| `names.tf` | the names the deploy role's grants are written against |
| `outputs.tf` / `variables.tf` | the module interface |
| `policies/` | task trust, execution policy, ALB access-log bucket policy |

The image itself — the Dockerfile, the server's routes, its request proxy, what `/healthz` serves —
belongs to `apps/portal`. **Two divergences from what CloudFront once served remain: no brotli (Next
compresses with gzip per request) and HSTS without `preload`.** The `Server` banner nginx could not
drop is gone: the Node server sends none.

## ⚠ CI must point the service, not just register a revision

`ignore_changes = [task_definition]`: the image is CI's, so its deploy registers a new revision **and
points the service at it**. Without the ignore, every later infra apply would point the service
straight back at whatever tag Terraform last rendered.

**A pipeline that only registers a revision leaves a `CannotPullContainerError` indistinguishable
from the endpoint failure task startup is tested for.**

**`desired_count` is deliberately not in that list.** The count is a Terraform variable whose raise
from 0 to 1 is a verification **step**, and an ignored attribute makes that step a silent no-op that
reads as a broken service. If a later spec introduces autoscaling or a CI-side scale, the count joins
the list **then** — with the variable retired in the same change, so one owner is losing it rather
than two quietly disagreeing.

## Platform version 1.4.0 is pinned, and it is load-bearing

On **1.3.0 the image pull travelled a separate Amazon-owned ENI to which VPC endpoints did not
apply**, so task startup's endpoints-only path silently does not hold.

**The circuit breaker is enabled with rollback disabled.** With rollback on and no previous good task
set, a missing image reads as a *rollback* rather than as `CannotPullContainerError` — the one
diagnosis this arc's central claim is tested by. Rollback may be enabled once a good task set exists.

## A Fargate task volume arrives empty and root-owned

`readonlyRootFilesystem = true` needs writable paths, and the mechanism is
**`linuxParameters.tmpfs`** — measured, after task-level volumes were tried and **could not work**.

A Fargate task volume is a fresh, **empty, root-owned** directory. **It does not initialise from the
image**, so a container running as a non-root user cannot write to it. Measured with the nginx image
this module once ran: its process, uid 101, saw `drwxr-xr-x root root /tmp`, and died on a permission
error writing its temp files, **a message that reads as a container bug and is not one**. The Node
server writes only its temp directory, so `/tmp` is the one mount, owned by uid 1000.

**tmpfs takes uid, gid and mode as mount options**, which is the whole difference: the mount is
created owned by the user that has to write to it.

**One uid feeds both** `user` and every mount option (`container_uid`). Split between the two, a
mount is silently unwritable by the process that needs it.

## The task environment is derived, never hand-written

One `CONFIG_<documentKey>` entry per key in the runtime-configuration map root builds. **A
hand-written list is how a container ships serving seven of twenty-one values** — every required key
present, every optional one missing, and a portal with no shared spaces, no notifications and no
queues.

The prefix and the camelCase key are the document's own. The Next.js server renders `/config.json`
from these variables, reading the same classification the browser does, and **refuses to start**
when a required one is unset or empty, so a key added to the classification and not here fails a
test rather than shipping a container missing one value.

`csp_connect_src` arrives whole from root as `PORTAL_CSP_CONNECT_SRC`, the policy's one
environment-shaped directive. The server validates it against an allowlist at start and refuses
anything else, because a `;` in it would append a directive of its own to every page's policy.

## The off switch, and why the balancer carries no deletion protection

This module and `network` exist only to serve the portal, and they are most of what the stack costs
while nobody uses it — so both are behind `web_tier_enabled`, which removes them whole. How to switch
it, and what stays up while it is off: [`../../info/web-tier.md`](../../info/web-tier.md).

**`enable_deletion_protection` is off, deliberately.** AWS refuses `DeleteLoadBalancer` while it is
on, and Terraform cannot turn it off and delete in one apply, so with it on every switch-off would
be two applies with a half-state between them. What it guarded was an accidental replacement — the
name is ForceNew — of a balancer that holds no state, whose alias record the same apply rewrites,
and whose replacement shows in the PR's rendered plan. `CKV_AWS_150` came off Checkov's enforced
list with it; the disposition is in `docs/security-baseline.md`.

**The listener's certificate goes with them** (`infra/certificates.tf`): ACM renews a public
certificate only while a service uses it, so one kept through a long off period would expire and
fail every later apply.

**Nothing outside these two modules may depend on them.** Anything wired to a `network` or `spa`
output has nothing to read while the switch is off, and a resource placed in the VPC is destroyed
with it.

## One two-apply change, and a name ELBv2 caps

- **The target group's port is ForceNew and the group cannot be replaced in one apply.** A listener
  forwards to it, so `DeleteTargetGroup` returns `ResourceInUse` and a destroy-then-create stops half
  done. `name_prefix` + `create_before_destroy` is the usual answer and is **not available**: the
  deploy role's grant is scoped to `targetgroup/${project}-*-spa*`, and a generated prefix does not
  match it. **Changing the container's port is two applies** — a second group and a listener
  re-point, then the first group's removal.
- **ELBv2 caps a target-group name at 32 characters** and refuses a longer one at *create*, with a
  `ValidationError` naming nothing about this module. `project_name` is not length-bounded, so a
  `precondition` moves the refusal to plan.

## The ALB access-log bucket policy: no conditions, two principals

This is the admin bucket's **first and only** policy, and it lives here rather than beside the bucket:
the analytics module has no interest in load-balancer logs, and the condition is built from this
module's names. `aws_s3_bucket_policy` is whole-document, so **"this is the bucket's only policy" is
a property a test pins** rather than a convention.

**The service-principal form, not the `aws_elb_service_account` data source.** AWS heads its own
published account-principal policy "Legacy bucket policy … we recommend that you replace it", and that
form delivers through an **ACL grant — which this bucket, at `BucketOwnerEnforced`, does not accept at
all**.

**No conditions, and both halves were measured on three failed applies.** A version carrying
`StringEquals aws:SourceAccount` beside an `ArnLike aws:SourceArn` was refused with
`InvalidConfigurationRequest: Access Denied for bucket`; dropping `SourceAccount` and keeping the
`ArnLike` was refused identically. **ELB validates this policy with its own `PutObject` at
`ModifyLoadBalancerAttributes` time, and a condition on a key that call does not populate fails
closed** — each condition was a bet that the caller supplies the key, and both bets lost. AWS's
documented policy carries no condition at all; the `SourceArn` suggestion sits in a separate
best-practices section and does not survive this validation.

The second principal is the region's own load-balancing account, the older delivery identity. **Which
of the two AWS actually delivers as was not isolated** — that needs candidate policies put on a live
bucket between attempts — so both are granted and the narrowing is **recorded as owed**.

**What still bounds it:** the `Resource` pins the account id as a path **segment**, and a load
balancer writes under its **own** account's id, so a foreign balancer's keys match nothing here. That
is AWS's own first-listed best practice, and the one that survives the validation. **The account id is
never wildcarded.**

**No `Deny` in it.** One would also stop the deploy role's refresh read of the bucket, and every
subsequent plan would propose a **destructive recreate of a bucket holding the structured logs**.

The `elb_account_arn` is read at **root** and passed in: a data source in this module would be
deferred to apply by its own `depends_on`, and the value is a property of the region rather than of
anything here. `account_id` is passed for the same reason.

## Where the security-group rules live

**The ALB's group is created here. The task group is not** — it belongs to `modules/network`, which
creates it with **no rules on purpose**, because every rule on it also names the ALB's group and a
rule split across two modules is a rule nobody can read.

Its reciprocal — the endpoints' ingress from the task group — is declared **beside the endpoints** and
**must not be repeated here**, or the apply fails with `InvalidPermission.Duplicate`.

**Egress to S3 is by prefix list, never by CIDR.** ECR stores image layers in S3 and the S3 endpoint
is a **gateway**: its traffic is matched by the managed prefix list the endpoint installs a route for.
**A CIDR rule naming S3's address ranges does not match it, and the symptom is an image pull that
hangs rather than one that refuses.**

Port 80 exists **only** to answer the redirect — the listener's sole action is a 301, so nothing is
served over it, but the port has to be reachable for a browser that types the bare host to be told
where to go. **The HTTP listener has no forward and no fixed response**: a listener that can serve
anything over port 80 is one that can serve the app over it.

## Two roles, and each holds only its own work

The **execution** role is ECS's — it pulls the image, opens the log stream and reads the server
client's secret from SSM, **before the container exists**. The **task** role is the container's own
AWS identity, and the server's one AWS call is its session store: item actions on that one table, and
the table's key only as DynamoDB uses it for that table (`kms:ViaService` and the table-name
encryption context). `key/*` because the key is created in the same apply as this document, which
the plan-time IAM scan must be able to read.

**Merging them applies green forever**, because nothing the container does would fail — and hands the
running container the registry pull, log-write and secret-read grants for no reason.

The execution policy is **a scoped document, not `AmazonECSTaskExecutionRolePolicy`**. The managed
policy grants the three pull actions on **every repository in the account** and hides that breadth
behind an attachment **the rendered-plan IAM scan cannot read**. Here the pull is scoped to this
repository, the log write to this group, and the one genuinely unscopable action —
`ecr:GetAuthorizationToken` takes no resource type at all — is left alone in its own statement where
it is visible.

Inline rather than managed-plus-attachment, for the same reason the API function's role is: the deploy
role holds `iam:PutRolePolicy` and neither `iam:AttachRolePolicy` nor a usable `iam:CreatePolicy`.

## Small shapes that are load-bearing

- **The ALB is internet-facing and in the public subnets.** Placed in the private ones it applies
  green and yields an address nothing can reach.
- **`drop_invalid_header_fields`** rejects a request carrying a header the ALB cannot parse rather
  than forwarding it with the header silently dropped — the difference matters wherever a header
  carries an identity.
- **The log group is declared, not created by `awslogs-create-group`.** A driver-created group is
  unmanaged and retained forever, and `retention_in_days` is an enforced scanner gate. The stronger
  reason is diagnostic: **with no group at all every task dies at start with
  `ResourceInitializationError`**, which during verification is indistinguishable from the
  `CannotPullContainerError` task startup is tested by.
- **`runtime_platform` is declared, not defaulted.** The default is `X86_64` either way, but an image
  built by hand on an Apple Silicon laptop is arm64 and the task fails with an image-manifest error
  **that reads nothing like the architecture mismatch it is**. CI names `--platform linux/amd64` to
  agree with this.
- **`evaluate_target_health = false` on the alias record.** With it on, a service scaled to zero —
  which is exactly how this ships — would take the record out of DNS and **turn a deliberate state
  into a resolution failure**.
- **The listener certificate comes from the *validation* resource**, not the certificate: same ARN,
  but only the validation creates the edge that stops a clean rebuild attaching a still-pending
  certificate.
- **The Route 53 zone id is a variable, never a lookup** — the deploy role does not hold
  `route53:ListHostedZonesByName`, and the failure would read as a mysterious `AccessDenied`.
- **Two `depends_on` edges Terraform does not infer:** the target group must be attached to a listener
  before ECS will register a target against it (Terraform infers the group but not the listener), and
  the execution role's **policy** is reachable only through the role — so at any desired count above
  zero a task could start before the pull grant exists, and with rollback disabled that failed
  deployment then needs a manual `force-new-deployment` to clear.
- **`image_tag` carries a `validation` on the value, not on its presence** — an empty repo variable
  renders as the empty string, which satisfies a required variable *and* overrides a default.
- **No `spa_origin`/`spa_host` output.** Both are built at root and passed down.

## What the offline guards prove, and what they cannot

`lambdas/test_spa_image.py` and `lambdas/test_spa_module.py` are **text assertions** over a
Dockerfile, the server's TypeScript and this module's Terraform. They hold the agreements no single
response can observe — that the image and the task definition agree about a port, a health path, a
uid and a writable set, and that `connect-src` arrives from the task definition rather than being
built into the image.

Each failure they guard **applies green somewhere and fails somewhere else**:

- a health path the module does not probe makes the balancer read some page's answer for health,
  where `/healthz`'s asserted `ok` body is the one a broken server cannot give;
- a writable set the task does not mount produces a container that never starts, reported as a
  generic essential-container exit — and `ResourceInitializationError` is indistinguishable from
  the `CannotPullContainerError` task startup is tested by;
- `appUrl` carrying the CloudFront origin fails only in a browser, only on a fresh sign-in;
- a merged task and execution role applies green forever, because nothing the container does
  would fail;
- a `version` literal drifted from the loader's ships a document every browser refuses whole — a
  white screen after a green deploy.

**The writable-path set is named in two places on purpose.** The assertion is an agreement
between an image and a configuration; a shared constant would prove nothing.

What they cannot prove — that the policy is what the server emits, that the refusals happen,
that a task reaches `healthy`, that the redirect answers — belongs to the behaviour matrix in CI,
which runs a real container, and to the live checks in `docs/testing/`.
