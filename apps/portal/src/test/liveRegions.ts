/**
 * The text every polite live region under `root` holds right now — what a screen reader has been
 * handed to speak without a focus move — trimmed, with empty regions left out.
 *
 * A field's spoken error sits in a roleless `aria-live` region, which no role query reaches, and
 * its text repeats the visible message, so a text query would find both.
 *
 * @param root - Where to look; the whole document by default.
 * @returns The non-empty region texts, in document order.
 */
export function politeAnnouncements(root: ParentNode = document.body): string[] {
  return Array.from(root.querySelectorAll('[aria-live="polite"]'), (node) => (node.textContent ?? '').trim()).filter(
    (text) => text !== ''
  );
}
