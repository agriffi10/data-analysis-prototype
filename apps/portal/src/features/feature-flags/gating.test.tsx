import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {Route, Routes} from 'react-router';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated, unauthenticated} from '../../test/authFixtures';
import {expectContainerHasNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {getFeatureFlags} from './featureFlags.service';
import type {FeatureFlags} from './featureFlags.types';

/**
 * The behaviours the registry walk cannot express (SPEC-163 FR-001/003/004/006/007).
 *
 * `gatedSurfaces.test.tsx` answers "does this control disappear?" for every registered
 * surface. This file answers the questions that are about the SHAPE of what is left: a nav
 * reduced to one tab, a route that must not fetch before it knows, a landing page that must
 * behave identically for a visitor who is not signed in, and the boundary that keeps
 * `useFeatureFlags` from being read directly all over the app.
 */
vi.mock('./featureFlags.service', async (importActual) => ({
  ...(await importActual<typeof import('./featureFlags.service')>()),
  getFeatureFlags: vi.fn()
}));
vi.mock('../notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));
vi.mock('../data-quality/dataQualityReport.service', async (importActual) => ({
  ...(await importActual<typeof import('../data-quality/dataQualityReport.service')>()),
  getQualityReport: vi.fn().mockResolvedValue({success: false, error: {message: 'no report'}})
}));
vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof import('../file-browser/fileBrowser.service')>()),
  ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
  listFiles: vi.fn(),
  getObjectMetadata: vi.fn(),
  getDownloadUrl: vi.fn()
}));
vi.mock('../file-browser/fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn().mockResolvedValue({success: true, data: {requestId: 'r1'}})
}));
import {Header} from '../../components/Header';
import {FeatureRoute} from '../../routes/FeatureRoute';
import LandingPage from '../../routes/LandingPage';
import DataQualityReportPage from '../../routes/DataQualityReportPage';
import {HelpPage} from '../help/HelpPage';
import {getQualityReport} from '../data-quality/dataQualityReport.service';
import {listFiles} from '../file-browser/fileBrowser.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {FileOpsInFlightProvider, UploadQueueProvider} from '../file-browser';
import FilesPage from '../../routes/FilesPage';

const ALL_ON: FeatureFlags = {
  files: true,
  query: true,
  sharedWorkspaces: true,
  dataQuality: true,
  dataExplorer: true,
  asyncFileOperations: true,
  resultsConversion: true
};
const opts = {auth: authenticated('alice'), seedFeatureFlags: false} as const;

function withFlags(overrides: Partial<FeatureFlags>) {
  vi.mocked(getFeatureFlags).mockResolvedValue({success: true, data: {...ALL_ON, ...overrides}});
}

/**
 * The report route inside a real `Routes` tree.
 *
 * Load-bearing, not ceremony: without a matching `<Route path>` the page's `useParams()` is
 * empty and it declines to fetch on its own — which would make every "no S3 request"
 * assertion below pass for the wrong reason. The positive control at the end of the group is
 * what caught exactly that.
 */
function renderReportRoute() {
  return renderWithProviders(
    <Routes>
      <Route
        path="/data-quality/:space/:requestId"
        element={
          <FeatureRoute flag="dataQuality">
            <DataQualityReportPage />
          </FeatureRoute>
        }
      />
    </Routes>,
    {...opts, route: '/data-quality/alice/req-1'}
  );
}

/** A read that never settles — the only way to hold the app in `status: 'loading'`. */
function withPendingFlags() {
  vi.mocked(getFeatureFlags).mockReturnValue(new Promise(() => {}));
}

