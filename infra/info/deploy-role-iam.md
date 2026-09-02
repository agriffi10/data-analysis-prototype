# Adding a new resource type to the IaC

The deploy role **self-grants** — `module.base` writes the permissions the same `tofu apply` then
uses — so every new resource type in `infra/` walks the same short list of traps. Work through this
page before merging, and read [`../modules/base/README.md`](../modules/base/README.md) for what the
role already holds and why it is split across one managed policy per resource family.

**The grant lands in its own PR, applied before the resources that need it.** Every plane module's
"no `time_sleep` guard is required here" comment is relying on that split.

## The traps

- **Self-grant propagation.** A freshly-granted permission may not have propagated by the time a new
  resource uses it. Gate first-use resources on a `time_sleep` (~60s). Caveat: a `time_sleep` with no
  `triggers` runs **once** at creation and never re-fires — so adding an Nth resource that `depends_on`
  an existing sleep gets zero delay and can hit `AccessDenied` on the **first** apply. Accepted fix:
  **re-run the deploy** (`module.base` attaches the policy first, so the grant is propagated by the
  re-run). Expect one first-apply failure when extending an existing module, then a clean re-run.

  > **Superseded for the two PLATFORM policies (2026-08-26).** Re-run is no longer the accepted
  > remedy there: `time_sleep.wait_for_platform_grant` sits **after** their attachments and carries
  > `triggers` keyed to both policy bodies, so it re-fires whenever a grant changes. Measured, and
  > the reason it stopped being acceptable: a grant written at `14:56:08.95` was refused at
  > `14:56:10.67` and `main` went red. Two lessons generalise beyond those policies — **placement**
  > (a sleep guarding the inline policy sits at the top of the graph and cannot cover a managed
  > policy written far below it) and **the failing shape** (this was an existing policy *modified*,
  > not the "Nth resource added" the rule above describes, which is the commoner case). The rule as
  > written still holds for the control-plane policies, whose sleeps remain create-only.
- **A service may call an action ON YOUR BEHALF that appears in no action list for it (2026-08-26).**
  ELBv2 calls `ec2:GetSecurityGroupsForVpc` inside `CreateLoadBalancer`, so a sweep of every
  `elasticloadbalancing:` action the provider makes finds nothing, and the apply fails on an EC2
  permission while creating a load balancer. It is scopable (`vpc`), like most of them.
- **The provider's call is the authority, not the action's name (2026-08-26).** `aws_ecs_cluster`
  calls `ecs:UpdateCluster` on any `setting` change and calls `UpdateClusterSettings` never — the
  grant named the second, and the first apply that edited the cluster would have failed on main.
  Read the resource's source at the pinned version when a grant looks obviously right.
- **A condition on a key the caller does not populate fails CLOSED (2026-08-26).** ELB validates the
  access-log bucket policy with a `PutObject` of its own; `aws:SourceAccount` and then
  `aws:SourceArn` were each refused alone, and the message named neither. An "extra" condition is not
  a tightening — it is a bet that the caller supplies the key.
- **Some actions are not resource-scopable** — they only authorize on `Resource: "*"`; a narrower ARN
  is an implicit deny. Known offenders: `logs:DescribeLogGroups`, `cognito-idp:DescribeUserPoolDomain`,
  `cognito-idp:CreateUserPool`. Put each in its own `"*"` statement. Verify scopability cheaply with
  `aws iam simulate-custom-policy --action-names <a> --resource-arns <arn>` (`allowed` vs `implicitDeny`)
  before spending a CI round.
- **CloudWatch log-group actions need both ARN forms.** `logs:ListTagsForResource` authorizes against
  the **bare** ARN (`…:log-group:NAME`) while others use the `…:log-group:NAME:*` form — scope the
  statement to a list of both.
- **An action that CREATES a numbered resource authorizes against the un-numbered one.**
  `ecs:RegisterTaskDefinition` creates revision 1, so at the moment of the call there is no revision
  for an ARN to carry. A grant scoped to `task-definition/NAME:*` matched every revision and not the
  register itself. Generalise it: whenever the action's own effect is to mint the identifier the ARN
  would contain, the pattern has to cover the form **without** it. Writing one pattern that covers
  both is usually enough — IAM's `*` spans `:`, so `task-definition/NAME*` matches `NAME` and
  `NAME:1` alike, and a separate `…:*` line beside it is dead.
  **Two documentation traps here, both live:** the ECS developer guide still states *"Task definition
  IAM policies do not support resource-level permissions"* with a `Resource: "*"` example, and the
  roadmap issue asking for them is still open — both contradicted by the Service Reference, which is
  what IAM evaluates against. Trust the Service Reference. And note what a policy simulate can
  answer: whether a **pattern matches a string**, never **which resource the service passes** — so it
  can prove a grant sufficient and cannot tell you which form is required.
