# How a Lambda gets deployed

Lambda **code** and Lambda **infrastructure** are deliberately separated, and `tofu apply` never
touches code. This page is the split, and the traps that only appear at deploy time. What each
function *is* lives in [`INDEX.md`](INDEX.md); how a plane works lives in [`planes/`](planes/).

## The split

| Owner | Owns |
|---|---|
| The repo | `lambdas/<function-name>/<module>.py` and its tests, plus a shared `lambdas/requirements.txt` |
| Terraform | the function resource, its execution role, its log group and its trigger wiring — bootstrapped with an inline `archive_file` placeholder and `lifecycle { ignore_changes = [filename, source_code_hash, layers] }` |
| GitHub Actions | the Python code and **every layer attachment** — `deploy-lambdas.yml` matrixes over the functions, builds each package, uploads it to the artifacts bucket at `<name>/<git-sha>.zip`, and runs `update-function-code --publish` |

**Use underscores in the `.py` filename** (`pre_signup.py`, handler `pre_signup.handler`) — a
hyphenated filename cannot be imported as a module, and the directory name is hyphenated.

**IAM trust and permission policies are `.tftpl` templates** under the owning module's `policies/`,
rendered with `templatefile()`. No inline `jsonencode` IAM policies anywhere.

**`ignore_changes` must name `layers`.** Without it, an apply landing after a deploy strips the layer
back off and the function fails at its next cold start on an import that had been working.

## Layers deploy like code

CI builds and publishes `cpcommon`, each plane's `*-common` layer and polars, then attaches them.
Terraform never manages a layer version. `lambdas/test_deploy_matrix.py` joins the deploy matrix
against what each function actually **imports** — the gate that catches a function shipped without a
layer it needs, which is the failure that broke sign-up for nine days.

## Adding a function

1. Create `lambdas/<name>/` with one handler module and its tests.
2. Add the function infrastructure in the owning module — placeholder zip plus `ignore_changes`.
3. Add a `{ name: <name> }` row to the `deploy-lambdas.yml` matrix.
4. Extend the deploy role for any new actions — [`../../infra/info/deploy-role-iam.md`](../../infra/info/deploy-role-iam.md).
5. Add a row to [`INDEX.md`](INDEX.md).

**The first `deploy-infra.yml` apply must precede `deploy-lambdas.yml`** — the function and the
artifacts bucket have to exist before code can be pushed into them.

## Deploy-time traps

- **`Deploy Infrastructure` and `Deploy Lambdas` run in parallel on the same push.** A change that
  rewrites a function's Terraform **env block** while CI is calling `UpdateFunctionConfiguration` to
  attach its layers fails with `ResourceConflictException: An update is in progress for resource:
  <arn>`. Nothing is wrong with the code — re-running the failed job after the apply settles
  succeeds. It bites any change touching Lambda **env** and Lambda **code** in one push; a real fix,
  if one is ever needed, is a `needs:` edge or a retry.
- **A `rate()` EventBridge rule fires on creation**, so a new scheduled function's first invocation
  can hit the placeholder zip before `Deploy Lambdas` lands. The async retry fixes it — **a red first
  invocation is expected, not a defect.**
- **Every variable a domain layer's `config` requires must be common to all of that plane's verbs.**
  The layer's config runs on any import chain, so a verb missing one fails on whichever branch reads
  it — at cold start, in production, with a green suite behind it.

## Related

- [`INDEX.md`](INDEX.md) — every function, grouped by control plane
- [`shared-layer.md`](shared-layer.md) — what `cpcommon` holds and why
- [`../../infra/info/control-plane-shape.md`](../../infra/info/control-plane-shape.md) — the Terraform side of the same machine
- [`best-practices/lambdas/lambdas.md`](best-practices/lambdas/lambdas.md) — the rules a handler follows
