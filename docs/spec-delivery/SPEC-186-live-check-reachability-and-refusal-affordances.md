# Completed Spec — SPEC-186: Live-Check Reachability, Refusal Affordances & Observability Fields

## What was completed?

All ten FRs on one branch (user decision — no SPEC-187 split). Three strands: making owed live
checks *possible*, announcing refusals *before* the user commits, and a reuse pass that gave four
drifting patterns one home each.

- **`lib/cx.ts`** returns `undefined` rather than `''` when nothing is truthy, and `Modal` treats an
  empty `className` as absent. Nine `FormDialog`s that passed neither `className` nor `scrollBody`
  were handing `Modal` an empty string, losing `max-w-md` to the panel's `w-full`.
- **`protectedFolders.undeletableSelectionRefusal`** + `SelectionToolbar`'s two new reasons, and
  `ConfirmDialog.confirmDisabledReason` (used by `RefreshTableDialog`).
- **`features/user-directory/comboboxPlacement.ts`** — `listPlacement()`, a pure function over the
  field's box and the box that *clips* it; `UsernameCombobox` walks to its nearest scrollable
  ancestor, caps the list to fit, and scrolls the active option into the visible region.
- **`shared-space-acknowledge-membership`** fans the promoted roster out to every member's cache
  (`cache.write_roster_to_all`) instead of the owner's projection alone, wrapped so it cannot fail
  an already-committed registry write. **`features/shared-spaces/memberStatus.ts`** closes the
  window before that lands.
- **`components/Chip.tsx`** (`Chip` + `ChipList`), **`components/StatusPill.tsx`**,
  **`components/fieldStyles.ts`** (`FIELD_LABEL`, `FIELD_HINT`, `SECTION_CAPTION`) and
  **`components/dialogChrome.ts`** (`DIALOG_PANEL`, `DIALOG_TITLE`), plus
  `components/sharedPrimitives.guard.test.ts` — a `?raw` glob sweep asserting one home per shape.
- **`cpcommon.observability._build_version()`** reads a `BUILD_VERSION` file shipped in the package;
  `ENV_NAME` now ships on **every** Lambda (was two modules).
- **`infra/modules/verification/`** — a CloudTrail trail over the archive vault's object-level
  events and a read-only role, with its Lake Formation half granted in `modules/analytics`.
- **Three corrected live-check scripts** — the saved-queries one (new) and corrections to the
  table-builder and Data Explorer ones. All three were folded into `docs/testing/e2e.md` and
  `docs/testing/owed.md` on 2026-08-18.

## The decisions worth carrying

Full entries in `docs/decisions/` → *A default that an empty string can defeat is not a default
(SPEC-186)*. The five that reach outside this spec:

### `??` does not fall back on `''`, and a helper that returns `''` is a trap for every consumer

Nine dialogs at full viewport width came from one line. The fix is in the shared layer twice over —
`cx` returns `undefined` (so the trap is gone for the *next* `??` consumer) and `Modal` uses `||`
(so a caller composing its own string is still safe). Widening `cx`'s return type to
`string | undefined` type-checked at every call site with no change; the two that wanted a string
already coerced with `|| undefined`.

### A refusal announced after the confirm is worse than no affordance at all

The service always refused deleting `saved_queries/` — but only after the user read *"Delete the
folder … and everything inside it? This can't be undone."* and pressed Delete. The most alarming
confirm in the app, shown for an action that was never possible. `Button.disabledReason` swallows
the click, so "no confirm is reachable" falls out of the mechanism rather than needing a second
guard. The test asserts **`alertdialog`**, not `dialog` — querying the wrong role would have passed
whatever happened, which is the assertion's whole point.

### jsdom has no layout, so a containment property must be arithmetic

FR-003's AC asked for a numeric assertion (`listbox.bottom <= dialog.bottom`). Every rect in jsdom
is zero, so the geometry moved into `listPlacement()` and the test derives the list's far edge from
the returned placement and compares it with the clip — over the measured 1400x900 case, and over a
sweep of every field position in a 600px dialog. The component test asserts only the half the DOM
can see: that the bound is a *measurement* and not the old fixed `max-h-60`.

### The roster and the connections row disagreed because the fan-out list was missing one verb

SPEC-073's acknowledge wrote the **owner's** projection; SPEC-075's fan-out ran on add/remove/leave.
Neither is wrong, and the composition left every member's copy — including the acknowledging
member's own — frozen at add time, so a member read `Pending` about themselves under a sentence
saying that means they had not signed in. The fix is one line in the verb plus a guard: the registry
write is the consistency point, so a cache failure afterwards must not fail the run — a retry finds
the member already acknowledged, no-ops, and would never write the caches at all.

### A build stamp belongs to the artefact, not to the environment map

