export type S3FileItem = {
  type: 'file';
  key: string;
  name: string;
  size: number;
  lastModified: Date;
};

export type S3FolderItem = {
  type: 'folder';
  prefix: string;
  name: string;
};

export type S3Item = S3FileItem | S3FolderItem;

export type FileList = {
  files: S3FileItem[];
  folders: S3FolderItem[];
};

// One page of a paginated ListObjectsV2 response (SPEC-015 FR-002). `isTruncated`
// drives the "Load more" control; `nextContinuationToken` is threaded into the
// next page request.
export type FileListPage = FileList & {
  isTruncated: boolean;
  nextContinuationToken?: string;
};

// ServiceResult now lives in service.types.ts (it is not S3-specific).
// Re-exported here for back-compat with existing imports.
export type { ServiceResult } from './service.types';
