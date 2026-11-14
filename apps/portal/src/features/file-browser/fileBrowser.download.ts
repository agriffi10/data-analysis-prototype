import {withoutLeaveGuard} from '../../lib/leaveGuard';

/**
 * Open a presigned URL so the browser saves the file. `ResponseContentDisposition`
 * (set on the URL) makes S3 return it as an attachment with the real filename, so a
 * plain anchor click downloads rather than navigates. Survives the `await` before it
 * because it's a programmatic download, not a popup.
 *
 * The click is still a navigation as far as the browser's `beforeunload` is concerned, so it runs
 * with the shell's leave guard disarmed: the document is not going anywhere.
 */
export function triggerBrowserDownload(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  document.body.appendChild(a);
  withoutLeaveGuard(() => a.click());
  a.remove();
}
