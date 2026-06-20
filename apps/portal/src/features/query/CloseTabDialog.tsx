import { useEffect, useRef } from 'react';
import { Button } from '../../components/Button';

type Props = {
  label: string; // the tab being closed, e.g. "Query 2"
  onConfirm: () => void;
  onCancel: () => void;
};

// SPEC-041 FR-005: warn-and-confirm before closing a tab that holds non-empty
// SQL (an empty tab closes without this). Reuses the SPEC-026 pattern (mirrors
// ClearQueryDialog): alertdialog, Escape/backdrop cancel, focus on Cancel.
export function CloseTabDialog({ label, onConfirm, onCancel }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label="Confirm close tab"
        className="w-full max-w-md rounded-lg bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 pb-4 pt-5">
          <div className="flex items-start gap-3">
            <span className="flex-shrink-0 rounded-full bg-danger-soft p-1 text-danger">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-6 w-6"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="9" />
                <path strokeLinecap="round" d="M12 8v5M12 16h.01" />
              </svg>
            </span>
            <h2 className="text-md font-semibold text-text">
              Close “{label}”?
            </h2>
          </div>
          <p className="mt-3 text-sm text-text-2">
            This tab has unsaved SQL. Closing it discards that text for this
            session.
          </p>
          <p className="mt-2 text-sm font-medium text-danger">
            This can’t be undone.
          </p>
        </div>

        <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
          <Button ref={cancelRef} variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm}>
            Close tab
          </Button>
        </div>
      </div>
    </div>
  );
}
