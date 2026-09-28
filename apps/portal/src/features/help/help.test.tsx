import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {Link, useLocation} from 'react-router';
import {HelpGuideCard} from './HelpGuideCard';
import {HelpPage} from './HelpPage';
import {HELP_SECTIONS} from './helpContent';
import {visibleHelpSections} from './visibleSections';
import {COMPONENT_AXE_OPTIONS, ROUTE_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {TestProviders, createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../feature-flags';
import type {FeatureFlags} from '../feature-flags';
import {configValue} from '../../lib/runtimeConfig';
import {HelpLink} from './HelpLink';
import {HelpSectionChips} from './HelpSectionChips';
import {HelpSidebar} from './HelpSidebar';
import {MAX_POLL_DURATION_MS} from '../catalog/catalog.constants';
import type {HelpGuide, HelpSection} from './help.types';

// ─── from HelpGuideCard.test.tsx ───
describe('HelpGuideCard', () => {
  const guide: HelpGuide = {
    id: 'upload-files',
    title: 'Upload files',
    subtitle: 'Add files from your computer.',
    steps: ['Open the <b>Files</b> tab.', 'Click <b>Upload</b>.'],
    callout: {kind: 'warning', text: 'Use <b>Cancel</b> to back out.'}
  };

  describe('HelpGuideCard (SPEC-074 FR-004)', () => {
    it('renders a collapsed card by default — title/subtitle visible, steps hidden', () => {
      render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
        />
      );
      const header = screen.getByRole('button', {name: /Upload files/});
      expect(header).toHaveAttribute('aria-expanded', 'false');
      expect(screen.getByText('Add files from your computer.')).toBeInTheDocument();
      expect(screen.queryByRole('list')).not.toBeInTheDocument();
    });

    it('toggles open on click, revealing numbered steps and the callout', () => {
      render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
        />
      );
      const header = screen.getByRole('button', {name: /Upload files/});
      fireEvent.click(header);
      expect(header).toHaveAttribute('aria-expanded', 'true');
      expect(header).toHaveAttribute('aria-controls');
      const steps = screen.getByRole('list');
      expect(steps).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(2);
      // Inline <b> is parsed to <strong>, not rendered as literal markup.
      expect(screen.getByText('Files')).toBeInTheDocument();
      expect(screen.queryByText(/<b>/)).not.toBeInTheDocument();
      // Warning callout prefix present.
      expect(screen.getByText(/Careful\./)).toBeInTheDocument();
      // Callout text is parsed too — <b> becomes <strong>, never literal markup.
      const cancel = screen.getByText('Cancel');
      expect(cancel.tagName).toBe('STRONG');
      expect(screen.queryByText(/<b>Cancel<\/b>/)).not.toBeInTheDocument();
    });

    it('honors defaultOpen', () => {
      render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
          defaultOpen
        />
      );
      expect(screen.getByRole('button', {name: /Upload files/})).toHaveAttribute('aria-expanded', 'true');
    });

    // ── the panel stays readable with several cards open (a UX report) ──

    // THE SQUISH. The drawer body is a scrolling flex column, and a flex item shrinks before
    // its container scrolls — this card's own `overflow-hidden` (which the rounded corners
    // over the accordion's grid transition need) drops its automatic minimum size to zero, so
    // it could be crushed to nothing. Opening a second guide compressed every card above it
    // instead of scrolling the panel.
    //
    // Asserted on the CLASS because jsdom has no layout: every rect here is 0×0, so a
    // measured height cannot tell a squashed card from a whole one. `docs/testing/e2e.md`
    // owns the browser check.
    it('does not shrink when its container runs out of room', () => {
      const {container} = render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
        />
      );
      expect(container.firstElementChild).toHaveClass('shrink-0');
    });

    // OFF by default, which is the half that says the clamp belongs to the panel. `/help`
    // renders the same card and must keep wrapping: that page scrolls the document, and its
    // text column is NARROWER than the panel's, so an ellipsis would cut more there and buy
    // nothing. Without this, moving the clamp into the card unconditionally stays green.
    it('does not clamp its heading unless asked', () => {
      render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
        />
      );
      expect(screen.getByText('Upload files')).not.toHaveClass('truncate');
      expect(screen.getByText('Add files from your computer.')).not.toHaveClass('truncate');
    });

    it('holds its title to one line while closed, and shows it whole once open', () => {
      render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
          clampHeading
        />
      );
      const header = screen.getByRole('button', {name: /Upload files/});
      // Both lines of the header, not the title alone: the subtitles are the sentences long
      // enough to wrap, so truncating only the bold line leaves the list as tall as it was.
      const title = screen.getByText('Upload files');
      const subtitle = screen.getByText('Add files from your computer.');

      expect(title).toHaveClass('truncate');
      expect(subtitle).toHaveClass('truncate');

      fireEvent.click(header);

      expect(title).not.toHaveClass('truncate');
      expect(subtitle).not.toHaveClass('truncate');
    });

    it('renders no callout when the guide has none', async () => {
      render(
        <HelpGuideCard
          guide={{...guide, callout: undefined}}
          iconName="files"
          defaultOpen
        />
      );
      expect(screen.queryByText(/Careful\./)).not.toBeInTheDocument();
      expect(screen.queryByText(/Tip\./)).not.toBeInTheDocument();
    });
  });
});

