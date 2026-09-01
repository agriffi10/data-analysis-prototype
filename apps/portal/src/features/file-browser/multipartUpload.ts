import {apiRequest} from '../../lib/apiClient';
import {ok} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';

import type {SpaceRef, UploadedPart} from '../../types/apiContract.generated';
import type {UploadResult} from './fileBrowser.types';
import {putBytes, uploadCancelled, uploadRejection} from './xhrUpload';
import type {UploadFailure} from './xhrUpload';

/**
 * The part loop: what turns a plan from `objects.upload` into an assembled object.
 *
 * **The server decided this upload is multipart and how it is cut.** The browser holds no
 * threshold and no part size — a second copy of a policy number would drift, and a drifted copy
 * sends files down the wrong path with nothing failing.
 */

/**
 * How many parts may be in flight at once, and the budget is the BROWSER's connection limit.
 *
 * Not `UPLOAD_CONCURRENCY`, which bounds *files*: three files each running four parts is twelve
 * concurrent transfers against an origin that will serve six. The product is what matters —
 * `UPLOAD_CONCURRENCY` (3) × this (2) = 6, exactly HTTP/1.1's per-origin ceiling — so this constant
 * cannot be read or changed without reading that one.
 */
export const PART_CONCURRENCY = 2;

/**
 * How many times a failed part is retried, and the budget is MAKESPAN.
 *
 * Each attempt re-mints, so each gets a full window and the constraint is not expiry — it is how
 * long one part may take before the upload is worse than starting over. At the server's part size
 * and its slowest supported uplink that is `(1 + 2) × 112,500,000 / 250,000 = 1350 s` worst case.
 * Two is where a third attempt against a connection that has already failed twice is unlikely to
 * succeed while adding half again to that number.
 */
export const PART_RETRIES = 2;

/**
 * Failure codes that survive the retry loop instead of collapsing into the generic one.
 *
 * Each names something the user can act on, and each already has an authored sentence that the
 * single-`PUT` path has always shown for the same condition. Flattening them would make the
 * multipart path strictly less informative than the one it replaces.
 *
 * **A denial reaches this list only from a failed MINT**, because a denial on the bytes returns
 * immediately. That asymmetry is deliberate and it is about cost: retrying a mint spends one small
 * API call, where retrying a `PUT` spends a whole part — hundreds of megabytes at the server's part
 * size — to be refused again.
 */
export const KEEP_SPECIFIC_CODES = ['AccessDenied', 'UploadLinkExpired', 'Cancelled', 'SessionExpired'];

/** What `uploadParts` needs that only the caller knows. */
export type MultipartParams = {
  space: SpaceRef;
  key: string;
  body: Blob;
  contentType: string;
  uploadId: string;
  partSize: number;
  partCount: number;
  overwrite: boolean;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
};

/**
 * Uploads every part, then assembles them.
 *
 * @param params - The plan the server returned, plus the bytes and the caller's signal.
 * @returns The key written, or a failure carrying a code `errorMessages.ts` has a sentence for.
 */
