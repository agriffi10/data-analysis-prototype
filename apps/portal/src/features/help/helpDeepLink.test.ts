import {describe, expect, it} from 'vitest';
import {resolveHelpHash} from './helpDeepLink';
import {HELP_SECTIONS} from './helpContent';
import {visibleHelpSections} from './visibleSections';

const ALL_ON = visibleHelpSections(() => true);

describe('resolveHelpHash', () => {
  it('resolves a section hash to that section, with no guide', () => {
    expect(resolveHelpHash('#query', ALL_ON)).toEqual({sectionId: 'query', guideId: null});
    expect(resolveHelpHash('query', ALL_ON)).toEqual({sectionId: 'query', guideId: null});
  });

  it('resolves a guide hash to its OWNING section, not the first one', () => {
    // `delete-space` lives in Shared connections, which is not `HELP_SECTIONS[0]` — so a
    // resolver that only ever answered "the first section" passes the section cases above and
    // fails here.
    expect(resolveHelpHash('#delete-space', ALL_ON)).toEqual({
      sectionId: 'shared-connections',
      guideId: 'delete-space'
    });
  });

  it('falls back to the first visible section for a hash that is neither', () => {
    expect(resolveHelpHash('#does-not-exist', ALL_ON)).toEqual({sectionId: ALL_ON[0].id, guideId: null});
    expect(resolveHelpHash('', ALL_ON)).toEqual({sectionId: ALL_ON[0].id, guideId: null});
  });

  it('does not find a guide the given sections have already filtered out', () => {
    // The panel and the page both hand this function FLAG-FILTERED sections, so a hidden
    // guide is simply absent and its anchor takes the unrecognised-hash path — rather than
    // naming a card that was never rendered.
    const withoutDataQuality = visibleHelpSections((key) => key !== 'dataQuality');
    expect(resolveHelpHash('#check-data-quality', withoutDataQuality)).toEqual({
      sectionId: withoutDataQuality[0].id,
      guideId: null
    });
  });
});

describe('the help content this resolver assumes', () => {
  it('gives every guide an id unique across all sections and distinct from every section id', () => {
    // The lookup is by bare id with no section in hand: a duplicate would resolve to
    // whichever section is walked first, and a guide sharing a section's id would never
    // resolve as a guide at all.
    const guideIds = HELP_SECTIONS.flatMap((section) => section.guides.map((guide) => guide.id));
    const duplicates = guideIds.filter((id, i) => guideIds.indexOf(id) !== i);
    expect(duplicates).toEqual([]);

    const sectionIds = new Set<string>(HELP_SECTIONS.map((section) => section.id));
    expect(guideIds.filter((id) => sectionIds.has(id))).toEqual([]);
  });
});
