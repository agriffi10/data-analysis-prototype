# Spec: One Owner for Every App-Managed Path

**ID:** SPEC-218
**Status:** Draft
**Last Updated:** 2026-09-04
**Depends On:** None

## Overview

The app writes six folders into every space on the user's behalf — `athenaresults/`,
`archive/`, `shared_tables/`, `saved_queries/`, `user_settings/` and
`_data-quality-reports/`. Their names are currently *declared* in eleven places: three
modules in the SPA, eight across the Lambda fleet, and again as literals inside nine IAM
policy templates. Every copy agrees today, and nothing checks that they do.

This spec changes no behaviour and ships nothing a user can see. It gives each of those
names exactly one owner per tree, splits the one constant that is deliberately doing two
jobs, and adds a sweep that refuses a second declaration. It exists because the arc it
opens ([ARCS.md](ARCS.md)) moves those folders under a real `system_settings/` prefix, and
a move that has to find eleven declarations is a move that will miss one. Missing one is
not a visible failure: the folder names carry **IAM Deny statements keyed on the literal
path**, so a copy left behind does not break — it silently stops being protected.

## Scope

### In Scope

- One owner per tree for the six app-managed root folder names, every other site importing it.
- Splitting `arcommon.ARCHIVE_FOLDER`, which is deliberately one constant for two different
  facts, into two constants that happen to share a value today.
- Rendering the nine IAM policy templates' prefix segments from Terraform locals rather than
  literals typed into each file.
- A sweep that fails on a second declaration, with a fixture corpus that proves the sweep
  itself fails when it should.

### Out of Scope

- **Any change to a path's value.** Every folder resolves to exactly the string it resolves
  to today; this spec is a refactor whose whole point is that it is invisible.
- **`system_settings/` itself.** SPEC-219 admits the new prefix; SPEC-220 moves onto it and
  narrows. Nothing here creates, reads or grants it.
- **Unioning the three divergent lists.** `dqcommon.RESERVED_PREFIXES`,
  `HIDDEN_BROWSER_FOLDERS` and `PICKER_LOCKED_FOLDERS` answer three different questions and
  are *meant* to differ (`protectedFolders.ts` says so at length). This spec gives the
  **names** one owner; the **memberships** stay exactly as many lists as they are now.
- The bucket-root documents `_directory/` and `_config/`. They belong to no space, so the
  arc does not move them and this spec does not re-home their names.

---

## Functional Requirements

### FR-001: The SPA declares each app-managed folder name once

#### Description:

`apps/portal/src/features/file-browser/protectedFolders.ts`,
`systemFolders.ts` and `apps/portal/src/features/archive/archiveSelection.ts` each write the
folder names out as string literals. One new module owns the names; the three list modules
keep their own memberships and build them from it.

#### Acceptance Criteria:

- [ ] A single module exports one named constant per app-managed folder name, and no other
      non-test file under `apps/portal/src` contains those names as a quoted string literal.
- [ ] `HIDDEN_BROWSER_FOLDERS`, `PICKER_LOCKED_FOLDERS`, `UNDELETABLE_ROOT_FOLDERS`,
      `SYSTEM_GROUPED_FOLDERS` and the archive's own list keep their current membership
      **exactly** — asserted by a test comparing each list against its literal value today,
      so a refactor that quietly widens or narrows one is caught.
- [ ] `npm run build` and the full vitest suite pass with no test's expected strings changed.

### FR-002: The Lambda fleet declares each name once, in `cpcommon`

#### Description:

`arcommon.plan`, `arcommon.config`, `focommon.config`, `dqcommon.config`, `fscommon.config`,
`api.routes.athena`, `api.apicommon.fifo` and `api.apicommon.protected` each declare one or
more of these names. `cpcommon` takes ownership; each domain layer imports.

#### Acceptance Criteria:

- [ ] `cpcommon` exports one constant per app-managed folder name, with a module docstring
      `Attributes:` block naming each.
- [ ] No module outside `cpcommon` contains any of those names as a string literal, tests
      excluded.
- [ ] Each domain layer's own list constants (`_UNDELETABLE_FOLDERS`, `RESERVED_PREFIXES`,
      `UNDELETABLE_ROOT_FOLDERS`, …) keep their current membership exactly, asserted per list.
- [ ] This is a **structure** move, not a wording move: the reviewer can check it against the
      `cpcommon` fence — "`cpcommon` owns the algorithm; a domain layer owns its wording" —
      because a prefix is neither a sentence nor a reason code, and the eight copies are one
      structural fact written eight times.
