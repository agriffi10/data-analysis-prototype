import {useState} from 'react';
import {Button} from '../../components/Button';
import {useToast} from '../../components/toastContext';
import {toUserText} from '../../lib/errorMessages';
import {lastSegment} from '../file-browser/fileBrowser.paths';
import {CreateTableDialog} from './CreateTableDialog';
import {enqueueTableBuild} from './tableBuild.service';
import type {PartitionKey} from './tableBuild.types';

type Props = {
  // The active space the current folder belongs to, plus the folder key.
  spaceKind: 'personal' | 'shared';
  bucket: string;
  database: string; // username (personal) | shared-space name
  prefix: string; // the current folder key (within the space)
};

// The file-browser toolbar action. Opens the name/partition
// prompt and, on confirm, ENQUEUES a create-table request for the current folder in
// the space's database (the browser never creates the table). Eligibility is
// enforced server-side, so the button is available at any folder; a
// bad case comes back as a notification, not a pre-flight block. Async: a success
// toast confirms submission and the outcome arrives via notifications.
export function CreateTableButton({spaceKind, bucket, database, prefix}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const toast = useToast();

  // Suggestion base: the folder's own name, or the space name at the space root.
  const folderName = lastSegment(prefix) || database;

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
