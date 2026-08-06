import {useEffect, useRef} from 'react';
import {useEscapeDepth} from './escapeLayerContext';

type Layer = {
  depth: number;
  /** `null` swallows the key — the layer is present but refuses to be dismissed. */
  handler: {current: (() => void) | null};
};

/**
 * Every Escape-dismissible surface currently on screen. One document listener serves
 * all of them; the key goes to the DEEPEST layer, ties broken by most-recently
 * registered (two layers at one depth are siblings, and the later one is on top).
 */
const layers: Layer[] = [];

function dispatch(e: KeyboardEvent): void {
  if (e.key !== 'Escape') return;
  let top: Layer | undefined;
  for (const layer of layers) {
    if (!top || layer.depth >= top.depth) top = layer;
  }
  top?.handler.current?.();
}

function useLayer(depth: number, onEscape: (() => void) | null, registered: boolean): void {
  // Written in an effect, never during render: the handler is read at KEY time, long
  // after commit, so the ref only has to be current by then.
  const latest = useRef(onEscape);
  useEffect(() => {
    latest.current = onEscape;
  });

  useEffect(() => {
    if (!registered) return;
    // Deps are `[depth, registered]` only. Every call site passes an inline arrow for
    // `onEscape`, so depending on it would re-register — and therefore reorder — the
    // layer on every render of its parent.
    const entry: Layer = {depth, handler: latest};
    layers.push(entry);
    if (layers.length === 1) document.addEventListener('keydown', dispatch);

    return () => {
      const i = layers.lastIndexOf(entry);
      if (i !== -1) layers.splice(i, 1);
      if (layers.length === 0) document.removeEventListener('keydown', dispatch);
    };
  }, [depth, registered]);
}

/**
 * Call `onEscape` when Escape is pressed — but only for the DEEPEST layer on screen.
 *
 * Nesting used to be the caller's problem: a drawer holding a dialog had to gate its
 * own Escape off (`closeOnEscape={!dialogOpen}`) or both would close at once, and every
 * new nesting was a fresh chance to forget. Depth comes from `EscapeLayer`, which
 * `Modal` and `Drawer` render around their children — so a dialog opened from inside a
 * drawer outranks it BY CONSTRUCTION, whatever order their effects happen to run in.
 * (Effect order is the trap here: child effects run first, so "last registered" is the
 * outermost layer, not the innermost.)
 *
 * `enabled` means "this surface is on screen and dismissible". A layer that is on
 * screen but must NOT be dismissed — a modal mid-request — wants {@link useEscapeBlock}
 * instead, so the key is swallowed rather than falling through to whatever is beneath.
 *
 * @example
 * useEscapeKey(onClose, open && !busy);
 */
export function useEscapeKey(onEscape: () => void, enabled = true): void {
  useLayer(useEscapeDepth(), onEscape, enabled);
}

/**
 * Hold the Escape key at this depth without acting on it, while `active`.
 *
 * For a surface that is present but currently undismissable — `Modal` while an action
 * is in flight. Without it, Escape would fall past the busy modal to the drawer behind
 * it and dismiss THAT, which is the opposite of what `dismissible={false}` asks for.
 */
export function useEscapeBlock(active: boolean): void {
  useLayer(useEscapeDepth(), null, active);
}
