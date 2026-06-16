import { useEffect } from 'react';
import { useObjectMetadata } from './useObjectMetadata';
import type { ObjectMetadata } from './fileBrowser.types';
import type { S3FileItem } from '../../types/s3.types';
import { IconButton } from '../../components/IconButton';

type Props = {
  bucket: string;
  file: S3FileItem;
  rootPrefix?: string; // stripped from the key to show a user-relative path
  onClose: () => void;
};

// Human-readable size, matching the listing's formatting (SPEC-015).
function formatSize(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
}

// Path shown to the user: the key with the user-root prefix stripped, so the
// raw prefix segment (e.g. the username) is never surfaced (SPEC-013).
function relativePath(key: string, rootPrefix?: string): string {
  return rootPrefix && key.startsWith(rootPrefix)
    ? key.slice(rootPrefix.length)
    : key;
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-b border-border-2 py-3 last:border-0">
      <dt className="text-xs font-semibold uppercase tracking-wide text-text-3">
        {label}
      </dt>
      <dd className="mt-1 break-all text-sm text-text">{value}</dd>
    </div>
  );
}

function MetadataFields({
  metadata,
  file,
  rootPrefix,
}: {
  metadata: ObjectMetadata;
  file: S3FileItem;
  rootPrefix?: string;
}) {
  const customEntries = Object.entries(metadata.userMetadata);
  return (
    <>
      <dl>
        <Field label="Name" value={file.name} />
        <Field label="Path" value={relativePath(metadata.key, rootPrefix)} />
        <Field
          label="Size"
          value={`${formatSize(metadata.size)} (${metadata.size.toLocaleString()} bytes)`}
        />
        <Field label="Type" value={metadata.contentType} />
        <Field
          label="Last modified"
          value={metadata.lastModified.toLocaleString()}
        />
        <Field label="ETag" value={metadata.etag.replace(/"/g, '')} />
        <Field label="Storage class" value={metadata.storageClass} />
      </dl>

      <div className="mt-6">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-3">
          Custom metadata
        </h3>
        {customEntries.length === 0 ? (
          <p className="mt-2 text-sm text-text-3">No custom metadata</p>
        ) : (
          <dl className="mt-2">
            {customEntries.map(([k, v]) => (
              <Field key={k} label={k} value={v} />
            ))}
          </dl>
        )}
      </div>
    </>
  );
}

// SPEC-017 FR-002: a read-only side drawer showing a single file's metadata. It
// is non-blocking (aria-modal="false", no backdrop) so the rest of the browser
// stays usable, and dismissible via the close button or Escape. The fetch state
// (loading / inline error / data) comes from useObjectMetadata; reopening after
// an error refetches because a fresh observer mounts on the same query key.
export function MetadataPanel({ bucket, file, rootPrefix, onClose }: Props) {
  const { metadata, isLoading, error } = useObjectMetadata(bucket, file.key);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-label={`Details for ${file.name}`}
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[380px] flex-col overflow-hidden border-l border-border bg-surface shadow-lg"
    >
      <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-border px-4">
        <h2
          className="min-w-0 flex-1 truncate text-base font-semibold text-text"
          title={file.name}
        >
          {file.name}
        </h2>
        <IconButton
          label="Close details"
          onClick={onClose}
          className="ml-3 flex-shrink-0"
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-4 w-4"
            aria-hidden="true"
          >
            <path strokeLinecap="round" d="M2 2l12 12M14 2L2 14" />
          </svg>
        </IconButton>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {isLoading && (
          <div
            role="status"
            aria-label="Loading details"
            className="flex flex-col items-center justify-center py-16 text-sm text-text-3"
          >
            Loading…
          </div>
        )}

        {!isLoading && error !== null && (
          <div
            role="alert"
            className="rounded-lg border border-danger-soft bg-danger-soft p-3 text-sm"
          >
            <p className="font-medium text-danger">Couldn’t load details</p>
            <p className="mt-1 text-danger/80">{error}</p>
          </div>
        )}

        {!isLoading && error === null && metadata && (
          <MetadataFields
            metadata={metadata}
            file={file}
            rootPrefix={rootPrefix}
          />
        )}
      </div>
    </aside>
  );
}
