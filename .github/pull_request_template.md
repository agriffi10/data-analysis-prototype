## Description

<!-- What does this PR do and why? -->

## Review (before this branch was pushed)

- [ ] Reviewed in a fresh context at the count the contract sets for this artifact — **two** framed
      reviews for a code diff, **one** for a PR that is only a spec or only a plan
- [ ] Where two were required, they were two **different frames**, not two rounds of one
- [ ] Every finding **fixed or flagged** out loud; nothing dropped silently
- [ ] Any acceptance criterion that could not settle pre-push is listed under **Owed** below

### Owed (criteria that can only settle on the green run)

<!-- One line each, or "none". These block the merge, not the push. Edit this line —
     "none" is a claim you are making, not a placeholder left unfilled. -->

- none

## Checklist

- [ ] CI passes (lint, tests, build) — merging once green **and** every Owed item above is settled
- [ ] No secrets or credentials committed
- [ ] `apps/portal/.env.example` updated if new `VITE_*` vars were added
- [ ] If IaC changed: `tofu plan` output reviewed in PR comments
- [ ] If IaC changed: `infra/terraform.tfvars.example` updated if new variables were added
- [ ] `CLAUDE.md` updated if architectural decisions or conventions changed
