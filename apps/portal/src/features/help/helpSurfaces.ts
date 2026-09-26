import type {HelpSectionId} from './help.types';

/**
 * One route that offers contextual help. `path` is the route the header control resolves
 * against; `sectionId` is the section the panel opens at. Route → section only: the
 * guide→flag mapping stays in `gatedSurfaces.ts`, which this module deliberately does not
 * import — a second home for it is the fork that registry exists to prevent.
 */
export type HelpSurface = {
  path: string;
  sectionId: HelpSectionId;
};

/**
 * Every route whose help control opens the panel instead of navigating to `/help`.
 *
 * A path absent from this list is not an error: its control stays the link it has always
 * been, which is what keeps `/help` itself, the landing page and any unmatched path working.
 * Matching is on the whole pathname, so a parameterised route — the data-quality report view
 * — falls back to navigation until someone adds it deliberately.
 *
 * Nothing here mentions a feature flag. A route the user cannot reach has no panel because
 * its section is filtered out of `visibleHelpSections`, not because a row says so.
 */
export const HELP_SURFACES: readonly HelpSurface[] = [
  {path: '/files', sectionId: 'files'},
  {path: '/query', sectionId: 'query'},
  {path: '/connections', sectionId: 'shared-connections'},
  // Its guides were authored inside the Files section, so this panel is headed "Files" and
  // holds the Files guides that are not about data quality too. The alternative is a section
  // of its own, which is content work; if the guides are ever regrouped, this row moves with
  // them.
  //
  // It is also the one row whose panel survives its own feature being off — there is no
  // data-quality SECTION to filter out, so this opens over the unavailable page. Benign: the
  // data-quality guides are hidden with the flag, and what is left is Files content the user
  // is entitled to either way.
  {path: '/data-quality', sectionId: 'files'},
  {path: '/explore', sectionId: 'data-explorer'},
  {path: '/notifications', sectionId: 'notifications'}
];