- [ ] `mypy` and the full pytest suite pass with no test's expected strings changed.

### FR-003: The archive receipt folder and the vault key segment become two constants

#### Description:

`arcommon.config.ARCHIVE_FOLDER` is documented as one constant deliberately serving two
facts: the receipt folder inside the user's own space, **and** the leading segment of every
key in the Glacier archive bucket. They are the same string by design today. SPEC-220 moves
the first and must not move the second, and a single constant cannot express that.

#### Acceptance Criteria:

- [ ] Two named constants exist, one per fact, each with a docstring saying which fact it is
      and that the other exists.
- [ ] Every call site reads the one that matches what it is naming — enumerated in the spec's
      delivery doc, not left to inspection.
- [ ] A test asserts the two are equal **today** and is written as an `ACCEPTED_` tripwire:
      it pins current behaviour, names the reasoning, and says *revisit the decision when
      SPEC-220 moves the receipt folder — do not delete the test*.
- [ ] `lambdas/test_archive_bucket_isolation.py` still passes unchanged: the portal role
      names the archive bucket nowhere, and splitting a constant must not introduce a
      statement that does.

### FR-004: The IAM templates take their prefix segments from Terraform

#### Description:

Nine `.tftpl` policy templates under `infra/modules/*/policies/` type an app-managed folder
name into a resource ARN directly. Two of them are easy to miss because they belong to planes
the arc is not otherwise about — `notifications/writer-permissions.json.tftpl` and
`shared-spaces/orchestrator-permissions.json.tftpl` both name `user_settings/`. They become
interpolated from a Terraform local, so the arc's later narrowing edits one value rather than
nine files. The `.tf` files that also mention these names carry them only in variable
`description` strings; those are prose and are swept separately, not interpolated.

#### Acceptance Criteria:

- [ ] No `.tftpl` under `infra/` contains an app-managed folder name as a literal path segment.
- [ ] `tofu plan` against the current state reports **no change** to any IAM policy document —
      the rendered JSON is byte-identical, which is the only evidence that a template refactor
      moved nothing.
- [ ] `tofu fmt -recursive -check` and `tofu validate` pass, and the plan scan's accept list is
      regenerated if any check ID or resource moves.

### FR-005: A sweep refuses a second declaration, and the sweep is proved to fail

#### Description:

A guard that runs in the local gates and fails when any app-managed folder name is declared
outside its owner, in either tree.

#### Acceptance Criteria:

- [ ] The sweep parses rather than regexes where a parser exists (Python AST for `lambdas/`),
      and reports the **file and the name** it found, not just a count.
- [ ] A fixture corpus drives it: at least one fixture per tree that must FAIL, and at least
      one that must PASS. A sweep run only against the tree it guards proves the tree is
      clean, never that the sweep works.
- [ ] The failing fixtures assert the **reason** — which name, in which file — never merely a
      non-zero exit, because the neighbouring failure path returns the same code.
- [ ] Every check in the sweep is mutation-tested once: break it, watch the corpus redden,
      revert. A gate's checks are few and each going quiet is invisible, which is the stated
      exception to the no-sweep rule.

---

## File & Folder Structure

```
apps/portal/src/
└── features/file-browser/
    └── appManagedFolders.ts        # NEW — the SPA's one owner

lambdas/
├── control-plane-common/cpcommon/
│   └── paths.py                    # NEW (or an existing module) — the fleet's one owner
└── ...                             # eight modules lose their literals, gain an import

infra/
└── locals.tf                       # the prefix segments, one place

scripts/
├── validate_app_managed_paths.py   # NEW — the sweep
└── validate_app_managed_paths_test.py  # NEW — its fixture corpus
```

## Implementation Phases

### Phase 1: The SPA

- Add the owner module; re-point `protectedFolders.ts`, `systemFolders.ts` and
  `archiveSelection.ts`.
- Add the per-list membership assertions (FR-001) BEFORE the move, so they are a
  before/after comparison rather than a description of the result.

### Phase 2: The fleet

- Add the `cpcommon` owner; re-point the eight modules.
- Split the archive constant (FR-003) and its tripwire.

### Phase 3: The templates

- Move the segments to a Terraform local; confirm a no-op plan.

### Phase 4: The sweep

- Write the fixture corpus first, watch it fail against a deliberately dirty fixture, then
  write the sweep until the corpus passes; mutation-test each check.
