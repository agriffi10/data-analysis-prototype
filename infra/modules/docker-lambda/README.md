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

**Both sides wait.** `Deploy Lambdas` waits for the tag before pointing a function
(`.github/scripts/point-lambda.sh`), and `Deploy Infrastructure`'s apply now polls for it before
`tofu apply` — because `deploy-lambda-image.yml` carries no `paths:` filter, so it fires on the same
push as an apply and the two race. The apply-side wait **fails on a `workflow_dispatch` too**, which
is deliberate: that path exists for a dropped push event, and a dropped push drops the image build
as well, so continuing would fail `CreateFunction` with functions already destroyed. The recovery
needs no new input — dispatch `Deploy Lambda image` with an empty tag, then dispatch
`Deploy Infrastructure`. Ordering note:
[`lambdas/info/deployment.md`](../../../lambdas/info/deployment.md).

**The registry acquires a policy Terraform does not declare.** AWS's own guidance is that a
same-account function needs `ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` allowed on either
side, and Lambda adds the repository policy itself at `CreateFunction` when the caller holds
`ecr:GetRepositoryPolicy` and `ecr:SetRepositoryPolicy` — which the deploy role does. So nothing here
declares an `aws_ecr_repository_policy`, and a `LambdaECRImageRetrievalPolicy` appearing on the
registry is that, not drift.

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

## Four callers cannot depend on their own execution policy

A caller normally lists its execution policy in the module call's `depends_on`, so the policy
settles before the function is created. **Four cannot:** `api`, `auth` (twice) and `observability`
render that policy from the function's own log-group ARN, and the group now lives in here — so
`module.x` → `depends_on aws_iam_role_policy.x` → `module.x.log_group_arn` is a cycle, reproduced in
a scratch config before it was worked around. Those four drop the policy from `depends_on` and keep
everything else.

What that costs, stated rather than left to be derived: **on the cutover apply, nothing.** Those log
groups are *moved*, not replaced, so their ARNs are unchanged and the four policies are no-ops. The
window is a **from-scratch** apply only, and of the four only `observability`'s sweep can be invoked
in it (`rate(10 minutes)`; the two auth triggers need a real sign-up and `api` needs real traffic).
Its worst case is one async invocation that cannot write logs, retried automatically.

Rejected: constructing the log-group ARN at the call site, which adds an interpolated ARN and, for
`api`, a variable and a root wiring site. Also rejected: a second inline policy per site holding only
the log statements — it preserves the ordering, but four more IAM resources on the Checkov surface is
a poor trade for a window that closes itself.

## The log group belongs to the module

A function and its log group cannot be declared in different places and disagree. Declaring it also
keeps `CKV_AWS_66` able to see it — checkov cannot evaluate a log group that Lambda creates
implicitly on first invoke, and the implicit one is created at **infinite** retention.

## Related

- [`../lambda-image/README.md`](../lambda-image/README.md) — the registry this module's functions pull from
- [`../../info/control-plane-shape.md`](../../info/control-plane-shape.md) — the Terraform shape every plane shares
- [`../../../lambdas/info/deployment.md`](../../../lambdas/info/deployment.md) — the code/infra split and its deploy-time traps
