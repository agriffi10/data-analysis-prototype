import {ConfirmDialog} from '../../components/ConfirmDialog';
import {useDataQualityCheck, type DataQualityTarget} from './useDataQualityCheck';
import {SECTION_CAPTION} from '../../components/fieldStyles';

type DataQualityDialogProps = {
  /** What to check, and the space that holds it — passed straight to the enqueue. */
  target: DataQualityTarget;
  /** Whether `target.location` is one file or a folder of them; drives the wording only. */
  kind: 'file' | 'folder';
  /** The path as the user sees it in the browser (space root stripped by the caller). */
  displayPath: string;
  /** Called once the request has been enqueued — or has failed. See below. */
  onClose: () => void;
  /**
   * Called only when the request was actually enqueued, before `onClose`. The Files
   * browser clears the selection here: a cancelled or failed dialog must leave it
   * intact. Required, not optional — a new mount point should have to decide.
   */
  onStarted: () => void;
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
export function DataQualityDialog({target, kind, displayPath, onClose, onStarted}: DataQualityDialogProps) {
  const {start, isPending} = useDataQualityCheck();

  const handleConfirm = async () => {
    if (await start(target)) onStarted();
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
        <span className={SECTION_CAPTION}>{kind === 'folder' ? 'Folder' : 'File'}</span>
        <p className="mt-0.5 break-all rounded-md border border-border bg-surface-2 px-2.5 py-1.5 font-mono text-sm text-text">
          {displayPath}
        </p>
      </div>

      <p className="mt-3 text-sm text-text-2">
        This <strong className="font-semibold text-text">only reads</strong> your data
        {kind === 'folder' ? ' and every file in this folder' : ''}. Nothing is modified, moved, or deleted.
      </p>

      <p className="mt-2 text-sm text-text-2">
        The check runs in the background and can take a few minutes. You’ll get a notification when it finishes — with a
        link to the report — so you don’t need to keep this page open.
      </p>
    </ConfirmDialog>
  );
}
