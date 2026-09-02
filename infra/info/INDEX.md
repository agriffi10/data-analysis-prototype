# Terraform (OpenTofu) — module index

Every module under `infra/modules/`, and what it owns. This is a **lookup**: find the resource, open
the one module. Each module's own `README.md` carries the reasoning its `.tf` files used to hold
inline — what applies green when it is wrong, and what must not be "tidied".

The seven control planes share one machine; that shape is written once in
[`control-plane-shape.md`](control-plane-shape.md), so each of their READMEs carries only what is
distinct.

## Layout

| Path | Holds |
|---|---|
| `infra/main.tf` | the root: every `module` block, and the locals that construct cross-module ARNs |
| `infra/variables.tf` / `outputs.tf` | the stack's inputs and its published values |
| `infra/certificates.tf` | the ACM certificates and their validation records |
| `infra/modules/<name>/` | a bounded context — resources, `locals.tf`, `policies/*.tftpl`, and its README |
| `infra/bootstrap/` | the one-time remote-state (S3 + DynamoDB) bootstrap |

**IAM policies are `.tftpl` templates rendered with `templatefile()`** — never inline `jsonencode`.
**An IAM policy document must be printable ASCII, so rationale never goes in a `.tftpl`**: comment
keys with em dashes are rejected at `CreatePolicy`, invisible to `tofu validate` and to the plan.

## Foundations

| Module | Owns | README |
|---|---|---|
| `base` | the GitHub OIDC provider, the **deploy role**, and every grant it holds | [README](../modules/base/README.md) |
| `network` | the VPC, subnets, route tables, VPC endpoints, security groups, flow logs | [README](../modules/network/README.md) |
| `data` | the **user-space bucket** (Bucket 1) and the shared **portal role** | [README](../modules/data/README.md) |
| `auth` | the Cognito User Pool, its SPA client, the Hosted UI domain and both triggers | [README](../modules/auth/README.md) |
| `analytics` | the Athena workgroup, the **admin bucket**, and the **Lake Formation** bootstrap | [README](../modules/analytics/README.md) |
| `lambda-artifacts` | the bucket CI stages Lambda zips in | [README](../modules/lambda-artifacts/README.md) |
| `observability` | the structured-logging queue and its scheduled sweep | [README](../modules/observability/README.md) |
| `lambda-image` | the registry CI pushes the Lambda container image to | [README](../modules/lambda-image/README.md) |

## Delivery

| Module | Owns | README |
|---|---|---|
| `spa` | the **container** path — ECR, Fargate cluster/service, ALB, and the admin bucket's first policy | [README](../modules/spa/README.md) |
| `api` | the HTTP API, its Lambda, custom domain and DNS record | [README](../modules/api/README.md) |

The container is the only delivery path. CloudFront and the static bucket were destroyed with the
`app` module; the container reproduces every job the distribution did, with three deliberate
divergences, and the deploy role's grants on both came off one apply later.

## Control planes

Each is a FIFO queue → EventBridge Pipe → Step Function → verb Lambdas, with **its own DLQ**. Shape
and shared traps: [`control-plane-shape.md`](control-plane-shape.md).

| Module | Plane | README |
|---|---|---|
| `shared-spaces` | shared spaces, **and the shared-space bucket (Bucket 2)** | [README](../modules/shared-spaces/README.md) |
| `table-builder` | create a table over a folder, and refresh it in place | [README](../modules/table-builder/README.md) |
| `table-share` | share a table with other users | [README](../modules/table-share/README.md) |
| `data-quality` | profile a table around one Athena query | [README](../modules/data-quality/README.md) |
| `file-send` | send files to another user or space | [README](../modules/file-send/README.md) |
| `archive` | archive to a GLACIER vault and restore, **and the archive bucket (Bucket 5)** | [README](../modules/archive/README.md) |
| `file-ops` | move, copy and delete, behind a per-space lock | [README](../modules/file-ops/README.md) |

## Standalone

| Module | Owns | README |
|---|---|---|
| `notifications` | the notifications FIFO queue and its **single writer** | [README](../modules/notifications/README.md) |
| `feedback` | the feedback FIFO queue and its **single writer** — the one queue the browser has no grant on at all | [README](../modules/feedback/README.md) |
| `control-plane-dlq-drain` | one scheduled drain over every plane's request DLQ | [README](../modules/control-plane-dlq-drain/README.md) |
| `user-directory` | the daily username-directory builder | [README](../modules/user-directory/README.md) |
| `verification` | the archive-audit CloudTrail trail and the read-only verification role | [README](../modules/verification/README.md) |

## The buckets

Four, and the constraint is one bucket of **personal prefixes**, not one bucket overall.

| Bucket | Module | Notes |
|---|---|---|
| user-space | `data` | Bucket 1. Every top-level prefix is a username, with `_directory/` the one exception |
| shared-space | `shared-spaces` | Bucket 2. **No bucket policy** — which is why an allowlist omission half-works |
| admin | `analytics` | Athena fallback output, the registry, the control planes' scratch, `logs/` (retained forever) |
| archive | `archive` | Bucket 5. GLACIER, and the browser has no relationship with it at all |

Plus the Lambda artifacts bucket (`lambda-artifacts`) and the CloudTrail bucket (`verification`).

## Before you add a resource type

1. **The deploy role's grant lands in its own PR, applied before the resources that need it.** Adding
   a new resource type trips recurring IAM traps — self-grant timing, non-scopable actions, refresh
   deadlocks, unknown-ARN-in-list. Read [`deploy-role-iam.md`](deploy-role-iam.md) and
   [`../modules/base/README.md`](../modules/base/README.md) first.
2. **Measure scopability with `simulate-custom-policy`**, never assume it. Actions with no resource
   type sit alone in a wildcard statement.
3. **Cross-module ARNs are constructed strings from the root locals**, never another module's output —
   an unknown ARN inside `compact()` or a list **silently drops the change**.
4. **A module-level `depends_on` defers every data source in that module** to apply time. Benign for a
   policy document; a hard error where the value feeds a `for_each` or a ForceNew attribute.
5. **A role that touches the user-space bucket must join that bucket policy's allowlist in the same
   PR** — an explicit resource-policy Deny beats an identity-policy Allow, and the omission reads as a
   code bug.

## Related

- [`lambdas/info/INDEX.md`](../../lambdas/info/INDEX.md) — every function, grouped by control plane
- [`deploy-role-iam.md`](deploy-role-iam.md) — the trap list for adding a new AWS resource type
- `docs/architecture.md` → *Infrastructure and delivery* — how this fits the running system
- [`docs/decisions/INDEX.md`](../../docs/decisions/INDEX.md) — the full reasoning register, one file per area
- [`../bootstrap/README.md`](../bootstrap/README.md) — remote-state bootstrap
