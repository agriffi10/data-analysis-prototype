import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, screen, waitFor, within} from '@testing-library/react';
import {Link, Route, Routes, useLocation, useNavigate} from 'react-router';
import {QueryClient} from '@tanstack/react-query';
import {Header} from '../../components/Header';
import {HelpPanel} from './HelpPanel';
import {HelpPage} from './HelpPage';
import {HELP_SECTIONS} from './helpContent';
import {HELP_SURFACES} from './helpSurfaces';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../feature-flags';
import {getFeatureFlags} from '../feature-flags/featureFlags.service';
import type {FeatureFlags} from '../feature-flags';
import {configValue} from '../../lib/runtimeConfig';
import type {HelpSectionId} from './help.types';

// The AWS boundary the header mounts for the bell's unread indicator, and the only thing
// mocked here.
vi.mock('../notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

// One test republishes the flag document mid-session; every other test here pre-seeds the cache
// and never lets this run.
vi.mock('../feature-flags/featureFlags.service', async (importActual) => ({
  ...(await importActual<typeof import('../feature-flags/featureFlags.service')>()),
  getFeatureFlags: vi.fn()
}));

beforeEach(() => {
  vi.mocked(getFeatureFlags).mockResolvedValue({success: true, data: FEATURE_FLAG_DEFAULTS});
});

/** A client answering the flags query with the compiled-in defaults plus `overrides`. */
function clientWithFlags(overrides: Partial<FeatureFlags> = {}): QueryClient {
  const client = createTestQueryClient();
  client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
  client.setQueryData(featureFlagKeys.resolved(configValue('environment')), {
    ...FEATURE_FLAG_DEFAULTS,
    ...overrides
  });
  return client;
}

/** Reports the router's current location, so "performed no navigation" is assertable. */
function LocationProbe() {
  const {pathname, hash} = useLocation();
  return <output aria-label="location">{`${pathname}${hash}`}</output>;
}

function renderHeaderAt(route: string, overrides: Partial<FeatureFlags> = {}) {
  return renderWithProviders(
    <>
      <Header />
      <LocationProbe />
    </>,
    {
      route,
      auth: authenticated('alice'),
      queryClient: clientWithFlags(overrides),
      seedFeatureFlags: false
    }
  );
}

/** A card header button's accessible name is its title followed by its subtitle. */
const byTitle = (title: string) => ({name: (accessibleName: string) => accessibleName.startsWith(title)});

const section = (id: HelpSectionId) => HELP_SECTIONS.find((s) => s.id === id)!;

function setWidth(w: number) {
  Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
}

afterEach(() => {
  cleanup();
  setWidth(1024);
});

// ─── FR-001: the panel renders the section the user can actually see ───────────

describe('HelpPanel', () => {
  const renderPanel = (sectionId: HelpSectionId, overrides: Partial<FeatureFlags> = {}) =>
    renderWithProviders(
      <HelpPanel
        sectionId={sectionId}
        open
        onClose={vi.fn()}
      />,
      {queryClient: clientWithFlags(overrides), seedFeatureFlags: false}
    );

  it('is named for its section and holds that section’s guides and no other’s', () => {
    renderPanel('query');

    const dialog = screen.getByRole('dialog', {name: section('query').label});
    for (const guide of section('query').guides) {
      expect(within(dialog).getByRole('button', byTitle(guide.title)), guide.id).toBeInTheDocument();
    }
    expect(within(dialog).queryByRole('button', byTitle('Upload files'))).not.toBeInTheDocument();
  });

  it('drops a guide the flags hide, exactly as the full page does', () => {
    const hidden = 'When a move or copy is refused';
    const shown = 'Upload files';

    const {unmount} = renderPanel('files', {asyncFileOperations: false});
    expect(screen.queryByRole('button', byTitle(hidden))).not.toBeInTheDocument();
    // A neighbour in the same section, so the absence above cannot be an empty panel.
    expect(screen.getByRole('button', byTitle(shown))).toBeInTheDocument();
    unmount();

    // THE FULL PAGE, under the SAME non-default flags — the criterion is that the two agree,
    // and every panel-only assertion above is satisfied by a panel that filters on its own.
    const page = renderWithProviders(<HelpPage />, {
      route: '/help#files',
      queryClient: clientWithFlags({asyncFileOperations: false}),
      seedFeatureFlags: false
    });
    expect(screen.queryByRole('button', byTitle(hidden))).not.toBeInTheDocument();
    expect(screen.getByRole('button', byTitle(shown))).toBeInTheDocument();
    page.unmount();

    renderPanel('files');
    expect(screen.getByRole('button', byTitle(hidden))).toBeInTheDocument();
  });

  it('reaches the guide→flag registry from exactly ONE module in this feature', () => {
    // Agreement is the property; a single call site is the mechanism the criterion names, and
    // the two are different claims — a duplicated filter agrees with the original right up
    // until one of them changes.
    const sources = import.meta.glob('./*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
      string,
      string
    >;
    const modules = Object.entries(sources).filter(([path]) => !path.includes('.test.'));
    expect(modules.length, 'the source sweep matched nothing').toBeGreaterThan(5);

    const callers = modules.filter(([, source]) => source.includes('hiddenHelpIds')).map(([path]) => path);
    expect(callers).toEqual(['./visibleSections.ts']);
  });

  it('renders the same guide card markup the full page renders', () => {
    // The one difference the page adds is an anchor WRAPPER carrying the deep-link id; the
    // card itself is the same component with the same props, which is what this compares.
    const guide = section('query').guides[0];
    const cardHtml = () => {
      const header = screen.getByRole('button', byTitle(guide.title));
      // `useId` mints a fresh value per render, so the panel/controls wiring is normalised.
      return header
        .parentElement!.outerHTML.replace(/\bid="[^"]*"/g, 'id="ID"')
        .replace(/\baria-controls="[^"]*"/g, 'aria-controls="ID"');
    };

    const {unmount} = renderWithProviders(<HelpPage />, {route: '/help#query'});
    const fromPage = cardHtml();
    unmount();

    renderPanel('query');
    expect(cardHtml()).toBe(fromPage);
  });

  it('issues no network request — the content is bundled', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    renderPanel('files');
    expect(screen.getByRole('dialog', {name: 'Files'})).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  // ─── FR-008: full-height sheet on mobile, right-hand sheet above it ──────────

  it('takes the drawer’s full-height variant, and keeps the close control out of the scroll area', () => {
    // Class assertions, because jsdom has no layout: what they pin is that the panel asks for
    // the full-height variant (full width and height below tablet, capped right-hand sheet
    // above) rather than the docked bottom sheet. That it LOOKS right at each width, and that
    // the page beneath does not scroll sideways, are live checks.
    renderPanel('files');

    const dialog = screen.getByRole('dialog', {name: 'Files'});
    expect(dialog).toHaveClass('w-full', 'h-full', 'tablet:max-w-[440px]');

    const close = screen.getByRole('button', {name: 'Close help'});
    const scrollArea = dialog.querySelector('.overflow-y-auto');
    expect(scrollArea).not.toBeNull();
    expect(scrollArea!.contains(close)).toBe(false);
  });
});

// ─── FR-002 / FR-003 / FR-007: the header control ──────────────────────────────

describe('the header help control', () => {
  it('opens the panel on a route the registry covers, without navigating', async () => {
    const {user} = renderHeaderAt('/files');

    expect(screen.queryByRole('link', {name: 'Help & guides'})).not.toBeInTheDocument();
    const control = screen.getByRole('button', {name: 'Help for this page'});
    expect(control).toHaveAttribute('aria-expanded', 'false');

    await user.click(control);

    expect(screen.getByRole('dialog', {name: 'Files'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Help for this page'})).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByLabelText('location')).toHaveTextContent('/files');
  });

  // THE WIRING, not the card's own behaviour — `help.test.tsx` owns that. The clamp is opt-in
  // and only this caller opts in, so a panel that stopped passing the prop would go back to
  // squashing its own heading list with every other test green.
  it('clamps a closed guide heading to one line, and lets the open one wrap', async () => {
    const {user} = renderHeaderAt('/files');
    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    const panel = screen.getByRole('dialog', {name: 'Files'});

    // The FIRST card opens by default, so one of each state is on screen without driving one.
    const headings = [...panel.querySelectorAll('button[aria-expanded] span > span:first-child')];
    expect(headings.length, 'no guide headings were found — the check below sees nothing').toBeGreaterThan(1);

    expect(headings[0]).not.toHaveClass('truncate');
    for (const closed of headings.slice(1)) expect(closed).toHaveClass('truncate');
  });

  it('stays the link to /help on a route with no row', () => {
    renderHeaderAt('/help');

    expect(screen.getByRole('link', {name: 'Help & guides'})).toHaveAttribute('href', '/help');
    expect(screen.queryByRole('button', {name: 'Help for this page'})).not.toBeInTheDocument();
  });

  it('adds no element to the header — the control count does not move with the route', () => {
    // Route invariance rather than a pinned number: sibling specs legitimately add header
    // controls, and a pinned count would then fail for a reason that has nothing to do with
    // contextual help.
    const controlsAt = (route: string) => {
      const {unmount} = renderHeaderAt(route);
      const header = screen.getByRole('banner');
      const count = within(header).getAllByRole('button').length + within(header).queryAllByRole('link').length;
      unmount();
      return count;
    };

    expect(controlsAt('/files')).toBe(controlsAt('/help'));
  });

  it('is the same affordance at every breakpoint', () => {
    for (const width of [400, 1024, 1400]) {
      setWidth(width);
      const {unmount} = renderHeaderAt('/files');
      expect(screen.getByRole('button', {name: 'Help for this page'}), `at ${width}px`).toBeInTheDocument();
      unmount();
    }
  });

  it('leaves the mobile nav drawer’s direct route to /help alone', async () => {
    setWidth(400);
    const {user} = renderHeaderAt('/files');

    await user.click(screen.getByRole('button', {name: 'Open navigation'}));
    const drawer = screen.getByRole('dialog', {name: 'Navigation'});
    expect(within(drawer).getByRole('link', {name: /Help/})).toHaveAttribute('href', '/help');
  });

  it('drives every registered row to its section', async () => {
    for (const surface of HELP_SURFACES) {
      const {user, unmount} = renderHeaderAt(surface.path);
      await user.click(screen.getByRole('button', {name: 'Help for this page'}));
      expect(screen.getByRole('heading', {level: 2}), surface.path).toHaveTextContent(section(surface.sectionId).label);
      unmount();
    }
  });

  // ─── FR-007: a gated page's help is gated with the page ──────────────────────

  it('falls back to navigation on a route whose feature is off', () => {
    // Nothing declares this. With `dataExplorer` off the Data Explorer SECTION is already
    // filtered out of the visible set, so `/explore` resolves to no section. That the route
    // itself renders its gated element is asserted by the registry walk in
    // `gatedSurfaces.test.tsx`; what is asserted here is that the help control follows it.
    renderHeaderAt('/explore', {dataExplorer: false});

    expect(screen.getByRole('link', {name: 'Help & guides'})).toHaveAttribute('href', '/help');
    expect(screen.queryByRole('button', {name: 'Help for this page'})).not.toBeInTheDocument();
  });

  it('does not re-open itself when a hidden feature comes back', async () => {
    // The flag document is re-read within a long session. Hiding the section only makes an
    // open panel invisible, so publishing the feature back would bring it up again with no
    // user action — `aria-expanded="true"` over a page nobody asked for it on.
    //
    // Republished through the SERVICE, not by writing the cache: a `setQueryData` on this
    // client reaches the cache and never reaches `useFeature`, so a test built on it asserts
    // nothing. The `waitFor`s are not decoration either — TanStack notifies observers on a
    // timer that neither form of `act` drains.
    const client = clientWithFlags();
    const publish = async (flags: FeatureFlags) => {
      vi.mocked(getFeatureFlags).mockResolvedValue({success: true, data: flags});
      await act(async () => {
        await client.invalidateQueries({queryKey: featureFlagKeys.all});
      });
    };
    const {user} = renderWithProviders(
      <>
        <Header />
        <LocationProbe />
      </>,
      {route: '/files', auth: authenticated('alice'), queryClient: client, seedFeatureFlags: false}
    );

    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    expect(screen.getByRole('dialog', {name: 'Files'})).toBeInTheDocument();

    await publish({...FEATURE_FLAG_DEFAULTS, files: false});
    await waitFor(() => expect(screen.getByRole('link', {name: 'Help & guides'})).toBeInTheDocument());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await publish(FEATURE_FLAG_DEFAULTS);
    await waitFor(() => expect(screen.getByRole('button', {name: 'Help for this page'})).toBeInTheDocument());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Help for this page'})).toHaveAttribute('aria-expanded', 'false');
  });

  it('is the link, not a dead button, while the flags are still loading', () => {
    // `useFeature` reports false until the answer arrives, so every section is hidden and the
    // control resolves to no panel. It degrades to the ungated page rather than to a control
    // that opens nothing — stated here because it is a role change under the pointer.
    renderWithProviders(<Header />, {route: '/files', auth: authenticated('alice'), seedFeatureFlags: false});

    expect(screen.getByRole('link', {name: 'Help & guides'})).toBeInTheDocument();
  });
});

// ─── FR-004 / FR-006: closing, focus, and the way out ──────────────────────────

describe('the panel’s dismissal and focus behaviour', () => {
  /** Header + a stand-in page, two destinations, and a Back control. */
  function Shell() {
    const navigate = useNavigate();
    return (
      <>
        <Header />
        <div>
          <Link to="/notifications">To notifications</Link>
          <Link to="/files">To files</Link>
          <button
            type="button"
            onClick={() => navigate(-1)}>
            Back
          </button>
          <Routes>
            {/* The field lives on the ROUTE, so "what was typed survives" is a statement about
                the route staying mounted and not about a sibling of the drawer. */}
            <Route
              path="/files"
              element={<input aria-label="Note" />}
            />
            <Route
              path="/help"
              element={<HelpPage />}
            />
          </Routes>
        </div>
      </>
    );
  }

  const renderShell = (route: string) =>
    renderWithProviders(<Shell />, {
      route,
      auth: authenticated('alice'),
      queryClient: clientWithFlags(),
      seedFeatureFlags: false
    });

  it('leaves the route beneath mounted, so what was typed survives', async () => {
    const {user} = renderShell('/files');

    await user.type(screen.getByLabelText('Note'), 'half a thought');
    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    await user.click(screen.getByRole('button', {name: 'Close help'}));

    expect(screen.getByLabelText('Note')).toHaveValue('half a thought');
  });

  it('closes on Escape and returns focus to the control that opened it', async () => {
    const {user} = renderShell('/files');

    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    // Move focus INTO the panel first: the drawer does not claim focus on open, so escaping
    // straight away would assert nothing about restoration.
    screen.getByRole('button', {name: 'Close help'}).focus();
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Help for this page'})).toHaveFocus();
  });

  it('keeps Tab inside the panel', async () => {
    // CONTAINMENT, not the first↔last wrap: jsdom reports no layout boxes, so `tabbable`
    // finds nothing inside the drawer and focus falls to the panel itself. Without a trap the
    // same Tab lands on the control after the drawer, so this still has teeth. The true wrap
    // is a live check.
    const {user} = renderShell('/files');

    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    const dialog = screen.getByRole('dialog', {name: 'Files'});
    within(dialog).getByRole('link', {name: 'Open the full guide'}).focus();
    await user.tab();

    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('is closed again after navigating away and back', async () => {
    const {user} = renderShell('/files');

    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    await user.click(screen.getByRole('link', {name: 'To notifications'}));
    await user.click(screen.getByRole('link', {name: 'To files'}));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('is closed by browser Back, which restores a pathname it has already seen', async () => {
    // The failure this pins: Back returns to a pathname the open state was never reset for,
    // and a different section's content is substituted into a live modal.
    const {user} = renderShell('/files');

    await user.click(screen.getByRole('link', {name: 'To notifications'}));
    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    expect(screen.getByRole('dialog', {name: 'Notifications'})).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'Back'}));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('links out to the full page at the same section, and is closed on arrival', async () => {
    const {user} = renderShell('/query');

    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    const out = screen.getByRole('link', {name: 'Open the full guide'});
    expect(out).toHaveAttribute('href', '/help#query');

    await user.click(out);

    expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Query');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('has no axe violations with the panel open', async () => {
    const {user, container} = renderShell('/files');
    await user.click(screen.getByRole('button', {name: 'Help for this page'}));

    // The DRIVEN container, and the COMPONENT options: the shared drawer is an
    // `<aside role="dialog">`, which the route options' `aria-allowed-role` rule rejects.
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
