# Completed Spec — SPEC-252: The Control Planes Are One Module, Composed From the Root

Merged as PR #956 (`4bcb629e`), 2026-11-12. Deploys were switched off, so nothing applied at merge,
and the PR's CI plan was the proof then. **It was first applied on 2026-11-13**, with the other two
restructure specs, by Deploy Infrastructure run 43422262900 on `8867e3f3` (#963): *"3 added, 4
changed, 1 destroyed"*. Its log shows 103 plain moves, and four more resources that moved and changed
in the same apply: the grant wait and three in shared spaces. The PR plans below are larger because
they were planned with the web tier switched on; it was switched off again before this apply. A live
session the same day ran every plane except archive green against it (`docs/testing/sessions.md`,
2026-11-13).

## What was completed?

- `infra/modules/control-plane` — the queue and its DLQ, the Pipe, the state machine, the three
  roles and the verbs, written once. Its inputs are exactly the arguments whose **resolved** values
  differ between planes (found by evaluating every old module's locals, not by reading HCL text).
- Eight root files, `infra/plane-<slug>.tf`, each one call to it at the plane's **existing**
  address, with the plane's verbs, environment, queue settings, ceiling and caps beside it. Their
  ASL, execution policy and README live in `infra/planes/<slug>/`; shared constructed ARNs in
  `infra/control-planes.tf`.
- `infra/modules/scheduled-function` (shared spaces' transfer reader is its first caller),
  `shared-space-storage` (Bucket 2, its Lake Formation registration, the portal grant, the 60s
  wait) and `archive-vault` (Bucket 5).
- 55 `moved` blocks in `infra/moved.tf`; the planes' 156 applied cutover blocks deleted.
- Two traps became structure: every verb reaches its definition as `<verb>_function_arn`,
  generated from the verb map, and the `TIMED_OUT` rule exists exactly when the call sets
  `ceiling`. A ceiling naming a verb the plane lacks is refused at plan, and
  `lambdas/test_control_plane_module.py` runs that refusal through `tofu test` with a mocked provider.
- `lambdas/fleet.py` resolves a building block's functions through the root call into it (same
  91 names); `test_fleet_refusals.py` reaches every new refusal.
- The IaC decision is rewritten (one-concept modules composed flat from the root), with
  architecture row 54.

### Deliberate deviations

- **The definition reads `<verb>_function_arn`, not a `function_arns` map.** The names are
  generated, so the trap is still gone, and every ASL reader kept the placeholders it parses. Only
  shared spaces' `acknowledge_function_arn` became `acknowledge_membership_function_arn`.
- **`infra/info/control-plane-shape.md` is a pointer, not deleted.** Two deployed definitions cite
  it inside their ASL `Comment`, and editing that text would be a definition update for a doc link.
- **The `depends_on` comparison with main ran once before the push**, rather than as a test,
  because after merge `main` is the branch.
- **Shared spaces' role split is recorded, not staged.** Its README names the ordering risk.

## What changed from earlier specs?

- SPEC-213's cutover guards: the shared-spaces constructed-ARN exemption and the per-plane
  `moved`-block guard are retired with their subjects. The Step Functions invoke list stays on
  the functions' outputs, as SPEC-213 required.
- Shared spaces now has the three roles every other plane has; `orchestrator` is its execution
  role, kept by name.
- About sixty tests that read Terraform were re-pointed. The lost IDs are listed in the PR.

## Verification

- Locally: Python suite (5,542) and Vitest (3,464) at exit 0; ruff, mypy, lint, format, build,
  `tofu fmt`/`validate`, and every `ci.yml` validator. A local read-only plan matched main except the
  five shared-spaces changes.
- CI plan on PR #956 against the web tier's switch-on baseline (46 to add, 1 to change, 9 to
  destroy): **48 to add, 4 to change, 9 to destroy, 55 moves**. The difference is exactly
  `module.shared_spaces`'s new `sfn` role and its policy, plus in-place updates to the state
  machine's `role_arn` and to the orchestrator role's trust and policy.
- Applied on 2026-11-13, and a live check ran the same day though none was owed (both in the
  opening paragraph). The next account is still created fresh.
- Nothing user-facing changed, so there is no Help & guides update.
