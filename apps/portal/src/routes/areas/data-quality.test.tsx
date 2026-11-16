import {afterEach, beforeEach, describe, it, expect, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {authenticated} from '../../test/authFixtures';
import {createTestQueryClient} from '../../test/renderWithProviders';
import {traverse} from '../../test/nextNavigation';
import {connectionKeys} from '../../features/connections/connectionKeys';
import {getRunsIndex} from '../../features/data-quality/dataQualityRuns.service';
import {getQualityReport} from '../../features/data-quality/dataQualityReport.service';
import {csvReport} from '../../features/data-quality/reportFixtures';
import type {DataQualityRunSummary} from '../../features/data-quality/dataQuality.types';
import {FEATURE_FLAG_DEFAULTS} from '../../features/feature-flags/featureFlagDefaults';
import {getFeatureFlags} from '../../features/feature-flags/featureFlags.service';
import type {FeatureFlags} from '../../features/feature-flags/featureFlags.types';
import {enqueueNotificationAction, getNotifications} from '../../features/notifications/notifications.service';
import {readSharedConnectionsCache} from '../../features/shared-spaces/sharedSpaces.service';
import type {SharedConnectionsCache} from '../../features/shared-spaces/sharedSpaces.types';
import type {ServiceResult} from '../../types/service.types';

/** Whether the two pages render as stand-ins; the App Router tests below switch them off for the real views. */
const standIns = vi.hoisted(() => ({on: true}));
vi.mock('../DataQualityPage', async (importOriginal) => {
  const {default: Page} = await importOriginal<typeof import('../DataQualityPage')>();
  return {default: () => (standIns.on ? <h1>Data quality runs</h1> : <Page />)};
});
vi.mock('../DataQualityReportPage', async (importOriginal) => {
  const {default: Page} = await importOriginal<typeof import('../DataQualityReportPage')>();
  return {default: () => (standIns.on ? <h1>A data quality report</h1> : <Page />)};
});

describe('the data-quality area', () => {
  it.each([
    ['/data-quality', 'Data quality runs'],
    ['/data-quality/alice/req-1', 'A data quality report']
  ])('serves %s inside the shell', async (path, heading) => {
    renderApp(path, {auth: authenticated('alice')});

    expect(await screen.findByRole('heading', {name: heading})).toBeInTheDocument();
    expect(screen.getByRole('link', {name: 'Files'})).toBeInTheDocument();
  });
});

vi.mock('../../features/data-quality/dataQualityRuns.service', async (importActual) => ({
  ...(await importActual<typeof import('../../features/data-quality/dataQualityRuns.service')>()),
  getRunsIndex: vi.fn()
}));
vi.mock('../../features/data-quality/dataQualityReport.service', async (importActual) => ({
  ...(await importActual<typeof import('../../features/data-quality/dataQualityReport.service')>()),
  getQualityReport: vi.fn()
}));
vi.mock('../../features/data-quality/dataQuality.service', async (importActual) => ({
  ...(await importActual<typeof import('../../features/data-quality/dataQuality.service')>()),
  enqueueQualityCheck: vi.fn()
}));
vi.mock('../../features/shared-spaces/sharedSpaces.service', async (importActual) => ({
  ...(await importActual<typeof import('../../features/shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('../../features/notifications/notifications.service', async (importActual) => ({
  ...(await importActual<typeof import('../../features/notifications/notifications.service')>()),
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));
vi.mock('../../features/feature-flags/featureFlags.service', async (importActual) => ({
  ...(await importActual<typeof import('../../features/feature-flags/featureFlags.service')>()),
  getFeatureFlags: vi.fn()
}));

const NO_SPACES: SharedConnectionsCache = {version: 1, connections: []};
const REPORT_LINK = /Data quality check finished/;

/** A completed run in alice's own space, as the runs index lists it. */
const RUN: DataQualityRunSummary = {
  requestId: 'req-1',
  space: 'alice',
  location: 'alice/sales/',
  format: 'csv',
  verdict: 'issues_found',
  fileCount: 3,
  hasIncompleteFigures: false,
  timestamp: '2026-07-20T10:00:00Z'
};

/** A notification linking to a report, as the data-quality plane writes one. */
function inboxLinkingTo(link: string) {
  return {
    success: true as const,
    data: [{id: 'n1', message: 'Data quality check finished', read: false, timestamp: '2026-07-20T10:05:00Z', link}]
  };
}

/** A promise the test settles, for a read whose ordering is the subject. */
function deferred<T>() {
  let settle: (value: T) => void = () => {};
  const promise = new Promise<T>((resolve) => (settle = resolve));
  return {promise, settle};
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue({success: true, data: NO_SPACES});
  vi.mocked(getRunsIndex).mockResolvedValue({success: true, data: []});
  vi.mocked(getQualityReport).mockResolvedValue({success: true, data: csvReport()});
  vi.mocked(getNotifications).mockResolvedValue({success: true, data: []});
  vi.mocked(enqueueNotificationAction).mockResolvedValue({success: true, data: undefined});
  vi.mocked(getFeatureFlags).mockResolvedValue({success: true, data: FEATURE_FLAG_DEFAULTS});
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('the data-quality pages on the App Router', () => {
  const mockRuns = vi.mocked(getRunsIndex);
  const mockReport = vi.mocked(getQualityReport);
  const mockCache = vi.mocked(readSharedConnectionsCache);
  const mockInbox = vi.mocked(getNotifications);

  beforeEach(() => {
    standIns.on = false;
  });

  afterEach(() => {
    standIns.on = true;
  });

  it('lists the runs, opens a run’s report from its row, and comes back to the list on Back', async () => {
    mockRuns.mockImplementation(async (_bucket, space) => ({success: true, data: space === 'alice' ? [RUN] : []}));
    const {user} = renderApp('/data-quality', {auth: authenticated('alice')});

    await user.click(await screen.findByRole('link', {name: /Data quality check on alice\/sales\//}));

    expect(await screen.findByRole('heading', {level: 1, name: 'Data quality report'})).toBeInTheDocument();
    expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
    expect(mockReport).toHaveBeenCalledWith('user-space', 'alice', 'req-1');

    await traverse(-1);

    expect(await screen.findByRole('link', {name: /Data quality check on alice\/sales\//})).toBeInTheDocument();
  });

  it('opens a deep link whose space is percent-encoded as the space it names', async () => {
    mockCache.mockResolvedValue({
      success: true,
      data: {version: 1, connections: [{name: 'a@b c', role: 'member', status: 'active'}]}
    });
    renderApp('/data-quality/a%40b%20c/req-1', {
      auth: authenticated('alice'),
      featureFlags: {sharedWorkspaces: true}
    });

    expect(await screen.findByRole('heading', {level: 1, name: 'Data quality report'})).toBeInTheDocument();
    expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
    expect(mockReport).toHaveBeenCalledWith('shared-space', 'a@b c', 'req-1');
  });

  it('renders the unavailable page with data quality off, and reads no report', async () => {
    renderApp('/data-quality/alice/req-1', {
      auth: authenticated('alice'),
      featureFlags: {dataQuality: false}
    });

    expect(await screen.findByRole('heading', {name: 'Data quality isn’t available'})).toBeInTheDocument();
    // A personal report is read as the page mounts; give a mounted page the time to have read.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(mockReport).not.toHaveBeenCalled();
  });

  it('reads no report until a late flag answers, and reads it once data quality is on', async () => {
    const flags = deferred<ServiceResult<FeatureFlags>>();
    vi.mocked(getFeatureFlags).mockReturnValue(flags.promise);
    renderApp('/data-quality/alice/req-1', {auth: authenticated('alice'), seedFeatureFlags: false});

    // Loaded, the page shows the gate's loader or, were the gate open early, starts a read; which is the subject.
    await waitFor(() => expect(screen.queryByText('Loading…') !== null || mockReport.mock.calls.length > 0).toBe(true));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(mockReport).not.toHaveBeenCalled();
    expect(screen.getByText('Loading…')).toBeInTheDocument();

    await act(async () => flags.settle({success: true, data: {...FEATURE_FLAG_DEFAULTS, dataQuality: true}}));

    await waitFor(() => expect(mockReport).toHaveBeenCalledWith('user-space', 'alice', 'req-1'));
    expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
  });

  it('waits for a read after the link before refusing a space the cached list lacks, and Back onto it reads nothing', async () => {
    // The list is cached and fresh, so nothing but the link's own wait reads it again.
    const queryClient = createTestQueryClient();
    queryClient.setQueryDefaults(connectionKeys.list('alice'), {gcTime: Infinity, staleTime: 30_000});
    queryClient.setQueryData(connectionKeys.list('alice'), NO_SPACES);
    mockInbox.mockResolvedValue(inboxLinkingTo('/data-quality/team-data/req-1'));
    const read = deferred<ServiceResult<SharedConnectionsCache>>();
    mockCache.mockReturnValue(read.promise);
    const {user} = renderApp('/notifications', {auth: authenticated('alice'), queryClient});

    await user.click(await screen.findByRole('link', {name: REPORT_LINK}));

    expect(await screen.findByText(/loading report/i)).toBeInTheDocument();
    expect(screen.queryByText('Report not available')).not.toBeInTheDocument();
    expect(mockCache).toHaveBeenCalledOnce();
    expect(mockReport).not.toHaveBeenCalled();

    await act(async () => read.settle({success: true, data: NO_SPACES}));
    expect(await screen.findByText('Report not available')).toBeInTheDocument();

    await act(async () => {
      const moved = new Promise((resolve) => window.addEventListener('popstate', resolve, {once: true}));
      await user.click(screen.getByRole('link', {name: 'Skip to main content'}));
      await moved;
    });
    expect(mockCache).toHaveBeenCalledOnce();

    await traverse(-1);

    expect(window.location.hash).toBe('');
    expect(screen.getByText('Report not available')).toBeInTheDocument();
    expect(mockCache).toHaveBeenCalledOnce();
    expect(mockReport).not.toHaveBeenCalled();
  });

  it('opens a report from a notification’s link, and Back returns to the notification', async () => {
    mockInbox.mockResolvedValue(inboxLinkingTo('/data-quality/alice/req-1'));
    const {user} = renderApp('/notifications', {auth: authenticated('alice')});

    await user.click(await screen.findByRole('link', {name: REPORT_LINK}));

    expect(await screen.findByRole('heading', {level: 1, name: 'Data quality report'})).toBeInTheDocument();
    expect(await screen.findByText('alice/sales/')).toBeInTheDocument();

    await traverse(-1);

    expect(await screen.findByRole('link', {name: REPORT_LINK})).toBeInTheDocument();
  });
});
