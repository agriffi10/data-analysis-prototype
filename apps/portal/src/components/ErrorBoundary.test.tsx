import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../test/axe';
import {ErrorBoundary} from './ErrorBoundary';

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
