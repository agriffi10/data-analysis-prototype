import {CopyObjectCommand, GetObjectCommand, PutObjectCommand} from '@aws-sdk/client-s3';
import {getS3Client} from './s3Client';
import {withCredentialRetry} from './credentialRetry';
import {toServiceError} from './serviceResult';
import {isNotFound} from './s3Errors';
import type {ServiceResult} from '../types/service.types';

/**
 * Why a document could not be used, when it could not be used.
 *
 * `newer` is NOT a failure of the document — it is a failure of THIS build to be
 * current, and it is the one outcome that must never be overwritten or quarantined:
 * doing either would downgrade a document a newer tab wrote, which is the exact class
 * of loss the write path's refusal exists to prevent.
 */
export type UnusableReason = 'unparseable' | 'newer';

/** What a write-path parser returns instead of a bare success/failure. */
export type DocumentParse<T> = {readable: true; value: T} | {readable: false; reason: UnusableReason};

/**
 * A read-modify-write's result, plus whether the previous document had to be set aside
 * before it could be written.
 *
 * `recovered` rides alongside `data` rather than inside it because it describes HOW the
 * write happened, not what was written — the document the caller gets back is a perfectly
 * ordinary one, and every existing consumer of `data` is unaffected. It is the only signal
 * that the user's earlier content is no longer in the list they are now looking at, so a
 * surface that can speak has to be able to see it.
 */
export type WriteOutcome<T> = ServiceResult<T> & {recovered?: boolean};

/**
 * Classify a versioned settings document into readable / newer / unparseable.
 *
 * The write path needs three answers where a boolean parser gave two. A body carrying a
 * `version` GREATER than the one this build writes is a document from a newer client, not
 * a corrupt one — telling the two apart is the whole point, because the corrupt case is
 * recovered by quarantining the bytes and the newer case must be left strictly alone.
 *
 * Written once here rather than per document: `saved-queries.json` and `query-history.json`
 * had byte-identical parsers differing only in the array field's name, and a tightened
 * classifier that reached one of them and not the other is the drift this closes.
 *
 * An absent or zero-byte body is the EMPTY document, not a failure — absence has nothing
 * to lose. Everything else that is not the current version and shaped right is
 * `unparseable`, including a version BELOW the current one: this build has no reader for
 * it either.
 *
 * @param opts.body - The raw object body; `undefined`/empty means no document yet.
 * @param opts.version - The document version this build reads and writes.
 * @param opts.empty - Freshly allocates the empty document (never a shared value).
 * @param opts.isReadable - Validates the version-matched body's own shape (its array field).
 * @returns The classification; `value` is present only when `readable`.
 *
 * @example
 * classifyDocument({body, version: 1, empty: emptyStore, isReadable: (d) => Array.isArray(d.queries)})
 */
export function classifyDocument<T>(opts: {
  body: string | undefined;
  version: number;
  empty: () => T;
  isReadable: (parsed: Record<string, unknown>) => boolean;
}): DocumentParse<T> {
  const {body, version, empty, isReadable} = opts;
  if (!body) return {readable: true, value: empty()};

  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return {readable: false, reason: 'unparseable'};
  }

  // An array is an object to `typeof`, and `[].version` is `undefined` — the numeric
  // check below rejects it, but naming the shape here keeps that from being an accident.
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return {readable: false, reason: 'unparseable'};
  }

  const document = parsed as Record<string, unknown>;
  if (typeof document.version !== 'number' || !Number.isFinite(document.version)) {
    return {readable: false, reason: 'unparseable'};
  }

  // Checked BEFORE the shape: a newer document is newer whatever else it contains, and a
  // newer schema is free to have renamed or dropped the field this build validates.
  if (document.version > version) return {readable: false, reason: 'newer'};

  if (document.version === version && isReadable(document)) return {readable: true, value: document as T};
  return {readable: false, reason: 'unparseable'};
}

