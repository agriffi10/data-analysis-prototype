---
type: Decision
title: "A module that waits on another reads no data source, because the wait defers the read"
description: "**A module-level `depends_on` defers every data source in that module, so none sits behind one** — a deferred document is `(known after apply)`, which no plan-time scan reads, and a deferred `for_each` is a hard error. Keep the edge; render documents with `templatefile()` and pass other reads from the root. A sweep refuses the shape. **A NEW IAM policy must be KNOWN at plan time, or the plan gate refuses it**, because Checkov passes a `(known after apply)` document unread; an updated one is only named in a warning. That decides a plane's PR grouping: an ARN a policy's `Resource` names is built from the resource's name in a local, and a `Principal` must exist when IAM writes the policy, so a role the same PR creates needs an explicit dependency on it or lands a PR earlier, as does a resource whose ARN AWS generates (a KMS key, a Cognito pool). Reasoning: `docs/decisions/gates-and-tests/a-scanners-configuration-is-its-command-line-and-what-it-discovers-is.md`, *What the scanner cannot read is refused too*."
---

Besides an argument unknown at plan, OpenTofu defers a data source to apply when it carries a
`depends_on`, its own or one inherited from a module call at any depth, and anything the edge names
has a change pending: a create or an update (a deposed object's destroy was measured not to). Then
everything built from it is `(known after apply)`. Nearly
every module the root calls waits on `module.base`, so every pull request changing a deploy grant
deferred whatever those modules read. Of the 111 readable pull-request plans run from 2026-08-26
through run 35001183572 on 2026-09-15, 30, across 23 pull requests, showed the observability sweep's trust policy and both
its role policies as `jsonencode(...) -> (known after apply)` on an in-place update, with their
content unchanged: the three documents were `aws_iam_policy_document` data sources, the one module
in the tree still building IAM that way. `module.data` had the same shape. An `aws_caller_identity`
read inside it fed the user-space bucket policy, and the isolation policy itself went unknown in
the same 30 runs and no others.

The register used to call this benign for a policy document, since it resolves to the identical
value at apply. It stopped being benign when the rendered plan became what the IAM gate reads. On
a deferred run Checkov scored the sweep's policy with 2 of the 9 checks it runs on the known
document, both passing, and the bucket policy with 1 of its 2, so a deferred document is
indistinguishable from a changed one nobody scanned.

**The edges stay and the reads go.** `depends_on = [module.base]` is what writes a deploy grant
before the apply that first uses it, and the self-grant traps in `infra/info/deploy-role-iam.md`
are what an apply without it risks. So the observability documents are `.tftpl` files rendered by
`templatefile()`, which the plan computes whenever its inputs are known, and `module.data` takes the
account ID from the root. `lambdas/test_depends_on_defers_no_data_source.py` walks every module
call carrying a `depends_on`, root or nested, through every module it reaches, and refuses a data
block there or a data block carrying its own `depends_on`. Planted once each, a data source in the
observability module and one in `docker-lambda` reddened it by name; a planted tree asserts every
deferring shape named and three reads nothing defers left silent.

**Do NOT drop a module's `depends_on` to make its reads plan-time**, and do not reach for
`ignore_changes` either: nothing drifts, so there is nothing to ignore.

A deferred `for_each` is a hard error. A new IAM policy must be known at plan time, or the plan gate refuses it, because Checkov passes a `(known after apply)` document unread; an updated one is only named in a warning. That decides a plane's PR grouping: an ARN a policy's `Resource` names is built from the resource's name in a local, and a `Principal` must exist when IAM writes the policy, so a role the same PR creates needs an explicit dependency on it or lands a PR earlier, as does a resource whose ARN AWS generates (a KMS key, a Cognito pool). Reasoning: `docs/decisions/gates-and-tests/a-scanners-configuration-is-its-command-line-and-what-it-discovers-is.md`, *What the scanner cannot read is refused too*.

## History

### 2026-09-15

- **Settled:** entered the register.
