# `spa-image` — the SPA container image's registry

One ECR repository and its lifecycle policy, and nothing else. The image that fills it and the
pipeline that pushes it live outside this module (`deploy-spa-image.yml`); the service that pulls
from it is `spa`'s.

| File | Holds |
|---|---|
| `ecr.tf` | the repository and its lifecycle policy |
| `names.tf` | the name the deploy role's grant and the image pipeline are both written against |
| `outputs.tf` / `variables.tf` | the module interface |

## Why it is not inside `spa`

**The web tier has an off switch, and the registry must outlive it.** `web_tier_enabled = false`
removes the `network` and `spa` modules whole ([`../../info/web-tier.md`](../../info/web-tier.md)).
Inside `spa`, the repository would go with them — and with `force_delete` unset, the destroy would
stop at `DeleteRepository` half done. Set, it would take every image with it, so switching the tier
back on would start a service whose task definition names a tag that no longer exists. Out here it
costs cents a month and keeps the rollback window intact while the tier is off.

## Immutable tags are the load-bearing setting

The deploy tags by **commit sha** and the task definition references that tag, so an image is what its
tag says it is for as long as the revision exists. **With mutable tags a re-push under an existing sha
silently changes what a rolled-back task definition starts, and nothing in the state records it.**
There is no `:latest` to point at.

`AES256, not a CMK` is a deliberate no — the layers are a public SPA bundle, and a CMK buys a key
policy to maintain rather than a secret to protect. The disposition is in `docs/security-baseline.md`.
**Revisiting it is a two-step** once the repository holds an image: the block is ForceNew and
`force_delete` is deliberately unset, so the replacement fails at `DeleteRepository` until the images
are removed by hand. Deleting a registry full of deployed images should be a deliberate act, not a
side effect of an encryption change.
