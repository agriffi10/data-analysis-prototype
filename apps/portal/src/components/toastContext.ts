import {createContext, useContext} from 'react';
import type {ToastState} from './Toast';

// Context + hook for the app-level toast host. Kept separate
// from ToastProvider.tsx so that component file only exports a component
// (react-refresh/only-export-components), mirroring uploadQueueContext.ts.

/** A pushed toast: the Toast view's props minus the host-owned `onDismiss`. */
export type ToastInput = ToastState & {
  action?: {label: string; onClick: () => void};
};

export type ToastApi = {
  /** Shows a toast in place of the current one, and returns the id that names this push. */
  push: (toast: ToastInput) => number;
  /**
   * Clears the toast on screen. Given a push id, clears it only while that push is still the one
   * showing, so a caller that outlives its own toast cannot take a later one down with it.
   */
  dismiss: (pushId?: number) => void;
};

/** The app-level toast host's API; provided by `ToastProvider`. */
export const ToastContext = createContext<ToastApi | null>(null);

/** Access the app-level toast host. Throws if used outside a `ToastProvider`. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
}
