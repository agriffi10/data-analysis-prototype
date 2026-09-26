import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * Warn-and-confirm before Clear wipes the editor, focus defaulting to Cancel.
 *
 * Not `irreversible`: the editor takes the cleared value as an undoable edit, so Ctrl/Cmd+Z brings
 * the SQL straight back, and "This can’t be undone" would be the one false sentence here.
 */
export function ClearQueryDialog({onConfirm, onCancel}: Props) {
  return (
    <ConfirmDialog
      title="Clear the query?"
      ariaLabel="Confirm clear query"
      confirmLabel="Clear"
      confirmVariant="danger"
      tone="danger"
      onConfirm={onConfirm}
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">This empties the editor and discards the draft saved for this session.</p>
    </ConfirmDialog>
  );
}
