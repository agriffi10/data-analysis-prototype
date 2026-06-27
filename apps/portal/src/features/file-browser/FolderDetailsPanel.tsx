import type { S3FolderItem } from '../../types/s3.types';
import { Drawer } from '../../components/Drawer';
import { relativePath } from './fileBrowser.paths';
import { DetailField } from './DetailField';

type Props = {
  bucket: string;
  folder: S3FolderItem;
  rootPrefix?: string; // stripped from the prefix to show a user-relative path
  onClose: () => void;
};

// Read-only details drawer for a folder (prefix). Folders have no HeadObject
// metadata, so unlike MetadataPanel this renders synchronously from the listing
// item: name, user-relative path, and the fully-qualified S3 URI. Mirrors the
// file panel's "Full Cloud Path" field and copy affordances.
export function FolderDetailsPanel({ bucket, folder, rootPrefix, onClose }: Props) {
  return (
    <Drawer
      open
      onClose={onClose}
      title={folder.name}
      ariaLabel={`Details for ${folder.name}`}
      closeLabel="Close details"
    >
      <dl>
        <DetailField label="Name" value={folder.name} />
        <DetailField label="Path" value={relativePath(folder.prefix, rootPrefix)} copyLabel="path" />
        {/* The unambiguous, fully-qualified S3 URI for this folder prefix. */}
        <DetailField label="Full Cloud Path" value={`s3://${bucket}/${folder.prefix}`} copyLabel="full cloud path" />
      </dl>
    </Drawer>
  );
}
