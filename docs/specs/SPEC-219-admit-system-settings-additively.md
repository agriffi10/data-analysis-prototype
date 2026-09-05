# Spec: Admit `system_settings/` Additively

**ID:** SPEC-219
**Status:** Draft
**Last Updated:** 2026-09-05
**Depends On:** SPEC-218

## Overview

Three folders the app fills for the user — `athenaresults/`, `archive/` (the receipt folder) and
`shared_tables/` — are moving from a space's root to a real `system_settings/` prefix beneath it
([ARCS.md](ARCS.md), *System-settings prefix arc*). For two of the three, what makes the folder
uneditable **is** an IAM Deny keyed on the literal path (`shared_tables/` carries none), and for all
three, what keeps a user from pasting into, deleting or archiving one is a rule in the browser and
on every plane that compares a key to that same path. Relocating the prefix relocates all of it at
once, and the gap between the two is a window in which the data is writable and nothing fails. This
spec closes the window before it opens: every statement and every rule learns the **new** location
as a second, equally protected home, while every write still goes to the old one. Nothing a user can
see changes, the rollback is the state we are already in, and SPEC-220 can then switch the writes
knowing both locations are already fenced.

## Scope

### In Scope

- Every IAM statement naming a moving folder in a **space** bucket gains a sibling naming the same
  folder under `system_settings/`, in the eight templates SPEC-218 pinned.
- One **plural** builder per tree beside SPEC-218's singular one — the root-anchored locations a
  folder may occupy, spelled as literals, with a second home **only for a member of the moving set**
  — and every rule that tests a key against a root-anchored prefix goes through it, so both homes
  are refused, excluded or hidden exactly alike and no non-moving folder acquires a phantom home.
  The singular builder, which is where writes go, is untouched.
- `system_settings` itself joins the reserved sets on both sides: never a paste target, never
  deletable or renamable, never an archive source, never a data-quality target.
- Proof that the new Denies are in force before anything is written there.

### Out of Scope

- **Any change to a path a write produces.** `app_managed_prefix` / `appManagedPrefix` still resolve
  to the depth-one string; SPEC-220 flips them. A criterion asserts the singular builders are
  byte-for-byte unchanged.
- **Copying, moving or deleting any object**, and re-pointing any Glue `LOCATION`. SPEC-220.
- **Deleting the `system_settings` group row.** It keeps standing in for the three unmoved folders
  until the folder is real; `SystemFolderGroupRow.tsx`, the partition and their tests are untouched,
  and `systemFolders.ts` changes exactly one declaration into an alias (FR-003).
- **Narrowing anything.** No statement, rule or list loses a member here. The narrowing is
  SPEC-220's second merge, after the live checks, while this spec's state is still the rollback.
- **A second home for any non-moving folder.** `user_settings/`, `saved_queries/`,
  `_data-quality-reports/` and `system_settings` itself sit in the same lists as the moving three;
  the plural builder returns them exactly one location, so no rule ever refuses or excludes
  `alice/system_settings/user_settings/` or `alice/system_settings/system_settings/`.
- **File-send's exclusion set.** The send plane excludes only `athenaresults/` and `user_settings/`
  from an expansion, and receipts and shared tables are sendable by design; `system_settings` does
  **not** join `_PORTAL_MANAGED_FOLDERS`, because after the move that would make receipts
  unsendable, which is a narrowing. Only the results folder's second home is excluded.
- **The admin bucket's `archive/*` statements** (`archive/policies/execution`, `sfn-permissions`) —
  fact 3 of the word, which does not move and must not gain a sibling.
- **The FIFO vault segment** (`VAULT_ARCHIVE_SEGMENT`), which addresses the archive bucket and is
  hashed into group ids pinned by golden vectors.
- **Lake Formation.** Both data-location registrations are bucket-wide, so a deeper prefix inside
  the same bucket needs no grant; FR-001 asserts that from the Terraform rather than assuming it.

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

**The shape of a sibling is fixed by the tests that read the templates as text.** In the three
portal-role templates (`analytics`, `data`, `shared-spaces`) a sibling is its **own statement**, with
the original Sid suffixed `SystemSettings` and a single-string Resource — because
`archiveWriteLock.test.ts` builds its matcher from one Sid's single-string Resource and says so. In
the five plane execution templates, whose Resources are already arrays, a sibling is a new array
element beside the old one.