// ─── from HelpPage.test.tsx ───
describe('HelpPage', () => {
  // Through the shared harness since SPEC-163: the page gates its own sections on the
  // feature flags, so it now needs the auth context and the query client the flags hook
  // reads. The harness seeds the flags all-on, which is the state these tests assume.
  function renderAt(path: string) {
    return renderWithProviders(<HelpPage />, {route: path});
  }

  function setWidth(w: number) {
    Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
  }

  afterEach(() => setWidth(1024));

  describe('HelpPage (SPEC-074 FR-002/003)', () => {
    it('activates the first section by default (no hash)', () => {
      renderAt('/help');
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent(HELP_SECTIONS[0].label);
      expect(screen.getByRole('button', {name: new RegExp(HELP_SECTIONS[0].label)})).toHaveAttribute(
        'aria-current',
        'true'
      );
    });

    it('activates the section named by the URL hash', () => {
      renderAt('/help#query');
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Query');
    });

    it('falls back to the first section for an unknown hash', () => {
      renderAt('/help#does-not-exist');
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent(HELP_SECTIONS[0].label);
    });

    it('switches sections when a sidebar item is selected', () => {
      renderAt('/help');
      fireEvent.click(screen.getByRole('button', {name: /Notifications/}));
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Notifications');
    });

    it('opens the first guide of a section by default', () => {
      renderAt('/help');
      const firstGuide = HELP_SECTIONS[0].guides[0];
      expect(screen.getByRole('button', {name: new RegExp(firstGuide.title)})).toHaveAttribute('aria-expanded', 'true');
    });

    // ── SPEC-103: responsive section selector ──────────────────────────────────

    it('shows the rail (not chips) at ≥ tablet, and chips (not rail) on mobile', () => {
      setWidth(1024);
      const {unmount} = renderAt('/help');
      expect(screen.getByRole('complementary', {name: 'Guides navigation'})).toBeInTheDocument();
      expect(screen.queryByRole('navigation', {name: 'Guides sections'})).not.toBeInTheDocument();
      unmount();

      setWidth(400);
      renderAt('/help');
      expect(screen.getByRole('navigation', {name: 'Guides sections'})).toBeInTheDocument();
      expect(screen.queryByRole('complementary', {name: 'Guides navigation'})).not.toBeInTheDocument();
    });

    it('selects a section from the mobile chips via the hash path', () => {
      setWidth(400);
      renderAt('/help');
      fireEvent.click(screen.getByRole('button', {name: 'Query'}));
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Query');
    });

    it('renders no search control at any breakpoint (FR-005)', () => {
      for (const w of [400, 1024, 1400]) {
        setWidth(w);
        const {unmount} = renderAt('/help');
        expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {name: /search/i})).not.toBeInTheDocument();
        expect(screen.queryByPlaceholderText(/search/i)).not.toBeInTheDocument();
        unmount();
      }
    });
  });
});

