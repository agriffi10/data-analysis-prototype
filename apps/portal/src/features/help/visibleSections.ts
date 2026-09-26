import {useMemo} from 'react';
import {hiddenHelpIds, useFeature} from '../feature-flags';
import type {FeatureFlagKey} from '../feature-flags';
import {HELP_SECTIONS} from './helpContent';
import type {HelpSection} from './help.types';

/**
 * The authored sections with everything the flags hide removed.
 *
 * Sections AND the guides inside them, not sections alone: the two data-quality guides live
 * inside the Files section, so a section-level filter would leave them listed with Data
 * Quality off. The guide→flag mapping is read from the registry (`hiddenHelpIds`) and lives
 * nowhere else — `helpContent.ts` knows nothing about flags.
 *
 * Pure, so the panel and the full page cannot drift into filtering differently. Callers
 * inside a component want {@link useVisibleHelpSections}.
 *
 * @param isEnabled - Answers whether one flag is on.
 * @returns The sections a user with those flags may see, in authored order.
 *
 * @example
 * const sections = visibleHelpSections((key) => flags[key]);
 */
export function visibleHelpSections(isEnabled: (key: FeatureFlagKey) => boolean): HelpSection[] {
  const hidden = hiddenHelpIds(isEnabled);
  return HELP_SECTIONS.filter((section) => !hidden.has(section.id)).map((section) => ({
    ...section,
    guides: section.guides.filter((guide) => !hidden.has(guide.id))
  }));
}

/**
 * {@link visibleHelpSections} against the live flags — the one surface both the Help page and
 * the contextual panel read.
 *
 * Eight single-question `useFeature` calls rather than the whole-set hook, which is for the few
 * places that cannot ask one question. They share one cached answer, so the extra calls cost
 * nothing.
 *
 * @returns The sections this user may see; referentially stable while the flags are.
 *
 * @example
 * const sections = useVisibleHelpSections();
 */
export function useVisibleHelpSections(): HelpSection[] {
  const files = useFeature('files');
  const query = useFeature('query');
  const sharedWorkspaces = useFeature('sharedWorkspaces');
  const dataQuality = useFeature('dataQuality');
  const dataExplorer = useFeature('dataExplorer');
  const asyncFileOperations = useFeature('asyncFileOperations');
  const resultsConversion = useFeature('resultsConversion');
  const archive = useFeature('archive');

  return useMemo(
    () =>
      // The map stays TOTAL over `FeatureFlagKey`: a partial one type-errors here rather than
      // silently answering `undefined` — falsy, so every guide — the day a new flag's first
      // guide row is registered.
      visibleHelpSections(
        (key) =>
          ({
            files,
            query,
            sharedWorkspaces,
            dataQuality,
            dataExplorer,
            asyncFileOperations,
            resultsConversion,
            archive
          })[key]
      ),
    [files, query, sharedWorkspaces, dataQuality, dataExplorer, asyncFileOperations, resultsConversion, archive]
  );
}
