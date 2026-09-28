import {useId} from 'react';
import {Button} from '../../components/Button';
import {formatAbsoluteDate, formatBytes, formatCount} from '../../lib/format';
import type {ArchiveListing} from '../../types/archive.types';

type Props = {
  /** Where the list's read has got to. `error` is the receipt folder failing to list. */
  status: 'loading' | 'error' | 'ready';
  listings: ArchiveListing[];
  selectedId: string | null;
  onSelect: (archiveId: string) => void;
  /** Whether to say who archived each one — true in a shared space, where it can be anyone. */
  showArchivedBy: boolean;
  onRetry: () => void;
};

/** What an archive held, as a row names it: "reports/, q1.csv and 1 more". */
function contentsSummary(details: NonNullable<ArchiveListing['details']>): string {
  const named = details.items.map((item) => item.path).join(', ');
  const more = details.itemCount - details.items.length;
  return more > 0 ? `${named} and ${formatCount(more)} more` : named;
}

/** A row's title: the name, or what the archive held, or — unlabelled — the start of its id. */
function titleOf(listing: ArchiveListing): string {
  if (!listing.details) return `Archive ${listing.archiveId.slice(0, 8)}`;
  return listing.details.name ?? contentsSummary(listing.details);
}

/**
 * What the archive's last restore did, or null when there has been none.
 *
 * **Each sentence is about a RUN, never about the archive's condition** — the restore-message rule
 * the plane enforces over its notifications applies here too. Two restores of one archive can run
 * at once, so "the archive is intact" or "the archive is gone" would be a claim this list has no
 * way to know is still true; what the plane recorded is what a restore did, and when.
 */
function statusOf(listing: ArchiveListing): string | null {
  const restore = listing.details?.restore;
  if (!restore) return null;
  if (restore.status === 'restored') return `Restored ${formatAbsoluteDate(restore.updatedAt)}`;
  if (restore.status === 'requested') return `Restore requested ${formatAbsoluteDate(restore.requestedAt)}`;
  return `Last restore did not finish (${formatAbsoluteDate(restore.updatedAt)})`;
}

/**
 * The restore dialog's list of the space's archives, one radio per archive.
 *
 * **Only a `restored` row is disabled.** A completed restore put every file back, so a second one
 * would be refused — every destination is occupied — or find an archive the first one swept. A
 * `requested` row stays selectable for two reasons: it is the ordinary in-flight state, which
 * lasts hours, and a second request then is refused safely by the plane's destination guard; and
 * it is also what a restore that stopped before its last write leaves behind, where a disabled row
 * would be a dead end with no way to try again.
 *
 * An archive the index does not label is a row like any other, and restores exactly the same
 * way: its details are unavailable, and its whole id is shown so it can be matched to its receipt.
 *
 * Each radio's accessible name is the row's title, and the details and status are its
 * description, so a screen reader hears the name first and the rest on request.
 */
export function ArchiveList({status, listings, selectedId, onSelect, showArchivedBy, onRetry}: Props) {
  const groupId = useId();

  if (status === 'loading') {
    return (
      <p
        role="status"
        className="mt-2 text-sm text-text-2">
        Loading archives…
      </p>
    );
  }
  if (status === 'error') {
    return (
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <p
          role="alert"
          className="text-sm text-danger">
          Couldn’t load this space’s archives.
        </p>
        <Button
          size="sm"
          onClick={onRetry}>
          Try again
        </Button>
      </div>
    );
  }
  if (listings.length === 0) {
    return <p className="mt-2 text-sm text-text-2">This space has no archives yet.</p>;
  }

  return (
    // `min-w-0`: a fieldset's default minimum width is its content's, so one unbroken name or path
    // would widen the whole list past the dialog instead of wrapping.
    <fieldset className="mt-2 min-w-0">
      <legend className="sr-only">Archive to restore</legend>
      <ul className="space-y-2">
        {listings.map((listing) => {
          const {archiveId, details} = listing;
          const rowId = `${groupId}-${archiveId}`;
          const restored = details?.restore?.status === 'restored';
          const statusText = statusOf(listing);
          return (
            <li key={archiveId}>
              <label
                htmlFor={rowId}
                className={
                  'flex min-w-0 gap-3 rounded-md border border-border p-3 ' +
                  (restored ? 'cursor-not-allowed bg-surface-2' : 'cursor-pointer hover:bg-surface-2')
                }>
                <input
                  id={rowId}
                  type="radio"
                  name={`${groupId}-archive`}
                  value={archiveId}
                  checked={selectedId === archiveId}
                  disabled={restored}
                  onChange={() => onSelect(archiveId)}
                  aria-labelledby={`${rowId}-title`}
                  aria-describedby={`${rowId}-details${statusText ? ` ${rowId}-status` : ''}`}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
                />
                <span className="min-w-0 flex-1">
                  <span
                    id={`${rowId}-title`}
                    className="block break-words text-sm font-medium text-text">
                    {titleOf(listing)}
                  </span>
                  <span
                    id={`${rowId}-details`}
                    className="mt-0.5 block break-words text-xs text-text-2">
                    {details ? (
                      <>
                        Archived {formatAbsoluteDate(details.archivedAt)}
                        {details.name !== null && <> · {contentsSummary(details)}</>} · {formatCount(details.fileCount)}{' '}
                        {details.fileCount === 1 ? 'file' : 'files'}, {formatBytes(details.totalBytes)}
                        {showArchivedBy && <> · by {details.archivedBy}</>}
                      </>
                    ) : (
                      <>
                        Details unavailable · <span className="break-all font-mono">{archiveId}</span>
                      </>
                    )}
                  </span>
                  {statusText && (
                    <span
                      id={`${rowId}-status`}
                      className="mt-0.5 block text-xs font-medium text-text-2">
                      {statusText}
                    </span>
                  )}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
