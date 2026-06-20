import { useEffect, useRef } from 'react';
import { Button } from '../../components/Button';
import { QUERY_TABS_MAX } from './query.constants';

type Props = {
  onDismiss: () => void;
};

// SPEC-041 FR-008: purely informational alert shown when a tab-open is attempted
// at QUERY_TABS_MAX. Dismissing leaves tabs unchanged (the attempted action is
// not completed). Escape / backdrop also dismiss. Reuses the SPEC-026 pattern.
export function TabLimitDialog({ onDismiss }: Props) {
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    okRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onDismiss();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onDismiss]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onDismiss}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label="Query tab limit reached"
        className="w-full max-w-md rounded-lg bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 pb-4 pt-5">
          <h2 className="text-md font-semibold text-text">
            You’ve reached the tab limit
          </h2>
          <p className="mt-3 text-sm text-text-2">
            You have the maximum of {QUERY_TABS_MAX} query tabs open. Close a tab
            before opening another.
          </p>
        </div>
        <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
          <Button ref={okRef} variant="primary" onClick={onDismiss}>
            Got it
          </Button>
        </div>
      </div>
    </div>
  );
}
