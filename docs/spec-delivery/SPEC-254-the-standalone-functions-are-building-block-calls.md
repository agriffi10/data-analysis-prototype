# Completed Spec — SPEC-254: The Standalone Functions Are Building-Block Calls

Merged as PR #959 (`4c2f4520`), 2026-11-12. Deploys were switched off, so nothing applied at merge,
and the PR's CI plan was the proof then. **It was first applied on 2026-11-13**, with the other two
restructure specs, by Deploy Infrastructure run 43422262900 on `8867e3f3` (#963): *"3 added, 4
changed, 1 destroyed"*. Its log shows 103 plain moves, and four more resources that moved and changed
in the same apply: the grant wait and three in shared spaces. The PR plans below are larger because
they were planned with the web tier switched on; it was switched off again before this apply. A live
session the same day ran every plane except archive green against it (`docs/testing/sessions.md`,
2026-11-13).

## What was completed?

- `module.user_directory`, `module.control_plane_dlq_drain` and a new `module.observability_sweep`
  are root calls to `infra/modules/scheduled-function`, which needed no change.
  `modules/observability` keeps only the logs queue and its backlog alarm, and its README still
  carries the whole pipeline's reasoning.
- `infra/modules/queue-consumer` — a FIFO queue, its own DLQ, a role with one `writer` policy, one
  function and a batch-size-1 event-source mapping. `module.notifications` and `module.feedback`
  call it at their old addresses; its queues keep their resource names, so they did not move.
  Its inputs are what differs between the two callers' resolved values: names, handler, memory,
  environment, the policy, and the queue's `content_based_deduplication` and `deduplication_scope`.
- Each function has a root file `infra/function-<slug>.tf` and its templates and README in
  `infra/functions/<slug>/`, mirroring the planes. The four per-function trust templates
  byte-identical to the building blocks' default are gone (git pairs one of them, as a rename, with
  `queue-consumer`'s own default); the sweep's Sid-less trust is passed explicitly.
- 27 `moved` blocks in `infra/moved.tf`; the 16 applied cutover blocks in `api`, `auth`,
  `observability` and the four retired modules deleted.
- `infra/info/INDEX.md`, the IaC decision, the control-plane and identity areas' `governs`, and
  the architecture prose describe the new layout.

### Deliberate deviations

- **The notifications writer's sender-id validation moved to the root.** `queue-consumer` takes a
  plain environment map and cannot check one key, so the `^AROA[A-Z0-9]+$` shape check is a
  `precondition` on the root output `notifications_writer_role_arn`. Proved in a scratch root: an
  `AROA…` value plans, a role ARN fails the plan.
- **Names are passed whole, as `scheduled-function` takes them**, rather than derived from a slug,
  so `fleet.py` needed no new shape and each root file owns its names once.
- **FR-003's grep criterion was amended** to SPEC-252's list of historical records, plus a
  docstring naming what a path was then.

## What changed from earlier specs?

- Guards that globbed the old layout were widened rather than left to shrink: the Vitest ASCII
  guard, `ci.yml`'s scope patterns and `test_ci_scope`, the Sid sweep, and `test_the_cutover`'s
  command check, which now reads every module `.tf` and each root call's `handler`.
  `test_absence_is_answerable` gained an existence check after three of its rows were found
  pointing at moved files without failing.
- Lost test IDs, listed in the PR: `test_fleet_derivation`'s per-module rows for the four retired
  modules and `observability`, which no longer deploys a function, and the ASCII-guard rows for the four deleted trust templates.

## Verification

- Locally: Python suite (5,539) and Vitest (3,461) at exit 0; ruff, mypy, lint, format, build,
  `tofu fmt`/`validate`, every `ci.yml` validator, and `fleet.py` identical to main. A pytest audit
  hook compared the files every test read on both refs.
- CI plan on PR #959: **48 to add, 4 to change, 9 to destroy** — main's pending plan unchanged (the
  web-tier baseline, the OIDC thumbprint, and SPEC-252's five shared-spaces changes) — plus 32 resource moves into the
  five touched addresses, and no output change outside the web tier's.
- Applied on 2026-11-13, and a live check ran the same day though none was owed (both in the
  opening paragraph). The next account is still created fresh.
- Nothing user-facing changed, so there is no Help & guides update.
