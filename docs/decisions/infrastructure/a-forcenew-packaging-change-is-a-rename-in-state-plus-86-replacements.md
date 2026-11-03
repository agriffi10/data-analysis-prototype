---
type: Decision
title: "A ForceNew packaging change is a rename in state plus 86 replacements, and the permissions are what nobody looks at (SPEC-213)"
description: "**`package_type` is FORCE-NEW: the cutover replaced all 86**, ordered only by **172 `moved` blocks** — without one, Terraform plans a create and a destroy with **no edge between them**, and it tolerates a `moved` whose `from` is not in state **silently**. So **reverting is not a rollback**; pointing at a previous sha's image is, and `image_uri` is *not* ForceNew, which is what lets CI move the fleet at all. **Every `aws_lambda_permission` binds to `function_arn`, never a name** — a name is config-known, plans **no diff**, and lets the replacement take the resource policy: an API-wide 500 behind a green apply and a green probe. Six planes' constructed ARN lists moved for the same reason. **CI points EVERY function every run** (\"which changed\" has no answer with one artefact; an un-pointed one runs an older image *working perfectly*), reconciles by NAME, then proves a sample STARTED — a check that took three designs, none of which an emulator can settle, because it diverges from Lambda on exactly the init-failure path."
---

`package_type` is ForceNew. Moving 86 functions from zip to one container image therefore destroys
and recreates every one of them, and the whole spec is about making that ordered and observable
rather than about the packaging itself.

**172 `moved` blocks are what make it ordered.** Every function and every log group changed address
(`aws_lambda_function.functions["x"]` → `module.functions["x"].aws_lambda_function.this`). Without a
block, Terraform plans a create at the new address and a destroy at the old one **with no dependency
edge between them** — for a function that is `CreateFunction` racing `DeleteFunction` on one name,
and for a log group it is `ResourceAlreadyExistsException` or lost logs. `moved` takes static
addresses only, so there is one per instance.

**Terraform tolerates a `moved` block whose `from` is not in state.** No error, no warning: the block
moves nothing and the resource falls back to exactly that unordered pair, with a plan byte-identical
to one carrying no block at all. Measured on real state. A guard therefore checks the `from` half as
hard as the `to` half, and both against the keys each call expands to — and anchors its expected
total to a **frozen** fixture, because a tree-derived count passes on a shrink that deletes a
function and its block together.

**THE OUTAGE THIS WOULD OTHERWISE HAVE SHIPPED.** All 11 `aws_lambda_permission` resources bound to
`.function_name` — a config-known literal, identical either side of a replacement. Terraform plans
**no diff**, so the permission is never recreated, while `DeleteFunction` takes the function's
resource policy with it: the API 500s on every request, sign-up breaks, every plane's `TIMED_OUT`
notifier goes silent — behind a green apply, a green deploy and a green cold-start probe, because a
probe invokes through IAM and never consults the resource policy. **Bind to the module's
`function_arn`**: the ARN is computed, therefore unknown while the function is replaced, and
`function_name` is ForceNew on the permission. An event-source mapping's is not, so it updates in
place — and that difference is worth knowing before predicting a plan. The same reasoning retires
six planes' constructed-ARN locals: a constructed ARN stays *known* across a replacement, which is
precisely what makes the grant it feeds survive undiffed.

**A ForceNew replacement is not revertible.** Reverting the commit deletes the `moved` blocks and
re-races 86 creates against live names, and the reverted configuration brings the placeholder zips
back. The rollback that exists is the **code**: point the fleet at a previous sha's image, which is a
`workflow_dispatch` input and no code change. Exercised once, both directions, with each function's
`Code.ImageUri` read back.

**One image means narrowing a deploy is a category error.** "Which functions changed" has no answer
when there is one artefact, so CI points **every** function on every run and reconciles by name. A
function left un-pointed runs an older image and reports a stale build stamp *while working
perfectly* — which is the failure this whole arc exists to prevent, and the reason the cost (the whole
fleet where four functions used to deploy) is worth paying.

**Proving a deployed function STARTED took three designs, and the first two were measured wrong
rather than argued wrong.** `START RequestId` is written *before* init and regardless of its outcome,
and is truncated away by `--log-type Tail`'s last-4-KB window. An `errorType` namespace rule
(`Runtime.*`) passes an exception raised at import, which reports its own class — the shape a fleet
with module-level initialisation most invites. A bare `REPORT RequestId` is present on an init
failure in production, whatever the runtime interface emulator shows; **the emulator diverges on
exactly that path**, answering 502 with no `X-Amz-Function-Error` where production answers 200 with
one, so it cannot be trusted about it. What survives is `Status: error` — a field Lambda writes only
when a phase failed, so it cannot redden a healthy deploy — plus an anchored `^REPORT RequestId` and
the `Runtime.` namespace. The general lesson is the one about fixtures: an earlier corpus paired a
production response envelope with an emulator log tail, a combination neither world produces, and
that inconsistency hid the defect through two review rounds.

**A probe's population is derived from the IAM, never hand-written.** The deploy role's own
`lambda:InvokeFunction` grants are the population, compared by set equality in **both** directions —
a probe without a grant is a loud `AccessDenied`, a grant without a probe is invisible. What that
cannot see, and is recorded rather than implied, is a plane shipping with no grant at all.

`image_uri` is not ForceNew, which is what lets CI move the fleet at all.

## History

### 2026-08-28

- **Settled:** SPEC-213.
