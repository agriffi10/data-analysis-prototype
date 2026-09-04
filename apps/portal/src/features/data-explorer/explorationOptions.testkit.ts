import {screen, within} from '@testing-library/react';
import type {UserEvent} from '@testing-library/user-event';

/**
 * Reach one of the Data Explorer's options-menu items.
 *
 * Every action moved off the toolbar and behind an **Options** menu — first the nine that do
 * not change which rows are on screen, then, on user feedback asking for a shorter bar, the
 * three that do. Roughly a hundred assertions reached them as toolbar buttons, and rewriting
 * each into "open the menu, then click the item" would have put the menu's shape in a hundred
 * places — so the next change to it would be the same sweep again. This is that shape, once,
 * and the second move cost only the call sites rather than the assertions.
 *
 * A helper rather than a query: the item is not in the document at all until the menu opens, so
 * there is no selector that finds it from a closed toolbar.
 */

/**
 * Opens the Options menu and returns the `role="menu"` popover.
 *
 * Safe to call when the menu is already open — the trigger reports its own state, so an
 * already-open menu is returned rather than toggled shut, which is what a caller reaching for a
 * second item wants.
 *
 * @param user - The `userEvent` instance the test is driving with.
 * @returns The open menu element.
 */
export async function openExplorationOptions(user: UserEvent): Promise<HTMLElement> {
  const trigger = await screen.findByRole('button', {name: 'Options'});
  if (trigger.getAttribute('aria-expanded') !== 'true') await user.click(trigger);
  return screen.getByRole('menu', {name: 'Exploration options'});
}

/**
 * Opens the Options menu and clicks one item by its accessible name.
 *
 * @param user - The `userEvent` instance the test is driving with.
 * @param label - The item's accessible name, e.g. `Grouping` or `Hide Calc`.
 * @returns Nothing, once the click has been dispatched.
 */
export async function chooseExplorationOption(user: UserEvent, label: string | RegExp): Promise<void> {
  const menu = await openExplorationOptions(user);
  await user.click(within(menu).getByRole('menuitem', {name: label}));
}

/**
 * The item's element, with the menu left open — for asserting on a refusal rather than acting.
 *
 * @param user - The `userEvent` instance the test is driving with.
 * @param label - The item's accessible name.
 * @returns The `menuitem` element.
 */
export async function explorationOption(user: UserEvent, label: string | RegExp): Promise<HTMLElement> {
  const menu = await openExplorationOptions(user);
  return within(menu).getByRole('menuitem', {name: label});
}
