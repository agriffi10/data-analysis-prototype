# Terraform (OpenTofu) — module index

Every module under `infra/modules/`, and what it owns. This is a **lookup**: find the resource, open
the one module. Each module's own `README.md` carries the reasoning its `.tf` files used to hold
inline — what applies green when it is wrong, and what must not be "tidied".

**A module is one architectural concept, and the root composes them.** A concept built once is a
module the root calls once (`auth`, `api`, `data`, …). A concept built more than once is a
**building block** the root calls once per instance, passing every dependency in: the eight control
planes are eight calls to [`control-plane`](../modules/control-plane/README.md), each in its own
root file with its plane-specific configuration beside it. The rule and its reasoning are the IaC
decision in `docs/decisions/infrastructure/`.

## Layout

| Path | Holds |
|---|---|
| `infra/main.tf` | the root: every module block a single concept needs, and the locals that construct cross-module ARNs |
| `infra/plane-<slug>.tf` | one control plane: its verbs, environment, queue settings, ceiling and caps, its call to `control-plane`, and any module only it uses |
| `infra/planes/<slug>/` | that plane's ASL definition, execution policy and README — what is distinct about it |
| `infra/control-planes.tf` | the constructed ARNs every plane's execution policy may name |
| `infra/moved.tf` | every address a refactor changed, kept until every state has applied it |
| `infra/variables.tf` / `outputs.tf` | the stack's inputs and its published values |
| `infra/certificates.tf` | the ACM certificates and their validation records |
| `infra/modules/<name>/` | one concept — resources, `locals.tf`, `policies/*.tftpl`, and its README |
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
| `lambda-artifacts` | the bucket CI staged Lambda zips in — **nothing writes to it and nothing reads it**; retiring it is nobody's spec yet | [README](../modules/lambda-artifacts/README.md) |
| `observability` | the structured-logging queue and its scheduled sweep | [README](../modules/observability/README.md) |
| `lambda-image` | the registry CI pushes the Lambda container image to | [README](../modules/lambda-image/README.md) |
| `docker-lambda` | one container-packaged function; every Lambda in the repo is a call to it | [README](../modules/docker-lambda/README.md) |

## Delivery

| Module | Owns | README |
|---|---|---|
| `spa` | the **container** path — Fargate cluster/service, ALB, and the admin bucket's first policy | [README](../modules/spa/README.md) |
| `spa-image` | the registry CI pushes the SPA container image to, kept outside `spa` so it survives the off switch | [README](../modules/spa-image/README.md) |
| `static-portal` | the portal without a VPC: the S3 bucket, the distribution and the alias, while the web tier is off | [README](../modules/static-portal/README.md) |
| `api` | the HTTP API, its Lambda, custom domain and DNS record | [README](../modules/api/README.md) |

**`network` and `spa` have an off switch, and `static-portal` is its other side.** Idle, the two are
most of what the stack costs, so `web_tier_enabled = false` removes both whole and CloudFront and S3
serve the portal instead. How to switch it: [`web-tier.md`](web-tier.md).

## Control planes

Each is a FIFO queue → EventBridge Pipe → Step Function → verb Lambdas, with **its own DLQ**, built by
one call to [`control-plane`](../modules/control-plane/README.md), whose README carries the shape and
every trap the planes share.

| Plane | Root file | Distinct reasoning |
|---|---|---|
| shared spaces | `plane-shared-spaces.tf` | [README](../planes/shared-spaces/README.md) |
| create a table over a folder, and refresh it in place | `plane-table-builder.tf` | [README](../planes/table-builder/README.md) |
| share a table with other users | `plane-table-share.tf` | [README](../planes/table-share/README.md) |
| profile a table around one Athena query | `plane-data-quality.tf` | [README](../planes/data-quality/README.md) |
| send files to another user or space | `plane-file-send.tf` | [README](../planes/file-send/README.md) |
| archive to a GLACIER vault and restore | `plane-archive.tf` | [README](../planes/archive/README.md) |
| move, copy and delete, behind a per-space lock | `plane-file-ops.tf` | [README](../planes/file-ops/README.md) |
| a finished execution's result set into a space, as Parquet, JSON, Excel or CSV | `plane-results-conversion.tf` | [README](../planes/results-conversion/README.md) |

| Building block or plane-owned module | Owns | README |
|---|---|---|
| `control-plane` | the machine every plane runs | [README](../modules/control-plane/README.md) |
| `scheduled-function` | one function on an EventBridge schedule — shared spaces' transfer reader | [README](../modules/scheduled-function/README.md) |
| `shared-space-storage` | **the shared-space bucket (Bucket 2)**, its Lake Formation registration and the portal role's grant on it | [README](../modules/shared-space-storage/README.md) |
| `archive-vault` | **the archive bucket (Bucket 5)** and its policy | [README](../modules/archive-vault/README.md) |

## Standalone

| Module | Owns | README |
|---|---|---|
| `notifications` | the notifications FIFO queue and its **single writer** | [README](../modules/notifications/README.md) |
| `feedback` | the feedback FIFO queue and its **single writer** — written only by the API, with a top-level username rather than an `identity` block, and an undrained DLQ | [README](../modules/feedback/README.md) |
| `control-plane-dlq-drain` | one scheduled drain over every plane's request DLQ | [README](../modules/control-plane-dlq-drain/README.md) |
| `user-directory` | the daily username-directory builder | [README](../modules/user-directory/README.md) |
| `verification` | the archive-audit CloudTrail trail and the read-only verification role | [README](../modules/verification/README.md) |

## The buckets

Four, and the constraint is one bucket of **personal prefixes**, not one bucket overall.

| Bucket | Module | Notes |
|---|---|---|
| user-space | `data` | Bucket 1. Every top-level prefix is a username, with `_directory/` the one exception |
| shared-space | `shared-space-storage` | Bucket 2. **No bucket policy** — which is why an allowlist omission half-works |
| admin | `analytics` | Athena fallback output, the registry, the control planes' scratch, `logs/` (retained forever) |
| archive | `archive-vault` | Bucket 5. GLACIER, and the browser has no relationship with it at all |

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
4. **A module-level `depends_on` defers every data source in that module** to apply time, so no
   module behind one reads any: a deferred document is one the plan-time IAM scan cannot read, and a
   deferred value feeding a `for_each` or a ForceNew attribute is a hard error or a replacement.
   `lambdas/test_depends_on_defers_no_data_source.py` refuses the shape.
5. **A role that touches the user-space bucket must join that bucket policy's allowlist in the same
   PR** — an explicit resource-policy Deny beats an identity-policy Allow, and the omission reads as a
   code bug.

## Related

- [`lambdas/info/INDEX.md`](../../lambdas/info/INDEX.md) — every function, grouped by control plane
- [`deploy-role-iam.md`](deploy-role-iam.md) — the trap list for adding a new AWS resource type
- [`web-tier.md`](web-tier.md) — switching the web tier off and back on
- `docs/architecture.md` → *Infrastructure and delivery* — how this fits the running system
- [`docs/decisions/index.yaml`](../../docs/decisions/index.yaml) — the fences of the reasoning register, one directory per area
- [`../bootstrap/README.md`](../bootstrap/README.md) — remote-state bootstrap
