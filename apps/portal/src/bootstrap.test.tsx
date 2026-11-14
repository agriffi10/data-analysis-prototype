import {StrictMode, type ReactNode} from 'react';
import {render, screen} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';

/**
 * The boot: load the configuration, configure Amplify, then render the frame around the page.
 *
 * Every assertion here is about ORDER and REACH, which is what the production build turns into a
 * boot failure when it is wrong, and which no other test in the suite can see, because Vitest's
 * fallback answers every configuration read whether or not a document was ever loaded.
 */

const state = vi.hoisted(() => ({
  frameEvaluated: false,
  order: [] as string[]
}));

vi.mock('./AppFrame', () => {
  // Runs on IMPORT, so it stays false unless the dynamic import is actually reached.
  state.frameEvaluated = true;
  return {
    AppFrame: function AppFrameMock({children}: {children: ReactNode}) {
      state.order.push('render');
      return <div data-testid="app-frame">{children}</div>;
    }
  };
});

/** The page the root layout hands the boot, which must render only inside the frame. */
const PAGE = <p>the page</p>;

vi.mock('./lib/amplify', () => ({
  configureAmplify: () => state.order.push('configure'),
  isAmplifyConfigured: () => true
}));

/** A complete document, so the load succeeds unless a test says otherwise. */
function completeDocument(): Record<string, unknown> {
  return {
    version: 1,
    apiBaseUrl: 'https://api.portal.test',
    appUrl: 'https://portal.test',
    awsRegion: 'us-east-1',
    userSpaceBucket: 'user-space',
    cognitoUserPoolId: 'pool',
    cognitoUserPoolClientId: 'client',
    cognitoDomain: 'auth.test'
  };
}

