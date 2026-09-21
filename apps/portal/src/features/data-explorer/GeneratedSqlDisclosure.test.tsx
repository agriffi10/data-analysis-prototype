import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {GeneratedSqlDisclosure, NO_GENERATED_SQL} from './GeneratedSqlDisclosure';

// **Open in Query** mounts only while the disclosure is open, only when the host gave it a handler
// — which the host does only with the `query` flag on — and only over a statement that exists.

const SQL = 'SELECT *\nFROM "alice"."orders"\nWHERE "qty" > 5';

describe('Open in Query in the Generated SQL disclosure', () => {
  it('hands over the exact statement once the disclosure is open', async () => {
    const onOpenInQuery = vi.fn();
    const {user} = renderWithProviders(
      <GeneratedSqlDisclosure
        sql={SQL}
        onOpenInQuery={onOpenInQuery}
      />
    );
    expect(screen.queryByRole('button', {name: 'Open in Query'})).toBeNull();

    await user.click(screen.getByText('Generated SQL'));
    await user.click(await screen.findByRole('button', {name: 'Open in Query'}));

    expect(onOpenInQuery).toHaveBeenCalledTimes(1);
    expect(onOpenInQuery).toHaveBeenCalledWith(SQL);
  });

  it('offers no Open in Query when the host gave no handler', async () => {
    const {user} = renderWithProviders(<GeneratedSqlDisclosure sql={SQL} />);

    await user.click(screen.getByText('Generated SQL'));

    expect(await screen.findByRole('button', {name: 'Copy SQL'})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Open in Query'})).toBeNull();
  });

  it('offers no Open in Query when there is no statement yet', async () => {
    const {user} = renderWithProviders(
      <GeneratedSqlDisclosure
        sql={null}
        onOpenInQuery={vi.fn()}
      />
    );

    await user.click(screen.getByText('Generated SQL'));

    expect(screen.getByText(NO_GENERATED_SQL)).toBeVisible();
    expect(screen.queryByRole('button', {name: 'Open in Query'})).toBeNull();
  });
});
