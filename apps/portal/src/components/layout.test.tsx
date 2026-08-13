import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, renderHook, screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router';
import {AppNavDrawer} from './AppNavDrawer';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations, expectNoA11yViolations} from '../test/axe';
import {CollapsibleRail} from './CollapsibleRail';
import {RAIL_COLLAPSED_STORAGE_KEY, useRailCollapsed} from './useRailCollapsed';
import {memoryStorage} from '../test/storage';
import {PageLayout} from './PageLayout';
import {PrimaryNav} from './PrimaryNav';
import {Sidebar} from '../features/connections/Sidebar';
import {ErrorBoundary} from './ErrorBoundary';
import type {Connection} from '../features/connections/connection.types';
import userEvent from '@testing-library/user-event';

// ─── from AppNavDrawer.test.tsx ───
describe('AppNavDrawer', () => {
  function renderDrawer(props: Partial<React.ComponentProps<typeof AppNavDrawer>> = {}, route = '/files') {
    return render(
      <MemoryRouter initialEntries={[route]}>
        <AppNavDrawer
          open
          onClose={props.onClose ?? vi.fn()}
          isPathEnabled={() => true}
          {...props}
        />
      </MemoryRouter>
    );
  }

  const DESTS = ['Files', 'Query', 'Connections', 'Data quality', 'Notifications', 'Help'];

  describe('AppNavDrawer', () => {
    it('renders nothing when closed', () => {
      renderDrawer({open: false});
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('lists the five primary destinations as links', () => {
      renderDrawer();
      for (const label of DESTS) {
        expect(screen.getByRole('link', {name: label})).toBeInTheDocument();
      }
    });

    it('marks the current route active with aria-current', () => {
      renderDrawer({}, '/query');
      expect(screen.getByRole('link', {name: 'Query'})).toHaveAttribute('aria-current', 'page');
      expect(screen.getByRole('link', {name: 'Files'})).not.toHaveAttribute('aria-current', 'page');
    });

    it('closes on link activation, close button, Escape, and scrim tap', () => {
      const onClose = vi.fn();

      const {unmount} = renderDrawer({onClose});
      fireEvent.click(screen.getByRole('link', {name: 'Files'}));
      expect(onClose).toHaveBeenCalledTimes(1);
      unmount();

      const view2 = renderDrawer({onClose});
      fireEvent.click(screen.getByRole('button', {name: 'Close navigation'}));
      expect(onClose).toHaveBeenCalledTimes(2);
      view2.unmount();

      renderDrawer({onClose});
      fireEvent.keyDown(document, {key: 'Escape'});
      fireEvent.click(screen.getByRole('dialog').parentElement!);
      expect(onClose).toHaveBeenCalledTimes(4);
    });

    it('renders a page-supplied contextual rail, and nothing when omitted', () => {
      const {unmount} = renderDrawer({contextualRail: <div>SPACES RAIL</div>});
      expect(screen.getByText('SPACES RAIL')).toBeInTheDocument();
      unmount();

      renderDrawer();
      expect(screen.queryByText('SPACES RAIL')).not.toBeInTheDocument();
    });

    it('moves focus into the drawer on open and returns it to the trigger on close', async () => {
      function Harness({open}: {open: boolean}) {
        return (
          <MemoryRouter>
            <button>hamburger</button>
            <AppNavDrawer
              open={open}
              onClose={vi.fn()}
              isPathEnabled={() => true}
            />
          </MemoryRouter>
        );
      }
      const {rerender} = render(<Harness open={false} />);
      const trigger = screen.getByRole('button', {name: 'hamburger'});
      trigger.focus();
      expect(trigger).toHaveFocus();

      rerender(<Harness open />);
      await waitFor(() => {
        const dialog = screen.getByRole('dialog', {name: 'Navigation'});
        expect(dialog.contains(document.activeElement)).toBe(true);
      });

      rerender(<Harness open={false} />);
      await waitFor(() => expect(trigger).toHaveFocus());
    });

    it('has no a11y violations', async () => {
      await expectNoA11yViolations(
        <MemoryRouter initialEntries={['/files']}>
          <AppNavDrawer
            open
            onClose={vi.fn()}
            isPathEnabled={() => true}
            contextualRail={<div>rail</div>}
          />
        </MemoryRouter>,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from CollapsibleRail.test.tsx ───
describe('CollapsibleRail', () => {
  beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));

  const rail = (
    <CollapsibleRail
      ariaLabel="Test rail"
      title="Section">
      <ul aria-label="Section list">
        <li>
          <button type="button">child action</button>
        </li>
      </ul>
    </CollapsibleRail>
  );

  function renderRail() {
    return render(
      <CollapsibleRail
        ariaLabel="Test rail"
        title="Section">
        <button type="button">child action</button>
      </CollapsibleRail>
    );
  }

  describe('CollapsibleRail', () => {
    it('renders the panel with its content + a collapse control, no reopen handle when expanded', () => {
      renderRail();
      const rail = screen.getByRole('complementary', {name: 'Test rail'});
      expect(within(rail).getByRole('button', {name: 'child action'})).toBeInTheDocument();

      const collapse = screen.getByRole('button', {name: /collapse sidebar/i});
      expect(collapse).toHaveAttribute('aria-expanded', 'true');
      expect(collapse).toHaveAttribute('aria-controls', rail.id);
      expect(screen.queryByRole('button', {name: /show sidebar/i})).not.toBeInTheDocument();
    });

    it('collapsing reveals a reopen handle wired to the rail; reopening hides it again', () => {
      renderRail();
      fireEvent.click(screen.getByRole('button', {name: /collapse sidebar/i}));

      const handle = screen.getByRole('button', {name: /show sidebar/i});
      expect(handle).toHaveAttribute('aria-expanded', 'false');
      expect(handle).toHaveAttribute('aria-controls', screen.getByRole('complementary', {name: 'Test rail'}).id);
      // The panel content is retained (not unmounted) so in-rail state survives.
      expect(
        within(screen.getByRole('complementary', {name: 'Test rail'})).getByRole('button', {name: 'child action'})
      ).toBeInTheDocument();

      fireEvent.click(handle);
      expect(screen.queryByRole('button', {name: /show sidebar/i})).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: /collapse sidebar/i})).toBeInTheDocument();
    });

    it('persists the collapsed choice under the single shared key', () => {
      renderRail();
      fireEvent.click(screen.getByRole('button', {name: /collapse sidebar/i}));
      expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('true');
    });

    it('starts collapsed when the shared key already says collapsed (carries across rails)', () => {
      localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, 'true');
      renderRail();
      expect(screen.getByRole('button', {name: /show sidebar/i})).toBeInTheDocument();
    });

    // SPEC-085 FR-004 / SPEC-045: no new axe violations in either rail state.
    it('has no axe violations when expanded', async () => {
      await expectNoA11yViolations(rail, COMPONENT_AXE_OPTIONS);
    });

    it('has no axe violations when collapsed', async () => {
      localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, 'true');
      await expectNoA11yViolations(rail, COMPONENT_AXE_OPTIONS);
    });
  });
});

// ─── from PageLayout.test.tsx ───
describe('PageLayout', () => {
  afterEach(cleanup);

  describe('PageLayout', () => {
    it('renders the title as the sole <h1> inside the <main id="main"> landmark', () => {
      render(
        <PageLayout title="Notifications">
          <p>body</p>
        </PageLayout>
      );
      const main = screen.getByRole('main');
      expect(main).toHaveAttribute('id', 'main');
      const headings = screen.getAllByRole('heading', {level: 1});
      expect(headings).toHaveLength(1);
      expect(headings[0]).toHaveTextContent('Notifications');
      expect(screen.getByText('body')).toBeInTheDocument();
    });

    it('renders the subtitle and actions when provided, and omits them otherwise', () => {
      const {rerender} = render(
        <PageLayout
          title="Connections"
          subtitle="Spaces you belong to"
          actions={<button type="button">New</button>}>
          body
        </PageLayout>
      );
      expect(screen.getByText('Spaces you belong to')).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'New'})).toBeInTheDocument();

      rerender(<PageLayout title="Connections">body</PageLayout>);
      expect(screen.queryByText('Spaces you belong to')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'New'})).not.toBeInTheDocument();
    });

    it('appends contentClassName to the content column', () => {
      render(
        <PageLayout
          title="T"
          contentClassName="max-w-[760px] gap-2">
          <span>child</span>
        </PageLayout>
      );
      const content = screen.getByText('child').parentElement!;
      expect(content.className).toContain('max-w-[760px]');
      expect(content.className).toContain('gap-2');
    });

    // ── SPEC-102: opt-in stacked mobile header ─────────────────────────────────

    it('keeps the inline single-row header by default (Connections/Help unaffected)', () => {
      render(
        <PageLayout
          title="Connections"
          actions={<button type="button">New</button>}>
          body
        </PageLayout>
      );
      const header = screen.getByRole('heading', {level: 1}).closest('div')!.parentElement!;
      expect(header).toHaveClass('flex', 'items-center');
      expect(header).not.toHaveClass('flex-col');
    });

    it('stacks the header below tablet when stackActionsOnMobile is set', () => {
      render(
        <PageLayout
          title="Notifications"
          stackActionsOnMobile
          actions={<button type="button">Mark all read</button>}>
          body
        </PageLayout>
      );
      const header = screen.getByRole('heading', {level: 1}).closest('div')!.parentElement!;
      expect(header).toHaveClass('flex-col', 'tablet:flex-row', 'tablet:items-center');
      const actions = screen.getByRole('button', {name: 'Mark all read'}).parentElement!;
      expect(actions).toHaveClass('flex-wrap', 'tablet:flex-none');
    });
  });
});

