/** The list's preferred height — 8 options plus its own padding, and its cap. */
export const MAX_LIST_HEIGHT = 240;

/**
 * Below this the list is not worth flipping FOR: two options and a hint of a third, which is
 * enough to tell the user the list is scrollable. A smaller box would flip on a few pixels.
 */
export const MIN_LIST_HEIGHT = 96;

/** The `mt-1`/`mb-1` gap between the field and the list, in px. */
export const LIST_GAP = 4;

export type PlacementInput = {
  /** The combobox field's own box, in viewport coordinates. */
  fieldTop: number;
  fieldBottom: number;
  /** The box that CLIPS the list — the dialog panel, or the viewport on a page. */
  clipTop: number;
  clipBottom: number;
};

export type Placement = {
  /** Render above the field rather than below it. */
  dropUp: boolean;
  /** The list's `max-height`, in px. */
  maxHeight: number;
};

/**
 * Where the suggestion list goes and how tall it may be.
 *
 * Kept pure and separate from the component because the property that matters
 * is NUMERIC — the list's far edge must stay inside the clipping box — and jsdom has no layout
 * engine, so a DOM test could only assert that the code ran. Here the arithmetic can be checked
 * against the cases that actually occurred: the 1400x900 Add-members dialog, where the list ran
 * 97px past the panel's bottom edge because the old rule measured `window.innerHeight` instead.
 *
 * The flip is CONSERVATIVE: it goes up only when below is genuinely cramped AND above is
 * roomier, because below is where the reading order already expects the list.
 *
 * @param input - The field's box and the box that clips it.
 * @returns The side to render on and the height cap for it.
 */
export function listPlacement({fieldTop, fieldBottom, clipTop, clipBottom}: PlacementInput): Placement {
  const below = clipBottom - fieldBottom - LIST_GAP;
  const above = fieldTop - clipTop - LIST_GAP;
  const dropUp = below < MIN_LIST_HEIGHT && above > below;
  const available = dropUp ? above : below;
  return {dropUp, maxHeight: Math.max(MIN_LIST_HEIGHT, Math.min(MAX_LIST_HEIGHT, available))};
}
