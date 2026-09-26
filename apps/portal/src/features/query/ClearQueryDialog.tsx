import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  /** The saved query this tab is linked to, which Clear unlinks — the one part Ctrl/Cmd+Z does not restore. */
  linkedName?: string;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * Warn-and-confirm before Clear wipes the editor, focus defaulting to Cancel.
 *
 * Not `irreversible`: the editor takes the cleared value as an undoable edit, so Ctrl/Cmd+Z brings
 * the SQL straight back, and "This can’t be undone" would be false of it. The tab's saved-query
 * link and its label are reset too, and undo restores neither, so a linked tab says so.
 */
export function ClearQueryDialog({linkedName, onConfirm, onCancel}: Props) {
  return (
    <ConfirmDialog
      title="Clear the query?"
      ariaLabel="Confirm clear query"
      confirmLabel="Clear"
      confirmVariant="danger"
      tone="danger"
      onConfirm={onConfirm}
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">
        This empties the editor and discards the draft saved for this session.
        {linkedName && ` It also unlinks this tab from “${linkedName}”, which stays saved.`}
      </p>
    </ConfirmDialog>
  );
}
