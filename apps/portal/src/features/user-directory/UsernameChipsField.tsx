import {useEffect, useMemo, useRef, useState} from 'react';
import {UsernameCombobox} from './UsernameCombobox';
import type {UsernameComboboxHandle} from './UsernameCombobox';
import {Chip, ChipList} from '../../components/Chip';
import type {SuggestionSource} from './userDirectory.types';
import {FIELD_HINT} from '../../components/fieldStyles';

export type UsernameChipsFieldProps = SuggestionSource & {
  label: string;
  /** `aria-label` for the chip list — the caller names the noun ("Members to add"). */
  listLabel: string;
  value: string[];
  onChange: (next: string[]) => void;
  /**
   * `false` ⇒ the caller renders committed values itself. This is what lets
   * `TableShareDialog` keep ONE combined list of user *and* space chips rather than growing a
   * second list beside it. Default `true`.
   */
  renderChips?: boolean;
  /** Defaults to `Remove {name}`; `TableShareDialog` supplies `Remove user {name}`. */
  chipRemoveLabel?: (name: string) => string;
  exclude?: ReadonlySet<string>;
  excludeReason?: (username: string) => string;
  placeholder?: string;
  disabled?: boolean;
  /** Extra ids for the input's `aria-describedby` (a caller's help line). */
  describedBy?: string;
  /**
   * Forwarded to {@link UsernameCombobox}. Passed through for the same reason the source is: a
   * caller supplying spaces (or anything else) must be able to say so, or the field would tell
   * them their name "is not in the directory" — a directory it never read.
   */
  unlistedNote?: (names: string[]) => string;
  /**
   * Focus the field on mount. Dialogs hosting this MUST set it: `Modal` passes
   * `initialFocus: false` on purpose, deferring to each consumer's own focus effect, so a
   * field that does not ask for focus leaves it on the trigger OUTSIDE the modal — a screen
   * reader is never moved into the dialog, and axe cannot see it.
   */
  autoFocus?: boolean;
};

/**
 * A multi-value username field: {@link UsernameCombobox} plus the committed names as removable
 * chips.
 *
 * Chip rendering can be handed back with `renderChips={false}`, because the two consumers in
 * SPEC-148 genuinely differ — `AddMembersDialog` owns nothing but usernames, while
 * `TableShareDialog` mixes user and space chips with kind badges in a single list. Owning the
 * common case and yielding the uncommon one keeps this from becoming the union of both
 * consumers' quirks.
 *
 * The component owns NO submission logic: it reports `string[]` and the caller decides what to
 * do with it.
 *
 * The suggestion source is passed STRAIGHT THROUGH to the combobox (SPEC-158): this component
 * adds chips, not a data source, and a hook call here would make it the second place that decides
 * what a field suggests.
 *
 * @example
 * <UsernameChipsField {...useUsernameSuggestions()} label="Usernames"
 *   listLabel="Members to add" value={members} onChange={setMembers} exclude={existingMembers} />
 */
export function UsernameChipsField({
  status,
  search,
  label,
  listLabel,
  value,
  onChange,
  renderChips = true,
  chipRemoveLabel = (name) => `Remove ${name}`,
  exclude,
  excludeReason,
  placeholder,
  disabled = false,
  describedBy,
  unlistedNote,
  autoFocus = false
}: UsernameChipsFieldProps) {
  const [entry, setEntry] = useState('');
  const fieldRef = useRef<UsernameComboboxHandle>(null);

  useEffect(() => {
    if (autoFocus) fieldRef.current?.focus();
  }, [autoFocus]);

  // Already-committed names are SUPPRESSED, not excluded: offering one again is noise, but
  // refusing it with an error would turn a harmless double-click into a complaint. The silent
  // no-op happens in `commit` below.
  const committed = useMemo(() => new Set(value), [value]);

  const commit = (names: string[]) => {
    const added = names.filter((name) => !committed.has(name));
    if (added.length === 0) return;
    onChange([...value, ...added]);
  };

  const remove = (name: string) => onChange(value.filter((existing) => existing !== name));

  return (
    <div
      onKeyDown={(event) => {
        // Backspace on an EMPTY input removes the last chip — the one keyboard behaviour users
        // expect from a chip input and never see documented. Handled here rather than in the
        // combobox so it exists only where chips do; in `renderChips={false}` mode the caller
        // owns the list and removing from it behind their back would be wrong.
        //
        // GATED ON THE EVENT TARGET. This handler sits on the wrapper, which also contains the
        // chip list — so without the check, a keyboard user tabbing to "Remove alice" and
        // pressing Backspace deletes the LAST chip instead. Silent, wrong, invisible to axe.
        // Matched by role rather than by a ref, so the combobox keeps its input private.
        if (!(event.target instanceof HTMLElement) || event.target.getAttribute('role') !== 'combobox') return;
        if (event.key !== 'Backspace' || entry !== '' || !renderChips || disabled) return;
        if (value.length === 0) return;
        event.preventDefault();
        remove(value[value.length - 1]);
      }}>
      <UsernameCombobox
        ref={fieldRef}
        status={status}
        search={search}
        label={label}
        value={entry}
        onChange={setEntry}
        onCommit={(name) => commit([name])}
        onCommitMany={commit}
        exclude={exclude}
        excludeReason={excludeReason}
        suppress={committed}
        placeholder={placeholder}
        disabled={disabled}
        describedBy={describedBy}
        unlistedNote={unlistedNote}
      />

      {/* Closes a dead-end the chips model creates. A consumer's submit button is gated on
          COMMITTED values (SPEC-148 FR-001 requires it), so a user who types a name and reaches
          straight for that button finds it disabled with nothing explaining why — the text they
          just typed is not a chip yet. One line, only while there is uncommitted text. */}
      {renderChips && entry.trim() !== '' && (
        // Deliberately does NOT name a token. Naming one promised something this line cannot
        // keep: the first token of `Bob-Smith` is refused by the rule, `cara` may already be a
        // member, and `bob, cara` adds two names rather than the one named. It is also NOT a
        // live region — the combobox already owns one for the match count, and a second
        // announcing "b / bo / bob" on every keystroke would talk over it.
        <p className={FIELD_HINT}>Press Enter to add the name you typed.</p>
      )}

      {renderChips && value.length > 0 && (
        <ChipList
          ariaLabel={listLabel}
          className="mt-2">
          {value.map((name) => (
            <Chip
              key={name}
              name={name}
              removeLabel={chipRemoveLabel(name)}
              disabled={disabled}
              onRemove={() => remove(name)}
            />
          ))}
        </ChipList>
      )}
    </div>
  );
}
