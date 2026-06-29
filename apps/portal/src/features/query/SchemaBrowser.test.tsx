import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';

vi.mock('./useSchema', () => ({useSchema: vi.fn()}));

import {useSchema} from './useSchema';
import {SchemaBrowser, type TableActions} from './SchemaBrowser';
import type {Connection} from './query.types';

const mockUseSchema = vi.mocked(useSchema);
type SchemaState = ReturnType<typeof useSchema>;

function makeActions(over: Partial<TableActions> = {}): TableActions {
  return {
    onViewSourceFiles: vi.fn(),
    onViewDdl: vi.fn(),
    onViewData: vi.fn(),
    onDropTable: vi.fn(),
    canViewSourceFiles: () => true,
    ...over
  };
}

const tableSchema = {
  isPending: false,
  isError: false,
  data: {
    database: {name: 'alice'},
    tables: [
      {
        name: 'sales_2026',
        location: 's3://bucket/alice/sales/',
        columns: [
          {name: 'order_id', type: 'bigint'},
          {name: 'region', type: 'string'}
        ]
      }
    ]
  }
} as unknown as SchemaState;

const connections: Connection[] = [
  {id: 'personal', label: 'My workspace', database: 'alice', kind: 'personal'},
  {id: 's1', label: 'Project Alpha', database: 'project_alpha', kind: 'shared', status: 'active', role: 'member'}
];

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSchema.mockReturnValue(tableSchema);
});

describe('SchemaBrowser', () => {
  // --- single-database default (the common case) ---

  it('renders a single database expanded by default with its Tables group', () => {
    render(
      <SchemaBrowser
        database="alice"
        connections={[connections[0]]}
        onSelectDatabase={vi.fn()}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    // Expanded by default → its objects show.
    expect(screen.getByRole('button', {name: /Collapse My workspace/})).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', {name: 'sales_2026'})).toBeInTheDocument();
  });

  it('inserts a column name on click', () => {
    const onInsert = vi.fn();
    render(
      <SchemaBrowser
        database="alice"
        onInsert={onInsert}
        actions={makeActions()}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'sales_2026'}));
    fireEvent.click(screen.getByRole('button', {name: /region/}));
    expect(onInsert).toHaveBeenCalledWith('region');
  });

  it('opens the options menu and fires an action without toggling expand', () => {
    const actions = makeActions();
    render(
      <SchemaBrowser
        database="alice"
        onInsert={vi.fn()}
        actions={actions}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'Options for sales_2026'}));
    expect(screen.getByRole('button', {name: 'sales_2026'})).toHaveAttribute('aria-expanded', 'false');
    const menu = screen.getByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', {name: 'View data'}));
    expect(actions.onViewData).toHaveBeenCalledWith(expect.objectContaining({name: 'sales_2026'}));
  });

  // --- the active-target radiogroup (SPEC-063 FR-003) ---

  it('keys the active node schema query off the active database', () => {
    render(
      <SchemaBrowser
        database="project_alpha"
        connections={connections}
        onSelectDatabase={vi.fn()}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    // The active node is expanded by default → it fetches its own schema.
    expect(mockUseSchema).toHaveBeenCalledWith('project_alpha');
  });

  it('marks the active database with a checked radio, the others unchecked', () => {
    render(
      <SchemaBrowser
        database="alice"
        connections={connections}
        onSelectDatabase={vi.fn()}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    expect(screen.getByRole('radio', {name: /Use My workspace/})).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', {name: /Use Project Alpha/})).toHaveAttribute('aria-checked', 'false');
  });

  it('selecting a different database calls onSelectDatabase without expanding it', () => {
    const onSelectDatabase = vi.fn();
    render(
      <SchemaBrowser
        database="alice"
        connections={connections}
        onSelectDatabase={onSelectDatabase}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    // Project Alpha is the non-active node — collapsed by default.
    const alphaDisclosure = screen.getByRole('button', {name: /Expand Project Alpha/});
    expect(alphaDisclosure).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(screen.getByRole('radio', {name: /Use Project Alpha/}));
    expect(onSelectDatabase).toHaveBeenCalledWith('project_alpha');
    expect(alphaDisclosure).toHaveAttribute('aria-expanded', 'false'); // unchanged
  });

  it('expands a non-active database to browse it without changing the active database', () => {
    const onSelectDatabase = vi.fn();
    render(
      <SchemaBrowser
        database="alice"
        connections={connections}
        onSelectDatabase={onSelectDatabase}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: /Expand Project Alpha/}));
    expect(mockUseSchema).toHaveBeenCalledWith('project_alpha');
    expect(onSelectDatabase).not.toHaveBeenCalled();
    // The active radio is still My workspace.
    expect(screen.getByRole('radio', {name: /Use My workspace/})).toHaveAttribute('aria-checked', 'true');
  });

  it('shows an unusable shared connection but not expandable or selectable (SPEC-052 FR-004)', () => {
    render(
      <SchemaBrowser
        database="alice"
        connections={[
          connections[0],
          {
            id: 's2',
            label: 'Project Beta',
            database: 'project_beta',
            kind: 'shared',
            status: 'provisioning',
            role: 'owner'
          }
        ]}
        onSelectDatabase={vi.fn()}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    expect(screen.getByText('Project Beta')).toBeInTheDocument();
    expect(screen.getByText(/Provisioning/)).toBeInTheDocument();
    // No disclosure toggle and no active radio for the unusable node.
    expect(screen.queryByRole('button', {name: /Project Beta/})).not.toBeInTheDocument();
    expect(screen.queryByRole('radio', {name: /Project Beta/})).not.toBeInTheDocument();
  });

  // --- accessibility (FR-006) ---

  it('has no axe violations', async () => {
    await expectNoA11yViolations(
      <SchemaBrowser
        database="alice"
        connections={connections}
        onSelectDatabase={vi.fn()}
        onInsert={vi.fn()}
        actions={makeActions()}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});
