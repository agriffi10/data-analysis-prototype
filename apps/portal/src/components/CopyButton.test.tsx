import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { CopyButton } from './CopyButton';

const writeText = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  });
});

describe('CopyButton', () => {
  it('has a stable accessible name woven from the label', () => {
    render(<CopyButton value="s3://b/k" label="full cloud path" />);
    expect(
      screen.getByRole('button', { name: /copy full cloud path/i }),
    ).toBeInTheDocument();
  });

  it('writes the value to the clipboard and announces success', async () => {
    render(<CopyButton value="s3://b/k" label="path" />);

    fireEvent.click(screen.getByRole('button', { name: /copy path/i }));

    expect(writeText).toHaveBeenCalledWith('s3://b/k');
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/copied/i),
    );
  });

  it('does not throw or announce when the clipboard rejects', async () => {
    writeText.mockRejectedValueOnce(new Error('denied'));
    render(<CopyButton value="x" label="path" />);

    fireEvent.click(screen.getByRole('button', { name: /copy path/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(screen.getByRole('status').textContent).toBe('');
  });
});
