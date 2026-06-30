import {IconButton} from '../../components/IconButton';
import {CollisionPrompt} from './CollisionPrompt';
import {useUploadQueue} from './uploadQueueContext';
import {uploadPercent} from './fileBrowser.service';
import {formatSize} from './fileBrowser.format';
import {leafName, fileExtension} from './fileBrowser.paths';
import {TERMINAL_STATUSES, type UploadItem, type UploadStatus} from './upload.types';

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
const CHIP: Record<Exclude<UploadStatus, 'collision'>, {label: string; tone: string; pulse?: boolean}> = {
  queued: {label: 'Queued', tone: 'bg-surface-2 text-text-2'},
  uploading: {label: 'Uploading', tone: 'bg-warning-soft text-warning', pulse: true},
  done: {label: 'Uploaded', tone: 'bg-success-soft text-success'},
  failed: {label: 'Failed', tone: 'bg-danger-soft text-danger'},
  cancelled: {label: 'Cancelled', tone: 'bg-surface-2 text-text-2'}
};

function StatusChip({status}: {status: Exclude<UploadStatus, 'collision'>}) {
  const {label, tone, pulse} = CHIP[status];
  return (
    <span
      className={`inline-flex flex-none items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}>
      <span className={`h-[7px] w-[7px] rounded-full bg-current ${pulse ? 'animate-pulse' : ''}`} />
      {label}
    </span>
  );
}

function UploadRow({item}: {item: UploadItem}) {
  const {cancel, dismiss, resolveOverwrite, resolveRename} = useUploadQueue();
  const name = leafName(item.key);

  // Collision (SPEC-016 warn-and-confirm): pause the row and reuse CollisionPrompt.
  // Cancelling it drops the item from the queue (FR-003).
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
      {/* File-type chip (28px) */}
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

        <p
          className={`mt-0.5 truncate text-sm ${item.status === 'failed' ? 'text-danger' : 'text-text-2'}`}
          title={item.status === 'failed' ? item.error : undefined}>
          {subtext}
        </p>

        {/* 6px accent progress bar — only while uploading (design-system §5) */}
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

// The in-drawer uploads list (feedback 2026-06-30): sits under the upload field in
// the Upload drawer, listing the session's uploads newest-first in a scrollable
// list, each with a progress bar + status chip. Reads the SESSION-scoped queue
// (UploadQueueProvider at the app shell), so it shows every upload of the session
// and survives the drawer closing / connection switches. Renders nothing when the
// queue is empty.
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
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-3">Uploads</h3>
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
