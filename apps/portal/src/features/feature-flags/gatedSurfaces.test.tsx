import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {GATED_SURFACES} from './gatedSurfaces';
import {FEATURE_FLAG_KEYS} from './featureFlagDefaults';
import {getFeatureFlags} from './featureFlags.service';
import {useFeature} from './useFeature';
import type {FeatureFlagKey, FeatureFlags} from './featureFlags.types';

/**
 * THE WALKING TEST (SPEC-163 FR-002).
 *
 * Every row in `GATED_SURFACES` is rendered twice — flag off, then flag on — and asserted by
 * ACCESSIBLE NAME. That is the whole design: a per-component gating pass finds the tabs and
 * the routes and ships the fourth cross-feature entry point visible, because nobody
 * remembers that "Create table" is a Query feature living on a file-browser toolbar.
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
  objectExists: vi.fn(),
  uploadFile: vi.fn(),
  createFolder: vi.fn()
}));
vi.mock('../file-browser/fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn().mockResolvedValue({success: true, data: {requestId: 'r1'}})
}));
vi.mock('../notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));
vi.mock('../query/glue.service', () => ({
  getDatabase: vi.fn().mockResolvedValue({success: true, data: {name: 'alice'}}),
  listTables: vi.fn().mockResolvedValue({
    success: true,
    data: [{name: 'sales', tableType: 'EXTERNAL_TABLE', location: 's3://b/alice/sales/', columns: []}]
  })
}));
vi.mock('../user-directory/userDirectory.service', () => ({
  DIRECTORY_KEY: '_directory/usernames.json',
  getUserDirectory: vi.fn().mockResolvedValue({success: true, data: {usernames: [], generatedAt: null}})
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'id-token'})
}));

import {Header} from '../../components/Header';
import {FileBrowser} from '../file-browser/FileBrowser';
import {UploadQueueProvider} from '../file-browser';
import {DatabaseNode} from '../query/DatabaseNode';
import {QueryToolbar} from '../query/QueryToolbar';
import {TableShareDialog} from '../table-share/TableShareDialog';
import {ManageMembersDrawer} from '../shared-spaces/ManageMembersDrawer';
import {Sidebar} from '../connections/Sidebar';
import {SchemaBrowser} from '../query/SchemaBrowser';
import {HelpPage} from '../help/HelpPage';
import {HELP_SECTIONS} from '../help/helpContent';
import {FeatureRoute} from '../../routes/FeatureRoute';
import {listFiles} from '../file-browser/fileBrowser.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {Connection} from '../connections/connection.types';

const ALL_ON: FeatureFlags = {files: true, query: true, sharedWorkspaces: true, dataQuality: true};

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

const SHARED: Connection = {
  id: 'teamspace',
  kind: 'shared',
  label: 'teamspace',
  database: 'teamspace',
  status: 'active'
} as Connection;

beforeEach(() => {
  vi.clearAllMocks();
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
    data: {spaces: [{name: 'teamspace', status: 'active', role: 'member'}]}
  } as never);
});

afterEach(() => {
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
};

const renderHeader = () => {
  renderWithProviders(<Header />, {auth: authenticated('alice'), seedFeatureFlags: false});
};

const renderFileBrowser = () => {
  renderWithProviders(
    <UploadQueueProvider>
      <FileBrowser
        bucket="user-space"
        rootPrefix="alice/"
        username="alice"
        writable
        spaceKind="personal"
      />
    </UploadQueueProvider>,
    {auth: authenticated('alice'), seedFeatureFlags: false}
  );
};

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
  render: () => {
    renderWithProviders(<HelpPage />, {auth: authenticated('alice'), seedFeatureFlags: false});
  },
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
    // A guide INSIDE a section: select its owning section first, then look for its card.
    const owner = HELP_SECTIONS.find((s) => s.guides.some((g) => g.id === helpId));
    if (!owner) throw new Error(`no help section or guide with id ${helpId}`);
    const guide = owner.guides.find((g) => g.id === helpId)!;
    return screen.queryByRole('button', {name: new RegExp(guide.title, 'i')});
  }
});

const RECIPES: Record<string, Recipe> = {
  // ── nav ──
  Files: {render: renderHeader, find: byRole('link', 'Files')},
  Query: {render: renderHeader, find: byRole('link', 'Query')},
  Connections: {render: renderHeader, find: byRole('link', 'Connections')},
  'Data quality': {render: renderHeader, find: byRole('link', 'Data quality')},

  // ── routes ──
  '/files': routeRecipe('files'),
  '/query': routeRecipe('query'),
  '/connections': routeRecipe('sharedWorkspaces'),
  '/data-quality': routeRecipe('dataQuality'),
  '/data-quality/:space/:requestId': routeRecipe('dataQuality'),

  // ── controls ──
  'Go to Dashboard': {
    render: async () => {
      const {default: LandingPage} = await import('../../routes/LandingPage');
      renderWithProviders(<LandingPage />, {auth: authenticated('alice'), seedFeatureFlags: false});
    },
    find: byRole('button', /^Go to /)
  },
  'Create table': {render: renderFileBrowser, find: byRole('button', 'Create table')},
  'Check data quality of the selected item': {
    render: renderFileBrowser,
    find: byRole('button', 'Check data quality of the selected item')
  },
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
          preset="even"
          onPresetChange={vi.fn()}
          isInFlight={false}
          canRun
          canClear
          canSave
          onClear={vi.fn()}
          onSave={vi.fn()}
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
    render: () => {
      renderWithProviders(<SpacesRailHost />, {auth: authenticated('alice'), seedFeatureFlags: false});
    },
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
        />,
        {auth: authenticated('alice'), seedFeatureFlags: false}
      );
    },
    find: byRole('button', 'Add members')
  },
  'Shared spaces': {
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
  'Shared databases in the schema rail': {
    render: () => {
      renderWithProviders(<SchemaRailHost />, {auth: authenticated('alice'), seedFeatureFlags: false});
    },
    find: async () => screen.queryByRole('button', {name: /teamspace/})
  },

  // ── guides ──
  'Files help section': helpRecipe('files'),
  'Query help section': helpRecipe('query'),
  'Tables help section': helpRecipe('tables'),
  'Shared connections help section': helpRecipe('shared-connections'),
  'Check data quality guide': helpRecipe('check-data-quality'),
  'Past data quality checks guide': helpRecipe('past-data-quality-checks')
};

/**
 * The spaces rail exactly as `FilesPage` mounts it — behind the `sharedWorkspaces` gate.
 *
 * Rendering the whole page here would drag in the file browser's entire service surface for
 * one `<aside>`; what is under test is the gate, and the gate is this condition.
 */
