import {ConfirmDialog} from '../../components/ConfirmDialog';
import {useDataQualityCheck, type DataQualityTarget} from './useDataQualityCheck';

type DataQualityDialogProps = {
  /** What to check, and the space that holds it — passed straight to the enqueue. */
  target: DataQualityTarget;
  /** Whether `target.location` is one file or a folder of them; drives the wording only. */
  kind: 'file' | 'folder';
  /** The path as the user sees it in the browser (space root stripped by the caller). */
  displayPath: string;
  /** Called once the request has been enqueued — or has failed. See below. */
  onClose: () => void;
};

/**
 * Warn-and-confirm for "Check data quality", composed on the shared `ConfirmDialog`
 * (so focus trapping, Escape, and focus return are inherited, not re-solved).
 *
 * It closes on failure as well as success: there is nothing to re-enter here, so keeping it
 * open would leave the user on a dialog whose only remaining move is Cancel. The failure
 * reaches them as a danger toast from `useDataQualityCheck` instead.
 *
 * The reassurance is load-bearing, not padding — this is the one place a user decides
 * whether to point a background job at their data, and the honest answer is that it only
 * reads.
 */
export function DataQualityDialog({target, kind, displayPath, onClose}: DataQualityDialogProps) {
  const {start, isPending} = useDataQualityCheck();

  const handleConfirm = async () => {
    await start(target);
    onClose();
  };

  return (
    <ConfirmDialog
      title="Check data quality?"
      ariaLabel="Confirm data quality check"
      confirmLabel="Start check"
      busy={isPending}
      busyLabel="Starting…"
      onConfirm={handleConfirm}
      onCancel={onClose}>
      <div className="mt-3">
        <span className="text-xs font-medium uppercase tracking-wide text-text-2">
          {kind === 'folder' ? 'Folder' : 'File'}
        </span>
        <p className="mt-0.5 break-all rounded-md border border-border bg-surface-2 px-2.5 py-1.5 font-mono text-sm text-text">
          {displayPath}
        </p>
      </div>

      <p className="mt-3 text-sm text-text-2">
        This <strong className="font-semibold text-text">only reads</strong> your data
        {kind === 'folder' ? ' and every file in this folder' : ''}. Nothing is modified, moved, or deleted.
      </p>

      {/* Deliberately does NOT promise a notification. The data-quality notification
          producer is SPEC-114 and is not built — `dq_notify_failure` is still a
          SPEC-108 pass-through stub and there is no success emitter — so a check today
          completes silently. Restore the "you'll be notified" wording as part of
          SPEC-114, not before. */}
      <p className="mt-2 text-sm text-text-2">
        The check runs in the background and can take a few minutes. It writes a report when it finishes; you don’t need
        to keep this page open.
      </p>
    </ConfirmDialog>
  );
}
