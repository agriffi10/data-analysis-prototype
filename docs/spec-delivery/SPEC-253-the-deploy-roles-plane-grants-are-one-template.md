# Completed Spec — SPEC-253: The Deploy Role's Plane Grants Are One Template

Merged as PR #960 (`07a908f2`), 2026-11-12. Deploys were switched off, so nothing applied; the PR's
CI plan is the proof.

## What was completed?

- The deploy role's eight per-plane managed policies render from one core template,
  `infra/modules/base/policies/github-actions-deploy-control-plane.json.tftpl`, and
  `local.control_plane_grants` in `infra/modules/base/iam.tf`. Archive and shared spaces each have
  an extras template for the statements no other plane has. `aws_iam_policy.control_plane` and its
  attachment iterate the map.
- The map's fields were found by diffing resolved documents: `name` and `description` verbatim
  (both ForceNew), the Sid prefix, `probe` (every plane but shared spaces), `ceiling` (the six
  planes that set one), and `extras`.
- `time_sleep.wait_for_archive_grant` became `wait_for_plane_grants`, whose `triggers` are every
  plane's policy body, so a plane added or changed later is paused for too.
- 17 `moved` blocks in `infra/moved.tf`, one of them the guard's.
- `lambdas/plane_grants.py` renders a plane's document the way Terraform does and refuses template
  syntax it does not mirror. `lambdas/test_plane_grants_one_template.py` plans `modules/base` under
  mocked providers and compares the two byte for byte. It also holds the map's keys to the root's
  calls into `./modules/control-plane` and `ceiling` to the calls that set one, and proves the
  statements equal the eight templates at `4bcb629e`.

### Deliberate deviations

The spec was corrected during the build for the first four, so they are deviations from it as drafted.

- **A `probe` field the drafted spec did not list.** Shared spaces carries no validate-authorize invoke;
  its probe is its backfill function, granted in its extras.
- **The FR-002 ceiling test reads `ceiling`, not `state_machine_timeout_seconds`.** The latter is
  only the variable the definition template reads.
- **The map is a local in `base`, not a variable.** `base` applies before the planes and cannot
  read them, and a root variable would put eight descriptions in the root.
- **The guard is replaced once.** The drafted spec asked for a move and nothing else, but a sleep with no
  trigger never pauses for a plane added later, and `replace_triggered_by` alone misses a create on
  the OpenTofu 1.8 CI runs. Adding `triggers` costs one 30-second replacement on the next apply.
- **The statement-equivalence test is temporary.** The PR that first changes a plane's grant on
  purpose deletes it; the name-and-description test stays.

## What changed from earlier specs?

- Every suite that read a per-plane template now reads the rendered plane documents:
  `test_deploy_platform_policies.py`, `test_cold_start_probe.py`,
  `test_invoke_grant_population.py`, `test_backfill_grant_population.py`,
  `test_state_machine_shared_space.py` and `test_portal_role_preservation.py`. The attachment
  ceiling in `test_feedback_deploy_grant.py` counts a `for_each` attachment once per plane, and
  `test_ci_scope.py`'s template floor was re-derived from 58 to 53.

## Verification

- Locally, on the rebased tree: 5,569 Python tests passed, and the one failure (the template
  floor) was re-derived and its file rerun green. Vitest exited 0, as did ruff, mypy, lint, format, build,
  `tofu fmt`/`validate` and every `ci.yml` validator. `tofu console` rendered all eight documents
  equal to the old ones. Two diff reviews ran, one in the IAM and apply frame and one planting a
  defect against each adapted consumer.
- CI plan on PR #960: **49 to add, 4 to change, 10 to destroy**. Outside `module.base`, the 147
  action lines are identical to SPEC-254's PR plan. Inside it are 16 moves, the guard's move with
  its replacement, and the existing OIDC thumbprint update. No policy or attachment changes.
- Not applied anywhere. Nothing user-facing changed, so there is no Help & guides update and no live check.
