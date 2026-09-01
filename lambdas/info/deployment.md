# How a Lambda gets deployed

Lambda **code** and Lambda **infrastructure** are deliberately separated, and `tofu apply` never
touches code. This page is the split, and the traps that only appear at deploy time. What each
function *is* lives in [`INDEX.md`](INDEX.md); how a plane works lives in [`planes/`](planes/).

## The split

| Owner | Owns |
|---|---|
| The repo | `lambdas/<function-name>/<module>.py` and its tests, plus a shared `lambdas/requirements.txt` |
| Terraform | the function resource, its execution role, its log group and its trigger wiring — bootstrapped with an inline `archive_file` placeholder and `lifecycle { ignore_changes = [filename, source_code_hash, layers] }` |
| GitHub Actions | the Python code and **every layer attachment** — `deploy-lambdas.yml` reads the function table, builds each package, uploads it to the artifacts bucket at `<name>/<git-sha>.zip`, and runs `update-function-code --publish` |

**Use underscores in the `.py` filename** (`pre_signup.py`, handler `pre_signup.handler`) — a
hyphenated filename cannot be imported as a module, and the directory name is hyphenated.

**IAM trust and permission policies are `.tftpl` templates** under the owning module's `policies/`,
rendered with `templatefile()`. No inline `jsonencode` IAM policies anywhere.

**`ignore_changes` must name `layers`.** Without it, an apply landing after a deploy strips the layer
back off and the function fails at its next cold start on an import that had been working.

## Layers deploy like code

CI builds and publishes `cpcommon`, each plane's `*-common` layer and polars, then attaches them.
Terraform never manages a layer version, so nothing in the infrastructure knows which layers a
function needs. The import-join in `lambdas/test_deploy_matrix.py` (below) is the only thing standing
between a missing layer and a `ModuleNotFoundError` at every cold start — the failure that broke
sign-up for nine days.

## The two deploy tables

**The function table is data, not workflow YAML.** `.github/lambda-functions.json` holds one object
per function — its `name`, and the `layers` it needs by flag — and `.github/lambda-layers.json` holds
what each of those flags builds. `deploy-lambdas.yml` reads both; its `strategy.matrix` is over
**shards**, computed from what the plan found, and has not been a list of functions since a matrix
could no longer express "these twelve in one job".

`lambdas/test_deploy_matrix.py` parses that JSON and joins it against what each function actually
**imports**, so a function omitted from the table, or shipped without a layer it imports, fails CI
rather than failing at a cold start in production.

## Adding a function

1. Create `lambdas/<name>/` with one handler module and its tests.
2. Add the function infrastructure in the owning module — placeholder zip plus `ignore_changes`.
3. Add a `{"name": "<name>", "layers": ["cpcommon", …]}` row to `.github/lambda-functions.json`.
   Every flag it names must already exist in `.github/lambda-layers.json`, and **the `layers` array
   is stored in attach order** — a test asserts that, because layers land on `/opt` in order and a
   later one shadows an earlier one's modules. A **genuinely new layer** is a row in
   `.github/lambda-layers.json` **and** a new flag in `deploy-lambda.sh`'s literal attach-order loop,
   in the same position: a test asserts the two orders are one list. All of these fail in CI rather
   than at a cold start.
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

## There is a Dockerfile here, and nothing deploys from it yet

`lambdas/Dockerfile` builds **one container image for the whole fleet** — dependencies installed
once, shared code copied once, every function running the same image with a different command. It
is built and proved on every pull request that touches `lambdas/`, pushed to ECR by commit sha on
every push to `main`, and **run by no function**. Everything above this section is still how a
Lambda gets deployed.

What it is for: the split described above means what a function can import is decided at deploy
time by a join between two tables, and is observable nowhere else. The image makes it a property of
an artefact — `.github/scripts/lambda-image-matrix.sh` imports every function's handler module
inside the built image, through the real runtime bootstrap, which is the check that would have
caught the nine-day sign-up outage.

Two things to know before changing anything under `lambdas/`:

- **A new top-level module in a function directory shares one task root with all 85 others.** Two
  directories cannot contribute the same path, and no top-level name there may match a name on
  `/opt/python` — the runtime searches the task root first, so a duplicate does not collide, it
  wins. Both are asserted against the built image.
- **The image's layout is one module**, `lambdas/docker/assemble.py`, which the build runs and the
  layout tests import. Change the layout there, not in the Dockerfile.

Full reasoning: [`../../docs/decisions/infrastructure.md`](../../docs/decisions/infrastructure.md)
→ *One image for the whole Lambda fleet*.

## Related

- [`INDEX.md`](INDEX.md) — every function, grouped by control plane
- [`shared-layer.md`](shared-layer.md) — what `cpcommon` holds and why
- [`../../infra/info/control-plane-shape.md`](../../infra/info/control-plane-shape.md) — the Terraform side of the same machine
- [`best-practices/lambdas/lambdas.md`](best-practices/lambdas/lambdas.md) — the rules a handler follows
