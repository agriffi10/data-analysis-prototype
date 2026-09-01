import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import type {HTMLAttributes, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent} from 'react';
import {
  DEFAULT_EDITOR_FRACTION,
  EDITOR_SPLIT_DIVIDER_HEIGHT,
  EDITOR_SPLIT_KEY_STEP,
  MAX_EDITOR_FRACTION,
  MIN_EDITOR_FRACTION,
  MIN_EDITOR_HEIGHT,
  MIN_RESULTS_HEIGHT,
  QUERY_EDITOR_SPLIT_STORAGE_PREFIX
} from './query.constants';

export type UseEditorSplitResult = {
  /** Editor share of the column, clamped to the column's bounds, in (0, 1). */
  fraction: number;
  /** The editor pane's derived pixel height, clamped to both floors. */
  editorHeight: number;
  /** Role, ARIA value and handlers for the divider element. */
  dividerProps: HTMLAttributes<HTMLDivElement>;
  /** Sets the fraction directly (keyboard, double-click reset), clamped and persisted. */
  setFraction: (next: number) => void;
  /** Moves the split one keyboard step: -1 shrinks the editor, 1 grows it. */
  step: (direction: -1 | 1) => void;
};

function storageKey(username: string | null): string | null {
  if (!username) return null;
  return `${QUERY_EDITOR_SPLIT_STORAGE_PREFIX}${username}`;
}

function isFraction(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 && value < 1;
}

