# Completed Spec — SPEC-158: Shared-Space Suggestions from the Local Cache

## What was completed?

`TableShareDialog`'s **Shared spaces** entry suggests as you type, from the spaces the signed-in
user already belongs to. Browser-only: no Lambda, no published document, no IAM, no env var, no new
AWS call.

- **`SuggestionSource`** (`user-directory/userDirectory.types.ts`) — `{status, search}`, what a
  suggestion field needs from whatever is suggesting.
- **`UsernameCombobox` takes that source as required props** and calls no hook of its own;
  `UsernameChipsField` passes it through. Both are otherwise unchanged.
- **`useUsernameSuggestions()`** (`features/user-directory/`) — the directory as a
  `SuggestionSource`, so `AddMembersDialog` and the dialog's user entry gained a prop, not a
  decision.
- **`useSpaceSuggestions()`** (`features/shared-spaces/`) — the same shape from `useConnections`,
  filtered to `kind === 'shared'` + `isConnectionUsable`, over SPEC-147's `buildIndex`/`search`.
  Lazy build keyed on the connection list's identity.
- **One combobox now serves both kinds** in `TableShareDialog`, keyed on the kind.

### Deliberate deviations

- **The combobox stays in `features/user-directory/`;** the spec's file tree put it (and
  `UsernameChipsField`) under `components/`. SPEC-155's ESLint rule forbids `components/` importing
  `features/`, and the combobox imports `parseMemberInputDetailed` from `features/shared-spaces`.
  FR-001's "imports nothing from `features/user-directory`" is met in substance: no hook call, and
  the only remaining import is its co-located type.
- **A third prop, `unlistedNote`.** The API contract says "the two additions", but FR-003 AC5
  requires different wording for spaces. It is optional and defaults to the exact directory
  sentence, so no existing consumer or test sees it.
- **Add is now enabled for a wholly-invalid SPACE entry**, as it already was for users — clicking it
  surfaces the rule instead of leaving a dead button. The disabled gate was correct while the space
  entry was a plain `Input` with its own pre-parse; once it is the same combobox, that pre-parse is
  a second, quieter parser beside the one that actually commits. Confirmed with the user before
  building; one assertion in `TableShareDialog.test.tsx` was updated with the reason.

## What changed from earlier specs?

- **SPEC-148's "the space path is deliberately unchanged" is superseded.** The space entry is a
  combobox: it suggests, and it reports malformed tokens instead of dropping them silently
  (`parseMemberInputDetailed`, not `parseMemberInput`) — the SPEC-148 behaviour the user kind
  already had.
- **SPEC-147's internal `useUserDirectory()` call is gone from `UsernameCombobox`.** Its spec's
  prose had wanted the status as a prop; the deviation is now closed rather than re-argued.
- **`parseMemberInput` has no production consumer left.** Kept: it is the domain's plain parse of a
  bulk string, pinned by its own tests and the baseline `parseMemberInputDetailed` is checked to
  agree with. Its docstring's claim that table-share still uses it was corrected.
- **`TableShareDialog`'s two entry branches became one element** with `key={kind}`, so a note or
  error raised under one kind cannot linger over the other (the two-component form gave that for
  free).

## Docs sweep

- **Help & guides:** the *Share a table* step now says both kinds suggest, that the space
  suggestions are the spaces you belong to, and that you can still type the name of any other space.
- **Component inventory:** rows updated for `UsernameCombobox`, `UsernameChipsField`,
  `TableShareDialog` and the types row; added for `useUsernameSuggestions` and `useSpaceSuggestions`.
- **`decisions.md`:** *No shared-space directory is published* — the disclosure trade, so the
  question is not reopened without the reasoning.

## Verification

`format:check`, `lint`, `build` and `test` (1678 passed) clean; coverage 92.54 / 87.82 / 91.55 /
94.40 against the 91/86/89/93 floors. Nothing here reaches AWS, so there is no live check owed — the
one browser pass already outstanding for SPEC-146/147 now covers this field too (**Share table**
signed in, at 400px and desktop, in Safari).
