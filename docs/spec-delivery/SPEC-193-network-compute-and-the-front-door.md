# Completed Spec — SPEC-193: The Network, the Compute and the Front Door

## What was completed?

The platform the rest of Arc B runs on: a VPC whose private subnets reach AWS through endpoints and
reach nothing else, an HTTP API on its own hostname, and a Fargate service behind a load balancer on
another. Two ACM certificates, two alias records, and three allowlists that **add** the new origins
beside the old ones so CloudFront stays a working rollback.

Nothing a user can see changes. `portal.dataquarry.app` serves a placeholder nobody is pointed at.

- **`infra/modules/network/`** — a VPC across two AZs, 2 public + 2 private /20s, `ecr.api`,
  `ecr.dkr` and `logs` interface endpoints, an S3 **gateway** endpoint, flow logs to a 14-day group,
  and **no NAT gateway anywhere in the tree** (asserted repo-wide, not module-scoped).
- **`infra/modules/api/`** — an HTTP API with a `$default` route, a regional custom domain, CORS
  admitting both origins, access logging, and a placeholder function that is **not in the VPC**.
- **`infra/modules/spa/`** — an ECR repository (immutable, scanned, AES256, bounded lifecycle), an
  ECS cluster with Container Insights, two task roles (the task role holds **nothing**), a task
  definition, a service on platform 1.4.0 in the private subnets, an ALB with a TLS 1.3 listener and
  a redirect-only :80, every rule on both security groups, the admin bucket's **first** policy, and
  the SPA alias record.
- **The runtime-configuration block** — the fifth wiring point. Root names the 20 keys and their
  values in `local.spa_runtime_config`; the module renders one `CONFIG_<key>` variable per entry,
  derived, so a container cannot ship carrying part of the document.
- **`.github/workflows/push-placeholder-image.yml`** — dispatch-only, idempotent, and **SPEC-194
  deletes it** when the real image pipeline lands.
- Deploy-role IAM across two managed policies, `dat-deploy-platform` and
  `dat-deploy-platform-frontdoor`, because one document exceeds the 6,144-character limit.

## The four traps this spec actually found

None was predicted, and each cost an apply.

1. **`ec2:GetSecurityGroupsForVpc`** — ELBv2 calls it **on the caller's behalf** inside
   `CreateLoadBalancer`, so it appears in no `elasticloadbalancing:` action list and survives a sweep
   of every ELB call the provider makes. Scopable: the Service Reference gives it one resource type,
   `vpc`.
2. **A condition on a key the caller does not populate fails CLOSED.** ELB validates the access-log
   bucket policy with a `PutObject` of its own at `ModifyLoadBalancerAttributes` time.
   `StringEquals aws:SourceAccount` was refused; `ArnLike aws:SourceArn` alone was refused
   identically. The shipped policy carries **no condition** and grants **both** delivery principals —
   which of the two AWS uses was never isolated, and the narrowing is `owed.md` §2.9.
3. **`ignore_changes = [task_definition]` means CI must point the service.** Terraform registered the
   revision carrying the image and left the service on revision 1, whose `:placeholder` tag nobody
   had pushed. The symptom was a `CannotPullContainerError` — **indistinguishable from the endpoint
   failure this whole platform is tested for**, and the first minute of diagnosis went to the
   network.
4. **A Fargate task volume arrives EMPTY and ROOT-OWNED, and does not initialise from the image.**
   The container printed `uid=101(nginx)` beside `drwxr-xr-x root root /var/cache/nginx` — a path the
   base image ships owned by 101. So FR-005 AC3's mechanism cannot give a **non-root** container a
   writable path under `readonlyRootFilesystem`. `linuxParameters.tmpfs` can, because its
   `mountOptions` take `uid`/`gid`/`mode`, and **Fargate accepts it**: revision 5 registered and the
   mounts came back `drwxrwxrwt nginx nginx`.

**Two hypotheses were wrong before the fourth was measured** — that the mount would be writable, and
that seeding `/tmp` in the image would carry ownership through. The third attempt printed `id` and
`ls -ld` instead of guessing again, and answered it in one cycle. That is the transferable lesson:
when two guesses have failed, spend a deploy on output rather than a third hypothesis.

## The non-scopable actions, as measured

`iam:SimulateCustomPolicy` produced an `implicitDeny`/`allowed` pair for every wildcard before it was
written. The wildcard statements hold only: the EC2, ELB and ECS `Describe*` family with no resource
type, the eight `logs:` delivery actions HTTP API access logging needs, `acm:RequestCertificate` and
`ListCertificates`, `ecs:DescribeTaskDefinition`/`DeregisterTaskDefinition`/`ListTaskDefinitions`, and
**`ecr:GetAuthorizationToken`** — whose five layer and manifest siblings all scope to the repository.

Contradicting the spec's predictions: **`ec2:DescribeVpcAttribute` IS scopable** (to `vpc/*`),
**`route53:GetChange` IS scopable** (to `change/*`), and **`ecs:RegisterTaskDefinition` scoped by
resource TYPE works** — the task definition was created on the first apply, settling a question the
ECS developer guide and the Service Reference disagree about.

## The endpoint set the pull really needed

Exactly the three interface endpoints and the one gateway endpoint the design named:
`com.amazonaws.us-east-1.ecr.api`, `.ecr.dkr`, `.logs`, all with `private_dns_enabled`, and the S3
**gateway** endpoint whose `RouteTableIds` equals the private route tables. Measured at the moment
the pull succeeded: both private tables carried `10.0.0.0/16 local` and `pl-63a5400a` and **no
`0.0.0.0/0` of any kind**. The pull is only evidence about the endpoints when it is read beside that.

## Did the first apply fail, and on what?

**Yes, four times, and never on the same thing.** `ec2:GetSecurityGroupsForVpc`; then the access-log
policy's `aws:SourceAccount`; then its `aws:SourceArn`; then the fourth apply succeeded and the
failures moved into the container. The grants-first rule held everywhere it was applied — every
grants-only PR applied green on its first run.

## What is deliberately not claimed

Nothing here is evidence about session, auth, the real SPA, or any ported route. Production is still
CloudFront. The API is internet-facing, unauthenticated and unthrottled, accepted in `owed.md` as a
billing exposure rather than a disclosure one, with SPEC-196 named as owner.
