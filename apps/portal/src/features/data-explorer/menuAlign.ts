import {MENU_MIN_WIDTH_PX} from '../../components/Menu';

/** The attribute that marks the grid's own scroll box, which a column menu must not open past. */
export const GRID_SCROLL_BOX_ATTRIBUTE = 'data-grid-scroll-box';

/**
 * Which way a column header's menu should open so it stays inside the grid's scroll box.
 *
 * Measured when the menu opens rather than fixed per column: a menu opening rightward from one
 * of the last columns ran past the box's edge and was clipped, and which columns are "last"
 * changes with widths, pinning, hiding and the panels beside the grid.
 *
 * @param trigger - The menu button's rectangle.
 * @param box - The grid scroll box's rectangle, or undefined when there is none to measure.
 * @returns `'right'` (open leftward from the button's right edge) when rightward would overflow.
 *
 * @example
 * menuAlignFor(button.getBoundingClientRect(), box?.getBoundingClientRect()); // 'left' | 'right'
 */
export function menuAlignFor(trigger: DOMRect, box: DOMRect | undefined): 'left' | 'right' {
  if (!box || box.width === 0) return 'left';
  return trigger.left + MENU_MIN_WIDTH_PX > box.right ? 'right' : 'left';
}
