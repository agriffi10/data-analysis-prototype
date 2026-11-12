---
type: Spec
id: SPEC-253
title: "The Deploy Role's Plane Grants Are One Template"
description: "Renders the deploy role's eight per-plane managed policies from one template and one map of planes, so a grant fix is one edit and a new plane is one map entry, with a CI plan showing no IAM document changed."
spec_status: Draft
depends_on: [SPEC-252]
arc: infra-building-blocks
arc_order: 2
---

**Dependency notes:** SPEC-252 (the planes are calls to `control-plane`, so the map of planes this
spec renders grants for can be held against the root's calls to it). Arc reasoning: `ARCS.md` →
*Infra building-blocks arc*.

## Overview

The deploy role holds one managed policy per control plane, each rendered from its own template in
`infra/modules/base/policies/`. The eight templates total 1,170 lines and differ by the plane's
name, the statement ids built from it, the order of their statements, and a handful of statements
only some planes need (a timeout rule, a bucket). A grant fix — the kind `deploy-role-iam.md`
records a dozen of — is eight edits that must agree. This spec renders all eight from one template
and a map, so the shape is written once, and what genuinely differs between planes is visible as
the map's entries rather than buried in eight near-copies.

## Scope

### In Scope

- One template, `github-actions-deploy-control-plane.json.tftpl`, and one `for_each` over a map of
  planes in `modules/base`, replacing eight templates, eight `aws_iam_policy` and eight
  `aws_iam_role_policy_attachment` resources.
- A per-plane extras template only for statements no other plane has, named by the plane.
- `moved` blocks for the sixteen resources, and a test holding the map's keys to the root's calls
  to `control-plane`.

### Out of Scope

- Every other grant `base` holds (platform, front door, static portal, notifications, feedback,
  observability, user directory, DLQ drain, verification). Their shapes are not repeated.
- **Changing what any grant allows.** Every rendered policy document is equivalent to `main`'s, and
  every policy keeps its name and description: `description` is ForceNew on `aws_iam_policy`, so a
  reworded one replaces the policy, and a replaced deploy-role policy is the refresh deadlock
  `deploy-role-iam.md` describes.
- An apply. The plan is the proof.

---

## Functional Requirements

### FR-001: One template renders every plane's deploy grant

#### Description:

`modules/base` takes a map of planes, keyed by slug, each entry carrying the policy's **name** and
**description** exactly as they are today (both are ForceNew, and shared spaces' policy is named
`deploy-shared-spaces` while its slug is `shared-space`), the statement-id prefix, whether the
plane has a ceiling (its `TIMED_OUT` rule grant), and the name of its extras template if it has
one. One template renders the shared statements; the extras, if any, are appended. The arguments
of the sixteen resources are found the way SPEC-252's are, by an attribute diff across the eight,
and every one that varies is a map field.

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` holds one control-plane deploy template and only the extras
      templates a plane needs; the eight per-plane templates are deleted.
- [ ] Every rendered document, parsed as JSON, contains the same statements as `main`'s — compared
      as a set of canonicalised statements by a test that renders both — and the PR's CI plan shows
      no create, update, replace or destroy of any `aws_iam_policy` or attachment in `module.base`,
      only moves.
- [ ] Every extras template a map entry names exists, asserted by a test that reads the map and
      names the plane whose file is missing (a missing file would otherwise surface as
      `templatefile()`'s error at plan, which is correct but late).
- [ ] The archive-only propagation guard becomes one guard for every plane: `time_sleep.wait_for_archive_grant`
      moves to `time_sleep.wait_for_plane_grants`, which depends on all eight attachments, so a
      plane created in the same apply as its grant waits whichever plane it is. The plan shows the
      move and nothing else for it.

### FR-002: The map cannot disagree with the planes

#### Description:

A plane with no deploy grant applies nothing and fails on its first apply; a grant for a plane that
does not exist is a standing permission nobody uses. The map and the root's calls to the
control-plane module are held together.

#### Acceptance Criteria:

- [ ] A test asserts the map's keys equal the `name` arguments of every root call whose `source` is
      `./modules/control-plane`, and fails naming the missing or extra slug.
- [ ] A test asserts a plane has the timeout-rule grant if and only if its root call sets
      `state_machine_timeout_seconds`.

### FR-003: The docs say a plane's grant is a map entry

#### Description:

`deploy-role-iam.md`, `modules/base/README.md` and the control-plane module's README tell a reader
adding a plane that its deploy grant is an entry in this map, landed in its own PR before the plane.

#### Acceptance Criteria:

- [ ] Those three pages say so, and no page still tells a reader to copy a plane's deploy template.
- [ ] `python3 scripts/validate_docs.py` passes.

---

## Implementation Phases

### Phase 1: Render and compare

- Write the template and the map; render both sides in a test and compare statement sets before
  deleting anything.

### Phase 2: Switch and move

- Point `for_each` at the map, write the sixteen `moved` blocks, delete the old templates.

### Phase 3: Hold and document

- The two tests in FR-002; the three pages in FR-003.
