import {useState} from 'react';
import {toUserText} from '../../lib/errorMessages';
import {Banner} from '../../components/Banner';
import {Drawer} from '../../components/Drawer';
import {Pager} from '../../components/Pager';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {DocumentIcon} from '../../components/icons';
import {formatRelativeTime} from '../../lib/format';
import {formatBytes} from '../../lib/format';
import {SavedQuerySpaceSelect} from '../saved-queries/SavedQuerySpaceSelect';
import {useSavedQueriesPager} from '../saved-queries/useSavedQueriesPager';
import type {SavedQuery} from '../saved-queries/savedQueries.types';
import type {QuerySpace} from '../catalog/catalog.types';

type Props = {
  open: boolean;
  onClose: () => void;
  /** Every space the user may load from, personal first. */
  spaces: QuerySpace[];
  space: QuerySpace | null;
  onSelectSpace: (spaceId: string) => void;
  queries: SavedQuery[];
  isLoading: boolean;
  /** The raw fetch error (or null); rendered via `toUserMessage`. */
  error: unknown;
  /** Further listing pages exist. */
  hasMore: boolean;
  onLoadMore: () => void;
  isLoadingMore: boolean;
  onRetry: () => void;
  onOpen: (query: SavedQuery) => void;
  /** Parent removes the query and unlinks any open tab. */
  onDelete: (query: SavedQuery) => void;
};

/**
 * Saved-queries drawer: a space selector, then that space's `.sql` files a page at a
 * time, with Open (→ new linked tab) and Delete (→ confirm). The delete confirm owns
 * Escape while open.
 *
 * the selector renders ABOVE every body state, so a space the user can
 * no longer reach is an error about *that space* — they pick another and carry on —
 * rather than a broken drawer.
 *
 * a row is name + last-modified + size and carries **no SQL preview**.
 * That is a deliberate, user-visible loss — a `.sql` file holds no metadata, so a
 * preview would mean a `GetObject` per row on every open: twenty-five round trips to
 * show twenty-five one-line snippets. The body is fetched only when a query is opened.
 */
export function SavedQueriesPanel({
  open,
  onClose,
  spaces,
  space,
  onSelectSpace,
  queries,
  isLoading,
  error,
  hasMore,
  onLoadMore,
  isLoadingMore,
  onRetry,
  onOpen,
  onDelete
}: Props) {
  const [pendingDelete, setPendingDelete] = useState<SavedQuery | null>(null);
  const pager = useSavedQueriesPager({
    queries,
    hasMore,
    loadMore: onLoadMore,
    isLoadingMore,
    error,
    // Reopening the drawer, and choosing another space, both start at page 1.
    resetKey: `${open ? 'open' : 'closed'}:${space?.id ?? ''}`,
    enabled: open
  });

  // The pager follows the ROWS, not the error: a load-more that fails must not take the
  // rows the user already has, and Prev has to remain reachable.
  const footer =
    !isLoading && pager.page.length > 0 ? (
      <Pager
        className="shrink-0 border-t border-border px-5 py-4"
        hasPrev={pager.hasPrev}
        hasNext={pager.hasNext}
        onPrev={pager.onPrev}
        onNext={pager.onNext}
        nextBusy={pager.isFetching}
        label={pager.label}
      />
    ) : undefined;

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        title="Saved queries"
        footer={footer}>
        <SavedQuerySpaceSelect
          spaces={spaces}
          space={space}
          onSelectSpace={onSelectSpace}
          className="shrink-0 pb-1"
        />

        {/* Above the list and never instead of it: a failed page keeps every row already
            loaded, so pressing Next at the end of a listing is non-destructive. */}
        {!!error && (
          <Banner
            variant="danger"
            title="Couldn’t load saved queries.">
            {toUserText(error)}
            <div className="pt-2">
              <button
                type="button"
                onClick={onRetry}
                className="h-8 rounded-md border border-border px-3 text-sm font-medium text-text-2 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                Retry
              </button>
            </div>
          </Banner>
        )}

        {isLoading || pager.isFilling ? (
          <p className="text-sm text-text-3">Loading saved queries&hellip;</p>
        ) : pager.isEmpty ? (
          // Never an empty state and an error at once — the banner above has
          // already said why there is nothing.
          error ? null : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
              <DocumentIcon className="h-8 w-8 text-text-3" />
              <p className="text-sm font-medium text-text">No saved queries in {space?.label ?? 'this space'}</p>
              <p className="max-w-[260px] text-sm text-text-3">
                Save a query from the editor and it’ll appear here so you can open and run it again.
              </p>
            </div>
          )
        ) : (
          pager.page.map((q) => (
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
          ))
        )}
      </Drawer>

      {open && pendingDelete && (
        <SavedQueryDeleteConfirm
          query={pendingDelete}
          onConfirm={() => {
            onDelete(pendingDelete);
            setPendingDelete(null);
          }}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </>
  );
}

/**
 * The warn-and-confirm both saved-queries surfaces raise before a delete — one wording,
 * so the drawer and the mobile card cannot drift apart about what a delete costs.
 */
export function SavedQueryDeleteConfirm({
  query,
  onConfirm,
  onCancel
}: {
  query: SavedQuery;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <ConfirmDialog
      title={`Delete “${query.name}”?`}
      ariaLabel="Confirm delete saved query"
      confirmLabel="Delete"
      confirmVariant="danger"
      irreversible
      onConfirm={onConfirm}
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">
        This deletes the file. Any open tab linked to it keeps its SQL but is no longer linked.
      </p>
    </ConfirmDialog>
  );
}
