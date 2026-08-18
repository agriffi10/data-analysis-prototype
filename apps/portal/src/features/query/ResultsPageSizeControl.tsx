import {useId, useState} from 'react';
import {clampPageSize} from './useResultsPageSize';

type Props = {
  /** The committed workspace-global page size. */
  pageSize: number;
  /** Called with a valid, clamped integer on commit (blur / Enter). */
  onCommit: (value: number) => void;
  /** No result set present — rendered but non-interactive. */
  disabled?: boolean;
};

/**
 * the "Rows per page" control above the results grid. Free-form
 * integer entry, committed on blur or Enter (never per keystroke); invalid input
 * reverts to the last committed value, out-of-range input is clamped;
 * Escape abandons the draft. The label is programmatically associated, so the
 * accessible name is "Rows per page".
 */
export function ResultsPageSizeControl({pageSize, onCommit, disabled = false}: Props) {
  const inputId = useId();
  const [draft, setDraft] = useState(String(pageSize));

  // Re-sync the draft when the committed value changes externally (render-time
  // state adjustment — no effect, no extra committed frame with a stale draft).
  const [lastPageSize, setLastPageSize] = useState(pageSize);
  if (lastPageSize !== pageSize) {
    setLastPageSize(pageSize);
    setDraft(String(pageSize));
  }

  const commit = () => {
    // Number() (not parseInt) so trailing garbage ("12abc") and fractions
    // ("2.5") are rejected as a whole rather than partially parsed.
    const parsed = draft.trim() === '' ? Number.NaN : Number(draft);
    const next = clampPageSize(parsed);
    if (next === null) {
      setDraft(String(pageSize)); // revert to the last valid value
      return;
    }
    setDraft(String(next)); // reflect clamping immediately
    onCommit(next);
  };

  return (
    <div className="flex flex-none items-center gap-2">
      <label
        htmlFor={inputId}
        className="text-sm text-text-2">
        Rows per page
      </label>
      <input
        id={inputId}
        type="text"
        inputMode="numeric"
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          else if (e.key === 'Escape') setDraft(String(pageSize));
        }}
        className="h-8 w-20 rounded-md border border-border bg-surface px-2 text-right text-sm text-text focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-45"
      />
    </div>
  );
}
