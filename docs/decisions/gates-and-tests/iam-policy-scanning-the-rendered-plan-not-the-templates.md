---
type: Decision
title: "IAM policy scanning = the rendered plan, not the templates (SPEC-139)"
description: "Checkov reads IAM policies only in the rendered-plan scan, never in the `.tf` scan or a loose policy file; both scans and the `.tftpl` extension stay, and a plan holding `aws_iam_policy` resources with no IAM check evaluated fails the job."
---

SPEC-138's Checkov step reads `.tf` and therefore evaluates **zero** IAM policy-document checks, because every policy in this system is a `templatefile()` call it cannot resolve. `deploy-infra.yml`'s plan job now saves the plan, renders it with `tofu show -json`, and scans that with `--framework terraform_plan`: **431 IAM checks against 55 IAM resources**, where the `.tf` scan evaluates none. It lives in `deploy-infra.yml` rather than `security.yml` because the plan and the AWS credentials already are, and that workflow is now in **its own path filter** — otherwise a change to how we scan the infrastructure could merge having never run. **Renaming the `.tftpl` policies to `.json` was raised and REJECTED on measurement:** Checkov emits nothing — zero findings, exit 0 — for a standalone policy file containing `"Action": "*", "Resource": "*"`, because it evaluates `aws_iam_policy` *resources*, not loose documents. The extension was never the blocker; the unevaluated `templatefile()` in the `.tf` was. Keeping `.tftpl` also keeps the signal that `$${aws:PrincipalTag/username}` escaping applies, which is the most error-prone thing about these files. (51 of the 57 templates happen to parse as JSON; 6 do not.) **Two scanners, deliberately:** the `.tf` scan runs every PR + weekly and reports checks the plan scan does not; the plan scan is the only one that reads IAM. Neither is redundant. **The scan asserts its own coverage:** if the plan holds `aws_iam_policy` resources but no IAM check was evaluated, the job fails — a silent regression to the `.tf`-only state would otherwise look identical to a clean run, and that tripwire caught a real matcher bug (`^aws_iam_` never matches `module.data.aws_iam_policy.x`) before CI did. First-run result: the isolation policies are **clean**; all 6 IAM findings are deploy-role `lambda:*EventSourceMapping` statements on `Resource: "*"`, an action AWS does not allow to be resource-scoped — the available hardening is a `lambda:FunctionArn` condition key. Detail: `docs/security-baseline.md`.

## History

### 2026-08-02

- **Settled:** SPEC-139.
