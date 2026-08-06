import {useState} from 'react';
import {useObjectMetadata} from './useObjectMetadata';
import type {ObjectMetadata} from './fileBrowser.types';
import type {S3FileItem} from '../../types/s3.types';
import {toUserMessage} from '../../lib/errorMessages';
import {Button} from '../../components/Button';
import {DownloadIcon, PencilIcon} from '../../components/icons';
import {Drawer} from '../../components/Drawer';
import {getDownloadUrl} from './fileBrowser.service';
import {triggerBrowserDownload} from './fileBrowser.download';
import {formatSize} from './fileBrowser.format';
import {relativePath} from './fileBrowser.paths';
import {DetailField} from './DetailField';

type Props = {
  bucket: string;
  file: S3FileItem;
  rootPrefix?: string; // stripped from the key to show a user-relative path
  /** Gates Rename — false in read-only (dev-unauth) browse. Download always shows. */
  canModify: boolean;
  /** Opens RenameDialog for this file (SPEC-097). */
  onRequestRename: (file: S3FileItem) => void;
  onClose: () => void;
};

// The Download + Rename action pair (SPEC-097). Download resolves a presigned URL
// and downloads with attachment disposition (both authenticated + read-only);
// Rename opens the shared RenameDialog and is hidden in read-only mode. Desktop =
// side-by-side 50/50; mobile sheet = stacked full-width (≥44px).
function PanelActions({
  bucket,
  file,
  canModify,
  onRequestRename
}: {
  bucket: string;
  file: S3FileItem;
  canModify: boolean;
  onRequestRename: (file: S3FileItem) => void;
}) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    if (downloading) return;
    setDownloading(true);
    setError(null);
    const result = await getDownloadUrl({bucket, key: file.key, fileName: file.name});
    setDownloading(false);
    if (result.success) triggerBrowserDownload(result.data.url);
    else setError(`Could not download ${file.name}. ${toUserMessage(result.error).message}`);
  }

  return (
    <div className="mb-5 flex flex-col gap-2">
      <div className="flex flex-col gap-2 tablet:flex-row">
        <Button
          variant="primary"
          className="!h-11 flex-1 gap-2 tablet:!h-[38px]"
          onClick={() => void download()}
          disabled={downloading}
          aria-busy={downloading}
          aria-label={`Download ${file.name}`}>
          <DownloadIcon />
          {downloading ? 'Downloading…' : 'Download'}
        </Button>
        {canModify && (
          <Button
            variant="default"
            className="!h-11 flex-1 gap-2 tablet:!h-[38px]"
            onClick={() => onRequestRename(file)}
            aria-label={`Rename ${file.name}`}>
            <PencilIcon />
            Rename
          </Button>
        )}
      </div>
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-danger-soft bg-danger-soft p-3 text-sm text-danger">
          {error}
        </div>
      )}
    </div>
  );
}

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
// close). SPEC-097 adds a Download + Rename action pair at the top. The fetch
// state (loading / inline error / data) comes from useObjectMetadata; reopening
// after an error refetches because a fresh observer mounts on the same query key.
export function MetadataPanel({bucket, file, rootPrefix, canModify, onRequestRename, onClose}: Props) {
  const {metadata, isLoading, error} = useObjectMetadata(bucket, file.key);

  return (
    <Drawer
      open
      onClose={onClose}
      title={file.name}
      ariaLabel={`Details for ${file.name}`}
      closeLabel="Close details">
      <PanelActions
        bucket={bucket}
        file={file}
        canModify={canModify}
        onRequestRename={onRequestRename}
      />

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
          <p className="mt-1 text-danger/80">{toUserMessage(error).message}</p>
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
