import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {DropTableDialog} from './DropTableDialog';

function renderDialog(props: {shared?: boolean; isView?: boolean}) {
  renderWithProviders(
    <DropTableDialog
      table="sales"
      database="team_q3"
      isDropping={false}
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
      {...props}
    />
  );
}

describe('DropTableDialog', () => {
  it('names the database and never promises an Iceberg table keeps its data', () => {
    renderDialog({});

    const body = screen.getByText(/This removes the table from team_q3\./);
    expect(body).toHaveTextContent('an Iceberg table’s data is deleted with it');
    expect(body).not.toHaveTextContent(/everyone/);
  });

  it('says a shared space’s drop is everyone’s', () => {
    renderDialog({shared: true, isView: true});

    expect(
      screen.getByText(
        'This removes the view from team_q3, for everyone in this shared space. No underlying data is deleted.'
      )
    ).toBeInTheDocument();
  });
});
