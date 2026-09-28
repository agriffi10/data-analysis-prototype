/**
 * The longest name an archive may carry, in code points after normalisation.
 *
 * The plane states the same number (`arcommon.config.ARCHIVE_NAME_MAX_CHARS`) and a Python test
 * reads this one back out of this file.
 */
export const ARCHIVE_NAME_MAX_CHARS = 100;

/**
 * The code points a name may not contain, as inclusive ranges, checked on the raw value.
 *
 * Control characters and line separators would start a new line in the archive's receipt; the
 * bidirectional controls would let a name shown to the other members of a shared space read as
 * something it is not; and a lone surrogate cannot be encoded at all. Mirrored from
 * `arcommon.config.ARCHIVE_NAME_REFUSED_RANGES` and held equal to it by a Python test.
 */
export const ARCHIVE_NAME_REFUSED_RANGES: readonly (readonly [number, number])[] = [
  [0x0000, 0x001f],
  [0x007f, 0x009f],
  [0x061c, 0x061c],
  [0x200e, 0x200f],
  [0x2028, 0x202e],
  [0x2066, 0x2069],
  [0xd800, 0xdfff]
];

/**
 * Collapse every run of spaces to one and trim spaces from both ends.
 *
 * **Only U+0020 counts as a space** — never `.trim()` or `\s`, which strip a no-break space and
 * an ideographic space and would disagree with the plane's rule, which the shared corpus in
 * `lambdas/archive-common/archive_name_corpus.json` holds both sides to.
 *
 * @param raw - The name as typed, already known to hold no refused character.
 * @returns The normalised name; an empty string means no name.
 */
export function normalizeArchiveName(raw: string): string {
  return raw
    .split(' ')
    .filter((part) => part !== '')
    .join(' ');
}

/**
 * Why a raw name cannot be used, or null when it can.
 *
 * Iterates by CODE POINT (`for…of`), so the two halves of a valid surrogate pair are one
 * character and only a lone surrogate meets the surrogate range — the same reading Python gives
 * a string.
 *
 * @param raw - The name exactly as the user typed or pasted it.
 * @returns A sentence for the field's error, or null.
 */
export function archiveNameRefusal(raw: string): string | null {
  for (const character of raw) {
    const point = character.codePointAt(0) ?? 0;
    if (ARCHIVE_NAME_REFUSED_RANGES.some(([low, high]) => point >= low && point <= high)) {
      return 'An archive name can’t contain tabs, line breaks or other control characters.';
    }
  }
  if ([...normalizeArchiveName(raw)].length > ARCHIVE_NAME_MAX_CHARS) {
    return `An archive name can be at most ${ARCHIVE_NAME_MAX_CHARS} characters.`;
  }
  return null;
}
