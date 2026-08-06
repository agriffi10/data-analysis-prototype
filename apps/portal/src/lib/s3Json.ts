import {GetObjectCommand, PutObjectCommand} from '@aws-sdk/client-s3';
import {getS3Client} from './s3Client';
import {withCredentialRetry} from './credentialRetry';
import {toServiceError} from './serviceResult';
import {isNotFound} from './s3Errors';
import type {ServiceResult} from '../types/service.types';

/**
 * Read one JSON document out of S3 — the skeleton seven services had written out
 * longhand (saved queries, query history, notifications, shared-space connections,
 * data-quality reports, data-quality runs, and the username directory, which was copied
 * from the others after the audit that named the first six). Twelve lines each,
 * differing only in the key, the parse function and the failure wording.
 *
 * `parse` receives the raw body — a `string` when the object exists, `undefined` when S3
 * returned no body — and decides what that body means, returning a `ServiceResult` so
 * that a document whose malformed state is a *failure* can say so. Most callers treat a
 * malformed body as the empty document, which is deliberate: a corrupt settings file must
 * not lock a user out of a page whose source of truth lives elsewhere. The data-quality
 * report is the exception, and the reason `parse` returns a result rather than a value —
 * the user followed a link to one specific report, so "unreadable" is the honest answer.
 *
 * NOT-FOUND IS THE CALLER'S DECISION. `onMissing` maps a 404/NoSuchKey to whatever that
 * document's absence means — the empty state for the settings documents, a specific
 * user-facing error for a data-quality report. Omit it and the miss falls through to
 * `fallbackMessage` like any other failure. A thunk rather than a value because every
 * caller's empty document is freshly allocated (`emptyStore()`, `emptyHistory()`, `[]`)
 * — a value would hand every call the same mutable object.
 *
 * Never throws — `ServiceResult` in, `ServiceResult` out, like every service in this repo.
 * A `parse` that throws anyway is caught and wrapped in `fallbackMessage`, but no caller
 * should rely on that: interpreting the body is the parser's whole job.
 * Follows `lib/enqueueFifo.ts`'s conventions: one options object, the user-safe wording
 * supplied by the caller, `withCredentialRetry` around the send.
 *
 * @example
 * return readJsonDocument({
 *   bucket: userSpaceBucket(),
 *   key: storeKey(username),
 *   parse: (body) => ({success: true, data: parseStore(body)}),
 *   onMissing: () => ({success: true, data: emptyStore()}),
 *   fallbackMessage: 'Failed to load saved queries'
 * });
 */
export async function readJsonDocument<T>(opts: {
  bucket: string;
  key: string;
  /** Must be TOTAL — a malformed body is that document's business, not an exception. */
  parse: (body: string | undefined) => ServiceResult<T>;
  /** What a 404/NoSuchKey means here. Omit to treat a miss as an ordinary failure. */
  onMissing?: () => ServiceResult<T>;
  fallbackMessage: string;
}): Promise<ServiceResult<T>> {
  const {bucket, key, parse, onMissing, fallbackMessage} = opts;

  return withCredentialRetry(getS3Client, async (client) => {
    try {
      const response = await client.send(new GetObjectCommand({Bucket: bucket, Key: key}));
      return parse(await response.Body?.transformToString());
    } catch (err) {
      if (onMissing && isNotFound(err)) return onMissing();
      return toServiceError(err, fallbackMessage);
    }
  });
}

/**
 * Write one JSON document to S3. PutObject only — never a delete — so the worst outcome of
 * a race on a single user's own file is last-writer-wins, which every caller accepts.
 */
export async function writeJsonDocument(opts: {
  bucket: string;
  key: string;
  value: unknown;
  fallbackMessage: string;
}): Promise<ServiceResult<void>> {
  const {bucket, key, value, fallbackMessage} = opts;

  return withCredentialRetry(getS3Client, async (client) => {
    try {
      await client.send(
        new PutObjectCommand({
          Bucket: bucket,
          Key: key,
          Body: JSON.stringify(value),
          ContentType: 'application/json'
        })
      );
      return {success: true, data: undefined};
    } catch (err) {
      return toServiceError(err, fallbackMessage);
    }
  });
}
