import {describe, expect, it, vi} from 'vitest';
import {screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import type {ArchiveListing} from '../../types/archive.types';
import {ArchiveList} from './ArchiveList';

const NAMED = '11111111-1111-4111-8111-111111111111';
const UNNAMED = '22222222-2222-4222-8222-222222222222';
const UNLABELLED = '33333333-3333-4333-8333-333333333333';

function listing(archiveId: string, overrides: Partial<NonNullable<ArchiveListing['details']>> = {}): ArchiveListing {
  return {
    archiveId,
    details: {
      name: null,
      archivedAt: '2026-09-01T10:00:00.000Z',
      archivedBy: 'alice',
      items: [
        {kind: 'folder', path: 'reports/'},
        {kind: 'file', path: 'q1.csv'}
      ],
      itemCount: 3,
      fileCount: 1204,
      totalBytes: 2048,
      restore: null,
      ...overrides
    }
  };
}

function renderList(props: Partial<Parameters<typeof ArchiveList>[0]> = {}) {
  const onSelect = vi.fn();
  const onRetry = vi.fn();
  const result = renderWithProviders(
    <ArchiveList
      status="ready"
      listings={[]}
      selectedId={null}
      onSelect={onSelect}
      showArchivedBy={false}
      onRetry={onRetry}
      {...props}
    />
  );
  return {onSelect, onRetry, ...result};
}

describe('ArchiveList', () => {
  it('names each archive, says what it held, and shows an unlabelled one by its whole id', async () => {
    const user = userEvent.setup();
    const {onSelect} = renderList({
      listings: [listing(NAMED, {name: 'Q1 reports'}), listing(UNNAMED), {archiveId: UNLABELLED, details: null}],
      showArchivedBy: true
    });

    const named = screen.getByRole('radio', {name: 'Q1 reports'});
    expect(named).toHaveAccessibleDescription(
      'Archived Sep 1, 2026 · reports/, q1.csv and 1 more · 1,204 files, 2.0 KB · by alice'
    );
    expect(screen.getByRole('radio', {name: 'reports/, q1.csv and 1 more'})).toHaveAccessibleDescription(
      /^Archived Sep 1, 2026 · 1,204 files, 2.0 KB · by alice$/
    );
    expect(screen.getByRole('radio', {name: 'Archive 33333333'})).toHaveAccessibleDescription(
      `Details unavailable · ${UNLABELLED}`
    );

    await user.click(screen.getByText('Q1 reports'));
    expect(onSelect).toHaveBeenCalledWith(NAMED);
  });

  it('says who archived it only in a shared space', () => {
    renderList({listings: [listing(NAMED, {name: 'Q1'})], showArchivedBy: false});

    expect(screen.getByRole('radio', {name: 'Q1'})).not.toHaveAccessibleDescription(/by alice/);
  });

  it('disables only an archive a restore has finished with, and says what each restore did without judging the archive', () => {
    renderList({
      listings: [
        listing(NAMED, {
          name: 'Restored',
          restore: {status: 'restored', requestedAt: '2026-09-02T08:00:00Z', updatedAt: '2026-09-03T08:00:00Z'}
        }),
        listing(UNNAMED, {
          name: 'Requested',
          restore: {status: 'requested', requestedAt: '2026-09-02T08:00:00Z', updatedAt: '2026-09-02T08:00:00Z'}
        }),
        listing(UNLABELLED, {
          name: 'Incomplete',
          restore: {status: 'incomplete', requestedAt: '2026-09-02T08:00:00Z', updatedAt: '2026-09-04T08:00:00Z'}
        })
      ]
    });

    expect(screen.getByRole('radio', {name: 'Restored'})).toBeDisabled();
    expect(screen.getByRole('radio', {name: 'Requested'})).toBeEnabled();
    expect(screen.getByRole('radio', {name: 'Incomplete'})).toBeEnabled();
    const statuses = [
      screen.getByText('Restored Sep 3, 2026'),
      screen.getByText('Restore requested Sep 2, 2026'),
      screen.getByText('Last restore did not finish (Sep 4, 2026)')
    ];
    for (const status of statuses) expect(status.textContent).not.toMatch(/intact|safe|complete|gone/i);
  });

  it('shows loading, empty and a retryable failure', async () => {
    const user = userEvent.setup();
    const {rerender, onRetry} = renderList({status: 'loading'});
    expect(screen.getByRole('status')).toHaveTextContent('Loading archives…');

    rerender(
      <ArchiveList
        status="ready"
        listings={[]}
        selectedId={null}
        onSelect={vi.fn()}
        showArchivedBy={false}
        onRetry={onRetry}
      />
    );
    expect(screen.getByText('This space has no archives yet.')).toBeInTheDocument();

    rerender(
      <ArchiveList
        status="error"
        listings={[]}
        selectedId={null}
        onSelect={vi.fn()}
        showArchivedBy={false}
        onRetry={onRetry}
      />
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Couldn’t load this space’s archives.');
    await user.click(screen.getByRole('button', {name: 'Try again'}));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('has no axe violations with a row of each kind', async () => {
    const {container} = renderList({
      listings: [listing(NAMED, {name: 'Q1'}), {archiveId: UNLABELLED, details: null}],
      selectedId: NAMED
    });

    expect(within(container).getAllByRole('radio')).toHaveLength(2);
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
