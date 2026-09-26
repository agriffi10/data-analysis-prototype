import {useMemo} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {useToast} from '../../components/toastContext';
import {SaveQueryDialog} from '../saved-queries/SaveQueryDialog';
import {useSaveQuery} from '../saved-queries/useSaveQuery';
import {savedQueryKeys} from '../saved-queries/savedQueryKeys';
import {appendViewLine} from '../../lib/savedViewLine';
import {buildSavedView} from './savedView';
import type {Exploration} from './dataExplorer.types';
import type {QuerySpace} from '../catalog/catalog.types';
import type {SavedQuery, SavedQueryLink} from '../saved-queries/savedQueries.types';

export type SaveExplorationDialogProps = {
  /**
   * The statement that produced the rows on screen — the body written.
   *
   * Handed down from `useExploration.sql`, the same string `StartQueryExecution` was given.
   * Re-rendering the description here would be a second rendering of it, and the two would
   * differ the moment either the description or the renderer moved between the run and the
   * save. The parent mounts this component only when there IS one.
   */
  sql: string;
  /**
   * The exploration as it was at the gesture, recorded in the file's view line so the Data
   * Explorer can reopen it. A statement source records none.
   */
  exploration: Exploration;
  /** Writable destinations, personal first — ALREADY view-gated by the caller. */
  spaces: QuerySpace[];
  /** The space remembered by `useSavedQuerySpace`, for a tab with no link. */
  defaultSpace: QuerySpace | null;
  /** The file this tab was last saved to, if any. What an unchanged re-save replaces. */
  link: SavedQueryLink | undefined;
  /** The write landed: link the tab, remember the space, close. */
  onSaved: (query: SavedQuery) => void;
  onClose: () => void;
};

/**
 * The Data Explorer's save flow: The dialog, its collision confirm, and the write.
 *
 * A thin host by design. Every rule about naming, destinations, collisions and in-place
 * replacement is the and lives in `useSaveQuery` — this feature is the second
 * caller, not a second implementation, which is the whole point of having taken
 * `{sql, link}` instead of a `QueryTab`.
 *
 * **Mounting IS the open state.** `useSaveQuery` carries an `open` flag for a host that
 * lives as long as its workspace does; here the parent mounts this component when the user
 * asks to save and unmounts it when they are done, so the form shows whenever there is no
 * collision pending and the confirm shows when there is. Reading the hook's flag as well
 * would give one dialog two sources of truth about whether it is on screen.
 */
export function SaveExplorationDialog({
  sql,
  exploration,
  spaces,
  defaultSpace,
  link,
  onSaved,
  onClose
}: SaveExplorationDialogProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  // Encoded once per statement and exploration, not on every keystroke in the name field.
  const {view, withView} = useMemo(() => {
    const built = buildSavedView(exploration);
    return {view: built, withView: built ? appendViewLine(sql, built) : null};
  }, [sql, exploration]);
  const save = useSaveQuery({
    spaces,
    defaultSpace,
    payload: {
      sql: withView ?? sql,
      link,
      // Only a view that was there to keep and did not fit: a statement source never has one.
      successNote: view && !withView ? 'The view was too large to keep, so it opens in Query only.' : undefined
    },
    toast,
    onSaved: (query) => {
      // The listing is cached for a while, and the drawer that reopens views reads it: without
      // this, a view saved a moment ago would be missing from it.
      void queryClient.invalidateQueries({queryKey: savedQueryKeys.list(query.spaceId)});
      onSaved(query);
    }
  });

  if (save.collision) {
    return (
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
          replace it with this exploration’s SQL.
        </p>
      </ConfirmDialog>
    );
  }

  return (
    <SaveQueryDialog
      initialName={save.initialName}
      spaces={save.spaces}
      initialSpace={save.initialSpace}
      linked={save.linked}
      error={save.error}
      busy={save.busy}
      onSave={save.save}
      onCancel={onClose}
    />
  );
}