// ─── from PrimaryNav.test.tsx ───
describe('PrimaryNav', () => {
  describe('PrimaryNav (SPEC-035 + SPEC-052)', () => {
    it('renders Files, Query, Connections and Data quality tabs with their routes', () => {
      render(
        <MemoryRouter>
          <PrimaryNav isPathEnabled={() => true} />
        </MemoryRouter>
      );
      expect(screen.getByRole('link', {name: 'Files'})).toHaveAttribute('href', '/files');
      expect(screen.getByRole('link', {name: 'Query'})).toHaveAttribute('href', '/query');
      expect(screen.getByRole('link', {name: 'Connections'})).toHaveAttribute('href', '/connections');
      // SPEC-123 FR-004: the runs dashboard is a primary destination, after Connections.
      expect(screen.getByRole('link', {name: 'Data quality'})).toHaveAttribute('href', '/data-quality');
    });

    it('orders Data quality last, after Connections', () => {
      render(
        <MemoryRouter>
          <PrimaryNav isPathEnabled={() => true} />
        </MemoryRouter>
      );
      expect(screen.getAllByRole('link').map((link) => link.textContent)).toEqual([
        'Files',
        'Query',
        // SPEC-179: beside Query, whose workspace it shares a catalog with — not appended
        // last, which would put it after the two administrative destinations.
        'Data Explorer',
        'Connections',
        'Data quality'
      ]);
    });

    it('marks the Data quality tab active on its own route', () => {
      render(
        <MemoryRouter initialEntries={['/data-quality']}>
          <PrimaryNav isPathEnabled={() => true} />
        </MemoryRouter>
      );
      expect(screen.getByRole('link', {name: 'Data quality'})).toHaveAttribute('aria-current', 'page');
    });

    it('marks the active tab via aria-current', () => {
      render(
        <MemoryRouter initialEntries={['/connections']}>
          <PrimaryNav isPathEnabled={() => true} />
        </MemoryRouter>
      );
      expect(screen.getByRole('link', {name: 'Connections'})).toHaveAttribute('aria-current', 'page');
    });
  });
});

