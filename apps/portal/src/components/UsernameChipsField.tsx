import {useMemo, useState} from 'react';
import {UsernameCombobox} from './UsernameCombobox';
import {cx} from '../lib/cx';

export type UsernameChipsFieldProps = {
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
 * @example
 * <UsernameChipsField label="Usernames" listLabel="Members to add"
 *   value={members} onChange={setMembers} exclude={existingMembers} />
 */
export function UsernameChipsField({
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
  describedBy
}: UsernameChipsFieldProps) {
  const [entry, setEntry] = useState('');

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
      />

      {renderChips && value.length > 0 && (
        <ul
          aria-label={listLabel}
          className="mt-2 flex flex-wrap gap-1.5">
          {value.map((name) => (
            <li
              key={name}
              className="flex items-center gap-1 rounded-full border border-border bg-surface-2 py-0.5 pl-2.5 pr-1 text-sm text-text">
              <span className="font-mono">{name}</span>
              <button
                type="button"
                aria-label={chipRemoveLabel(name)}
                disabled={disabled}
                onClick={() => remove(name)}
                className={cx(
                  'grid h-6 w-6 place-items-center rounded-full text-text-3',
                  'hover:bg-surface hover:text-text focus-visible:outline-none focus-visible:ring-2',
                  'focus-visible:ring-accent disabled:opacity-45'
                )}>
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  className="h-3 w-3"
                  aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
