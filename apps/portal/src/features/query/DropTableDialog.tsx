import { useEffect, useRef } from 'react';
import { Button } from '../../components/Button';

type Props = {
  table: string;
  isDropping: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

// SPEC-044 FR-005: warn-and-confirm before DROP TABLE (SPEC-026 alertdialog,
// danger action). Escape/backdrop cancel and focus defaults to Cancel so a stray
// Enter never drops a table. The action shows progress + locks while in flight.
export function DropTableDialog({
  table,
  isDropping,
  onConfirm,
  onCancel,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !isDropping) onCancel();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isDropping, onCancel]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={() => {
        if (!isDropping) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label="Confirm drop table"
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
              Drop the table “{table}”?
            </h2>
          </div>
          <p className="mt-3 text-sm text-text-2">
            This removes the table definition from your database. The underlying
            data files in S3 are not deleted.
          </p>
          <p className="mt-2 text-sm font-medium text-danger">
            This can’t be undone.
          </p>
        </div>

        <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
          <Button
            ref={cancelRef}
            variant="ghost"
            onClick={onCancel}
            disabled={isDropping}
          >
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={isDropping}>
            {isDropping ? 'Dropping…' : 'Drop table'}
          </Button>
        </div>
      </div>
    </div>
  );
}
