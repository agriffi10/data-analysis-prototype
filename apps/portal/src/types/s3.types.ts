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

export type ServiceResult<T> =
  | { success: true; data: T }
  | { success: false; error: { message: string; code?: string } };
