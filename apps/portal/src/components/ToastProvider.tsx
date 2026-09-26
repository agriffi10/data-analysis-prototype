import {useCallback, useMemo, useState} from 'react';
import {Toast} from './Toast';
import {ToastContext, type ToastApi, type ToastInput} from './toastContext';

/**
 * App-level toast host: mounts a single {@link Toast} and exposes push/dismiss to the
 * whole tree via {@link ToastContext}, replacing per-page toast state.
 * Single-toast semantics — a new push replaces the current toast; `dismiss` clears it.
 * Every push remounts the toast, so a repeated message gets its own display time and is
 * announced again rather than riding out the first one's timer.
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
  const push = useCallback((t: ToastInput) => setToast((prev) => ({input: t, pushId: (prev?.pushId ?? 0) + 1})), []);
  const dismiss = useCallback(() => setToast(null), []);
  const api = useMemo<ToastApi>(() => ({push, dismiss}), [push, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {toast && (
        <Toast
          key={toast.pushId}
          {...toast.input}
          onDismiss={dismiss}
        />
      )}
    </ToastContext.Provider>
  );
}
