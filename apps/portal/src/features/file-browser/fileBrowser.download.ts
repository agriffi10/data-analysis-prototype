/**
 * Open a presigned URL so the browser saves the file. `ResponseContentDisposition`
 * (set on the URL) makes S3 return it as an attachment with the real filename, so a
 * plain anchor click downloads rather than navigates. Survives the `await` before it
 * because it's a programmatic download, not a popup.
 */
export function triggerBrowserDownload(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
