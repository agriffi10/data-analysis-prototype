import {configValue} from '../../lib/runtimeConfig';

/** The compiled-in ceiling, used when nothing is configured. */
const DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024;

/**
 * The per-file upload ceiling, read at call time.
 *
 * A function rather than a const, and not in `fileBrowser.types.ts` where it used to
 * live: the value comes from the runtime document, which is not in hand at module load.
 * A non-numeric or non-positive configured value falls back to the default rather than
 * rejecting every upload.
 *
 * @returns The maximum size of a single upload, in bytes.
 */
export function maxUploadBytes(): number {
  const configured = Number(configValue('maxUploadBytes'));
  return Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_MAX_UPLOAD_BYTES;
}
