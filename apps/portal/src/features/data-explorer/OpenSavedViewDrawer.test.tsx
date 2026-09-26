import {beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {listSavedQueries} from '../saved-queries/savedQueries.service';
import {OpenSavedViewDrawer} from './OpenSavedViewDrawer';
import type {QuerySpace} from '../catalog/catalog.types';
import type {SavedQuery} from '../saved-queries/savedQueries.types';

vi.mock('../saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../saved-queries/savedQueries.service')>()),
  listSavedQueries: vi.fn()
}));

const PERSONAL: QuerySpace = {
  id: 'personal',
  label: 'alice',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};
const TEAM: QuerySpace = {
  id: 'teamspace',
  label: 'teamspace',
  bucket: 'shared-space',
  rootPrefix: 'teamspace/',
  rootLabel: 'teamspace'
};
const ok = <T,>(data: T) => ({success: true as const, data});

const file = (n: number): SavedQuery => ({
  spaceId: 'personal',
  bucket: 'user-space',
  key: `alice/saved_queries/View ${n}.sql`,
  name: `View ${n}`,
  updatedAt: '2026-09-20T00:00:00.000Z',
  size: 100
});

function render(over: Partial<Parameters<typeof OpenSavedViewDrawer>[0]> = {}) {
  const props = {
    spaces: [PERSONAL, TEAM],
    space: PERSONAL,
    onSelectSpace: vi.fn(),
    openingKey: null,
    onOpen: vi.fn(),
    onClose: vi.fn(),
    ...over
  };
  const view = renderWithProviders(<OpenSavedViewDrawer {...props} />, {auth: authenticated('alice')});
  return {...view, props};
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('OpenSavedViewDrawer', () => {
  it('lists a space’s saved queries ten to a page, opens one, and asks for another space', async () => {
    vi.mocked(listSavedQueries).mockResolvedValue(
      ok({queries: Array.from({length: 11}, (_, i) => file(i + 1)), isTruncated: false})
    );
    const {user, props} = render();

    expect(await screen.findAllByRole('button', {name: /^Open saved view View/})).toHaveLength(10);
    expect(screen.getByText('1–10 of 11')).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Open saved view View 3'}));
    await user.selectOptions(screen.getByRole('combobox'), 'teamspace');

    expect(props.onOpen).toHaveBeenCalledWith(file(3), PERSONAL);
    expect(props.onSelectSpace).toHaveBeenCalledWith('teamspace');
  });

  it('says a folder is empty, and offers to try again when the listing fails', async () => {
    vi.mocked(listSavedQueries).mockResolvedValueOnce(ok({queries: [], isTruncated: false}));
    const {unmount} = render();
    expect(await screen.findByText('No saved queries in alice yet.')).toBeInTheDocument();
    unmount();

    vi.mocked(listSavedQueries).mockResolvedValue({success: false, error: {message: 'no', code: 'AccessDenied'}});
    const {user} = render();
    const banner = await screen.findByText('Couldn’t load saved queries.');
    const calls = vi.mocked(listSavedQueries).mock.calls.length;
    await user.click(within(banner.closest('[role="alert"]') as HTMLElement).getByRole('button', {name: 'Try again'}));

    await waitFor(() => expect(vi.mocked(listSavedQueries).mock.calls.length).toBe(calls + 1));
  });

  it('closes on Escape and on its close control, and is axe-clean as driven', async () => {
    vi.mocked(listSavedQueries).mockResolvedValue(ok({queries: [file(1)], isTruncated: false}));
    const {user, props, container} = render();
    await screen.findByRole('button', {name: 'Open saved view View 1'});

    await expectContainerHasNoA11yViolations(container.ownerDocument.body, COMPONENT_AXE_OPTIONS);
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', {name: 'Close open saved view'}));

    expect(props.onClose).toHaveBeenCalledTimes(2);
  });
});