export async function uploadParts(params: MultipartParams): Promise<ServiceResult<UploadResult>> {
  const {space, key, body, uploadId, partCount, overwrite, onProgress, signal} = params;

  const progress = new AggregateProgress(body.size, onProgress);
  const parts: UploadedPart[] = new Array(partCount);
  const queue = Array.from({length: partCount}, (_, index) => index + 1);
  let failure: UploadFailure | null = null;

  const worker = async (): Promise<void> => {
    for (;;) {
      const partNumber = queue.shift();
      if (partNumber === undefined || failure || signal?.aborted) return;

      const outcome = await sendOnePart({...params, partNumber, progress});
      if (!outcome.success) {
        // First failure wins. A later one would overwrite a more specific reason with whatever
        // the sibling in flight happened to hit as the upload wound down.
        failure ??= outcome;
        return;
      }
      parts[partNumber - 1] = outcome.data;
    }
  };

  await Promise.all(Array.from({length: Math.min(PART_CONCURRENCY, partCount)}, worker));

  if (signal?.aborted) {
    // NOT awaited. The user gets `Cancelled` immediately; the abort is best effort, carries no
    // signal, and a slow one must not hold the queue row on "Uploading" — a stalled connection is
    // a leading reason someone cancels in the first place, and `abandon` would then wait out the
    // client's full timeout. A cancel that can be made to wait is a control that fails when it is
    // most wanted.
    void abandon(space, key, uploadId);
    return uploadCancelled();
  }
  if (failure) {
    void abandon(space, key, uploadId);
    return failure;
  }

  const completed = await apiRequest('objects.uploadComplete', {
    body: {space, key, uploadId, parts, overwrite},
    signal
  });
  if (!completed.success) {
    // A cancel landing HERE arrives as the client's own abort code rather than as a refusal, so
    // it has to be recognised before anything else — otherwise the user is told their cancel
    // timed out.
    if (signal?.aborted) {
      void abandon(space, key, uploadId);
      return uploadCancelled();
    }
    // **Every failed assembly abandons the upload**, and the collision arm is the one that
    // matters: the user is about to be offered Overwrite or Rename, and both re-enter with a NEW
    // upload id. Without this the first attempt's parts are stranded — a whole file's worth of
    // multipart storage, billed until the bucket's seven-day sweep, for an interruption the user
    // never saw.
    //
    // Not awaited, for the same reason the cancel is not: the queue holds the row on "Uploading"
    // until this call resolves, and the collision prompt only appears afterwards — so awaiting a
    // discard that cannot answer would leave the user staring at a progress bar for the client's
    // full timeout, on the arm they meet most often.
    void abandon(space, key, uploadId);
    if (completed.error.code === 'Conflict') {
      return {success: false, error: {message: `"${key}" already exists.`, code: 'Collision'}};
    }
    return {success: false, error: {message: 'Failed to upload file.', code: completed.error.code ?? 'UploadFailed'}};
  }
  return ok({key});
}

/**
 * Sends one part, re-minting its URL on every attempt.
 *
 * **The re-mint is forced, not chosen.** A part is sized to use half its window on the slowest
 * supported uplink, so a second attempt on the *same* URL starts with roughly half the window
 * already spent and a third could not finish inside it at all. Reusing a failed URL would
 * reintroduce the tail-403 by another route, on the very path built to remove it.
 */
async function sendOnePart(
  params: MultipartParams & {partNumber: number; progress: AggregateProgress}
): Promise<ServiceResult<UploadedPart>> {
  const {space, key, body, contentType, uploadId, partSize, partNumber, progress, signal} = params;

  const start = (partNumber - 1) * partSize;
  const slice = body.slice(start, Math.min(start + partSize, body.size));
  let last: UploadFailure = {
    success: false,
    error: {message: 'Failed to upload file.', code: 'UploadFailed'}
  };

  for (let attempt = 0; attempt <= PART_RETRIES; attempt += 1) {
    if (signal?.aborted) return uploadCancelled();

    const minted = await apiRequest('objects.uploadPart', {
      body: {space, key, uploadId, partNumber},
      signal
    });
    if (!minted.success) {
      last = {success: false, error: {message: 'Failed to upload file.', code: minted.error.code ?? 'UploadFailed'}};
      continue;
    }

    const sent = await putBytes({
      url: minted.data.url,
      body: slice,
      contentType,
      onProgress: (loaded) => progress.report(partNumber, loaded),
      signal
    });

    if (!sent.success) {
      // A cancel is not a failure to retry against — the user asked for it, and retrying twice
      // more against an aborted signal just delays the answer they are waiting for.
      if (sent.error.code === 'Cancelled') return sent;
      last = sent;
      continue;
    }

    const {status, etag} = sent.data;
    if (status < 200 || status >= 300) {
      last = uploadRejection(status, minted.data.expiresAt);
      // **A denial is terminal; an expiry is not.** `uploadRejection` is what separates them, and
      // retrying past a denial spends a whole part's bytes per attempt to be refused again — at
      // the server's part size that is hundreds of megabytes of the user's uplink. An expired URL
      // is the opposite: the next attempt re-mints, so it is exactly what a retry fixes.
      if (last.error.code === 'AccessDenied') return last;
      continue;
    }
    if (etag === undefined) {
      // Not retryable and not S3's fault: the header is missing because the bucket's CORS stopped
      // exposing it. Retrying would send the bytes again and read `null` again. Completing with a
      // null would fail at S3 with an error naming none of this.
      return {
        success: false,
        error: {
          message: 'The upload could not be verified, so nothing was saved.',
          code: 'UploadUnverifiable'
        }
      };
    }
    progress.settle(partNumber, slice.size);
    return ok({partNumber, etag});
  }

  // Every attempt is spent. A reason the single-`PUT` path would have named is KEPT rather than
  // flattened — telling someone whose link expired, or who lacks permission, only that "the file
  // could not be uploaded" throws away the one sentence that tells them what to do. The generic
  // exhausted code is for the failures that have no better name.
  if (last.error.code && KEEP_SPECIFIC_CODES.includes(last.error.code)) return last;
  return {
    success: false,
    error: {
      message: 'That file could not be uploaded, and nothing was saved. Try again.',
      code: 'UploadPartsExhausted'
    }
  };
}

