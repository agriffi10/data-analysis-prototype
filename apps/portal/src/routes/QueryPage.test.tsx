import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated} from '../test/authFixtures';

// The lazy Monaco editor is stubbed to a plain textarea so the route renders
// without the editor chunk / web workers (react.md §21 "stub the heavy editor by
// exception"). Amplify is stubbed at the credential boundary so the workspace's
// data hooks resolve to empty ServiceResults instead of hitting AWS.
vi.mock('../features/query/SqlEditor', () => ({
  SqlEditor: ({value}: {value: string}) => (
    <textarea
      aria-label="SQL editor"
      defaultValue={value}
    />
  )
}));
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

import QueryPage from './QueryPage';

beforeEach(() => {
  vi.clearAllMocks();
  window.innerWidth = 1280;
});

describe('QueryPage route', () => {
  it('renders the query workspace for an authenticated user', async () => {
    renderWithProviders(<QueryPage />, {route: '/query', auth: authenticated('alice')});

    // The workspace toolbar is present (real QueryWorkspace, real tab strip).
    expect(await screen.findByRole('button', {name: 'Run statement'})).toBeInTheDocument();
    // The lazy editor mounts (stubbed textarea) once its chunk resolves.
    expect(await screen.findByLabelText('SQL editor')).toBeInTheDocument();
  });

  it('sets the page title', () => {
    renderWithProviders(<QueryPage />, {route: '/query', auth: authenticated('alice')});
    expect(document.title).toMatch(/Query/);
  });
});
