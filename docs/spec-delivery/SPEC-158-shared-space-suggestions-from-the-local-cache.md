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
- **The two features now import each other**, and it is worth knowing rather than discovering:
  `user-directory` → `shared-spaces` for `parseMemberInputDetailed` (pre-dates this spec) and now
  `shared-spaces` → `user-directory` for `SuggestionSource` and the trie. No runtime cycle — the
  specific modules do not close a loop — and SPEC-155's rule polices `components/ → features/` only.
  Accepted rather than solved: extracting either would be a layering spec of its own, and the
  alternative here was duplicating the ranking, which FR-003 forbids.
- **A third prop, `unlistedNote`.** The API contract says "the two additions", but FR-003 AC5
  requires different wording for spaces. It is optional and defaults to the exact directory
  sentence, so no existing consumer or test sees it.
- **Add is now enabled for a wholly-invalid SPACE entry**, as it already was for users — clicking it
  surfaces the rule instead of leaving a dead button. The disabled gate was correct while the space
  entry was a plain `Input` with its own pre-parse; once it is the same combobox, that pre-parse is
  a second, quieter parser beside the one that actually commits. Confirmed with the user before
  building; one assertion in `TableShareDialog.test.tsx` was updated with the reason.
- **Three assertions in the existing dialog suite moved, not one.** FR-001 AC2's "unmodified apart
  from supplying the two new props" is about declaring exactly this, so all three: the Add gate
  above; `entryInput()` now queries by ROLE, because the open listbox is labelled
  `<kind> suggestions` and a label query matches it too; and `expect(queryByRole('combobox')).not
  .toBeInTheDocument()` was deleted from *offers NO suggestions under the Shared spaces kind*,
  which became *never offers USERNAMES under the Shared spaces kind* — the space entry IS a
  combobox now, and what still matters is that the two sources do not bleed.

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
- **`decisions/`:** *No shared-space directory is published* — the disclosure trade, so the
  question is not reopened without the reasoning.

## Verification

`format:check`, `lint`, `build` and `test` (1681 passed) clean; coverage comfortably over the
91/86/89/93 floors. A fresh-context review mutation-tested the load-bearing claims: feeding the
username source to both kinds fails 9 tests, dropping the `spaces` memo fails the single-build test,
and deleting `key={kind}` fails the note-does-not-outlive-the-toggle test (which that review's first
pass found missing, and which was added because of it). Nothing here reaches AWS, so there is no live check owed — the
one browser pass already outstanding for SPEC-146/147 now covers this field too (**Share table**
signed in, at 400px and desktop, in Safari).
