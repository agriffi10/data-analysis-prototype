# Spec: One Builder Per App-Managed Path

**ID:** SPEC-218
**Status:** In Progress
**Last Updated:** 2026-09-05
**Depends On:** None

## Overview

Three folders move under a real `system_settings/` prefix in the arc this spec opens
([ARCS.md](ARCS.md)): `athenaresults/`, `archive/` and `shared_tables/` — the set the collapsed
group row already shows, chosen by the user over four wider alternatives. This spec moves nothing.
It makes the move *findable*, and it ships nothing a user can see.

The risk it retires is not that a folder name is spelled in many places. It is that **almost every
rule about these folders is anchored at depth 1** and built as `{space_root}{NAME}/`, so a move to
depth 2 leaves each rule silently not matching — `fscommon/authz.py` says so in its own comment:
the check is written as containment *"because a rule that depends on the layout not changing is a
rule that fails silently when it does."* The layout is about to change. So the unit this spec
creates is a **path builder per fact**, not a constant per name: 220 then changes one function per
tree instead of hunting every anchored comparison.

## Scope

### In Scope

- One path builder per fact, per tree, for the three moving folders, with every anchored
  `{root}{NAME}/` comparison routed through it.
- Splitting the **three** different facts currently spelled `archive` into three named things, of
  which exactly one moves.
- A test pinning the set of IAM policy templates that name a moving folder, so 219 cannot miss one.
- A sweep that refuses a new declaration outside its owner, wired into CI, with a fixture corpus
  that proves the sweep fails when it should.

### Out of Scope

- **Any change to a path's value.** Every folder resolves to exactly today's string; this spec is
  invisible by construction, and FR-001/FR-002 say so as a criterion.
