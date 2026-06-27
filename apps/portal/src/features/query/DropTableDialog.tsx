import { ConfirmDialog } from '../../components/ConfirmDialog';

type Props = {
  table: string;
  isDropping: boolean;
  isView?: boolean; // SPEC-048: switch the copy/labels to "view"
  onConfirm: () => void;
  onCancel: () => void;
};

// SPEC-044 FR-005 / SPEC-048 FR-006: warn-and-confirm before DROP TABLE / DROP
// VIEW. Thin wrapper over the shared ConfirmDialog; locks + shows progress while
// the drop is in flight.
export function DropTableDialog({ table, isDropping, isView = false, onConfirm, onCancel }: Props) {
  const noun = isView ? 'view' : 'table';
  return (
    <ConfirmDialog
      title={`Drop the ${noun} “${table}”?`}
      ariaLabel={`Confirm drop ${noun}`}
      confirmLabel={`Drop ${noun}`}
      busyLabel="Dropping…"
      busy={isDropping}
      confirmVariant="danger"
      tone="danger"
      irreversible
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      <p className="mt-3 text-sm text-text-2">
        {isView
          ? 'This removes the view definition from your database. No underlying data is deleted.'
          : 'This removes the table definition from your database. The underlying data files in S3 are not deleted.'}
      </p>
    </ConfirmDialog>
  );
}
