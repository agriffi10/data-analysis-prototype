import {useRef, type ReactNode} from 'react';
import {FocusTrap} from 'focus-trap-react';
import {cx} from '../lib/cx';
import {useEscapeBlock, useEscapeKey} from '../hooks/useEscapeKey';
import {EscapeLayer} from './EscapeLayer';
import {useBackdropDismiss} from './useBackdropDismiss';

type ModalProps = {
  onDismiss: () => void;
  ariaLabel: string;
  role?: 'dialog' | 'alertdialog';
  /**
   * When false (e.g. an action is in flight), backdrop-click and Escape don't
   * dismiss. The dialog's own buttons remain the way out.
   */
  dismissible?: boolean;
  /**
   * Panel width/shape classes. Omit for the standard `max-w-md` card; pass your
   * own (e.g. `max-w-lg` + padding) to replace it — no tailwind-merge, so don't
   * expect a passed `max-w-*` to layer on top of a default.
   *
   * An EMPTY STRING counts as omitted. `cx()` no longer returns one,
   * but a caller composing its own class string can still produce it, and `??` would
   * take it as a deliberate choice to have no width at all — leaving the panel's
   * `w-full` to fill the viewport.
   */
  className?: string;
  children: ReactNode;
};

/**
 * Centered modal shell: scrim + surface card + dialog role/aria +
 * backdrop-dismiss + Escape. Traps focus while open and restores it to the
 * trigger on close. Children supply the body and footer; higher-level dialogs
 * (e.g. ConfirmDialog) compose this.
 *
 * @example
 * <Modal ariaLabel="Rename file" onDismiss={() => setOpen(false)}>
 *   <form className="p-5">…</form>
 * </Modal>
 */
export function Modal({onDismiss, ariaLabel, role = 'dialog', dismissible = true, className, children}: ModalProps) {
  useEscapeKey(onDismiss, dismissible);
  // Present but refusing: swallow Escape rather than let it dismiss whatever is behind.
  useEscapeBlock(!dismissible);
  const panelRef = useRef<HTMLDivElement>(null);
  const backdrop = useBackdropDismiss(onDismiss, dismissible);

  return (
    // `initialFocus: false` defers to each consumer's own focus effect
    // (ConfirmDialog → a button, rename/save dialogs → an input). Escape is
    // owned by useEscapeKey above and the scrim owns backdrop-dismiss, so
    // focus-trap's own escape/outside-click handling is disabled.
    <FocusTrap
      focusTrapOptions={{
        initialFocus: false,
        fallbackFocus: () => panelRef.current ?? document.body,
        escapeDeactivates: false,
        allowOutsideClick: true
      }}>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
        {...backdrop}>
        <div
          ref={panelRef}
          role={role}
          aria-modal="true"
          aria-label={ariaLabel}
          tabIndex={-1}
          // The outer `p-4` keeps the panel off the screen edges on mobile; the
          // matching `max-h` (100dvh − the 1rem gutters) + `overflow-y-auto` cap
          // a long body to the viewport, scrolling inside the panel, at every
          // width. Desktop width/centering is unchanged (`max-w-md` default or a
          // passed class).
          className={cx(
            'max-h-[calc(100dvh-2rem)] w-full overflow-y-auto rounded-lg bg-surface shadow-lg',
            // `||`, not `??`: an empty class string means "I passed nothing", and the
            // default has to survive it. See the prop's doc comment.
            className || 'max-w-md'
          )}
          onClick={(e) => e.stopPropagation()}>
          {/* Anything opened from inside this modal is one layer deeper, so it wins
              Escape without either side coordinating. */}
          <EscapeLayer>{children}</EscapeLayer>
        </div>
      </div>
    </FocusTrap>
  );
}
