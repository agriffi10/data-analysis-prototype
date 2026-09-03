# `base` — the GitHub Actions OIDC provider and the deploy role

The OIDC identity provider, the role CI assumes, and **every grant that role holds**. Nothing else in
the repo can be created until the grant for it lands here first.

| File | Holds |
|---|---|
| `iam.tf` | the provider, the role, one inline policy, **one customer-managed policy per resource family**, and the propagation guards |
| `outputs.tf` / `variables.tf` | the module interface |
| `policies/` | one `.tftpl` per policy |

Trust allows a push to `main` (deploy and apply) and `pull_request` events (`tofu plan` on PRs —
read-only, no deploy permissions used). The thumbprint is fetched from GitHub's OIDC discovery
endpoint.

Read [`../../info/deploy-role-iam.md`](../../info/deploy-role-iam.md) before adding one.

## Why one managed policy per family instead of more inline JSON

**IAM's 10,240-character limit is the AGGREGATE of all inline policies on a role** — a sum, not a
per-policy budget — and the main deploy policy alone spends most of it. An inline second policy
pushed the aggregate over and failed with `LimitExceeded`. No figure is written here for the same
reason the managed policies' sizes are not: `lambdas/test_deploy_platform_policies.py` measures the
live one, and the number this sentence used to carry was a thousand characters stale.

**A customer-managed policy has its own separate 6,144-character budget and does not count toward the
inline aggregate.** So every new resource family gets its own managed policy. The count is not written
down here — it moves with the resource families, and the only ceiling it has to clear is IAM's cap of
twenty managed policies attached to one role.

That budget is also why the container platform is **two** files rather than one: **one document
would not have fitted**, and the larger half is still the one under pressure. The sizes are
deliberately not written down here — a number in prose rots, and
`lambdas/test_deploy_platform_policies.py` measures **every** managed policy against the ceiling on
every run. The split is by what the resources *are* — network and container runtime in one, the
API's front door and the roles beside it in the other — and `deploy_platform` keeps its name
**because the scanner accept list names it**.

## ⚠ Grants land in their own PR, before the resources that need them

**The deploy-perms-before-resources rule.** Every plane's module comment saying "no `time_sleep` guard
is required here" is relying on it.

**That rule holds only for as long as somebody remembers to split** — which is why the archive grants
carry a **structural** guard instead. The apply that first added them went red, and the mechanism is
invisible in a plan: `module.archive` carries `depends_on = [module.base]`, so the attachment
genuinely happens first — **and it is still not enough, because IAM is eventually consistent**.
`CreateBucket`, `CreateRole`, `CreateQueue` and `CreateLogGroup` all came back `AccessDenied` seconds
after the attach, and **the identical apply succeeded on a re-run minutes later with no change at
all**.

**A red FIRST apply of a new plane is expected rather than a defect**, and a re-run is the remedy.
`wait_for_self_grant` fires once at creation, so an *Nth* policy added later gets zero delay.

### The three guards, and why the third needs `triggers`

- **`wait_for_self_grant`** sits at the top of the graph: the main deploy policy grants the role
  `iam:CreatePolicy`/`iam:AttachRolePolicy` **on itself**, and the same apply then uses those grants.
- **The archive guard** (30 s) is a floor on eventual consistency for the plane that creates a bucket.
- **The platform guard** is a **second** sleep rather than a wider dependency on the first, because
  `wait_for_self_grant` has long since finished by the time these two policies are written and gates
  nothing. Every module using a platform grant carries `depends_on = [module.base]`, which waits for
  every resource here — **so placing the pause AFTER the attachments is what puts it between the
  grant and its first use**.

  **`triggers` is the half that makes it durable, and its absence is what a once-created sleep gets
  wrong.** Measured: the API Gateway service-linked-role grant was written at **14:56:08.95** and the
  `CreateDomainName` it authorises was refused at **14:56:10.67** — **1.7 seconds**, on an apply where
  a sleep created months earlier had nothing left to do. Keyed to the policy **bodies**, it is
  replaced whenever either grant changes, so the pause returns exactly when a grant is new and costs
  nothing when neither has moved.

## Scopability is measured, never assumed

**Every `Resource: "*"` statement holds only actions IAM defines no resource type for**, and each was
checked with **`simulate-custom-policy`** before it was written: **37 actions, each reading
`implicitDeny` under a scoped ARN and `allowed` under `"*"`**.

**The `implicitDeny` alone proves nothing — it reads identically to a wrong ARN** — so the `allowed`
control is what makes the pair evidence.

**`test_deploy_platform_policies.py` pins that recorded measurement rather than re-deriving it.** It
holds the set as a literal and asserts the policies agree in both directions, because a test that
reads the AWS Service Reference over the network **fails on a runner with no egress and passes by
finding nothing when the endpoint changes shape**.

The recurring non-scopable actions, each isolated in its own wildcard statement:

- **`states:ValidateStateMachineDefinition`** — every control-plane policy.
- **`lambda:*EventSourceMapping`** — the mapping has no ARN at create time. `ListEventSourceMappings`
  is the one that genuinely cannot be narrowed at all: AWS defines **no** resource types and **no**
  condition keys for it, so conditioning it would deny the call outright — the *unknown-ARN-in-list*
  trap. Create/Get/Update/Delete **are** condition-scopable on `lambda:FunctionArn`.
- **`ecr:GetAuthorizationToken`** and **`cloudtrail:DescribeTrails`/`ListTrails`**.

## Traps worth reading before adding a grant

