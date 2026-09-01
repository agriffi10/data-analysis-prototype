import {useEffect} from 'react';
import {useLocation, useNavigate} from 'react-router';
import {PageLayout} from '../../components/PageLayout';
import {usePageTitle} from '../../hooks/usePageTitle';
import {useIsMobile} from '../../lib/useBreakpoint';
import {HelpGuideCard} from './HelpGuideCard';
import {HelpSidebar} from './HelpSidebar';
import {HelpSectionChips} from './HelpSectionChips';
import {HELP_SECTIONS} from './helpContent';
import {resolveHelpHash} from './helpDeepLink';
import {useVisibleHelpSections} from './visibleSections';
import type {HelpSectionId} from './help.types';

/**
 * The Help & guides page: a section sidebar beside the active
 * section's guides as accordion cards. The URL hash addresses either a section
 * (`/help#query`) or a single guide (`/help#upload-files`), so both are shareable and
 * back/forward moves between them. Static content — no loading/error/network states.
 *
 * @example
 * <HelpPage />
 */
export function HelpPage() {
  usePageTitle('Help & guides');

  const {hash} = useLocation();
  const navigate = useNavigate();

  // A disabled feature's guides are neither listed nor reachable by anchor, and the panel
  // reads the same filtered set — so the two cannot disagree about what is visible.
  const sections = useVisibleHelpSections();

  const {sectionId: activeId, guideId} = resolveHelpHash(hash, sections.length ? sections : HELP_SECTIONS);
  const section = sections.find((s) => s.id === activeId) ?? sections[0] ?? HELP_SECTIONS[0];

  // Reset the content panel to the top when the section changes so a long
  // scroll position doesn't carry over.
  useEffect(() => {
    document.getElementById('main')?.scrollTo?.({top: 0});
  }, [activeId]);

  // ORDER IS LOAD-BEARING: this effect must stay below the reset above. Both run on a
  // hash-driven mount and the one declared second wins, so swapping them scrolls the guide
  // into view and then jumps back to the top. jsdom has no layout, so no test can see it.
  useEffect(() => {
    if (!guideId) return;
    document.getElementById(`help-guide-${guideId}`)?.scrollIntoView?.({block: 'start'});
  }, [activeId, guideId]);

  const selectSection = (id: HelpSectionId) => {
    if (id !== activeId) navigate(`#${id}`);
  };

  // Rail at ≥ tablet, horizontal chips on mobile — mount-gated so exactly one
  // section selector exists in the layout at a time.
  const isMobile = useIsMobile();

  return (
    <div className="flex min-h-0 flex-1">
      {!isMobile && (
        <HelpSidebar
          sections={sections}
          activeId={activeId}
          onSelect={selectSection}
        />
      )}
      <PageLayout
        title={section.label}
        subtitle={section.subtitle}
        contentClassName="max-w-[820px] gap-2.5">
        {isMobile && (
          <HelpSectionChips
            sections={sections}
            activeId={activeId}
            onSelect={selectSection}
          />
        )}
        {section.guides.length === 0 ? (
          <p className="py-12 text-center text-sm text-text-3">No guides in this section yet.</p>
        ) : (
          section.guides.map((guide, i) => (
            <div
              key={guide.id}
              id={`help-guide-${guide.id}`}>
              {/* The key carries the addressed guide so a hash change re-opens the card:
                  `defaultOpen` is read once into state and ignores a later prop change. */}
              <HelpGuideCard
                key={`${guide.id}:${guideId ?? ''}`}
                guide={guide}
                iconName={section.icon}
                defaultOpen={guideId ? guide.id === guideId : i === 0}
              />
            </div>
          ))
        )}
      </PageLayout>
    </div>
  );
}
