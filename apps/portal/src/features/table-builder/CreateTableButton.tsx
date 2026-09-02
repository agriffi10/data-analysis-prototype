import {useState} from 'react';
import {Button} from '../../components/Button';
import {useToast} from '../../components/toastContext';
import {toUserText} from '../../lib/errorMessages';
import {lastSegment} from '../file-browser/fileBrowser.paths';
import {CreateTableDialog} from './CreateTableDialog';
import {createTableRefusal} from './createTableRefusal';
import {armCatalogCatchUp} from './useCatalogCatchUp';
import {enqueueTableBuild} from './tableBuild.service';
import type {PartitionKey} from './tableBuild.types';

type Props = {
  // The active space the current folder belongs to, plus the folder key.
  spaceKind: 'personal' | 'shared';
  bucket: string;
  database: string; // username (personal) | shared-space name
  prefix: string; // the current folder key (within the space)
  rootPrefix: string; // the space root, which is the one folder a table may NOT be built from
};

/**
 * The file-browser toolbar action. Opens the name/partition
 * prompt and, on confirm, ENQUEUES a create-table request for the current folder in
 * the space's database (the browser never creates the table). Eligibility is otherwise
 * enforced server-side, so a bad case comes back as a notification rather than a
 * pre-flight block. Async: a success toast confirms submission and the outcome arrives
 * via notifications.
 *
 * The ONE case refused before submission is the space root, because that build succeeds:
 * see `createTableRefusal`. The control plane refuses it too — this is the explanation,
 * not the enforcement.
 *
 * @example
 * <CreateTableButton spaceKind="personal" bucket={bucket} database="alice" prefix="alice/sales/" rootPrefix="alice/" />
 */
export function CreateTableButton({spaceKind, bucket, database, prefix, rootPrefix}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const toast = useToast();

  // Suggestion base: the folder's own name, or the space name at the space root.
  const folderName = lastSegment(prefix) || database;
  const refusal = createTableRefusal(prefix, rootPrefix);

  const openDialog = () => {
    setSubmitError(null);
    setOpen(true);
  };

  const handleSubmit = async ({tableName, partitionKeys}: {tableName: string; partitionKeys: PartitionKey[]}) => {
    setBusy(true);
    setSubmitError(null);
    const result = await enqueueTableBuild({
      space: {kind: spaceKind, bucket, prefix, database},
      tableName,
      partitionKeys
    });
    setBusy(false);
    if (result.success) {
      // The build lands minutes from now and announces itself in a notification, not here — so
      // the catalog is re-read when the user comes back to the page, and every cache keyed on
      // it catches up. Without this, a table dropped and rebuilt under the same name leaves the
      // Data Explorer resolving to the pre-drop execution.
      armCatalogCatchUp(database, tableName);
      setOpen(false);
      toast.push({
        variant: 'success',
        message: `Creating table “${tableName}”… you’ll be notified when it’s ready.`
      });
    } else {
      // Keep the dialog open so the user can retry ( — no silent failure).
      setSubmitError(toUserText(result.error));
    }
  };

  return (
    <>
      <Button
        variant="default"
        className="shrink-0"
        disabledReason={refusal ?? undefined}
        onClick={openDialog}>
        Create table
      </Button>

      {open && (
        <CreateTableDialog
          folderName={folderName}
          folderPath={prefix}
          busy={busy}
          submitError={submitError}
          onSubmit={handleSubmit}
          onCancel={() => setOpen(false)}
        />
      )}
    </>
  );
}
