import {apiRequest} from '../../lib/apiClient';
import {ok} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';

import type {SpaceRef, UploadedPart} from '../../types/apiContract.generated';
import type {UploadResult} from './fileBrowser.types';
import {putBytes, uploadCancelled, uploadRejection} from './xhrUpload';

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
/** The failure arm alone, so a held-onto failure can be read without re-narrowing it. */
type Failure = {success: false; error: {message: string; code?: string}};

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
  let failure: Failure | null = null;

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
    await abandon(space, key, uploadId);
    return uploadCancelled();
  }
  if (failure) {
    await abandon(space, key, uploadId);
    return failure;
  }

  const completed = await apiRequest('objects.uploadComplete', {
    body: {space, key, uploadId, parts, overwrite},
    signal
  });
  if (!completed.success) {
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
  let last: Failure = {
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
      if (sent.error.code === 'Cancelled') return sent as Failure;
      last = sent as Failure;
      continue;
    }

    const {status, etag} = sent.data;
    if (status < 200 || status >= 300) {
      last = uploadRejection(status, minted.data.expiresAt) as Failure;
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

  // Every attempt is spent. The wording says nothing was saved, which is true of multipart: an
  // upload that never completes assembles no object at all.
  return {
    success: false,
    error: {
      message: 'That file could not be uploaded, and nothing was saved. Try again.',
      code: last.error.code === 'Cancelled' ? 'Cancelled' : 'UploadPartsExhausted'
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
  await apiRequest('objects.uploadAbort', {body: {space, key, uploadId}});
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
