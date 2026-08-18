import {useEffect, useMemo} from 'react';
import {useLocation, useNavigate} from 'react-router';
import {PageLayout} from '../../components/PageLayout';
import {usePageTitle} from '../../hooks/usePageTitle';
import {useIsMobile} from '../../lib/useBreakpoint';
import {HelpGuideCard} from './HelpGuideCard';
import {HelpSidebar} from './HelpSidebar';
import {HelpSectionChips} from './HelpSectionChips';
import {HELP_SECTIONS} from './helpContent';
import {hiddenHelpIds, useFeature} from '../feature-flags';
import type {HelpSectionId} from './help.types';

function sectionFromHash(hash: string, sections: typeof HELP_SECTIONS): HelpSectionId {
  const id = hash.replace(/^#/, '');
  const match = sections.find((s) => s.id === id);
  // Falls back to the first VISIBLE section, so `/help#query` with Query off lands somewhere
  // real instead of on a section the list no longer offers (FR-006: unreachable by anchor).
  return match ? match.id : sections[0].id;
}

/**
 * The Help & guides page: a section sidebar beside the active
 * section's guides as accordion cards. The active section lives in the URL hash
 * (`/help#query`) so it's shareable and back/forward moves between sections
 * (FR-002/003/004). Static content — no loading/error/network states.
 *
 * @example
 * <HelpPage />
 */
export function HelpPage() {
  usePageTitle('Help & guides');

  const {hash} = useLocation();
  const navigate = useNavigate();

  // a disabled feature's guides are neither listed nor reachable. The
  // guide→flag mapping lives ONLY in the registry (`hiddenHelpIds`) — `helpContent.ts` knows
  // nothing about flags, so a guide cannot end up gated in the list and ungated by anchor.
  //
  // Sections AND guides, not sections alone: the two data-quality guides live inside the
  // Files section, so a section-level filter would leave them listed with Data Quality off.
  const files = useFeature('files');
  const query = useFeature('query');
  const sharedWorkspaces = useFeature('sharedWorkspaces');
  const dataQuality = useFeature('dataQuality');
  // The Data Explorer's section carries five guides, so this flag now
  // hides content like the other four. The map below stays TOTAL over `FeatureFlagKey`
  // regardless: a partial one type-errors here rather than silently answering `undefined`
  // (falsy, so every guide) the day a new flag's first guide row is registered.
  const dataExplorer = useFeature('dataExplorer');
  const sections = useMemo(() => {
    const hidden = hiddenHelpIds((key) => ({files, query, sharedWorkspaces, dataQuality, dataExplorer})[key]);
    return HELP_SECTIONS.filter((s) => !hidden.has(s.id)).map((s) => ({
      ...s,
      guides: s.guides.filter((g) => !hidden.has(g.id))
    }));
  }, [files, query, sharedWorkspaces, dataQuality, dataExplorer]);

  const activeId = sectionFromHash(hash, sections.length ? sections : HELP_SECTIONS);
  const section = sections.find((s) => s.id === activeId) ?? sections[0] ?? HELP_SECTIONS[0];

  // Reset the content panel to the top when the section changes so a long
  // scroll position doesn't carry over (FR-003).
  useEffect(() => {
    document.getElementById('main')?.scrollTo?.({top: 0});
  }, [activeId]);

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
            <HelpGuideCard
              key={guide.id}
              guide={guide}
              iconName={section.icon}
              defaultOpen={i === 0}
            />
          ))
        )}
      </PageLayout>
    </div>
  );
}
