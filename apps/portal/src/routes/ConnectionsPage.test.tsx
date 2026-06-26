import { describe, it, expect, vi, beforeEach, type MockedFunction } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../features/auth', () => ({ useAuth: vi.fn() }));
vi.mock('../features/shared-spaces/sharedSpaces.service', () => ({
  enqueueSharedSpaceRequest: vi.fn(),
}));

import { useAuth } from '../features/auth';
import { enqueueSharedSpaceRequest } from '../features/shared-spaces/sharedSpaces.service';
import ConnectionsPage from './ConnectionsPage';

const mockUseAuth = useAuth as unknown as MockedFunction<() => unknown>;
const mockEnqueue = enqueueSharedSpaceRequest as unknown as MockedFunction<
  (...args: unknown[]) => Promise<unknown>
>;

beforeEach(() => {
  vi.clearAllMocks();
  mockUseAuth.mockReturnValue({ user: { username: 'alice' } });
});

describe('ConnectionsPage (SPEC-051)', () => {
  it('shows the empty state until a connection is created', () => {
    render(<ConnectionsPage />);
    expect(screen.getByText(/No shared connections yet/)).toBeInTheDocument();
  });

  it('creates a connection: enqueues one create request, shows pending + success toast', async () => {
    mockEnqueue.mockResolvedValue({ success: true, data: { requestId: 'r1' } });
    render(<ConnectionsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'New shared connection' }));
    fireEvent.change(screen.getByLabelText('Connection name'), {
      target: { value: 'sales_data' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() =>
      expect(screen.getByText(/Creating .*sales_data/)).toBeInTheDocument(),
    );
    expect(mockEnqueue).toHaveBeenCalledTimes(1);
    expect(mockEnqueue).toHaveBeenCalledWith({
      action: 'create',
      actor: 'alice',
      space: 'sales_data',
      payload: {},
    });
    // Optimistic pending entry rendered; dialog closed.
    expect(screen.getByText('sales_data')).toBeInTheDocument();
    expect(screen.getByText('Provisioning…')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Create' }),
    ).not.toBeInTheDocument();
  });

  it('shows an error toast and no pending entry when the enqueue fails', async () => {
    mockEnqueue.mockResolvedValue({
      success: false,
      error: { message: 'Shared connections are not configured' },
    });
    render(<ConnectionsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'New shared connection' }));
    fireEvent.change(screen.getByLabelText('Connection name'), {
      target: { value: 'sales_data' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() =>
      expect(
        screen.getByText('Shared connections are not configured'),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText('Provisioning…')).not.toBeInTheDocument();
    expect(screen.getByText(/No shared connections yet/)).toBeInTheDocument();
  });
});
