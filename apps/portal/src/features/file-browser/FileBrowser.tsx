import { useState } from 'react';
import { useFileBrowser } from './useFileBrowser';
import type { S3FileItem, S3FolderItem } from '../../types/s3.types';

// ─── Types ───────────────────────────────────────────────────────────────────

type Props = {
  bucket: string;
  prefix?: string;     // initial prefix; browser starts here on mount
  rootPrefix?: string; // navigation floor; defaults to prefix prop value
};

type BreadcrumbItem = {
  label: string;
  prefix: string | undefined;
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function buildBreadcrumbs(prefix: string | undefined, rootPrefix: string): BreadcrumbItem[] {
  if (!rootPrefix) {
    // No root clamping — standard Home-rooted breadcrumb
    const crumbs: BreadcrumbItem[] = [{ label: 'Home', prefix: undefined }];
    if (!prefix) return crumbs;

    const parts = prefix.split('/').filter(Boolean);
    parts.forEach((part, i) => {
      crumbs.push({
        label: part,
        prefix: parts.slice(0, i + 1).join('/') + '/',
      });
    });

    return crumbs;
  }

  // Root-clamped breadcrumb: show only segments at or below rootPrefix
  const rootParts = rootPrefix.split('/').filter(Boolean);
  const rootLabel = rootParts[rootParts.length - 1] ?? rootPrefix;
  const crumbs: BreadcrumbItem[] = [{ label: rootLabel, prefix: rootPrefix }];

  if (!prefix || prefix === rootPrefix) return crumbs;

  const allParts = prefix.split('/').filter(Boolean);
  const subParts = allParts.slice(rootParts.length);
  subParts.forEach((part, i) => {
    crumbs.push({
      label: part,
      prefix: [...rootParts, ...subParts.slice(0, i + 1)].join('/') + '/',
    });
  });

  return crumbs;
}

function formatSize(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
}

function formatDate(date: Date): string {
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function FolderRow({
  folder,
  onClick,
}: {
  folder: S3FolderItem;
  onClick: () => void;
}) {
  return (
    <li className="border-b border-gray-100 last:border-0">
      <button
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
        onClick={onClick}
        aria-label={`Open folder ${folder.name}`}
      >
        <span aria-hidden="true">📁</span>
        <span className="flex-1 font-medium text-gray-800">{folder.name}</span>
        <span className="text-gray-400" aria-hidden="true">›</span>
      </button>
    </li>
  );
}

function FileRow({ file }: { file: S3FileItem }) {
  return (
    <li className="flex items-center gap-3 border-b border-gray-100 px-4 py-3 last:border-0">
      <span aria-hidden="true">📄</span>
      <span className="flex-1 text-gray-800">{file.name}</span>
      <span className="w-20 text-right text-sm text-gray-500">
        {formatSize(file.size)}
      </span>
      <span className="w-32 text-right text-sm text-gray-400">
        {formatDate(file.lastModified)}
      </span>
    </li>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function FileBrowser({ bucket, prefix: prefixProp = '', rootPrefix: rootPrefixProp }: Props) {
  const rootPrefix = rootPrefixProp ?? prefixProp;
  const [prefix, setPrefix] = useState<string | undefined>(prefixProp || undefined);
  const { files, folders, isLoading, error } = useFileBrowser(bucket, prefix);

  const breadcrumbs = buildBreadcrumbs(prefix, rootPrefix);
  const isEmpty =
    !isLoading && error === null && files.length === 0 && folders.length === 0;
  const hasContent =
    !isLoading && error === null && (files.length > 0 || folders.length > 0);

  return (
    <div>
      {/* Breadcrumb */}
      <nav aria-label="breadcrumb" className="mb-4">
        <ol className="flex flex-wrap items-center gap-1 text-sm text-gray-600">
          {breadcrumbs.map((crumb, i) => {
            const isLast = i === breadcrumbs.length - 1;
            return (
              <li key={crumb.prefix ?? 'root'} className="flex items-center gap-1">
                {i > 0 && (
                  <span aria-hidden="true" className="text-gray-300">
                    /
                  </span>
                )}
                {isLast ? (
                  <span
                    aria-current="page"
                    className="font-medium text-gray-900"
                  >
                    {crumb.label}
                  </span>
                ) : (
                  <button
                    className="hover:text-blue-600 hover:underline"
                    onClick={() => setPrefix(crumb.prefix)}
                  >
                    {crumb.label}
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      </nav>

      {/* Loading */}
      {isLoading && (
        <div
          role="status"
          aria-label="Loading"
          className="flex justify-center py-12 text-gray-400"
        >
          <span>Loading…</span>
        </div>
      )}

      {/* Error */}
      {!isLoading && error !== null && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700"
        >
          <p className="font-medium">Failed to load files</p>
          <p className="mt-1 text-sm">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {isEmpty && (
        <p className="py-12 text-center text-gray-400">This folder is empty.</p>
      )}

      {/* File and folder list */}
      {hasContent && (
        <ul
          aria-label="File list"
          className="overflow-hidden rounded-lg border border-gray-200 bg-white"
        >
          {folders.map((folder) => (
            <FolderRow
              key={folder.prefix}
              folder={folder}
              onClick={() => setPrefix(folder.prefix)}
            />
          ))}
          {files.map((file) => (
            <FileRow key={file.key} file={file} />
          ))}
        </ul>
      )}
    </div>
  );
}
