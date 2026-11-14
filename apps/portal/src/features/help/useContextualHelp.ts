import {useCallback, useMemo, useState} from 'react';
import {useLocation} from '../../lib/navigation';
import {HELP_SURFACES} from './helpSurfaces';
import {useVisibleHelpSections} from './visibleSections';
import type {HelpSectionId} from './help.types';

export type UseContextualHelpResult = {
  /** `null` on a route with no row, or whose section the flags hide — the control navigates to /help instead. */
  sectionId: HelpSectionId | null;
  open: boolean;
  openPanel: () => void;
  closePanel: () => void;
};

/**
 * Which help section belongs to the route the user is on, and whether its panel is up.
 *
 * A route the user cannot reach resolves to `null` without anything declaring it: its
 * section has already been filtered out of `visibleHelpSections`, so the control falls back
 * to `/help` rather than offering a panel for a feature the user does not have.
 *
 * @returns The resolved section, the open flag, and the two setters the control drives.
 *
 * @example
 * const {sectionId, open, openPanel, closePanel} = useContextualHelp();
 */
export function useContextualHelp(): UseContextualHelpResult {
  const {pathname} = useLocation();
  const sections = useVisibleHelpSections();
  const [open, setOpen] = useState(false);
  const [openedAt, setOpenedAt] = useState(pathname);

  const sectionId = useMemo(() => {
    const surface = HELP_SURFACES.find((candidate) => candidate.path === pathname);
    if (!surface) return null;
    return sections.some((section) => section.id === surface.sectionId) ? surface.sectionId : null;
  }, [pathname, sections]);

  // Closed on the pathname CHANGING, not on first paint. Two failures otherwise, both of
  // which pass a mount-only test: leave a route and come back and the panel is still up, and
  // pressing Back swaps a different section's content into a live modal. Adjusted during
  // render rather than from an effect, so the panel is already gone when the new route paints
  // — and because deriving `open` from the pathname alone cannot see a return to a pathname
  // the panel was opened on.
  if (openedAt !== pathname) {
    setOpenedAt(pathname);
    setOpen(false);
  } else if (open && sectionId === null) {
    // A section that vanishes under an open panel closes it for GOOD. Without this the flag
    // only hides it: publish the feature back inside the same session and the panel returns,
    // with `aria-expanded="true"` and no user action.
    setOpen(false);
  }

  const openPanel = useCallback(() => setOpen(true), []);
  const closePanel = useCallback(() => setOpen(false), []);

  return {sectionId, open, openPanel, closePanel};
}
