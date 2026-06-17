import { IconButton } from '../../components/IconButton';
import { CollisionPrompt } from './CollisionPrompt';
import { useUploadQueue } from './uploadQueueContext';
import { uploadPercent } from './fileBrowser.service';
import { TERMINAL_STATUSES, type UploadItem } from './upload.types';

// Human-readable byte size (mirrors FileBrowser's formatter; queue subtext only).
function formatSize(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
}

function leafName(key: string): string {
  return key.split('/').pop() || key;
}

// Uppercased extension for the file-type chip, or "FILE" when there's none.
function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  if (dot <= 0 || dot === name.length - 1) return 'FILE';
  return name.slice(dot + 1).toUpperCase().slice(0, 4);
}

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-3.5 w-3.5"
      aria-hidden="true"
    >
      <path strokeLinecap="round" d="M2 2l12 12M14 2L2 14" />
    </svg>
  );
}

// Right-aligned status text — design-system §5: ✓ Done (success), 62% (accent),
// Queued (muted), plus Failed (danger) and Cancelled (muted). Never color-only:
// each carries text (and Done a check icon), per the accessibility notes.
function StatusLabel({ item }: { item: UploadItem }) {
  switch (item.status) {
    case 'uploading':
      return (
        <span className="text-sm font-semibold text-accent-text tabular-nums">
          {uploadPercent(item.loaded, item.total)}%
        </span>
      );
    case 'done':
      return (
        <span className="flex items-center gap-1 text-sm font-medium text-success">
          <svg viewBox="0 0 16 16" fill="currentColor" className="h-3.5 w-3.5" aria-hidden="true">
            <path
              fillRule="evenodd"
              d="M13.78 4.22a.75.75 0 010 1.06l-6 6a.75.75 0 01-1.06 0l-3-3a.75.75 0 111.06-1.06L7.25 9.69l5.47-5.47a.75.75 0 011.06 0z"
              clipRule="evenodd"
            />
          </svg>
          Done
        </span>
      );
    case 'queued':
      return <span className="text-sm text-text-3">Queued</span>;
    case 'failed':
      return <span className="text-sm font-medium text-danger">Failed</span>;
    case 'cancelled':
      return <span className="text-sm text-text-3">Cancelled</span>;
    default:
      return null;
  }
}

function QueueCard({ item }: { item: UploadItem }) {
  const { cancel, dismiss, resolveOverwrite, resolveRename } = useUploadQueue();
  const name = leafName(item.key);

  // Collision (SPEC-016 warn-and-confirm): pause the card and reuse CollisionPrompt.
  // Cancelling it drops the item from the queue (FR-003).
  if (item.status === 'collision') {
    return (
      <li className="px-3 pt-3">
        <p className="mb-1 truncate text-base font-medium text-text" title={name}>
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
      <span className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-[10px] font-semibold text-text-2">
        {fileExtension(name)}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1 truncate text-base font-medium text-text" title={name}>
            {name}
          </p>
          <StatusLabel item={item} />
        </div>

        <p
          className={`mt-0.5 truncate text-sm ${item.status === 'failed' ? 'text-danger' : 'text-text-2'}`}
          title={item.status === 'failed' ? item.error : undefined}
        >
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
            aria-valuemax={100}
          >
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-200"
              style={{ width: `${percent}%` }}
            />
          </div>
        )}
      </div>

      {/* Per-file cancel / dismiss — revealed on hover (and on focus, a11y) */}
      <div className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <IconButton
          label={isTerminal ? `Dismiss ${name}` : `Cancel upload of ${name}`}
          onClick={() => (isTerminal ? dismiss(item.id) : cancel(item.id))}
        >
          <CloseIcon />
        </IconButton>
      </div>
    </li>
  );
}

// SPEC-020 FR-003: a non-blocking, floating queue panel (bottom-right). Renders
// nothing when the queue is empty; while present, the user can keep browsing and
// navigating — it never traps focus behind a scrim (unlike the modal upload
// drawer). Uses the design-system §5 queue-card treatment.
export function UploadQueuePanel() {
  const { items, clearFinished } = useUploadQueue();
  if (items.length === 0) return null;

  const finishedCount = items.filter((i) => TERMINAL_STATUSES.has(i.status)).length;
  const activeCount = items.length - finishedCount;

  return (
    <section
      aria-label="Upload queue"
      className="fixed bottom-4 right-4 z-30 flex max-h-[70vh] w-[380px] flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-lg"
    >
      <header className="flex h-11 flex-shrink-0 items-center gap-2 border-b border-border px-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-text-3">
          Uploads
        </h2>
        <span className="text-sm text-text-2" aria-live="polite">
          {activeCount > 0 ? `${activeCount} in progress` : 'Complete'}
        </span>
        <div className="flex-1" />
        {finishedCount > 0 && (
          <button
            type="button"
            className="rounded-md px-2 py-1 text-sm font-medium text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none"
            onClick={clearFinished}
          >
            Clear finished
          </button>
        )}
      </header>

      <ul className="flex-1 divide-y divide-border-2 overflow-y-auto">
        {items.map((item) => (
          <QueueCard key={item.id} item={item} />
        ))}
      </ul>
    </section>
  );
}
