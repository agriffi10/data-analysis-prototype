import type {S3FolderItem} from '../../types/s3.types';
import {Button} from '../../components/Button';
import {PencilIcon} from '../../components/icons';
import {Drawer} from '../../components/Drawer';
import {relativePath} from './fileBrowser.paths';
import {DetailField} from './DetailField';

type Props = {
  bucket: string;
  folder: S3FolderItem;
  rootPrefix?: string; // stripped from the prefix to show a user-relative path
  /** Gates Rename — false in read-only (dev-unauth) browse. */
  canModify: boolean;
  /** Opens RenameDialog for this folder (SPEC-097). */
  onRequestRename: (folder: S3FolderItem) => void;
  onClose: () => void;
};

// Read-only details drawer for a folder (prefix). Folders have no HeadObject
// metadata, so unlike MetadataPanel this renders synchronously from the listing
// item: name, user-relative path, and the fully-qualified S3 URI. SPEC-097 adds a
// full-width Rename action (folders aren't downloadable); hidden in read-only mode.
export function FolderDetailsPanel({bucket, folder, rootPrefix, canModify, onRequestRename, onClose}: Props) {
  return (
    <Drawer
      open
      onClose={onClose}
      title={folder.name}
      ariaLabel={`Details for ${folder.name}`}
      closeLabel="Close details">
      {canModify && (
        <div className="mb-5">
          <Button
            variant="default"
            className="!h-11 w-full gap-2 tablet:!h-[38px]"
            onClick={() => onRequestRename(folder)}
            aria-label={`Rename ${folder.name}`}>
            <PencilIcon />
            Rename
          </Button>
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
