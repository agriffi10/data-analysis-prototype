import {useState} from 'react';
import {toUserText} from '../../lib/errorMessages';
import {getDownloadUrl} from './fileBrowser.service';
import {triggerBrowserDownload} from './fileBrowser.download';
import type {S3FileItem} from '../../types/s3.types';

export type UseFileDownloadResult = {
  /** The key currently downloading, or `null`. Compare to a row's key to disable just that row. */
  downloadingKey: string | null;
  /** User-safe failure text, already through `toUserMessage`. Render it directly. */
  error: string | null;
  download: (file: S3FileItem) => Promise<void>;
  dismissError: () => void;
};

/**
 * Presign one file and hand it to the browser.
 *
 * The file list and the metadata panel had each written this out, down to the same
 * error sentence — so a change to the wording, or to the re-entrancy guard, was two
 * edits. The guard matters: `download` is a no-op while the SAME key is in flight, so
 * a rapid double-click cannot mint two presigned URLs.
 *
 * Never throws — the service returns a `ServiceResult` and the failure lands in
 * `error`, where the caller renders it.
 *
 * @example
 * const dl = useFileDownload(bucket);
 * <Button disabled={dl.downloadingKey === file.key} onClick={() => void dl.download(file)}>Download</Button>
 */
export function useFileDownload(bucket: string): UseFileDownloadResult {
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download(file: S3FileItem): Promise<void> {
    if (downloadingKey === file.key) return;
    setDownloadingKey(file.key);
    setError(null);
    const result = await getDownloadUrl({bucket, key: file.key, fileName: file.name});
    setDownloadingKey(null);
    if (result.success) triggerBrowserDownload(result.data.url);
    else setError(`Could not download ${file.name}. ${toUserText(result.error)}`);
  }

  return {
    downloadingKey,
    error,
    download,
    dismissError: () => setError(null)
  };
}