function respondWith(body: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue({ok: true, status: 200, json: async () => body});
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** The boot module, fresh: its in-flight boot is module state, and each test boots once. */
async function freshBoot() {
  const {PortalBoot} = await import('./PortalBoot');
  return PortalBoot;
}

beforeEach(() => {
  state.frameEvaluated = false;
  state.order = [];
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  // `vi.spyOn` on an already-spied method hands back the SAME mock, so without this a console
  // line written by the previous test's boot is still in `mock.calls` when the next one reads it.
  vi.restoreAllMocks();
  vi.resetModules();
});

describe('the boot', () => {
  it('configures Amplify BEFORE the first render', async () => {
    // Asserted by call order rather than by reading the file: a boot that configures Amplify
    // after the first render produces a SOMETIMES-working sign-in, and a warm session never
    // exercises it, because the browser arrives already authenticated.
    respondWith(completeDocument());
    const PortalBoot = await freshBoot();

    render(<PortalBoot>{PAGE}</PortalBoot>);

    expect(await screen.findByTestId('app-frame')).toHaveTextContent('the page');
    expect(state.order).toEqual(['configure', 'render']);
  });

  it('fetches the document exactly once, even when React mounts it twice', async () => {
    // StrictMode replays every effect on mount, which is what a development build does to the
    // real page; a boot keyed to the effect would fetch and configure twice.
    const fetchMock = respondWith(completeDocument());
    const PortalBoot = await freshBoot();

    render(
      <StrictMode>
        <PortalBoot>{PAGE}</PortalBoot>
      </StrictMode>
    );

    expect(await screen.findByTestId('app-frame')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(state.order.filter((step) => step === 'configure')).toHaveLength(1);
  });

  it('renders the boot failure without importing AppFrame, and evaluates no config read on the way', async () => {
    // The test that can only pass because the boot reaches the app through `await import`. With a
    // static import, the graph is evaluated before the boot runs, so this would throw on the first
    // module-scope read instead of rendering, in a production build only.
    //
    // WHAT IT DOES NOT PROVE: `AppFrame` is mocked here, so the application graph behind it is
    // evaluated by nothing in this file. What is under test is the boot's OWN static graph. The page
    // never renders either: a page's view reads configuration, and only the frame waited for it.
    vi.stubEnv('MODE', 'production');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no document')));
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const PortalBoot = await freshBoot();

    render(<PortalBoot>{PAGE}</PortalBoot>);

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(state.frameEvaluated).toBe(false);
    expect(state.order).not.toContain('configure');
    expect(screen.queryByText('the page')).not.toBeInTheDocument();
    expect(error).toHaveBeenCalledOnce();
  });

  it('renders the boot failure when the app chunk cannot be loaded', async () => {
    // A deploy that replaces the hashed assets mid-boot rejects the dynamic import outright; the
    // alternative to this screen is a blank page and an unhandled rejection.
    respondWith(completeDocument());
    vi.doMock('./AppFrame', () => {
      throw new Error('chunk gone');
    });
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const PortalBoot = await freshBoot();

    render(<PortalBoot>{PAGE}</PortalBoot>);

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('the page')).not.toBeInTheDocument();
    expect(String(error.mock.calls[0][0])).toContain('(bootstrap)');
    vi.doUnmock('./AppFrame');
  });

  it('names the reason and the missing KEYS in the console, and no value', async () => {
    vi.stubEnv('MODE', 'production');
    const served = completeDocument();
    delete served.userSpaceBucket;
    respondWith(served);
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const PortalBoot = await freshBoot();

    render(<PortalBoot>{PAGE}</PortalBoot>);
    await vi.waitFor(() => expect(error).toHaveBeenCalled());

    const line = String(error.mock.calls[0][0]);
    expect(line).toContain('missing-required');
    expect(line).toContain('userSpaceBucket');
    // A key NAME is the only diagnostic an operator staring at a failed task has. A VALUE is the
    // deployed app printing its own configuration to a user's console.
    for (const value of Object.values(served)) {
      if (typeof value === 'string') expect(line).not.toContain(value);
    }
  });
});

describe('the boot module graph', () => {
  const BOOT = Object.values(
    import.meta.glob('./PortalBoot.tsx', {query: '?raw', import: 'default', eager: true})
  )[0] as string;

  /**
   * The whole point of the boundary. Adding a static import of `./AppFrame`, or of any provider,
   * evaluates the application graph before the document is fetched, which is a boot failure in
   * production and INVISIBLE under the test fallback, which answers every read.
   */
  const ALLOWED_STATIC_IMPORTS = ['react', './lib/amplify', './lib/runtimeConfig', './components/BootFailure'];

  it('reads its own source', () => {
    expect(BOOT).toContain('loadRuntimeConfig');
  });

  it('statically imports exactly the four modules that cannot wait', () => {
    // `export … from` evaluates its module exactly as an import does, so it counts as one. A
    // statement may span lines, but never runs through `(`, `=` or `;` before its specifier: an
    // `export function` or `export const` would otherwise read on to its first string literal.
    const imported = [...BOOT.matchAll(/^(?:import|export)\s[^'"(=;]*['"]([^'"]+)['"]/gm)].map(
      ([, specifier]) => specifier
    );

    expect(imported.slice().sort()).toEqual([...ALLOWED_STATIC_IMPORTS].sort());
  });

  it('reaches the application graph only through a dynamic import', () => {
    expect(BOOT).toMatch(/await import\(['"]\.\/AppFrame['"]\)/);
    expect(BOOT).not.toMatch(/^import .*['"]\.\/AppFrame['"]/m);
  });

  it('carries no bare side-effect import of Amplify', () => {
    // The set assertion above cannot catch this: `./lib/amplify` is a permitted member, so
    // `import './lib/amplify'` passes it while restoring the configure-at-import-time coupling
    // the boot exists to remove. Ordering is expressed by `await`, which no reorder can break.
    expect(BOOT).not.toMatch(/^import\s+['"]\.\/lib\/amplify['"]/m);
    expect(BOOT).toContain('configureAmplify()');
  });
});