beforeEach(() => {
  vi.clearAllMocks();
  // Defaults for BOTH boundaries, at the top level. The report route's fetch waits on
  // `connectionsLoading`, so a `readSharedConnectionsCache` left as a bare `vi.fn()` resolves
  // to `undefined` and whether the query ever becomes enabled is a race — which passed
  // locally and failed in CI, on the positive control rather than on an assertion.
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue({
    success: true,
    data: {version: 1, connections: []}
  } as never);
  vi.mocked(listFiles).mockResolvedValue({
    success: true,
    data: {files: [], folders: [], nextToken: undefined}
  } as never);
  withFlags({});
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('FR-003 — the reduced navigation', () => {
  it('renders a single tab correctly with four of five features off', async () => {
    withFlags({query: false, sharedWorkspaces: false, dataQuality: false, dataExplorer: false});
    renderWithProviders(<Header />, opts);

    const nav = await screen.findByRole('navigation', {name: 'Primary'});
    await waitFor(() => expect(within(nav).getAllByRole('link')).toHaveLength(1));
    expect(within(nav).getByRole('link', {name: 'Files'})).toBeInTheDocument();
  });

  it('leaves the reduced nav axe-clean', async () => {
    withFlags({query: false, sharedWorkspaces: false, dataQuality: false, dataExplorer: false});
    const {container} = renderWithProviders(<Header />, opts);

    await screen.findByRole('link', {name: 'Files'});
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('leaves no aria reference pointing at a tab it removed', async () => {
    // A dangling `aria-controls`/`aria-labelledby` is invisible on screen and breaks the
    // accessibility tree outright, so it cannot be caught by looking at the rendered page.
    withFlags({query: false, sharedWorkspaces: false, dataQuality: false, dataExplorer: false});
    const {container} = renderWithProviders(<Header />, opts);
    await screen.findByRole('link', {name: 'Files'});

    for (const attribute of ['aria-controls', 'aria-labelledby', 'aria-describedby']) {
      for (const element of container.querySelectorAll(`[${attribute}]`)) {
        for (const id of element.getAttribute(attribute)!.split(/\s+/)) {
          expect(document.getElementById(id), `${attribute}="${id}" points at nothing`).not.toBeNull();
        }
      }
    }
  });

  it('renders nothing gated at all while the flags are still loading', async () => {
    // FR-007: a tab that appears and then vanishes under the pointer is worse than one that
    // arrives a tick late.
    withPendingFlags();
    renderWithProviders(<Header />, opts);

    const nav = await screen.findByRole('navigation', {name: 'Primary'});
    expect(within(nav).queryAllByRole('link')).toHaveLength(0);
  });
});

describe('FR-004 — the unavailable route', () => {
  it('names the feature and offers one that IS enabled', async () => {
    withFlags({query: false});
    renderWithProviders(
      <FeatureRoute flag="query">
        <div>QUERY PAGE</div>
      </FeatureRoute>,
      opts
    );

    expect(await screen.findByRole('heading', {name: /Query/})).toBeInTheDocument();
    expect(screen.queryByText('QUERY PAGE')).not.toBeInTheDocument();
    // The link must never point at another unavailable page.
    expect(screen.getByRole('link', {name: 'Go to Files'})).toHaveAttribute('href', '/files');
  });

  it('names nothing and offers nothing when every feature is off', async () => {
    withFlags({files: false, query: false, sharedWorkspaces: false, dataQuality: false, dataExplorer: false});
    renderWithProviders(
      <FeatureRoute flag="query">
        <div>QUERY PAGE</div>
      </FeatureRoute>,
      opts
    );

    // It still NAMES the feature — "nothing to show" is the LANDING page's wording for a
    // signed-in visitor with nowhere to go (FR-007). Here the user asked for Query by name.
    expect(await screen.findByRole('heading', {name: /Query/})).toBeInTheDocument();
    // What is absent is the way out, because every destination would render this same page.
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });

  it('is NOT the 404 page — the route exists, the feature does not', async () => {
    withFlags({query: false});
    renderWithProviders(
      <FeatureRoute flag="query">
        <div>QUERY PAGE</div>
      </FeatureRoute>,
      opts
    );

    await screen.findByRole('heading', {name: /Query/});
    expect(screen.queryByText(/Page not found/i)).not.toBeInTheDocument();
  });

  it('makes NO S3 request for a report deep link with the flag off', async () => {
    // SPEC-113's rule, inherited: a disabled feature must not become an existence oracle for
    // someone else's report. The page fetches on mount, so this can only hold if the page
    // never mounts — which is why FeatureRoute renders a neutral state while loading rather
    // than rendering the page optimistically.
    withFlags({dataQuality: false});
    renderReportRoute();

    await screen.findByRole('heading', {name: /Data quality/});
    expect(getQualityReport).not.toHaveBeenCalled();
  });

  it('issues no request for the page even while the flags are still unknown', async () => {
    withPendingFlags();
    renderReportRoute();

    await screen.findByRole('status');
    expect(getQualityReport).not.toHaveBeenCalled();
  });

  it('DOES read the report when the flag is on — the control for the two assertions above', async () => {
    // Without this, "no request was made" passes just as well against a mock pointed at the
    // wrong module, which is exactly the mistake it is here to catch.
    withFlags({});
    renderReportRoute();

    await waitFor(() => expect(getQualityReport).toHaveBeenCalledWith(expect.anything(), 'alice', 'req-1'));
  });

  it('renders the page on the next render once the flag resolves the other way', async () => {
    // FR-004 AC4: no reload. The query refetches, the hook re-renders, the gate re-decides.
    withFlags({query: false});
    const {queryClient} = renderWithProviders(
      <FeatureRoute flag="query">
        <div>QUERY PAGE</div>
      </FeatureRoute>,
      opts
    );
    await screen.findByRole('heading', {name: /Query/});

    withFlags({});
    await queryClient.invalidateQueries();

    expect(await screen.findByText('QUERY PAGE')).toBeInTheDocument();
  });
});

describe('FR-006 — Help with features off', () => {
  it('renders with every feature off, listing only the ungated sections', async () => {
    withFlags({files: false, query: false, sharedWorkspaces: false, dataQuality: false, dataExplorer: false});
    renderWithProviders(<HelpPage />, opts);

    const rail = await screen.findByRole('complementary', {name: 'Guides navigation'});
    await waitFor(() => expect(within(rail).queryByRole('button', {name: /^Files/})).toBeNull());
    // Notifications is gated by nothing, so Help is never empty and never crashes.
    expect(within(rail).getByRole('button', {name: /^Notifications/})).toBeInTheDocument();
  });

  it('drops a gated guide from INSIDE an enabled section', async () => {
    // The two data-quality guides live in the Files section, which is why the registry gates
    // guides individually and not only whole sections.
    withFlags({dataQuality: false});
    renderWithProviders(<HelpPage />, opts);

    await screen.findByRole('complementary', {name: 'Guides navigation'});
    await waitFor(() => expect(screen.queryByRole('button', {name: /Check data quality/i})).toBeNull());
    expect(screen.getByRole('button', {name: /Upload files/i})).toBeInTheDocument();
  });
});

describe('FR-007 — the landing page', () => {
  it('is identical for a signed-out visitor whatever the flags say', async () => {
    // SPEC-162 gates the FETCH on a signed-in user, so a signed-out visitor's flags never
    // resolve. A landing page that waited on them would show a permanently empty shell.
    withPendingFlags();
    renderWithProviders(<LandingPage />, {auth: unauthenticated(), seedFeatureFlags: false});

    expect(await screen.findAllByRole('button', {name: /Sign in/i})).not.toHaveLength(0);
    expect(getFeatureFlags).not.toHaveBeenCalled();
  });

  it('offers the first enabled feature when Files is off', async () => {
    withFlags({files: false});
    renderWithProviders(<LandingPage />, opts);

    expect(await screen.findAllByRole('button', {name: 'Go to Query'})).not.toHaveLength(0);
    expect(screen.queryByRole('button', {name: 'Go to Dashboard'})).not.toBeInTheDocument();
  });

  it('renders the unavailable state when a signed-in visitor has no feature at all', async () => {
    withFlags({files: false, query: false, sharedWorkspaces: false, dataQuality: false, dataExplorer: false});
    renderWithProviders(<LandingPage />, opts);

    expect(await screen.findByRole('heading', {name: 'Nothing to show'})).toBeInTheDocument();
  });

  it('shows Go to Dashboard for a signed-in visitor with Files on', async () => {
    // The surface exists ONLY for an authenticated visitor, so an unauthenticated-only test
    // would pass while shipping it visible.
    renderWithProviders(<LandingPage />, opts);

    expect(await screen.findAllByRole('button', {name: 'Go to Dashboard'})).not.toHaveLength(0);
  });
});

describe('FR-005/FR-007 — fallback is indistinguishable from all-on', () => {
  it('shows every tab when the document could not be read at all', async () => {
    vi.mocked(getFeatureFlags).mockResolvedValue({success: false, error: {message: 'unreadable'}});
    renderWithProviders(<Header />, opts);

    const nav = await screen.findByRole('navigation', {name: 'Primary'});
    await waitFor(() => expect(within(nav).getAllByRole('link')).toHaveLength(5));
  });
});

describe('FR-001 — one sanctioned door', () => {
  // `useFeature` / `useFeatureSet` / `FeatureGate` are how app code asks. Reaching past them
  // into `useFeatureFlags` is how a fifth consumer ends up gating on a slightly different
  // condition — someone forgets that `'loading'` must read as OFF, and a tab flickers or a
  // page fetches before the answer arrives. Enforced by reading the source, because the
  // convention is exactly what an urgent change forgets.
  const SOURCES = import.meta.glob('../../**/*.{ts,tsx}', {
    query: '?raw',
    import: 'default',
    eager: true
  }) as Record<string, string>;

  // Vite keys a glob relative to THIS file, so the feature's own siblings come back as
  // `./useFeature.ts` rather than carrying `/feature-flags/` in the path — excluding only the
  // directory name would have left the feature reporting itself.
  const outside = Object.entries(SOURCES).filter(
    ([path]) =>
      !path.startsWith('./') &&
      !path.includes('/feature-flags/') &&
      !path.includes('.test.') &&
      !path.includes('/test/')
  );

  it('found the files it claims to check', () => {
    expect(outside.length).toBeGreaterThan(100);
  });

  it('no module outside the feature reads useFeatureFlags directly', () => {
    const offenders = outside.filter(([, source]) => /\buseFeatureFlags\b/.test(source)).map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});

describe('FR-005 — the ?space= deep link with shared workspaces off', () => {
  // The mechanism the AC calls out by name, and it shipped with no coverage of its own until
  // review said so. The point is the DIFFERENCE from `fellBack`: a space that cannot be
  // resolved raises "That shared space is no longer available", which would be a false
  // statement about a space that is perfectly fine and returns the moment the flag flips.
  it('resolves to the personal space, with no banner and no shared-bucket read', async () => {
    vi.mocked(readSharedConnectionsCache).mockResolvedValue({
      success: true,
      data: {version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]}
    } as never);
    withFlags({sharedWorkspaces: false});

    renderWithProviders(
      <UploadQueueProvider>
        <FileOpsInFlightProvider>
          <FilesPage />
        </FileOpsInFlightProvider>
      </UploadQueueProvider>,
      {...opts, route: '/files?space=teamspace'}
    );

    await screen.findByRole('button', {name: 'New folder'});
    await waitFor(() => expect(listFiles).toHaveBeenCalled());

    const buckets = vi.mocked(listFiles).mock.calls.map((call) => call[0]);
    expect(buckets).not.toContain('shared-space');
    expect(screen.queryByText(/no longer available/i)).not.toBeInTheDocument();
  });

  it('DOES resolve the space when the flag is on — the control for the assertion above', async () => {
    vi.mocked(readSharedConnectionsCache).mockResolvedValue({
      success: true,
      data: {version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]}
    } as never);
    withFlags({});

    renderWithProviders(
      <UploadQueueProvider>
        <FileOpsInFlightProvider>
          <FilesPage />
        </FileOpsInFlightProvider>
      </UploadQueueProvider>,
      {...opts, route: '/files?space=teamspace'}
    );

    await waitFor(() => {
      const buckets = vi.mocked(listFiles).mock.calls.map((call) => call[0]);
      expect(buckets).toContain('shared-space');
    });
    // NOT asserted here: that the personal space is never listed first. It is — but because
    // the CONNECTIONS cache resolves after the first paint (`useFileSpace` falls back to
    // personal while `isLoading`), which predates this spec and belongs to SPEC-052/057.
    // What SPEC-163 owes is that the FLAGS never become a second cause of it, which is why
    // `FilesPage` ignores `?space=` only once the flag answer is known rather than while it
    // is in flight. Measuring the flags' contribution separately is what this control is for.
    expect(vi.mocked(listFiles).mock.calls.length).toBeLessThanOrEqual(2);
  });
});
