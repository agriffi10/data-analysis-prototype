# How a Lambda gets deployed

Lambda **code** and Lambda **infrastructure** are deliberately separated, and `tofu apply` never
touches code. This page is the split, and the traps that only appear at deploy time. What each
function *is* lives in [`INDEX.md`](INDEX.md); how a plane works lives in [`planes/`](planes/).

## The split

Every function is **container-packaged**: one image for the whole fleet, and a function differs from
its neighbours only by the `command` naming its handler.

| Owner | Owns |
|---|---|
| The repo | `lambdas/<function-name>/<module>.py` and its tests, plus a shared `lambdas/requirements.txt` |
| Terraform | the function resource, its execution role, its log group and its trigger wiring — every function a call to [`infra/modules/docker-lambda`](../../infra/modules/docker-lambda/README.md), with `lifecycle { ignore_changes = [image_uri] }` |
| GitHub Actions | the image, and which image each function runs — `deploy-lambda-image.yml` builds and pushes it tagged by commit sha, and `deploy-lambdas.yml` runs `update-function-code --image-uri` |

**Use underscores in the `.py` filename** (`pre_signup.py`, command `pre_signup.handler`) — a
hyphenated filename cannot be imported as a module, and the directory name is hyphenated.

**IAM trust and permission policies are `.tftpl` templates** under the owning module's `policies/`,
rendered with `templatefile()`. No inline `jsonencode` IAM policies anywhere.

**`ignore_changes` names `image_uri`, and it cuts both ways.** Without it every apply would drag the
whole fleet back to whatever tag Terraform was last handed. **With** it, Terraform will never move a
function forward either — so CI must call `update-function-code` on every function on every deploy.
A pipeline that builds an image, pushes it, and points nothing at it leaves the fleet on the previous
image, **each function still working**, and nothing goes red. `deploy-lambdas.yml`'s `pointed` job
reconciles names, not a count, for exactly that reason.

## The image must exist before a function is created

`image_uri` is ignored *after* creation, but it has to be valid **at** creation — a container
function cannot be created pointing at a tag the registry does not hold. That makes the constraint
real exactly once per function, and "once" was the cutover, when it applied to all 86 at the same
moment.

`deploy-lambda-image.yml` carries no `paths:` filter, so it fires on the **same push** as
`Deploy Infrastructure` and the two race. `Deploy Infrastructure`'s apply therefore polls for this
commit's tag before `tofu apply`, and **fails if it never arrives — on a `workflow_dispatch` too**.
That is deliberate: the dispatch path exists for a dropped push event, which drops the image build
as well, so main's tip has no image and continuing would fail `CreateFunction` with functions
already destroyed. The recovery needs no extra input — dispatch `Deploy Lambda image` with an empty
tag, which builds this commit, then dispatch `Deploy Infrastructure`.

## The layer machinery is still here, and attaches nothing

`deploy-lambdas.yml` still has its `layers` job, `.github/lambda-layers.json` still describes the
layers, and `deploy-lambda.sh` still knows how to attach them. **None of it reaches a function.**
`point-lambda.sh` dispatches on the function's live `PackageType`, and every function is `Image`, so
the zip branch is never taken — and attaching a layer to a container function is an error anyway.

It survives on purpose, until SPEC-214: it is what makes a partly-failed apply recoverable rather
than wedged, because a fleet that is half zip and half image can still be deployed by a pipeline that
speaks both. Read the two tables as history for now; what a function can import is a property of the
**image**, which `.github/scripts/lambda-image-matrix.sh` proves by importing every handler module
inside it, through the real runtime bootstrap.

## The function table

`.github/lambda-functions.json` holds one object per function — its `name`, and the `layers` it used
to need by flag. `deploy-lambdas.yml` reads it; its `strategy.matrix` is over **shards**, computed
from what the plan found, and has not been a list of functions since a matrix could no longer express
"these twelve in one job".

