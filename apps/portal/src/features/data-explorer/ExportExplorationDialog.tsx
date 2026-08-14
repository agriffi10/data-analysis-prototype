import {ConfirmDialog} from '../../components/ConfirmDialog';
import {SaveResultsDialog} from '../catalog/SaveResultsDialog';
import type {UseSaveResultsResult} from '../catalog/useSaveResults';

export type ExportExplorationDialogProps = {
  /** The save path, already pointed at this exploration's execution by the host. */
  saveResults: UseSaveResultsResult;
};

/**
 * Export this exploration's rows into a space (SPEC-185 FR-002).
 *
 * **Nothing here is new.** It is the Query workspace's own destination picker, overwrite
 * warn-and-confirm and cross-bucket copy, mounted on the other workspace — which is why
 * `useSaveResults` moved down to `features/catalog/` rather than being reimplemented here.
 * The Explorer may not import `features/query/` (SPEC-176's sibling clause), and a second
 * copy of a path with a collision round-trip in it is how the two come to disagree about
 * what happens when a name is taken.
 *
 * What export copies is the EXECUTION's results object, so a filtered, ordered or grouped
 * exploration exports exactly the rows on screen — every one of them, not just the loaded
 * page — with no second query and no second bill. That division is the whole reason copy
 * and export both exist: copy is the selection-shaped tool, export is the result-shaped one.
 */
export function ExportExplorationDialog({saveResults}: ExportExplorationDialogProps) {
  return (
    <>
      {/* The empty-list guard is the Query workspace's, kept verbatim: a picker with no
          destination is a dialog whose only honest state is its Cancel button. */}
      {saveResults.open && saveResults.spaces.length > 0 && (
        <SaveResultsDialog
          spaces={saveResults.spaces}
          defaultName={saveResults.defaultName}
          isBusy={saveResults.busy}
          onSave={saveResults.save}
          onCancel={saveResults.closeDialog}
        />
      )}
      {saveResults.overwritePrompt && (
        <ConfirmDialog
          title={`Overwrite “${saveResults.overwritePrompt.filename}”?`}
          ariaLabel="Confirm overwrite"
          confirmLabel="Overwrite"
          confirmVariant="danger"
          busy={saveResults.busy}
          busyLabel="Saving…"
          onConfirm={saveResults.confirmOverwrite}
          onCancel={saveResults.cancelOverwrite}>
          <p className="mt-3 text-sm text-text-2">
            A file named “{saveResults.overwritePrompt.filename}” already exists in that folder. Saving will replace it.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
