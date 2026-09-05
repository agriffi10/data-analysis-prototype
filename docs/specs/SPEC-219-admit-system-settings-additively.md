# Spec: Admit `system_settings/` Additively

**ID:** SPEC-219
**Status:** Draft
**Last Updated:** 2026-09-05
**Depends On:** SPEC-218

## Overview

Three folders the app fills for the user — `athenaresults/`, `archive/` (the receipt folder) and
`shared_tables/` — are moving from a space's root to a real `system_settings/` prefix beneath it
([ARCS.md](ARCS.md), *System-settings prefix arc*). What makes those folders uneditable today **is**
an IAM Deny keyed on the literal path, and what keeps a user from pasting into, deleting or archiving
one is a rule in the browser and on every plane that compares a key to that same path. Relocating
the prefix relocates all of it at once, and the gap between the two is a window in which the data is
writable and nothing fails. This spec closes the window before it opens: every statement and every
rule learns the **new** location as a second, equally protected home, while every write still goes
to the old one. Nothing a user can see changes, the rollback is the state we are already in, and
SPEC-220 can then switch the writes knowing both locations are already fenced.

## Scope

### In Scope

- Every IAM statement naming a moving folder in a **space** bucket gains a sibling naming the same
  folder under `system_settings/`, in the eight templates SPEC-218 pinned.
- One **plural** builder per tree beside SPEC-218's singular one — the locations a folder may
  occupy — and every rule that *tests* a location goes through it, so both homes are refused,
  excluded or hidden exactly alike. The singular builder, which is where writes go, is untouched.
- `system_settings` itself joins the reserved sets on both sides: never a paste target, never
  deletable or renamable, never an archive or send source, never a data-quality target.
- A live check that the new Deny is in force before anything is written there.

### Out of Scope

- **Any change to a path a write produces.** `app_managed_prefix` / `appManagedPrefix` still resolve
  to the depth-one string; SPEC-220 flips them. A criterion asserts the singular builders are
  byte-for-byte unchanged.
- **Copying, moving or deleting any object**, and re-pointing any Glue `LOCATION`. SPEC-220.
- **Deleting the `system_settings` group row.** It keeps standing in for the three unmoved folders
  until the folder is real.
- **Narrowing anything.** No statement, rule or list loses a member here. The narrowing is
  SPEC-220's second merge, after the live checks, while this spec's state is still the rollback.
- **The admin bucket's `archive/*` statements** (`archive/policies/execution`, `sfn-permissions`) —
  fact 3 of the word, which does not move and must not gain a sibling.
- **The FIFO vault segment** (`VAULT_ARCHIVE_SEGMENT`), which addresses the archive bucket and is
  hashed into group ids pinned by golden vectors.
- **Lake Formation.** Both data-location registrations are bucket-wide
  (`analytics/lakeformation.tf`, `shared-spaces/lakeformation.tf`), so a deeper prefix inside the
  same bucket needs no grant; a criterion records that reading rather than assuming it.

---

## Functional Requirements

### FR-001: Every space-bucket statement gains its `system_settings/` sibling

#### Description:

`lambdas/test_app_managed_template_population.py` pins, per template, the `<anchor>/<folder>`
pairs naming a moving folder in a space bucket: eight files. Each such Resource gains a sibling
naming `<anchor>/system_settings/<folder>/` with the same actions and effect — an Allow that lets a
plane or Athena read and write there later, a Deny that already refuses what the old Deny refuses.
The shared-space Denies are written `*/archive/*` and an S3 `*` matches `/`, so they already cover
the new depth; they still gain an explicit sibling, because "covered by a wildcard" is a fact about
S3 that no test here can see and the narrowing must be able to remove the *old* form without
re-deriving it. The two personal-space Denies that matter most — `ResultsNoDelete`
(`analytics/policies/portal-role-analytics.json.tftpl`) and `ArchiveReceiptsAreNotUserWritable`
(`data/policies/portal-role-permissions.json.tftpl`) — are anchored at the principal tag and match
nothing under the new prefix until this lands.

#### Acceptance Criteria:

- [ ] The population test's expected table gains, for every one of the eight files, a
      `<anchor>/system_settings/<folder>` pair beside each existing `<anchor>/<folder>` pair; the two
      admin-bucket entries are unchanged; the test passes against the edited templates and fails
      when any one sibling is removed (plant one, watch it name the file, revert).
- [ ] Each sibling carries the same `Effect` and `Action` list as the statement it mirrors — asserted
      by a test that renders each template with placeholder values, parses the JSON, and for every
      statement whose Resource names an old-anchor path finds a statement with an equal Effect and
      Action set naming the new-anchor path. A sibling with a narrower action list fails it.
