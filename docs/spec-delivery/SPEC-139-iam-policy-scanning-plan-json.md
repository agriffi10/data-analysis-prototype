# Completed Spec — SPEC-139: IAM Policy Scanning (Checkov over the rendered plan)

## What was completed?

- **`deploy-infra.yml`'s `plan` job** gained `-out=tfplan`, a `tofu show -json` render, and a
  Checkov step with `--framework terraform_plan`. Reuses SPEC-138's `apply-gate.sh` and
  `summary-section.sh`; `GATE_CHECKOV_PLAN: report`.
- **The coverage assertion.** If the plan holds `aws_iam_policy` resources but no IAM check was
  evaluated, the job fails. A silent regression to the `.tf`-only state would otherwise be
  indistinguishable from a clean run.
- **`CHECKOV_NORM`** — one normaliser for Checkov's three output shapes, shared by the validation
  and the summary so they cannot drift.
- **The workflow is in its own path filter.** It was `infra/**` only, so the PR that rewrote the
  plan step would not have run it.
- **`docs/security-baseline.md`** gained the plan-scan addendum; the "IAM policies are unscanned"
  gap is rewritten as closed.

**Result:** 55 IAM resources, **431 IAM checks evaluated** (the `.tf` scan evaluates 0), 6 findings.
Every per-user isolation policy passed — `portal-role-permissions` has three statements and zero
`Resource: "*"`. All 6 findings are deploy-role `lambda:*EventSourceMapping` statements, an action
AWS does not permit to be resource-scoped; the available hardening is a `lambda:FunctionArn`
condition key, left as its own PR.

> **Corrected 2026-09-07.** Three of those four actions — `Get`, `Update` and `DeleteEventSourceMapping` — DO accept an `event-source-mapping` ARN; only `Create` and `List` take none. The wildcard is still right, because the mapping's UUID does not exist when the policy is written and `lambda:FunctionArn` pins what an ARN pattern would. Method and evidence: `docs/decisions/infrastructure/`.


## What changed from earlier specs?

- **SPEC-138's Checkov step comment** described an open blind spot; it now points at this scan and
  states that the two are complementary. Neither subsumes the other — only the `.tf` scan reports
  CKV_AWS_50/115/18/82/86 and runs weekly; only the plan scan reads IAM at all.
- **`deploy-infra.yml`'s plan step** now writes a plan file. The PR plan comment is byte-for-byte
  unchanged.
- No infrastructure changed. No policy was edited.

## Verification

The `plan` job ran green on PR #319 with the real plan: 226 resources, 239 failed / 733 passed,
0 parsing errors, and the IAM coverage line `55 / 431 / 6`.

Before that, the Summarize step's script was extracted from the YAML and executed against fixtures
covering flat, `child_modules` and nested-`child_modules` plans, an empty plan, and a simulated
regression. Three defects were found and fixed that way rather than in CI:

1. Checkov's third output shape (a bare summary object, no `.summary` key) made the count `null`,
   and `[ null -gt 0 ]` is a shell error rather than a zero.
2. The IAM matcher was anchored `^aws_iam_`, which never matches `module.data.aws_iam_policy.x` —
   caught by the coverage assertion, which is the argument for having written it.
3. An earlier conclusion that Checkov could not parse `child_modules` was wrong; the fixture was
   malformed. Re-tested properly — and `no-op` resources are scanned too, so the scan reads the
   whole isolation model, not just the PR's diff.

**No user-facing change** — the SPEC-074 Help & guides sweep is a no-op.
