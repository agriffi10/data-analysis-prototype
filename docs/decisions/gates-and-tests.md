# Gates, scanners and tests

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries the one-line digest of each entry. This file holds the reasoning, the constraints and the
explicit "do NOT build" fences for one area. **Read the entry you need, not the file.**

## Contents

- [Security scanning (SPEC-138)](#security-scanning-spec-138)
- [IAM policy scanning = the rendered plan, not the templates (SPEC-139)](#iam-policy-scanning--the-rendered-plan-not-the-templates-spec-139)
- [A scanner gate blocks on a narrowed count, never a total (2026-08-09, completes SPEC-138)](#a-scanner-gate-blocks-on-a-narrowed-count-never-a-total-2026-08-09-completes-spec-138)
- [Compiler and coverage defaults are declared, never inherited (SPEC-150)](#compiler-and-coverage-defaults-are-declared-never-inherited-spec-150)
- [`ACCEPTED_` tripwires: what the project knows it has not verified (SPEC-153)](#accepted_-tripwires-what-the-project-knows-it-has-not-verified-spec-153)

## Security scanning (SPEC-138)

Five classes of scan across all three surfaces — SAST (Semgrep `p/owasp-top-ten` + language rulesets), dependencies (`npm audit` at **two scopes**, `pip-audit` over glob-discovered requirements), secrets (`gitleaks`, full history, redacted), IaC (`checkov` on `infra/`) and DAST (OWASP ZAP baseline, weekly, unauthenticated). Three decisions carry the weight. **(1) Gating is data, not code:** one `GATE_*` value per scanner in `security.yml`, all `report` at ship, and an unrecognised value is a *hard error* — a typo must never silently mean "not enforcing". The exception is `eslint-plugin-security` + `no-unsanitized`, which run inside `npm run lint` (now `--max-warnings 0`) and therefore **block**: an injection sink in code being written now should stop the PR, not become a line in a report. **(2) Every scanner is version-pinned**, for the reason `pyproject.toml` already records — ruff 0.16.0 widened its defaults and reddened `main` with 500 findings in untouched files (#311); a scanner that gains rules on release does that to every open PR at once. **(3) "Did not run" is never "clean":** unparseable output, a scanner exit ≥ 2, or Checkov `parsing_errors > 0` fails the job *even under `gate=report`*, and Semgrep's partial-parse count is published beside its finding count. That is SPEC-137's failure mode — three gates all satisfied by an import that could never resolve — and a zero from a broken scanner reads as evidence, which is worse than no scanner. **Not available, not declined:** CodeQL, SARIF upload and the Security tab need GitHub Code Security, which a private repo on a personal account does not have — hence the job-summary-plus-artifact substitute and the fact that each run is a fresh snapshot with no cross-run deduplication. **Declined on merit:** OWASP Dependency-Check (NVD-centric, slower and less accurate than the ecosystem-native audits) and a second `bandit` (ruff already selects `S`). **Known blind spot:** Checkov parses `.tf`, so the `.tftpl` IAM policies that implement the whole `${aws:PrincipalTag/username}` isolation model are opaque strings to it — a green Checkov job says nothing about the authorization model, and closing that needs `checkov -f plan.json` against a `tofu plan`. First-run findings and their dispositions: `docs/security-baseline.md`.

## IAM policy scanning = the rendered plan, not the templates (SPEC-139)

SPEC-138's Checkov step reads `.tf` and therefore evaluates **zero** IAM policy-document checks, because every policy in this system is a `templatefile()` call it cannot resolve. `deploy-infra.yml`'s plan job now saves the plan, renders it with `tofu show -json`, and scans that with `--framework terraform_plan`: **431 IAM checks against 55 IAM resources**, where the `.tf` scan evaluates none. It lives in `deploy-infra.yml` rather than `security.yml` because the plan and the AWS credentials already are, and that workflow is now in **its own path filter** — otherwise a change to how we scan the infrastructure could merge having never run. **Renaming the `.tftpl` policies to `.json` was raised and REJECTED on measurement:** Checkov emits nothing — zero findings, exit 0 — for a standalone policy file containing `"Action": "*", "Resource": "*"`, because it evaluates `aws_iam_policy` *resources*, not loose documents. The extension was never the blocker; the unevaluated `templatefile()` in the `.tf` was. Keeping `.tftpl` also keeps the signal that `$${aws:PrincipalTag/username}` escaping applies, which is the most error-prone thing about these files. (51 of the 57 templates happen to parse as JSON; 6 do not.) **Two scanners, deliberately:** the `.tf` scan runs every PR + weekly and reports checks the plan scan does not; the plan scan is the only one that reads IAM. Neither is redundant. **The scan asserts its own coverage:** if the plan holds `aws_iam_policy` resources but no IAM check was evaluated, the job fails — a silent regression to the `.tf`-only state would otherwise look identical to a clean run, and that tripwire caught a real matcher bug (`^aws_iam_` never matches `module.data.aws_iam_policy.x`) before CI did. First-run result: the isolation policies are **clean**; all 6 IAM findings are deploy-role `lambda:*EventSourceMapping` statements on `Resource: "*"`, an action AWS does not allow to be resource-scoped — the available hardening is a `lambda:FunctionArn` condition key. Detail: `docs/security-baseline.md`.

## A scanner gate blocks on a narrowed count, never a total (2026-08-09, completes SPEC-138)

SPEC-138 shipped every scanner as `report` and `docs/security-baseline.md` proposed a threshold for
each. Four now block: `gitleaks` and `pip-audit` at a true zero (2026-08-02), and **Semgrep** and
**Checkov** here, plus `GATE_CHECKOV_PLAN` on the rendered-plan IAM scan. Semgrep needed one thing —
`--exclude-rule` for a Flask template-injection rule in a fleet with no Flask, excluded **by rule ID**
rather than by dropping `p/owasp-top-ten`, with a test asserting there is exactly one exclusion so a
second cannot arrive without a disposition. Checkov needed a shape.

**The shape is an ENFORCE list, not a suppression list.** Checkov reports 373 failures over 22 rules
on `infra/`, nearly all of them documented accepts — no VPC, no CMK, no X-Ray, no WAF. Gating that
total would mean suppressing 22 rules to enforce a handful, producing a file nobody reads and a gate
whose meaning drifts every time the scanner adds a rule. So `.github/checkov-enforced.txt` names the
**52 check IDs measured at zero**, and the gate counts failures on those; the rest publish and do not
block. **The criterion is "passes today", not "matters most"** — two entries are merely operational
(`CKV_AWS_216`, `CKV_AWS_305`) and are in because they pass. Deciding which checks *deserve*
enforcement is an argument to re-litigate on every infra change; holding everything already clean is
not, and it costs no remediation to turn on. Same ratchet-at-the-measured-level shape as the coverage
floors (SPEC-150) and the mypy baseline.

**The plan scan accepts by check ID AND resource, never by ID.** Its two permanent findings —
`CKV_AWS_290`/`CKV_AWS_355` on `module.base.aws_iam_role_policy.github_actions_deploy` — exist because
the deploy role must create resources that have no ARN yet and no applicable condition key. Keyed by
resource, the same two rules firing on any other policy still fail; keyed by ID alone, the exemption
would silently cover the isolation policies, which is the one thing this scan exists to watch.

**Three implementation facts that are not obvious and will bite again:**

- **`--quiet` strips `passed_checks`**, and without them an enforced ID that passed is
  indistinguishable from one that never ran. The flag is gone from the `.tf` scan (the plan scan had
  already learned this) and a test pins its absence.
- **An enforced ID evaluated against nothing is a hard error, not a pass** — and so is a plan-scan
  acceptance that matches no finding. A typo, a rename in a scanner bump, or a resource class
  leaving the repo all yield a line that enforces nothing while reading as enforcement: "did not run
  is never clean", turned on the gate's own configuration. **Neither Checkov gate can redden a
  production deploy:** `deploy-infra.yml`'s `plan` job is `pull_request`-only and `apply` does not
  depend on it, so both gates block PRs and nothing else.
- **A gate's count defaults to a NON-NUMERIC sentinel, and its narrowing step assigns before it
  echoes.** These two together are what make the hard errors above reachable, and the first draft
  had neither — every one of them arrived at the gate as a silent green. `echo "VAR=$(script)"` does
  **not** fail the step when the script fails: `echo` exits 0, `set -e` sees success, and the empty
  value it writes wins over any earlier record. Only an assignment's failed substitution trips
  `set -e`. And `${VAR:-0}` substitutes on **empty** as well as unset, so a numeric default converts
  "no count was written" into "clean" — `apply-gate.sh` rejects a non-numeric count, which is what an
  absent count is. ZAP's pre-existing `no-report` default is the same idea; it was there to be copied
  and wasn't. **A pessimistic pre-write does not substitute for either**, which is what the first
  draft believed.

**One exposure accepted, and it is not the Checkov one.** Semgrep's binary is pinned but its
`--config p/*` rulesets are fetched from the registry at scan time and are **not** — so an upstream
rule addition can redden every PR with no code change, the shape #311 made this repo pin everything
to avoid. Accepted because `pip-audit` already blocks on a live advisory database with exactly the
same property, and because the alternative (vendoring 157 rules) trades a rare interruption for a
permanent staleness. The Flask false positive is the demonstration that these rulesets misfire here;
if a second arrives, the answer is another `--exclude-rule` with a disposition, not a narrowed count.

**Still not blocking, by decision:** `npm audit` — `apply-gate.sh` has no severity threshold and the
runtime scope carries two accepted `dompurify` advisories (monaco pins the version exactly), so a
flip would redden every PR; ZAP — two Lows survive by decision, so gate by `riskcode >= 2` or not at
all. Record: `docs/security-baseline.md` → *Addendum — The Gates Went On*.

## Compiler and coverage defaults are declared, never inherited (SPEC-150)

`tsconfig.app.json` and `tsconfig.node.json` state `"strict": true` even though TypeScript 6 already
defaults it on, and both suites carry **literal** coverage floors. Adding the `strict` key changed
**zero** errors — that is the point, and a build that finds otherwise should stop and re-derive the
premise rather than "fix" the errors.

This reverses the implicit trade-off of leaving a default alone because it happens to be correct.
`pyproject.toml`'s ruff block is the precedent and says it outright — "THE RULE SET IS CHOSEN HERE,
NOT INHERITED" — after ruff 0.16 widened its own default set from 59 rules to 413 overnight and
turned `main` red with 500 findings in files nobody had touched (#311). A default is a decision
*someone else* gets to change; strict is this project's single most important type guarantee, and it
does not ride on one.

The coverage floors are the same principle pointed at a different kind of erosion: both suites
measured coverage and neither gated on it, so deleting tests passed CI identically to keeping them.
They are hard-coded literals on purpose. Nothing computes, inherits or reads them from a file, so
changing one is a visible one-line diff in review rather than a number that drifted.

> **Superseded — the ratchet is gone; the floor is flat 85.** They were ratchets at the measured
> level (portal 91/86/89/93, lambdas 95) until the suites were rewritten around entry points rather
> than around individual functions. A ratchet at the measured level makes any deliberate reduction
> in test volume fail CI, which is the opposite of what was wanted, and it rewards adding tests
> around internals to buy back a tenth of a point. Both suites now sit at a flat **85** and stay
> there: raise it only with a reason that is not "coverage happens to be higher today", and never
> lower it to accommodate a regression.
>
> **What that costs, measured.** A coverage floor was never a measure of guard strength, and the
> review of that rewrite proved it: four separate mutations of production code — an archive
> rollback default that routed to deletion, a route minting its own AWS client, the CI watcher
> reporting a red run green, and a verb losing its `@traced` — each passed the full suite with
> total coverage unchanged to the hundredth of a point. **Mutate the guard; do not ask coverage
> whether it exists.**

**Do NOT read this as "enable strict"** — it was already on. The work is *declaring* an inherited
default, which is a much smaller and different thing.

**The typecheck gate itself is separate and already shipped** (#363): `ci.yml` runs `npm run build`
on every PR. Two traps are recorded in that file's header comment and should be read before touching
it — vitest does not typecheck, and `tsc --noEmit -p apps/portal/tsconfig.json` **exits 0 having
checked nothing**, because that config is solution-style (project references only, no
`files`/`include`). `tsc -b` is the only invocation covering the app *and* its `*.test.tsx` files.
SPEC-150 confirmed the gate empirically on a scratch PR: with the #361 defect reintroduced, Lint and
Format check passed, **Build failed**, and Test was skipped.

## `ACCEPTED_` tripwires: what the project knows it has not verified (SPEC-153)

The repo invented this idiom in SPEC-110 (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`).
SPEC-153 makes it the standard way to record a **load-bearing premise that is corroborated but not
discharged**, and a **documented behaviour someone will later mistake for a bug**.

A tripwire test pins **today's behaviour**, names the reasoning in its docstring, and ends with the
same instruction every time: **if it starts failing, revisit the decision — do not delete the test.**
That is the whole point. A premise held only in prose degrades silently; a premise held in an
assertion tells you the day it stops being true.

Four now exist. Two pin premises:

- **Athena's column-name fold** (`test_apply_refresh.py`). AWS documents that Athena lowercases every
  column name it creates through DDL, which is why SPEC-149 hard-codes the fold — but 149's in-place
  `UpdateTable` bypasses Athena, so the fold is now **ours**. If the premise is wrong, the first
  refresh of a mixed-case table silently re-cases every column while `diff-schema`, which folds case
  to compare, reports them unchanged: a mutation no test and no notification would report. The
  tripwire pins that a live `Order_ID` becomes `order_id` and the carried comment survives. Still
  **corroborated, not discharged** — the `GetTable` read-back that would discharge it is an owed live
  check.
- **The projection round-trip** (`test_load_table_definition.py`). The existing round-trip builds its
  fixture from `ddl.projection_properties` and compares the reconstruction re-rendered through the
  same function: render → parse → render vs render. It proves the parser is a left inverse of the
  renderer **on the renderer's own image**, which is worth having and is not "reads tables this
  pipeline did not write". It was **kept and renamed to say so**, and a second fixture whose
  properties did not come from our renderer was added beside it, with a guard test that fails if the
  fixture ever becomes the renderer's output.

Two pin accepted behaviour:

- **A redelivered notification create writes a second inbox row** (`test_notifications_writer.py`).
  These pipelines are at-least-once and `apply_create` mints a fresh `uuid4` per invocation; FIFO's
  producer-side dedup window does not bound a visibility-timeout redelivery. **Accepted:** the blast
  radius is one duplicated line in a read-only, dismissible list, while the fix with teeth is a
  producer-supplied idempotency key — a contract change across four control planes and the browser
  producer. `dqcommon.index_store` handles the equivalent case by replacing the row, and the
  asymmetry is now stated rather than accidental.
- **The runs-index cap evicts by position, not by timestamp** (`test_index_store_dqcommon.py`). Once
  a replay has moved a row to the end, position order and timestamp order disagree and the next new
  run drops a row that is newer in time. **Accepted:** the code says at the cap that the dashboard
  sorts by timestamp itself, and every evicted run's report object is untouched.

A tripwire is **not** a licence to leave a defect. It is the difference between a project that knows
what it has not verified and one that has forgotten.
