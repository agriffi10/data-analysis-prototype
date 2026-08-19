import {forwardRef} from 'react';
import {FIELD_LABEL} from './fieldStyles';

/** The shape this control needs from a space, and nothing more — see the note on the type. */
export type SelectableSpace = {
  id: string;
  label: string;
  /** A shared space says so in its option text; omit for a space with no kinds to tell apart. */
  kind?: 'personal' | 'shared';
};

export type SpaceSelectProps = {
  /** The `<label>`, which differs by dialog: "Save to", "Space", "Build the table in". */
  label: string;
  /** Unique in the document — these dialogs are modal, but `useId` would break the tests' `getByLabelText`. */
  id: string;
  spaces: readonly SelectableSpace[];
  value: string;
  onChange: (spaceId: string) => void;
  disabled?: boolean;
  /** Wrapper margin, which is positional and belongs to the caller. Default `mt-3`. */
  className?: string;
};

/**
 * The "which space" `<select>` that sits above a `DestinationPicker`.
 *
 * **RENDERS NOTHING FOR A SINGLE SPACE**, which is the rule rather than a nicety: a one-option
 * control is the shape the gating rule declines to render for the share dialog's recipient kind
 * and for the Data Explorer's absent database step. With `sharedWorkspaces` off there is only
 * ever the personal space, so this disappears for most users most of the time.
 *
 * Extracted at its THIRD consumer. `SaveResultsDialog` and `StartQualityCheckDialog` carried
 * byte-similar copies of it, and the guard sweep's whole finding is that copies like these do
 * not stay identical — one of them already differed in whether a shared space said so in its
 * option text.
 *
 * Typed on a structural `SelectableSpace` rather than on `FileSpaceTarget`: this lives in
 * `components/`, which may not import from `features/`.
 *
 * @example
 * <SpaceSelect id="save-results-space" label="Save to" spaces={spaces} value={space.id} onChange={setSpaceId} />
 */
export const SpaceSelect = forwardRef<HTMLSelectElement, SpaceSelectProps>(function SpaceSelect(
  {label, id, spaces, value, onChange, disabled = false, className = 'mt-3'},
  ref
) {
  if (spaces.length <= 1) return null;
  return (
    <div className={className}>
      <label
        htmlFor={id}
        className={FIELD_LABEL}>
        {label}
      </label>
      <select
        ref={ref}
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-full rounded-md border border-border bg-surface px-3 text-base text-text focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-45">
        {spaces.map((s) => (
          <option
            key={s.id}
            value={s.id}>
            {s.label}
            {s.kind === 'shared' ? ' (shared)' : ''}
          </option>
        ))}
      </select>
    </div>
  );
});
