import {useEffect, useRef, useState} from 'react';
import {useFileBrowser} from './useFileBrowser';
import {toUserText} from '../../lib/errorMessages';
import type {SelectableItem} from './selectionContext';
import type {FileSpaceTarget} from './useFileSpace';
import {Button} from '../../components/Button';
import {cx} from '../../lib/cx';
import {PICKER_LOCKED_FOLDERS, isRootFolderNamed} from './protectedFolders';
import {SAVED_QUERIES_FOLDER} from './fileBrowser.constants';
import {UP_ONE_LEVEL_LABEL} from './ParentFolderRow';
import {useFeature} from '../feature-flags';
import {buildBreadcrumbs, parentPrefix} from './fileBrowser.paths';

type BaseProps = {
  bucket: string; // the SOURCE space's bucket (also the default destination)
  items: SelectableItem[]; // the items being moved/copied
  rootPrefix: string; // navigation floor (source space root)
  rootLabel?: string; // label for the root crumb (hides the username segment)
  currentPrefix: string; // the items' current parent
  startPrefix?: string; // the folder to open at, inside `rootPrefix`; the root when omitted
  isBusy?: boolean;
  // Connections the user can target (feedback 2026-06-30). When more than one is
  // given, a connection selector is shown and the destination can be another
  // connection's bucket. Defaults to source-only (no selector) when omitted.
  destinations?: FileSpaceTarget[];
  // Whether the items' current parent is a valid destination. Move forbids it
  // (a no-op); Copy allows it (→ same-folder auto-number). Only
  // meaningful when the destination is the source space (same bucket).
  allowCurrentParent?: boolean;
  // an extra gate the host controls (e.g. an invalid filename) — when
  // true the confirm button is disabled regardless of the destination validity.
  confirmDisabled?: boolean;
  confirmLabel: string; // e.g. "Move here" / "Copy here"
  busyLabel: string; // e.g. "Moving…" / "Copying…"
  // Message shown when the confirm action is blocked inside an operated folder's
  // own subtree (the verb differs: "move" vs "copy").
  selfMessage?: string;
  // Why the CURRENT folder is not a valid destination, shown when `allowCurrentParent` is off
  // and the user is standing in it. Defaulted to the move/copy wording the three original
  // callers rely on; overridden by any caller whose rule is a different one — Create table's
  // is that a table reads the whole folder, which has nothing to do with items already being
  // here. A prop rather than a second status line under the picker, because two competing
  // explanations of one disabled button is worse than the wrong one alone.
  currentParentMessage?: string;
  // The list's aria-label. "Destination folders" is wrong in a
  // mode where files are selectable and nothing is a "destination".
  listLabel?: string;
  // Claim initial focus once the listing settles. For a dialog whose
  // ENTIRE content is this picker (Move, Copy) — never where it is one section among
  // others the user may already be operating (Save results), because it remounts there.
  autoFocus?: boolean;
  // Fired on mount and on EVERY navigation/selection change, so
  // the caller can render the resolved target and compute a confirm label without
  // the picker giving up ownership of its browse state. Must be referentially
  // stable (useCallback) — it is an effect dependency.
  onTargetChange?: (target: {prefix: string; fileKey?: string}) => void;
  // `selectedFileKey` is APPENDED rather than folded into the first argument so the
  // three shipped callers (Move, Copy, Save results) compile and behave unchanged;
  // they ignore it.
  onConfirm: (destPrefix: string, destBucket: string, selectedFileKey?: string) => void;
  onCancel: () => void;
};

// The prefix marker used to need a caller-supplied key here, because in
// selectable-files mode an unfiltered `DO_NOT_DELETE.txt` sat at every space root
// as a selectable target. `useFileBrowser` hides every marker
// by basename, so the rule holds for every caller with nothing to pass.
type Props = BaseProps & {
  // Opt-in: render file rows as selectable buttons. Deliberately NOT defaulted
  // on — a file is never a valid move/copy/save destination, and flipping the
  // default would silently make one a valid paste target in three shipped
  // dialogs.
  selectableFiles?: boolean;
};

// Is this folder prefix an app-managed root folder (athenaresults/ results or
// user_settings/), which is never a valid move/copy destination? Only the
// user-root instance is locked.
//
// `locked` is composed by the caller rather than read from the constant, because
// One entry the FLAG decides: `saved_queries/` is an
// ordinary paste target, and a destination the user cannot see is not a
// destination.
function isProtectedFolder(folderPrefix: string, rootPrefix: string, locked: readonly string[]): boolean {
  return isRootFolderNamed(folderPrefix, rootPrefix, locked);
}

