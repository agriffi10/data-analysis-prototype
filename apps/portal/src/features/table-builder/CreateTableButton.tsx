import {useState} from 'react';
import {Button} from '../../components/Button';
import {Toast, type ToastState} from '../query/Toast';
import {lastSegment} from '../file-browser/fileBrowser.paths';
import {CreateTableDialog} from './CreateTableDialog';
import {enqueueTableBuild} from './tableBuild.service';
import type {PartitionKey} from './tableBuild.types';

type Props = {
  // The active space (SPEC-057) the current folder belongs to, plus the folder key.
  spaceKind: 'personal' | 'shared';
  bucket: string;
  database: string; // username (personal) | shared-space name
  prefix: string; // the current folder key (within the space)
};

// SPEC-071 FR-001/004: the file-browser toolbar action. Opens the name/partition
// prompt and, on confirm, ENQUEUES a create-table request for the current folder in
// the space's database (the browser never creates the table). Eligibility is
// enforced server-side (SPEC-067/068), so the button is available at any folder; a
// bad case comes back as a notification, not a pre-flight block. Async: a success
// toast confirms submission and the outcome arrives via notifications (SPEC-072).
export function CreateTableButton({spaceKind, bucket, database, prefix}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

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
      setToast({
        variant: 'success',
        message: `Creating table “${tableName}”… you’ll be notified when it’s ready.`
      });
    } else {
      // Keep the dialog open so the user can retry (FR-004 — no silent failure).
      setSubmitError(result.error.message);
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
          busy={busy}
          submitError={submitError}
          onSubmit={handleSubmit}
          onCancel={() => setOpen(false)}
        />
      )}

      {toast && (
        <Toast
          variant={toast.variant}
          message={toast.message}
          onDismiss={() => setToast(null)}
        />
      )}
    </>
  );
}
