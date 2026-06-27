import {useObjectMetadata} from './useObjectMetadata';
import type {ObjectMetadata} from './fileBrowser.types';
import type {S3FileItem} from '../../types/s3.types';
import {Drawer} from '../../components/Drawer';
import {formatSize} from './fileBrowser.format';
import {relativePath} from './fileBrowser.paths';
import {DetailField} from './DetailField';

type Props = {
  bucket: string;
  file: S3FileItem;
  rootPrefix?: string; // stripped from the key to show a user-relative path
  onClose: () => void;
};

function MetadataFields({
  metadata,
  file,
  bucket,
  rootPrefix
}: {
  metadata: ObjectMetadata;
  file: S3FileItem;
  bucket: string;
  rootPrefix?: string;
}) {
  const customEntries = Object.entries(metadata.userMetadata);
  return (
    <>
      <dl>
        <DetailField
          label="Name"
          value={file.name}
        />
        <DetailField
          label="Path"
          value={relativePath(metadata.key, rootPrefix)}
          copyLabel="path"
        />
        {/* The unambiguous, fully-qualified S3 URI for this object. */}
        <DetailField
          label="Full Cloud Path"
          value={`s3://${bucket}/${metadata.key}`}
          copyLabel="full cloud path"
        />
        <DetailField
          label="Size"
          value={`${formatSize(metadata.size)} (${metadata.size.toLocaleString()} bytes)`}
        />
        <DetailField
          label="Type"
          value={metadata.contentType}
        />
        <DetailField
          label="Last modified"
          value={metadata.lastModified.toLocaleString()}
        />
        <DetailField
          label="ETag"
          value={metadata.etag.replace(/"/g, '')}
        />
        <DetailField
          label="Storage class"
          value={metadata.storageClass}
        />
      </dl>

      <div className="mt-6">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-3">Custom metadata</h3>
        {customEntries.length === 0 ? (
          <p className="mt-2 text-sm text-text-3">No custom metadata</p>
        ) : (
          <dl className="mt-2">
            {customEntries.map(([k, v]) => (
              <DetailField
                key={k}
                label={k}
                value={v}
              />
            ))}
          </dl>
        )}
      </div>
    </>
  );
}

// SPEC-017 FR-002: a read-only drawer showing a single file's metadata, rendered
// in the shared Drawer primitive (blur backdrop + focus trap; dismissible via the
// close button, Escape, or backdrop click — focus returns to the trigger on
// close). The fetch state (loading / inline error / data) comes from
// useObjectMetadata; reopening after an error refetches because a fresh observer
// mounts on the same query key.
export function MetadataPanel({bucket, file, rootPrefix, onClose}: Props) {
  const {metadata, isLoading, error} = useObjectMetadata(bucket, file.key);

  return (
    <Drawer
      open
      onClose={onClose}
      title={file.name}
      ariaLabel={`Details for ${file.name}`}
      closeLabel="Close details">
      {isLoading && (
        <div
          role="status"
          aria-label="Loading details"
          className="flex flex-col items-center justify-center py-16 text-sm text-text-3">
          Loading…
        </div>
      )}

      {!isLoading && error !== null && (
        <div
          role="alert"
          className="rounded-lg border border-danger-soft bg-danger-soft p-3 text-sm">
          <p className="font-medium text-danger">Couldn’t load details</p>
          <p className="mt-1 text-danger/80">{error}</p>
        </div>
      )}

      {!isLoading && error === null && metadata && (
        <MetadataFields
          metadata={metadata}
          file={file}
          bucket={bucket}
          rootPrefix={rootPrefix}
        />
      )}
    </Drawer>
  );
}
