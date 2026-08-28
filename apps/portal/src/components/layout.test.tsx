import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, renderHook, screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router';
import {AppNavDrawer} from './AppNavDrawer';
import {CollapsibleRail} from './CollapsibleRail';
import {RAIL_COLLAPSED_STORAGE_KEY, useRailCollapsed} from './useRailCollapsed';
import {memoryStorage} from '../test/storage';
import {ErrorBoundary} from './ErrorBoundary';

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

  describe('AppNavDrawer', () => {
    it('renders nothing when closed', () => {
      renderDrawer({open: false});
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
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
  });
});

// ─── from CollapsibleRail.test.tsx ───
describe('CollapsibleRail', () => {
  beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));

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
  });
});

// ─── from useRailCollapsed.test.ts ───
describe('useRailCollapsed', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('localStorage', memoryStorage());
  });

  describe('useRailCollapsed', () => {
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
  });
});