/**
 * Copy an unreadable document aside, server-side, so the caller may then overwrite it.
 *
 * The way out of a refusal that would otherwise be permanent: `user_settings/` denies
 * `s3:DeleteObject` and the bucket is unversioned, so a body the write path cannot read
 * can be neither removed nor (correctly) replaced, and saving stays broken for that user
 * forever. Quarantine keeps the evidence AND unblocks them, which neither destroying the
 * document nor refusing it does.
 *
 * The key is the source key with `.unreadable-{ISO-8601 basic UTC}-{token}.json` appended —
 * same prefix, so the user's existing `GetObject`/`PutObject` grants already cover it and no
 * IAM changes. Every segment is app-generated (a catalog-safe username, a fixed basename, a
 * generated timestamp and token), so `CopySource` needs no percent-encoding.
 *
 * THE RANDOM TOKEN IS LOAD-BEARING, not decoration. `CopyObject` copies whatever is live at
 * copy time, and nothing ties this copy to the body the caller classified. Two tabs that
 * both find the same corrupt document race: the first copies the corrupt bytes aside and
 * repairs the document, and the second — reading a key derived only from a clock it shares —
 * would copy the now-REPAIRED document over the first one's quarantine object, destroying
 * the only surviving copy of what the user actually had. A per-call token means the loser
 * writes a redundant object instead of overwriting evidence. (It leaves the ordinary
 * last-writer-wins race on the document itself alone; that one is accepted and is not this
 * function's business.)
 *
 * A `CopyObject`, never a read-then-write: the unreadable bytes never enter the browser,
 * so an arbitrarily large or hostile document costs no memory and no second `GetObject`.
 *
 * The quarantine object inherits the folder's delete deny, so neither the app nor the user
 * can ever remove one — only an administrator working directly in the AWS console can.
 * Accepted: one object per genuine corruption event is a smaller problem than the evidence
 * being destroyed, and accumulation is not a loop — the document written after a quarantine
 * is one the app serialized itself, so a second quarantine needs a second, independent
 * corruption. Never throws.
 *
 * @param opts.bucket - The bucket holding the document (source and destination).
 * @param opts.key - The unreadable document's key.
 * @param opts.now - Injected for determinism in tests; defaults to the current time.
 * @returns The quarantine key on success; a failure the caller must treat as fatal.
 */
export async function quarantineDocument(opts: {
  bucket: string;
  key: string;
  now?: Date;
}): Promise<ServiceResult<{quarantineKey: string}>> {
  const {bucket, key, now = new Date()} = opts;
  const quarantineKey = `${key}.unreadable-${basicUtcTimestamp(now)}-${crypto.randomUUID().slice(0, 8)}.json`;

  return withCredentialRetry(getS3Client, async (client) => {
    try {
      await client.send(new CopyObjectCommand({Bucket: bucket, Key: quarantineKey, CopySource: `${bucket}/${key}`}));
      return {success: true, data: {quarantineKey}};
    } catch (err) {
      return toServiceError(err, 'Failed to set the unreadable file aside');
    }
  });
}

/** `2026-08-10T13:15:00.123Z` → `20260810T131500Z` (ISO-8601 basic, UTC). */
function basicUtcTimestamp(now: Date): string {
  return now
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d+Z$/, 'Z');
}

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
 * a RACE on a single user's own file is last-writer-wins, which every caller accepts.
 *
 * That is the worst outcome of a race, NOT the worst outcome available. The write is
 * unconditional, so it has no precondition to fail on: whatever the caller read is
 * committed verbatim. A read that forgivingly returned the EMPTY document for a body it
 * could not parse therefore commits emptiness over the real document — losing the whole
 * file rather than one update. The forgiving parse is right for DISPLAY and wrong before a
 * write, so a read-modify-write must classify the body first (`classifyDocument`, and see
 * `savedQueries.service.ts`'s `storeForWrite`) and reach this function only for a body it
 * could read or one it has first copied aside with `quarantineDocument`; an absent object
 * is still the empty document, because absence has nothing to lose.
 *
 * The control planes close the same hazard the other way, with a conditional write —
 * `shared-space-common/cache.py` treats an unreadable object as absent and notes that is
 * "safe only because the create path is conditional". The browser has no such precondition,
 * so it refuses instead.
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
