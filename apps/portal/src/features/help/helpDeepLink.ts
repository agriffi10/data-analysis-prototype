import type {HelpSection, HelpSectionId} from './help.types';

/** What a `/help#…` hash addresses: always a section, and sometimes one guide within it. */
export type HelpHashTarget = {
  sectionId: HelpSectionId;
  /** The guide to expand and scroll to, or `null` for a section-level hash. */
  guideId: string | null;
};

/**
 * Resolve a `/help` URL hash to the section to show and the guide to open.
 *
 * Sections are matched first, so `#query` keeps meaning exactly what it always has. A guide
 * id resolves to its owning section — which is what makes a single guide linkable — and the
 * lookup is by bare id. The ordering is not what keeps the two apart, though: what does is
 * that no guide id equals a section id, asserted over the shipped content. Swap the two
 * lookups and today's content behaves identically.
 *
 * `sections` must already be flag-filtered: a guide the flags hide is then simply not found,
 * so an anchor into it falls back rather than promising to expand a card nobody rendered.
 *
 * @param hash - The location hash, with or without its leading `#`.
 * @param sections - The visible sections; must not be empty.
 * @returns The section to select, and the guide to expand if the hash named one.
 *
 * @example
 * const {sectionId, guideId} = resolveHelpHash('#upload-files', sections);
 */
export function resolveHelpHash(hash: string, sections: readonly HelpSection[]): HelpHashTarget {
  const id = hash.replace(/^#/, '');

  const section = sections.find((candidate) => candidate.id === id);
  if (section) return {sectionId: section.id, guideId: null};

  const owner = sections.find((candidate) => candidate.guides.some((guide) => guide.id === id));
  if (owner) return {sectionId: owner.id, guideId: id};

  return {sectionId: sections[0].id, guideId: null};
}
