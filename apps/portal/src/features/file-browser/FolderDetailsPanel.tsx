import type {S3FolderItem} from '../../types/s3.types';
import {Button} from '../../components/Button';
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

function PencilIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      className="h-4 w-4"
      aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13.5 3.5l3 3L7 16l-3.5.5L4 13z"
      />
    </svg>
  );
}

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
