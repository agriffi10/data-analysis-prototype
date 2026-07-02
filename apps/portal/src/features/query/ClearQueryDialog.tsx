import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  onConfirm: () => void;
  onCancel: () => void;
};

/** Warn-and-confirm before Clear wipes the editor (no undo, so focus defaults to Cancel). */
export function ClearQueryDialog({onConfirm, onCancel}: Props) {
  return (
    <ConfirmDialog
      title="Clear the query?"
      ariaLabel="Confirm clear query"
      confirmLabel="Clear"
      confirmVariant="danger"
      tone="danger"
      irreversible
      onConfirm={onConfirm}
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">This empties the editor and discards the draft saved for this session.</p>
    </ConfirmDialog>
  );
}
