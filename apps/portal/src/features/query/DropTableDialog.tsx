import { ConfirmDialog } from '../../components/ConfirmDialog';

type Props = {
  table: string;
  isDropping: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

// SPEC-044 FR-005: warn-and-confirm before DROP TABLE. Thin wrapper over the
// shared ConfirmDialog; locks + shows progress while the drop is in flight.
export function DropTableDialog({
  table,
  isDropping,
  onConfirm,
  onCancel,
}: Props) {
  return (
    <ConfirmDialog
      title={`Drop the table “${table}”?`}
      ariaLabel="Confirm drop table"
      confirmLabel="Drop table"
      busyLabel="Dropping…"
      busy={isDropping}
      confirmVariant="danger"
      tone="danger"
      irreversible
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      <p className="mt-3 text-sm text-text-2">
        This removes the table definition from your database. The underlying data
        files in S3 are not deleted.
      </p>
    </ConfirmDialog>
  );
}