// ─── from HelpPage.a11y.test.tsx ───
describe('HelpPage.a11y', () => {
  const page = (
    <TestProviders route="/help">
      <HelpPage />
    </TestProviders>
  );

  describe('Help page accessibility (SPEC-074 FR-006 / SPEC-045)', () => {
    it('has no axe violations with the first section rendered (first guide expanded)', async () => {
      await expectNoA11yViolations(page, ROUTE_AXE_OPTIONS);
    });

    it('exposes exactly one <h1> and a <main> landmark', () => {
      render(page);
      expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
      expect(screen.getByRole('main')).toBeInTheDocument();
    });

    it('gives the header help control an accessible name (FR-001)', async () => {
      // Through the app's providers rather than a bare router: the control resolves its
      // behaviour from the route and the flags, so it needs both. `/` has no contextual
      // section, which is the link half of that decision.
      const control = (
        <TestProviders route="/">
          <HelpLink />
        </TestProviders>
      );
      await expectNoA11yViolations(control, COMPONENT_AXE_OPTIONS);
      render(control);
      expect(screen.getByRole('link', {name: 'Help & guides'})).toBeInTheDocument();
    });
  });
});

// ─── from HelpSectionChips.test.tsx ───
describe('HelpSectionChips', () => {
  const sections: HelpSection[] = [
    {
      id: 'files',
      label: 'Files',
      subtitle: '',
      icon: 'files',
      guides: [{id: 'a', title: 'A', subtitle: '', steps: ['x']}]
    },
    {
      id: 'query',
      label: 'Query',
      subtitle: '',
      icon: 'query',
      guides: [{id: 'c', title: 'C', subtitle: '', steps: ['x']}]
    },
    {
      id: 'shared-connections',
      label: 'Shared spaces',
      subtitle: '',
      icon: 'connections',
      guides: [{id: 'd', title: 'D', subtitle: '', steps: ['x']}]
    }
  ];

  describe('HelpSectionChips (SPEC-103 FR-003)', () => {
    it('renders a labelled nav with one chip per section (full labels)', () => {
      render(
        <HelpSectionChips
          sections={sections}
          activeId="files"
          onSelect={vi.fn()}
        />
      );
      const nav = screen.getByRole('navigation', {name: 'Guides sections'});
      expect(nav).toBeInTheDocument();
      expect(nav).toHaveClass('overflow-x-auto');
      expect(screen.getAllByRole('button')).toHaveLength(3);
      expect(screen.getByRole('button', {name: 'Shared spaces'})).toBeInTheDocument();
    });

    it('highlights exactly the active section chip', () => {
      render(
        <HelpSectionChips
          sections={sections}
          activeId="query"
          onSelect={vi.fn()}
        />
      );
      expect(screen.getByRole('button', {name: 'Query'})).toHaveAttribute('aria-current', 'true');
      expect(screen.getByRole('button', {name: 'Files'})).not.toHaveAttribute('aria-current');
      expect(screen.getAllByRole('button').filter((b) => b.getAttribute('aria-current') === 'true')).toHaveLength(1);
    });

    it('calls onSelect with the section id when a chip is activated', () => {
      const onSelect = vi.fn();
      render(
        <HelpSectionChips
          sections={sections}
          activeId="files"
          onSelect={onSelect}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Shared spaces'}));
      expect(onSelect).toHaveBeenCalledWith('shared-connections');
    });

    it('keeps chips on a single line (no wrap)', () => {
      render(
        <HelpSectionChips
          sections={sections}
          activeId="files"
          onSelect={vi.fn()}
        />
      );
      for (const chip of screen.getAllByRole('button')) {
        expect(chip).toHaveClass('shrink-0', 'whitespace-nowrap');
      }
    });

    it('has no a11y violations', async () => {
      await expectNoA11yViolations(
        <HelpSectionChips
          sections={sections}
          activeId="files"
          onSelect={vi.fn()}
        />,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from HelpSidebar.test.tsx ───
describe('HelpSidebar', () => {
  const sections: HelpSection[] = [
    {
      id: 'files',
      label: 'Files',
      subtitle: 'files sub',
      icon: 'files',
      guides: [
        {id: 'a', title: 'A', subtitle: '', steps: ['x']},
        {id: 'b', title: 'B', subtitle: '', steps: ['x']}
      ]
    },
    {
      id: 'query',
      label: 'Query',
      subtitle: 'query sub',
      icon: 'query',
      guides: [{id: 'c', title: 'C', subtitle: '', steps: ['x']}]
    }
  ];

  // A section whose short label differs from its full label (SPEC-103 FR-002).
  const sharedSection: HelpSection[] = [
    {
      id: 'shared-connections',
      label: 'Shared spaces',
      subtitle: 'shared sub',
      icon: 'connections',
      guides: [{id: 'd', title: 'D', subtitle: '', steps: ['x']}]
    }
  ];

  function setWidth(w: number) {
    Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
  }

  afterEach(() => setWidth(1024));

  describe('HelpSidebar (SPEC-074 FR-003)', () => {
    it('renders one item per section with a guide count derived from content', () => {
      render(
        <HelpSidebar
          sections={sections}
          activeId="files"
          onSelect={vi.fn()}
        />
      );
      const items = screen.getAllByRole('button');
      expect(items).toHaveLength(2);
      expect(items[0]).toHaveTextContent('Files');
      expect(items[0]).toHaveTextContent('2');
      expect(items[1]).toHaveTextContent('Query');
      expect(items[1]).toHaveTextContent('1');
    });

    it('marks the active section with aria-current', () => {
      render(
        <HelpSidebar
          sections={sections}
          activeId="query"
          onSelect={vi.fn()}
        />
      );
      expect(screen.getByRole('button', {name: /Query/})).toHaveAttribute('aria-current', 'true');
      expect(screen.getByRole('button', {name: /Files/})).not.toHaveAttribute('aria-current');
    });

    it('calls onSelect with the section id when clicked', async () => {
      const onSelect = vi.fn();
      render(
        <HelpSidebar
          sections={sections}
          activeId="files"
          onSelect={onSelect}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: /Query/}));
      expect(onSelect).toHaveBeenCalledWith('query');
    });

    // ── SPEC-103 FR-002: narrowed tablet rail with short labels ────────────────

    it('renders the short section label at tablet width', () => {
      setWidth(1000); // tablet band (< desktop)
      render(
        <HelpSidebar
          sections={sharedSection}
          activeId="shared-connections"
          onSelect={vi.fn()}
        />
      );
      expect(screen.getByText('Shared')).toBeInTheDocument();
      expect(screen.queryByText('Shared spaces')).not.toBeInTheDocument();
    });

    it('renders the full section label at desktop width', () => {
      setWidth(1400); // desktop
      render(
        <HelpSidebar
          sections={sharedSection}
          activeId="shared-connections"
          onSelect={vi.fn()}
        />
      );
      expect(screen.getByText('Shared spaces')).toBeInTheDocument();
    });
  });
});

describe('the delete-space guide (SPEC-205)', () => {
  it('no longer promises the space is destroyed with no undo', () => {
    // Asserted on the guide OBJECT rather than by rendering the panel: the content module is
    // the source of truth and a rendered assertion would pass just as well on a guide the
    // panel happens not to show.
    const section = HELP_SECTIONS.find((s) => s.id === 'shared-connections');
    const guide = section?.guides.find((g) => g.id === 'delete-space');

    expect(guide).toBeDefined();
    const text = `${guide!.subtitle} ${guide!.intro} ${guide!.callout?.text ?? ''}`;
    expect(text).not.toMatch(/no undo/i);
    expect(text).not.toMatch(/permanently remove|permanently deletes/i);
    expect(text).toMatch(/kept by administrators/i);
    expect(text).toMatch(/name can never be used/i);
  });
});

describe('the refresh-table guide', () => {
  it('promises the kept order, tells the user to put a new CSV column last, and does not blame the older files', () => {
    // Asserted on the guide OBJECT, like the delete-space case above: the content module is the
    // source of truth. The STEPS are in the text because the card renders them, and a negative
    // assertion that skips them forbids nothing — a forbidden sentence lands in a step just as
    // readably as in the intro.
    //
    // The three negatives are FR-003's, the claims a CSV refresh keeping the table's order makes
    // false: that a refresh reorders the table to match its first file, that a misplaced column
    // misreads the OLDER files rather than the one that misplaced it, and that the user should
    // reorder a file to restore the table's order. Each shipped in this guide at some point.
    const section = HELP_SECTIONS.find((s) => s.id === 'tables');
    const guide = section?.guides.find((g) => g.id === 'refresh-table');

    expect(guide).toBeDefined();
    //
    // The copy is authored with typographic apostrophes, so the text is normalized before
    // matching: a pattern written with a plain `'` matches nothing against `\u2019` and the
    // negative assertions would forbid nothing at all.
    const text = [guide!.subtitle, guide!.intro ?? '', ...guide!.steps, guide!.callout?.text ?? '']
      .join(' ')
      .replace(/\u2019/g, "'");
    expect(text).toMatch(/never moves the columns it already has/i);
    expect(text).toMatch(/put a new column last/i);
    expect(text).toMatch(/comes back as a <b>new<\/b> column, at the <b>end<\/b> of the table/i);
    expect(text).not.toMatch(/older files/i);
    expect(text).not.toMatch(/reorder(ing)? (the |your )?(columns|file)|to match the order|restore the table's order/i);
  });
});

describe('the upload guide', () => {
  it('names the collision prompt’s choices and promises no suggested name', () => {
    // The prompt starts its rename field at the colliding name; only a same-folder copy proposes a
    // numbered one, so the guide must not promise that for an upload.
    const section = HELP_SECTIONS.find((s) => s.id === 'files');
    const guide = section?.guides.find((g) => g.id === 'upload-files');

    expect(guide).toBeDefined();
    const callout = guide!.callout?.text ?? '';
    expect(callout).toMatch(/<b>Rename<\/b> lets you type a different name/);
    expect(callout).toMatch(/<b>Cancel<\/b> leaves the new one out/);
    expect(callout).toMatch(/<b>Overwrite<\/b> replaces the existing file for good/);
    // An overwrite cannot be undone, so this is a warning like the other guides that say so.
    expect(guide!.callout?.kind).toBe('warning');
    const everything = [guide!.subtitle, guide!.intro ?? '', ...guide!.steps, callout].join(' ');
    expect(everything).not.toMatch(/suggest|numbered/i);
  });
});

describe('guide inline markup', () => {
  it('renders each supported tag as its element, never as literal markup', () => {
    const guide: HelpGuide = {
      id: 'save-query',
      title: 'Save a query',
      subtitle: 'Keep it for later.',
      steps: ['Click <b>Save</b> or press <kbd>Enter</kbd> to write a <code>.sql</code> file.'],
      callout: {kind: 'tip', text: 'Another space gets a <i>new</i> file.'}
    };

    render(
      <HelpGuideCard
        guide={guide}
        iconName="query"
        defaultOpen
      />
    );

    expect(screen.getByText('Save').tagName).toBe('STRONG');
    expect(screen.getByText('Enter').tagName).toBe('KBD');
    expect(screen.getByText('.sql').tagName).toBe('CODE');
    expect(screen.getByText('new').tagName).toBe('EM');
    expect(screen.queryByText(/<\/?(b|kbd|code|i)>/)).not.toBeInTheDocument();
  });

  it('shows no raw tag anywhere in the authored help, whichever flags hide it', () => {
    const rawTag = /<\/?[a-z]/i;
    const cards = HELP_SECTIONS.flatMap((section) =>
      section.guides.map((guide) => ({key: `${section.id}/${guide.id}`, guide, icon: section.icon}))
    );

    const {container} = render(
      <>
        {cards.map(({key, guide, icon}) => (
          <HelpGuideCard
            key={key}
            guide={guide}
            iconName={icon}
            defaultOpen
          />
        ))}
      </>
    );

    // Section labels and subtitles are printed verbatim, never parsed, so their source text is what shows.
    const raw = HELP_SECTIONS.flatMap((section) => [section.label, section.subtitle]).filter((text) =>
      rawTag.test(text)
    );
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      if (rawTag.test(node.textContent ?? '')) raw.push(node.textContent ?? '');
    }
    // The walk proves nothing unless every step reached the DOM it scanned.
    expect(screen.getAllByRole('listitem')).toHaveLength(cards.reduce((sum, {guide}) => sum + guide.steps.length, 0));
    expect(raw).toEqual([]);
  });
});

describe('the long-query guides', () => {
  it('state the watch’s ceiling the code enforces, and where a long query’s results go', () => {
    // The minutes are computed from the constant, so a changed ceiling fails here rather than
    // leaving the guides describing the old one.
    const minutes = `${MAX_POLL_DURATION_MS / 60_000} minutes`;
    const guide = (section: string, id: string) =>
      HELP_SECTIONS.find((s) => s.id === section)?.guides.find((g) => g.id === id);

    const runQuery = guide('query', 'run-query')?.callout?.text ?? '';
    const runScript = guide('query', 'run-script')?.steps.find((step) => step.startsWith('If a statement fails')) ?? '';
    // Not something a user does, so the Explorer states it in its callout rather than a step.
    const explore = guide('data-explorer', 'start-exploring')?.callout?.text ?? '';

    for (const text of [runQuery, runScript, explore]) expect(text).toContain(minutes);
    expect(runQuery).toContain('athenaresults');
    expect(explore).toContain('athenaresults');
  });
});

// ─── guide-level deep links (SPEC-207 FR-005) ───────────────────────────────

describe('HelpPage guide deep links', () => {
  /** A client answering the flags query with the compiled-in defaults plus `overrides`. */
  function clientWithFlags(overrides: Partial<FeatureFlags> = {}) {
    const client = createTestQueryClient();
    client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
    client.setQueryData(featureFlagKeys.resolved(configValue('environment')), {
      ...FEATURE_FLAG_DEFAULTS,
      ...overrides
    });
    return client;
  }

  const renderAt = (route: string, overrides: Partial<FeatureFlags> = {}) =>
    renderWithProviders(<HelpPage />, {route, queryClient: clientWithFlags(overrides), seedFeatureFlags: false});

  const byTitle = (title: string) => ({name: (accessibleName: string) => accessibleName.startsWith(title)});

  // jsdom implements neither of the page's two scroll calls, so the guide scroll is stubbed
  // in rather than spied on. Its ORDER relative to the reset-to-top is unassertable here —
  // there is no layout — and is held by the comment beside the effects instead.
  const scrolled: Element[] = [];
  beforeEach(() => {
    scrolled.length = 0;
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
  });
  afterEach(() => {
    delete (Element.prototype as {scrollIntoView?: unknown}).scrollIntoView;
  });

  it('leaves a SECTION hash meaning exactly what it always has', () => {
    // Pinned so the guide half below cannot regress it: a section hash selects the section
    // and opens its FIRST card, naming no guide.
    renderAt('/help#query');

    expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Query');
    const query = HELP_SECTIONS.find((s) => s.id === 'query')!;
    expect(screen.getByRole('button', byTitle(query.guides[0].title))).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', byTitle(query.guides[1].title))).toHaveAttribute('aria-expanded', 'false');
    expect(scrolled).toEqual([]);
  });

  it('opens the guide a guide hash names, in that guide’s own section, and scrolls to it', () => {
    // `delete-space` lives in Shared spaces, not the first section — so this fails for a
    // resolver that only ever answers "the first visible section".
    renderAt('/help#delete-space');

    expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Shared spaces');
    expect(screen.getByRole('button', byTitle('Delete a space'))).toHaveAttribute('aria-expanded', 'true');
    const shared = HELP_SECTIONS.find((s) => s.id === 'shared-connections')!;
    expect(screen.getByRole('button', byTitle(shared.guides[0].title))).toHaveAttribute('aria-expanded', 'false');
    expect(scrolled.at(-1)).toHaveAttribute('id', 'help-guide-delete-space');
  });

  it('falls back to the section-level behaviour for a guide the flags hide', () => {
    // What it cannot see, said out loud: every flag-hidden guide whose section survives lives
    // in the Files section, and Files is the first section — so "the guide's own section" and
    // "the first visible section" are the same answer for all of them today. What this does
    // assert is that no card is expanded by a hash naming content nobody rendered.
    renderAt('/help#check-data-quality', {dataQuality: false});

    expect(screen.getByRole('heading', {level: 1})).toHaveTextContent(HELP_SECTIONS[0].label);
    expect(screen.queryByRole('button', byTitle('Check data quality'))).not.toBeInTheDocument();
    expect(screen.getByRole('button', byTitle(HELP_SECTIONS[0].guides[0].title))).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(scrolled).toEqual([]);
  });

  it('moves to the guide a NEW hash names, without remounting the page', async () => {
    // The mount-only half passes with `defaultOpen` alone, because the card reads it once
    // into state. This is what the card's key is for: a hash change while the page stays
    // mounted has to re-open a different card.
    const {user} = renderWithProviders(
      <>
        <HelpPage />
        <Link to="/help#leave-space">To leave-space</Link>
      </>,
      {route: '/help#delete-space'}
    );

    expect(screen.getByRole('button', byTitle('Delete a space'))).toHaveAttribute('aria-expanded', 'true');
    await user.click(screen.getByRole('link', {name: 'To leave-space'}));

    expect(screen.getByRole('button', byTitle('Leave a space'))).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', byTitle('Delete a space'))).toHaveAttribute('aria-expanded', 'false');
    expect(scrolled.at(-1)).toHaveAttribute('id', 'help-guide-leave-space');
  });

  it('writes no history entry when it expands a guide', () => {
    // `location.key` changes on a push AND on a replace, so this is stricter than the
    // criterion: any navigation at all reddens it.
    const keys: string[] = [];
    function KeyProbe() {
      keys.push(useLocation().key);
      return null;
    }
    renderWithProviders(
      <>
        <HelpPage />
        <KeyProbe />
      </>,
      {route: '/help#delete-space'}
    );

    expect(new Set(keys).size).toBe(1);
    expect(screen.getByRole('button', byTitle('Delete a space'))).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('the archive switch in Help', () => {
  const filesGuides = (sections: HelpSection[]) =>
    sections.find((section) => section.id === 'files')?.guides.map((g) => g.id);

  it('drops the archive guide and keeps the Files section that holds it', () => {
    const off = filesGuides(visibleHelpSections((key) => key !== 'archive'));

    expect(off).toBeDefined();
    expect(off).not.toContain('archive-files');
    // Names Archive in passing and stays: the switch hides the archive guide, not every mention.
    expect(off).toContain('rename-move-copy-delete');
  });

  it('shows the archive guide with every flag on', () => {
    expect(filesGuides(visibleHelpSections(() => true))).toContain('archive-files');
  });
});

describe('what a switch removes, Help leaves out of the guides it does not hide', () => {
  const guideText = (id: string) => {
    const guide = HELP_SECTIONS.flatMap((s) => s.guides).find((g) => g.id === id);
    expect(guide, id).toBeDefined();
    return [guide!.subtitle, guide!.intro ?? '', ...guide!.steps, guide!.callout?.text ?? ''].join(' ');
  };

  it('keeps the theme guide with every switch off, since the Theme control is on every page', () => {
    const guides = visibleHelpSections(() => false).flatMap((s) => s.guides.map((g) => g.id));

    expect(guides).toContain('choose-a-theme');
  });

  it('names a shared space or a conversion format only in the guides those switches hide', () => {
    // The recipient kind and the Format field are each removed by their own switch, so the send,
    // share and save guides beside them must stay true without them. The options live in the
    // split-out guides, which the registry hides with the switch.
    for (const id of ['send-files', 'share-table']) expect(guideText(id), id).not.toMatch(/shared space|Space names/i);
    for (const id of ['save-results', 'explore-copy-and-export'])
      expect(guideText(id), id).not.toMatch(/Parquet|Excel|<b>Format<\/b>/);

    expect(guideText('send-files-to-a-space')).toMatch(/<b>Shared spaces<\/b>/);
    expect(guideText('share-table-to-a-space')).toMatch(/<b>Shared spaces<\/b>/);
    expect(guideText('save-results-formats')).toMatch(/<b>Format<\/b>/);
    expect(guideText('explore-save-formats')).toMatch(/<b>Format<\/b>/);
  });
});

describe('the words someone used to a desktop SQL client looks for', () => {
  const guide = (id: string) => {
    const found = HELP_SECTIONS.flatMap((s) => s.guides).find((g) => g.id === id);
    expect(found, id).toBeDefined();
    return found!;
  };
  const steps = (id: string) => [guide(id).intro ?? '', ...guide(id).steps].join(' ');

  // A closed card shows only its title and a subtitle cut to one line, so a word must sit near the
  // front of the subtitle to be seen by someone scanning the list. On a 375px phone the panel is a
  // full-width sheet showing about 214px of subtitle, which is about 34 characters of 13px Inter.
  // 32 is a stand-in for that width, kept below it for headroom since glyph widths vary.
  const SUBTITLE_VISIBLE_CHARS = 32;

  it('puts each one near the front of the subtitle of the guide that holds the feature', () => {
    const onCard: [string, RegExp][] = [
      ['explore-filter-sort', /filter by value/i],
      ['browse-databases', /database navigator/i],
      ['run-script', /SQL script/i],
      ['work-with-results', /result tabs/i],
      ['save-query', /SQL script/i],
      ['load-saved-query', /\.sql script/i],
      ['archive-files', /back where they were/i]
    ];
    for (const [id, pattern] of onCard) {
      const match = pattern.exec(guide(id).subtitle);
      expect(match, `${id} ${pattern}`).not.toBeNull();
      expect(match!.index + match![0].length, `${id} ${pattern}`).toBeLessThanOrEqual(SUBTITLE_VISIBLE_CHARS);
    }
  });

  it('names LIKE, NOT LIKE, IN and NOT IN in the filter steps, and result tabs in the script steps', () => {
    for (const pattern of [/<b>LIKE<\/b>/, /<b>NOT LIKE<\/b>/, /<b>IN<\/b>/, /<b>NOT IN<\/b>/])
      expect(steps('explore-filter-sort'), String(pattern)).toMatch(pattern);
    expect(steps('run-script')).toMatch(/result tab/i);
  });

  it('weaves them into the guides rather than naming DBeaver', () => {
    for (const section of HELP_SECTIONS) {
      expect(`${section.label} ${section.subtitle}`, section.id).not.toMatch(/dbeaver/i);
      for (const g of section.guides) {
        const text = [g.title, g.subtitle, g.intro ?? '', ...g.steps, g.callout?.text ?? ''].join(' ');
        expect(text, g.id).not.toMatch(/dbeaver/i);
      }
    }
  });
});

describe('the filter box the Data Explorer no longer has', () => {
  it('is named by no guide, so a later edit cannot send anyone to it', () => {
    const texts = HELP_SECTIONS.flatMap((section) => [
      `${section.label} ${section.subtitle}`,
      ...section.guides.map((g) => [g.title, g.subtitle, g.intro ?? '', ...g.steps, g.callout?.text ?? ''].join(' '))
    ]);
    // The population first: over no text at all, the absence below would hold vacuously.
    expect(texts.join(' ')).toMatch(/<b>Filter rows…<\/b>/);
    for (const text of texts) expect(text).not.toMatch(/Filter expression|Apply expression/i);
  });
});
