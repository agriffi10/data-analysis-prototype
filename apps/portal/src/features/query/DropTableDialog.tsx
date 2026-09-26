import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  table: string;
  /** The database it is dropped from, named because a shared space's is everyone's. */
  database: string;
  /** The database is a shared space's, so the drop removes it for every member. */
  shared?: boolean;
  isDropping: boolean;
  /** Switches the copy/labels from "table" to "view". */
  isView?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * Warn-and-confirm before DROP TABLE / DROP VIEW; locks and shows progress
 * while the drop is in flight.
 *
 * The table sentence hedges on purpose: Athena treats an Iceberg table as managed and deletes its
 * data with it, and the catalog summary this dialog is given cannot tell an Iceberg table from any
 * other, so a flat "your files are kept" would be false for exactly the drop that costs data.
 */
export function DropTableDialog({
  table,
  database,
  shared = false,
  isDropping,
  isView = false,
  onConfirm,
  onCancel
}: Props) {
  const noun = isView ? 'view' : 'table';
  const from = `This removes the ${noun} from ${database}${shared ? ', for everyone in this shared space' : ''}.`;
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
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">
        {isView
          ? `${from} No underlying data is deleted.`
          : `${from} A standard table’s data files in S3 are kept; an Iceberg table’s data is deleted with it.`}
      </p>
    </ConfirmDialog>
  );
}
