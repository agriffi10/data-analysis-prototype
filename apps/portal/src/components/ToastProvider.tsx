import {useCallback, useMemo, useState} from 'react';
import {Toast} from '../features/query/Toast';
import {ToastContext, type ToastApi, type ToastInput} from './toastContext';

/**
 * App-level toast host: mounts a single {@link Toast} and exposes push/dismiss to the
 * whole tree via {@link ToastContext} (SPEC-106 FR-003, replacing per-page toast state).
 * Single-toast semantics — a new push replaces the current toast; `dismiss` clears it.
 * Consume it with the `useToast` hook (in `toastContext.ts`).
 *
 * @example
 * <ToastProvider>
 *   <App />
 * </ToastProvider>
 * // elsewhere: const {push} = useToast(); push({variant: 'success', message: 'Saved'});
 */
export function ToastProvider({children}: {children: React.ReactNode}) {
  const [toast, setToast] = useState<ToastInput | null>(null);
  const push = useCallback((t: ToastInput) => setToast(t), []);
  const dismiss = useCallback(() => setToast(null), []);
  const api = useMemo<ToastApi>(() => ({push, dismiss}), [push, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {toast && (
        <Toast
          {...toast}
          onDismiss={dismiss}
        />
      )}
    </ToastContext.Provider>
  );
}
