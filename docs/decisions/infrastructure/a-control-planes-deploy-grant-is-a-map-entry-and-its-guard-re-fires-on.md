---
type: Decision
title: "A control plane's deploy grant is an entry in one map, and its propagation guard re-fires on triggers (SPEC-253)"
description: "**A control plane's deploy grant is one entry in `local.control_plane_grants`**, rendered from one core template plus an extras template only for statements no other plane has — never a copied template. Its `name` and `description` are ForceNew. Suites read a plane's grant through `lambdas/plane_grants.py`, never a file. **A `time_sleep` guarding grants added later needs `triggers`**: `replace_triggered_by` never fires on a create before OpenTofu 1.12, and CI runs 1.8, so a guard written that way looks right in every local plan on a newer tofu and pauses for nothing in CI."
---

The eight per-plane deploy policies were eight near-copies that differed by the plane's name, its
Sid prefix, whether it has a validate-authorize probe and a `TIMED_OUT` rule, and four statements
only archive or shared spaces need. A grant fix was eight edits that had to agree. They are now one
core template and one map in `modules/base`, held by tests to the root's calls into
`./modules/control-plane`: the keys in both directions, and `ceiling` to the calls that set one.
`infra/modules/base/README.md` says what an entry carries.

- **No file is a plane's policy any more**, so every guard that measures one, whether the budget,
  the wildcard and account rules, the Sid shape or the invoke populations, reads the composed
  document through `plane_grants`. That renderer refuses template syntax it does not mirror, and a
  test plans the module under mocked providers and compares the two byte for byte. The first
  version stripped whitespace after `~}` greedily and agreed with Terraform only because its
  fixtures had one newline and no indentation. Its fixtures are now taken from `templatefile()`.
- **The guard's trigger was nearly the wrong one.** Its first version used `replace_triggered_by`
  on the plane policies and attachments, which re-fired for a new plane on the local OpenTofu 1.12,
  so every local check passed. The OpenTofu
  1.12 release changed it to fire on a create as well; on the 1.8 CI runs it fires on an update or
  a replacement only, so a ninth plane would have got no pause at all. `triggers` keyed to the
  policy bodies, the pattern `wait_for_platform_grant` already used, works on every version.

Do NOT copy a plane's template for a new plane; do NOT read a plane's grant from a template file in a
test; do NOT guard later additions with `replace_triggered_by` alone.

## History

### 2026-11-12

- **Settled:** SPEC-253.
