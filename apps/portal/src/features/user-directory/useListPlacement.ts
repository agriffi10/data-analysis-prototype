import {useLayoutEffect, useState, type RefObject} from 'react';
import {MAX_LIST_HEIGHT, listPlacement} from './comboboxPlacement';

/**
 * The box the list is actually clipped by — the nearest scrollable ancestor, or the viewport.
 *
 * This used to measure against `window.innerHeight`, which is right for a
 * combobox on a page and wrong for one inside a dialog: `Modal`'s panel is `overflow-y-auto`, so
 * a list with room below it *in the viewport* is still clipped by the panel. Measured live in
 * Add members, the list ran 97px past the dialog's bottom edge and showed 3 of 8 options.
 *
 * `overflow: hidden` counts: it clips just as hard as `auto` does, and does not scroll to
 * reveal what it cut off.
 *
 * @param from - The combobox wrapper.
 * @returns The clipping rectangle in viewport coordinates.
 */
function clippingRect(from: HTMLElement): {top: number; bottom: number} {
  for (let el = from.parentElement; el; el = el.parentElement) {
    const overflowY = getComputedStyle(el).overflowY;
    if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'hidden') {
      const box = el.getBoundingClientRect();
      // A zero-height ancestor is jsdom reporting nothing rather than a real clip; keep walking.
      if (box.height > 0) return {top: box.top, bottom: box.bottom};
    }
  }
  return {top: 0, bottom: window.innerHeight};
}

export type ListPlacement = {
  /** Render the list above the field rather than below it. */
  dropUp: boolean;
  /** The list's `max-height`, in px — applied inline, because it is a measurement. */
  maxHeight: number;
};

/**
 * Where an open suggestion list goes and how tall it may be, measured live.
 *
 * Flips above the field when there is not room below, and CAPS the list at the room there
 * actually is — measured against the box that clips it, which inside a dialog is the panel
 * and not the viewport. A bounded max-height plus this flip is sufficient: no positioning
 * library, which would be a Tech Stack change. Re-measured on scroll and resize, both
 * captured, because the field moves within the dialog's own scroll box and that scroll event
 * does not bubble to `window`. The arithmetic is `listPlacement`, kept pure so it can be
 * checked without a layout engine; this hook owns the measuring and the listeners.
 *
 * @param wrapperRef - The combobox wrapper the list is positioned against.
 * @param listOpen - Whether the list is showing; nothing is measured while it is not.
 * @returns The side and the height cap.
 *
 * @example
 * const {dropUp, maxHeight} = useListPlacement(wrapperRef, listOpen);
 */
export function useListPlacement(wrapperRef: RefObject<HTMLElement | null>, listOpen: boolean): ListPlacement {
  const [dropUp, setDropUp] = useState(false);
  const [maxHeight, setMaxHeight] = useState(MAX_LIST_HEIGHT);

  useLayoutEffect(() => {
    if (!listOpen) return;
    function measure() {
      const wrapper = wrapperRef.current;
      const box = wrapper?.getBoundingClientRect();
      if (!wrapper || !box) return;
      const clip = clippingRect(wrapper);
      const placement = listPlacement({
        fieldTop: box.top,
        fieldBottom: box.bottom,
        clipTop: clip.top,
        clipBottom: clip.bottom
      });
      setDropUp(placement.dropUp);
      setMaxHeight(placement.maxHeight);
    }
    measure();
    window.addEventListener('scroll', measure, true);
    window.addEventListener('resize', measure);
    return () => {
      window.removeEventListener('scroll', measure, true);
      window.removeEventListener('resize', measure);
    };
  }, [listOpen, wrapperRef]);

  return {dropUp, maxHeight};
}
