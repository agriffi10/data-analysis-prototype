import {describe, it, expect, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {authenticated} from '../../test/authFixtures';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
vi.mock('../DataQualityPage', () => ({default: () => <h1>Data quality runs</h1>}));
vi.mock('../DataQualityReportPage', () => ({default: () => <h1>A data quality report</h1>}));

describe('the data-quality area', () => {
  // Served from whichever router the area's record names, so the move that changes it does not
  // redden these.
  it.each([
    ['/data-quality', 'Data quality runs'],
    ['/data-quality/alice/req-1', 'A data quality report']
  ])('serves %s inside the shell', async (path, heading) => {
    renderApp(path, {auth: authenticated('alice')});

    expect(await screen.findByRole('heading', {name: heading})).toBeInTheDocument();
    expect(screen.getByRole('link', {name: 'Files'})).toBeInTheDocument();
  });
});
