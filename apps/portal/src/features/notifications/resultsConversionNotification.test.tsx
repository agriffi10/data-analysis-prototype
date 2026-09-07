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
 * **What this half can and cannot prove.** It proves the row renders the plane's sentence as
 * plain text — unlinked, untruncated, whole. It CANNOT prove the sentence is still the plane's:
 * the literal is fed in as the notification's `message` and read back out, which holds for any
 * string at all, so drift between the two languages is invisible from here.
 *
 * The gate that closes that is on the Python side, where the sentence can actually be produced:
 * `test_the_row_limit_refusal_is_the_sentence_the_browser_renders` in
 * `lambdas/results-conversion-common/test_plane_results_conversion.py` renders it for real and
 * compares it against the literal below, read out of THIS file. Change the plane's wording, the
 * Python golden, or this copy, and `pytest lambdas/` fails — which is why the literal is one
 * template literal on one line, and why the apostrophe is ASCII.
 */
// ONE template literal, on ONE line, and each of those is load-bearing for the Python gate that
// compares this against the sentence the plane really produces. One literal, because that gate
// reads the VALUE between the backticks rather than re-implementing TypeScript concatenation —
// it refuses anything else rather than guess. One line, so nothing has to reassemble it.
// Backticks, so neither the apostrophe nor the inner quotes need escaping: an escaped quote
// would put bytes in this file the produced sentence does not have. The apostrophe is ASCII,
// which is what the plane emits; the portal’s own authored wording uses a curly one, and a
// curly apostrophe here would agree with nothing.
const GOLDEN_ROW_LIMIT = `Couldn't save the query results as Excel: the results have 1,400,000 rows, which is more than a spreadsheet can hold, so "q1.xlsx" was not written. Please save them as Parquet instead, or narrow the query.`;

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

  it('refreshes the same folder when the sibling Review conflicts control is the way in', async () => {
    // `reviewHref` is this same path plus a request id, so it lands on the same listing — which
    // makes a user who arrived that way the one person an anchor-only refresh would miss.
    const {user, queryClient} = renderRow(
      note({
        link: '/files?prefix=alice/reports/',
        payload: {requestId: 'req-1', conflicts: [{itemKey: 'alice/reports/a.csv'}]}
      })
    );
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    await user.click(screen.getByRole('link', {name: 'Review conflicts'}));

    expect(invalidate).toHaveBeenCalledWith({queryKey: fileBrowserKeys.list('user-space', 'alice/reports/')});
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
