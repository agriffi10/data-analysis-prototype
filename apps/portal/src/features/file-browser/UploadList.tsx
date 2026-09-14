import {IconButton} from '../../components/IconButton';
import {StatusPill, type StatusTone} from '../../components/StatusPill';
import {CollisionPrompt} from './CollisionPrompt';
import {useUploadQueue} from './uploadQueueContext';
import {uploadPercent} from './fileBrowser.service';
import {formatSize} from './fileBrowser.format';
import {leafName, fileExtension} from './fileBrowser.paths';
import {TERMINAL_STATUSES, type UploadItem, type UploadStatus} from './upload.types';
import {SECTION_CAPTION} from '../../components/fieldStyles';

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-3.5 w-3.5"
      aria-hidden="true">
      <path
        strokeLinecap="round"
        d="M2 2l12 12M14 2L2 14"
      />
    </svg>
  );
}

// Status as a colored dot + text chip, matching the shared-connections StatusBadge
// (feedback 2026-06-30): Uploading (amber, pulsing — in-progress, like
// "Provisioning…"), Uploaded (green), Failed (red), Queued/Cancelled (neutral).
// The label always carries the meaning, so color/dot is never the only signal (a11y).
const CHIP: Record<Exclude<UploadStatus, 'collision'>, {label: string; tone: StatusTone; pulse?: boolean}> = {
  queued: {label: 'Queued', tone: 'neutral'},
  uploading: {label: 'Uploading', tone: 'warning', pulse: true},
  done: {label: 'Uploaded', tone: 'success'},
  failed: {label: 'Failed', tone: 'danger'},
  cancelled: {label: 'Cancelled', tone: 'neutral'}
};

function StatusChip({status}: {status: Exclude<UploadStatus, 'collision'>}) {
  const {label, tone, pulse} = CHIP[status];
  return (
    <StatusPill
      tone={tone}
      pulse={pulse}>
      {label}
    </StatusPill>
  );
}

// The destination workspace is the first segment of the key (the username for the
// personal space, the shared-space name otherwise) — the same value the breadcrumb
// root and sidebar show. Returns null for a key with no prefix (dev/edge).
function workspaceFromKey(key: string): string | null {
  const i = key.indexOf('/');
  return i > 0 ? key.slice(0, i) : null;
}

// A small muted tag naming the workspace an upload is going to (feedback
// 2026-06-30) — useful now that uploads from different connections share one list.
function WorkspaceTag({name}: {name: string}) {
  return (
    <span className="inline-flex min-w-0 max-w-[55%] flex-none items-center gap-1 rounded-full bg-surface-2 px-1.5 py-0.5 text-xs font-medium text-text-2">
      <svg
        viewBox="0 0 20 20"
        fill="currentColor"
        className="h-3 w-3 shrink-0 text-text-3"
        aria-hidden="true">
        <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
      </svg>
      <span className="truncate">{name}</span>
    </span>
  );
}

function UploadRow({item}: {item: UploadItem}) {
  const {cancel, dismiss, resolveOverwrite, resolveRename} = useUploadQueue();
  const name = leafName(item.key);
  const workspace = workspaceFromKey(item.key);

  // Collision (warn-and-confirm): pause the row and reuse CollisionPrompt.
  // Cancelling it drops the item from the queue.
  if (item.status === 'collision') {
    return (
      <li className="px-3 pt-3">
        <p
          className="mb-1 truncate text-base font-medium text-text"
          title={name}>
          {name}
        </p>
        <CollisionPrompt
          kind="file"
          name={name}
          onOverwrite={() => resolveOverwrite(item.id)}
          onRename={(newName) => resolveRename(item.id, newName)}
          onCancel={() => cancel(item.id)}
        />
      </li>
    );
  }

  const isTerminal = TERMINAL_STATUSES.has(item.status);
  const percent = uploadPercent(item.loaded, item.total);

  const subtext =
    item.status === 'uploading'
      ? `${formatSize(item.loaded)} of ${formatSize(item.total)}`
      : item.status === 'failed'
        ? (item.error ?? 'Upload failed')
        : item.status === 'cancelled'
          ? 'Cancelled'
          : item.status === 'queued'
            ? 'Waiting…'
            : formatSize(item.total);

  return (
    <li className="group relative flex items-start gap-3 px-3 py-3 hover:bg-surface-2">
      {/* File-type chip, `h-7 w-7` (24.5px) */}
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-[10px] font-semibold text-text-2">
        {fileExtension(name, {fallback: 'FILE', maxLen: 4})}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p
            className="min-w-0 flex-1 truncate text-base font-medium text-text"
            title={name}>
            {name}
          </p>
          <StatusChip status={item.status} />
        </div>

        <div className="mt-0.5 flex items-center gap-1.5">
          {workspace && <WorkspaceTag name={workspace} />}
          <span
            className={`min-w-0 truncate text-sm ${item.status === 'failed' ? 'text-danger' : 'text-text-2'}`}
            title={item.status === 'failed' ? item.error : undefined}>
            {subtext}
          </span>
        </div>

        {/* `h-1.5` (5.25px) accent progress bar — only while uploading (design-system §5) */}
        {item.status === 'uploading' && (
          <div
            className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-border"
            role="progressbar"
            aria-label={`Uploading ${name}`}
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}>
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-200"
              style={{width: `${percent}%`}}
            />
          </div>
        )}
      </div>

      {/* Per-file cancel / dismiss — revealed on hover (and on focus, a11y) */}
      <div className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <IconButton
          label={isTerminal ? `Dismiss ${name}` : `Cancel upload of ${name}`}
          onClick={() => (isTerminal ? dismiss(item.id) : cancel(item.id))}>
          <CloseIcon />
        </IconButton>
      </div>
    </li>
  );
}

/**
 * The in-drawer uploads list (feedback 2026-06-30): sits under the upload field in
 * the Upload drawer, listing the session's uploads newest-first in a scrollable
 * list, each with a progress bar + status chip. Reads the SESSION-scoped queue
 * (UploadQueueProvider at the app shell), so it shows every upload of the session
 * and survives the drawer closing / connection switches. Renders nothing when the
 * queue is empty.
 *
 * @example
 * <UploadList />
 */
export function UploadList() {
  const {items, clearFinished} = useUploadQueue();
  if (items.length === 0) return null;

  const finishedCount = items.filter((i) => TERMINAL_STATUSES.has(i.status)).length;
  const activeCount = items.length - finishedCount;
  // Newest-first: the reducer appends, so reverse a shallow copy to show the most
  // recent upload at the top.
  const newestFirst = [...items].reverse();

  return (
    <section
      aria-label="Uploads"
      className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-surface">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-4">
        <h3 className={SECTION_CAPTION}>Uploads</h3>
        <span
          className="text-sm text-text-2"
          aria-live="polite">
          {activeCount > 0 ? `${activeCount} in progress` : 'Complete'}
        </span>
        <div className="flex-1" />
        {finishedCount > 0 && (
          <button
            type="button"
            className="rounded-md px-2 py-1 text-sm font-medium text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={clearFinished}
            aria-label="Clear finished uploads from the list">
            Clear finished
          </button>
        )}
      </header>

      <ul className="min-h-0 flex-1 divide-y divide-border-2 overflow-y-auto">
        {newestFirst.map((item) => (
          <UploadRow
            key={item.id}
            item={item}
          />
        ))}
      </ul>
    </section>
  );
}
