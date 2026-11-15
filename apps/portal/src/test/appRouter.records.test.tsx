import {screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {useAreaRecords} from '../lib/navigation';
import {renderApp} from './appRouter';
import {authenticated} from './authFixtures';
import {renderWithProviders} from './renderWithProviders';

// Help's production record says the App Router serves it, as it will once its move lands, so each
// test below shows whether the harness followed that record or its fixture.
vi.mock('../lib/navigation/areas/help', () => ({
  helpArea: {area: 'help', paths: ['/help'], router: 'app'}
}));

const pages = {
  '(signed-in)/help/page.tsx': () => <h1>App Router help</h1>,
  '[[...slug]]/page.tsx': () => <h1>Catch-all page</h1>
};

/** The router the records in force say serves Help. */
function HelpRouter() {
  return <p>{useAreaRecords().find((record) => record.area === 'help')?.router}</p>;
}

describe('the records a test runs on', () => {
  it('are the catch-all fixture through renderApp, whatever a production record says', async () => {
    renderApp('/help', {auth: authenticated('alice'), pages});

    expect(await screen.findByRole('heading', {name: 'Catch-all page'})).toBeInTheDocument();
  });

  it('are the production records through renderApp when a test asks for them', async () => {
    renderApp('/help', {auth: authenticated('alice'), pages, routers: 'as-recorded'});

    expect(await screen.findByRole('heading', {name: 'App Router help'})).toBeInTheDocument();
  });

  it('are the catch-all fixture through renderWithProviders', () => {
    renderWithProviders(<HelpRouter />);

    expect(screen.getByText('catch-all')).toBeInTheDocument();
  });
});
