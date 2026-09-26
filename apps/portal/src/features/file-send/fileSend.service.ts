import {wireBytes} from '../../lib/wireBytes';
import {apiRequest} from '../../lib/apiClient';
import {discardPayload} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {FileSendRequest} from './fileSend.types';

/**
 * The control plane's own caps, mirrored (`fscommon/config.py`). Terraform and Python already
 * share numbers this way on the table-share plane, and a test holds each pair together.
 *
 * The mirror is not belt-and-braces. `validate-authorize` enforces these in the machine's first
 * task, and a request too large for `StartExecution` never reaches it — the Pipe cannot start
 * the execution at all, so the message dead-letters and the sender learns about it from the DLQ
 * drain minutes later rather than from a refusal now. Below the caps the verb is still the
 * authority; these exist so the common case fails fast and legibly.
 */
const SEND_MAX_ITEMS = 200;
const SEND_MAX_ITEM_BYTES = 84 * 1024;
/** The plane's recipient cap, mirrored so a longer list is refused now rather than by notification later. */
export const SEND_MAX_RECIPIENTS = 50;

/**
 * Enqueue a send-files request through the API's `fileSend.enqueue` route — the browser's only
 * file-send write. The browser holds no privilege on the plane: the API's execution role puts the
 * request on the file-send FIFO queue, and the async control plane copies the files into each
 * recipient's `shared_files/{sender}/` inbox, so success means *enqueued*, not sent.
 *
 * The `requestId` stays minted PER SUBMIT in the browser: it is still the double-submit guard,
 * the API echoes it rather than minting one, and reusing it across a retry would make the retry a
 * silent no-op. The FIFO keys themselves are derived server-side now.
 */
export async function enqueueFileSend(req: FileSendRequest): Promise<ServiceResult<void>> {
  const selectionBytes = wireBytes(req.items);
  if (req.items.length > SEND_MAX_ITEMS || selectionBytes > SEND_MAX_ITEM_BYTES) {
    return {
      success: false,
      error: {
        message: 'That selection is too large to send in one go. Select fewer items and try again.',
        code: 'SelectionTooLarge'
      }
    };
  }

  if (req.recipients.length > SEND_MAX_RECIPIENTS) {
    return {
      success: false,
      error: {
        message: `You can send to at most ${SEND_MAX_RECIPIENTS} recipients at a time. Send to the rest in a second request.`,
        code: 'TooManyRecipients'
      }
    };
  }

  return discardPayload(
    await apiRequest('fileSend.enqueue', {
      body: {
        requestId: req.requestId,
        source: {space: req.space, items: req.items},
        recipients: req.recipients
      }
    })
  );
}