// ─── from Sidebar.test.tsx ───
describe('Sidebar', () => {
  const personal: Connection = {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'};
  const activeShared: Connection = {
    id: 'marketing_data',
    label: 'marketing_data',
    database: 'marketing_data',
    kind: 'shared',
    status: 'active',
    role: 'member'
  };
  const pendingShared: Connection = {
    id: 'sales_2026',
    label: 'sales_2026',
    database: 'sales_2026',
    kind: 'shared',
    status: 'provisioning',
    role: 'owner'
  };

  const renderSidebar = (connections: Connection[], activeSpaceId = 'personal', onSelectSpace = vi.fn()) =>
    render(
      <MemoryRouter initialEntries={['/files']}>
        <Sidebar
          connections={connections}
          activeSpaceId={activeSpaceId}
          onSelectSpace={onSelectSpace}
        />
      </MemoryRouter>
    );

  describe('Sidebar (SPEC-057)', () => {
    it('lists the personal space (by username) plus shared connections', () => {
      renderSidebar([personal, activeShared]);
      expect(screen.getByText('Spaces')).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /alice/i})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /marketing_data/i})).toBeInTheDocument();
    });

    it('marks the active space with aria-current', () => {
      renderSidebar([personal, activeShared], 'marketing_data');
      expect(screen.getByRole('button', {name: /marketing_data/i})).toHaveAttribute('aria-current', 'true');
      expect(screen.getByRole('button', {name: /alice/i})).not.toHaveAttribute('aria-current');
    });

    it('selecting a usable space calls onSelectSpace with its id', () => {
      const onSelectSpace = vi.fn();
      renderSidebar([personal, activeShared], 'personal', onSelectSpace);
      fireEvent.click(screen.getByRole('button', {name: /marketing_data/i}));
      expect(onSelectSpace).toHaveBeenCalledWith('marketing_data');
    });

    it('renders provisioning/failed shared connections disabled with their status', () => {
      const onSelectSpace = vi.fn();
      renderSidebar([personal, pendingShared], 'personal', onSelectSpace);
      const btn = screen.getByRole('button', {name: /sales_2026/i});
      expect(btn).toBeDisabled();
      expect(screen.getByText('Provisioning…')).toBeInTheDocument();
      fireEvent.click(btn);
      expect(onSelectSpace).not.toHaveBeenCalled();
    });

    it('a personal-only user sees just their own space', () => {
      renderSidebar([personal]);
      // Exactly one space entry (the collapse control is rail chrome, not a space).
      const list = screen.getByRole('list', {name: 'Spaces'});
      expect(within(list).getAllByRole('listitem')).toHaveLength(1);
      expect(screen.getByRole('button', {name: /alice/i})).toBeInTheDocument();
    });

    it('does not render a manage-connections link (managing lives on the Connections tab)', () => {
      renderSidebar([personal]);
      expect(screen.queryByRole('link', {name: /manage connections/i})).not.toBeInTheDocument();
    });
  });
});

