import {withoutLeaveGuard} from './leaveGuard';

/**
 * How long the object URL outlives the click. The download may still be reading it after
 * `click()` returns, so it is revoked later rather than at once; a URL left alive for a minute
 * costs nothing.
 */
const REVOKE_AFTER_MS = 60_000;

/**
 * Hands the browser a text file to save, built in memory from `text` — nothing is uploaded or
 * fetched, so it works for content that exists only in the page, like an editor's buffer. The click
 * runs with the shell's leave guard disarmed, as the file download's does: a download is not the
 * document going.
 *
 * @example
 * downloadTextFile('report.sql', sql, 'application/sql');
 */
export function downloadTextFile(fileName: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], {type}));
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.rel = 'noopener';
  document.body.appendChild(a);
  withoutLeaveGuard(() => a.click());
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER_MS);
}