- **An IAM policy document must be printable ASCII.** The verification policy's first version carried
  `"//"` comment keys containing em dashes and **the apply rejected it at `CreatePolicy`** — not
  something `tofu validate` or the plan can see. **Rationale goes in the `.tf`, never the `.tftpl`.**
- **The archive bucket is scoped by EXACT NAME, not by the plane's name pattern.**
  `{project}-prod-archive` has no trailing segment, so it does **not** match `{project}-*-archive-*`
  at all — **a pattern-scoped grant would render, apply, and then fail the bucket create with an
  implicit deny.**
- **The EC2 mutators are scoped by RESOURCE TYPE, not by name.** An EC2 ARN carries a generated id, so
  there is no name pattern and no tag to condition on at create time — but the actions accept ARNs, so
  the grant names the nine resource types the platform builds and reaches no other kind. **The tagging
  statement names the same nine**, so it cannot reach an instance, a volume or an AMI. It carries **no
  condition**: `ec2:CreateAction` does not exist as a condition key on `DeleteTags`, so a condition
  there is an implicit deny that can never be widened without a refresh that itself needs the grant —
  and on `CreateTags` it would forbid tagging anything that already exists, **which is exactly what
  `aws_default_security_group` is**.
- **The logs queue statement names BOTH `-logs` and `-logs.fifo`.** A FIFO queue's name must end in
  `.fifo`, which made that rename a **destroy-and-create**, so the one apply performing it needed
  `DeleteQueue` on the old name and `CreateQueue` on the new one **at the same time**. The old ARN
  stays: removing it would only reclaim permission to manage a queue that no longer exists, and
  re-adding it is exactly the grant a rollback would need.
- **`iam:PassRole` on the platform's front-door policy is split into THREE statements**, because a
  statement carries one condition block and the four roles are passed to three different services — **a
  single `iam:PassedToService` listing all three would let the flow-logs role be handed to ECS**. The
  fourth role is the VPC flow-logs delivery role: flow logs to CloudWatch are delivered **as** a role,
  so one exists even though no resource in the platform's own list names it, and **a grant written
  from that list alone is short by one**.
- **There is no `iam:AttachRolePolicy`, and that absence is load-bearing.** Every role carries
  **inline** policies rendered from `.tftpl`, which `PutRolePolicy` covers. The one that invites a
  managed attachment is the ECS task execution role — AWS publishes `AmazonECSTaskExecutionRolePolicy`
  for exactly it — and that grant is deliberately **narrower and written out**, so the wildcard it
  would otherwise hide behind an attachment **stays visible to the scanner**. Reaching for the managed
  policy fails at the attach, **which is where that decision should be re-made**.
- **The verification policy has no `iam:PassRole`**, unlike every plane's: a service assumes those,
  and **nothing must be able to hand this one to a service**.

## Absences that are decisions

- **No `lambda:*EventSourceMapping` on the observability policy.** The sweep is pulled by a
  **schedule**, not a managed poll loop — **idle long-polling was the bulk of this account's SQS
  request volume** — and the absence of the grant is what keeps a future "just add an event-source
  mapping" from applying cleanly **without a deliberate decision**.
- **No SQS resource grants on the DLQ-drain policy.** The drain **creates no queue** — it reads the
  four request DLQs the plane modules already own, whose ARNs reach it through Terraform state, so the
  deploy role makes no SQS API call for them. The drain's **runtime** access is a grant on its
  *execution* role.
- **No S3 statement on the user-directory policy.** The builder writes an object, but the **deploy**
  role never touches it — it only creates the function and its role. What the deploy role needs on
  that bucket it already holds via `S3UserSpaceBucketManage`. **A second S3 statement would be a
  duplicate, not a tightening**, and the same applies to the observability policy's admin-bucket
  access.
- **No layer grant on most plane policies.** `deploy_control_plane_common` covers the shared
  `cpcommon` layer, deliberately scoped to the **layer ARN and nothing else** — so every verb that
  attached it was covered by its own policy's function-manage grant plus that one layer grant.
  **No function attaches a layer any more and nothing publishes one**; these grants are what the
  published versions are destroyed with, and they come out after that.
- **An `events:` statement means one of two things, and they are not the same thing.** The commoner
  is a `TIMED_OUT` rule: a machine that validates and stops has none to manage, so the grant arrives
  with the transfer that adds the ceiling. **`file-ops` is the exception among those and carries it
  from its first version** — not copied habit: its per-space lock's **waiting loop** is in the
  machine before any data work is, so it ships with the rule from day one, **and the grant has to be
  here or the first apply fails on the rule rather than on anything to do with the plane's purpose**.
  The other is a **schedule**, which has nothing to do with a ceiling: `user-directory`,
  `observability` and `control-plane-dlq-drain` are all schedules, and **`shared-spaces` now holds
  one too** — for the reader that picks operator-driven ownership transfers out of the admin bucket
  — while that plane still carries no `TimeoutSeconds` at all. Reading the grant as evidence of a
  ceiling gets that plane exactly backwards.
- **No data-quality workgroup grant.** Those verbs run in the **shared** portal Athena workgroup,
  because a dedicated one breaks Lake Formation — so there is no plane-specific workgroup to grant on.
- **No S3-bucket-manage statement on most plane policies**, because most planes create no bucket. The
  **archive** policy is the first that does.

## The push grants live with the platform

The deploy role creates the ECR registry **and writes to it**, because the image pipeline runs as that
role. **A registry token with no layer-upload actions beside it would authorize nothing at all**, so
`ecr:GetAuthorizationToken` and the layer/manifest actions travel together, the latter scoped to
this project's **two** repositories — the SPA's and the Lambda container image's, which ride the
same two statements rather than a second pair of them.
