import {apiRequest} from '../../lib/apiClient';
import {discardPayload} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {FileOpRequest} from './fileOps.types';

/**
 * The control plane's own caps, mirrored (`focommon/config.py`).
 *
 * The mirror is not belt-and-braces. `validate-authorize` enforces these in the machine's first
 * task, and a request too large for `StartExecution` never reaches it — the Pipe cannot start the
 * execution at all, so the message dead-letters and the user learns about it from the DLQ drain
 * minutes later rather than from a refusal now. Below the caps the verb is still the authority;
 * these exist so the common case fails fast and legibly.
 *
 * Both sides measure the SAME quantity — the bytes of the compact JSON selection with non-ASCII
 * ESCAPED — and that had to be made true rather than assumed. A test compares the two
 * MEASUREMENTS on the same input, not just the two constants.
 *
 * Escaped, because that is what travels. The two sides first disagreed the other way — Python
 * escapes non-ASCII by default and `JSON.stringify` does not, so a folder of accented filenames
 * measured 26 KB here and 66 KB there — and were reconciled on the LITERAL form, which agreed with
 * each other and with nothing else: the API re-serialises the body with the default escaping one
 * hop before the Pipe. An accented selection therefore passed both caps, reached the queue at three
 * times its measured size, and produced a failure state over the 256 KB limit on a state with no
 * catch, where the user hears nothing at all. An ASCII selection is unaffected.
 */
const FILE_OPS_MAX_ITEMS = 200;
const FILE_OPS_MAX_SELECTION_BYTES = 64 * 1024;

/** Non-ASCII, which the wire's serialiser escapes to `\uXXXX` and `JSON.stringify` leaves literal. */
const NON_ASCII = /[\u007f-\uffff]/g;

/**
 * The serialized size of a value as the API sends it, in bytes.
 *
 * `JSON.stringify` matches Python's escaping for every control character already; the two part
 * company from `U+007F` up, which this closes. The result is pure ASCII, so its length in
 * characters is its length in bytes.
 */
function wireBytes(value: unknown): number {
  return JSON.stringify(value).replace(NON_ASCII, (character) =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`
  ).length;
}

/**
 * Enqueue one file operation onto the file-ops FIFO queue — the browser's only file-ops write,
 * and its only file-ops privilege. The async control plane performs the copy, move or delete, so
 * success means *enqueued*, never completed.
 *
 *
 * The `requestId` stays minted PER SUBMIT in the browser: it is still the double-submit guard,
 * the API echoes it rather than minting one, and reusing it across a retry would make the retry a
 * silent no-op. The FIFO keys themselves are derived server-side now.
 */
export async function submitFileOperation(request: FileOpRequest): Promise<ServiceResult<void>> {
  const selectionBytes = wireBytes(request.source.items);
  if (request.source.items.length > FILE_OPS_MAX_ITEMS || selectionBytes > FILE_OPS_MAX_SELECTION_BYTES) {
    return {
      success: false,
      error: {message: 'That selection is too large to do in one go', code: 'SelectionTooLarge'}
    };
  }

  return discardPayload(
    await apiRequest('fileOps.enqueue', {
      body: {
        requestId: request.requestId,
        operation: request.operation,
        source: request.source,
        ...(request.operation === 'delete'
          ? {}
          : {
              destination: request.destination,
              onConflict: request.onConflict,
              submittedAt: request.submittedAt
            })
      }
    })
  );
}
