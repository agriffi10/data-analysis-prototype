import type {ReactNode} from 'react';
import {Banner} from '../../components/Banner';
import {OperationSummaryBanner} from './OperationSummaryBanner';
import {BatchOverwritePrompt} from './BatchOverwritePrompt';
import {lastSegment} from './fileBrowser.paths';
import type {BulkOperationState} from './fileBrowser.types';

type OperationFeedbackProps = {
  op: BulkOperationState;
  /** Past tense for the summary: "Deleted", "Moved", "Copied". */
  pastVerb: string;
  /** Bare infinitive for the failure line: "delete", "move", "copy". */
  failVerb: string;
  /** Present participle for the progress line: "Moving", "Copying". Omit where the operation reports no progress. */
  progressVerb?: string;
  /**
   * Rendered between the progress line and the batch-overwrite prompt — the one slot
   * where an operation has a prompt of its own. Move's rename collision sits here, which
   * is exactly where it sat before these three stanzas were merged; without the slot the
   * merge would have moved it above or below the whole group.
   */
  children?: ReactNode;
};

/**
 * Everything a bulk file operation says to the user, in the order it says it:
 * a dismissible systemic error, the result summary with any per-item failures, a
 * live progress line, and the batch overwrite confirmation.
 *
 * `FileBrowser` rendered this same four-block stanza three times — once each for
 * delete, move and copy — differing only in the verbs and the field names the three
 * hooks happened to use. `BulkOperationState` settled the names; this settles the
 * markup, so a change to how a partial failure reads is one edit rather than three.
 *
 * Each block renders only when its state is present, so an operation that cannot
 * produce one (delete has no progress and no batch collision) passes `null` and
 * costs nothing.
 *
 * @example
 * <OperationFeedback op={move} pastVerb="Moved" failVerb="move" progressVerb="Moving" />
 */
export function OperationFeedback({op, pastVerb, failVerb, progressVerb, children}: OperationFeedbackProps) {
  return (
    <>
      {op.error && (
        <Banner
          variant="danger"
          onDismiss={op.dismissError}
          className="mb-4">
          {op.error}
        </Banner>
      )}

      {op.summary && (
        <OperationSummaryBanner
          pastVerb={pastVerb}
          failVerb={failVerb}
          count={op.summary.count}
          // The banner shows the leaf, not the whole key: a column of full prefixes
          // is unreadable, and the user picked these items by name.
          errors={op.summary.errors.map((e) => ({
            label: lastSegment(e.key),
            message: e.message,
            code: e.code
          }))}
          onDismiss={op.dismissSummary}
        />
      )}

      {op.isBusy && op.progress !== null && progressVerb && (
        <div
          role="status"
          className="mb-4 text-sm text-text-2">
          {progressVerb}… {op.progress}%
        </div>
      )}

      {children}

      {op.collision && (
        <BatchOverwritePrompt
          count={op.collision.count}
          onOverwriteAll={op.collision.onOverwriteAll}
          onCancel={op.collision.onCancel}
        />
      )}
    </>
  );
}
