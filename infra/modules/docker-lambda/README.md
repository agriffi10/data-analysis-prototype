# `docker-lambda` — one container-packaged function

Every Lambda in this repository is a call to this module. They all run the **same image** — the one
`lambda-image` holds and `lambdas/Dockerfile` builds — and differ only by the `command` that names
their handler. What a function can import stopped being a deploy-time join between two JSON tables
and became a property of an artefact you can pull and run.

The module takes what actually differs between functions (name, command, environment, timeout,
memory, role, VPC) and gives back the function's **name, ARN and invoke ARN**, so a module that
grants, triggers or references a function consumes an output instead of rebuilding a name from a
string template.

## `image_uri` is ignored, so CI has to point every function

`lifecycle { ignore_changes = [image_uri] }` is the load-bearing line, and it cuts both ways.

Terraform owns the function; CI owns the code. Without the ignore, every apply would drag the whole
fleet back to whatever tag Terraform was last handed. **With** it, Terraform will never move a
function forward either — so `Deploy Lambdas` must call `update-function-code --image-uri` on every
function on every deploy. `image_uri` is *not* ForceNew, which is what makes that a live update
rather than a replacement.

The failure this arrangement invites has a shape worth knowing before changing anything here: a
pipeline that builds an image, pushes it, and never points anything at it leaves all 86 functions
on the previous image, **each of them still working**. Nothing goes red. That is the same trap the
SPA's ECS service hit, where a pipeline that only registered a task-definition revision left a
`CannotPullContainerError` indistinguishable from the endpoint failure the platform was tested for.
The mitigation is the same: CI counts what it pointed and fails loudly on a shortfall.

## The tag must exist at creation, and only at creation

A container function cannot be created pointing at a tag the registry does not hold. After
creation the value is ignored, so the constraint is real exactly once per function — but "once" is
the cutover, when it applies to all 86 at the same moment.

**That wait does not exist yet.** `Deploy Lambdas` waits for the tag before pointing a function
(`.github/scripts/point-lambda.sh`), but `Deploy Infrastructure` has no such step — and
`deploy-lambda-image.yml` carries no `paths:` filter, so it fires on the same push as an apply and
the two race. Nothing depends on that today, because no function is created from an image. The
apply-side wait, and the ordering note in
[`lambdas/info/deployment.md`](../../../lambdas/info/deployment.md), land with the cutover — the
change that makes the race matter.

## What is deliberately not declared

- **`layers`.** A container function has none; its imports are the image's. A stale
  `ignore_changes = [layers]` left behind would be a fossil that reads as meaningful.
- **`handler` and `runtime`.** Both are Zip-only, enforced at apply rather than by the schema.
- **`filename` / `source_code_hash`.** They conflict with `image_uri` outright, and there is no
  placeholder zip any more — the image is valid from the first apply, so the bootstrap artefact
  that every function needed under the zip pipeline is gone.

## What is declared even though AWS would default it

`memory_mb`, `architectures` and `reserved_concurrency` are always set, and that is not
belt-and-braces. Two reasons, and the second is the one that bites:

1. An unset memory tier is **invisible in the plan** and surfaces only as an OOM in production.
   Several planes previously left it at the 128 MB default without saying so.
2. An attribute the configuration does not set comes back **unknown** in a *replacement* plan —
   present-and-refreshed in a no-op plan, absent in a replacement. The cutover compares the two,
   so a field left to the provider's default reads as "no value" on one side and a number on the
   other, and the natural repair (skip what the new plan lacks) makes the comparison vacuous for
   precisely the fields most likely to have moved.

`architectures` also has to agree with the image, which is built `--platform linux/amd64`: an
arm64 function fails at start with a manifest error that reads nothing like the mismatch it is.

## The log group belongs to the module

A function and its log group cannot be declared in different places and disagree. Declaring it also
keeps `CKV_AWS_66` able to see it — checkov cannot evaluate a log group that Lambda creates
implicitly on first invoke, and the implicit one is created at **infinite** retention.

## Related

- [`../lambda-image/README.md`](../lambda-image/README.md) — the registry this module's functions pull from
- [`../../info/control-plane-shape.md`](../../info/control-plane-shape.md) — the Terraform shape every plane shares
- [`../../../lambdas/info/deployment.md`](../../../lambdas/info/deployment.md) — the code/infra split and its deploy-time traps
