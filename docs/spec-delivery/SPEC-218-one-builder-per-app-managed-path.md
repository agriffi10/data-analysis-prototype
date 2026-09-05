# Completed Spec — SPEC-218: One Builder Per App-Managed Path

## What was completed?

Nothing a user can see, and no path value changed. Three folders — `athenaresults/`, `archive/`
(the receipt folder) and `shared_tables/` — are about to move under a real `system_settings/`
prefix, and what breaks such a move is **depth**: nearly every rule about them was anchored at depth
one as `{root}{name}/`, in four browser modules and eleven fleet modules, and at depth two each
would stop matching silently. This spec made that move one edit per tree.

- **`apps/portal/src/lib/appManagedPaths.ts`** — the three names and `appManagedPrefix(rootPrefix,
  folder)`; `protectedFolders.ts`, `systemFolders.ts`, `archiveSelection.ts` and
  `writeLockedPrefix.ts` build through it. `fileBrowser.constants.ts` no longer declares
  `ARCHIVE_FOLDER`. In `lib/` because two features consume it and the archive feature imports
  nothing from another feature.
- **`cpcommon/app_managed.py`** — `ATHENA_RESULTS_FOLDER`, `RECEIPT_FOLDER`, `SHARED_TABLES_FOLDER`,
  `VAULT_ARCHIVE_SEGMENT`; `app_managed_prefix` plus per-fact wrappers and `vault_archive_prefix`.
  **No builder normalizes** — each caller keeps its own `normalize_root`, so every produced string
  (the FIFO group id included) is byte-identical to before. Re-pointed: `arcommon` (`config`,
  `paths`, `authz`, `plan`), `focommon` (`config`, `protected`), `fscommon` (`config`, `authz`,
  `expand`), `dqcommon.config`, `cpcommon` (`results`, `s3_listing`), `apicommon` (`fifo`,
  `protected`), `api/routes/athena.py`, `file_ops_inspect_source.py`,
  `table_share_check_target_absent.py`.
- **`archive` is three facts** (FR-003): `RECEIPT_FOLDER` (space bucket, **moves**) and
  `VAULT_ARCHIVE_SEGMENT` (Glacier vault key segment, hashed into FIFO ids, stays) in `cpcommon`;
  `arcommon.plan.PREFIX` (admin-bucket scratch, stays) left in its domain layer. The call sites
  that used to read one overloaded constant: `arcommon/paths.py` `archive_root` (fact 2) and
  `receipt_root` (fact 1); `apicommon/fifo.py` (fact 2, was its own `ARCHIVE_FOLDER`);
  `apicommon/protected.py` (fact 1, was its own `ARCHIVE_FOLDER`). `focommon.config.ARCHIVE_FOLDER`
  survives as a re-export of `RECEIPT_FOLDER`, so its call sites and tests are unchanged. The `.tf` literal
  `infra/modules/analytics/s3.tf` `prefix = "archive/"` is the lifecycle rule for **fact 3 and must
  not move**. `test_archive_facts_arcommon.py` pins all three equal today (`ACCEPTED_`).
- **`lambdas/test_app_managed_template_population.py`** — the eight `.tftpl` files naming a moving
  folder in a space bucket, per file, per folder and per anchoring segment (so a path replaced in
  place reddens it), spelled as literals; and separately the two
  naming the admin bucket's `archive/*` (`archive/policies/execution`, `archive/policies/sfn-permissions`),
  which must not gain a sibling. An earlier draft said nine: `sfn-permissions` names fact 3 only.
- **`scripts/validate_app_managed_paths.py`** + its corpus, two unconditional steps in `ci.yml`.
  Python by AST (a folder-name constant with or without slashes, an f-string or concatenation
  building the prefix from a literal or an imported name, a module-level `"archive"`, `"archive"`
  beside another managed name in a collection); TypeScript by regex over source with comments and
  regex literals stripped, a bare `'archive'` refused only beside another managed name or as a
  module-level `const`. Owners: the two modules above plus `arcommon/plan.py`. 35 corpus cases;
  24 mutations of the sweep and the wiring each reddened it. Not covered, deliberately:
  `"/".join`, `%` and `.format` constructions, none of which exist in the tree.

### Deliberate deviations

- The owner module is `cpcommon/app_managed.py`, not the spec's `cpcommon/paths.py` — that file
  already existed and holds containment only. The SPA owner is in `lib/`, not `features/file-browser/`.
- Rule (a) of the sweep needs no docstring exclusion: it matches a constant EQUAL to the name, so
  prose is never flagged. The exclusion was written, found unreachable by mutation, and removed.

## What changed from earlier specs?

- `archiveSelection.test.ts`'s plane-mirror extractor resolves identifiers against the owner module
  and fails on one it cannot resolve; the property (value-set equality) is unchanged.
- `ci.yml`'s `SCOPE_PATTERNS` gained `cpcommon/app_managed.py`, which the browser suite now reads.
- `cpcommon.s3_listing._IGNORED_SUBTREES` builds its results entry through the builder with an EMPTY
  root, because the remainder it matches is listing-relative; it moves when the builder does.
  `dq_validate_authorize`'s first-segment rule does not and is on 220's hunt list.

## What 219 needs from this

Shared-space Denies are written `${shared_space_bucket_arn}/*/athenaresults/*`, and an S3 resource
`*` matches `/`, so they keep matching after the move. The personal ones are anchored at
`${aws:PrincipalTag/username}/` and stop matching entirely — **the unprotected window at cutover is
personal-space-only**, and the statements it turns on are `ResultsNoDelete`
(`analytics/policies/portal-role-analytics.json.tftpl`) and `ArchiveReceiptsAreNotUserWritable`
(`data/policies/portal-role-permissions.json.tftpl`). `UserSettingsNoDelete` beside the first guards
a folder that does not move. `shared_tables/` carries no Deny anywhere. (The spec's FR-004 named the
wrong file and the wrong pair; corrected in both places at close.)

## Verification

Locally by exit code: ruff, mypy, `pytest lambdas/` (2498 passed, coverage 89.5%), Prettier, ESLint,
vitest (2422 passed), `npm run build`, `validate_docs.py`, the sweep (clean) and its corpus (35
cases), 24/24 mutations caught. Nothing deployed changes; no live check is owed.