/**
 * Abandons the upload so S3 discards its parts.
 *
 * **Best effort, and it never carries the caller's signal.** The cancel path is entered *because*
 * the signal aborted, so passing it here aborts the abort — leaving the upload to the bucket's
 * seven-day sweep for a cancel the user watched succeed. A failed abort is reported nowhere: the
 * alternative is a cancel that can fail, which is a control that does not work when it is most
 * wanted.
 *
 * What is NOT guaranteed: a closed tab, a crash or a dead network leaves the upload unaborted, and
 * nothing in the browser will ever abort it. The lifecycle rule is the only sweep there is.
 */
async function abandon(space: SpaceRef, key: string, uploadId: string): Promise<void> {
  // Swallowed rather than propagated: every caller fires this WITHOUT awaiting, so a rejection
  // would surface as an unhandled one — which fails a test run while the test itself passes.
  // `apiRequest` resolves on every path today, so this is a guard against a future where it does
  // not, not a live catch.
  await apiRequest('objects.uploadAbort', {body: {space, key, uploadId}}).catch(() => undefined);
}

/**
 * The aggregate the progress bar reads: `sum over parts of max(seen, latest)`.
 *
 * **Never a running sum and never last-value-wins**, and a retry is what separates the three. A
 * retried part is a new request whose first progress event reports a small `loaded`, so
 * last-value-wins drops that part's contribution to near zero and the bar FALLS — with three parts
 * in flight and part two failing at 4 MiB of 5, the aggregate goes 9.0 MiB → 5.0 MiB. A running sum
 * has the opposite defect, over-reporting and then jumping. Taking the per-part maximum is
 * monotonic at every step, and nothing downstream would hide a regression: the queue stores
 * `loaded` verbatim with no clamp.
 *
 * **A failed attempt's high-water mark is deliberately KEPT.** Clearing it looks tidier — the
 * bytes really are being sent again — and it reintroduces the falling bar by the back door, which
 * is the one behaviour this class exists to prevent. The cost of keeping it is that the bar pauses
 * while the retry catches up to where the failed attempt reached; the cost of clearing it is a bar
 * that goes backwards in front of the user.
 */
class AggregateProgress {
  private readonly seen = new Map<number, number>();
  private readonly total: number;
  private readonly onProgress?: (loaded: number, total: number) => void;

  constructor(total: number, onProgress?: (loaded: number, total: number) => void) {
    this.total = total;
    this.onProgress = onProgress;
  }

  report(partNumber: number, loaded: number): void {
    this.seen.set(partNumber, Math.max(this.seen.get(partNumber) ?? 0, loaded));
    this.emit();
  }

  /** Pins a finished part at its true size, so rounding in progress events cannot leave a gap. */
  settle(partNumber: number, size: number): void {
    this.seen.set(partNumber, size);
    this.emit();
  }

  private emit(): void {
    if (!this.onProgress) return;
    let loaded = 0;
    for (const bytes of this.seen.values()) loaded += bytes;
    this.onProgress(Math.min(loaded, this.total), this.total);
  }
}
