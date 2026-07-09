import {useCallback, useMemo, useState} from 'react';
import {Toast} from '../features/query/Toast';
import {ToastContext, type ToastApi, type ToastInput} from './toastContext';

// SPEC-106 FR-003 — one app-level toast host, replacing the per-page
// `useState<ToastState>` + local `<Toast>` render. Reuses the existing Toast
// view unchanged (variants, auto-dismiss, actionable toast). Single-toast
// semantics, matching the old per-page behavior: a new push replaces the
// current toast; `dismiss` clears it. The `useToast` hook lives in
// `toastContext.ts` (react-refresh/only-export-components).

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
