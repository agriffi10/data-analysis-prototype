import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {fileBrowserKeys} from '../file-browser/fileBrowserKeys';
import {NotificationRow} from './NotificationRow';
import type {Notification} from './notifications.types';

// `spaceBuckets` and NOT the two single getters: it reads the runtime config itself rather than
// calling them, so mocking those leaves it answering `{user: undefined, shared: undefined}` and
// the link resolves to no bucket at all.
vi.mock('../../lib/userSpace', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/userSpace')>()),
  spaceBuckets: () => ({user: 'user-space', shared: 'shared-space'})
}));

/**
 * The browser's half of a two-language assertion on the row-limit refusal.
 *
 * `rccommon/messages.py` composes this sentence and the Python suite asserts it, which proves
 * the producer is consistent with itself. What it cannot prove is that the wording registered
 * on the plane is the wording a user READS — that needs the row rendering it. So the same
 * string is written out on both sides, deliberately duplicated rather than shared through a
 * fixture file, since a shared file both halves read would go stale together. The Python copy
 * is `GOLDEN_ROW_LIMIT` in `lambdas/results-conversion-common/test_plane_results_conversion.py`;
 * change one and this fails.
 */
const GOLDEN_ROW_LIMIT =
  // ASCII apostrophe, byte for byte what the plane emits. The portal's own authored copy uses a
  // curly one, and a curly apostrophe here would make this string agree with nothing at all —
  // the two halves would each pass against themselves while the sentence differed.
  "Couldn't save the query results as Excel: the results have 1,400,000 rows, which is more " +
  'than a spreadsheet can hold, so "q1.xlsx" was not written. Please save them as Parquet ' +
  'instead, or narrow the query.';

const note = (over: Partial<Notification> = {}): Notification => ({
  id: 'n1',
  message: 'Saved 1,234 rows as Parquet to "q1.parquet".',
  read: false,
  timestamp: new Date(Date.now() - 60_000).toISOString(),
  ...over
});

function renderRow(notification: Notification) {
  return renderWithProviders(
    <ul>
      <NotificationRow
        notification={notification}
        onMarkRead={vi.fn()}
      />
    </ul>,
    {route: '/notifications'}
  );
}

describe('a results-conversion notification (SPEC-223 FR-004)', () => {
  it.each([
    ['a personal destination', '/files?prefix=alice/reports/', 'user-space', 'alice/reports/'],
    ['a shared destination', '/files?space=finance&prefix=finance/out/', 'shared-space', 'finance/out/']
  ])('refreshes the folder it lands on when the link is followed — %s', async (_case, link, bucket, prefix) => {
    // The bucket is not in the link and never will be, so this is the translation being
    // asserted as much as the invalidation: both variants, because which bucket a link
    // resolves to is decided by the presence of `?space=` and nothing else.
    const {user, queryClient} = renderRow(note({link}));
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    await user.click(screen.getByRole('link', {name: 'Saved 1,234 rows as Parquet to "q1.parquet".'}));

    expect(invalidate).toHaveBeenCalledWith({queryKey: fileBrowserKeys.list(bucket, prefix)});
  });

  it('renders the plane’s row-limit sentence verbatim, naming the count and suggesting Parquet', () => {
    renderRow(note({message: GOLDEN_ROW_LIMIT, link: undefined}));

    const shown = screen.getByText(GOLDEN_ROW_LIMIT);
    expect(shown).toBeInTheDocument();
    // Named individually as well as in the golden, because those two are what make the sentence
    // actionable — a user who cannot see the count does not know how far over they are, and one
    // who is not told about Parquet has no next step.
    expect(shown).toHaveTextContent('1,400,000 rows');
    expect(shown).toHaveTextContent('save them as Parquet instead');
  });

  it('renders neither a column name nor the SQL, even when the payload carries both', () => {
    renderRow(
      note({
        message: 'Saved 1,234 rows as Parquet to "q1.parquet".',
        link: '/files?prefix=alice/reports/',
        // Neither field is one this row reads. The assertion is that they stay unread rather
        // than that they are absent from the fixture.
        payload: {
          requestId: 'req-1',
          ...({column: 'salary', sql: 'SELECT salary FROM payroll'} as object)
        }
      })
    );

    // POSITIVE CONTROL first: without it the two absences below pass on a row that rendered
    // nothing at all, which is the way an absence assertion goes quiet.
    expect(screen.getByRole('link', {name: 'Saved 1,234 rows as Parquet to "q1.parquet".'})).toBeInTheDocument();
    expect(screen.queryByText(/salary/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SELECT/)).not.toBeInTheDocument();
  });
});
