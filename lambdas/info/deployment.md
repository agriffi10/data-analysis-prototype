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
| GitHub Actions | the image, and which image each function runs — `deploy-lambda-image.yml` builds and pushes it tagged by commit sha, and `deploy-lambdas.yml` runs `update-function-code --image-uri` on **every** function, then proves a sample of them starts |

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

## Every function, every run — and why narrowing is now a category error

`Deploy Lambdas` points the **whole fleet** on every run. It used to deploy only what a diff
touched, which was right while each function carried its own zip and its own layer ARNs. With one
image for all 86, "which functions changed" has no answer: a function left un-pointed runs an older
image and reports a stale `BUILD_VERSION` **while working perfectly**, which is the failure this
whole arc is written around.

The cost is real and was paid deliberately: six shard jobs of ~15 functions on every `lambdas/**`
push, against a median of four before. That is the price of the guarantee, and the reconciliation is
what makes it worth paying — the `pointed` job compares the functions actually deployed against the
deploy table by NAME, because a count tells you a number is wrong and the names tell you which
functions are running last week's image.

## The layer machinery is still here, and nothing reaches it

`.github/lambda-layers.json` still describes the layers and `build-layer.sh` and `deploy-lambda.sh`
still know how to build and attach them. **Nothing calls any of it.** `point-lambda.sh`'s zip branch
is gone and a non-`Image` packaging is now refused by name, so there is no path from a deploy to a
layer — and attaching a layer to a container function is an error anyway.

It survives until SPEC-214, which deletes it against a coverage proof rather than on the strength of
being unreachable. What a function can import is a property of the **image**, which
`.github/scripts/lambda-image-matrix.sh` proves by importing every handler module inside it, through
the real runtime bootstrap.

## The deployed artefact is proved to start

An image that imports cleanly is not a function that starts. After pointing, `Deploy Lambdas`
invokes one function per plane and every standalone — exactly the set the deploy role holds
`lambda:InvokeFunction` for — and requires each invocation's log to carry **`REPORT RequestId`**.

Three designs were tried, and each looked right until it was driven:

| design | why it is wrong |
|---|---|
| `START RequestId` present | Written **before** init and regardless of its outcome. Also the first line, so `--log-type Tail`'s last-4-KB window truncates it away on a chatty function. Wrong in both directions. |
| `errorType` begins `Runtime.` | An exception raised at import reports its own class — `RuntimeError` — with no prefix. That is the shape this fleet most invites, since `observability.init` runs at module scope. |
| `REPORT RequestId` present | True under the runtime interface emulator, false in production: AWS's documented output for a `Runtime.ExitError` init failure carries `START`, `END` **and** `REPORT`. |

What the probe actually fails on is what is unambiguous in both worlds: an `errorType` under
`Runtime.`, a `Status: error` in the log — a field Lambda writes only when a phase failed, so it
cannot redden a healthy deploy — or no `^REPORT RequestId` line at all. `INIT_REPORT` is
deliberately **not** a signal: some runtimes emit it on every cold start, and failing on it would
turn every deploy red. A handler that ran and raised is a **pass** — the subject is the cold start.

The residual, and the one command that settles it, is in [`../../docs/testing/owed.md`](../../docs/testing/owed.md).

`lambdas/test_cold_start_probe.py` derives the probe's population from the deploy role's grants and
fails on any difference **in both directions**: a probe without a grant fails loudly the first time
it runs, but a grant without a probe is invisible. `control-plane-dlq-drain` is the one deliberate
exemption — invoking it consumes DLQ messages — and it is recorded in `docs/testing/owed.md`.

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
   **A new PLANE also needs a probe:** grant the deploy role `lambda:InvokeFunction` on one of its
   functions and add that name to `.github/lambda-probes.json`. Without the grant the plane is
   simply unprobed and nothing says so — `test_cold_start_probe.py` compares the probe table against
   the grants, so it cannot see a plane that has neither.
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
registry under the lifecycle bound `lambda-image` computes. No code change is involved: run
`Deploy Lambdas` by `workflow_dispatch` with `image_tag` set to that sha. The tag is checked against
the registry once, up front, because `point-lambda.sh` waits five minutes per function for one that
never arrives.

**Confirm it by reading `Code.ImageUri` back, never by "main went green".** The `deploy-lambdas`
concurrency group holds one pending run, so a merge landing while the forward dispatch is queued can
evict it — leaving the fleet on the rollback image, serving perfectly, with main green.

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
brings the placeholder zips back** — which is where the path stops being a recovery at all: nothing
can deploy a zip function any more. `point-lambda.sh` refuses a non-`Image` packaging by name and
the layer job is gone, so 86 functions would sit on placeholder code raising *"code not yet deployed
by CI"* with no pipeline able to fix them. Recovering from that means restoring the zip pipeline
first, out of git history.

**So do not roll the infrastructure back. Roll the CODE back** — point the fleet at a previous sha's
image, above — which is the recovery this arc actually built and exercised. The infra revert is
documented here so that nobody discovers its shape during an incident, not because it is the
procedure to reach for.

## Related

- [`INDEX.md`](INDEX.md) — every function, grouped by control plane
- [`shared-layer.md`](shared-layer.md) — what `cpcommon` holds and why
- [`../../infra/modules/docker-lambda/README.md`](../../infra/modules/docker-lambda/README.md) — the module every function is a call to
- [`../../infra/info/control-plane-shape.md`](../../infra/info/control-plane-shape.md) — the Terraform side of the same machine
- [`best-practices/lambdas/lambdas.md`](best-practices/lambdas/lambdas.md) — the rules a handler follows
