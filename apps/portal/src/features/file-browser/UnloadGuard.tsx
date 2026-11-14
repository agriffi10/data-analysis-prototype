import {useEffect} from 'react';
import {armLeaveGuard, isLeaveGuardDisarmed} from '../../lib/leaveGuard';
import {useUploadQueue} from './uploadQueueContext';
import {TERMINAL_STATUSES} from './upload.types';

/**
 * Asks the browser to confirm before the document unloads while an upload is unfinished: running,
 * queued, or waiting on a name decision, the set `UploadsAtRiskNotice` counts.
 *
 * Under the App Router a navigation to or from an App Router page fetches that page from the
 * server, and Next turns it into a document load when the server cannot be reached or a new build
 * has been deployed since the page loaded; a document load ends the shell and every upload in it.
 * Measured: on "Stay", the document, the shell, the uploads and the page all remain. It also asks
 * on a reload or a closed tab mid-upload, which before this cancelled the uploads silently.
 *
 * The listener exists only while something would be lost, so an idle page keeps the back-forward
 * cache. A deliberate sign-out disarms it first (`lib/leaveGuard.ts`).
 *
 * @returns Nothing visible.
 */
export function UnloadGuard() {
  const {items} = useUploadQueue();
  const atRisk = items.some((item) => !TERMINAL_STATUSES.has(item.status));

  useEffect(() => {
    armLeaveGuard();
  }, []);

  useEffect(() => {
    if (!atRisk) return;
    const ask = (event: BeforeUnloadEvent) => {
      if (isLeaveGuardDisarmed()) return;
      event.preventDefault();
      // Older browsers ask only when a return value is set.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', ask);
    return () => window.removeEventListener('beforeunload', ask);
  }, [atRisk]);

  return null;
}
