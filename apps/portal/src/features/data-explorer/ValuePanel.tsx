import {IconButton} from '../../components/IconButton';
import {useEscapeKey} from '../../hooks/useEscapeKey';
import {EMPTY_DISPLAY, NULL_DISPLAY} from './cellText';
import type {TransformedValue} from './formatting';

export type ValuePanelProps = {
  /** The focused cell's column, or null when nothing is focused. */
  column: string | null;
  /**
   * The focused cell's complete value — never the truncated rendering. `null` is SQL NULL;
   * **`undefined` is "no cell is focused"**, which is a different thing and must not be
   * announced as NULL: telling those two apart is the panel's whole job.
   */
  value: string | null | undefined;
  /**
   * The column's Athena type (SPEC-184 FR-003 AC3).
   *
   * Here because the type tint must never be the only thing carrying a value's type: this
   * panel and the column header are the two places it is written in words.
   */
  type?: string | null;
  /** How the grid is rendering this cell, when a transformer changes it (FR-005 AC6). */
  transformed?: TransformedValue | null;
  onClose: () => void;
};

/**
 * The focused cell's full value (SPEC-180 FR-003).
 *
 * A `<textarea readonly>` rather than a block of text: it is scrollable, selectable and
 * copyable with the platform's own shortcuts, and read-only rather than disabled so it
 * stays focusable — the Data Explorer is read-only, but a value you cannot select is a
 * value you cannot use. **It does not trap focus**: this is a side surface beside the
 * grid, not a modal over it, so Tab leaves it the way it arrived.
 *
 * NULL and the empty string are named rather than shown, because both would render as an
 * empty box and the whole point of this panel is to say what a cell actually holds.
 *
 * One tree reflows (SPEC-095): below `tablet` it is a full-width sheet docked to the
 * bottom, at `tablet` and up a column beside the grid. Escape closes it through the
 * depth-ordered registry (SPEC-155), so a dialog opened above it still outranks it.
 */
export function ValuePanel({column, value, type, transformed, onClose}: ValuePanelProps) {
  useEscapeKey(onClose, true);
  const focused = column !== null && value !== undefined;
  const marker = !focused
    ? 'Select a cell to see its value.'
    : value === null
      ? NULL_DISPLAY
      : value === ''
        ? EMPTY_DISPLAY
        : null;

  return (
    <aside
      aria-label="Value"
      className="fixed inset-x-0 bottom-0 z-30 flex max-h-[50dvh] flex-col gap-2 border-t border-border bg-surface p-3 shadow-lg tablet:static tablet:z-auto tablet:max-h-none tablet:w-80 tablet:flex-none tablet:rounded-lg tablet:border tablet:shadow-none">
      <div className="flex flex-none items-center gap-2">
        <span className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-text">{column ?? 'Value'}</h3>
          {type && <span className="block truncate font-mono text-[10px] text-text-3">{type}</span>}
        </span>
        <IconButton
          label="Close value panel"
          onClick={onClose}>
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-4 w-4"
            aria-hidden="true">
            <path
              strokeLinecap="round"
              d="M2 2l12 12M14 2L2 14"
            />
          </svg>
        </IconButton>
      </div>
      {/* The RAW value and the rendering, both, and labelled apart. A panel that showed
          only the transformed form would leave a user with no way to see what they are
          actually filtering, colouring and copying (FR-005 AC6). */}
      {focused && transformed && (
        <div className="flex-none">
          <h4 className="text-xs font-medium text-text-2">Shown as</h4>
          <p className="mt-1 truncate rounded-md border border-border bg-surface-2 p-2 font-mono text-sm text-text">
            {transformed.text}
          </p>
          {transformed.reason && <p className="mt-1 text-xs text-text-2">{transformed.reason}</p>}
        </div>
      )}
      {focused && transformed && <h4 className="flex-none text-xs font-medium text-text-2">The value itself</h4>}

      {marker !== null ? (
        <p className="min-h-0 flex-1 overflow-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-sm italic text-text-3">
          {marker}
        </p>
      ) : (
        <textarea
          readOnly
          aria-label={`Value of ${column ?? 'the focused cell'}`}
          value={value ?? ''}
          className="min-h-0 flex-1 resize-none overflow-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-sm text-text tablet:min-h-[12rem]"
        />
      )}
    </aside>
  );
}
