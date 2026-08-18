/**
 * The body chrome `FormDialog` renders, for the four dialogs that cannot use it.
 *
 * SPEC-186 FR-010 pattern C. Every one of them hands its footer to `DestinationPicker`, which
 * owns the confirm's label, its enabled-ness and the prefix it acts on, and is shared between
 * them — so `FormDialog`, which renders its own Cancel/submit pair, would give each dialog two
 * footers. Hoisting the picker's state into four parents to reach the shared chrome costs more
 * than the chrome saves, and `FormDialog`'s Enter-to-submit contract (
 * AC8) has no meaning where the submitting control belongs to a child.
 *
 * "Cannot" is a legitimate answer that has to be written down, which is what this file is. What
 * it does NOT excuse is four copies of the class strings, so those live here.
 */

/** The panel: `Modal`'s width plus the body padding `FormDialog` would have supplied. */
export const DIALOG_PANEL = 'flex max-w-lg flex-col px-5 pb-4 pt-5';

/** The dialog's `<h2>`, matching `FormDialog`'s title exactly. */
export const DIALOG_TITLE = 'text-md font-semibold text-text';