function SpacesRailHost() {
  const enabled = useFeature('sharedWorkspaces');
  return enabled ? (
    <Sidebar
      connections={[PERSONAL, SHARED]}
      activeSpaceId="personal"
      onSelectSpace={vi.fn()}
    />
  ) : null;
}

/** The schema rail's connection list, filtered exactly as `QueryWorkspace` filters it. */
function SchemaRailHost() {
  const enabled = useFeature('sharedWorkspaces');
  const connections = enabled ? [PERSONAL, SHARED] : [PERSONAL, SHARED].filter((c) => c.kind === 'personal');
  return (
    <SchemaBrowser
      connections={connections}
      actions={tableActionsStub()}
    />
  );
}

function tableActionsStub() {
  return {
    onViewSourceFiles: vi.fn(),
    canViewSourceFiles: () => true,
    onViewDdl: vi.fn(),
    onViewData: vi.fn(),
    onRefreshTable: vi.fn(),
    onShareTable: vi.fn(),
    onDropTable: vi.fn()
  } as never;
}

async function openTableMenu() {
  const trigger = await screen.findByRole('button', {name: 'Options for sales'});
  trigger.click();
}

// ─── The walk ───────────────────────────────────────────────────────────────

describe('every registered surface disappears with its flag off and returns with it on', () => {
  const rows = (Object.entries(GATED_SURFACES) as [FeatureFlagKey, (typeof GATED_SURFACES)[FeatureFlagKey]][]).flatMap(
    ([flag, surfaces]) => surfaces.map((surface) => ({flag, surface}))
  );

  it.each(rows.map((row) => [row.flag, row.surface.name, row] as const))(
    '%s off hides "%s"',
    async (flag, _name, row) => {
      const recipe = RECIPES[row.surface.name];
      withFlags({[flag]: false});
      await recipe.render();
      await waitFor(async () => expect(await recipe.find()).toBeNull());
    }
  );

  it.each(rows.map((row) => [row.flag, row.surface.name, row] as const))(
    '%s on shows "%s"',
    async (_flag, _name, row) => {
      const recipe = RECIPES[row.surface.name];
      withFlags({});
      await recipe.render();
      await waitFor(async () => expect(await recipe.find()).not.toBeNull());
    }
  );
});

// ─── Guard the guard (FR-002 AC4) ───────────────────────────────────────────

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
      files: ['Files', '/files', 'Go to Dashboard', 'Files help section'],
      query: [
        'Query',
        '/query',
        'Create table',
        'Refresh table',
        'Share table',
        'Create view',
        'Query help section',
        'Tables help section'
      ],
      sharedWorkspaces: [
        'Connections',
        '/connections',
        'Your spaces navigation',
        'Add members',
        'Shared spaces',
        // NOT in the spec's table — a deliberate extension, recorded in the delivery doc.
        'Shared databases in the schema rail',
        'Shared connections help section'
      ],
      dataQuality: [
        'Data quality',
        '/data-quality',
        '/data-quality/:space/:requestId',
        'Check data quality of the selected item',
        'Check data quality guide',
        'Past data quality checks guide'
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
    }
  });
});