**Two existing guards pin these templates and must be re-baselined by this spec, with the argument
written down.** `lambdas/test_portal_role_preservation.py` byte-compares the portal-role templates
against `BASELINE_COMMIT` under an `ACCEPTED_` test whose docstring says the spec making a change
moves the baseline forward with a note, and pins the set of Sids each template gained since that
baseline (`{"ListTheSharedDocuments"}` for the user-space template, none for the shared-space one).

#### Acceptance Criteria:

- [ ] `SEGMENT` in the population test captures the anchoring segment **before** `system_settings`
      as well — `(?<=["/])([^/"\s]+)/((?:system_settings/)?)(athenaresults|archive|shared_tables)/` or
      equivalent — so a personal sibling measures as `username}/system_settings/archive` and a shared
      one as `*/system_settings/archive`, and a sibling written with the wrong anchor is
      distinguishable from the right one. The expected table gains, for every one of the eight
      files, one such pair beside each existing pair; the two admin-bucket entries are unchanged; the
      test fails when any one sibling is removed (plant one, watch it name the file, revert).
- [ ] For the seven templates carrying no `%{ … }` directive, a test renders each with placeholder
      values, parses the JSON, and for every statement whose Resource names an old-anchor path finds
      a statement with an equal `Effect` and equal `Action` set naming the new-anchor path; a sibling
      with a narrower action list fails it. The eighth, `shared-spaces/policies/portal-role-shared-space.json.tftpl`,
      carries `%{ for }` loops and is checked as text, the way `archiveWriteLock.test.ts` already
      checks it: each old-anchor Sid has a `…SystemSettings` sibling with the same Effect and Action
      lines.
- [ ] `archiveWriteLock.test.ts`'s personal matcher becomes the union of
      `ArchiveReceiptsAreNotUserWritable` and `ArchiveReceiptsAreNotUserWritableSystemSettings`, its
      vector table gains `alice/system_settings/archive/` rows, and the browser predicate (FR-003)
      agrees with the IAM side on every row, old and new.
- [ ] `test_portal_role_preservation.py`: `BASELINE_COMMIT` moves to the commit that lands the
      siblings, with the note the docstring asks for; the gained-Sid expectations become
      `{"ListTheSharedDocuments", "ArchiveReceiptsAreNotUserWritableSystemSettings"}` for the
      user-space template and the exact new Sid set for the shared-space and analytics ones; the test
      stays `ACCEPTED_`, and nothing else in it changes.
- [ ] `checkov -f plan.json` on the deploy plan reports no new unaccepted finding, or the finding is
      **scoped by check ID and resource** with a written disposition — never accepted wholesale.
- [ ] A test over `infra/modules/analytics/lakeformation.tf` and `infra/modules/shared-spaces/lakeformation.tf`
      (through `tf_blocks`) asserts each `aws_lakeformation_resource` block's `arn` is an unadorned
      bucket reference with no `/` suffix (`aws_s3_bucket.shared_space.arn`;
      `var.user_space_bucket_arn`, whose root-module argument in `infra/main.tf` is the bare bucket
      ARN and is read too). That is what makes no LF change necessary; if either ever narrows to a
      prefix, the test names it.
- [ ] The templates land in their own PR, before the rule PRs. This is a **convention**, not a
      dependency — FR-002 and FR-003 change what code refuses, not what IAM allows — kept because the
      plan scan that reads these templates runs in the deploy workflow and a finding is easier to
      scope on a diff that is only templates.

### FR-002: The fleet's location rules accept both homes

#### Description:

`cpcommon.app_managed` gains `SYSTEM_SETTINGS_FOLDER`, `MOVING_FOLDERS` (the three) and
`app_managed_prefixes(root, folder) -> tuple[str, ...]`: for a member of `MOVING_FOLDERS`,
`(f"{root}{folder}/", f"{root}system_settings/{folder}/")` — **two literals, depth-one first, neither
derived from the singular**, so that SPEC-220 can flip the singular without the plural following;
for any other name, `(f"{root}{folder}/",)`. A separate assertion pins that the first element equals
the singular **today**; SPEC-220 FR-001 deletes it. The type is `tuple[str, ...]`, not a pair:
SPEC-220's narrowing shrinks it to one element inside the owner and touches no rule.

