## Description

<!-- What does this PR do and why? -->

## Review (before this branch was pushed)

- [ ] **Two** fresh-context reviews of this diff, in **different frames**, before the push — every
      diff gets two, including a spec-only or docs-only one (`docs/reviewer-contract.md` names the two
      frames for a diff with no code in it). The single review a spec or plan gets is the earlier
      gate on the artifact, not this one.
- [ ] Every finding **fixed or flagged** out loud; nothing dropped silently
- [ ] Any acceptance criterion that could not settle pre-push is listed under **Owed** below

### Owed acceptance criteria (settle on the green run — not `docs/testing/owed.md`)

<!-- One line each, or "none". These block the merge, not the push. Edit this line —
     "none" is a claim you are making, not a placeholder left unfilled. -->

- none

## Checklist

- [ ] CI passes (build, contract, docs, flags) — merging once green **and** every Owed item above is settled
- [ ] Lint, both suites and mypy run and green **locally** — CI no longer runs any of them (`docs/process/ci-and-deploy-traps.md`)
- [ ] No secrets or credentials committed
- [ ] `apps/portal/.env.example` updated if new `VITE_*` vars were added
- [ ] If IaC changed: `tofu plan` output reviewed in PR comments
- [ ] If IaC changed: `infra/terraform.tfvars.example` updated if new variables were added
- [ ] `CLAUDE.md` updated if architectural decisions or conventions changed