- **`system_settings/` itself.** 219 admits it additively; 220 moves onto it and narrows.
- **The three folders that are NOT moving** — `saved_queries/`, `user_settings/` and
  `_data-quality-reports/`. `saved_queries/` is deliberately user-owned (`systemFolders.ts`: *"the
  user names, moves and deletes what is in them"*), and the other two are hidden from the browser
  entirely, so making them children of a visible folder would change what a user can see. They keep
  the owners they have; this spec neither re-homes nor sweeps them.
- **Interpolating the folder segment into the `.tftpl` templates.** An earlier draft required it.
  It is dropped because **three test files read those templates as raw text** —
  `archiveWriteLock.test.ts`, `verificationAccess.test.ts` and the plan test in
  `test_plan_arcommon.py` — and `archiveWriteLock.test.ts` is the only place browser-side and
  IAM-side agreement is checkable **without AWS credentials**. Its own docstring says a test that
  merely asserted the template *contains* `archive` would pass with the predicate deleted.
  Interpolation would trade that for a plan obtainable only from CI. FR-004 pins the template
  population instead, which closes the same risk without spending the property.
- **Unioning the divergent membership lists.** `dqcommon.RESERVED_PREFIXES`,
  `HIDDEN_BROWSER_FOLDERS` and `PICKER_LOCKED_FOLDERS` answer different questions and are meant to
  differ. This spec changes how a path is BUILT, never who is in a list.

---

## Functional Requirements

### FR-001: The SPA builds every app-managed path through one function

#### Description:

Four non-test modules name a moving folder as a literal — `protectedFolders.ts`, `systemFolders.ts`,
`archiveSelection.ts` and `fileBrowser.constants.ts` (which already declares `ARCHIVE_FOLDER` and
whose docstring already claims the owner role). More importantly, the comparisons are anchored:
`protectedFolders.ts` tests `folderPrefix === \`${rootPrefix}${folder}/\`` and
`writeLockedPrefix.ts` builds `\`${rootPrefix}${ARCHIVE_FOLDER}/\``. One module owns both the names
and the construction.

#### Acceptance Criteria:

- [ ] One module exports the three names AND an `appManagedPrefix(rootPrefix, folder)` builder; every
      anchored `${rootPrefix}${NAME}/` construction in `apps/portal/src` goes through it.
- [ ] `fileBrowser.constants.ts`'s existing `ARCHIVE_FOLDER` either moves into that module or
      re-exports from it — **not a second owner beside it**, which is the state this FR exists to end.
- [ ] Every existing list keeps its membership **exactly**, asserted against values spelled out as
      literals in the test file. Current coverage is `toContain`/`arrayContaining`, which passes
      under a widening, so this criterion is load-bearing rather than ceremonial.
- [ ] The sweep in FR-005 is scoped to **path construction**, not to any occurrence of the word: the
      refusal table's keys are unquoted identifiers a string sweep cannot see, and Help copy names
      these folders in ordinary prose, which is wording and stays where it is.

### FR-002: The fleet builds them through one function in `cpcommon`

#### Description:

Thirteen non-test modules are involved: eleven declare a literal, and two build a path with an
f-string — `cpcommon/results.py` (which **is** the per-query Athena output location; the workgroup's
own `output_location` is an unused admin fallback) and `table_share_check_target_absent.py` (which
writes the `destPrefix` that becomes a shared table's Glue `LOCATION`, the arc's own named trap).

#### Acceptance Criteria:

- [ ] `cpcommon` exports a builder per **fact**, and the domain layers call it. Ownership is by fact,
      not by name — FR-003 exists because one name currently carries three.
- [ ] The criterion is written as *no module outside `cpcommon` constructs an app-managed path
      segment*, **never** as *no module contains the string*: `"archive"` is an overloaded bare
      token — `ARCHIVE_MODES = frozenset({"archive", "restore"})`, `observability.init(service="archive")`
      in eleven handlers, and twenty-odd user-facing sentences in `arcommon/messages.py`. A
      string-shaped criterion would drag the wording modules across the `cpcommon` fence.
- [ ] A prefix is **structure, not wording**, so this does not erode "`cpcommon` owns the algorithm;
      a domain layer owns its wording" — `cpcommon` already owns exactly this kind of thing in
      `results.py` and `s3_listing.py`. The reviewer checks that claim against the fence.
- [ ] Every domain list constant keeps its membership exactly, asserted per list.
- [ ] `mypy` and the full pytest suite pass with no test's expected strings changed.

### FR-003: `archive` is three facts, and exactly one of them moves

#### Description:

Four constants spell `"archive"` and they mean three different things:

| Fact | Today | Moves in 220? |
|---|---|---|
| The user's receipt folder in their own space | `arcommon.config.ARCHIVE_FOLDER`, `apicommon.protected.ARCHIVE_FOLDER` | **Yes** |
| The leading key segment in the Glacier vault | `arcommon.config.ARCHIVE_FOLDER`, `apicommon.fifo.ARCHIVE_FOLDER` | No |
| Control-plane scratch in the admin bucket | `arcommon.plan.PREFIX` | No |

`arcommon.config.ARCHIVE_FOLDER` is documented as deliberately serving the first two at once —
*"One constant, because they are the same folder name by design"* — and they diverge at two call
sites in `arcommon/paths.py`, one building an archive-bucket key and one a space key.
`arcommon.plan.PREFIX`'s docstring is already a warning against merging them: *"Three unrelated
things, in three buckets."*

#### Acceptance Criteria:

- [ ] Three named constants exist, one per fact, each docstring saying which fact it is, which bucket
      it addresses, and that the other two exist.
- [ ] Every call site reads the one matching what it names — `arcommon/paths.py`'s two builders and
      `apicommon`'s two same-named constants enumerated explicitly in the delivery doc.
- [ ] An `ACCEPTED_` tripwire asserts all three are equal **today**, names the reasoning, and says
      *revisit when 220 moves the receipt folder — do not delete the test*.
- [ ] `infra/modules/analytics/s3.tf`'s `prefix = "archive/"` lifecycle rule is identified in the
      delivery doc as **fact 3, which must not move**. An earlier draft of this spec claimed the
      `.tf` files carried these names only in variable descriptions; that was false, and this is the
      one functional `.tf` literal it missed.
- [ ] `test_plan_arcommon.py`'s three assertions on the rendered template text still pass unchanged.

### FR-004: The template population is pinned, so 219 cannot miss one

#### Description:

Eight `.tftpl` policy templates name a moving folder in a space bucket (an earlier draft counted
nine: the ninth, `archive/policies/sfn-permissions.json.tftpl`, names only the admin bucket's
`archive/` scratch prefix — fact 3 — and is pinned separately as the one that must NOT gain a
sibling). 219 must add a sibling statement to each of the eight, and missing one is the arc's
silent failure. Rather than interpolate the segment (see Out of Scope), a test enumerates the
population.

#### Acceptance Criteria:

- [ ] A test asserts the exact set of `.tftpl` files under `infra/` naming a moving folder, spelled
      out as literal paths, and fails on a file joining or leaving the set.
- [ ] It also records, per file, which of the three folders it names — a file gaining a second
      folder must redden it, not just a file appearing.
- [ ] The set is **measured, not asserted from the same rule the test uses** — a self-derived
      expectation passes on a deletion.
- [ ] The delivery doc records the asymmetry that decides 219's shape: shared-space Denies are
      written `${shared_space_bucket_arn}/*/athenaresults/*`, and an S3 resource `*` matches `/`, so
      they keep matching after the move; the personal ones are anchored at
      `${aws:PrincipalTag/username}/` and stop matching entirely. **The unprotected window at cutover
      is personal-space-only**, and `ResultsNoDelete` / `UserSettingsNoDelete` are the statements it
      turns on.

### FR-005: A sweep refuses a new declaration, runs in CI, and is proved to fail

#### Description:

A guard that fails when an app-managed path is constructed outside its owner, in either tree.

#### Acceptance Criteria:

- [ ] The sweep parses rather than regexes where a parser exists (Python AST), and names the **file
      and the fact** it found, never just a count. `lambdas/test_one_jwks_path.py` is the existing
      pattern to follow.
- [ ] **It is wired into `.github/workflows/ci.yml` beside the other validators**, and a criterion
      names that step. CI runs the build and the validators and nothing else, so a sweep that is not
      a validator does not run at all — and every other criterion here is tickable against a script
      nothing executes.
- [ ] A fixture corpus drives it: at least one fixture per tree that must FAIL and one that must
      PASS, asserting the **reason** — which fact, in which file — never merely a non-zero exit.
- [ ] Every check in the sweep is mutation-tested once, and so is the **CI wiring**: break the check,
      watch the corpus redden, revert.

---

## File & Folder Structure

```
apps/portal/src/lib/
└── appManagedPaths.ts                    # NEW — names + `appManagedPrefix(root, folder)`; in lib/
                                          #       because two features consume it and the archive
                                          #       feature imports nothing from another feature

lambdas/control-plane-common/cpcommon/
└── app_managed.py                        # NEW — names + one builder per fact (`paths.py` already
                                          #       exists and holds containment only)
lambdas/archive-common/arcommon/
└── plan.py                               # `PREFIX` stays: fact 3 has one consumer and is pinned here

scripts/
├── validate_app_managed_paths.py         # NEW — the sweep
└── validate_app_managed_paths_test.py    # NEW — its fixture corpus
.github/workflows/ci.yml                  # the sweep joins the validators
```

## Implementation Phases

### Phase 1: The SPA

- Add the owner module and the builder; re-point the four modules, folding
  `fileBrowser.constants.ts`'s `ARCHIVE_FOLDER` in rather than beside.
- Write the literal-valued membership assertions BEFORE the move, so they compare before against
  after rather than describing the result.

### Phase 2: The fleet

- Add the `cpcommon` builders; re-point the thirteen modules, including the two f-string sites.
- Split the three `archive` facts and add the tripwire.

### Phase 3: The template inventory

- The population test, and the personal-vs-shared asymmetry written into the delivery doc.

### Phase 4: The sweep

- Fixture corpus first, watched failing against a dirty fixture; then the sweep until the corpus
  passes; then the CI wiring, mutation-tested.
