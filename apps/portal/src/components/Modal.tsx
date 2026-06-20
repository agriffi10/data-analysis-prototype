import { useRef, type ReactNode } from 'react';
import { FocusTrap } from 'focus-trap-react';
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
  const panelRef = useRef<HTMLDivElement>(null);

  return (
    // Trap focus within the panel while open; restore it to the trigger on
    // close. `initialFocus: false` defers to each consumer's own focus effect
    // (ConfirmDialog → a button, Rename/SaveQuery → an input). Escape is owned
    // by useEscapeKey above, and the full-screen scrim owns backdrop-dismiss, so
    // we disable focus-trap's escape/outside-click handling.
    <FocusTrap
      focusTrapOptions={{
        initialFocus: false,
        fallbackFocus: () => panelRef.current ?? document.body,
        escapeDeactivates: false,
        allowOutsideClick: true,
      }}
    >
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
        onClick={() => {
          if (dismissible) onDismiss();
        }}
      >
        <div
          ref={panelRef}
          role={role}
          aria-modal="true"
          aria-label={ariaLabel}
          tabIndex={-1}
          className={cx(
            'w-full rounded-lg bg-surface shadow-lg',
            className ?? 'max-w-md',
          )}
          onClick={(e) => e.stopPropagation()}
        >
          {children}
        </div>
      </div>
    </FocusTrap>
  );
}