- **`s3:ListBucketMultipartUploads` does not support `s3:prefix`** — under a prefix condition it is
  always an implicit deny (a dead grant), and it would leak other users' in-progress uploads. Don't
  grant it. The prefix-scopable multipart actions are `s3:AbortMultipartUpload` /
  `s3:ListMultipartUploadParts`; create/upload/complete ride on `s3:PutObject`.
- **Refresh-before-policy-update deadlock.** Once a resource is in state, `tofu apply` **refreshes**
  it (using the role's *current* policy) before applying the policy fix — so a scope fix that the
  refresh itself needs can never land. **Break-glass (preferred): dispatch `Deploy Infrastructure`
  with `skip_refresh=true`**, which applies from cached state; then dispatch again *normally*, because
  an apply that skipped refresh has proved nothing about drift. Out-of-band `aws iam put-role-policy`
  remains the fallback when even that cannot run.
  - **Tightening a grant deadlocks exactly like widening one** (the SPEC-139 follow-up). Two
    imperatives: (a) a **mapping ARN and a function ARN are different resource types** — check
    every resource type an action accepts before scoping, not just the one you have in mind;
    (b) **a green `plan` is not proof the apply will work** — IAM is eventually consistent.
    Narrative: `docs/decisions/infrastructure.md` → *Deploy-role refresh deadlock*.
- **Resource policies (bucket/KMS) can lock out the deploy role too.** Always **except the deploy role**
  from any resource-policy `Deny` that covers a read the AWS provider uses on refresh — otherwise the
  provider sees the resource as "deleted" and every plan proposes a destructive recreate. Same
  break-glass shape (`put-bucket-policy` out-of-band, then merge).
- **`depends_on` defers data sources (benign plan noise).** `module.auth`/`module.data` declare
  `depends_on = [module.base]`, so any PR touching `module.base` makes their data sources unknown at
  plan → cascades to `(known after apply)` and can show the identity-pool principal tag as
  *force-replace*. At apply these resolve to identical values (no-op / identical recreate). This is
  **not** drift — don't panic at the plan.
- **An unknown ARN inside `compact()`/a list silently drops the change.** A cross-module ARN that is
  unknown-at-plan (e.g. a role created in the same apply) inside `compact()` made OpenTofu plan *no*
  change to a list attribute — the value was never written. **Rule:** any cross-module ARN feeding a
  list/set attribute must be a **constructed string in root `locals`** (so it's known at plan time);
  apply ordering is still preserved via the `depends_on` chain.
- **Lake Formation enforcement hides the catalog from non-admins.** After LF enforcement, a principal
  with no LF grant sees empty `get-databases` / `AccessDenied` on `list-permissions` — that's the
  isolation working, not a failure. Verify per-user provisioning via the post-confirmation Lambda's
  CloudWatch logs or by querying as an LF admin (only the deploy role + control-plane execution
  roles + post-confirmation exec role are LF admins).

- **A container-packaged Lambda needs registry actions on the role that CREATES it, not only on
  Lambda.** AWS requires `ecr:GetRepositoryPolicy`, `ecr:SetRepositoryPolicy`, `ecr:BatchGetImage`
  **and `ecr:GetDownloadUrlForLayer`** on the *caller* of `CreateFunction` — the last of which this
  role held for neither registry, because pushing an image needs `BatchGetImage` and pulling one
  into a function needs both. Nothing in an action list says so; it is the same shape as ELB calling
  `ec2:GetSecurityGroupsForVpc` inside `CreateLoadBalancer`. Same-account image pulls need no
  repository policy of their own: given the two `RepositoryPolicy` actions, Lambda writes
  `LambdaECRImageRetrievalPolicy` itself. Declaring that policy in Terraform instead is a standing
  diff against a document Lambda wrote.

## The ForceNew data-source trap

**Inside a module carrying a module-level `depends_on`, prefer a variable over a data source for
anything feeding a ForceNew attribute.** A pending change in the dependency defers the data source to
apply time, and `(known after apply)` on a ForceNew attribute plans *"must be replaced"*. This had
every infra apply destroying and recreating `module.auth`'s identity-pool principal-tag mapping — the
ABAC keystone — until `data.aws_region.current.name` became `var.aws_region`.

`ignore_changes` is the wrong tool here, because nothing drifts. Contrast
`aws_lakeformation_permissions`, where the API genuinely reads back different values and
`ignore_changes` is correct. The `archive_file` placeholders that used to defer the same way are gone
with the container cutover — a container function is valid from its image, so no bootstrap artefact
is rendered at all. The case this rule was learned
on — the Identity Pool's principal-tag map, replaced on every infra merge because a module-level
`depends_on` made its `data.aws_region` unknown at plan time — is gone with the pool, so the
narrative is in git history rather than beside a resource.

## The role's own budgets, and the forced wildcard

Neither failure here is visible in a plan. `lambdas/test_deploy_platform_policies.py` measures
**every** managed policy against the per-document budget, and holds the wildcard rule;
`lambdas/test_feedback_deploy_grant.py` holds the attach ceiling against the role's own
attachment count, and re-checks its own document.

**The budgets.** IAM's 10,240-character limit is the **aggregate** of a role's inline policies,
not a per-policy allowance, and `github-actions-deploy.json.tftpl` already spends most of it —
no figure here, for the reason the platform policy's is not written down either: the last one
was a thousand characters stale, and `test_the_inline_deploy_policy_stays_under_the_iam_aggregate`
measures the live one. A customer-managed policy has its own separate 6,144-character budget, and a role may carry only
so many of them. All three ceilings are enforced at `CreatePolicy` / `PutRolePolicy` /
`AttachRolePolicy` — an apply-time `LimitExceeded` on a document that rendered, validated and
planned green. The container platform's grants are two managed policies rather than one for
exactly this reason.

**Which one you can buy your way out of, read from the account.** The 6,144 is Service Quotas
`L-ED111B8C`, `Adjustable: false` — a hard limit, so a document over it gets **split**, never a
quota request. The attach ceiling is `L-0DA4ABF3`, adjustable, and twenty is AWS's own default
rather than a raise this account already spent (`get-aws-default-service-quota` and
`get-service-quota` both return 20; it is auto-approved up to 25).

**`github-actions-deploy-platform` is the one near its line** — the largest managed policy, and
the only one far enough along that a statement added without looking fails the apply. No current
figure is written down here, because the last one written down rotted; the suite names the policy
and both numbers when one goes over, so measure there.

**The wildcard.** `Resource: "*"` on a deploy grant is sometimes forced and sometimes laziness,
and the two read identically in a diff. IAM defines no resource type at all for the actions in
that suite's `NON_SCOPABLE` set, so a narrower ARN on one of them is an implicit deny that
presents as a missing grant; every other action accepts an ARN and must carry one. The set was
**measured**, not assembled by eye — each entry read back from `aws iam simulate-custom-policy`
as `implicitDeny` under a scoped ARN of its own service and `allowed` under `"*"`. The
`implicitDeny` leg alone proves nothing, because a wrong ARN reads exactly the same; the
`allowed` control is what makes the pair evidence. It is a recorded measurement rather than a
live read of the AWS Service Reference: a test that reaches the network fails on a runner with no
egress and passes by finding nothing when the endpoint changes shape.

## Preserving an authorization artefact across a move

`lambdas/test_portal_role_preservation.py` checks the "this rewrites no existing artefact" claim
**artefact by artefact**, because a claim asserted once is a claim nobody checked.

**The no-change guard is a named-absence assertion plus a git baseline, never a snapshot.** A test
that captures the rendered templates during the build and diffs them against themselves compares a
copy of the answer with itself and passes whatever happens. So the byte comparison is against the
**pre-change blob in git**, and the file set is enumerated from that same commit — a glob of the
working tree with a length check passes a deletion, because the deleted file is simply not in the
glob.

**A template the change edits needs its own baseline, and that is the easy one to miss.** The blob
comparison excludes the trust template, so "the existing statement is untouched" has nothing to
compare against. Asserting that `sts:AssumeRoleWithWebIdentity` still appears would survive someone
changing that statement's principal, its conditions, or dropping `sts:TagSession` from it — so it is
asserted whole, against a literal second copy, for the same reason the CSP terms are.

## Domain variables: an empty one is not an unset one

The domain variables carry no default on purpose, but a missing default only fails when the
variable is genuinely absent — and an unset GitHub repo variable does not arrive absent. `${{
vars.X }}` renders as the **empty string**, which satisfies a required variable and overrides a
defaulted one alike. Measured on OpenTofu: with `TF_VAR_spa_subdomain=""` the origin plans as
`https://.example.com`, plausible enough to be requested and refused only at apply, by ACM, in a
message that does not name the repo variable behind it. Guard with `validation`, never with the
absence of a default.

**The zone id's shape is the same guard in the other direction.** It is rendered into the deploy
role's Route 53 statement as well as into the records, and IAM matches ARNs literally. The
`/hostedzone/`-prefixed form the API returns names the right zone, reads correct to a human, and
yields a grant that matches nothing — so every record write is denied for a reason the value does
not look like it could cause.

## Related

- [`INDEX.md`](INDEX.md) — the module index, and the five-point version of this page
- [`../modules/base/README.md`](../modules/base/README.md) — every grant the deploy role holds
- [`docs/decisions/infrastructure.md`](../../docs/decisions/infrastructure.md) — the full reasoning register for this area
