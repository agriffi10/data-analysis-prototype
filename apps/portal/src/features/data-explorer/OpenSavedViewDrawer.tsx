import {toUserText} from '../../lib/errorMessages';
import {formatBytes, formatRelativeTime} from '../../lib/format';
import {Banner} from '../../components/Banner';
import {Drawer} from '../../components/Drawer';
import {Pager} from '../../components/Pager';
import {SavedQuerySpaceSelect} from '../saved-queries/SavedQuerySpaceSelect';
import {useSavedQueries} from '../saved-queries/useSavedQueries';
import {useSavedQueriesPager} from '../saved-queries/useSavedQueriesPager';
import type {SavedQuery} from '../saved-queries/savedQueries.types';
import type {QuerySpace} from '../catalog/catalog.types';

type Props = {
  /** The spaces the table picker offers, personal first — already view-gated. */
  spaces: QuerySpace[];
  /** The remembered space, shared with every other saved-query surface. */
  space: QuerySpace | null;
  onSelectSpace: (spaceId: string) => void;
  /** The key of the file being opened, whose row is busy until it resolves. */
  openingKey: string | null;
  onOpen: (query: SavedQuery, space: QuerySpace) => void;
  onClose: () => void;
};

/**
 * The Data Explorer's list of saved queries to reopen as views.
 *
 * Built from the store's own pieces — its listing, pager and space select — rather than from
 * the Query workspace's drawer, which this feature may not import. Every `.sql` file is listed:
 * telling the ones that carry a view from the rest would mean reading every body, so a file
 * without one is refused when it is opened, not hidden here.
 *
 * **Mounting IS the open state**, as the save dialog's is: the listing is fetched only while
 * this is on screen, rather than on every render of the picker it opens from.
 */
export function OpenSavedViewDrawer({spaces, space, onSelectSpace, openingKey, onOpen, onClose}: Props) {
  const listing = useSavedQueries(space);
  const pager = useSavedQueriesPager({
    queries: listing.queries,
    hasMore: listing.hasMore,
    loadMore: listing.loadMore,
    isLoadingMore: listing.isLoadingMore,
    error: listing.error,
    resetKey: space?.id ?? '',
    enabled: true
  });

  const footer =
    !listing.isLoading && pager.page.length > 0 ? (
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
    <Drawer
      open
      onClose={onClose}
      title="Open saved view"
      footer={footer}>
      <SavedQuerySpaceSelect
        spaces={spaces}
        space={space}
        onSelectSpace={onSelectSpace}
        className="shrink-0 pb-1"
      />

      {!!listing.error && (
        <Banner
          variant="danger"
          title="Couldn’t load saved queries."
          retry={listing.refresh}>
          {toUserText(listing.error)}
        </Banner>
      )}

      {listing.isLoading || pager.isFilling ? (
        <p className="text-sm text-text-3">Loading saved queries&hellip;</p>
      ) : pager.isEmpty ? (
        listing.error ? null : (
          <p className="text-sm text-text-3">No saved queries in {space?.label ?? 'this space'} yet.</p>
        )
      ) : (
        pager.page.map((query) => (
          <div
            key={query.key}
            className="rounded-md border border-border p-3">
            <div className="mb-1.5 flex items-center gap-2">
              <span className="truncate font-semibold text-text">{query.name}</span>
              <span
                className="ml-auto flex-none text-xs text-text-3"
                title={new Date(query.updatedAt).toLocaleString()}>
                {formatRelativeTime(query.updatedAt)}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <p className="flex-1 text-sm text-text-3">{formatBytes(query.size)}</p>
              <button
                type="button"
                disabled={openingKey !== null}
                onClick={() => space && onOpen(query, space)}
                aria-label={`Open saved view ${query.name}`}
                className="min-h-[24px] rounded-sm px-1.5 py-0.5 text-xs font-semibold text-accent-text hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50">
                {openingKey === query.key ? 'Opening…' : 'Open'}
              </button>
            </div>
          </div>
        ))
      )}
    </Drawer>
  );
}
