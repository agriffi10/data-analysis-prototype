import {configValue} from '../../lib/runtimeConfig';

/** The compiled-in ceiling, used when nothing is configured. */
const DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024;

/**
 * S3's hard limit on a single `PutObject`, and the product's upload ceiling.
 *
 * Exported so the test that fixes it can name the service limit it measures rather than restate a
 * number. It is exactly `DEFAULT_MAX_UPLOAD_BYTES`, which is the point: the ceiling has survived
 * three upload designs unchanged — a managed multipart upload, one `PUT`, and now a server-chosen
 * mix of the two — because raising it is a product decision about cost and blast radius rather
 * than a technical one.
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
 * **The clamp exists because the failure it prevents is invisible.** Without it, an operator who
 * raised the configured maximum above 5 GiB would have every over-size upload refused far from
 * here — by S3 at the end of a long single `PUT`, or by the create route's own ceiling check —
 * with no failing test anywhere and nothing in the app refusing it before the user picked a file.
 *
 * @returns The maximum size of a single upload, in bytes.
 */
export function maxUploadBytes(): number {
  const configured = Number(configValue('maxUploadBytes'));
  const requested = Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_MAX_UPLOAD_BYTES;
  return Math.min(requested, S3_SINGLE_PUT_MAX_BYTES);
}
