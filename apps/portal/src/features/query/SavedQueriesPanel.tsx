import {useState} from 'react';
import {toUserText} from '../../lib/errorMessages';
import {Banner} from '../../components/Banner';
import {Drawer} from '../../components/Drawer';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {DocumentIcon} from '../../components/icons';
import {formatRelativeTime} from '../../lib/format';
import {formatBytes} from './query.format';
import type {SavedQuery} from './query.types';

type Props = {
  open: boolean;
  onClose: () => void;
  queries: SavedQuery[];
  isLoading: boolean;
  /** The raw fetch error (or null); rendered via `toUserMessage`. */
  error: unknown;
  /** Further listing pages exist. */
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
  onOpen: (query: SavedQuery) => void;
  /** Parent removes the query and unlinks any open tab. */
  onDelete: (query: SavedQuery) => void;
};

/**
 * Saved-queries drawer, in S3's own listing order, with Open (→ new linked tab) and
 * Delete (→ confirm). The delete confirm owns Escape while open.
 *
 * SPEC-173 FR-006: a row is name + last-modified + size and carries **no SQL preview**.
 * That is a deliberate, user-visible loss — a `.sql` file holds no metadata, so a
 * preview would mean a `GetObject` per row on every open: twenty-five round trips to
 * show twenty-five one-line snippets. The body is fetched only when a query is opened.
 */
export function SavedQueriesPanel({
  open,
  onClose,
  queries,
  isLoading,
  error,
  hasMore,
  loadMore,
  isLoadingMore,
  onOpen,
  onDelete
}: Props) {
  const [pendingDelete, setPendingDelete] = useState<SavedQuery | null>(null);

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        title="Saved queries">
        {error ? (
          <Banner
            variant="danger"
            title="Couldn’t load saved queries.">
            {toUserText(error)}
          </Banner>
        ) : isLoading ? (
          <p className="text-sm text-text-3">Loading saved queries&hellip;</p>
        ) : queries.length === 0 && !hasMore ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
            <DocumentIcon className="h-8 w-8 text-text-3" />
            <p className="text-sm font-medium text-text">No saved queries yet</p>
            <p className="max-w-[260px] text-sm text-text-3">
              Save a query from the editor and it’ll appear here so you can open and run it again.
            </p>
          </div>
        ) : (
          <>
            {queries.map((q) => (
              <div
                key={q.key}
                className="rounded-md border border-border p-3">
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="truncate font-semibold text-text">{q.name}</span>
                  <span
                    className="ml-auto flex-none text-xs text-text-3"
                    title={new Date(q.updatedAt).toLocaleString()}>
                    {formatRelativeTime(q.updatedAt)}
                  </span>
                </div>
                <p className="text-sm text-text-3">{formatBytes(q.size)}</p>
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
            ))}
            {/* An S3 page and a display page are different things: a listing page of 25
                keys can hold no `.sql` file at all, so a folder of CSVs must not read as
                empty with nothing to press. SPEC-174 replaces this with a real pager. */}
            {hasMore && (
              <div className="pt-1 text-center">
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={isLoadingMore}
                  className="h-8 rounded-md border border-border px-3 text-sm font-medium text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                  {isLoadingMore ? 'Loading…' : 'Load more'}
                </button>
              </div>
            )}
          </>
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
            onDelete(pendingDelete);
            setPendingDelete(null);
          }}
          onCancel={() => setPendingDelete(null)}>
          <p className="mt-3 text-sm text-text-2">
            This deletes the file. Any open tab linked to it keeps its SQL but is no longer linked.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
