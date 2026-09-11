import {ConfirmDialog} from '../../components/ConfirmDialog';
import {TableShareDialog, useTableShare} from '../table-share';
import {RefreshTableDialog, useTableRefresh} from '../table-builder';
import {ClearQueryDialog} from './ClearQueryDialog';
import {CloseTabDialog} from './CloseTabDialog';
import {TabLimitDialog} from './TabLimitDialog';
import {SaveQueryDialog} from '../saved-queries/SaveQueryDialog';
import {CreateViewDialog} from '../catalog/CreateViewDialog';
import {DropTableDialog} from './DropTableDialog';
import {SaveResultsDialog} from '../catalog/SaveResultsDialog';
import type {QueryTab} from './query.types';
import type {GlueTableSummary} from '../catalog/catalog.types';
import type {UseSaveResultsResult} from '../catalog/useSaveResults';
import type {UseSaveQueryResult} from '../saved-queries/useSaveQuery';

type Props = {
  clear: {open: boolean; onConfirm: () => void; onCancel: () => void};
  save: UseSaveQueryResult;
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
          // Remounted per open, so the space control re-defaults each time.
          initialName={save.initialName}
          spaces={save.spaces}
          initialSpace={save.initialSpace}
          linked={save.linked}
          error={save.error}
          busy={save.busy}
          onSave={save.save}
          onCancel={save.closeDialog}
        />
      )}
      {/* the collision is a HEAD on the exact key, so the confirm is
          raised by the WRITE's failure rather than by a scan of the loaded list. It names
          the SPACE as well as the query — the destination is a choice, so
          "already exists" without a where is half an answer. */}
      {save.collision && (
        <ConfirmDialog
          title={`Replace “${save.collision.name}”?`}
          ariaLabel="Confirm replace saved query"
          confirmLabel="Replace"
          confirmVariant="danger"
          busy={save.busy}
          busyLabel="Saving…"
          onConfirm={save.confirmReplace}
          onCancel={save.cancelReplace}>
          <p className="mt-3 text-sm text-text-2">
            A saved query named “{save.collision.name}” already exists in {save.collision.space.label}. Saving will
            replace it with the current SQL.
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
          initial={saveResults.initial}
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