The table is also the fleet's population: `deploy-infra.yml`'s plan guard holds it equal to the
functions Terraform actually declares, and the `pointed` job holds what CI deployed equal to what the
planner selected.

## Adding a function

1. Create `lambdas/<name>/` with one handler module and its tests.
2. Add a `docker-lambda` module call in the owning module's `lambda.tf`, supplying its
   `command = ["<module>.<handler>"]`, its timeout and its memory.
3. Add a `{"name": "<name>", …}` row to `.github/lambda-functions.json`.
4. Extend the deploy role for any new actions — [`../../infra/info/deploy-role-iam.md`](../../infra/info/deploy-role-iam.md).
5. Add a row to [`INDEX.md`](INDEX.md).

**The first `deploy-infra.yml` apply must precede `deploy-lambdas.yml`** — the function has to exist
before code can be pointed at it.

## Deploy-time traps

- **`Deploy Infrastructure` and `Deploy Lambdas` run in parallel on the same push, and that window is
  UNCHANGED by the move to containers.** A change that rewrites a function's Terraform **env block**
  while CI is calling `UpdateFunctionCode` on it fails with `ResourceConflictException: An update is
  in progress for resource: <arn>`. Nothing is wrong with the code — re-running the failed job after
  the apply settles succeeds. A real fix, if one is ever needed, is a `needs:` edge or a retry.
- **A `rate()` EventBridge rule fires on creation**, so a new scheduled function's first invocation
  can hit an image that is still being optimised. The async retry fixes it — **a red first invocation
  is expected, not a defect.**
- **Every variable the shared code requires must be common to all of a plane's verbs.** The shared
  config runs on any import chain, so a verb missing one fails on whichever branch reads it — at cold
  start, in production, with a green suite behind it.
- **A new top-level module in a function directory shares one task root with all 85 others.** Two
  directories cannot contribute the same path, and no top-level name there may match a name on
  `/opt/python` — the runtime searches the task root first, so a duplicate does not collide, it
  wins. Both are asserted against the built image.
- **The image's layout is one module**, `lambdas/docker/assemble.py`, which the build runs and the
  layout tests import. Change the layout there, not in the Dockerfile.

## Rolling back

Two different things, and only one of them is a revert.

**The code** rolls back by pointing the functions at a previous sha's image, which is still in the
registry under the lifecycle bound `lambda-image` computes. No code change is involved.

**The packaging does not.** The cutover moved every function and every log group to a new Terraform
address, and 172 `moved` blocks are what made that a rename in state rather than a create racing a
destroy. Reverting the cutover commit **deletes those blocks**, so Terraform would plan 86 creates at
the old addresses and 86 destroys at the new ones with no dependency edge between them — which for a
function is `CreateFunction` racing `DeleteFunction` on one name. An infra rollback is therefore a
revert **plus** hand-written reverse `moved` blocks: recover the originals with
`git show <cutover-sha>:infra/modules/<module>/moved.tf` and swap each block's `from` and `to`.

Two things about that path, both worth knowing before taking it. **Terraform tolerates a `moved`
block whose `from` is not in state** — no error, no warning — so a mistyped address is a block that
moves nothing, and the resource falls back to the create-beside-destroy the blocks exist to prevent.
The plan is byte-identical to one with no block at all; measured. And **the reverted configuration
brings the placeholder zips back**, so every function is recreated raising *"code not yet deployed by
CI"* until the next `Deploy Lambdas` run points and re-attaches. An infra rollback is therefore a
two-step recovery, not one.

## Related

- [`INDEX.md`](INDEX.md) — every function, grouped by control plane
- [`shared-layer.md`](shared-layer.md) — what `cpcommon` holds and why
- [`../../infra/modules/docker-lambda/README.md`](../../infra/modules/docker-lambda/README.md) — the module every function is a call to
- [`../../infra/info/control-plane-shape.md`](../../infra/info/control-plane-shape.md) — the Terraform side of the same machine
- [`best-practices/lambdas/lambdas.md`](best-practices/lambdas/lambdas.md) — the rules a handler follows
