import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  label: string; // the tab being closed, e.g. "Query 2"
  onConfirm: () => void;
  onCancel: () => void;
};

// SPEC-041 FR-005: warn-and-confirm before closing a tab that holds non-empty
// SQL. Thin wrapper over the shared ConfirmDialog.
export function CloseTabDialog({label, onConfirm, onCancel}: Props) {
  return (
    <ConfirmDialog
      title={`Close “${label}”?`}
      ariaLabel="Confirm close tab"
      confirmLabel="Close tab"
      confirmVariant="danger"
      tone="danger"
      irreversible
      onConfirm={onConfirm}
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">
        This tab has unsaved SQL. Closing it discards that text for this session.
      </p>
    </ConfirmDialog>
  );
}