/**
 * The shared destination-folder picker used by both Move
 * and Copy. Lists only folders within the user's own space
 * (navigable), excludes the folders being operated on (can't descend into them)
 * and the protected `athenaresults/` folder (never a write destination), and
 * disables the confirm button inside an operated folder's own subtree (no
 * moving/copying a folder into itself). Whether the items' current parent is a
 * valid destination is caller-controlled (`allowCurrentParent`): Move forbids it,
 * Copy allows it (same-folder auto-number).
 *
 * An opt-in `selectableFiles` mode exists for the caller that targets
 * data rather than a destination (the data-quality dialog). There a file row can be
 * selected as the target, the resolved target is reported back via `onTargetChange`
 * (the picker keeps owning the browse state).
 *
 * @example
 * <DestinationPicker bucket={bucket} items={selected} rootPrefix="alice/" currentPrefix="alice/docs/" confirmLabel="Move here" busyLabel="Moving…" onConfirm={move} onCancel={close} />
 */
export function DestinationPicker({
  bucket,
  items,
  rootPrefix,
  rootLabel,
  currentPrefix,
  startPrefix,
  isBusy = false,
  destinations,
  allowCurrentParent = false,
  confirmDisabled = false,
  confirmLabel,
  busyLabel,
  selfMessage = "You can't copy a folder into itself.",
  currentParentMessage = 'These items are already here.',
  listLabel = 'Destination folders',
  autoFocus = false,
  selectableFiles = false,
  onTargetChange,
  onConfirm,
  onCancel
}: Props) {
  // The list of targetable connections. Falls back to the source space alone so
  // the picker works unchanged when no `destinations` are supplied.
  const options: FileSpaceTarget[] =
    destinations && destinations.length > 0
      ? destinations
      : [{id: 'source', bucket, rootPrefix, label: rootLabel ?? rootPrefix, kind: 'personal'}];
  // Default to the source space (matched by bucket + root), else the first option.
  const initial = options.find((o) => o.bucket === bucket && o.rootPrefix === rootPrefix) ?? options[0];
  const [destId, setDestId] = useState(initial.id);
  const active = options.find((o) => o.id === destId) ?? initial;
  const showSelector = options.length > 1;
  // True when the chosen destination is a different connection than the source —
  // the current-parent and into-itself guards (which key off source-space paths)
  // don't apply across buckets.
  const crossBucket = active.bucket !== bucket;

  // With `query` off the saved-queries folder is not offered as a
  // destination, alongside leaving the listing. Read here rather than drilled from
  // four dialogs — every picker in the app inherits the rule from one place.
  const queryEnabled = useFeature('query');
  const lockedFolders = queryEnabled ? PICKER_LOCKED_FOLDERS : [...PICKER_LOCKED_FOLDERS, SAVED_QUERIES_FOLDER];

  const [browsePrefix, setBrowsePrefix] = useState(startPrefix ?? initial.rootPrefix);
  // Selectable-files mode only. Null = the browsed folder is the target.
  const [selectedFileKey, setSelectedFileKey] = useState<string | null>(null);
  const {folders, files, isLoading, error, hasMore, loadMore, isLoadingMore} = useFileBrowser(
    active.bucket,
    browsePrefix
  );

  // Navigating ALWAYS clears the file selection. The target must be the thing the
  // confirm button says it is; a selection surviving a navigation would silently
  // confirm a file the user is no longer looking at.
  function navigateTo(prefix: string) {
    setBrowsePrefix(prefix);
    setSelectedFileKey(null);
  }

  const selectRef = useRef<HTMLSelectElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  function selectDestination(id: string) {
    const next = options.find((o) => o.id === id);
    if (!next) return;
    setDestId(id);
    navigateTo(next.rootPrefix); // switching connections resets to its root
  }

  // A DIALOG DRAWS FOCUS, and this picker is rendered straight into `Modal`'s panel by
  // Copy/Move rather than through `FormDialog`, so it gets no fallback from there —
  // `Modal`'s `initialFocus: false` would leave focus on the panel, a Tab away from the
  // list. OPT-IN, because the picker is not always the whole dialog: `SaveResultsDialog`
  // embeds it below its own fields and remounts it (`key={space.id}`) whenever the user
  // changes the Save-to select, so claiming focus there would yank it off the control
  // they are operating.
  //
  // Deferred until the listing settles, not fired on mount: at mount the list is still
  // loading and holds no buttons, so a mount-only effect would focus nothing for a user
  // with one space and the first folder for a user whose listing happened to be cached —
  // the same dialog behaving two ways. `focusClaimed` keeps it to once per mount, so
  // navigating into a folder never steals focus from the button just pressed.
  const focusClaimed = useRef(false);
  useEffect(() => {
    if (!autoFocus || focusClaimed.current || isLoading) return;
    const target = selectRef.current ?? listRef.current?.querySelector('button');
    if (!target) return;
    focusClaimed.current = true;
    target.focus();
  }, [autoFocus, isLoading]);

  useEffect(() => {
    onTargetChange?.({prefix: browsePrefix, fileKey: selectedFileKey ?? undefined});
  }, [browsePrefix, selectedFileKey, onTargetChange]);

  // Folders being operated on can't be navigated into (you can't move/copy a
  // folder inside itself), so hide them from the picker. The protected results
  // folder is also hidden — it is never a valid write destination.
  const operatedFolderPrefixes = new Set(items.filter((i) => i.type === 'folder').map((i) => i.prefix));
  const navigableFolders = folders.filter(
    (f) => !operatedFolderPrefixes.has(f.prefix) && !isProtectedFolder(f.prefix, active.rootPrefix, lockedFolders)
  );

  // The confirm action is invalid anywhere inside an operated folder's own
  // subtree, and (for Move) at the current parent — but only within the source
  // space; targeting another connection is always a fresh location.
  const intoOwnSubtree = !crossBucket && [...operatedFolderPrefixes].some((p) => browsePrefix.startsWith(p));
  const atCurrentParent = !crossBucket && browsePrefix === currentPrefix;
  const currentParentBlocked = atCurrentParent && !allowCurrentParent;
  // The one invalid target the picker can detect for free —
  // scoped to selectable-files mode, since an empty folder is a perfectly good
  // move/copy/save destination. Everything deeper (format, readability) stays
  // server-side. Not applied while the listing is still loading or errored, or an
  // in-flight page would read as "empty".
  const emptyFolderBlocked =
    selectableFiles && !isLoading && error === null && navigableFolders.length === 0 && files.length === 0;
  const canConfirm = !isBusy && !currentParentBlocked && !intoOwnSubtree && !confirmDisabled && !emptyFolderBlocked;
  const disabledReason = currentParentBlocked
    ? currentParentMessage
    : intoOwnSubtree
      ? selfMessage
      : emptyFolderBlocked
        ? "There's nothing here to check. Open a folder that has files in it."
        : undefined;

  const crumbs = buildBreadcrumbs(browsePrefix, active.rootPrefix, active.label);

  return (
    <>
      {showSelector && (
        <div className="mt-3">
          <label
            htmlFor="dest-connection"
            className="mb-1 block text-sm font-medium text-text-2">
            Destination connection
          </label>
          <select
            ref={selectRef}
            id="dest-connection"
            className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            value={destId}
            onChange={(e) => selectDestination(e.target.value)}
            disabled={isBusy}>
            {options.map((o) => (
              <option
                key={o.id}
                value={o.id}>
                {o.label}
                {o.kind === 'shared' ? ' (shared)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Destination breadcrumb */}
      <nav
        aria-label="destination breadcrumb"
        className="mt-1">
        <ol className="flex flex-wrap items-center gap-1 text-sm text-text-2">
          {crumbs.map((crumb, i) => {
            const isLast = i === crumbs.length - 1;
            return (
              <li
                key={crumb.prefix}
                className="flex items-center gap-1">
                {i > 0 && (
                  <span
                    aria-hidden="true"
                    className="mx-0.5 text-text-3">
                    /
                  </span>
                )}
                {isLast ? (
                  <span
                    aria-current="page"
                    className="font-medium text-text">
                    {crumb.label}
                  </span>
                ) : (
                  <button
                    // Both floors are the 24 CSS px pointer-target threshold, absolute because it
                    // is a threshold and not a step on the rem-derived scale. Width matters too:
                    // a one-character folder draws a 7px box, and this trail wraps, so two of
                    // them land 22.8px apart — inside each other's 24px circle.
                    className="min-h-[24px] min-w-[24px] hover:text-text hover:underline"
                    // A crumb's prefix is only `undefined` in the unclamped dev-unauth
                    // breadcrumb, which this picker never renders — it always has a
                    // space root. Falling back to the root keeps the clamp total.
                    onClick={() => navigateTo(crumb.prefix ?? active.rootPrefix)}>
                    {crumb.label}
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      </nav>

      {/* Folder picker */}
      <div className="mt-4">
        <div className="max-h-64 overflow-y-auto rounded-md border border-border bg-surface">
          {isLoading && (
            <p
              role="status"
              aria-label="Loading"
              className="py-4 text-center text-sm text-text-3">
              Loading…
            </p>
          )}
          {!isLoading && error !== null && (
            <p
              role="alert"
              className="p-4 text-sm text-danger">
              {toUserText(error)}
            </p>
          )}
          {!isLoading && error === null && navigableFolders.length === 0 && files.length === 0 && (
            <p className="py-4 text-center text-sm text-text-3">This folder is empty.</p>
          )}
          <ul
            ref={listRef}
            aria-label={listLabel}>
            {/* Parent-folder row: climb back up toward the
                root. Shown only below the navigation floor. */}
            {browsePrefix !== active.rootPrefix && (
              <li>
                <button
                  className="flex h-10 w-full cursor-pointer items-center gap-2 px-3 text-left text-sm text-text-2 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
                  onClick={() => navigateTo(parentPrefix(browsePrefix, active.rootPrefix))}
                  aria-label={UP_ONE_LEVEL_LABEL}>
                  <svg
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    className="h-4 w-4 shrink-0 text-text-3"
                    aria-hidden="true">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M4 10l4-4m-4 4l4 4m-4-4h8a4 4 0 014 4v2"
                    />
                  </svg>
                  <span className="flex-1 truncate">..</span>
                </button>
              </li>
            )}
            {navigableFolders.map((folder) => (
              <li key={folder.prefix}>
                <button
                  className="flex h-10 w-full cursor-pointer items-center gap-2 px-3 text-left text-sm text-text hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
                  onClick={() => navigateTo(folder.prefix)}
                  aria-label={`Open folder ${folder.name}`}>
                  <svg
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    className="h-4 w-4 shrink-0 text-accent"
                    aria-hidden="true">
                    <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                  </svg>
                  <span className="flex-1 truncate">{folder.name}</span>
                </button>
              </li>
            ))}
            {/* Files in the browsed folder are shown so the destination's existing
                contents are visible. By DEFAULT they are non-interactive, muted rows
                — you pick a folder, not a file (feedback 2026-06-30). Under
                `selectableFiles` they become toggle buttons: selecting one
                makes it the target, clicking it again returns the target to the
                browsed folder. */}
            {files.map((file) => {
              const selected = selectedFileKey === file.key;
              const icon = (
                <svg
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className={cx('h-4 w-4 shrink-0', selected ? 'text-accent' : 'text-text-3')}
                  aria-hidden="true">
                  <path d="M4 4a2 2 0 012-2h5.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
                </svg>
              );
              return (
                <li key={file.key}>
                  {selectableFiles ? (
                    <button
                      aria-pressed={selected}
                      aria-label={`Select file ${file.name}`}
                      onClick={() => setSelectedFileKey(selected ? null : file.key)}
                      className={cx(
                        'flex h-10 w-full cursor-pointer items-center gap-2 px-3 text-left text-sm hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent',
                        selected ? 'bg-accent-soft font-medium text-accent-text' : 'text-text'
                      )}>
                      {icon}
                      <span className="flex-1 truncate">{file.name}</span>
                    </button>
                  ) : (
                    <div
                      aria-disabled="true"
                      className="flex h-10 w-full items-center gap-2 px-3 text-left text-sm text-text-3">
                      {icon}
                      <span className="flex-1 truncate">{file.name}</span>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {hasMore && (
            <div className="p-2 text-center">
              <button
                className="h-8 rounded-md px-3 text-sm text-text-2 hover:bg-surface-2 disabled:opacity-45"
                onClick={loadMore}
                disabled={isLoadingMore}>
                {isLoadingMore ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </div>

        {disabledReason && (
          <p
            id="dest-disabled-reason"
            role="status"
            className="mt-2 text-xs text-text-3">
            {disabledReason}
          </p>
        )}
      </div>

      <div className="-mx-5 -mb-4 mt-4 flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
        <Button
          variant="ghost"
          onClick={onCancel}
          disabled={isBusy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={() => onConfirm(browsePrefix, active.bucket, selectedFileKey ?? undefined)}
          disabled={!canConfirm}
          aria-describedby={disabledReason ? 'dest-disabled-reason' : undefined}>
          {isBusy ? busyLabel : confirmLabel}
        </Button>
      </div>
    </>
  );
}
