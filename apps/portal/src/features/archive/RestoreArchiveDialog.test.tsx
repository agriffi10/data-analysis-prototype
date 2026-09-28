import {beforeEach, describe, expect, it, vi} from 'vitest';
import {QueryClient} from '@tanstack/react-query';
import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {apiFailure, documentBody, mockApi} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {politeAnnouncements} from '../../test/liveRegions';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import type {ArchiveListing, ArchiveSpace} from '../../types/archive.types';
import {RestoreArchiveDialog} from './RestoreArchiveDialog';
import {archiveKeys} from './useArchive';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

const SPACE: ArchiveSpace = {kind: 'personal', name: 'alice'};
const PREFIX = 'alice/system_settings/archive/';
const Q1 = '11111111-1111-4111-8111-111111111111';
const OLD = '22222222-2222-4222-8222-222222222222';
const TYPED = '3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93';

function folders(...ids: string[]) {
  return foldersUnder(PREFIX, ...ids);
}

function foldersUnder(prefix: string, ...ids: string[]) {
  return {
    success: true as const,
    data: {
      items: ids.map((id) => ({kind: 'folder' as const, key: `${prefix}${id}/`, size: null, lastModified: null})),
      nextToken: null
    }
  };
}

const INDEX = {
  version: 1,
  archives: [
    {
      archiveId: Q1,
      name: 'Q1 reports',
      archivedAt: '2026-09-01T10:00:00.000Z',
      archivedBy: 'alice',
      items: [{kind: 'folder', path: 'reports/'}],
      itemCount: 1,
      fileCount: 3,
      totalBytes: 10,
      restore: null
    }
  ]
};

let api: ApiMock;

beforeEach(async () => {
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bkt');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bkt');
  const {apiRequest} = await import('../../lib/apiClient');
  api = mockApi(vi.mocked(apiRequest));
  api.on('objects.list', folders(Q1, OLD));
  api.on('objects.readContent', documentBody(INDEX));
});

function renderDialog(overrides: Partial<Parameters<typeof RestoreArchiveDialog>[0]> = {}, queryClient?: QueryClient) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const result = renderWithProviders(
    <RestoreArchiveDialog
      space={SPACE}
      spaceLabel="My Files"
      busy={false}
      submitError={null}
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...overrides}
    />,
    queryClient ? {queryClient} : {}
  );
  return {onSubmit, onCancel, ...result};
}

async function openIdMode(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', {name: 'Restore by archive id instead'}));
  return screen.getByLabelText('Archive id');
}

