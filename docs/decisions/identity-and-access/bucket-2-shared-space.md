---
type: Decision
title: "Bucket 2 (shared-space)"
description: "Shared-space mutations run through an async control plane of single-task verb Lambdas sharing one `orchestrator` role; access is one session tag per space across ten `custom:shared_space_k` slots, which caps a user's spaces and not a space's members."
---

User-created shared connections via a privileged async control plane (FIFO SQS → EventBridge Pipe → Standard Step Function) — reverses "no backend" for shared-space mutations only; access = a membership principal tag (SPEC-056). **The tag set is ten slots PER USER** — Cognito `custom:shared_space_1..10`, each holding one space name — because a session tag holds exactly **one value** and IAM cannot iterate a list inside a `Resource` ARN. (The Identity Pool's one-claim-to-one-tag mapping was the original statement of that constraint; SPEC-202 retired the pool and the constraint is unchanged, because the API stamps one tag per claim for the same reason.) A space's own member count is unbounded; what is capped is how many spaces one person can be in. The Step Function **orchestrates single-task verb Lambdas** (`validate-authorize → Choice(action) → create-space | add-members | remove-members | leave | delete-space`) sharing a **`shared-space-common` Lambda layer** — **not** one monolithic provisioner (SPEC-062 refactor; the 050→054 monolith is decomposed). The six Lambdas + the Step Function keep **one shared `orchestrator` role** (per-verb roles were descoped — user decision, SPEC-062 FR-005); ~~the layer is CI-built/published (deploy-lambdas) with TF `ignore_changes=[layers]`~~ **— superseded by SPEC-213:** every function is container-packaged, declares no `layers` at all, and gets its shared code from the image; `ignore_changes` names `image_uri`. The one-shared-`orchestrator`-role decision is unchanged. **Create is creator-only** (members added later via add-members from the Connections tab). Decision record: `lambdas/info/planes/shared-spaces.md`; Lambda rules: `lambdas/info/best-practices/lambdas/lambdas.md`. Do NOT build the old daily-IAM-pipeline / user-managed-keys models.

## History

### 2026-08-03

- **Settled:** entered the register.
