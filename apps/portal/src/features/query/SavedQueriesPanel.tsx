import { useEffect, useState } from 'react';
import { IconButton } from '../../components/IconButton';
import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { formatRelativeTime } from './query.format';
import type { SavedQuery } from './query.types';

type Props = {
  open: boolean;
  onClose: () => void;
  queries: SavedQuery[];
  isLoading: boolean;
  error: string | null;
  onOpen: (query: SavedQuery) => void;
  onDelete: (id: string) => void; // parent removes + unlinks any open tab
};

// SPEC-043 FR-005/006/007: right slide-over listing the user's saved queries,
// mirroring the SPEC-036 history drawer mechanics. Each card: name, updated time,
// SQL preview, Open (→ new linked tab) + Delete (→ confirm). Most-recently-updated
// first. Presentational — the workspace owns the data so it can also drive dirty
// markers, the save flow, and tab unlinking on delete.
export function SavedQueriesPanel({
  open,
  onClose,
  queries,
  isLoading,
  error,
  onOpen,
  onDelete,
}: Props) {
  const [pendingDelete, setPendingDelete] = useState<SavedQuery | null>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (pendingDelete) setPendingDelete(null);
        else onClose();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose, pendingDelete]);

  if (!open) return null;

  const sorted = [...queries].sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/30"
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Saved queries"
        className="flex h-full w-full max-w-[440px] flex-col bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex h-14 flex-shrink-0 items-center gap-2 border-b border-border px-5">
          <h2 className="text-md font-semibold text-text">Saved queries</h2>
          <div className="flex-1" />
          <IconButton label="Close saved queries" onClick={onClose}>
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
            <Banner variant="danger" title="Couldn’t load saved queries.">
              {error}
            </Banner>
          ) : isLoading ? (
            <p className="text-sm text-text-3">Loading saved queries&hellip;</p>
          ) : sorted.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-8 w-8 text-text-3"
                aria-hidden="true"
              >
                <path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z" />
                <path d="M9 4v5h6" />
              </svg>
              <p className="text-sm font-medium text-text">No saved queries yet</p>
              <p className="max-w-[260px] text-sm text-text-3">
                Save a query from the editor and it’ll appear here so you can open
                and run it again.
              </p>
            </div>
          ) : (
            sorted.map((q) => {
              const preview = q.sql.replace(/\s+/g, ' ').trim();
              return (
                <div key={q.id} className="rounded-md border border-border p-3">
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="truncate font-semibold text-text">
                      {q.name}
                    </span>
                    <span
                      className="ml-auto flex-none text-xs text-text-3"
                      title={new Date(q.updatedAt).toLocaleString()}
                    >
                      {formatRelativeTime(q.updatedAt)}
                    </span>
                  </div>
                  <p className="truncate font-mono text-sm text-text-2" title={preview}>
                    {preview}
                  </p>
                  <div className="mt-2 flex items-center gap-3">
                    <div className="flex-1" />
                    <button
                      type="button"
                      onClick={() => onOpen(q)}
                      className="rounded-sm px-1.5 py-0.5 text-xs font-semibold text-accent-text hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                    >
                      Open
                    </button>
                    <button
                      type="button"
                      onClick={() => setPendingDelete(q)}
                      className="rounded-sm px-1.5 py-0.5 text-xs font-semibold text-danger hover:bg-danger-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/40"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </aside>

      {pendingDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setPendingDelete(null)}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label="Confirm delete saved query"
            className="w-full max-w-md rounded-lg bg-surface shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 pb-4 pt-5">
              <h2 className="text-md font-semibold text-text">
                Delete “{pendingDelete.name}”?
              </h2>
              <p className="mt-3 text-sm text-text-2">
                This removes the saved query. Any open tab linked to it keeps its
                SQL but is no longer linked.
              </p>
              <p className="mt-2 text-sm font-medium text-danger">
                This can’t be undone.
              </p>
            </div>
            <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
              <Button variant="ghost" onClick={() => setPendingDelete(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  onDelete(pendingDelete.id);
                  setPendingDelete(null);
                }}
              >
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
