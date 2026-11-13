import {StrictMode} from 'react';
import {render, screen} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';

/**
 * The boot: load the configuration, configure Amplify, then render the app.
 *
 * Every assertion here is about ORDER and REACH, which is what the production build turns into a
 * boot failure when it is wrong, and which no other test in the suite can see, because Vitest's
 * fallback answers every configuration read whether or not a document was ever loaded.
 */

const state = vi.hoisted(() => ({
  appRootEvaluated: false,
  order: [] as string[]
}));

vi.mock('./AppRoot', () => {
  // Runs on IMPORT, so it stays false unless the dynamic import is actually reached.
  state.appRootEvaluated = true;
  return {
    AppRoot: function AppRootMock() {
      state.order.push('render');
      return <div data-testid="app-root" />;
    }
  };
});

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
  state.appRootEvaluated = false;
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

    render(<PortalBoot />);

    expect(await screen.findByTestId('app-root')).toBeInTheDocument();
    expect(state.order).toEqual(['configure', 'render']);
  });

  it('fetches the document exactly once, even when React mounts it twice', async () => {
    // StrictMode replays every effect on mount, which is what a development build does to the
    // real page; a boot keyed to the effect would fetch and configure twice.
    const fetchMock = respondWith(completeDocument());
    const PortalBoot = await freshBoot();

    render(
      <StrictMode>
        <PortalBoot />
      </StrictMode>
    );

    expect(await screen.findByTestId('app-root')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(state.order.filter((step) => step === 'configure')).toHaveLength(1);
  });

  it('renders the boot failure without importing AppRoot, and evaluates no config read on the way', async () => {
    // The test that can only pass because the boot reaches the app through `await import`. With a
    // static import, the graph is evaluated before the boot runs, so this would throw on the first
    // module-scope read instead of rendering, in a production build only.
    //
    // WHAT IT DOES NOT PROVE: `AppRoot` is mocked here, so the application graph behind it is
    // evaluated by nothing in this file. What is under test is the boot's OWN static graph.
    vi.stubEnv('MODE', 'production');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no document')));
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const PortalBoot = await freshBoot();

    render(<PortalBoot />);

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(state.appRootEvaluated).toBe(false);
    expect(state.order).not.toContain('configure');
    expect(error).toHaveBeenCalledOnce();
  });

  it('names the reason and the missing KEYS in the console, and no value', async () => {
    vi.stubEnv('MODE', 'production');
    const served = completeDocument();
    delete served.userSpaceBucket;
    respondWith(served);
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const PortalBoot = await freshBoot();

    render(<PortalBoot />);
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
   * The whole point of the boundary. Re-adding `import {App} from './App.tsx'`, or any provider
   * beside it, evaluates the application graph before the document is fetched, which is a boot
   * failure in production and INVISIBLE under the test fallback, which answers every read.
   */
  const ALLOWED_STATIC_IMPORTS = ['react', './lib/amplify', './lib/runtimeConfig', './components/BootFailure'];

  it('reads its own source', () => {
    expect(BOOT).toContain('loadRuntimeConfig');
  });

  it('statically imports exactly the four modules that cannot wait', () => {
    const imported = [...BOOT.matchAll(/^import\s[^'"]*['"]([^'"]+)['"]/gm)].map(([, specifier]) => specifier);

    expect(imported.slice().sort()).toEqual([...ALLOWED_STATIC_IMPORTS].sort());
  });

  it('reaches the application graph only through a dynamic import', () => {
    expect(BOOT).toMatch(/await import\(['"]\.\/AppRoot['"]\)/);
    expect(BOOT).not.toMatch(/^import .*['"]\.\/AppRoot['"]/m);
  });

  it('carries no bare side-effect import of Amplify', () => {
    // The set assertion above cannot catch this: `./lib/amplify` is a permitted member, so
    // `import './lib/amplify'` passes it while restoring the configure-at-import-time coupling
    // the boot exists to remove. Ordering is expressed by `await`, which no reorder can break.
    expect(BOOT).not.toMatch(/^import\s+['"]\.\/lib\/amplify['"]/m);
    expect(BOOT).toContain('configureAmplify()');
  });
});

describe('the catch-all route', () => {
  // Globbed one level down and filtered, because the folder's brackets are glob syntax; the route's
  // own tests are not part of the route.
  const ROUTE = Object.fromEntries(
    Object.entries(
      import.meta.glob('./app/*/*.tsx', {query: '?raw', import: 'default', eager: true}) as Record<string, string>
    ).filter(([file]) => file.startsWith('./app/[[...slug]]/') && !file.includes('.test.'))
  );

  it('reads both of its files', () => {
    expect(Object.keys(ROUTE).sort()).toEqual(['./app/[[...slug]]/PortalMount.tsx', './app/[[...slug]]/page.tsx']);
  });

  it('reaches the application only through the client-only dynamic import', () => {
    // A static import of the app here would evaluate it on the server, where the boot's
    // configuration and the browser's storage do not exist; `ssr: false` is what keeps it off.
    for (const [file, source] of Object.entries(ROUTE)) {
      const imported = [...source.matchAll(/^import\s[^'"]*['"]([^'"]+)['"]/gm)].map(([, specifier]) => specifier);
      expect(imported.length, `${file} imports nothing`).toBeGreaterThan(0);
      for (const specifier of imported) {
        expect(['react', 'next/dynamic', './PortalMount'], `${file} imports ${specifier}`).toContain(specifier);
      }
    }
    const mount = ROUTE['./app/[[...slug]]/PortalMount.tsx'];
    expect(mount).toMatch(/import\(['"]\.\.\/\.\.\/PortalBoot['"]\)/);
    expect(mount).toMatch(/ssr:\s*false/);
  });
});