// All storage access is wrapped so a disabled/quota-exceeded sessionStorage
// degrades to "not persisted" rather than breaking the workspace.
function readStoredFraction(username: string | null): number | null {
  const key = storageKey(username);
  if (!key) return null;
  try {
    const raw = sessionStorage.getItem(key);
    if (raw === null) return null;
    const parsed = Number(raw);
    return isFraction(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function writeStoredFraction(username: string | null, fraction: number): void {
  const key = storageKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, String(fraction));
  } catch {
    // Storage unavailable — the split still applies for this render tree.
  }
}

// A column that cannot hold the divider has not been measured yet (the first
// render of every mount, and any environment without a layout engine). Dividing
// by it yields Infinity, which is not a number an `aria-valuemin` may carry.
function isMeasured(containerHeight: number): boolean {
  return containerHeight > EDITOR_SPLIT_DIVIDER_HEIGHT;
}

/**
 * The fractions the divider may take within a column of `containerHeight`.
 *
 * The pixel floors are the whole constraint on a measured column — mixing the
 * hard fraction bounds in would make these bounds and `clampEditorHeight`
 * describe different splits, so those apply only before the measurement. On a
 * column too short for both floors `max` collapses onto `min` — the editor floor
 * wins — and `min` itself stops at the room the divider leaves, so no pane is
 * ever asked for a negative height.
 */
export function splitBounds(containerHeight: number): {min: number; max: number} {
  if (!isMeasured(containerHeight)) return {min: MIN_EDITOR_FRACTION, max: MAX_EDITOR_FRACTION};
  const room = (containerHeight - EDITOR_SPLIT_DIVIDER_HEIGHT) / containerHeight;
  const min = Math.min(room, MIN_EDITOR_HEIGHT / containerHeight);
  const max = (containerHeight - MIN_RESULTS_HEIGHT - EDITOR_SPLIT_DIVIDER_HEIGHT) / containerHeight;
  return {min, max: Math.max(min, max)};
}

/**
 * Clamps `fraction` into the bounds of a column of `containerHeight`.
 *
 * @example
 * clampFraction(0.9, 400); // 0.64 — the results floor and the divider cap it
 */
export function clampFraction(fraction: number, containerHeight: number): number {
  const {min, max} = splitBounds(containerHeight);
  return Math.min(Math.max(fraction, min), max);
}

/**
 * The editor pane's pixel height for a fraction within the available
 * editor+results column.
 *
 * The proportion is capped so the results region keeps `MIN_RESULTS_HEIGHT`
 * beneath the divider, then floored so the editor keeps `MIN_EDITOR_HEIGHT` — on
 * a column too short for both floors the editor floor wins. It never wins past
 * the column itself, so on one shorter than the floor the editor simply takes
 * what is left and no pane is given a negative height.
 *
 * @example
 * clampEditorHeight(0.5, 1000); // 500
 */
export function clampEditorHeight(fraction: number, containerHeight: number): number {
  if (!isMeasured(containerHeight)) return MIN_EDITOR_HEIGHT;
  const capped = Math.min(
    containerHeight * fraction,
    containerHeight - MIN_RESULTS_HEIGHT - EDITOR_SPLIT_DIVIDER_HEIGHT
  );
  return Math.round(Math.min(Math.max(MIN_EDITOR_HEIGHT, capped), containerHeight - EDITOR_SPLIT_DIVIDER_HEIGHT));
}

/**
 * Owns the editor/results split: the fraction (per-user `sessionStorage`
 * persistence, degrade-safe, default an even split), the editor pane's derived
 * pixel height within `containerHeight` (the measured editor+results column),
 * and the divider's role, ARIA value and pointer/keyboard/double-click
 * handlers.
 *
 * A stored fraction is re-clamped on read rather than rewritten, so a window
 * that shrinks and grows again returns to the split the user chose. The pointer
 * drag writes storage once, on release; the keyboard and the reset write
 * immediately.
 *
 * @example
 * const split = useEditorSplit(username, columnHeight);
 * <div style={{height: split.editorHeight}}>…</div>
 * <EditorSplitDivider {...split.dividerProps} />
 */
export function useEditorSplit(username: string | null, containerHeight: number): UseEditorSplitResult {
  const [stored, setStored] = useState<number>(() => readStoredFraction(username) ?? DEFAULT_EDITOR_FRACTION);

  const fraction = clampFraction(stored, containerHeight);
  const editorHeight = useMemo(() => clampEditorHeight(fraction, containerHeight), [fraction, containerHeight]);

  const setFraction = useCallback(
    (next: number) => {
      const clamped = clampFraction(next, containerHeight);
      setStored(clamped);
      writeStoredFraction(username, clamped);
    },
    [containerHeight, username]
  );

  // The drag's window listeners are self-contained in the closure below so the
  // move handler always sees the gesture origin, and the up handler can unbind
  // both without a forward reference. The last fraction the move produced is
  // held in a ref because that — not the pre-drag value the closure captured —
  // is what release has to persist.
  const draggedTo = useRef(fraction);
  // Unbinds the gesture in flight, if any. Held in a ref so unmounting mid-drag
  // can drop the listeners: a release arriving after the tree is gone would
  // otherwise persist a split the user was still choosing.
  const endDrag = useRef<(() => void) | null>(null);
  useEffect(() => () => endDrag.current?.(), []);

  const onPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!isMeasured(containerHeight)) return;
      // Cancelling the gesture is what stops a text selection, and it also
      // suppresses the focus that a mousedown would have given — so focus the
      // divider by hand, or the arrow keys are unreachable for a pointer user.
      e.preventDefault();
      e.currentTarget.focus();
      const startY = e.clientY;
      const startHeight = editorHeight;
      draggedTo.current = fraction;

      const onMove = (move: PointerEvent) => {
        const next = clampFraction((startHeight + (move.clientY - startY)) / containerHeight, containerHeight);
        draggedTo.current = next;
        setStored(next);
      };
      const unbind = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        window.removeEventListener('pointercancel', onUp);
        endDrag.current = null;
      };
      const onUp = () => {
        unbind();
        writeStoredFraction(username, draggedTo.current);
      };
      endDrag.current = unbind;
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
      // A gesture the browser or OS takes over fires this INSTEAD of pointerup,
      // and an unbound move handler then resizes on every pointer move with no
      // button held.
    },
    [containerHeight, editorHeight, fraction, username]
  );

  // One definition of a step, shared by the arrow keys and the step buttons, so
  // the pointer path and the keyboard path cannot drift apart.
  const step = useCallback(
    (direction: -1 | 1) => setFraction(fraction + direction * EDITOR_SPLIT_KEY_STEP),
    [fraction, setFraction]
  );

  const onKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      const {min, max} = splitBounds(containerHeight);
      if (e.key === 'ArrowUp') step(-1);
      else if (e.key === 'ArrowDown') step(1);
      else if (e.key === 'Home') setFraction(min);
      else if (e.key === 'End') setFraction(max);
      else return;
      e.preventDefault();
    },
    [containerHeight, setFraction, step]
  );

  const onDoubleClick = useCallback(() => setFraction(DEFAULT_EDITOR_FRACTION), [setFraction]);

  const {min, max} = splitBounds(containerHeight);
  const percent = Math.round(fraction * 100);
  const dividerProps: HTMLAttributes<HTMLDivElement> = {
    role: 'separator',
    tabIndex: 0,
    'aria-orientation': 'horizontal',
    'aria-label': 'Resize the editor and results',
    // A FOCUSABLE separator is a widget, not a divider, so ARIA requires a
    // value. The percentage of the column is what the arrow keys move.
    'aria-valuenow': percent,
    'aria-valuemin': Math.round(min * 100),
    'aria-valuemax': Math.round(max * 100),
    'aria-valuetext': `Editor ${percent}% of the column`,
    onPointerDown,
    onKeyDown,
    onDoubleClick
  };

  return {fraction, editorHeight, dividerProps, setFraction, step};
}
