# `lambda-image` — the Lambda container image's registry

One ECR repository, its lifecycle policy, and nothing else. The image that fills it, the behaviour
matrix that proves it and the pipeline that pushes it live outside this module; **no Lambda runs
from it yet**, and until the fleet is cut over this repository is a place CI puts an artifact
nobody starts.

## Why it is not the SPA's repository

The two have different lifecycles, and a shared repository would make one's expiry policy the
other's problem. The SPA rolls back in **deploys** — thirty images is a long way back when one
service pulls one image. The Lambda fleet rolls back in **days**, because the failure it rolls back
from is an import that only a rare function's cold start reveals, and that can take a day or more
to surface. Sharing one retention rule would either starve the SPA's history or inflate it.

Separate repositories also keep the grant readable: the deploy role's registry statements name two
ARN patterns, one per repository, and a reader can see which is which.

## The retention bound is computed

`lambdas/test_lambda_image_lifecycle.py` derives it and fails if this module disagrees:

```
MEASURED_PEAK_MERGES_PER_DAY  ×  ROLLBACK_WINDOW_DAYS
```

The rate is **derived from a recorded measurement, not restated** — the test holds the raw
`git rev-list --count --first-parent --since=` counts per window, dated, and takes the peak of
count/days. That distinction is the whole guard: an earlier version named the rate directly, and
the bound could then be halved by editing one constant and the Terraform together with both
assertions still green. Lowering it now means falsifying a recorded count.

The **peak** is taken rather than the mean, because a bound sized on the average is short during
exactly the weeks a rollback is most likely. The window is the budget the bound exists to buy: a
long weekend plus a working day. It is an engineering choice stated plainly rather than a
derivation — what the requirement asks is that the budget be *named*, and it is.

**Why a generous bound is cheap:** ECR de-duplicates layers within a repository. Builds that do not
touch a requirements file share the dependency layer byte for byte, so the marginal cost of the
Nth image is its code layer — single-digit megabytes against the ~230 MB the first image costs.

The untagged rule beside it is not decoration, but **its usual justification is wrong here and
worth not repeating**: under `IMMUTABLE` tags a push cannot orphan an image by taking its tag —
`PutImage` returns `ImageTagAlreadyExistsException` instead. That is `MUTABLE` behaviour. What
actually produces an untagged manifest in an immutable repository is an image index (a multi-arch
or `buildx`-provenance build writes child manifests that carry no tag of their own) or a deliberate
tag deletion.

The rule earns its place for those, and the distinction matters for the next spec in this arc: if
the build ever moves to `docker buildx`, a one-day untagged expiry begins acting on the children of
a live tagged index, and a reader who believed the orphaned-by-re-push story would not think to
look.

## What the deploy role must already hold

**The grant lands in its own PR, applied before this module.** The registry statements are
`PlatformRegistryManage` and `PlatformRegistryPush` in
[`../base/policies/github-actions-deploy-platform.json.tftpl`](../base/policies/github-actions-deploy-platform.json.tftpl),
and the image's repository rides the SPA's two statements rather than adding a pair of its own.

Two constraints that decision inherits, and that the next specs in this arc inherit from it:

- **The document sits at roughly 94% of IAM's 6,144-character managed-policy budget.** It is not
  the place for the next grant family. A customer-managed policy has its own budget and the role
  is four attachments below its ceiling of twenty.
- **No new wildcard statement was needed.** `ecr:GetAuthorizationToken` is the only registry action
  IAM defines no resource type for, and it already sits alone on `Resource: "*"`. Every other
  action a build and a push need is scoped, measured rather than assumed.

The repository's name is built here and matched there, in two files, and IAM matches ARNs
literally — so a rename on either side is a grant that reads correct to a human and authorizes
nothing. `test_the_repository_name_is_the_one_the_deploy_role_was_granted` is what makes that
fail in CI instead of at a push.

## Encryption

`AES256`, not a CMK — the same deliberate no the SPA's repository takes, dispositioned once in
[`docs/security-baseline.md`](../../../docs/security-baseline.md). Answering it differently here
would be a second answer to one question.

Revisiting it is a **force-new**, and `force_delete` is deliberately unset, so the replacement
fails at `DeleteRepository` until the images are removed by hand.

## Related

- [`../../info/deploy-role-iam.md`](../../info/deploy-role-iam.md) — the trap list for adding a
  resource type to this stack
- [`../spa/README.md`](../spa/README.md) — the other registry, and the container platform around it
