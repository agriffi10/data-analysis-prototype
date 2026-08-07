import {createContext, useContext} from 'react';
import type {ToastState} from './Toast';

// SPEC-106 FR-003 — context + hook for the app-level toast host. Kept separate
// from ToastProvider.tsx so that component file only exports a component
// (react-refresh/only-export-components), mirroring uploadQueueContext.ts.

/** A pushed toast: the Toast view's props minus the host-owned `onDismiss`. */
export type ToastInput = ToastState & {
  action?: {label: string; onClick: () => void};
};

export type ToastApi = {
  push: (toast: ToastInput) => void;
  dismiss: () => void;
};

export const ToastContext = createContext<ToastApi | null>(null);

/** Access the app-level toast host. Throws if used outside a `ToastProvider`. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
}
