import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  /** The tab being closed, e.g. "Query 2". */
  label: string;
  onConfirm: () => void;
  onCancel: () => void;
};

/** Warn-and-confirm before closing a tab that holds non-empty SQL. */
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
