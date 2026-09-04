import {useState} from 'react';
import {Button} from '../../components/Button';
import {useToast} from '../../components/toastContext';
import {toUserText} from '../../lib/errorMessages';
import {lastSegment} from '../file-browser/fileBrowser.paths';
import {CreateTableDialog} from './CreateTableDialog';
import {createTableTarget} from './createTableRefusal';
import {armCatalogCatchUp} from './useCatalogCatchUp';
import {enqueueTableBuild} from './tableBuild.service';
import type {PartitionKey} from './tableBuild.types';
import type {SelectableItem} from '../file-browser/selectionContext';

type Props = {
  // The active space the current folder belongs to.
  spaceKind: 'personal' | 'shared';
  bucket: string;
  database: string; // username (personal) | shared-space name
  /** The browser's current selection — the table is built from the one folder in it. */
  selected: readonly SelectableItem[];
  rootPrefix: string; // the space root, which is the one folder a table may NOT be built from
};

/**
 * The file-browser toolbar action. Opens the name/partition prompt and, on confirm,
 * ENQUEUES a create-table request in the space's database (the browser never creates the
 * table). Async: a success toast confirms submission and the outcome arrives via
 * notifications.
 *
 * It builds from the SELECTED folder, not the folder being viewed. A table reads every file
 * below its location, so which folder it means has to be said rather than inferred from where
 * the user happens to be standing — and a build from the wrong one succeeds, quietly, over
 * the wrong files. Exactly one folder, never a file and never several: `createTableTarget`
 * owns those arms and their wording.
 *
 * Eligibility is otherwise enforced server-side, so a bad case comes back as a notification
 * rather than a pre-flight block. The control plane refuses the space root too — this is the
 * explanation, not the enforcement.
 *
 * @example
 * <CreateTableButton spaceKind="personal" bucket={bucket} database="alice" selected={selectedItems} rootPrefix="alice/" />
 */
export function CreateTableButton({spaceKind, bucket, database, selected, rootPrefix}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const toast = useToast();

  const {prefix, refusal} = createTableTarget(selected, rootPrefix);
  // Suggestion base: the chosen folder's own name. Null only while refused, when the dialog
  // cannot be opened to read it.
  const folderName = (prefix && lastSegment(prefix)) || database;

  const openDialog = () => {
    setSubmitError(null);
    setOpen(true);
  };

  const handleSubmit = async ({tableName, partitionKeys}: {tableName: string; partitionKeys: PartitionKey[]}) => {
    // Unreachable while the button is disabled on the same refusal that nulls the prefix;
    // typed rather than asserted so a future caller that renders the dialog another way
    // cannot enqueue a build with no folder.
    if (prefix === null) return;
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

      {open && prefix !== null && (
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
