import {useQuery} from '@tanstack/react-query';
import type {S3FolderItem} from '../../types/s3.types';
import {Button} from '../../components/Button';
import {PencilIcon} from '../../components/icons';
import {Drawer} from '../../components/Drawer';
import {ArchiveButton} from '../archive';
import {relativePath} from './fileBrowser.paths';
import {folderExists} from './fileBrowser.service';
import {fileBrowserKeys} from './fileBrowserKeys';
import {unwrap} from '../../lib/serviceResult';
import {DetailField} from './DetailField';

type Props = {
  bucket: string;
  folder: S3FolderItem;
  rootPrefix?: string; // stripped from the prefix to show a user-relative path
  /** Gates Rename — false in read-only (dev-unauth) browse. */
  canModify: boolean;
  /** Opens RenameDialog for this folder. */
  onRequestRename: (folder: S3FolderItem) => void;
  /**
   * archives THIS folder without selecting it first. Absent when the space can't be
   * resolved, the `files` flag is off, or the user is inside the read-only `archive/` folder.
   */
  onRequestArchive?: (folder: S3FolderItem) => void;
  /** Why this folder can't be archived (a portal-managed root), if it can't. */
  archiveDisabledReason?: string;
  /** Why nothing here can be written — Rename carries it. */
  writeLockReason?: string;
  onClose: () => void;
};

/**
 * Read-only details drawer for a folder (prefix). Folders have no HeadObject metadata, so unlike
 * `MetadataPanel` the fields here render straight from the listing item: name, user-relative
 * path, and the fully-qualified S3 URI. There is a full-width Rename action (folders aren't
 * downloadable); hidden in read-only mode.
 *
 * **One thing is NOT read from the listing, and it was the gap.** File operations now finish
 * minutes after the browser stops watching, so a folder the plane has removed can still be in the
 * listing this panel opened from — and unlike a deleted file, whose details panel surfaces the
 * mapped `NotFound` from its metadata read, a folder rendering synchronously showed a full panel
 * with live actions and no error at all. So it asks, once, whether anything still lives under the
 * prefix.
 *
 * **A confirmed empty answer, never an error and never the listing.** `folderExists` reads a raw
 * unfiltered key because the browser's own listing hides a folder's marker object — an empty
 * folder would otherwise report itself deleted. A failed read changes nothing: a folder this
 * session cannot list is not a folder that is gone.
 */
export function FolderDetailsPanel({
  bucket,
  folder,
  rootPrefix,
  canModify,
  onRequestRename,
  onRequestArchive,
  archiveDisabledReason,
  writeLockReason,
  onClose
}: Props) {
  const presence = useQuery({
    queryKey: fileBrowserKeys.exists(bucket, folder.prefix),
    queryFn: async () => unwrap(await folderExists({bucket, prefix: folder.prefix})),
    // A point-in-time question, so it never serves a cached answer. The app-wide 30 s would let a
    // folder deleted and then re-created under the same name keep saying it is gone — and neither
    // the manual Refresh nor a focus return would clear it, because `invalidateListing` touches
    // only the listing key.
    staleTime: 0,
    gcTime: 0
  });
  const gone = presence.data === false;

  return (
    <Drawer
      open
      onClose={onClose}
      title={folder.name}
      ariaLabel={`Details for ${folder.name}`}
      closeLabel="Close details">
      {gone && (
        <div
          role="status"
          className="mb-5 rounded-lg border border-border bg-surface-2 p-3 text-sm text-text-2">
          This folder no longer exists. It may have been moved or deleted — refresh the file list to see what is there
          now.
        </div>
      )}
      {canModify && !gone && (
        <div className="mb-5 flex flex-col gap-2">
          <Button
            variant="default"
            className="!h-11 w-full gap-2 tablet:!h-[38px]"
            onClick={() => onRequestRename(folder)}
            disabledReason={writeLockReason}
            aria-label={`Rename ${folder.name}`}>
            <PencilIcon />
            Rename
          </Button>
          {onRequestArchive && (
            <ArchiveButton
              placement="panel"
              onClick={() => onRequestArchive(folder)}
              disabledReason={archiveDisabledReason}
              label="Archive this item"
            />
          )}
        </div>
      )}
      <dl>
        <DetailField
          label="Name"
          value={folder.name}
        />
        <DetailField
          label="Path"
          value={relativePath(folder.prefix, rootPrefix)}
          copyLabel="path"
        />
        {/* The unambiguous, fully-qualified S3 URI for this folder prefix. */}
        <DetailField
          label="Full Cloud Path"
          value={`s3://${bucket}/${folder.prefix}`}
          copyLabel="full cloud path"
        />
      </dl>
    </Drawer>
  );
}
