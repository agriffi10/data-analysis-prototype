import {useEffect} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor, within} from '@testing-library/react';
import type {UserEvent} from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {GATED_SURFACES, firstEnabledDestination, navDestination} from './gatedSurfaces';
import {FEATURE_FLAG_KEYS} from './featureFlagDefaults';
import {getFeatureFlags} from './featureFlags.service';
import type {FeatureFlagKey, FeatureFlags} from './featureFlags.types';

/**
 * THE WALKING TEST (SPEC-163 FR-002).
 *
 * Every row in `GATED_SURFACES` is rendered twice — flag off, then flag on — and asserted by
 * ACCESSIBLE NAME. That is the whole design: a per-component gating pass finds the tabs and
 * the routes and ships a cross-feature entry point visible, because nobody remembers that
 * "Create table" is a Query feature living on a file-browser toolbar. Deliberately not an
 * ordinal — the population changes whenever a surface is added or retired, and a count in
 * prose goes stale in silence while the walk below stays correct.
 *
 * Only the AWS boundary is mocked (react.md §21) — including the feature-flag service, so the
 * real `useFeatureFlags` → `useFeature` → component chain runs. Mocking `useFeature` itself
 * would test the recipes and nothing else.
 */
vi.mock('./featureFlags.service', async (importActual) => ({
  ...(await importActual<typeof import('./featureFlags.service')>()),
  getFeatureFlags: vi.fn()
}));
vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof import('../file-browser/fileBrowser.service')>()),
  ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
  listFiles: vi.fn(),
  getObjectMetadata: vi.fn(),
  getDownloadUrl: vi.fn(),
  // Resolved, not bare: `QueryWorkspace` holds its `saved_queries/` folder open on mount
  // (SPEC-173 FR-001), and a `vi.fn()` returning undefined made that a rejection that
  // reddened the whole run from a recipe that has nothing to do with it.
  objectExists: vi.fn().mockResolvedValue({success: true, data: true}),
  uploadFile: vi.fn(),
  createFolder: vi.fn(),
  // Resolved so a save-results run reaches its success toast, whose action is a gated surface.
  copyObject: vi.fn().mockResolvedValue({success: true, data: {destKey: 'alice/results.csv'}})
}));
vi.mock('../file-browser/fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
// The sanctioned heavy-child exception (react.md §21): Monaco needs a real DOM editor and
// workers, and jsdom has neither — it throws on `ResizeObserver` the moment the lazy chunk
// resolves. Every Query recipe here mounts the workspace, and until SPEC-185 none of them
// lived long enough for that import to land; the save-results recipe below does, because it
// runs a statement. A textarea keeps the workspace's own contract honest.
vi.mock('../query/SqlEditor', async () => {
  const {forwardRef} = await import('react');
  return {
    SqlEditor: forwardRef<unknown, {value: string; onChange: (v: string) => void}>(function MockSqlEditor({
      value,
      onChange
    }) {
      return (
        <textarea
          aria-label="SQL editor"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    })
  };
});
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn().mockResolvedValue({success: true, data: {requestId: 'r1'}})
}));
vi.mock('../notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));
// SPEC-183's two recipes seed an exploration tab, which runs SPEC-178's engine for real —
// so the Athena boundary is mocked here as the Glue one already is. `isTerminalState` stays
// real: it decides when polling stops.
vi.mock('../catalog/athena.service', async (importActual) => ({
  ...(await importActual<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn().mockResolvedValue({success: true, data: {queryExecutionId: 'e1'}}),
  getQueryStatus: vi.fn().mockResolvedValue({
    success: true,
    data: {
      state: 'SUCCEEDED',
      dataScannedBytes: 1,
      engineExecutionTimeMillis: 1,
      // SPEC-185: the results location is what makes Export and Save-results reachable at
      // all — both copy THAT object, and both refuse without it.
      outputLocation: 's3://user-space/alice/athenaresults/e1.csv'
    }
  }),
  // One column and one row, not an empty page: the Query workspace offers Save-results only
  // for a result that HAS columns, so an empty page hid the surface SPEC-185 registers.
  getQueryResults: vi.fn().mockResolvedValue({
    success: true,
    data: {columns: [{name: 'region', type: 'varchar'}], rows: [['north']], nextToken: undefined}
  }),
  // Declared rather than spread from the real module, which would reach for the network. "Athena
  // does not count this", like every workspace suite's default, so the walk over the one-row page
  // above is what counts.
  getQueryRowCount: vi.fn().mockResolvedValue({success: true, data: {rowCount: null, pending: false}})
}));
vi.mock('../catalog/glue.service', () => ({
  getDatabase: vi.fn().mockResolvedValue({success: true, data: {name: 'alice'}}),
  listTables: vi.fn().mockResolvedValue({
    success: true,
    data: [{name: 'sales', tableType: 'EXTERNAL_TABLE', location: 's3://b/alice/sales/', columns: []}]
  })
}));
vi.mock('../data-quality/dataQualityReport.service', async (importActual) => ({
  ...(await importActual<typeof import('../data-quality/dataQualityReport.service')>()),
  getQualityReport: vi.fn()
}));
vi.mock('../data-quality/dataQualityRuns.service', async (importActual) => ({
  ...(await importActual<typeof import('../data-quality/dataQualityRuns.service')>()),
  getRunsIndex: vi.fn()
}));
vi.mock('../user-directory/userDirectory.service', () => ({
  DIRECTORY_KEY: '_directory/usernames.json',
  getUserDirectory: vi.fn().mockResolvedValue({success: true, data: {usernames: [], generatedAt: null}})
}));
import {Header} from '../../components/Header';
import {FileBrowser} from '../file-browser/FileBrowser';
import {UploadQueueProvider} from '../file-browser';
import {DatabaseNode} from '../query/DatabaseNode';
import {QueryToolbar} from '../query/QueryToolbar';
import {TableShareDialog} from '../table-share/TableShareDialog';
import {ManageMembersDrawer} from '../shared-spaces/ManageMembersDrawer';
import {QueryWorkspace} from '../query/QueryWorkspace';
import {QueryRunsProvider} from '../query/QueryRunsProvider';
import FilesPage from '../../routes/FilesPage';
import {NotificationRow} from '../notifications/NotificationRow';
import {SendFilesDialog} from '../file-send';
import {HelpPage} from '../help/HelpPage';
import {HELP_SECTIONS} from '../help/helpContent';
import {FeatureRoute} from '../../routes/FeatureRoute';
import {DataExplorerWorkspace} from '../data-explorer';
import {DataQualityPage} from '../data-quality';
import DataQualityReportPage from '../../routes/DataQualityReportPage';
import {getQualityReport} from '../data-quality/dataQualityReport.service';
import {getRunsIndex} from '../data-quality/dataQualityRuns.service';
import {csvReport} from '../data-quality/reportFixtures';
import type {DataQualityRunSummary} from '../data-quality/dataQuality.types';
import {listFiles} from '../file-browser/fileBrowser.service';
import {FileOpsInFlightProvider} from '../file-browser/FileOpsInFlightProvider';
import {InFlightOperations} from '../file-browser/InFlightOperations';
import {useFileOpsInFlight} from '../file-browser/fileOpsInFlightContext';
import {getNotifications} from '../notifications/notifications.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {Connection} from '../connections/connection.types';
import {
  chooseExplorationOption,
  explorationOption,
  openExplorationOptions
} from '../data-explorer/explorationOptions.testkit';

const ALL_ON: FeatureFlags = {
  files: true,
  query: true,
  sharedWorkspaces: true,
  dataQuality: true,
  dataExplorer: true,
  asyncFileOperations: true,
  resultsConversion: true,
  archive: true
};

/** Point the mocked service at one flag set, as the real reader would resolve it. */
function withFlags(overrides: Partial<FeatureFlags>) {
  vi.mocked(getFeatureFlags).mockResolvedValue({success: true, data: {...ALL_ON, ...overrides}});
}

const PERSONAL: Connection = {
  id: 'personal',
  kind: 'personal',
  label: 'alice',
  database: 'alice',
  status: 'active'
} as Connection;

beforeEach(() => {
  vi.clearAllMocks();
  // A recipe may seed a tab (the save-query one does). Left behind, it becomes a fixture
  // every later recipe silently inherits.
  sessionStorage.clear();
  // Both buckets, because `usableSpaceTargets` returns no SHARED target without the shared
  // bucket — the move-destination row would then be absent for a reason that has nothing to
  // do with the flag, and its "on" half would fail while its "off" half passed vacuously.
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  withFlags({});
  vi.mocked(listFiles).mockResolvedValue({
    success: true,
    data: {
      files: [{type: 'file', key: 'alice/a.csv', name: 'a.csv', size: 10, lastModified: new Date('2026-01-01')}],
      folders: [],
      nextToken: undefined
    }
  } as never);
  vi.mocked(readSharedConnectionsCache).mockResolvedValue({
    success: true,
    data: {version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]}
  } as never);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── Recipes: how each registered surface is reached ────────────────────────
//
// One entry per registry row, keyed by the row's `name`. `render` mounts the smallest tree
// that owns the surface; `find` returns the element or null. Keeping the recipes HERE rather
// than in the registry keeps the registry declarative and reviewable by someone who has not
// read a single component — and the coverage guard below fails if the two ever diverge.

type Recipe = {
  render: () => Promise<void> | void;
  find: () => Promise<Element | null>;
  /**
   * Something present REGARDLESS of the flag, awaited before an absence is asserted.
   *
   * Without it the off-half is vacuous: `useFeature` reports `false` while the flags are
   * still resolving, so `waitFor`'s first attempt runs at the one moment every surface is
   * legitimately missing — and an ungated surface that merely renders asynchronously passes.
   * Only needed where the surface itself arrives async; the rest settle inside `render`.
   */
  anchor?: () => Promise<unknown>;
  /**
   * Set where `render` waits on a statement run (`runStatement`, or the Data Explorer's execution), so the
   * case gets the longer limit that wait needs; without it the case's own five seconds would end first.
   */
  runsStatement?: true;
  /**
   * Set where `find` selects the section that owns a guide before it looks, so the row's "on" wait spans the
   * flags applying, an import, a click and a role query; without it that wait and the case's own limit end first.
   */
  selectsSection?: true;
};

const renderHeader = () => {
  renderWithProviders(<Header />, {auth: authenticated('alice'), seedFeatureFlags: false});
};

const renderFileBrowser = () => {
  renderWithProviders(
    <UploadQueueProvider>
      <FileOpsInFlightProvider>
        <FileBrowser
          bucket="user-space"
          rootPrefix="alice/"
          username="alice"
          writable
          spaceKind="personal"
        />
      </FileOpsInFlightProvider>
    </UploadQueueProvider>,
    {auth: authenticated('alice'), seedFeatureFlags: false}
  );
};

/** One notification carrying a run's conflicts — what the conflict view resolves its id against. */
const CONFLICT_NOTIFICATION = {
  id: 'n5',
  message: 'Moved 1 of 2 items to “out”.',
  read: false,
  timestamp: '2026-08-23T00:00:00Z',
  link: '/files?prefix=alice/out/',
  payload: {
    requestId: '11111111-2222-3333-4444-555555555555',
    operation: 'move',
    source: {kind: 'personal', name: 'alice'},
    destination: {kind: 'personal', name: 'alice', prefix: 'alice/out/'},
    conflicts: [{itemKey: 'alice/q1.csv', kind: 'file'}]
  }
};

/**
 * Seeds ONE in-flight entry, so the surface has something to render in both flag states.
 *
 * A recipe may not re-implement a gate, and this does not: the gate lives inside
 * `InFlightOperations`, which is rendered here for real. What the seed supplies is DATA — the
 * store is session state with no other door, and driving a whole enqueue through the toolbar
 * would make the recipe a test of the dispatcher instead.
 */
function SeedInFlight() {
  const {add} = useFileOpsInFlight();
  useEffect(() => {
    add({
      requestId: 'seed-1',
      operation: 'move',
      itemCount: 3,
      sourceSpace: {kind: 'personal', name: 'alice'},
      submittedAt: new Date().toISOString(),
      state: 'submitted'
    });
  }, [add]);
  return null;
}

/**
 * Leave the Data Explorer with one open tab, the way a previous visit would have.
 *
 * The save surfaces live on the RESULTS region, which only renders once a tab exists — with
 * none, the workspace shows the source picker and both rows would be absent for a reason
 * that has nothing to do with a flag, so their "on" halves would fail and their "off" halves
 * would pass vacuously. The key is spelled out for the same reason the query-tabs one above
 * is: a recipe reaching into the feature's constants is a step away from re-implementing it.
 */
function seedExplorationTab() {
  sessionStorage.setItem(
    's3portal.dataExplorer.tabs.alice',
    JSON.stringify({
      version: 1,
      tabs: [
        {
          id: 'x',
          label: 'sales',
          exploration: {
            id: 'x',
            source: {kind: 'table', spaceId: 'personal', database: 'alice', table: 'sales'},
            query: {filters: [], expression: null, ordering: [], grouping: null},
            presentation: {}
          },
          scannedByExecution: {},
          history: {past: [], future: []}
        }
      ],
      activeTabId: 'x'
    })
  );
}

const byRole = (role: string, name: string | RegExp) => async () => {
  const found = screen.queryAllByRole(role, {name});
  return found[0] ?? null;
};

/** A gated route's surface is the PAGE: present means the unavailable page did NOT render. */
const routeRecipe = (flag: FeatureFlagKey): Recipe => ({
  render: () => {
    renderWithProviders(
      <FeatureRoute flag={flag}>
        <div>THE PAGE</div>
      </FeatureRoute>,
      {auth: authenticated('alice'), seedFeatureFlags: false}
    );
  },
  find: async () => {
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    return screen.queryByText('THE PAGE');
  }
});

const helpRecipe = (helpId: string): Recipe => ({
  ...(HELP_SECTIONS.some((s) => s.id === helpId) ? {} : {selectsSection: true as const}),
  render: () => {
    renderWithProviders(<HelpPage />, {auth: authenticated('alice'), seedFeatureFlags: false});
  },
  anchor: async () => screen.findByRole('complementary', {name: 'Guides navigation'}),
  find: async () => {
    const section = HELP_SECTIONS.find((s) => s.id === helpId);
    if (section) {
      // An <aside>, so `complementary` — and jsdom reports no desktop breakpoint, which is
      // the band where the rail shows its COMPACT labels. Matching the section id in the
      // button's own accessible name would be brittle either way, so the query is a
      // case-insensitive prefix of the label, which both spellings share.
      const rail = screen.getByRole('complementary', {name: 'Guides navigation'});
      const compact = section.label.split(' ')[0];
      return within(rail).queryByRole('button', {name: new RegExp(`^${compact}`, 'i')});
    }
    // A guide INSIDE a section: SELECT ITS OWNING SECTION FIRST, then look for its card.
    //
    // The selection is load-bearing and was missing until SPEC-185 (every guide row until
    // then happened to live in `files`, the section the page opens on). Without it, a row
    // for a guide in any other section queries a card the page has not rendered and comes
    // back null in BOTH flag states — which reads as "correctly hidden" rather than as a
    // recipe that cannot see its own surface.
    const owner = HELP_SECTIONS.find((s) => s.guides.some((g) => g.id === helpId));
    if (!owner) throw new Error(`no help section or guide with id ${helpId}`);
    const guide = owner.guides.find((g) => g.id === helpId)!;
    const rail = screen.getByRole('complementary', {name: 'Guides navigation'});
    const sectionButton = within(rail).queryByRole('button', {
      name: new RegExp(`^${owner.label.split(' ')[0]}`, 'i')
    });
    // The owning SECTION may itself be gated by the same flag — that is the `files` shape,
    // where a guide row and a section row share one flag. With it gone the guide is gone
    // too, which is the answer this recipe is being asked for.
    if (!sectionButton) return null;
    const {default: userEvent} = await import('@testing-library/user-event');
    await userEvent.setup({delay: null}).click(sectionButton);
    return screen.queryByRole('button', {name: new RegExp(guide.title, 'i')});
  }
});

/**
 * The archive entry points, each walked twice: once under `files`, whose gate removes the whole
 * file browser, and once under `archive`, the kill switch over these controls alone. One recipe per
 * control, so the two rows cannot drift into asserting different things.
 */
const archiveToolbarRecipe: Recipe = {
  render: renderFileBrowser,
  anchor: fileBrowserReady,
  find: byRole('button', 'Archive selected items')
};

const restoreRecipe: Recipe = {
  render: renderFileBrowser,
  anchor: fileBrowserReady,
  find: byRole('button', 'Restore Archived Data')
};

// The DETAILS-PANEL entry point, reached the way a user reaches it: open a file's details
// drawer. There is no context menu in this file browser, so this is the ONLY route to
// archiving one item without selecting it, and it is a different component from the toolbar.
const archivePanelRecipe: Recipe = {
  render: async () => {
    renderFileBrowser();
    (await screen.findByRole('button', {name: 'Details for a.csv'})).click();
  },
  anchor: async () => screen.findByRole('dialog', {name: 'Details for a.csv'}),
  find: byRole('button', 'Archive this item')
};

const RECIPES: Record<string, Recipe> = {
  // ── nav ──
  Files: {render: renderHeader, anchor: navReady, find: byRole('link', 'Files')},
  Query: {render: renderHeader, anchor: navReady, find: byRole('link', 'Query')},
  'Shared spaces': {render: renderHeader, anchor: navReady, find: byRole('link', 'Shared spaces')},
  'Data quality': {render: renderHeader, anchor: navReady, find: byRole('link', 'Data quality')},
  'Data Explorer': {render: renderHeader, anchor: navReady, find: byRole('link', 'Data Explorer')},

  // ── routes ──
  '/files': routeRecipe('files'),
  '/query': routeRecipe('query'),
  '/connections': routeRecipe('sharedWorkspaces'),
  '/data-quality': routeRecipe('dataQuality'),
  '/data-quality/:space/:requestId': routeRecipe('dataQuality'),
  '/explore': routeRecipe('dataExplorer'),

  // ── controls ──
  'Go to Files': {
    render: async () => {
      const {default: LandingPage} = await import('../../routes/LandingPage');
      renderWithProviders(<LandingPage />, {auth: authenticated('alice'), seedFeatureFlags: false});
    },
    // EXACT, not `/^Go to /`: with Files off the page correctly renders "Go to Query", and a
    // prefix match would have found that and called the gate broken — or, worse, found
    // nothing yet and called it working.
    find: byRole('button', 'Go to Files')
  },
  'Create table': {render: renderFileBrowser, anchor: fileBrowserReady, find: byRole('button', 'Create table')},
  // The REAL /files page against a listing that contains the folder — a recipe that
  // re-applied the gate itself would pass with the app's own gate deleted (measured).
  'saved_queries folder': {
    render: () => {
      vi.mocked(listFiles).mockResolvedValue({
        success: true,
        data: {
          files: [],
          folders: [{type: 'folder', prefix: 'alice/saved_queries/', name: 'saved_queries'}],
          isTruncated: false
        }
      } as never);
      renderFilesPage();
    },
    anchor: filesPageReady,
    find: byRole('button', 'Open folder saved_queries')
  },
  'Check data quality of the selected item': {
    render: renderFileBrowser,
    anchor: fileBrowserReady,
    find: byRole('button', 'Check data quality of the selected item')
  },
  'Send to another user': {
    render: renderFileBrowser,
    anchor: fileBrowserReady,
    find: byRole('button', 'Send to another user')
  },
  'Archive selected items': archiveToolbarRecipe,
  'Restore Archived Data': restoreRecipe,
  'Archive this item': archivePanelRecipe,
  'Archive in the selection toolbar': archiveToolbarRecipe,
  'Archive in the details panel': archivePanelRecipe,
  'Restore Archived Data in the file browser': restoreRecipe,
  'Refresh table': {
    render: async () => {
      renderWithProviders(
        <DatabaseNode
          connection={PERSONAL}
          defaultExpanded
          actions={tableActionsStub()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
      await openTableMenu();
    },
    find: byRole('menuitem', 'Refresh table')
  },
  // The same menu item, under each of the two flags that must be able to remove it on its
  // own. One recipe shape, deliberately: what differs between the rows is which flag the walk
  // turns off, and that is the whole point of registering it twice.
  'Explore data': {
    render: async () => {
      renderWithProviders(
        <DatabaseNode
          connection={PERSONAL}
          defaultExpanded
          actions={tableActionsStub()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
      await openTableMenu();
    },
    find: byRole('menuitem', 'Explore data')
  },
  'Explore data on the Query schema rail': {
    render: async () => {
      renderWithProviders(
        <DatabaseNode
          connection={PERSONAL}
          defaultExpanded
          actions={tableActionsStub()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
      await openTableMenu();
    },
    find: byRole('menuitem', 'Explore data')
  },
  // One recipe for both rows, as with the rail item: the flag the walk turns off is the only
  // difference. Save is the anchor because it shares the control's gate on the result and follows
  // neither flag, so the off-half judges an absence only once the result has landed.
  'Explore in Data Explorer': exploreResultRecipe(),
  'Explore in Data Explorer on a query result': exploreResultRecipe(),
  'Shared spaces in the Data Explorer source picker': {
    render: () => {
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
    },
    // The PERSONAL space — always offered, so it settles the picker without depending on the
    // row under test.
    anchor: async () => screen.findByRole('button', {name: /^alice/}),
    find: async () => screen.queryByRole('button', {name: /^teamspace/})
  },
  'Open saved view': {
    render: () => {
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
    },
    // The picker's personal space: always offered, so it settles the picker without the row.
    anchor: async () => screen.findByRole('button', {name: /^alice/}),
    find: async () => screen.queryByRole('button', {name: 'Open saved view'})
  },
  'Shared spaces in the saved-view drawer': {
    render: async () => {
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
      const {default: userEvent} = await import('@testing-library/user-event');
      await userEvent.setup({delay: null}).click(await screen.findByRole('button', {name: 'Open saved view'}));
    },
    anchor: async () => screen.findByRole('option', {name: 'alice'}),
    find: async () => screen.queryByRole('option', {name: 'teamspace'})
  },
  'Create view…': {
    render: async () => {
      seedExplorationTab();
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
      const {default: userEvent} = await import('@testing-library/user-event');
      await openExplorationOptions(userEvent.setup({delay: null}));
    },
    // A SIBLING ITEM as the anchor, not the trigger: anchoring on the trigger settles before
    // the menu has opened and lets the `find` miss for a reason that is not the flag.
    anchor: async () => screen.findByRole('menuitem', {name: 'Grouping'}),
    find: async () => screen.queryByRole('menuitem', {name: 'Create view…'})
  },
  'Open in Query in the Options menu': {
    render: async () => {
      seedExplorationTab();
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
      const {default: userEvent} = await import('@testing-library/user-event');
      await openExplorationOptions(userEvent.setup({delay: null}));
    },
    // A sibling item as the anchor, for the reason `Save as query` gives below. Run or not, the
    // item is present — refused while there is no statement — so only the flag can remove it.
    anchor: async () => screen.findByRole('menuitem', {name: 'Grouping'}),
    find: async () => screen.queryByRole('menuitem', {name: 'Open in Query'})
  },
  'Save as query': {
    render: async () => {
      seedExplorationTab();
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
      const {default: userEvent} = await import('@testing-library/user-event');
      await openExplorationOptions(userEvent.setup({delay: null}));
    },
    // A tab is seeded because the control lives on the RESULTS region, which does not mount
    // at all with no tabs — absent for a reason that has nothing to do with a flag. Given one,
    // an unrunnable exploration leaves the control `aria-disabled` rather than absent, so from
    // here the flag is the only thing that can remove it.
    //
    // The control is now a menu item, so `render` opens the menu and the anchor is a SIBLING
    // ITEM — `Grouping`, which is ungated. Anchoring on the trigger instead would settle before
    // the menu had opened and let the `find` miss for a reason that is not the flag.
    anchor: async () => screen.findByRole('menuitem', {name: 'Grouping'}),
    find: async () => screen.queryByRole('menuitem', {name: 'Save as query'})
  },
  'Open in Query': {
    render: async () => {
      seedExplorationTab();
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
      const {default: userEvent} = await import('@testing-library/user-event');
      // The control mounts only over a statement that exists, so the recipe waits for one before
      // opening the disclosure — otherwise it is absent for a reason that is not the flag.
      await screen.findByLabelText('Generated SQL');
      await userEvent.setup({delay: null}).click(screen.getByText('Generated SQL'));
    },
    // The copy button beside it, which is ungated and mounts under the same rule.
    anchor: async () => screen.findByRole('button', {name: 'Copy SQL'}),
    find: async () => screen.queryByRole('button', {name: 'Open in Query'})
  },
  // SPEC-185. Export's own destination selector, reached through the real toolbar button —
  // which is itself refused until an execution has SUCCEEDED, so the recipe exercises that
  // gate on the way past.
  'Shared spaces in the Data Explorer export dialog': {
    render: async () => {
      seedExplorationTab();
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      // Save results lives in the Options menu too, and the recipe walks the refusal there:
      // the item is REFUSED until an execution has succeeded (FR-002 AC3), and a refused
      // `MenuItem` drops its `onSelect` — so choosing it early would silently do nothing and
      // the row would read as correctly hidden in both states. Re-fetched on each pass rather
      // than held, because `waitFor` outlives the menu's own open state.
      await waitFor(
        async () => expect(await explorationOption(user, 'Save results…')).not.toHaveAttribute('aria-disabled', 'true'),
        SLOW_WAIT
      );
      await chooseExplorationOption(user, 'Save results…');
    },
    runsStatement: true,
    anchor: async () => within(await screen.findByRole('dialog', {name: 'Save results'})).findByLabelText('File name'),
    find: async () => screen.queryByRole('option', {name: 'teamspace'})
  },
  // SPEC-185. The TWIN, in the Query workspace — ungated since SPEC-055 because
  // `useSaveResults` built its own destination list from an unfiltered `useQuerySpaces()`.
  'Shared spaces in the save-results dialog': {
    render: async () => {
      sessionStorage.setItem(
        's3portal.query.tabs.alice',
        JSON.stringify({
          version: 1,
          tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1;'}],
          activeTabId: 'a',
          nextQueryNumber: 2
        })
      );
      renderQueryWorkspace();
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      // The button is offered only for a displayed result with a results location, so
      // the run is part of reaching it rather than scaffolding around it.
      await user.click(await runStatement(user));
    },
    runsStatement: true,
    anchor: async () => within(await screen.findByRole('dialog', {name: 'Save results'})).findByLabelText('File name'),
    find: async () => screen.queryByRole('option', {name: 'teamspace'})
  },
  // SPEC-223. The SAME two recipes as the two save-results rows above — the dialog is reached
  // the same way and the flag under test is the only difference. The `find` is the format select
  // itself, which is `absent` rather than disabled with the flag off.
  'Format in the Data Explorer export dialog': {
    render: async () => {
      seedExplorationTab();
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      await waitFor(
        async () => expect(await explorationOption(user, 'Save results…')).not.toHaveAttribute('aria-disabled', 'true'),
        SLOW_WAIT
      );
      await chooseExplorationOption(user, 'Save results…');
    },
    runsStatement: true,
    anchor: async () => within(await screen.findByRole('dialog', {name: 'Save results'})).findByLabelText('File name'),
    find: async () => screen.queryByLabelText('Format')
  },
  'Format in the save-results dialog': {
    render: async () => {
      sessionStorage.setItem(
        's3portal.query.tabs.alice',
        JSON.stringify({
          version: 1,
          tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1;'}],
          activeTabId: 'a',
          nextQueryNumber: 2
        })
      );
      renderQueryWorkspace();
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      await user.click(await runStatement(user));
    },
    runsStatement: true,
    anchor: async () => within(await screen.findByRole('dialog', {name: 'Save results'})).findByLabelText('File name'),
    find: async () => screen.queryByLabelText('Format')
  },
  'Shared spaces in the Data Explorer save dialog': {
    render: async () => {
      seedExplorationTab();
      renderWithProviders(<DataExplorerWorkspace />, {auth: authenticated('alice'), seedFeatureFlags: false});
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      await chooseExplorationOption(user, 'Save as query');
    },
    anchor: async () => within(await screen.findByRole('dialog', {name: 'Save query'})).findByLabelText('Space'),
    find: async () => screen.queryByRole('option', {name: 'teamspace'})
  },
  'Share table': {
    render: async () => {
      renderWithProviders(
        <DatabaseNode
          connection={PERSONAL}
          defaultExpanded
          actions={tableActionsStub()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
      await openTableMenu();
    },
    find: byRole('menuitem', 'Share table')
  },
  'Create view': {
    render: () => {
      renderWithProviders(
        <QueryToolbar
          isInFlight={false}
          canRun
          canClear
          canSave
          sql="SELECT 1"
          downloadName="query.sql"
          onClear={vi.fn()}
          onSave={vi.fn()}
          onOpenSaved={vi.fn()}
          onCreateView={vi.fn()}
          onStop={vi.fn()}
          onRunStatement={vi.fn()}
          onRunScript={vi.fn()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('button', 'Create view')
  },
  'Your spaces navigation': {
    render: renderFilesPage,
    anchor: filesPageReady,
    find: async () => screen.queryByRole('complementary', {name: 'Your spaces navigation'})
  },
  'Add members': {
    render: () => {
      renderWithProviders(
        <ManageMembersDrawer
          open
          space="teamspace"
          owner="alice"
          members={[{username: 'alice', status: 'active'} as never]}
          onClose={vi.fn()}
          onRefresh={vi.fn()}
          onAddMembers={vi.fn()}
          onRemoveMembers={vi.fn()}
          onTransferOwnership={vi.fn()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('button', 'Add members')
  },
  'Shared spaces recipient kind in the share dialog': {
    render: () => {
      renderWithProviders(
        <TableShareDialog
          source={{database: 'alice', table: 'sales'}}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('radio', 'Shared spaces')
  },
  'Shared spaces as a move destination': {
    render: async () => {
      renderFilesPage();
      await fileBrowserReady();
      // Through the real flow: select an item, open Copy, and look at the picker's
      // destination selector — which only renders at all when there is more than one option,
      // so with shared workspaces off there is nothing to choose and no selector.
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      await user.click(await screen.findByRole('checkbox', {name: 'Select all'}));
      await user.click(await screen.findByRole('button', {name: 'Copy selected items'}));
    },
    anchor: async () => screen.findByRole('dialog'),
    find: async () => screen.queryByRole('combobox', {name: 'Destination space'})
  },

  'Data quality link on a notification': {
    render: () => {
      renderWithProviders(
        <NotificationRow
          notification={{
            id: 'n1',
            message: 'Data quality check finished',
            read: false,
            timestamp: '2026-08-11T00:00:00Z',
            link: '/data-quality/alice/req-1'
          }}
          onMarkRead={vi.fn()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('link', 'Data quality check finished')
  },
  'Shared spaces recipient kind in the send dialog': {
    render: () => {
      renderWithProviders(
        <SendFilesDialog
          items={[{kind: 'file', key: 'alice/notes.txt'}]}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('radio', 'Shared spaces')
  },
  'Received files link on a notification': {
    render: () => {
      renderWithProviders(
        <NotificationRow
          notification={{
            id: 'n2',
            message: 'alice sent you "reports" (300 files)',
            read: false,
            timestamp: '2026-08-11T00:00:00Z',
            link: '/files?prefix=bob/shared_files/alice/'
          }}
          onMarkRead={vi.fn()}
        />,
        {auth: authenticated('bob'), seedFeatureFlags: false}
      );
    },
    find: byRole('link', 'alice sent you "reports" (300 files)')
  },
  'Review conflicts for a file operation': {
    render: () => {
      vi.mocked(getNotifications).mockResolvedValue({success: true, data: [CONFLICT_NOTIFICATION]} as never);
      renderWithProviders(
        <UploadQueueProvider>
          <FileOpsInFlightProvider>
            <FileBrowser
              bucket="user-space"
              rootPrefix="alice/"
              username="alice"
              writable
              spaceKind="personal"
              requestId={CONFLICT_NOTIFICATION.payload.requestId}
            />
          </FileOpsInFlightProvider>
        </UploadQueueProvider>,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    anchor: fileBrowserReady,
    find: byRole('alertdialog', 'Review conflicts')
  },
  'File operations in progress': {
    render: () => {
      renderWithProviders(
        <FileOpsInFlightProvider>
          <SeedInFlight />
          <InFlightOperations />
        </FileOpsInFlightProvider>,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('region', 'File operations in progress')
  },
  'Background file operations guide': helpRecipe('resolve-file-operation-conflicts'),
  'Review conflicts on a notification': {
    render: () => {
      renderWithProviders(
        <NotificationRow
          notification={{
            id: 'n4',
            message: 'Moved 1 of 2 items to "out". 1 was not moved: "q1.csv" - something is already in the way there.',
            read: false,
            timestamp: '2026-08-23T00:00:00Z',
            link: '/files?prefix=alice/out/',
            payload: {
              requestId: '11111111-2222-3333-4444-555555555555',
              operation: 'move',
              conflicts: [{itemKey: 'alice/q1.csv', kind: 'file'}]
            }
          }}
          onMarkRead={vi.fn()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('link', 'Review conflicts')
  },
  'Review conflicts on a notification that carries no link': {
    render: () => {
      renderWithProviders(
        <NotificationRow
          notification={{
            id: 'n6',
            message: 'Moved 1 of 2 items. 1 was not moved: "q1.csv" - something is already in the way there.',
            read: false,
            timestamp: '2026-08-23T00:00:00Z',
            payload: {
              requestId: '11111111-2222-3333-4444-555555555555',
              operation: 'move',
              conflicts: [{itemKey: 'alice/q1.csv', kind: 'file'}]
            }
          }}
          onMarkRead={vi.fn()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('link', 'Review conflicts')
  },
  'Received files link to a space on a notification': {
    render: () => {
      renderWithProviders(
        <NotificationRow
          notification={{
            id: 'n3',
            message: 'alice sent "reports" (300 files) to your space "finance"',
            read: false,
            timestamp: '2026-08-11T00:00:00Z',
            link: '/files?space=finance&prefix=finance/shared_files/alice/'
          }}
          onMarkRead={vi.fn()}
        />,
        {auth: authenticated('bob'), seedFeatureFlags: false}
      );
    },
    find: byRole('link', 'alice sent "reports" (300 files) to your space "finance"')
  },
  'Shared spaces in the saved-queries selector': {
    render: async () => {
      renderQueryWorkspace();
      // Through the real flow: the selector lives in the drawer, so the drawer is opened.
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      await user.click(await screen.findByRole('button', {name: 'Saved queries'}));
    },
    // The PERSONAL option — always offered, so it settles the selector without depending on
    // the row under test.
    anchor: async () => screen.findByRole('option', {name: 'alice'}),
    find: async () => screen.queryByRole('option', {name: 'teamspace'})
  },
  'Shared spaces in the save-query dialog': {
    render: async () => {
      // Save is disabled on an empty buffer, so the tab is seeded rather than typed into:
      // Monaco is real in this file, and the recipe must render the REAL page (SPEC-163 —
      // a recipe that re-implements the gate proves nothing).
      sessionStorage.setItem(
        's3portal.query.tabs.alice',
        JSON.stringify({
          version: 1,
          tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1;'}],
          activeTabId: 'a',
          nextQueryNumber: 2
        })
      );
      renderQueryWorkspace();
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      await user.click(await screen.findByRole('button', {name: 'Save query'}));
    },
    anchor: async () => within(await screen.findByRole('dialog', {name: 'Save query'})).findByLabelText('Space'),
    find: async () => screen.queryByRole('option', {name: 'teamspace'})
  },
  'Shared databases in the schema rail': {
    render: renderQueryWorkspace,
    // The PERSONAL database node — present either way, so it settles the rail without
    // depending on the row under test.
    anchor: async () => screen.findAllByRole('button', {name: /alice/}),
    find: async () => screen.queryByRole('button', {name: /teamspace/})
  },

  // ── guides ──
  'View source files': {
    render: async () => {
      renderWithProviders(
        <DatabaseNode
          connection={PERSONAL}
          defaultExpanded
          actions={tableActionsStub()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
      await openTableMenu();
    },
    anchor: async () => screen.findByRole('menuitem', {name: 'View DDL'}),
    find: byRole('menuitem', 'View source files')
  },
  'View in Files after saving results': {
    render: async () => {
      sessionStorage.setItem(
        's3portal.query.tabs.alice',
        JSON.stringify({
          version: 1,
          tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1;'}],
          activeTabId: 'a',
          nextQueryNumber: 2
        })
      );
      renderQueryWorkspace();
      const {default: userEvent} = await import('@testing-library/user-event');
      const user = userEvent.setup({delay: null});
      await user.click(await runStatement(user));
      const dialog = await screen.findByRole('dialog', {name: 'Save results'});
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));
    },
    runsStatement: true,
    // The toast itself is not gated — only its way into the file browser is.
    anchor: async () => screen.findByText(/^Saved to /),
    find: byRole('button', 'View in Files')
  },
  'Open folder on a data quality report': {
    render: () => {
      vi.mocked(getQualityReport).mockResolvedValue({success: true, data: csvReport()});
      renderReportRoute('/data-quality/alice/req-1');
    },
    anchor: async () => screen.findByRole('button', {name: 'Re-run check'}),
    find: byRole('button', 'Open folder')
  },
  'Shared-space data quality report': {
    render: () => {
      vi.mocked(getQualityReport).mockResolvedValue({success: true, data: csvReport()});
      renderReportRoute('/data-quality/teamspace/req-1');
    },
    // A level-one heading renders either way: the report's, or the unavailable page's.
    anchor: async () => screen.findByRole('heading', {level: 1}),
    find: async () => screen.queryByRole('heading', {level: 1, name: 'Data quality report'})
  },
  'Shared-space runs in the data quality list': {
    render: () => {
      vi.mocked(getRunsIndex).mockImplementation(async (_bucket, space) => ({
        success: true,
        data: [runSummary(space)]
      }));
      renderWithProviders(<DataQualityPage />, {auth: authenticated('alice'), seedFeatureFlags: false});
    },
    anchor: async () => screen.findByRole('link', {name: /on alice\/data\.csv/}),
    find: byRole('link', /on teamspace\/data\.csv/)
  },
  'Refresh table link on a notification': notificationRecipe('/query?refreshTable=alice.sales&removed=id'),
  'Refresh table link to a shared space on a notification': notificationRecipe(
    '/query?refreshTable=teamspace.sales&removed=id'
  ),
  'Data quality link to a shared space on a notification': notificationRecipe('/data-quality/teamspace/req-1'),
  'Files help section': helpRecipe('files'),
  'Query help section': helpRecipe('query'),
  'Tables help section': helpRecipe('tables'),
  'Shared connections help section': helpRecipe('shared-connections'),
  'Check data quality guide': helpRecipe('check-data-quality'),
  'Past data quality checks guide': helpRecipe('past-data-quality-checks'),
  'Send files guide': helpRecipe('send-files'),
  'Archive and restore guide': helpRecipe('archive-files'),
  'Archive and restore guide under the archive switch': helpRecipe('archive-files'),
  // SPEC-185. The first guide rows outside the section the Help page opens on — see
  // `helpRecipe`, which had to learn to select the owning section for them.
  'Data Explorer help section': helpRecipe('data-explorer'),
  'Start exploring guide': helpRecipe('start-exploring'),
  'Filter and sort guide': helpRecipe('explore-filter-sort'),
  'Grouping and Calc guide': helpRecipe('explore-group-and-calc'),
  'Copy and export guide': helpRecipe('explore-copy-and-export'),
  'Save an exploration guide': helpRecipe('explore-save-as-query'),
  'Save an exploration guide under Query': helpRecipe('explore-save-as-query'),
  'Filter by value guide under Query': helpRecipe('query-filter-by-value'),
  'Colors and Transformers guide': helpRecipe('explore-colors-and-formats'),
  'Data Explorer save formats guide under the Data Explorer': helpRecipe('explore-save-formats'),
  'Create table guide': helpRecipe('create-table'),
  'Shared space files guide': helpRecipe('use-shared-space-files'),
  'Send to a shared space guide': helpRecipe('send-files-to-a-space'),
  'Share with a shared space guide': helpRecipe('share-table-to-a-space'),
  'Data quality report guide': helpRecipe('read-data-quality-report'),
  'Save results formats guide': helpRecipe('save-results-formats'),
  'Data Explorer save formats guide': helpRecipe('explore-save-formats')
};

/**
 * The REAL page, not a test-local component that re-applies the gate.
 *
 * A host defined here would assert that `useFeature` works — which nothing doubts — while the
 * app's own gate could be deleted with the suite still green. That is not a hypothetical: it
 * was measured on this very row before it was rewritten, and both gates came out with 1843
 * tests still passing.
 */
function renderFilesPage() {
  renderWithProviders(
    <UploadQueueProvider>
      <FileOpsInFlightProvider>
        <FilesPage />
      </FileOpsInFlightProvider>
    </UploadQueueProvider>,
    {auth: authenticated('alice'), seedFeatureFlags: false}
  );
}

/** The report page at its real pattern, so the page's `useParams()` has its space. */
function renderReportRoute(path: string) {
  renderWithProviders(<DataQualityReportPage />, {
    route: path,
    path: '/data-quality/:space/:requestId',
    auth: authenticated('alice'),
    seedFeatureFlags: false
  });
}

/** One completed check in `space`, named for its space so a query can tell the rows apart. */
function runSummary(space: string): DataQualityRunSummary {
  return {
    requestId: `req-${space}`,
    space,
    location: `${space}/data.csv`,
    format: 'csv',
    verdict: 'clean',
    fileCount: 1,
    hasIncompleteFigures: false,
    timestamp: '2026-09-01T00:00:00Z'
  };
}

/** A notification row whose message is a link to `link`, found by that message. */
function notificationRecipe(link: string): Recipe {
  const message = `Notification linking to ${link}`;
  return {
    render: () => {
      renderWithProviders(
        <NotificationRow
          notification={{id: link, message, read: false, timestamp: '2026-08-11T00:00:00Z', link}}
          onMarkRead={vi.fn()}
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('link', message)
  };
}

/** Likewise the real workspace. Mobile, so Monaco never mounts (SPEC-100). */
function renderQueryWorkspace() {
  renderWithProviders(
    <QueryRunsProvider username="alice">
      <QueryWorkspace />
    </QueryRunsProvider>,
    {auth: authenticated('alice'), seedFeatureFlags: false}
  );
}

// Real work (a statement run, a Help guide found by selecting its section) outlasts a wait's 1 s under load,
// and a 5 s wait needs a case above 5 s.
const SLOW_WAIT = {timeout: 5_000};
const SLOW_CASE = {timeout: 15_000};

/**
 * Runs the open tab's statement and waits for its results to render.
 *
 * @param user - The `userEvent` instance the recipe is driving with.
 * @returns The results region's **Save results…** button, offered for the displayed result whatever its verdict.
 */
async function runStatement(user: UserEvent) {
  await user.click(await screen.findByRole('button', {name: 'Run statement'}));
  return screen.findByRole('button', {name: 'Save results…'}, SLOW_WAIT);
}

/** The file browser has finished its first listing — the tree is settled either way. */
async function filesPageReady() {
  return screen.findByRole('button', {name: 'New folder'});
}

function exploreResultRecipe(): Recipe {
  return {
    render: async () => {
      sessionStorage.setItem(
        's3portal.query.tabs.alice',
        JSON.stringify({
          version: 1,
          tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1 AS region;'}],
          activeTabId: 'a',
          nextQueryNumber: 2
        })
      );
      renderQueryWorkspace();
      const {default: userEvent} = await import('@testing-library/user-event');
      await runStatement(userEvent.setup({delay: null}));
    },
    runsStatement: true,
    anchor: async () => screen.findByRole('button', {name: 'Save results…'}),
    find: async () => screen.queryByRole('button', {name: 'Explore in Data Explorer'})
  };
}

function tableActionsStub() {
  return {
    onViewSourceFiles: vi.fn(),
    canViewSourceFiles: () => true,
    onViewDdl: vi.fn(),
    onViewData: vi.fn(),
    onExploreData: vi.fn(),
    onRefreshTable: vi.fn(),
    onShareTable: vi.fn(),
    onDropTable: vi.fn()
  } as never;
}

async function openTableMenu() {
  const trigger = await screen.findByRole('button', {name: 'Options for sales'});
  trigger.click();
}

/** The primary nav exists; only its CONTENTS depend on the flags. */
async function navReady() {
  return screen.findByRole('navigation', {name: 'Primary'});
}

/** The file browser's first listing has landed. */
async function fileBrowserReady() {
  return screen.findByRole('button', {name: 'New folder'});
}

/**
 * Wait until the flag answer has actually been applied.
 *
 * Two steps, both necessary: the recipe's own anchor proves the tree finished rendering, and
 * the flush lets the resolved query re-render before anything is asserted absent.
 */
async function settle(recipe: Recipe) {
  await waitFor(() => expect(getFeatureFlags).toHaveBeenCalled());
  await recipe.anchor?.();
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

// ─── The walk ───────────────────────────────────────────────────────────────

describe('every registered surface disappears with its flag off and returns with it on', () => {
  const rows = (Object.entries(GATED_SURFACES) as [FeatureFlagKey, (typeof GATED_SURFACES)[FeatureFlagKey]][]).flatMap(
    ([flag, surfaces]) => surfaces.map((surface) => ({flag, surface}))
  );

  // A loop rather than `it.each`, whose options are one object for every row: only a row that runs a
  // statement, or whose "on" wait selects a section first, gets the longer case limit. A row with no
  // recipe reads as no budget, so the guard below, not a collection error, is what names it.
  const caseFor = (name: string) => (RECIPES[name]?.runsStatement ? SLOW_CASE : {});
  const onCaseFor = (name: string) => (RECIPES[name]?.runsStatement || RECIPES[name]?.selectsSection ? SLOW_CASE : {});

  for (const {flag, surface} of rows) {
    it(`${flag} off hides "${surface.name}"`, caseFor(surface.name), async () => {
      const recipe = RECIPES[surface.name];
      withFlags({[flag]: false});
      await recipe.render();
      await settle(recipe);
      // Asserted ONCE, after the tree has settled — never inside `waitFor`, whose first
      // attempt lands while every surface is legitimately absent.
      expect(await recipe.find()).toBeNull();
    });
  }

  for (const {flag, surface} of rows) {
    it(`${flag} on shows "${surface.name}"`, onCaseFor(surface.name), async () => {
      const recipe = RECIPES[surface.name];
      withFlags({});
      await recipe.render();
      await waitFor(
        async () => expect(await recipe.find()).not.toBeNull(),
        recipe.selectsSection ? SLOW_WAIT : undefined
      );
    });
  }
});

// ─── Guard the guard (FR-002 AC4) ───────────────────────────────────────────

describe('the fallback an unavailable page offers', () => {
  it('skips an enabled flag with no destination, and offers none when only such flags are on', () => {
    const on = (keys: string[]) => (key: string) => keys.includes(key);
    expect(navDestination('asyncFileOperations')).toBeUndefined();

    expect(firstEnabledDestination(on(['asyncFileOperations', 'dataQuality']))).toBe('dataQuality');
    expect(firstEnabledDestination(on(['asyncFileOperations', 'resultsConversion', 'archive']))).toBeUndefined();
  });
});

describe('the registry itself', () => {
  it('is not empty, and no flag has zero surfaces', () => {
    // A walk over nothing passes silently forever, which is the failure mode a registry is
    // supposed to close rather than introduce (SPEC-153).
    expect(Object.keys(GATED_SURFACES).sort()).toEqual([...FEATURE_FLAG_KEYS].sort());
    for (const key of FEATURE_FLAG_KEYS) {
      expect(GATED_SURFACES[key].length, `${key} has no gated surfaces`).toBeGreaterThan(0);
    }
  });

  it('has a recipe for every row, and no recipe for a row that does not exist', () => {
    // The half that matters: a row added without a recipe would otherwise be silently
    // unwalked, which is a registry entry that proves nothing.
    const names = Object.values(GATED_SURFACES)
      .flat()
      .map((s) => s.name)
      .sort();
    expect(Object.keys(RECIPES).sort()).toEqual(names);
  });

  it('covers the gating contract entry for entry', () => {
    // The contract table transcribed from SPEC-163. A surface named there with no registry
    // row fails HERE, before the walk gets a chance to not-look-for-it.
    const contract: Record<FeatureFlagKey, string[]> = {
      files: [
        'Files',
        '/files',
        'Go to Files',
        'Files help section',
        // NOT in the spec's table — SPEC-167's link, recorded in its delivery doc.
        'Received files link on a notification',
        // NOT in SPEC-163's table either — the file-operations plane's own, recorded in its
        // delivery doc. A named control rather than a link gate, so the link exemption above
        // does not reach it.
        'Review conflicts on a notification',
        'Review conflicts on a notification that carries no link',
        'Send to another user',
        'Send files guide',
        // NOT in SPEC-163's table — SPEC-172's own, recorded in its delivery doc. Archive is a
        // Files sub-surface, so it goes with the file browser; its own switch holds these again.
        'Archive selected items',
        'Archive this item',
        'Restore Archived Data',
        'Archive and restore guide',
        // SPEC-190: the VIEW the control above opens. Under THIS flag rather than the async
        // switchover, so throwing that kill switch never turns a shipped notification's control
        // into a link to nothing.
        'Review conflicts for a file operation',
        // Three ways into the file browser from other features' screens.
        'View source files',
        'View in Files after saving results',
        'Open folder on a data quality report',
        'Create table guide',
        'Shared space files guide'
      ],
      query: [
        'Query',
        '/query',
        'Create table',
        'Refresh table',
        'Share table',
        // SPEC-179: the mirror image of "Create table" — a Data Explorer capability on a
        // Query surface, registered under both flags.
        'Explore data on the Query schema rail',
        'Explore in Data Explorer on a query result',
        // SPEC-173: added to the contract, like the two shared-workspace rows below —
        // a saved query is a FILE now, so the folder holding them is a Query surface
        // living on the file browser's screen.
        'saved_queries folder',
        // SPEC-183: the mirror of 'Explore data on the Query schema rail' — a saved-queries
        // capability on a Data Explorer surface, so it follows the store's flag.
        'Save as query',
        'Create view',
        // The twin of `Create view` on the Query toolbar: creating a Glue view is a Query
        // capability wherever the control lives, so an exemption here would hand back, through
        // a different door, the one thing turning this flag off is meant to remove.
        'Create view…',
        // The generated statement opened in a Query tab: a Query surface wearing a Data Explorer
        // control, on the same terms as the two above it.
        'Open in Query',
        'Open in Query in the Options menu',
        'Open saved view',
        'Query help section',
        'Tables help section',
        'Save an exploration guide under Query',
        'Refresh table link on a notification'
      ],
      sharedWorkspaces: [
        'Shared spaces',
        '/connections',
        'Your spaces navigation',
        'Add members',
        'Shared spaces recipient kind in the share dialog',
        // NOT in the spec's table — a deliberate extension, recorded in the delivery doc.
        'Shared databases in the schema rail',
        // SPEC-174: likewise an extension. Its spec offers "exactly the spaces
        // `useQuerySpaces()` returns"; leaving that ungated would name shared spaces in a
        // dropdown with every other shared-workspace surface hidden.
        'Shared spaces in the saved-queries selector',
        'Shared spaces in the save-query dialog',
        'Shared spaces as a move destination',
        'Shared connections help section',
        'Send to a shared space guide',
        'Share with a shared space guide',
        'Received files link to a space on a notification',
        'Shared spaces recipient kind in the send dialog',
        // SPEC-179: the Data Explorer's own reader of `useQuerySpaces`, on SPEC-174's
        // reasoning — the rows above render other surfaces entirely.
        'Shared spaces in the Data Explorer source picker',
        'Shared spaces in the saved-view drawer',
        // SPEC-183: the third instance of the same choice, and the second WRITE target.
        'Shared spaces in the Data Explorer save dialog',
        // SPEC-185: the export destination, and the Query workspace's Save-results twin,
        // which had been ungated since SPEC-055 because the hook built its own list.
        'Shared spaces in the Data Explorer export dialog',
        'Shared spaces in the save-results dialog',
        // Links naming a shared space other than by `?space=`, and the data-quality surfaces that
        // listed or rendered a shared space's checks with this flag off.
        'Refresh table link to a shared space on a notification',
        'Data quality link to a shared space on a notification',
        'Shared-space runs in the data quality list',
        'Shared-space data quality report'
      ],
      dataQuality: [
        'Data quality',
        '/data-quality',
        '/data-quality/:space/:requestId',
        'Check data quality of the selected item',
        'Data quality link on a notification',
        'Check data quality guide',
        'Past data quality checks guide',
        'Data quality report guide'
      ],
      dataExplorer: [
        'Data Explorer',
        '/explore',
        'Explore data',
        'Explore in Data Explorer',
        // SPEC-185's guides: the section and every guide in it, on the `files` precedent.
        'Data Explorer help section',
        'Start exploring guide',
        'Filter and sort guide',
        'Grouping and Calc guide',
        'Colors and Transformers guide',
        'Copy and export guide',
        'Data Explorer save formats guide under the Data Explorer',
        'Save an exploration guide',
        // The Query section's pointer to Filter by value: every step it names is a surface this
        // flag hides, so it follows this flag as well as its section's.
        'Filter by value guide under Query'
      ],
      // SPEC-190: a kill switch rather than an area. It hides the record of what this session
      // handed to the plane, and the guide for a round trip that only exists while the routing
      // does. It does not hide Copy/Move/Delete — with the flag off a single file still goes
      // synchronously, and a folder or multi-item selection leaves them disabled with a reason —
      // and a registry row can only assert presence or absence.
      asyncFileOperations: ['File operations in progress', 'Background file operations guide'],
      // SPEC-223: one control, two dialogs. The completion notification's link is deliberately
      // not here — it is a `/files` link, already covered by the row's link gate.
      resultsConversion: [
        'Format in the save-results dialog',
        'Format in the Data Explorer export dialog',
        'Save results formats guide',
        'Data Explorer save formats guide'
      ],
      // The second kill switch: the same archive surfaces the `files` entry holds, under
      // descriptive names because a name keys the walk. The folder details panel and the mobile
      // action bar are asserted beside the archive journey and the responsive tests instead.
      archive: [
        'Archive in the selection toolbar',
        'Archive in the details panel',
        'Restore Archived Data in the file browser',
        'Archive and restore guide under the archive switch'
      ]
    };
    for (const key of FEATURE_FLAG_KEYS) {
      expect(GATED_SURFACES[key].map((s) => s.name).sort(), key).toEqual([...contract[key]].sort());
    }
  });

  it('gives every guide row a help id that actually exists', () => {
    const known = new Set([
      ...HELP_SECTIONS.map((s) => s.id),
      ...HELP_SECTIONS.flatMap((s) => s.guides.map((g) => g.id))
    ]);
    for (const surface of Object.values(GATED_SURFACES).flat()) {
      if (surface.kind !== 'guide') continue;
      expect(surface.helpId, `${surface.name} has no helpId`).toBeDefined();
      expect(known.has(surface.helpId!), `${surface.helpId} is not a help section or guide`).toBe(true);
      // A recipe that loses its longer wait passes alone and fails only under load, so it is held here.
      const insideSection = HELP_SECTIONS.some((s) => s.guides.some((g) => g.id === surface.helpId));
      expect(Boolean(RECIPES[surface.name]?.selectsSection), `${surface.name} selectsSection`).toBe(insideSection);
    }
  });
});
