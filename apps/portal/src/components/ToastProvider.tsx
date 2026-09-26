import {useCallback, useMemo, useRef, useState} from 'react';
import {Toast} from './Toast';
import {ToastContext, type ToastApi, type ToastInput} from './toastContext';

/**
 * App-level toast host: mounts a single {@link Toast} and exposes push/dismiss to the
 * whole tree via {@link ToastContext}, replacing per-page toast state.
 * Single-toast semantics — a new push replaces the current toast; `dismiss` clears it, or with a
 * push id clears it only while that push is still the one showing.
 * Every push restarts the toast's timer, so a repeated message gets its own display time rather
 * than riding out the first one's. The toast itself stays mounted across pushes: a live region
 * whose text changes in place is what screen readers announce reliably, and one remounted with its
 * text already in it is not.
 * Consume it with the `useToast` hook (in `toastContext.ts`).
 *
 * @example
 * <ToastProvider>
 *   <App />
 * </ToastProvider>
 * // elsewhere: const {push} = useToast(); push({variant: 'success', message: 'Saved'});
 */
export function ToastProvider({children}: {children: React.ReactNode}) {
  const [toast, setToast] = useState<{input: ToastInput; pushId: number} | null>(null);
  const lastPushId = useRef(0);
  const push = useCallback((t: ToastInput) => {
    lastPushId.current += 1;
    const pushId = lastPushId.current;
    setToast({input: t, pushId});
    return pushId;
  }, []);
  const dismiss = useCallback(
    (pushId?: number) => setToast((cur) => (pushId === undefined || cur?.pushId === pushId ? null : cur)),
    []
  );
  // The toast's own close and timer: a bare function, since a click would hand `dismiss` its event.
  const close = useCallback(() => setToast(null), []);
  const api = useMemo<ToastApi>(() => ({push, dismiss}), [push, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {toast && (
        <Toast
          pushId={toast.pushId}
          {...toast.input}
          onDismiss={close}
        />
      )}
    </ToastContext.Provider>
  );
}