// ─── from useRailCollapsed.test.ts ───
describe('useRailCollapsed', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('localStorage', memoryStorage());
  });

  describe('useRailCollapsed', () => {
    it('defaults to expanded when nothing is stored', () => {
      const {result} = renderHook(() => useRailCollapsed());
      expect(result.current.collapsed).toBe(false);
    });

    it('reads a persisted collapsed=true on mount', () => {
      localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, 'true');
      const {result} = renderHook(() => useRailCollapsed());
      expect(result.current.collapsed).toBe(true);
    });

    it('toggle flips the state and persists it under the shared key', () => {
      const {result} = renderHook(() => useRailCollapsed());
      act(() => result.current.toggle());
      expect(result.current.collapsed).toBe(true);
      expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('true');
      act(() => result.current.toggle());
      expect(result.current.collapsed).toBe(false);
      expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('false');
    });

    it('setCollapsed writes through to storage', () => {
      const {result} = renderHook(() => useRailCollapsed());
      act(() => result.current.setCollapsed(true));
      expect(result.current.collapsed).toBe(true);
      expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('true');
    });

    it('is shared across rails: a fresh instance reads the persisted value', () => {
      const a = renderHook(() => useRailCollapsed());
      act(() => a.result.current.setCollapsed(true));
      const b = renderHook(() => useRailCollapsed());
      expect(b.result.current.collapsed).toBe(true);
    });

    it('degrades to not-persisted (default expanded, no throw) when localStorage is unavailable', () => {
      vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
        throw new Error('storage denied');
      });
      vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
        throw new Error('storage denied');
      });
      const {result} = renderHook(() => useRailCollapsed());
      expect(result.current.collapsed).toBe(false); // default, not a throw
      act(() => result.current.toggle()); // must not throw despite setItem throwing
      expect(result.current.collapsed).toBe(true); // in-memory state still works
    });
  });
});

