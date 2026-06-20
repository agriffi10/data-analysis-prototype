import type { ReactNode } from 'react';
import { cx } from '../lib/cx';
import { useEscapeKey } from '../hooks/useEscapeKey';

type ModalProps = {
  onDismiss: () => void;
  ariaLabel: string;
  role?: 'dialog' | 'alertdialog';
  // When false (e.g. an action is in flight), backdrop-click and Escape don't
  // dismiss. The dialog's own buttons remain the way out.
  dismissible?: boolean;
  // Panel width/shape classes. Omit for the standard `max-w-md` card; pass your
  // own (e.g. `max-w-lg` + padding) to replace it — no tailwind-merge, so don't
  // expect a passed `max-w-*` to layer on top of a default.
  className?: string;
  children: ReactNode;
};

// SPEC-026 centered modal shell (react-best-practices abstraction pass): scrim +
// surface card + role/aria + backdrop-dismiss + Escape, consolidated from the
// ~10 dialogs that hand-rolled it. Children supply the body and footer; higher-
// level dialogs (ConfirmDialog) compose this.
export function Modal({
  onDismiss,
  ariaLabel,
  role = 'dialog',
  dismissible = true,
  className,
  children,
}: ModalProps) {
  useEscapeKey(onDismiss, dismissible);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={() => {
        if (dismissible) onDismiss();
      }}
    >
      <div
        role={role}
        aria-modal="true"
        aria-label={ariaLabel}
        className={cx(
          'w-full rounded-lg bg-surface shadow-lg',
          className ?? 'max-w-md',
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
