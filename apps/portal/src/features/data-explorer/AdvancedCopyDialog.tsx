import {useState} from 'react';
import {cx} from '../../lib/cx';
import {FormDialog} from '../../components/FormDialog';
import {ADVANCED_COPY_DEFAULTS, COPY_FORMAT_LABELS, SELECT_CLASS} from './dataExplorer.constants';
import {formatUsesQuoting} from './renderCopy';
import type {CopyFormat, CopyOptions} from './dataExplorer.types';

export type AdvancedCopyDialogProps = {
  /** Cells currently selected on this page — what the copy will be taken from. */
  selectedCount: number;
  onCopy: (options: CopyOptions) => void;
  onCancel: () => void;
};

/**
 * Why a gap can appear in a paste (FR-001 AC5).
 *
 * Stated rather than discovered: a discontiguous selection copies as the rectangle around
 * it, and a spreadsheet has no way to show which of its blank cells were never selected.
 */
export const COPY_RECTANGLE_NOTE =
  'A copy always comes out as one rectangle. If your selection has gaps, the cells in between are copied blank.';

/**
 * Why the copy may be smaller than the result (FR-001 AC6).
 *
 * The grid holds ONE page, so selecting a whole column selects the loaded rows and no more.
 * A user who has paged through a large result has every reason to expect otherwise, and
 * export is the tool that does cover the whole result set.
 */
export const COPY_LOADED_ROWS_NOTE =
  'Only the rows loaded on this page are copied — selecting a column header selects that page, not the whole result. To take everything, use Export.';

/** Why quoting is unavailable in the formats that already delimit their values. */
export const COPY_QUOTING_INERT = 'This format already keeps text and numbers apart, so quoting adds nothing.';

/** Why quoting is worth turning on where it does apply. */
export const COPY_QUOTING_NOTE = 'Quoting also keeps a value whose text is “NULL” apart from an actual empty cell.';

/**
 * The copy formats, in the order the dialog offers them.
 *
 * Tab-separated first because it is what Ctrl/Cmd+C already does and what a spreadsheet
 * expects — the dialog exists for the other five, but it should not make the ordinary case
 * look like the unusual one.
 */
const FORMATS = Object.keys(COPY_FORMAT_LABELS) as CopyFormat[];

/** Ties the quoting note to the checkbox, so the refusal is announced with the control. */
const QUOTING_NOTE_ID = 'advanced-copy-quoting-note';

/**
 * Copy, in the shape the destination wants (SPEC-185 FR-001).
 *
 * Staged rather than applied per control, for the reason every dialog in this feature is:
 * the copy is a single clipboard write, and writing on each keystroke would leave whatever
 * the user touched last on the clipboard rather than what they chose.
 *
 * **This dialog issues nothing.** Copy reads the page already on screen, so it starts no
 * execution and scans no bytes however many times it is used — which is exactly why it is
 * the selection-shaped tool and export is the result-shaped one.
 */
export function AdvancedCopyDialog({selectedCount, onCopy, onCancel}: AdvancedCopyDialogProps) {
  const [draft, setDraft] = useState<CopyOptions>(ADVANCED_COPY_DEFAULTS);
  const quotingApplies = formatUsesQuoting(draft.format);

  return (
    <FormDialog
      title="Copy selection"
      ariaLabel="Copy selection"
      submitLabel="Copy"
      className="max-w-lg"
      submitDisabled={selectedCount === 0}
      onSubmit={() => onCopy(draft)}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        {selectedCount} {selectedCount === 1 ? 'cell' : 'cells'} selected on this page.
      </p>

      <div className="mt-4">
        <label
          htmlFor="advanced-copy-format"
          className="mb-1.5 block text-sm font-medium text-text">
          Format
        </label>
        <select
          id="advanced-copy-format"
          value={draft.format}
          onChange={(e) => setDraft((d) => ({...d, format: e.target.value as CopyFormat}))}
          className={`${SELECT_CLASS} w-full`}>
          {FORMATS.map((format) => (
            <option
              key={format}
              value={format}>
              {COPY_FORMAT_LABELS[format]}
            </option>
          ))}
        </select>
      </div>

      <label className="mt-4 flex items-center gap-2 text-sm text-text-2">
        <input
          type="checkbox"
          checked={draft.includeHeaders}
          onChange={(e) => setDraft((d) => ({...d, includeHeaders: e.target.checked}))}
        />
        Include column names
      </label>

      <label className="mt-2 flex items-center gap-2 text-sm text-text-2">
        <input
          type="checkbox"
          checked={draft.includeRowNumbers}
          onChange={(e) => setDraft((d) => ({...d, includeRowNumbers: e.target.checked}))}
        />
        Include row numbers
      </label>

      {/* Refused rather than silently inert: in JSON, SQL and XML every value is already
          delimited by the format, so a quoting toggle would change nothing about the output.
          **`aria-disabled`, not `disabled`** — SPEC-172's fleet-wide rule, so the control
          stays in the tab order and the reason beside it is reachable rather than something
          a keyboard user tabs straight past. The handler ignores the change, since
          `aria-disabled` alone does not stop a checkbox toggling. */}
      <label className="mt-2 flex items-center gap-2 text-sm text-text-2">
        <input
          type="checkbox"
          checked={quotingApplies && draft.quoteValues}
          aria-disabled={!quotingApplies}
          aria-describedby={QUOTING_NOTE_ID}
          className={cx(!quotingApplies && 'opacity-45')}
          onChange={(e) => {
            if (!quotingApplies) return;
            setDraft((d) => ({...d, quoteValues: e.target.checked}));
          }}
        />
        Quote values
      </label>
      <p
        id={QUOTING_NOTE_ID}
        className="mt-1 text-xs text-text-3">
        {quotingApplies ? COPY_QUOTING_NOTE : COPY_QUOTING_INERT}
      </p>

      <p className="mt-4 text-xs text-text-3">{COPY_RECTANGLE_NOTE}</p>
      <p className="mt-1 text-xs text-text-3">{COPY_LOADED_ROWS_NOTE}</p>
    </FormDialog>
  );
}