// ─── from ErrorBoundary.test.tsx ───
describe('ErrorBoundary', () => {
  function Boom({message = 'chunk load failed'}: {message?: string}): never {
    throw new Error(message);
  }

  // React logs every caught error to console.error regardless of the boundary. That
  // is React's own noise, not ours, and would bury a real failure in the output.
  let consoleError: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    consoleError.mockRestore();
    vi.unstubAllEnvs();
    cleanup();
  });

  describe('ErrorBoundary', () => {
    it('renders its children when nothing throws', () => {
      render(
        <ErrorBoundary>
          <p>the real page</p>
        </ErrorBoundary>
      );

      expect(screen.getByText('the real page')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('renders the fallback with a reload control when a child throws', () => {
      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      );

      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText('This part of the page didn’t load')).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Reload the page'})).toBeInTheDocument();
    });

    it('reloads the page when the control is activated', async () => {
      const reload = vi.fn();
      // jsdom's location.reload is not configurable in place; replace the accessor.
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: {...window.location, reload}
      });

      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      );
      await userEvent.click(screen.getByRole('button', {name: 'Reload the page'}));

      expect(reload).toHaveBeenCalledOnce();
    });

    it('never renders the thrown error’s message (SPEC-106: no raw text on a surface)', () => {
      render(
        <ErrorBoundary>
          <Boom message="TypeError: Failed to fetch dynamically imported module: https://d123.cloudfront.net/assets/QueryPage-a1b2c3.js" />
        </ErrorBoundary>
      );

      expect(screen.queryByText(/cloudfront/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Failed to fetch/i)).not.toBeInTheDocument();
      expect(document.body.textContent).not.toContain('QueryPage-a1b2c3.js');
    });

    it('leaves surrounding chrome intact — the boundary is scoped below it', () => {
      // The placement contract: RootLayout wraps the Outlet, not the Header, so a
      // page that throws still leaves the user navigation to somewhere else.
      render(
        <div>
          <header>
            <a href="/files">Files</a>
          </header>
          <ErrorBoundary>
            <Boom />
          </ErrorBoundary>
        </div>
      );

      expect(screen.getByRole('link', {name: 'Files'})).toBeInTheDocument();
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    it('renders a caller-supplied fallback instead of the default panel', () => {
      render(
        <ErrorBoundary fallback={<p>bespoke</p>}>
          <Boom />
        </ErrorBoundary>
      );

      expect(screen.getByText('bespoke')).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Reload the page'})).not.toBeInTheDocument();
    });

    it('logs the original in a dev build only, and never with console.error', () => {
      vi.stubEnv('DEV', true);
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

      render(
        <ErrorBoundary>
          <Boom message="chunk load failed" />
        </ErrorBoundary>
      );

      expect(warn).toHaveBeenCalled();
      expect(warn.mock.calls[0][0]).toContain('[ErrorBoundary]');
      warn.mockRestore();
    });

    it('logs nothing in a production build', () => {
      vi.stubEnv('DEV', false);
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      );

      expect(warn).not.toHaveBeenCalled();
      warn.mockRestore();
    });

    it('has no axe violations in the fallback state', async () => {
      // Checked on the DRIVEN container: `expectNoA11yViolations(ui)` re-renders from
      // scratch, and a fresh render of this tree throws again rather than handing axe
      // the fallback. Render first, then assert on what is actually on screen.
      const {container} = render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      );
      expect(screen.getByRole('alert')).toBeInTheDocument();

      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
    });
  });
});
