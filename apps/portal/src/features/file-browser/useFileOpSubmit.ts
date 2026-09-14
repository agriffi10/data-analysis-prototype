import {useRef, useState} from 'react';
import {useToast} from '../../components/toastContext';
import {toUserText} from '../../lib/errorMessages';
import {submitFileOperation} from './fileOps.service';
import {buildFileOpRequest, itemLabel, type FileOpGesture} from './fileOps.request';
import {useFileOpsInFlight} from './fileOpsInFlightContext';
import type {FileOpRequest, FileOpSpace} from './fileOps.types';

/**
 * What the toast calls this gesture.
 *
 * A rename and a same-folder copy are both `targetName` shapes of an ordinary verb, and the user
 * did not press a button called "move" — saying so would be the second most confusing thing this
 * surface could do, after claiming the work is finished.
 *
 * @param gesture - The gesture.
 * @returns The verb, capitalised for the head of a sentence.
 */
function requestVerb(gesture: FileOpGesture): string {
  if (gesture.operation === 'delete') return 'Delete';
  if (gesture.targetName) return gesture.operation === 'move' ? 'Rename' : 'Copy';
  return gesture.operation === 'move' ? 'Move' : 'Copy';
}

/**
 * What an enqueue attempt did.
 *
 * `busy` is NOT `refused` and the difference is load-bearing: a caller that puts the selection back
 * on a refusal would, on a double-click, put it back over the submit that is succeeding — leaving a
 * stale selection behind a request that worked, with nothing to explain it.
 */
export type SubmitOutcome = 'sent' | 'refused' | 'busy';

export type UseFileOpSubmitResult = {
  /** True while an enqueue is resolving — the SQS call, never the plane's run. */
  pending: boolean;
  /** Why this space cannot take another operation from this session right now, if it cannot. */
  busyReason: (space: FileOpSpace | undefined) => string | undefined;
  /** Enqueues a pre-built envelope (the conflict re-submit's door). Reports whether it worked. */
  submitRequest: (
    request: FileOpRequest,
    describe: {verb: string; itemCount: number; label?: string; destinationSpace?: FileOpSpace}
  ) => Promise<SubmitOutcome>;
  /** Builds and enqueues one gesture. Reports what it did. */
  submitGesture: (gesture: FileOpGesture, source: FileOpSpace) => Promise<SubmitOutcome>;
};

/**
 * The browser's half of handing an operation to the plane: build, gate, enqueue, record, say so.
 *
 * **Success means ENQUEUED, never completed**, and the wording says so — the established shape
 * for this component's three existing async submitters (`useFileSend`, `useArchive`,
 * `useRestoreArchive`), all of which promise a notification rather than claiming an outcome.
 *
 * **The per-space gate is kept deliberately.** The plane accepts unordered lock waiters *because*
 * the browser's own gate makes a same-space collision rare from one session; removing it would
 * invalidate an acceptance the plane's own design rests on. It is not a correctness mechanism —
 * two tabs defeat it — and it covers the destination space as well as the source, because a
 * cross-space move takes both locks.
 */
export function useFileOpSubmit(): UseFileOpSubmitResult {
  const toast = useToast();
  const inFlight = useFileOpsInFlight();
  const [pending, setPending] = useState(false);
  // A ref, not `pending`: a second click in the same tick reads the state before React has
  // re-rendered, so the state read loses the race. Without it a double-click enqueues twice —
  // two request ids, two executions, and the gate closing only after the first one resolves.
  const submitting = useRef(false);

  function busyReason(space: FileOpSpace | undefined): string | undefined {
    if (!space || !inFlight.busySpace(space)) return undefined;
    // Names the dismiss affordance, because a run whose notification never arrives is never
    // correlated and this sentence would otherwise be the whole explanation for a gate the user
    // cannot clear.
    return 'Another file operation is still running here. Wait for its notification, or dismiss it from the in-progress list.';
  }

  async function send(
    request: FileOpRequest,
    describe: {verb: string; itemCount: number; label?: string; destinationSpace?: FileOpSpace}
  ): Promise<SubmitOutcome> {
    if (submitting.current) return 'busy';
    submitting.current = true;
    try {
      setPending(true);
      const result = await submitFileOperation(request);
      if (!result.success) {
        toast.push({variant: 'danger', message: toUserText(result.error)});
        return 'refused';
      }
      inFlight.add({
        requestId: request.requestId,
        operation: request.operation,
        itemCount: describe.itemCount,
        label: describe.label,
        sourceSpace: request.source.space,
        destinationSpace: describe.destinationSpace,
        destinationPrefix: request.operation === 'delete' ? undefined : request.destination.prefix,
        submittedAt: new Date().toISOString(),
        state: 'submitted'
      });
      toast.push({
        variant: 'success',
        message: `${describe.verb} requested — you’ll get a notification when it finishes.`
      });
      return 'sent';
    } catch (err) {
      // Nothing here should throw: the request arrives built, its id minted behind the caller's
      // own guard, and the service returns a `ServiceResult`. This is the backstop for a breach of
      // that contract, which would otherwise reject past every caller with no message shown.
      toast.push({variant: 'danger', message: toUserText(err)});
      return 'refused';
    } finally {
      setPending(false);
      submitting.current = false;
    }
  }

  return {
    pending,
    busyReason,
    submitRequest: send,
    submitGesture: async (gesture, source) => {
      const destinationSpace = gesture.destination?.space;
      const blocked = busyReason(source) ?? busyReason(destinationSpace);
      if (blocked) {
        toast.push({variant: 'danger', message: blocked});
        return 'refused';
      }
      // Minted per SUBMIT, both of them. The request id is the queue's only double-submit guard
      // (content-based dedup is off), so reusing one across a retry makes the retry a silent
      // no-op; and a stale `submittedAt` makes the plane refuse the very objects the user just
      // agreed to overwrite.
      //
      // Built inside a guard because `crypto.randomUUID` is undefined outside a secure context
      // and the builder refuses a destination-less copy: both are throws on a path reachable from
      // a click, where an unhandled one aborts the event handler with no feedback at all.
      let request: FileOpRequest;
      try {
        request = buildFileOpRequest(gesture, source, {
          requestId: crypto.randomUUID(),
          submittedAt: new Date().toISOString()
        });
      } catch (err) {
        toast.push({variant: 'danger', message: toUserText(err)});
        return 'refused';
      }
      return send(request, {
        verb: requestVerb(gesture),
        itemCount: gesture.items.length,
        label: gesture.items.length === 1 ? itemLabel(gesture.items[0]) : undefined,
        destinationSpace
      });
    }
  };
}
