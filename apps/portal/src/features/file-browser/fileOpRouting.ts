import type {FileOpItem} from './fileOps.types';

/**
 * Does this selection go to the control plane, or stay synchronous in the browser?
 *
 * **The rule is a property of the SELECTION, never of the operation**: the same selection routes
 * the same way for copy, move and delete. An operation stays in the browser if and only if the
 * selection is exactly one item and that item is a file. Everything else — any folder, and any
 * multi-item selection — is enqueued.
 *
 * A **single folder is enqueued, including a folder rename**, and that is forced rather than
 * chosen: a rename is one `CopyObject` per contained object, so its cost cannot be bounded without
 * listing the folder first. It is the case a reader assumes is synchronous, which is why the tests
 * name it.
 *
 * The boundary was measured against the wrong quantity first, and the correction is worth knowing:
 * "does it need a listing?" is coherent but wrong, because a file-only copy or move of K files is a
 * sequential loop of `HeadObject` + `CopyObject` + `DeleteObject` — up to 3K round trips from the
 * user's laptop, which is precisely the cost this plane exists to remove.
 *
 * **This is the single home of the rule.** The plane does not re-implement it: it processes
 * whatever it is handed, and a request the rule would have kept synchronous is still valid. A test
 * sweeps `src/` and fails if a second module imports this, because the failure mode of two copies
 * is silent — the two disagree about one selection shape and half the gestures take the wrong path.
 *
 * **Where the call site must sit, because the throw depends on it.** An empty selection is a
 * programmer error, not an answer: the plane refuses an empty `source.items` as a request-shape
 * error, so returning "enqueue it" for zero items would send a request guaranteed to fail by
 * notification minutes later. The throw is unreachable from a real gesture today only because the
 * toolbar disables every bulk action at `count === 0`, and because `useDelete` and `useCopy`
 * early-return on an empty list before doing anything. `useMove`'s `runMove` has no such guard, so
 * a call placed at the head of it — rather than after the existing emptiness checks — would abort
 * a React event handler with no unmount and no feedback, and the user's click would silently do
 * nothing. Consult this AFTER the emptiness guard, never before it.
 *
 * @param items - The current selection. Must be non-empty. Without that precondition "not exactly
 *   one item" would route a zero-item selection to the plane.
 * @returns True when the operation must be enqueued.
 */
export function requiresControlPlane(items: readonly FileOpItem[]): boolean {
  if (items.length === 0) {
    throw new Error('requiresControlPlane needs a non-empty selection');
  }
  return !(items.length === 1 && items[0].kind === 'file');
}
