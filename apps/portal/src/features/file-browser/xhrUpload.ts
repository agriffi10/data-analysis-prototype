import {toServiceError} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';

/**
 * The one module in the app permitted to name `XMLHttpRequest`, and the reason is the progress bar.
 *
 * `fetch` fires **no upload-progress event**. An implementation built on it uploads correctly and
 * leaves the bar at 0% until it jumps to 100% — a shipped feature deleted by a transport choice,
 * with every "the upload succeeded" test still green. So the transport is a requirement rather than
 * a preference, and a lint-style sweep confines it here: a rule forbidding `fetch` and silent about
 * `XMLHttpRequest` permits the same escape hatch under another name.
 *
 * Both upload paths call this — the single `PUT` and every part of a multipart upload — because
 * otherwise the abort handling, the progress plumbing and the expiry-versus-denial mapping are each
 * written twice, and the copies diverge in the path nobody is testing.
 */

/**
 * The failure arm on its own.
 *
 * Both helpers below only ever fail, and saying so in the type is what lets a caller hold onto one
 * without re-narrowing it — the alternative was a cast at every call site, and a cast is where a
 * success arm would slip through unnoticed.
 */
export type UploadFailure = {success: false; error: {message: string; code?: string}};

/** What one `PUT` of bytes reports back. `etag` is absent when the response withheld the header. */
export type PutOutcome = {status: number; etag?: string};

/** What `putBytes` takes. `expiresAt` is read by the CALLER on a 403 — see `uploadRejection`. */
export type PutParams = {
  url: string;
  body: Blob;
  contentType: string;
  onProgress?: (loaded: number) => void;
  signal?: AbortSignal;
};

/** The one wording for an upload the user stopped, wherever the stop was noticed. */
export function uploadCancelled(): UploadFailure {
  return {success: false, error: {message: 'Upload cancelled.', code: 'Cancelled'}};
}

/**
 * What S3 refusing the bytes means, in the user's terms.
 *
 * **A 403 here is routinely an EXPIRY, not a permissions problem**, and telling a user to contact an
 * administrator about it is wrong twice over: nothing is misconfigured, and the thing that would
 * actually help — upload it again — goes unsaid. This is what `expiresAt` is FOR; a caller that
 * discards it leaves the field satisfying its acceptance criterion in letter only.
 *
 * @param status - The HTTP status S3 answered with.
 * @param expiresAt - When the URL the transfer used was due to die.
 * @returns The service failure, with a code `errorMessages.ts` has a sentence for.
 */
export function uploadRejection(status: number, expiresAt: string): UploadFailure {
  if (status === 403 && Date.parse(expiresAt) <= Date.now()) {
    return {
      success: false,
      error: {message: 'The upload took longer than its secure link lasted.', code: 'UploadLinkExpired'}
    };
  }
  // Never S3's own body, which is XML and names a bucket. The code is what the surface maps, and
  // `AccessDenied` and `UploadFailed` both have authored sentences.
  return {
    success: false,
    error: {message: 'Failed to upload file.', code: status === 403 ? 'AccessDenied' : 'UploadFailed'}
  };
}

/**
 * `PUT`s one blob to a presigned URL, reporting progress as it goes.
 *
 * Resolves rather than rejecting on every path, including a thrown `open`/`setRequestHeader` — a
 * service in this app never throws, and a promise executor that throws REJECTS, which the upload
 * queue awaits with no catch: the item would sit in `uploading` for ever, its concurrency slot never
 * freed and nothing said to the user.
 *
 * @param params.url - The presigned URL to redeem.
 * @param params.body - The bytes, whole file or one slice of it.
 * @param params.contentType - Signed into the URL, so it must be the type actually sent.
 * @param params.onProgress - Called with bytes sent **for this request**. Aggregating across parts
 *   is the caller's job, because only the caller knows what the whole is.
 * @param params.signal - Aborts the transfer.
 * @returns The status and the `ETag` header, or a failure. A `status` of 0 means the request never
 *   completed: `aborted` says which kind.
 */
export function putBytes(params: PutParams): Promise<ServiceResult<PutOutcome>> {
  return new Promise((resolve) => {
    try {
      send(params, resolve);
    } catch (err) {
      // The thrown reason is carried rather than replaced: `open` throws on a malformed URL and
      // `setRequestHeader` on an invalid header value, both reachable from a route answer this
      // browser did not compose, and which of the two it was is the whole diagnostic.
      resolve(toServiceError(err, 'Failed to upload file'));
    }
  });
}

// Separated only so the executor above is nothing but its own guard — a `try` wrapping thirty lines
// is a `try` whose scope nobody re-reads.
function send(params: PutParams, resolve: (result: ServiceResult<PutOutcome>) => void): void {
  const {url, body, contentType, onProgress, signal} = params;

  // Checked as well as listened for, and BEFORE anything is sent. `addEventListener('abort')` on a
  // signal that has already fired never runs, so a cancel landing while this part's URL was being
  // minted would attach a listener to a spent signal and upload a whole part anyway — and, because
  // nothing would ever call `xhr.abort()`, the user's `Cancelled` would wait for that transfer to
  // finish. Both upload paths reach this line, so one check covers them.
  if (signal?.aborted) return resolve(uploadCancelled());

  const xhr = new XMLHttpRequest();

  // Listening on `xhr.upload`, not on `xhr`: the request's own progress events describe the
  // RESPONSE download, which for a `PUT` is empty and fires once at the end.
  if (onProgress) {
    xhr.upload.addEventListener('progress', (event) => {
      onProgress(event.loaded);
    });
  }

  const onAbort = () => xhr.abort();
  // Removed on every path, not left to `{once: true}`: that fires the listener at most once but does
  // not detach it, so a long-lived queue signal accumulates one closure per completed transfer.
  const settle = (result: ServiceResult<PutOutcome>) => {
    signal?.removeEventListener('abort', onAbort);
    resolve(result);
  };

  xhr.addEventListener('load', () => {
    // Read here and not by the caller: `getResponseHeader` is only meaningful on this object, and
    // an absent header answers `null` rather than throwing — which is what a CORS regression looks
    // like, and why the caller has to check rather than trust it.
    const etag = xhr.getResponseHeader('ETag');
    settle({
      success: true,
      data: etag === null ? {status: xhr.status} : {status: xhr.status, etag: etag.replace(/"/g, '')}
    });
  });
  xhr.addEventListener('error', () =>
    settle({success: false, error: {message: 'Failed to upload file.', code: 'NetworkUnavailable'}})
  );
  xhr.addEventListener('abort', () => settle(uploadCancelled()));

  xhr.open('PUT', url);
  // The SIGNED content type, byte for byte. A different one here fails the signature check at S3
  // and returns a 403 that reads as a permissions problem.
  xhr.setRequestHeader('Content-Type', contentType);

  // Attached AFTER the two calls that can throw. `open` throws on a malformed URL and
  // `setRequestHeader` on an invalid header value; a throw unwinds past `settle`, so a listener
  // attached earlier is never removed — the accumulation `{once: true}` is rejected above to
  // prevent, on a signal that lives as long as the session.
  signal?.addEventListener('abort', onAbort);
  try {
    xhr.send(body);
  } catch (err) {
    // `send` can throw too, and by this line the listener is attached — so the throw would unwind
    // past `settle` and leave one closure per failed transfer on a session-lifetime signal.
    signal?.removeEventListener('abort', onAbort);
    throw err;
  }
}
