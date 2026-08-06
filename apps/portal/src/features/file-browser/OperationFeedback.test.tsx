import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, it, expect, vi} from 'vitest';
import {OperationFeedback} from './OperationFeedback';
import type {BulkOperationState} from './fileBrowser.types';

function state(over: Partial<BulkOperationState> = {}): BulkOperationState {
  return {
    isBusy: false,
    progress: null,
    error: null,
    summary: null,
    collision: null,
    dismissError: vi.fn(),
    dismissSummary: vi.fn(),
    ...over
  };
}

describe('OperationFeedback', () => {
  it('renders nothing when the operation has said nothing', () => {
    const {container} = render(
      <OperationFeedback
        op={state()}
        pastVerb="Deleted"
        failVerb="delete"
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('reports a clean run with the operation’s own past tense', () => {
    render(
      <OperationFeedback
        op={state({summary: {count: 3, errors: []}})}
        pastVerb="Copied"
        failVerb="copy"
      />
    );
    expect(screen.getByText(/Copied 3 items/i)).toBeInTheDocument();
  });

  it('names each failed item by its LEAF, and maps the error rather than showing raw AWS text', () => {
    render(
      <OperationFeedback
        op={state({
          summary: {
            count: 1,
            errors: [{key: 'alice/reports/q1.csv', message: 'Access Denied', code: 'AccessDenied'}]
          }
        })}
        pastVerb="Moved"
        failVerb="move"
      />
    );

    expect(screen.getByText(/Could not move 1/i)).toBeInTheDocument();
    expect(screen.getByText(/q1\.csv/)).toBeInTheDocument();
    expect(screen.queryByText(/alice\/reports\//)).toBeNull(); // the leaf, not the key
    expect(screen.queryByText(/Access Denied/)).toBeNull(); // SPEC-106: never raw
  });

  it('announces progress with the operation’s present participle', () => {
    // The verb became a prop in this refactor, so a wrong or missing one is exactly the
    // mistake that is now possible and was not before.
    render(
      <OperationFeedback
        op={state({isBusy: true, progress: 42})}
        pastVerb="Moved"
        failVerb="move"
        progressVerb="Moving"
      />
    );
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Moving… 42%');
  });

  it('shows no progress line for an operation that reports none', () => {
    // Delete passes neither `progress` nor `progressVerb`; both must be absent, not "…%".
    render(
      <OperationFeedback
        op={state({isBusy: true, progress: null})}
        pastVerb="Deleted"
        failVerb="delete"
      />
    );
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('offers the batch overwrite confirmation and reports the choice', async () => {
    const user = userEvent.setup();
    const onOverwriteAll = vi.fn();
    const onCancel = vi.fn();
    render(
      <OperationFeedback
        op={state({collision: {count: 2, onOverwriteAll, onCancel}})}
        pastVerb="Copied"
        failVerb="copy"
      />
    );

    await user.click(screen.getByRole('button', {name: /overwrite/i}));
    expect(onOverwriteAll).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('dismisses a systemic error without touching the summary', async () => {
    const user = userEvent.setup();
    const dismissError = vi.fn();
    const dismissSummary = vi.fn();
    render(
      <OperationFeedback
        op={state({error: 'You must be signed in to copy files.', dismissError, dismissSummary})}
        pastVerb="Copied"
        failVerb="copy"
      />
    );

    expect(screen.getByText('You must be signed in to copy files.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: /dismiss/i}));
    expect(dismissError).toHaveBeenCalledTimes(1);
    expect(dismissSummary).not.toHaveBeenCalled();
  });

  it('renders its slot between the progress line and the collision prompt', () => {
    // Move's rename prompt lives here, at the position it held before the three stanzas
    // were merged.
    const {container} = render(
      <OperationFeedback
        op={state({isBusy: true, progress: 10, collision: {count: 1, onOverwriteAll: vi.fn(), onCancel: vi.fn()}})}
        pastVerb="Moved"
        failVerb="move"
        progressVerb="Moving">
        <p>rename prompt</p>
      </OperationFeedback>
    );

    const text = Array.from(container.querySelectorAll('*'))
      .map((el) => el.textContent ?? '')
      .join('|');
    expect(text.indexOf('Moving… 10%')).toBeLessThan(text.indexOf('rename prompt'));
    expect(text.indexOf('rename prompt')).toBeLessThan(text.lastIndexOf('Overwrite'));
  });
});
