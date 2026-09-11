/**
 * The class strings for a bulk action on the Files selection toolbar — its glyph and its word.
 *
 * One owner, because the toolbar's actions live in two features: the file browser's own, and
 * Archive beside them. A row a user reads as one set of controls must not drift into two.
 *
 * The button's classes stay on each tag rather than here: they carry its height, and the
 * target-size sweep reads a size only where it is written on the tag.
 */

/**
 * The glyph: the whole control on mobile, gone at `tablet`, beside the word at `desktop`.
 *
 * Between the two the words only fit once the glyphs and some spacing give their room back —
 * with both drawn, the words wrapped onto two lines and Delete spilled out of the bar.
 */
export const TOOLBAR_ACTION_ICON = 'h-[15px] w-[15px] tablet:hidden desktop:block';

/**
 * The word: CSS-hidden on mobile, and never wrapped. Every action keeps an `aria-label` that
 * names it, so nothing is lost to a screen reader at any width.
 */
export const TOOLBAR_ACTION_LABEL = 'hidden whitespace-nowrap tablet:inline';
