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
 * Both sides measure the SAME quantity — the UTF-8 bytes of the compact JSON selection — and that
 * had to be made true rather than assumed. Python escapes non-ASCII by default and JavaScript does
 * not, so a folder of accented filenames measured 26 KB here and 66 KB there, and the browser
 * accepted selections the plane then refused by notification. A test now compares the two
 * MEASUREMENTS on the same input, not just the two constants.
 */
const FILE_OPS_MAX_ITEMS = 200;
const FILE_OPS_MAX_SELECTION_BYTES = 64 * 1024;

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
  const selectionBytes = new TextEncoder().encode(JSON.stringify(request.source.items)).length;
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
