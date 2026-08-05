# Completed Spec — SPEC-147: Username Directory — Browser Data Layer & Typeahead Combobox

## What was completed?

The browser half of the arc: reading SPEC-146's document, searching it, and two components around
it. **No dialog is wired** — that is SPEC-148, and nothing here is reachable by a user yet.

- **`features/user-directory/`** — `userDirectory.service.ts` (forgiving read; missing, corrupt,
  wrong-`version` and non-array all degrade to empty), `userDirectoryKeys`, `useUserDirectory`, and
  the pure `usernameTrie.ts`.
- **`useUserDirectory`** returns `{status, search, generatedAt}`. `search` is a **stable callback**,
  not the index — it builds on first call and memoises, so the lazy build is invisible and no
  consumer holds a half-built structure. `status` collapses *errored* and *empty* into
  `'unavailable'`, so no consumer has to remember to handle both.
- **`UsernameCombobox`** — the ARIA combobox pattern, built on the shared `Input`.
- **`UsernameChipsField`** — the multi-value composition, with `renderChips={false}`.
- **`parseMemberInputDetailed`** beside the unchanged `parseMemberInput`.

### Deliberate deviations

- **The components call `useUserDirectory()` themselves rather than taking `status` as a prop.**
  FR-002's prose says "the components take it as a prop", but the spec's own API contract declares
  neither `UsernameComboboxProps` nor `UsernameChipsFieldProps` with a status field, and the repo's
  testing rule is integration-style — render the real hook, mock only the service boundary. The
  declared props were treated as authoritative. Consumers are unaffected either way.
- **`UsernameCombobox` gained two props the contract does not list**: `suppress` (hidden from
  suggestions but **not** refused — what an already-committed chip is; refusing one with an error
  would turn a harmless double-click into a complaint) and `describedBy` (so a consumer's help line
  can reach the input's `aria-describedby`). `UsernameChipsField` likewise takes `placeholder` and
  `describedBy`.
- **`searchWithCost` is exported from `usernameTrie.ts`**, which the contract does not list. FR-003
  requires a test asserting the number of trie nodes visited; making that a returned number rather
  than an inferred timing is the difference between pinning the claim and hoping.
- **A paste of a single name does NOT auto-commit**; only a paste containing a separator does.
  Someone pasting `bob, cara` has said they are done with both; someone pasting one name very often
  wants to fix a character first, and auto-committing takes the field away from them.
- **`memberInput.test.ts` is new.** FR-006 requires `parseMemberInput`'s existing tests to pass
  unmodified — it had none. Its behaviour is now pinned directly, *before* the variant landed beside
  it, because a behaviour with no test is one a refactor can change silently.

## What changed from earlier specs?

- **`features/shared-spaces/memberInput.ts`** gained `parseMemberInputDetailed`; `parseMemberInput`'s
  signature and behaviour are untouched, and the barrel exports both.
- **`useEscapeKey` was NOT changed** — see below.

## The Escape mechanism, settled by measurement

FR-004 left this genuinely open: `stopPropagation` from a React handler *should* prevent
`useEscapeKey`'s `document` listener, but the spec required it be **verified, not assumed**, with a
`defaultPrevented` guard as the fallback.

It was verified with a throwaway probe — a bare input inside a `Modal`, calling only
`stopPropagation` — and the modal's `onDismiss` fired **zero** times. React delegates events at its
root container, which sits *below* the `document` listener, so stopping the native event there is
enough. **`useEscapeKey` therefore needed no guard and did not get one**, and no other consumer of it
changed.

The combobox still calls `preventDefault` alongside, for a different and non-redundant reason: some
browsers treat Escape in a text input as "revert the value", and this is a field whose content must
survive closing the list.

The order is pinned by a test rendering the real composition — a **Modal inside a Drawer**, with the
drawer's `closeOnEscape` **gated** as `ManageMembersDrawer` gates it. Without that gate one keydown
closes both surfaces and the stated order is unreachable; a fixture that omitted it would fail and
the combobox would be blamed for something it does not control.

## Two defects the tests caught, both of which would have shipped silently

1. **`commit()` clobbered the exclusion error it had just set.** `commitNames` set the error and
   `commit` overwrote it a line later with `null`, so every "already a member" refusal was invisible
   while the name was still (correctly) not committed. Fixed by having `commitNames` *return* the
   refusal and setting the error exactly once.
2. **An invalid-token fixture that was not invalid.** `bob Bad Name` was written as a mixed
   valid/invalid paste, but `Bad` lowercases to `bad`, which is catalog-safe — the test asserted
   nothing. Replaced with `alice@corp.com` and `9lives`, which genuinely fail the rule.

## Verification

`npm run lint`, `npm run build` and `npm run test` all clean: **1394 tests** (+93). Coverage includes
every FR-003 ranking and cost case (both bands, with the substring scan asserted to be skipped when
the prefix band fills the limit), every FR-004 keyboard interaction, the Modal-inside-Drawer
three-Escape case, all three directory statuses for FR-005, FR-006's paste / exclude /
`renderChips={false}` / chip-label behaviours, and `vitest-axe` in every state the spec lists
(including at a 400px width).

**No new dependency was added** — the trie is a plain object and the flip-above positioning is a
bounded max-height plus a measured flip, not a floating-UI library.

Two lint rules shaped the implementation rather than being suppressed:
`react-hooks/set-state-in-effect` (the debounced live-region count is now *derived* from a
query-stamped state value, which also stops a count being announced against a query it did not
describe) and `react-hooks/exhaustive-deps` (the suggestions array is memoised).

**Nothing user-facing shipped, so no help-content change** — SPEC-148 owns that sweep, and it also
carries the browser-session live check SPEC-146 still owes.
