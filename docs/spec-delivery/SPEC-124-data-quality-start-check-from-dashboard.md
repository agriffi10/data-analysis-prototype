# Completed Spec — SPEC-124: Data Quality — Start a Check from the Dashboard

## What was completed?

A second entry point into a quality check, on the page that lists them. `/data-quality` gains
a **New quality check** action (header + empty-state CTA) opening **`StartQualityCheckDialog`**:
space `<select>` → `DestinationPicker` → confirm, targeting one folder **or** one file.

- **`StartQualityCheckDialog.tsx`** — the `SaveResultsDialog` composition with the filename
  field removed. Spaces come from `usableSpaceTargets` (reused, not re-derived — a third
  derivation of connection→bucket/rootPrefix would be the one that drifts). Keyed picker per
  space, live target line, confirm that names the target ("Check this folder"/"Check this
  file"). Enqueues through `useDataQualityCheck` — no second enqueue path.
- **`DestinationPicker`** gains an **opt-in** `selectableFiles` mode: `onTargetChange`
  (fired on mount and every navigation/selection), `listLabel`, an **appended**
  `onConfirm(prefix, bucket, selectedFileKey?)` argument, clear-selection-on-navigate, and a
  confirm guard on an empty folder. `markerKey` becomes **type-required** in that mode (a
  union on `Props`), because without it the space's `DO_NOT_DELETE.txt` sits at every root as
  a selectable target.
- **`DataQualityPage`** — the action in every list state (including the error one), the
  post-enqueue **info banner** (the check is not in the list yet and will not be for minutes),
  and the amended SPEC-123 FR-005 empty-state copy.
- **Help** — both entry points documented; the "not in the list yet" rule stated (SPEC-074).

**Deviations, both technical and taken in-session:**

- **`toast: false` suppresses the SUCCESS toast only.** FR-005 wants one confirmation per
  action, but FR-004 keeps the failure wording inside the hook — suppressing both would make a
  failed dashboard enqueue silent, since the banner only appears on success.
- **The target line is two spans, not `direction: rtl`.** Reuses `splitLocation` (now
  exported from `DataQualityRunRow`) for the same bidi reason SPEC-123 recorded.
- **The SPEC-106 listing-error fix was already in place** (`DestinationPicker` renders
  `toUserMessage(error)`); only the regression test was owed, and it was added.

## What changed from earlier specs?

- **`useDataQualityCheck.start` (SPEC-113)** now returns `Promise<boolean>` and takes
  `opts?: {toast?: boolean}`. The Files-browser caller is unchanged in behaviour.
- **`DestinationPicker.onConfirm` (SPEC-039)** gained an optional third argument. Move, Copy
  and Save results forward the callback directly, so it reaches their handlers and is ignored
  there; three test assertions were updated to expect the extra `undefined`.
- **SPEC-123 FR-005's empty-state body copy** no longer sends the user to the Files browser.
- **`test/axe.ts`** gained `expectContainerHasNoA11yViolations` for a state that must be
  driven into (the page a11y spec now runs with the dialog open).

## Verification

`vitest` 1185+ passed · `npm run build` · `lint` · `format` — all green locally.

Mutations observed to fail the guards they claim to protect: deleting the
clear-selection-on-navigate (2 tests red) and dropping the space `<label>`'s `htmlFor` (both
a11y specs red).

**Deferred:** the live end-to-end. Per the standing decision (2026-07-21) the whole
data-quality arc gets **one** smoke pass now that 124 is built — nothing here has been
exercised against real SQS/S3/Cognito.
