import {describe, it, expect, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {authenticated} from '../../test/authFixtures';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

describe('App routing', () => {
  it('renders a protected route through the layout for an authenticated user', async () => {
    renderApp('/help', {auth: authenticated('alice')});
    expect(await screen.findByRole('main')).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
  });
});
