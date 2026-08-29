import {configValue} from '../../lib/runtimeConfig';

/** The compiled-in ceiling, used when nothing is configured. */
const DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024;

/**
 * S3's hard limit on a single `PutObject`, which is what an upload is now.
 *
 * Exported so the test that fixes it can name the service limit it measures rather than restate a
 * number. It is exactly `DEFAULT_MAX_UPLOAD_BYTES`, which is the point: the managed upload this
 * replaced auto-multiparted above 5 MiB and capped in the same place, so the ceiling has not
 * moved — only the number of requests behind it.
 */
export const S3_SINGLE_PUT_MAX_BYTES = 5 * 1024 * 1024 * 1024;

/**
 * The per-file upload ceiling, read at call time and clamped to what one `PUT` can carry.
 *
 * A function rather than a const, and not in `fileBrowser.types.ts` where it used to
 * live: the value comes from the runtime document, which is not in hand at module load.
 * A non-numeric or non-positive configured value falls back to the default rather than
 * rejecting every upload.
 *
 * **The clamp is the new half, and it exists because the failure it prevents is invisible.** An
 * operator who raised the configured maximum above 5 GiB used to get a multipart upload; without
 * the clamp they now get an `EntityTooLarge` from S3 at the *end* of a long transfer, with no
 * failing test anywhere and nothing in the app that could have refused it earlier.
 *
 * @returns The maximum size of a single upload, in bytes.
 */
export function maxUploadBytes(): number {
  const configured = Number(configValue('maxUploadBytes'));
  const requested = Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_MAX_UPLOAD_BYTES;
  return Math.min(requested, S3_SINGLE_PUT_MAX_BYTES);
}
