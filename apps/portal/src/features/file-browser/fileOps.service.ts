import {enqueueFifoRequest} from '../../lib/enqueueFifo';
import {spaceDigest} from '../../lib/spaceDigest';
import type {ServiceResult} from '../../types/service.types';
import type {FileOpRequest, FileOpSpace} from './fileOps.types';

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
 * The bucket a space lives in, derived exactly as the control plane derives it
 * (`focommon.authz`): personal spaces are in the user-space bucket, shared spaces in the
 * shared-space bucket. Used only to build the FIFO group id — the enqueued body never carries a
 * bucket, because the verb resolves it server-side from the verified actor.
 */
function spaceBucket(space: FileOpSpace): string {
  const bucket =
    space.kind === 'personal' ? import.meta.env.VITE_S3_USER_SPACE_BUCKET : import.meta.env.VITE_S3_SHARED_SPACE_BUCKET;
  return (bucket as string | undefined) ?? '';
}

/**
 * Enqueue one file operation onto the file-ops FIFO queue — the browser's only file-ops AWS call,
 * and its only file-ops privilege. The async control plane performs the copy, move or delete, so
 * success means *enqueued*, never completed.
 *
 * The token rides as a top-level `actor`, matching every other plane's envelope: the shared DLQ
 * drain reads and redacts that field flatly, so a nested one would mean a dead-lettered request
 * notified nobody *and* wrote the raw JWT to CloudWatch.
 *
 * `MessageDeduplicationId` is the caller's `requestId` — the queue has content-based dedup OFF, so
 * that id is the only double-submit guard, and it must be minted per submit rather than per
 * dialog. Reusing one across a retry makes the retry a silent no-op.
 */
export async function submitFileOperation(request: FileOpRequest): Promise<ServiceResult<void>> {
  const selectionBytes = new TextEncoder().encode(JSON.stringify(request.source.items)).length;
  if (request.source.items.length > FILE_OPS_MAX_ITEMS || selectionBytes > FILE_OPS_MAX_SELECTION_BYTES) {
    return {
      success: false,
      error: {message: 'That selection is too large to do in one go', code: 'SelectionTooLarge'}
    };
  }

  return enqueueFifoRequest<void>({
    // Read at call time (not module load) so tests can stub the env — a module-level
    // import.meta.env const is read before vi.stubEnv runs.
    queueUrl: import.meta.env.VITE_FILE_OPS_QUEUE_URL as string | undefined,
    notConfiguredMessage: 'File operations are not configured',
    build: async (idToken) => ({
      body: {
        requestId: request.requestId,
        actor: idToken,
        operation: request.operation,
        source: request.source,
        // Gated on the OPERATION, not on whether the fields happen to be set: the plane rejects
        // them on a delete rather than ignoring them, so a stale destination carried over from a
        // re-submitted request object would refuse the whole thing. The union in `fileOps.types`
        // makes that unconstructable in TypeScript; this keeps it true of the wire.
        ...(request.operation === 'delete'
          ? {}
          : {
              destination: request.destination,
              onConflict: request.onConflict,
              submittedAt: request.submittedAt
            })
      },
      messageGroupId: await spaceDigest(spaceBucket(request.source.space), request.source.space.name),
      deduplicationId: request.requestId,
      data: undefined
    })
  });
}
