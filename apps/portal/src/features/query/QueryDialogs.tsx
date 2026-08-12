import {ConfirmDialog} from '../../components/ConfirmDialog';
import {TableShareDialog, useTableShare} from '../table-share';
import {RefreshTableDialog, useTableRefresh} from '../table-builder';
import {ClearQueryDialog} from './ClearQueryDialog';
import {CloseTabDialog} from './CloseTabDialog';
import {TabLimitDialog} from './TabLimitDialog';
import {SaveQueryDialog} from './SaveQueryDialog';
import {CreateViewDialog} from './CreateViewDialog';
import {DropTableDialog} from './DropTableDialog';
import {SaveResultsDialog} from './SaveResultsDialog';
import type {GlueTableSummary, QueryTab} from './query.types';
import type {UseSaveResultsResult} from './useSaveResults';

type Props = {
  clear: {open: boolean; onConfirm: () => void; onCancel: () => void};
  save: {
    open: boolean;
    initialName: string;
    /** Where the file lands, named in the dialog before anything is replaced. */
    spaceLabel: string;
    /** The name whose file already exists — the replace confirm, or null. */
    collidingName: string | null;
    onSave: (name: string) => void;
    onReplace: (name: string) => void;
    onCancelReplace: () => void;
    onCancel: () => void;
  };
  /** The tab awaiting a close confirm (non-empty buffer), or null. */
  closing: {tab: QueryTab | null; onConfirm: () => void; onCancel: () => void};
  tabLimit: {open: boolean; onDismiss: () => void};
  createView: {
    open: boolean;
    busy: boolean;
    targetDatabase: string;
    onCreate: (name: string) => void;
    onCancel: () => void;
  };
  drop: {
    target: {database: string; table: GlueTableSummary} | null;
    busy: boolean;
    onConfirm: () => void;
    onCancel: () => void;
  };
  share: ReturnType<typeof useTableShare>;
  refresh: ReturnType<typeof useTableRefresh>;
  saveResults: UseSaveResultsResult;
};

/**
 * Every modal the query workspace can raise, in one mount point. Each is
 * conditionally rendered by its own open state — the workspace holds the state
 * and the handlers; this file holds the mounts.
 */
export function QueryDialogs({clear, save, closing, tabLimit, createView, drop, share, refresh, saveResults}: Props) {
  return (
    <>
      {clear.open && (
        <ClearQueryDialog
          onConfirm={clear.onConfirm}
          onCancel={clear.onCancel}
        />
      )}
      {save.open && (
        <SaveQueryDialog
          initialName={save.initialName}
          spaceLabel={save.spaceLabel}
          onSave={save.onSave}
          onCancel={save.onCancel}
        />
      )}
      {/* SPEC-173 FR-004: the collision is a HEAD on the exact key, so the confirm is
          raised by the WRITE's failure rather than by a scan of the loaded list. */}
      {save.collidingName !== null && (
        <ConfirmDialog
          title={`Replace “${save.collidingName}”?`}
          ariaLabel="Confirm replace saved query"
          confirmLabel="Replace"
          confirmVariant="danger"
          onConfirm={() => save.onReplace(save.collidingName as string)}
          onCancel={save.onCancelReplace}>
          <p className="mt-3 text-sm text-text-2">
            A saved query named “{save.collidingName}” already exists in that space. Saving will replace it with the
            current SQL.
          </p>
        </ConfirmDialog>
      )}
      {closing.tab && (
        <CloseTabDialog
          label={closing.tab.label}
          onConfirm={closing.onConfirm}
          onCancel={closing.onCancel}
        />
      )}
      {tabLimit.open && <TabLimitDialog onDismiss={tabLimit.onDismiss} />}
      {createView.open && (
        <CreateViewDialog
          busy={createView.busy}
          targetDatabase={createView.targetDatabase}
          onCreate={createView.onCreate}
          onCancel={createView.onCancel}
        />
      )}
      {share.target && (
        <TableShareDialog
          source={share.target}
          busy={share.busy}
          submitError={share.error}
          onSubmit={(args) => void share.submit(args)}
          onCancel={share.close}
        />
      )}
      {refresh.target && (
        <RefreshTableDialog
          target={refresh.target}
          busy={refresh.busy}
          submitError={refresh.error}
          onConfirm={(allowRemovals) => void refresh.submit(allowRemovals)}
          onCancel={refresh.close}
        />
      )}
      {drop.target && (
        <DropTableDialog
          table={drop.target.table.name}
          isDropping={drop.busy}
          isView={drop.target.table.tableType === 'VIRTUAL_VIEW'}
          onConfirm={drop.onConfirm}
          onCancel={drop.onCancel}
        />
      )}
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