describe('RestoreArchiveDialog — the list', () => {
  it('restores the archive picked, and refuses rather than guessing when none is', async () => {
    const user = userEvent.setup();
    const {onSubmit} = renderDialog();

    await user.click(screen.getByRole('button', {name: 'Restore'}));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose an archive to restore.');
    expect(onSubmit).not.toHaveBeenCalled();

    await user.click(await screen.findByRole('radio', {name: 'Q1 reports'}));
    await user.click(screen.getByRole('button', {name: 'Restore'}));

    expect(onSubmit).toHaveBeenCalledWith(Q1);
    expect(screen.queryByText('Choose an archive to restore.')).not.toBeInTheDocument();
    expect(screen.getByRole('radio', {name: 'Archive 22222222'})).toBeInTheDocument();
  });

  it('opens on the list heading rather than a radio, and Enter on a radio restores nothing', async () => {
    const user = userEvent.setup();
    const seeded = new QueryClient({defaultOptions: {queries: {retry: false}}});
    const listings: ArchiveListing[] = [{archiveId: OLD, details: null}];
    seeded.setQueryData(archiveKeys.list(SPACE), listings);
    const {onSubmit} = renderDialog({}, seeded);

    expect(screen.getByRole('radio', {name: 'Archive 22222222'})).toBeInTheDocument();
    expect(screen.getByRole('heading', {name: 'Choose an archive'})).toHaveFocus();

    await user.click(screen.getByRole('radio', {name: 'Archive 22222222'}));
    await user.keyboard('{Enter}');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('keeps the heading focused when the list arrives after the dialog opened', async () => {
    renderDialog();

    await screen.findByRole('radio', {name: 'Q1 reports'});

    expect(screen.getByRole('heading', {name: 'Choose an archive'})).toHaveFocus();
  });

  it('offers a retry when the archives cannot be listed', async () => {
    const user = userEvent.setup();
    api.onEach('objects.list', [apiFailure('InternalError'), folders(Q1)]);
    renderDialog();

    expect(await screen.findByText('Couldn’t load this space’s archives.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Try again'}));

    expect(await screen.findByRole('radio', {name: 'Q1 reports'})).toBeInTheDocument();
  });

  it('keeps the rows it has when a later read of the list fails', async () => {
    const seeded = new QueryClient({defaultOptions: {queries: {retry: false}}});
    seeded.setQueryData(archiveKeys.list(SPACE), [{archiveId: OLD, details: null}] satisfies ArchiveListing[]);
    api.on('objects.list', apiFailure('InternalError'));
    renderDialog({}, seeded);

    await vi.waitFor(() => expect(seeded.getQueryState(archiveKeys.list(SPACE))?.errorUpdateCount).toBe(1));

    expect(screen.getByRole('radio', {name: 'Archive 22222222'})).toBeInTheDocument();
    expect(screen.queryByText('Couldn’t load this space’s archives.')).not.toBeInTheDocument();
  });

  it('says who made each archive in a shared space, and not in a personal one', async () => {
    api.on('objects.list', foldersUnder('team/system_settings/archive/', Q1));
    const {unmount} = renderDialog({space: {kind: 'shared', name: 'team'}});
    expect(await screen.findByRole('radio', {name: 'Q1 reports'})).toHaveAccessibleDescription(/by alice$/);
    unmount();

    api.on('objects.list', folders(Q1));
    renderDialog();
    expect(await screen.findByRole('radio', {name: 'Q1 reports'})).not.toHaveAccessibleDescription(/by alice/);
  });

  it('reads the list afresh on every opening, however long the app keeps other queries fresh', async () => {
    const patient = new QueryClient({defaultOptions: {queries: {retry: false, staleTime: 30_000}}});
    patient.setQueryData(archiveKeys.list(SPACE), [{archiveId: OLD, details: null}] satisfies ArchiveListing[]);

    renderDialog({}, patient);

    await vi.waitFor(() => expect(api.countOf('objects.list')).toBe(1));
  });

  it('has no axe violations with the list loaded', async () => {
    const {container} = renderDialog();

    await screen.findByRole('radio', {name: 'Q1 reports'});

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});

describe('RestoreArchiveDialog — restoring by id instead', () => {
  it('is one link away in every state of the list', async () => {
    api.onEach('objects.list', [apiFailure('InternalError')]);
    const {unmount} = renderDialog();
    expect(screen.getByRole('status')).toHaveTextContent('Loading archives…');
    expect(screen.getByRole('button', {name: 'Restore by archive id instead'})).toBeInTheDocument();
    await screen.findByText('Couldn’t load this space’s archives.');
    expect(screen.getByRole('button', {name: 'Restore by archive id instead'})).toBeInTheDocument();
    unmount();

    api.on('objects.list', folders());
    renderDialog();
    await screen.findByText('This space has no archives yet.');
    expect(screen.getByRole('button', {name: 'Restore by archive id instead'})).toBeInTheDocument();
  });

  it('takes a typed id from Enter in the field, trimmed, and focuses the field', async () => {
    const user = userEvent.setup();
    const {onSubmit} = renderDialog();

    const field = await openIdMode(user);
    expect(field).toHaveFocus();
    await user.type(field, `  ${TYPED}  {Enter}`);

    expect(onSubmit).toHaveBeenCalledWith(TYPED);
  });

  it('refuses a malformed id only once the user has tried, naming what a valid one looks like', async () => {
    const user = userEvent.setup();
    const {onSubmit} = renderDialog();

    const field = await openIdMode(user);
    await user.type(field, 'not-an-id');
    expect(field).not.toBeInvalid();
    await user.click(screen.getByRole('button', {name: 'Restore'}));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(field).toHaveAccessibleDescription(/doesn’t look like an archive id.*3f8a1c2e/i);
    expect(politeAnnouncements()).toEqual([expect.stringMatching(/^Archive id: That doesn’t look like an archive id/)]);
    expect(screen.getByText(/find the id/i)).toHaveTextContent(/system_settings/);
  });

  it('goes back to the list with the choice still made, and focus on the heading', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(await screen.findByRole('radio', {name: 'Q1 reports'}));
    await openIdMode(user);
    await user.click(screen.getByRole('button', {name: 'Back to the list'}));

    expect(screen.getByRole('radio', {name: 'Q1 reports'})).toBeChecked();
    expect(screen.getByRole('heading', {name: 'Choose an archive'})).toHaveFocus();
  });

  it('has no axe violations while showing its inline error', async () => {
    const user = userEvent.setup();
    const {container} = renderDialog();

    await user.type(await openIdMode(user), 'nope');
    await user.click(screen.getByRole('button', {name: 'Restore'}));

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});

describe('RestoreArchiveDialog — what it says and how it holds', () => {
  it('names the space the restore lands in and says it takes hours', () => {
    renderDialog({spaceLabel: 'finance'});

    expect(screen.getByText('finance')).toBeInTheDocument();
    expect(screen.getByText(/several hours/i)).toBeInTheDocument();
  });

  it('locks while the enqueue is in flight, and shows a failure inline', async () => {
    const user = userEvent.setup();
    const {onCancel} = renderDialog({busy: true, submitError: 'Restoring is not configured'});

    expect(screen.getByRole('button', {name: 'Starting…'})).toBeDisabled();
    await user.keyboard('{Escape}');
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByText('Restoring is not configured')).toBeInTheDocument();
  });
});
