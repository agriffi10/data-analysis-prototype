# Completed Spec — SPEC-246: Archive and Restore Get Their Own Kill Switch

## What was completed?

- **An eighth flag key, `archive`, the second kill switch** (#881). Published `false`, it withdraws
  every entry point that starts an archive or a restore: Archive in the selection toolbar and in
  both details panels, and Restore Archived Data on the toolbar and in the mobile action bar. The
  archive guide leaves Help too. Default on, so an unreadable document never withdraws it. The
  controls' gate is one clause in `FileBrowser.tsx` (`archiveSwitchOn`, feeding `archiveEnabled` and
  `restoreEnabled`), and the guide's is its registry row; no archive service, hook or dialog reads a
  flag, and the routes stay live and ungated.
- **The key in all eight places a key lives**: `FeatureFlagKey`, `FEATURE_FLAG_KEYS` (last),
  `FEATURE_FLAG_DEFAULTS`, `config/feature-flags.json`, the validator's `FLAG_KEYS`, the restated
  Python tuple, `GATED_SURFACES`, and `useVisibleHelpSections`' total map.
- **Four `archive` registry rows**, walked in both states, beside the unchanged `files` rows for the
  same surfaces — one row per (surface, flag). Their names are descriptions, because a name keys the
  walk's recipes; `GatedSurface.name` now says a name may be either.
- **A `featureFlags` option on `renderWithProviders`**, seeding a partial set over the all-on
  defaults, and refusing to be passed beside `seedFeatureFlags: false`.
- **The record.** The taxonomy says two kill switches everywhere it is stated. There is a register
  entry, *Archive and restore get their own kill switch*, and superseded markers in `ARCS.md` (twice)
  and SPEC-172. `apps/portal/info/runtime-configuration.md` gains an operator's "Throwing a switch"
  section, and `e2e.md` §4.14 the `archive` sitting.

### Deliberate deviations

- **Four PRs, not one.** Publish Config can only publish `main`'s document — the deploy role trusts
  `refs/heads/main` and pull requests only — so the sitting was a merge to throw the switch (#882)
  and a merge to set it back (#883), plus this close. The queue lock was held across #882 and #883
  so no other merge could move the image between them.
- **The sitting's "Copy, Move and Delete still work on a file" was not attempted.** Driving a
  confirm or a delete in the live app needed Andrew's per-action approval while the switch was off.
  The three controls were observed present and not disabled with the switch off; the functional
  run is owed (`docs/testing/owed.md`, *SPEC-246's `archive` sitting*).
- **FR-004's "when it takes effect" wording was corrected while building**: an open session re-reads
  a stale document whenever something mounts a flag reader — a page change or a dialog, drawer or
  panel that reads one — not only on "the next navigation", and a folder click inside Files is
  neither. The spec's AC was amended in place.
- **Beyond the spec's list**: the stale "five places" count in `runtime-configuration.md`, an
  unmarked second copy of the superseded one-row-per-flag claim in `ARCS.md`, a pointer paragraph in
  `e2e.md` §4.11, and the test harness option above (which the spec's two new test sites needed).

## What changed from earlier specs?

- SPEC-172's "it inherits the Files flag" is superseded: archive and restore are registered under
  both `files` and `archive`.
- SPEC-190's register sentence that one control cannot hold a row under two flags is superseded —
  the second row takes a description, as `Explore data` had already done.

## Verification

Locally, by exit code: Prettier, ESLint, `npm run build`, the portal suite, `pytest lambdas/`,
mypy, ruff, and everything `ci.yml` runs on a branch. The FR-003 mutation pair and a harness-guard
plant each reddened exactly the tests they should. Two diff reviews ran before #881's push, and two
more on #882/#883 together. FR-005 AC2 is the push runs on `a6a03e09`; AC3–AC5 ran live on
2026-09-26, all passing except the not-attempted step above, on one image, `a6a03e09` —
`docs/testing/sessions.md`.
