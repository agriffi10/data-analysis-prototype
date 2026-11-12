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

The cost is real and was paid deliberately: the whole fleet on every `lambdas/**` push, against a
median of four functions before. It is paid in ONE job that points eight functions at a time
(`.github/scripts/deploy-fleet.sh`), because a function deployed alone is almost all waiting on Lambda and
GitHub bills every job's wall clock — six shard jobs walking the fleet in sequence billed ~45 minutes
a run, and once held all six to a 30-minute timeout while idle functions each failed a waiter. Every
function gets its attempt however many fail, and the job's 20-minute timeout is the cost bound —
there is no early stop, because no rule for which failures count told a fleet-wide failure from a
local one reliably. That is the price of the guarantee, and the reconciliation is what makes it
worth paying — the `pointed` job reconciles by NAME, because a count tells you a number
is wrong and the names tell you which functions are running last week's image. It does so on **two**
axes, and they read different things: what this commit's Terraform sources declare against what the
deploy recorded pointing (a function planned and never pointed), and those same sources against
Terraform's applied state (a function deployed that this commit does not declare, running an image
nobody pointed). The *Which functions exist* section below says why the two readers are different.

## The layer machinery is gone, and what is left is in AWS rather than in the repo

There is no layer table, no layer build script and no attach loop. What a function can import is a
property of the **image**, which `.github/scripts/lambda-image-matrix.sh` proves by importing every
handler module inside it, through the real runtime bootstrap.

**What decides the shared surface now is the tree.** `lambdas/docker/assemble.py` reads
`lambdas/*-common/` and copies what each directory holds onto `/opt/python` — a package is a
subdirectory with an `__init__.py`, a flat module is a top-level `.py` that is not a suite, a
`conftest.py`, a `fakes.py` or an `__init__.py`. There is no list a module can be missing from,
which was the whole failure the table made possible: a module on disk, absent from the list, never
shipped, and raised `ModuleNotFoundError` at the next cold start behind a green suite and a green
deploy. That cost nine days once.

**A directory under `lambdas/` is therefore one of three things, and never by default.** It is a
function (it holds a module defining a top-level `handler`), it is shared code (its name ends
`-common`), or it is named in `assemble.NOT_SHARED` with the reason it is neither.
`test_image_layout.py` fails on a directory that is none of the three, so a new one has to be
classified before it can ship — shared code is deliberately **not** the default bucket, because a
default makes that partition total by construction and its guard unable to fail.

**Nothing about layers outlives this any more.** The 923 versions the old pipeline published across
ten layers were destroyed in CI — that is AWS state rather than repository state, and the deploy role
held `DeleteLayerVersion` where a local identity did not — and the grants that authorised it came off
in the apply after. The ordering was forced: a grant removed first would have stranded the versions
with no identity able to reach them. A test now fails on a layer ARN, a layer IAM action, a layer API
call, a `*_layer_name` declaration or a project-and-environment-qualified layer name reappearing in
a workflow, a script or a `.tf` file.

Two things about that destroy are worth carrying. The layer names could not come from Terraform,
which declared eight of the ten as layer-name locals. `control-plane-common` appeared only as a
wildcard ARN pattern in a deploy policy, and `table-builder-common` nowhere in Terraform at all — so
neither full name was derivable from it. And an absent layer and a just-emptied one are the
same API answer (`{"LayerVersions": []}`, not an exception), so a sweep of the wrong names would have
reported a completed destroy of nothing; the run had to carry the count its own report found.

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

## Which functions exist

**Terraform, and nothing else.** `lambdas/fleet.py` derives the fleet's names from the
`docker-lambda` module calls in `infra/modules/`, and the hand-maintained table that used to hold
the same list is deleted (the post-cutover name set beside the frozen capture is a fail-closed
acknowledgement of growth, not a membership source) — a second declaration of one fact can only ever drift, and the drift is
invisible until something deploys against the wrong copy.

Two readers, for two different questions. `deploy-lambdas.yml` deploys **this commit's**
sources, because a `tofu output` is last-applied state and the two deploy workflows fire on the same
push with no ordering — so on the push that adds a function the output does not have it yet, and the
new function would never be pointed. The `pointed` job reads the **applied** output
(`lambda_function_names`) afterwards and reconciles: a function this commit declares but Terraform
has not created is reported and benign, while a deployed function this commit does not declare
fails, because nothing pointed it at this run's image and nothing else would say so.

`deploy-infra.yml`'s plan guard reads the same derivation, which makes its check "the static parser
agrees with Terraform's own evaluator" rather than a comparison of a list with itself.

## Adding a function

1. Create `lambdas/<name>/` with one handler module and its tests.
2. Add a `docker-lambda` module call in the owning module's `lambda.tf`, supplying its
   `command = ["<module>.<handler>"]`, its timeout and its memory.
3. Nothing to register — step 2 IS the registration, and CI derives the fleet from it — but
   **name it in `ADDED_SINCE_THE_CUTOVER`** in `lambdas/test_lambda_plan_guard.py`: the frozen
   pre-cutover capture is a floor under the fleet, and an addition it does not name fails by name.
   **A new MODULE** additionally needs a `function_names` output and a line in `infra/outputs.tf`'s
   `lambda_deployed_names`; `test_fleet_derivation.py` fails by name if either is missing.
   **A new PLANE also needs a probe:** grant the deploy role `lambda:InvokeFunction` on one of its
   functions and add that name to `.github/lambda-probes.json`. Without the grant the plane is
   simply unprobed and nothing says so — `test_cold_start_probe.py` compares the probe table against
   the grants, so it cannot see a plane that has neither.
4. Extend the deploy role for any new actions — [`../../infra/info/deploy-role-iam.md`](../../infra/info/deploy-role-iam.md).
5. Add a row to [`INDEX.md`](INDEX.md).

**Changing an EXISTING function's timeout, memory, role or other parity field** fails the same plan
guard, and only in CI — the capture is frozen, so every captured field is pinned to what the cutover
left. Declare the move in `DELIBERATE_CHANGES` in `.github/scripts/lambda_plan_guard.py`, with the
new value: the declaration is a new pin, not a waiver. `test_lambda_plan_guard.py` ties a declared
`timeout` to the function's row in its module's `locals.tf`; it cannot resolve any other field, or a
function with no such row, and fails on one rather than passing it — extend the test when you need
one.

**The first `deploy-infra.yml` apply must precede `deploy-lambdas.yml`** — the function has to exist
before code can be pointed at it.

## Deploy-time traps

- **`Deploy Infrastructure` and `Deploy Lambdas` run in parallel on the same push, and that window is
  UNCHANGED by the move to containers.** A change that rewrites a function's Terraform **env block**
  while CI is calling `UpdateFunctionCode` on it fails with `ResourceConflictException: An update is
  in progress for resource: <arn>`. Nothing is wrong with the code — re-running the failed job after
  the apply settles succeeds. A real fix, if one is ever needed, is a `needs:` edge or a retry. The
  rest of the fleet still lands: `deploy-fleet.sh` gives every function its attempt however many
  fail.
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
`Deploy Lambdas` by `workflow_dispatch` with `image_tag` set to that sha. Anything that is not a
bare tag is refused before it is looked up or printed (`.github/scripts/check-image-tag.sh`), and
the tag is checked against the registry once, up front, because `point-lambda.sh` waits five
minutes per function for one that never arrives.

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
- [`../../infra/modules/control-plane/README.md`](../../infra/modules/control-plane/README.md) — the Terraform side of the same machine
- [`best-practices/lambdas/lambdas.md`](best-practices/lambdas/lambdas.md) — the rules a handler follows
