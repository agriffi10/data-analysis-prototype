import type {ReactNode} from 'react';
import {render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {PortalMount} from './PortalMount';

vi.mock('../PortalBoot', () => ({
  PortalBoot: function PortalBootMock({children, flags}: {children: ReactNode; flags?: {readAt: number}}) {
    return (
      <div
        data-testid="boot"
        data-read-at={flags?.readAt}>
        {children}
      </div>
    );
  }
}));

describe('the root mount', () => {
  it('loads the boot in the browser, and hands it the page', async () => {
    render(
      <PortalMount>
        <p>the page</p>
      </PortalMount>
    );

    expect(await screen.findByTestId('boot')).toHaveTextContent('the page');
  });

  it('hands the boot the flag set the server sent with the page', async () => {
    const seeded = {flags: {} as never, readAt: 1234};

    render(
      <PortalMount flags={seeded}>
        <p>the page</p>
      </PortalMount>
    );

    expect(await screen.findByTestId('boot')).toHaveAttribute('data-read-at', '1234');
  });
});
