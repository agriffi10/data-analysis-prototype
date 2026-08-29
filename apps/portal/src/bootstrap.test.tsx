import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';

/**
 * The bootstrap: load the configuration, configure Amplify, then render.
 *
 * Every assertion here is about ORDER and REACH, which is what the production build
 * turns into a boot failure when it is wrong — and which no other test in the suite can
 * see, because Vitest runs with `import.meta.env.DEV` true and the dev fallback answers
 * every read whether or not a document was ever loaded.
 */

const state = vi.hoisted(() => ({
  appRootEvaluated: false,
  order: [] as string[],
  rendered: [] as string[],
  configured: true
}));

vi.mock('./AppRoot', () => {
  // Runs on IMPORT, so it stays false unless the dynamic import is actually reached.
  state.appRootEvaluated = true;
  return {
    AppRoot: function AppRootMock() {
      return <div data-testid="app-root" />;
    }
  };
});

vi.mock('./lib/amplify', () => ({
  configureAmplify: () => state.order.push('configure'),
  isAmplifyConfigured: () => state.configured
}));

const renderSpy = vi.fn((element: {type?: {name?: string}}) => {
  state.order.push('render');
  state.rendered.push(element?.type?.name ?? 'unknown');
});
vi.mock('react-dom/client', () => ({
  createRoot: () => ({render: renderSpy, unmount: vi.fn()})
}));

/** A complete document, so the load succeeds unless a test says otherwise. */
function completeDocument(): Record<string, unknown> {
  return {
    version: 1,
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

beforeEach(() => {
  state.appRootEvaluated = false;
  state.order = [];
  state.rendered = [];
  state.configured = true;
  renderSpy.mockClear();
  document.body.innerHTML = '<div id="root"></div>';
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  // `vi.spyOn` on an already-spied method hands back the SAME mock, so without this a
  // console line written by the previous test's bootstrap is still in `mock.calls` when
  // the next one reads `calls[0]`.
  vi.restoreAllMocks();
  vi.resetModules();
});

describe('the bootstrap', () => {
  it('configures Amplify BEFORE the first render', async () => {
    // Asserted by call order rather than by reading the file: a bootstrap that configures
    // Amplify after the first render produces a SOMETIMES-working sign-in, and a warm
    // session never exercises it — the browser arrives already authenticated.
    respondWith(completeDocument());

    await import('./main');
    await vi.waitFor(() => expect(state.order).toContain('render'));

    expect(state.order).toEqual(['configure', 'render']);
  });

  it('fetches the document exactly once per page load', async () => {
    // Before `createRoot(...).render(...)`, so StrictMode's double-render cannot
    // double-fetch.
    const fetchMock = respondWith(completeDocument());

    await import('./main');
    await vi.waitFor(() => expect(renderSpy).toHaveBeenCalled());

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('renders the app once the document resolves', async () => {
    respondWith(completeDocument());

    await import('./main');
    await vi.waitFor(() => expect(renderSpy).toHaveBeenCalled());

    expect(state.rendered).toEqual(['AppRootMock']);
  });

  it('renders the boot failure without importing AppRoot, and evaluates no config read on the way', async () => {
    // The test that can only pass because `main.tsx` reaches the app through
    // `await import`. With a static import, the graph is evaluated before the first
    // statement runs — so this would throw on the first module-scope read instead of
    // rendering, in a production build only.
    //
    // WHAT IT DOES NOT PROVE: `AppRoot` is mocked here, so the application graph behind
    // it is evaluated by nothing in this file. What is under test is main.tsx's OWN
    // static graph — measured: a module-scope `configValue` added to `lib/errorMessages`
    // (which `BootFailure` pulls in) reddens this test, while one added inside AppRoot's
    // tree does not, and does not need to: that tree is only ever evaluated after the
    // document is in hand.
    vi.stubEnv('DEV', false);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no document')));
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});

    await import('./main');
    await vi.waitFor(() => expect(renderSpy).toHaveBeenCalled());

    expect(state.rendered).toEqual(['BootFailure']);
    expect(state.appRootEvaluated).toBe(false);
    expect(state.order).not.toContain('configure');
    expect(error).toHaveBeenCalledOnce();
  });

  it('names the reason and the missing KEYS in the console, and no value', async () => {
    vi.stubEnv('DEV', false);
    const served = completeDocument();
    delete served.userSpaceBucket;
    respondWith(served);
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});

    await import('./main');
    await vi.waitFor(() => expect(error).toHaveBeenCalled());

    const line = String(error.mock.calls[0][0]);
    expect(line).toContain('missing-required');
    expect(line).toContain('userSpaceBucket');
    // A key NAME is the only diagnostic an operator staring at a failed task has. A
    // VALUE is the deployed app printing its own configuration to a user's console.
    for (const value of Object.values(served)) {
      if (typeof value === 'string') expect(line).not.toContain(value);
    }
  });
});

describe('the bootstrap module graph', () => {
  const MAIN = Object.values(
    import.meta.glob('./main.tsx', {query: '?raw', import: 'default', eager: true})
  )[0] as string;

  /**
   * The whole point of the boundary. Re-adding `import App from './App.tsx'` — or any
   * provider beside it — evaluates the application graph before the document is
   * fetched, which is a boot failure in production and INVISIBLE in dev, where the
   * fallback answers every read.
   */
  const ALLOWED_STATIC_IMPORTS = [
    'react-dom/client',
    './index.css',
    './lib/amplify',
    './lib/runtimeConfig',
    './components/BootFailure'
  ];

  it('reads its own source', () => {
    expect(MAIN).toContain('createRoot');
  });

  it('statically imports exactly the five modules that cannot wait', () => {
    const imported = [...MAIN.matchAll(/^import\s[^'"]*['"]([^'"]+)['"]/gm)].map(([, specifier]) => specifier);

    expect(imported.slice().sort()).toEqual([...ALLOWED_STATIC_IMPORTS].sort());
  });

  it('reaches the application graph only through a dynamic import', () => {
    expect(MAIN).toMatch(/await import\(['"]\.\/AppRoot['"]\)/);
    expect(MAIN).not.toMatch(/^import .*['"]\.\/AppRoot['"]/m);
  });

  it('carries no bare side-effect import of Amplify', () => {
    // The set assertion above cannot catch this: `./lib/amplify` is a permitted member,
    // so `import './lib/amplify'` with an ordering comment passes it while restoring the
    // configure-at-import-time coupling the bootstrap exists to remove. Ordering is
    // expressed by `await`, which no import reorder can break.
    expect(MAIN).not.toMatch(/^import\s+['"]\.\/lib\/amplify['"]/m);
    expect(MAIN).toContain('configureAmplify()');
  });
});
