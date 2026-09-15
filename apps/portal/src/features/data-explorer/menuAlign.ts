import {MENU_MIN_WIDTH_PX} from '../../components/Menu';

/** The attribute that marks the grid's own scroll box, which a column menu must not open past. */
export const GRID_SCROLL_BOX_ATTRIBUTE = 'data-grid-scroll-box';

/**
 * The x of a scroll box's content edge: its right side less the scrollbar gutter it reserves,
 * which clips what reaches into it. Undefined for a box with no measured width (nothing laid out).
 *
 * @param box - The grid's scroll box element.
 * @returns The viewport x a menu must not pass, or undefined.
 */
export function contentRightOf(box: Element | null): number | undefined {
  if (!box || box.clientWidth === 0) return undefined;
  return box.getBoundingClientRect().left + box.clientLeft + box.clientWidth;
}

/**
 * Which way a column header's menu should open so it stays inside the grid's scroll box.
 *
 * Measured when the menu opens rather than fixed per column: a menu opening rightward from one
 * of the last columns ran past the box's edge and was clipped, and which columns are "last"
 * changes with widths, pinning, hiding and the panels beside the grid.
 *
 * @param triggerLeft - The menu button's left edge, in viewport px.
 * @param contentRight - The scroll box's content edge from {@link contentRightOf}, or undefined.
 * @returns `'right'` (open leftward from the button's right edge) when rightward would overflow.
 *
 * @example
 * menuAlignFor(button.getBoundingClientRect().left, contentRightOf(box)); // 'left' | 'right'
 */
export function menuAlignFor(triggerLeft: number, contentRight: number | undefined): 'left' | 'right' {
  if (contentRight === undefined) return 'left';
  return triggerLeft + MENU_MIN_WIDTH_PX > contentRight ? 'right' : 'left';
}
