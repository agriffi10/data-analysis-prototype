import {useState} from 'react';
import {toUserMessage} from '../../lib/errorMessages';
import {Banner} from '../../components/Banner';
import {Drawer} from '../../components/Drawer';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {DocumentIcon} from '../../components/icons';
import {formatRelativeTime} from '../../lib/format';
import type {SavedQuery} from './query.types';

type Props = {
  open: boolean;
  onClose: () => void;
  queries: SavedQuery[];
  isLoading: boolean;
  /** The raw fetch error (or null); rendered via `toUserMessage`. */
  error: unknown;
  onOpen: (query: SavedQuery) => void;
  /** Parent removes the query and unlinks any open tab. */
  onDelete: (id: string) => void;
};

/**
 * Saved-queries drawer (most-recently-updated first) with Open (→ new linked
 * tab) and Delete (→ confirm). The delete confirm owns Escape while open.
 */
export function SavedQueriesPanel({open, onClose, queries, isLoading, error, onOpen, onDelete}: Props) {
  const [pendingDelete, setPendingDelete] = useState<SavedQuery | null>(null);

  const sorted = [...queries].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        title="Saved queries"
        closeOnEscape={!pendingDelete}>
        {error ? (
          <Banner
            variant="danger"
            title="Couldn’t load saved queries.">
            {toUserMessage(error).message}
          </Banner>
        ) : isLoading ? (
          <p className="text-sm text-text-3">Loading saved queries&hellip;</p>
        ) : sorted.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
            <DocumentIcon className="h-8 w-8 text-text-3" />
            <p className="text-sm font-medium text-text">No saved queries yet</p>
            <p className="max-w-[260px] text-sm text-text-3">
              Save a query from the editor and it’ll appear here so you can open and run it again.
            </p>
          </div>
        ) : (
          sorted.map((q) => {
            const preview = q.sql.replace(/\s+/g, ' ').trim();
            return (
              <div
                key={q.id}
                className="rounded-md border border-border p-3">
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="truncate font-semibold text-text">{q.name}</span>
                  <span
                    className="ml-auto flex-none text-xs text-text-3"
                    title={new Date(q.updatedAt).toLocaleString()}>
                    {formatRelativeTime(q.updatedAt)}
                  </span>
                </div>
                <p
                  className="truncate font-mono text-sm text-text-2"
                  title={preview}>
                  {preview}
                </p>
                <div className="mt-2 flex items-center gap-3">
                  <div className="flex-1" />
                  <button
                    type="button"
                    onClick={() => onOpen(q)}
                    aria-label={`Open saved query ${q.name}`}
                    className="rounded-sm px-1.5 py-0.5 text-xs font-semibold text-accent-text hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                    Open
                  </button>
                  <button
                    type="button"
                    onClick={() => setPendingDelete(q)}
                    aria-label={`Delete saved query ${q.name}`}
                    className="rounded-sm px-1.5 py-0.5 text-xs font-semibold text-danger hover:bg-danger-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger">
                    Delete
                  </button>
                </div>
              </div>
            );
          })
        )}
      </Drawer>

      {open && pendingDelete && (
        <ConfirmDialog
          title={`Delete “${pendingDelete.name}”?`}
          ariaLabel="Confirm delete saved query"
          confirmLabel="Delete"
          confirmVariant="danger"
          irreversible
          onConfirm={() => {
            onDelete(pendingDelete.id);
            setPendingDelete(null);
          }}
          onCancel={() => setPendingDelete(null)}>
          <p className="mt-3 text-sm text-text-2">
            This removes the saved query. Any open tab linked to it keeps its SQL but is no longer linked.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