- [ ] `archiveWriteLock.test.ts`'s matcher over the rendered personal and shared Deny statements
      passes for BOTH `alice/archive/x` and `alice/system_settings/archive/x`, and the browser's
      predicate (FR-003) agrees on both.
- [ ] `checkov -f plan.json` on the deploy plan reports no new unaccepted finding, or the finding is
      **scoped by check ID and resource** with a written disposition — never accepted wholesale.
- [ ] The grants land in **their own PR**, merged and applied green, before the PR that changes any
      rule to read the new location (the deploy-role rule for anything IAM).
- [ ] A criterion records, from reading `infra/modules/analytics/lakeformation.tf` and
      `infra/modules/shared-spaces/lakeformation.tf`, that both data-location registrations are the
      whole bucket, so no LF grant changes for a deeper prefix.

### FR-002: The fleet's location rules accept both homes

#### Description:

`cpcommon.app_managed` gains `app_managed_prefixes(root, folder)`, returning the tuple of prefixes
the folder may occupy — today `({root}{folder}/, {root}system_settings/{folder}/)` — and every rule
that *tests* whether a key is in, under or containing an app-managed folder consults it. The rules
today: `focommon.protected._is_at_or_below` (destination and source refusals),
`fscommon.authz.assert_not_results_folder`, `fscommon.expand._excluder`,
`file_ops_inspect_source`'s excluder, `arcommon.authz.assert_not_reserved`,
`arcommon.plan`'s excluder and `_assert_deletable_folder`, `focommon.delete`'s any-depth rule,
`apicommon.protected.is_write_locked`, `cpcommon.s3_listing._IGNORED_SUBTREES`, and
`dq_validate_authorize`'s first-segment refusal. The singular builder is where a write goes and is
not touched.

#### Acceptance Criteria:

- [ ] `app_managed_prefixes(root, folder)` exists, returns exactly the two prefixes in that order,
      normalizes nothing (an empty root and a slash-carrying root come back as handed), and its
      first element equals `app_managed_prefix(root, folder)` — asserted.
- [ ] For every rule above, a test asserts the SAME refusal code or exclusion for a key under the
      old location and a key under the new one, written as a parametrised pair over the two prefixes
      so the two cannot drift: `alice/archive/r.txt` and `alice/system_settings/archive/r.txt` are
      both `archive_read_only`; `finance/system_settings/athenaresults/q.csv` is not sendable; a
      selection containing `alice/system_settings/` is refused as `reserved_folder`; a file-ops
      expansion of a space root lists neither `athenaresults/` home.
- [ ] `dqcommon.RESERVED_PREFIXES` gains `system_settings`, so a check whose first segment is the
      new prefix is refused with the same `FORBIDDEN` reason as one under `athenaresults` today —
      asserted by name.
- [ ] `RESERVED_SOURCE_ROOTS`, `PICKER_LOCKED_FOLDERS` and `UNDELETABLE_ROOT_FOLDERS` gain
      `system_settings`; each per-list literal assertion from SPEC-218 is updated to the new exact
      membership, and no other member moves.
- [ ] `apicommon.protected.is_write_locked` is true for `alice/system_settings/archive/receipt.txt`
      and for a nested `finance/x/system_settings/archive/y` in a shared space, and still false for
      `alice/reports/archive/old.csv` in a personal one.
- [ ] `scripts/validate_app_managed_paths.py` recognises `app_managed_prefixes` as an owner export
      (its imported-name rules neither flag a call to it nor a constant beside it) and the tree is
      still clean; the corpus gains one case that a hand-built `f"{root}system_settings/{name}/"`
      outside the owner is refused as a construction.
- [ ] Every string the singular builders produce is unchanged: the SPEC-218 builder tests pass
      untouched, `test_fifo_derivations.py` passes untouched, and no test's expected strings change.

### FR-003: The browser's location rules accept both homes

#### Description:

`lib/appManagedPaths.ts` gains `appManagedPrefixes(rootPrefix, folder)`, and `isRootFolderNamed`,
`undeletableRootFolderRefusal`, `archiveRefusal` and `isWriteLockedPrefix` test against both. The
`system_settings` name joins `PICKER_LOCKED_FOLDERS`, `UNDELETABLE_ROOT_FOLDERS` and
`ARCHIVE_RESERVED_ROOTS`, with its own refusal wording. The group row is unchanged.

#### Acceptance Criteria:

- [ ] `appManagedPrefixes('alice/', ARCHIVE_FOLDER)` is `['alice/archive/', 'alice/system_settings/archive/']`
      and its first element equals `appManagedPrefix('alice/', ARCHIVE_FOLDER)` — asserted.
