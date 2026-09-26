import {useRef, type MouseEvent, type PointerEvent} from 'react';

/**
 * Backdrop-dismiss for a scrim: the props to spread on the scrim element, which dismiss only
 * when the pointer both went DOWN on the scrim itself and released there.
 *
 * A click is dispatched to the nearest common ancestor of where the press started and where it
 * ended, so a drag that starts inside the panel — a text selection in a rename field that
 * overshoots the edge — lands its click on the scrim, and the panel's own `stopPropagation` never
 * runs. Checking the target at both ends is what tells that drag from a tap on the backdrop.
 *
 * @param onDismiss - Called for a genuine backdrop tap.
 * @param enabled - False while the surface refuses dismissal (an action in flight).
 * @returns `onPointerDown` and `onClick` for the scrim.
 *
 * @example
 * const backdrop = useBackdropDismiss(onClose, !busy);
 * <div className="fixed inset-0" {...backdrop}>…</div>
 */
export function useBackdropDismiss(onDismiss: () => void, enabled = true) {
  const pressedOnScrim = useRef(false);
  return {
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      pressedOnScrim.current = e.target === e.currentTarget;
    },
    onClick: (e: MouseEvent<HTMLElement>) => {
      const pressed = pressedOnScrim.current;
      pressedOnScrim.current = false;
      if (enabled && pressed && e.target === e.currentTarget) onDismiss();
    }
  };
}