`BUILD_VERSION` in a Lambda's environment would either race Tofu (which owns that map, and whose
`--environment` replaces it whole) or be reverted by the next apply — and Deploy Infrastructure is
path-filtered to `infra/**`, so a Tofu-set sha would name the last *infra* commit rather than the
running code. The stamp travels in the zip instead. `ENV_NAME` is the opposite case and belongs to
Tofu: it is the deployment's identity, from the same `var.environment` the feature-flag document's
`environments` keys come from.

## What the sweep found that the spec did not

- **Seven status-pill sites, not six** — `routes/LandingPage.tsx` carried a copy whose own comment
  said "Mirrors UploadList's StatusChip".
- **22 files carrying a section caption, not 11**, across three spellings.
- **Five deliberate visual changes**, called out on SPEC-155 FR-007's precedent (the first draft
  of this doc listed two and review caught the other three — under-reporting them is exactly the
  drift the consolidation exists to stop):
  1. neutral pills gain a border (`UploadList`'s Queued/Cancelled);
  2. `QueryHistoryRow`'s neutral dot brightens `text-text-3` → `text-text-2`, now every dot is
     `bg-current`;
  3. `ConnectionsPage`'s `RolePill` goes `font-semibold` → `font-medium`;
  4. the roster's Owner tag goes `bg-surface px-2.5` → `bg-surface-2 px-2`;
  5. the data-quality `Sampled` tag gains a border.

  Seven captions also take the majority spelling (slightly bolder, dimmer or more tightly
  tracked, depending on which of the three variants they had).
- **`components/` may export only components** (react-refresh), which is why
  `displayedMemberStatus` lives in `memberStatus.ts` and the class-string constants live in
  `fieldStyles.ts` / `dialogChrome.ts` rather than beside the components that use them.

## Pattern C: the four dialogs that cannot use `FormDialog`

`StartQualityCheckDialog`, `MoveDialog`, `CopyDialog` and `SaveResultsDialog` each hand their footer
to `DestinationPicker`, which owns the confirm's label, its enabled-ness and the prefix it acts on —
so `FormDialog`, which renders its own Cancel/submit pair, would give each of them two footers, and
its Enter-to-submit contract (SPEC-155, SPEC-175 FR-004 AC8) has no meaning where the submitting
control belongs to a child. AC3 allows "cannot" as an answer provided it is written down; it is
written down in `components/dialogChrome.ts`, which also holds the class strings they were copying.

## Live checks

**Owed, and this spec's own additions to the pile are small.** FR-004 built the access that unblocks
five previously-unrunnable assertions rather than running them:

- **Saved queries, both layers** (`docs/testing/e2e.md` §4.7 and `docs/testing/owed.md` §2.1).
  Check 1 (the client-side refusal, personal
  and shared) is a two-minute browser pass; check 2 (the bucket-policy Deny) needs portal-role
  credentials via the CLI and is the layer SPEC-173's original check was actually about.
- **Archive and restore** (`docs/testing/e2e.md` §4.11) — SPEC-170's negative assertion now reads from
  `dat-prod-archive-audit`. **Confirm `get-trail-status` reports `IsLogging: true` first**: an empty
  result from a trail that is off reads exactly like a `RestoreObject` that never happened. Data
  events arrive in batches — wait ~10 minutes.
- **Table refresh** (`docs/testing/e2e.md` §4.4) — the add-a-column fixture must name the new file so it
  **sorts first** (`part0.csv`), and SPEC-157's contention needs an SQS double-send or a
  several-hundred-object folder; two UI submits 2 s apart are measured not to contend.
- **SPEC-149's preservation check and SPEC-153's foreign projection fixture** are now makeable, from
  the `dat-prod-verification` role.

  > **NOT YET, as of 2026-08-15.** The role is **not created** — `verification_principal_arns` is
  > unset by decision, so both read-backs remain blocked. Confirmed live: `aws glue get-databases`
  > returns **empty** for the laptop IAM identity (Lake Formation filtering the catalog), and a
  > local plan fails on `GetLFTag` for `portal-managed`. Creating it is now a repo variable plus a
  > CI apply (#461), never a local one.
- **FR-007's nine dialogs** need a visual pass at desktop and 400px, and **FR-003's listbox** needs
  re-measuring in both dialogs under both share kinds, in Safari.

  > **PARTIALLY SUPERSEDED 2026-08-15.** Measured in **Chrome at desktop**: **8 of the 9 dialogs**
  > at **392px** (root font-size is 14px, so `max-w-md` is 392 — the 448 figure in this spec's own
  > text is `max-w-lg`), and FR-003's containment in **Add members** and **Share table under both
  > share kinds** at 0px/−61px/−135px overhang. Both are **rendering** assertions, so Chrome
  > corroborates and does not discharge them: **Safari is still owed**, as is **400px** (not
  > reachable by window resize on macOS — Chrome's minimum is 606px) and the **ninth dialog**
  > (`SaveQueryDialog`'s "nowhere to save" state, which needs the personal space unavailable).
  > FR-005 **is** discharged. Evidence: `docs/testing/sessions.md`.

**Not verifiable offline:** that CloudTrail actually records `RestoreObject` for this bucket's
object-level calls (the selector is built from the documented shape), that the DESCRIBE tag grant is
sufficient for `GetTableVersions`, and that the first apply of the new module survives IAM's
eventual consistency — the archive plane's own first apply did not, which is why the 30s propagation
floor is here too. **A red first apply of new infra is expected rather than a defect.**

## The plan scan rejected the verification role's trust, and rejecting it was right

The first version trusted `arn:aws:iam::{account}:root` — the standard AWS delegation idiom, which
grants nothing by itself because an account principal still needs its own `sts:AssumeRole`. The
rendered-plan scan failed it with **`CKV_AWS_61` on `module.verification.aws_iam_role.verification`**
(1 unaccepted IAM finding; the `Resource: "*"` rows I had expected to fire did not).

**It was not accepted, and the accept list is unchanged.** SPEC-139's rule is that the list holds
findings with *no scopable alternative* — CloudFront and Cognito creation have no ARN before the
resource exists and no applicable condition key. Naming the principal **is** a scopable alternative
here, so accepting would have been suppressing a fixable finding, which is the thing that list's own
header warns against.

`verification_principal_arns` is now a root variable, **empty by default**, and the role is not
created when it is empty. Two consequences worth knowing:

- **The trail ships unconditionally** — it needs no principal, and it is the half that unblocks
  SPEC-170's negative assertion. That check is runnable the moment this applies.
- **The catalog read-backs need one line of config first**, and it is **not** a local
  `terraform.tfvars`:

  ```bash
  gh variable set TF_VAR_verification_principal_arns \
    --body '["arn:aws:iam::<account>:user/<your-iam-user>"]'
  ```

  then run **Deploy Infrastructure**. Until then SPEC-149's preservation check and SPEC-153's
  fixture stay blocked on the same Lake Formation wall.

  > **CORRECTED 2026-08-14 (#461).** This section, `terraform.tfvars.example`, both live-check
  > scripts and the variable's own description originally said to set the ARN in a gitignored
  > `infra/terraform.tfvars` and apply. **Following that instruction would have destroyed
  > production.** No human identity in this account can apply locally: the laptop IAM user is
  > not on the data buckets' policy allowlists, so tofu reads `dat-prod-user-space` and
  > `dat-prod-archive` as absent and plans to replace them — measured as `25 to add, 3 to
  > change, 13 to destroy`, with both buckets in the replace set. The same plan then failed on
  > `GetLFTag` for `portal-managed`, the exact refusal this role exists to lift, so the tfvars
  > route could not have worked even had the drift been benign. `modules/data/s3.tf` already
  > recorded this failure mode for the deploy role under SPEC-016; the lesson did not reach the
  > one variable a human was meant to set by hand.

## What the fresh-context review caught

Four defects, all fixed on the branch before merge. Worth recording because three of them are the
same failure class this spec is about — **a gate that could not fail**.

- **The verification role could not read the catalog.** Its Glue statement was scoped to
  `catalog` + `catalog/*`, and **Glue has no `catalog/*` hierarchy** — `GetTable` and
  `GetTableVersions` each need the database and table ARNs alongside it, which is the shape
  `portal-role-analytics` and the table-builder execution role already use. It would have applied
  cleanly and denied at runtime, leaving the read-back blocked with nothing red. The test asserted
  the *actions* and never the resources, so it passed over it; it now asserts the resource set,
  including that `catalog/*` is absent.
- **FR-007's fix closed half the trap.** `FormDialog` with `scrollBody` and no `className` hands
  `Modal` a **truthy** string, so `className || 'max-w-md'` never fires — the identical failure one
  branch over, and the exact call shape the component's own doc comment advertises. Nothing was
  broken only because all six current `scrollBody` callers happen to pass a width. `FormDialog` now
  supplies the width itself.
- **FR-002 refused mixed selections the service would have honoured.** `undeletableSelectionRefusal`
  returned on the *first* protected item and the reason disables the whole button — so
  `saved_queries` + an ordinary file killed Delete entirely, and at a space root select-all takes in
  all three protected folders at once. It now refuses only when **every** item is refused; a
  selection that genuinely does something keeps the confirm and the per-item report.
- **`modules/analytics` had no `depends_on` edge to `module.verification`**, while granting Lake
  Formation to its constructed ARN — latent until `verification_principal_arns` is set, which is
  precisely the apply that would hit it.

## Follow-ups
- **SPEC-183's LOADING half stays descoped** and is untouched here.

## User-facing docs sweep

**No Help change.** The two guides this spec could have invalidated both stay true, and one of them
becomes true for the first time: `shared-spaces` says *"Active once they've signed in and opened the
space, or Pending until they do"* — which was exactly the claim FR-008 found the roster
contradicting, and is now the behaviour. The `saved_queries` guides already say the folder can't be
deleted or renamed; FR-002 changed **when** that refusal reaches the user, not what it says. FR-007,
FR-009 and FR-010 are presentational with no documented behaviour attached.
