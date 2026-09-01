/**
 * The class strings shared by every form field and section heading, in one place.
 *
 * `Input` owned the label and hint strings, but five features
 * re-implemented them rather than using it — and they could not use it, because a `<legend>` or
 * a `<select>`'s label is not an `<input>`. Exporting the strings is what actually gives them
 * one owner. Pattern E was worse: three competing strings for one idea across eleven sites,
 * already three-way drifted with nobody owning any of them.
 */

/** A field's label, above the control. `Input` renders this for you; a `<legend>` cannot. */
export const FIELD_LABEL = 'mb-1.5 block text-sm font-medium text-text';

/** A field's hint, below the control. Not the error — `Input` owns that, and it is `text-danger`. */
export const FIELD_HINT = 'mt-1.5 text-xs text-text-3';

/**
 * A small uppercase caption over a group, a rail section or a table header.
 *
 * The majority variant of the three that existed. The other two — `font-medium text-text-2` and
 * `tracking-[.04em]` — are folded into this one, which makes seven captions very slightly
 * bolder, dimmer or more tightly tracked than before. That is the deliberate visual change in
 * this consolidation, on the byte-formatter precedent: two spellings of one idea on two screens
 * is the defect, not the fix.
 */
export const SECTION_CAPTION = 'text-xs font-semibold uppercase tracking-wide text-text-3';

/**
 * The chrome for a bare `<select>`.
 *
 * There is still no `Select` primitive in `components/`, so this is the same "one string until a
 * primitive exists" arrangement the Data Explorer had — moved down a layer at its first consumer
 * outside that feature, because a second copy is how two surfaces come to disagree about a focus
 * ring, and a class string owned by one feature is not somewhere another feature may reach.
 */
export const SELECT_CLASS =
  'h-9 rounded-md border border-border bg-surface px-2 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent';
