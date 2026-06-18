import { useEffect } from 'react';
import { IconButton } from '../../components/IconButton';
import { Banner } from '../../components/Banner';
import { useQueryHistory } from './useQueryHistory';
import { QueryHistoryRow } from './QueryHistoryRow';
import type { QueryHistoryEntry } from './query.types';

type QueryHistoryPanelProps = {
  open: boolean;
  onClose: () => void;
  username: string;
  onReopen: (entry: QueryHistoryEntry) => void;
  onRerun: (entry: QueryHistoryEntry) => void;
  rerunDisabled: boolean;
};

// SPEC-036: right slide-over drawer listing the user's private query history
// (SPEC-034 store, newest-first). Read-only — view / Open / Re-run, no delete.
// Mirrors the file-browser UploadDrawer pattern (scrim, Escape/click close).
export function QueryHistoryPanel({
  open,
  onClose,
  username,
  onReopen,
  onRerun,
  rerunDisabled,
}: QueryHistoryPanelProps) {
  const { history, isLoading, error } = useQueryHistory(open ? username : null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/30"
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Query history"
        className="flex h-full w-full max-w-[440px] flex-col bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex h-14 flex-shrink-0 items-center gap-2 border-b border-border px-5">
          <h2 className="text-md font-semibold text-text">Query history</h2>
          <div className="flex-1" />
          <IconButton label="Close query history" onClick={onClose}>
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true"
            >
              <path strokeLinecap="round" d="M2 2l12 12M14 2L2 14" />
            </svg>
          </IconButton>
        </div>

        <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-5">
          {error ? (
            <Banner variant="danger" title="Couldn’t load history.">
              {error}
            </Banner>
          ) : isLoading ? (
            <p className="text-sm text-text-3">Loading history&hellip;</p>
          ) : history.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-8 w-8 text-text-3"
                aria-hidden="true"
              >
                <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
                <path d="M3 3v5h5" />
                <path d="M12 8v5l3 2" />
              </svg>
              <p className="text-sm font-medium text-text">No queries yet</p>
              <p className="max-w-[260px] text-sm text-text-3">
                Run a query in the editor and it’ll appear here so you can re-open
                or re-run it.
              </p>
            </div>
          ) : (
            history.map((entry) => (
              <QueryHistoryRow
                key={`${entry.queryExecutionId}-${entry.submittedAt}`}
                entry={entry}
                onReopen={() => onReopen(entry)}
                onRerun={() => onRerun(entry)}
                rerunDisabled={rerunDisabled}
              />
            ))
          )}
        </div>
      </aside>
    </div>
  );
}
