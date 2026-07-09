import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {ErrorBanner} from './ErrorBanner';

describe('ErrorBanner', () => {
  it('renders the FR-001-mapped message for a known AWS code, not the raw text', () => {
    render(<ErrorBanner error={{code: 'AccessDenied', message: 'User: arn:aws:sts is not authorized'}} />);
    expect(screen.getByText(/don't have permission/)).toBeInTheDocument();
    expect(screen.queryByText(/arn:aws/)).not.toBeInTheDocument();
  });

  it('maps an unqualified-table Athena failure to the add-database fix', () => {
    render(<ErrorBanner error={{code: 'FAILED', message: 'line 1:15: Table sales does not exist'}} />);
    expect(screen.getByText(/Add a database to each table/)).toBeInTheDocument();
  });

  it('falls back to the generic message for an unknown error', () => {
    render(<ErrorBanner error={{code: 'Whatever', message: 'boom internal detail'}} />);
    expect(screen.getByText('Something went wrong. Contact the Administrator.')).toBeInTheDocument();
    expect(screen.queryByText(/boom internal/)).not.toBeInTheDocument();
  });

  it('is an alert live region and can be dismissed', async () => {
    const onDismiss = vi.fn();
    render(
      <ErrorBanner
        error={{code: 'NetworkError'}}
        onDismiss={onDismiss}
      />
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', {name: 'Dismiss'}));
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
