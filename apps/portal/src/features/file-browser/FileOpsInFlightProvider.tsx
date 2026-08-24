import {useCallback, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {useAuth} from '../auth';
import {useNotifications} from '../notifications';
import {FILE_OPS_MACHINE_TIMEOUT_SECONDS} from './fileOps.constants';
import {FileOpsInFlightContext, isOpen, sameSpace} from './fileOpsInFlightContext';
import type {FileOpSpace, InFlightOperation} from './fileOps.types';

/**
 * The session's record of what it has handed to the file-operations plane.
 *
 * **Session-scoped and mounted at the app shell**, for the reason the upload queue is: the file
 * browser remounts on a `?space=` change and on every route change away and back, and an
 * operation that outlives the tab's attention must not vanish with the component that started
 * it. **Nothing is persisted.** The notification is the durable channel — a stored queue would
 * be a second writer to state the plane owns, and it would survive the only thing that can
 * settle it.
 *
 * **An entry settles when a notification carrying its `requestId` arrives.** Without that
 * nothing clears it, and the per-space submit gate below would hold a space until the machine's
 * own ceiling — worse than the `isBusy` gate it replaces. This is correlation for the ENTRY and
 * not notification-driven listing invalidation, which is deliberately not the mechanism: the
 * listing catches up on window focus instead, because the notification poll is a minute wide and
 * pauses on a hidden tab.
 *
 * **Whether the run succeeded is read off the payload's shape, not asserted by the producer.**
 * `focommon.notify.outcome_payload` always carries `operation`; the whole-request failure path's
 * `request_payload` carries `requestId` alone. Both states behave identically here — dismissible,
 * gate released — so a mis-inference costs a word on a card and nothing else, which is what makes
 * reading another module's payload shape an acceptable coupling.
 *
 * **Some runs settle by neither route.** `request_payload` returns nothing at all in the
 * pre-identity window, and the shared DLQ drain writes no payload — so a request that
 * dead-letters is never correlated. That is what the two belt-and-braces bounds are for: every
 * entry is dismissible, and every entry expires at the machine's `TimeoutSeconds`.
 */
export function FileOpsInFlightProvider({children}: {children: ReactNode}) {
  const {status, user} = useAuth();
  const username = status === 'authenticated' ? (user?.username ?? null) : null;
  // The same query key the always-mounted header bell polls, so this observer costs no extra
  // request — and resolves to nothing at all while signed out.
  const {notifications} = useNotifications(username);
  const [operations, setOperations] = useState<InFlightOperation[]>([]);

  // Expiry is scheduled per entry rather than swept on an interval: a timer ticking at the shell
  // would re-render the whole app for a state nothing normally reaches. Keyed by request id and
  // cleared on DISMISS, so a dismissed entry's three-hour timer does not survive to wake the shell
  // for a row that is no longer there. A SETTLED entry keeps its timer — pruning it would mean
  // mutating this ref from the render-time correlation below — and the timeout returns `prev`
  // untouched when it finds one, so the wake-up costs nothing but itself.
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  useEffect(() => {
    const held = timers;
    return () => held.current.forEach(clearTimeout);
  }, []);

  const add = useCallback((operation: InFlightOperation) => {
    setOperations((prev) => [operation, ...prev]);
    timers.current.set(
      operation.requestId,
      setTimeout(() => {
        timers.current.delete(operation.requestId);
        setOperations((prev) => {
          // Returns `prev` unchanged when the entry has already settled or gone: a fresh array
          // would re-render the whole shell and hand out a new context value for no new state.
          const stale = prev.find((entry) => entry.requestId === operation.requestId);
          if (!stale || stale.state !== 'submitted') return prev;
          return prev.map((entry) =>
            entry.requestId === operation.requestId ? {...entry, state: 'expired' as const} : entry
          );
        });
      }, FILE_OPS_MACHINE_TIMEOUT_SECONDS * 1000)
    );
  }, []);

  const dismiss = useCallback((requestId: string) => {
    const timer = timers.current.get(requestId);
    if (timer !== undefined) {
      clearTimeout(timer);
      timers.current.delete(requestId);
    }
    setOperations((prev) => prev.filter((entry) => entry.requestId !== requestId));
  }, []);

  // Folded in during RENDER — the "adjust state when a value changes" pattern, guarded so it sets
  // only on an actual change — rather than in an effect, which cascades a second render for every
  // poll and which the lint rightly refuses. The same shape `useNotifications` uses to retire its
  // own optimistic overlay.
  if (operations.some((entry) => entry.state === 'submitted')) {
    const next = operations.map((entry) => {
      if (entry.state !== 'submitted') return entry;
      const row = notifications.find((notification) => notification.payload?.requestId === entry.requestId);
      if (!row) return entry;
      return {...entry, state: row.payload?.operation ? ('settled' as const) : ('refused' as const)};
    });
    // Identity, not a flag: every unchanged entry is returned as itself above, so a differing
    // reference IS the change — and a `let` reassigned inside the map would be state the render
    // carries, which the immutability rule refuses for the reason this comment exists.
    if (next.some((entry, index) => entry !== operations[index])) setOperations(next);
  }

  const busySpace = useCallback(
    (space: FileOpSpace) => {
      const now = Date.now();
      return operations.some(
        (entry) =>
          isOpen(entry, now) &&
          (sameSpace(entry.sourceSpace, space) ||
            (entry.destinationSpace !== undefined && sameSpace(entry.destinationSpace, space)))
      );
    },
    [operations]
  );

  const value = useMemo(() => ({operations, add, dismiss, busySpace}), [operations, add, dismiss, busySpace]);

  return <FileOpsInFlightContext.Provider value={value}>{children}</FileOpsInFlightContext.Provider>;
}
