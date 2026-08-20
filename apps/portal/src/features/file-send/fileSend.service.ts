import {enqueueFifoRequest} from '../../lib/enqueueFifo';
import {spaceDigest} from '../../lib/spaceDigest';
import type {ServiceResult} from '../../types/service.types';
import type {FileSendRequest, SendSourceSpace} from './fileSend.types';

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
const SEND_MAX_ITEM_BYTES = 96 * 1024;

/**
 * The bucket a source space lives in, derived exactly as the control plane derives it
 * (`fscommon.authz.authorize_source`): personal spaces are in the user-space bucket, shared
 * spaces in the shared-space bucket. Used only to build the FIFO group id — the enqueued body
 * never carries a bucket, because the verb resolves it server-side from the verified actor.
 */
function sourceBucket(space: SendSourceSpace): string {
  const bucket =
    space.kind === 'personal' ? import.meta.env.VITE_S3_USER_SPACE_BUCKET : import.meta.env.VITE_S3_SHARED_SPACE_BUCKET;
  return (bucket as string | undefined) ?? '';
}

/**
 * Enqueue a send-files request onto the file-send FIFO queue — the browser's only file-send
 * AWS call, and its only file-send privilege. The async control plane copies the files into
 * each recipient's `shared_files/{sender}/` inbox, so success means *enqueued*, not sent.
 *
 * The token rides as a top-level `actor`, matching every other plane's envelope: the
 * shared DLQ drain reads and redacts that field flatly, so a nested one would mean a
 * dead-lettered send notified nobody and wrote the raw JWT to CloudWatch.
 *
 * `MessageDeduplicationId` is the caller's `requestId` — the queue has content-based dedup
 * OFF, so that id is the only double-submit guard, and it must therefore be minted per submit
 * rather than per dialog.
 */
export async function enqueueFileSend(req: FileSendRequest): Promise<ServiceResult<void>> {
  const selectionBytes = new TextEncoder().encode(JSON.stringify(req.items)).length;
  if (req.items.length > SEND_MAX_ITEMS || selectionBytes > SEND_MAX_ITEM_BYTES) {
    return {
      success: false,
      error: {message: 'That selection is too large to send in one go', code: 'SelectionTooLarge'}
    };
  }

  return enqueueFifoRequest<void>({
    // Read at call time (not module load) so tests can stub the env — a module-level
    // import.meta.env const is read before vi.stubEnv runs.
    queueUrl: import.meta.env.VITE_FILE_SEND_QUEUE_URL as string | undefined,
    notConfiguredMessage: 'Sending files is not configured',
    build: async (idToken) => ({
      body: {
        requestId: req.requestId,
        actor: idToken,
        source: {space: req.space, items: req.items},
        recipients: req.recipients
      },
      messageGroupId: await spaceDigest(sourceBucket(req.space), req.space.name),
      deduplicationId: req.requestId,
      data: undefined
    })
  });
}