Every rule that tests a key against a **root-anchored prefix** consults it, member or not, so the
loops over mixed lists stay uniform and the Out of Scope promise holds by construction:
`focommon.protected._is_at_or_below`'s anchored arm **and its two hand-built neighbours
`_is_root_folder` and `_is_under_root_folder`** (which build `f"{normalize_root(root)}{name}/"` from a
parameter and so were invisible to SPEC-218's sweep — a blind spot this spec records),
`fscommon.authz.assert_not_results_folder`, `fscommon.expand._excluder`, `file_ops_inspect_source`'s
excluder, `arcommon.authz.assert_not_reserved`, `arcommon.plan`'s excluder,
`apicommon.protected.is_write_locked`'s anchored arm, and `cpcommon.s3_listing._IGNORED_SUBTREES`,
which is built as `(*app_managed_prefixes("", ATHENA_RESULTS_FOLDER), "user_settings/")`. Rules that
already hold at any depth — the segment-membership checks in `focommon.delete` and
`arcommon.plan._assert_deletable_folder`, the shared-bucket arms of `_is_at_or_below` and
`is_write_locked`, and `dq_validate_authorize`'s first-segment test — are **not** re-pointed; they
are asserted against the new home with a pair test and, for data quality, extended by list.

#### Acceptance Criteria:

- [ ] `app_managed_prefixes("alice/", "archive") == ("alice/archive/", "alice/system_settings/archive/")`,
      `app_managed_prefixes("alice/", "user_settings") == ("alice/user_settings/",)`,
      `app_managed_prefixes("alice/", "system_settings") == ("alice/system_settings/",)`; it normalizes
      nothing (an empty root and a slash-carrying root come back as handed); `MOVING_FOLDERS` is
      exactly the three names — all asserted as literals.
- [ ] A separate test asserts `app_managed_prefixes(r, f)[0] == app_managed_prefix(r, f)` for every
      member today, and its docstring says SPEC-220 FR-001 deletes it when the singular moves.
- [ ] For every rule named above, re-pointed or not, a test asserts the SAME refusal code or
      exclusion for a key under the old home and one under the new, written as a parametrised pair
      over the two prefixes so they cannot drift: `alice/archive/r.txt` and
      `alice/system_settings/archive/r.txt` are both `archive_read_only`; a paste to
      `alice/system_settings/shared_tables/` is refused by `destination_refusal` as the plane's
      picker-lock (`_is_root_folder` re-pointed), and a move of `alice/system_settings/athenaresults/`
      by `source_refusal` (`_is_under_root_folder` re-pointed);
      `finance/system_settings/athenaresults/q.csv` is not sendable; a selection containing
      `alice/system_settings/` is refused as `reserved_folder`; a file-ops expansion of a space root
      lists neither `athenaresults/` home and still lists `alice/user_settings/` as excluded exactly
      once; `is_write_locked` is true for `alice/system_settings/archive/receipt.txt` and for
      `finance/x/system_settings/archive/y` in a shared space, and still false for
      `alice/reports/archive/old.csv` in a personal one.
- [ ] `dqcommon.RESERVED_PREFIXES` gains `system_settings`, so a check whose first segment is the
      new prefix is refused with the same `FORBIDDEN` reason as one under `athenaresults` today —
      asserted by name.
- [ ] `RESERVED_SOURCE_ROOTS`, `PICKER_LOCKED_FOLDERS` and `UNDELETABLE_ROOT_FOLDERS` gain
      `system_settings`, and `_IGNORED_SUBTREES` is `("athenaresults/", "system_settings/athenaresults/", "user_settings/")`;
      each per-list literal assertion from SPEC-218 is updated to the new exact membership, and no
      other member moves.
- [ ] The sweep learns the new prefix as a **folder name**: `system_settings` joins the names rules
      (a) and (b) flag and the two TypeScript literal/template regexes match, `SYSTEM_SETTINGS_FOLDER`
      joins `OWNER_IDENTIFIERS` with `_IDENT_TO_NAME["SYSTEM_SETTINGS_FOLDER"] = "system_settings"`,
      and `_TS_TEMPLATE_SEGMENT` is widened so `${x}system_settings/archive/` is a construction. The
      corpus gains one failing case per tree — Python `f"{root}system_settings/{folder}/"` and
      TypeScript `` `${root}system_settings/${folder}/` `` outside the owner — and the tree is clean
      after the re-pointing. The sweep's known blind spot — a prefix built from a **parameter**, as
      `_is_root_folder` did — is recorded in its module docstring as what the pair tests cover instead.
- [ ] The singular builders' values are unchanged: every SPEC-218 builder VALUE test passes
      untouched, `test_fifo_derivations.py` passes untouched, and the only expected strings that
      change in any existing test are the list memberships named above.

### FR-003: The browser's location rules accept both homes

#### Description:

`lib/appManagedPaths.ts` gains `SYSTEM_SETTINGS_FOLDER`, `MOVING_FOLDERS` and
`appManagedPrefixes(rootPrefix, folder): readonly string[]` with the same member rule and the same
literal spelling as the fleet's; `isRootFolderNamed`, `undeletableRootFolderRefusal`,
`archiveRefusal` and `isWriteLockedPrefix`'s anchored arm test against every element. The
`system_settings` name joins `PICKER_LOCKED_FOLDERS`, `UNDELETABLE_ROOT_FOLDERS` and
`ARCHIVE_RESERVED_ROOTS`, with its own refusal wording. `systemFolders.ts`'s
`SYSTEM_FOLDER_GROUP_NAME` becomes an alias of `SYSTEM_SETTINGS_FOLDER` rather than a second
declaration; the row component, the partition and their tests are untouched.

#### Acceptance Criteria:

- [ ] `appManagedPrefixes('alice/', ARCHIVE_FOLDER)` equals `['alice/archive/', 'alice/system_settings/archive/']`,
      `appManagedPrefixes('alice/', 'user_settings')` equals `['alice/user_settings/']`, and a separate
      assertion pins `appManagedPrefixes(r, f)[0] === appManagedPrefix(r, f)` for every member today,
      marked for SPEC-220 FR-001 to delete.
- [ ] `writeLockRefusal` names the same reason for `alice/archive/` and `alice/system_settings/archive/`;
      `undeletableRootFolderRefusal` returns the archive wording for both homes and a new wording for
      `alice/system_settings/` itself; the destination picker offers neither home and not
      `system_settings/`; `archiveRefusal` refuses a selection containing `alice/system_settings/` as
      an ancestor of a reserved folder, naming `system_settings`; and `isRootFolderNamed('alice/system_settings/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)`
      is **false** — the phantom home is not hidden, because it is not a home.
- [ ] The plane-mirror test in `archiveSelection.test.ts` still passes with `ARCHIVE_RESERVED_ROOTS`
      and `RESERVED_SOURCE_ROOTS` at six members each, and the literal membership assertions on
      both sides are updated to exactly six.
- [ ] `git diff` of `SystemFolderGroupRow.tsx`, `systemFolders.test.ts`, `FileListTable.tsx` and
      `FileListMobile.tsx` is empty; `systemFolders.ts` changes only the one declaration.
- [ ] Help & guides are unchanged: the text already says the folders are "gathered under
      `system_settings`", which is what a user sees before and after.

### FR-004: Nothing visible changed, and the new fence is proved live

#### Description:

This spec is invisible by construction and is asserted so; and the one thing it changes in the
account — the new Deny statements — is exercised before SPEC-220 writes there. No laptop identity
can hold the portal role (its trust policy admits only the API's execution role, and the Identity
Pool is retired), and the deploy role holds no `iam:SimulatePrincipalPolicy`, so the IAM half is
proved the way every earlier simulate in `docs/testing/owed.md` was: `iam simulate-principal-policy`
from the operator's own CLI identity against the portal role, one resource per call, with the
principal tag supplied as a context entry — under identity-only evaluation IAM substitutes the tag
into the Resource pattern, the old Denies do not match the new path, and `UserPrefixObjects` would
answer `allowed` without the sibling, so `explicitDeny` is discriminating. The route half is proved
from a signed-in session.

#### Acceptance Criteria:

- [ ] The full pytest suite, the full vitest suite and `npm run build` pass; every list membership
      assertion changes only by the addition named in FR-002/FR-003; the sweep is clean.
- [ ] Live, from a signed-in session after the templates applied: a `PUT /v1/objects/content` under
      `{root}system_settings/archive/x` is refused by the **route layer** with the same code as under
      `{root}archive/x` (the API's write lock, FR-002), recorded in `docs/testing/e2e.md`'s API
      table beside the existing `curl … {root}archive/` row.
- [ ] Live, from the operator's CLI identity: `aws iam simulate-principal-policy --policy-source-arn <portal role>
      --context-entries ContextKeyName=aws:PrincipalTag/username,ContextKeyValues=alice,ContextKeyType=string`,
      one resource per call, returns `explicitDeny` for `s3:PutObject` on
      `arn:…:{user-space bucket}/alice/system_settings/archive/x` and for `s3:DeleteObject` on
      `…/alice/system_settings/athenaresults/x`, as it does for the old paths; and `allowed` for
      `s3:PutObject` on `…/alice/system_settings/notes.txt`, the control that the Deny is not wider
      than its resource. Recorded in `docs/testing/owed.md` with the commands and the date.
- [ ] The rollback is recorded in the delivery doc as the empty change: reverting the rule PRs
      leaves the siblings inert (nothing is written there), and reverting the templates PR is a plan
      that removes statements matching nothing.

---

## Data Model

```py
# lambdas/control-plane-common/cpcommon/app_managed.py

SYSTEM_SETTINGS_FOLDER = "system_settings"
MOVING_FOLDERS = (ATHENA_RESULTS_FOLDER, RECEIPT_FOLDER, SHARED_TABLES_FOLDER)

def app_managed_prefix(root: str, folder: str) -> str: ...        # unchanged: where a write goes
def app_managed_prefixes(root: str, folder: str) -> tuple[str, ...]:
    """The root-anchored locations a folder may occupy, depth-one first, as LITERALS — never derived
    from the singular, so the singular can move without these following. Two elements for a member
    of MOVING_FOLDERS while both homes are admitted (SPEC-220 shrinks it to one); one for any other
    name. Normalizes nothing."""
```

```ts
// apps/portal/src/lib/appManagedPaths.ts

export const SYSTEM_SETTINGS_FOLDER = 'system_settings';
export const MOVING_FOLDERS = [ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER, SHARED_TABLES_FOLDER] as const;
export function appManagedPrefix(rootPrefix: string, folder: string): string;      // unchanged
export function appManagedPrefixes(rootPrefix: string, folder: string): readonly string[];
```

## File & Folder Structure

```
infra/modules/*/policies/*.json.tftpl        # the eight pinned templates gain sibling statements/elements
lambdas/test_app_managed_template_population.py   # SEGMENT captures the anchor before system_settings;
                                                  #   expected pairs doubled
lambdas/test_app_managed_template_siblings.py     # NEW — rendered Effect/Action pairs (seven), text (one)
lambdas/test_lakeformation_registrations.py       # NEW — both registrations are the bare bucket ARN
lambdas/test_portal_role_preservation.py          # BASELINE_COMMIT moved with its note; gained-Sid sets
lambdas/control-plane-common/cpcommon/app_managed.py   # SYSTEM_SETTINGS_FOLDER, MOVING_FOLDERS, app_managed_prefixes
lambdas/file-ops-common/focommon/protected.py          # _is_root_folder / _is_under_root_folder through the plural
apps/portal/src/lib/appManagedPaths.ts                 # SYSTEM_SETTINGS_FOLDER, MOVING_FOLDERS, appManagedPrefixes
scripts/validate_app_managed_paths.py                  # system_settings as a folder name; the blind spot recorded
docs/testing/e2e.md · docs/testing/owed.md             # one row each (FR-004)
```

## Implementation Phases

### Phase 1: The templates (their own PR, by convention first)

- Sibling statements and elements in the eight templates; `SEGMENT` widened and the population
  test's expectations doubled; the siblings test; the LF registration test; the preservation test
  re-baselined with its note; the Checkov plan scan read and any finding scoped.

### Phase 2: The fleet reads both

- `SYSTEM_SETTINGS_FOLDER`, `MOVING_FOLDERS`, `app_managed_prefixes` and the today-equality test;
  the anchored rules re-pointed, the two hand-built ones included; the lists and `_IGNORED_SUBTREES`
  gain their members; parametrised old/new pair tests for every rule; the sweep taught the name and
  the blind spot, plus its two corpus cases.

### Phase 3: The browser reads both

- `appManagedPrefixes` and the today-equality assertion; the four predicates; the three lists and
  the new wording; the alias; the mirror test at six; the phantom-home negative.

### Phase 4: The live checks

- The route-layer refusal from a signed-in session; the simulate runs from the operator's CLI
  identity with the positive control; the rollback sentence in the delivery doc.
