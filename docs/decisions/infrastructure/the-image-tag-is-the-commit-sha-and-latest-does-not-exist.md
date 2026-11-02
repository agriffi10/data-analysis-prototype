---
type: Decision
title: "The image tag is the commit sha, and `:latest` does not exist (SPEC-193)"
description: "Both ECR registries are `IMMUTABLE` and every image tag is a commit sha with no `:latest`, so a bad build is fixed by a new commit. CI owns which revision the service runs and must point it; Terraform owns `desired_count`. `task_definition` is ignored while `desired_count` is not — so **CI must point the service**, and a pipeline that only registers a revision leaves a `CannotPullContainerError` **indistinguishable from the endpoint failure the platform is tested for** (the Lambda fleet's registry rides the same rule)."
---

The ECR repository is `IMMUTABLE`. An image is therefore what its tag says it is for as long as the
revision referencing it exists, and a re-push under an existing sha cannot silently change what a
rolled-back task definition starts.

> **Extended by SPEC-212 (2026-09-01).** There are now **two** registries on this rule — the SPA's
> and the Lambda fleet's — and everything below still holds for both. What differs is the
> retention bound: the SPA's is thirty images, a rollback window measured in deploys, while the
> fleet's is computed from the merge rate against a window measured in days, because the failure it
> rolls back from surfaces at a cold start rather than at a deploy. Full entry: *One image for the
> whole Lambda fleet*.

**The consequences are not cosmetic.** There is no `:latest` to point a task definition at, so the tag
is a **variable** (`spa_image_tag`) rather than a constant — a fixed placeholder tag could be pushed
exactly once, ever, and a bad first push would burn it. And a tag cannot be re-pushed after a bad
build: the fix is a new commit, not a retry.

**The service's `task_definition` is in `ignore_changes` and its `desired_count` is NOT**, which is a
division of ownership with teeth. CI owns which revision runs — so **CI must point the service**, and
a pipeline that only registers a revision leaves the service on the old one, failing with a
`CannotPullContainerError` that reads exactly like the endpoint failure this platform is tested for.
Terraform owns the count, because raising it from 0 to 1 is a verification step and an ignored
attribute would make that step a silent no-op.

Detail: `spec-delivery/SPEC-193`.

## History

### 2026-09-01

- **Changed:** SPEC-212 extended the rule to a second registry, the Lambda fleet's, with its retention computed from the merge rate.

### 2026-08-26

- **Settled:** SPEC-193.