- [ ] `writeLockRefusal` names the same reason for `alice/archive/` and `alice/system_settings/archive/`;
      `undeletableRootFolderRefusal` returns the archive wording for both, and a new wording for
      `alice/system_settings/` itself ("The folders the app manages for you live here…"); the
      destination picker offers neither home and not `system_settings/`; `archiveRefusal` refuses a
      selection containing `alice/system_settings/` as an ancestor of a reserved folder.
- [ ] The plane-mirror test in `archiveSelection.test.ts` still passes: `ARCHIVE_RESERVED_ROOTS` and
      `RESERVED_SOURCE_ROOTS` agree, now six members each, spelled as literals on both sides.
- [ ] `partitionSystemFolders` still groups only the three depth-one folders and lets a real
      `system_settings/` folder through as an ordinary row — asserted, because a listing that
      collapsed the real folder into the row standing in for it would show the folder twice.
- [ ] Help & guides are unchanged: the text already says the folders are "gathered under
      `system_settings`", which is what a user sees before and after.

### FR-004: Nothing visible changed, and the new fence is proved live

#### Description:

This spec is invisible by construction and is asserted so; and the one thing it changes in the
account — the new Deny statements — is exercised against the account before SPEC-220 writes there.

#### Acceptance Criteria:

- [ ] The full pytest suite, the full vitest suite and `npm run build` pass; every list membership
      assertion is updated only by the addition of `system_settings`; the sweep is clean.
- [ ] Live, from a signed-in session after the grants applied: a `PUT /v1/objects/content` under
      `{root}system_settings/archive/x` is refused by the **route layer** with the same code as under
      `{root}archive/x` (the API's write lock, FR-002), recorded in `docs/testing/e2e.md`'s archive
      section beside the existing row.
- [ ] Live, with the portal role's own credentials (a CLI check, `docs/testing/owed.md` if it cannot
      run from a browser session): `aws s3api put-object` to `{user}/system_settings/archive/x` in
      the user-space bucket is `AccessDenied`, as it is for `{user}/archive/x`; and to
      `{user}/system_settings/athenaresults/x` a `delete-object` is `AccessDenied`. A Deny that is
      only read off a plan is not proved.
- [ ] The rollback is the empty change: reverting the rule PRs leaves the templates' siblings inert
      (nothing is written there), and reverting the grants PR is a plan that removes statements
      matching nothing — recorded in the delivery doc so SPEC-220 knows what "the rollback still
      works" means.

---

## Data Model

```py
# lambdas/control-plane-common/cpcommon/app_managed.py

SYSTEM_SETTINGS_FOLDER = "system_settings"

def app_managed_prefix(root: str, folder: str) -> str: ...        # unchanged: where a write goes
def app_managed_prefixes(root: str, folder: str) -> tuple[str, str]:
    """The locations a folder may occupy, the write location first. Normalizes nothing."""
```

```ts
// apps/portal/src/lib/appManagedPaths.ts

export const SYSTEM_SETTINGS_FOLDER = 'system_settings';
export function appManagedPrefix(rootPrefix: string, folder: string): string;      // unchanged
export function appManagedPrefixes(rootPrefix: string, folder: string): readonly [string, string];
```

## File & Folder Structure

```
infra/modules/*/policies/*.json.tftpl        # the eight pinned templates gain sibling Resources
lambdas/test_app_managed_template_population.py   # expected pairs doubled; a rendered-statement
                                                  #   test compares Effect/Action across each pair
lambdas/control-plane-common/cpcommon/app_managed.py   # SYSTEM_SETTINGS_FOLDER, app_managed_prefixes
apps/portal/src/lib/appManagedPaths.ts                 # SYSTEM_SETTINGS_FOLDER, appManagedPrefixes
scripts/validate_app_managed_paths.py                  # the plural builder is an owner export
docs/testing/e2e.md · docs/testing/owed.md             # one row each (FR-004)
```

## Implementation Phases

### Phase 1: The grants (its own PR, applied first)

- Sibling Resources in the eight templates; the population test's doubled expectations; the
  rendered Effect/Action pair test; the LF reading recorded.
- Checkov plan scan measured; any new finding scoped.

### Phase 2: The fleet reads both

- `SYSTEM_SETTINGS_FOLDER`, `app_managed_prefixes`; every location rule re-pointed; the three lists
  gain the member; parametrised old/new pair tests; the sweep taught the plural export, plus its
  corpus case.

### Phase 3: The browser reads both

- `appManagedPrefixes`; the four predicates; the three lists and the new wording; the group-row
  assertion; the mirror test.

### Phase 4: The live checks

- The route-layer refusal from a signed-in session; the CLI Denies; the rollback recorded.
