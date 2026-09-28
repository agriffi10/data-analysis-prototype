import {useEffect, useId, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {SELECT_CLASS} from './dataExplorer.constants';
import {FilterValuePicker} from './FilterValuePicker';
import {FilterValuesField} from './FilterValuesField';
import {
  FILTER_OPERATOR_LABELS,
  filterValueKind,
  operatorHint,
  operatorListsNull,
  operatorTakesValue,
  operatorTakesValues,
  operatorUsesValueKind,
  operatorsFor
} from './explorationQueryOps';
import {
  addItem,
  draftValueKind,
  emptyCondition,
  fieldOfSelection,
  fromDraft,
  newGroup,
  removeItem,
  selectionOfField,
  toDraft,
  updateItem,
  withColumn,
  withOperator
} from './filterBuilderDraft';
import type {DraftCondition, DraftGroup, DraftItem} from './filterBuilderDraft';
import type {QueryColumn} from '../catalog/catalog.types';
import type {ExplorationSource, FilterItem, FilterJoin, FilterOperator, ValuesNarrowing} from './dataExplorer.types';

export type FilterBuilderDialogProps = {
  /** The columns a condition may test: the source's, hidden ones included. */
  columns: QueryColumn[];
  /** Why a column takes no filter, or null when it does — the header menu's own reader. */
  queryRefusalOf: (column: string) => string | null;
  /** The applied filter, which the draft starts from. */
  filters: FilterItem[];
  /** Where the rows come from, which the values picker lists a column's values over; null offers no picker. */
  source: ExplorationSource | null;
  onApply: (filters: FilterItem[]) => void;
  onCancel: () => void;
};

/**
 * What narrows the values a builder row's picker lists: nothing.
 *
 * Inside an OR group, narrowing one condition's values by its neighbours would hide exactly the
 * values the OR exists to reach, and the builder cannot tell which neighbours a row is ANDed with
 * until Apply.
 */
const NO_NARROWING: ValuesNarrowing = {filters: [], expression: null};

/** What a group's select calls each join. */
const JOIN_LABELS: Record<FilterJoin, string> = {and: 'all of these', or: 'any of these'};

function opposite(join: FilterJoin): FilterJoin {
  return join === 'and' ? 'or' : 'and';
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

/**
 * The name every control of an item carries in front of its own, so a screen reader hears which
 * condition a select belongs to: `Condition 2`, `Group 1`, `Group 1, condition 2`, `Group 1.1`.
 */
function labelsFor(items: DraftItem[], parent: string | null): string[] {
  let conditions = 0;
  let groups = 0;
  return items.map((item) => {
    if (item.kind === 'condition') {
      conditions += 1;
      return parent ? `${parent}, condition ${conditions}` : `Condition ${conditions}`;
    }
    groups += 1;
    return parent ? `${parent}.${groups}` : `Group ${groups}`;
  });
}

/** The control focus lands on for an item: a row's column select, a group's match select. */
function firstControlId(base: string, item: DraftItem): string {
  return `${base}-${item.id}-first`;
}

function addConditionId(base: string, containerId: string | null): string {
  return `${base}-${containerId ?? 'top'}-add`;
}

/**
 * Where focus goes once an item is removed: the item that takes its place, else the one before it,
 * else the container's Add condition — never the page body the removed control leaves it on.
 */
function focusAfterRemoval(base: string, siblings: DraftItem[], index: number, containerId: string | null): string {
  const next = siblings[index + 1] ?? siblings[index - 1];
  return next ? firstControlId(base, next) : addConditionId(base, containerId);
}

/**
 * **Filter rows**: conditions and groups, built by pointing and applied as ONE query.
 *
 * Every apply is an Athena execution and a bill, so this edits a local draft and hands the whole
 * filter over on Apply — however many rows changed, one execution. Cancel discards the draft.
 *
 * The top level always matches **all** of its items, and OR lives in a group — so the column menus,
 * which edit only the top level, always narrow. A group may hold one more level of groups, and a
 * new group starts on the opposite match of the one it sits in, since that is the only reason to
 * nest it.
 *
 * A row the user leaves alone is handed back as the stored condition itself (`fromDraft`), so a
 * field this dialog does not show survives an Apply that changed something else.
 *
 * **No field submits on Enter**, as in Order and filter: every field is one row of many, and a row
 * mid-edit filing the whole dialog is what `FormDialog`'s suppression exists to prevent.
 */
export function FilterBuilderDialog({
  columns,
  queryRefusalOf,
  filters,
  source,
  onApply,
  onCancel
}: FilterBuilderDialogProps) {
  const base = useId();
  const [draft, setDraft] = useState<DraftItem[]>(() => toDraft(filters));
  const [refusals, setRefusals] = useState<Record<string, string>>({});
  // The list rows whose values picker is open. Opening one is the billed gesture — the picker lists
  // the column's values with a query — so a list row never mounts one on its own.
  const [picking, setPicking] = useState<ReadonlySet<string>>(() => new Set());
  const togglePicking = (id: string) =>
    setPicking((open) => {
      const next = new Set(open);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  // Finds the control to focus once the edit that set it has been committed. A ref rather than
  // state: nothing renders from it, and the effect below consumes it on that commit.
  const pendingFocus = useRef<(() => HTMLElement | null) | null>(null);

  useEffect(() => {
    const find = pendingFocus.current;
    if (find === null) return;
    pendingFocus.current = null;
    find()?.focus();
  }, [draft, refusals]);

  const offered = columns.filter((column) => queryRefusalOf(column.name) === null);
  const typeOf = new Map(columns.map((column) => [column.name, column.type]));
  const operatorsOf = (column: string) => operatorsFor(typeOf.get(column) ?? '');
  const valueKindOf = (column: string) => filterValueKind(typeOf.get(column) ?? '');
  const byId = (id: string) => () => document.getElementById(id);

  const edit = (id: string, update: (row: DraftCondition) => DraftCondition) => {
    setRefusals((current) => ({...current, [id]: ''}));
    setDraft((items) => updateItem(items, id, (item) => (item.kind === 'condition' ? update(item) : item)));
  };

  const add = (containerId: string | null, added: DraftItem) => {
    if (containerId !== null) setRefusals((current) => ({...current, [containerId]: ''}));
    pendingFocus.current = byId(firstControlId(base, added.kind === 'group' ? added.items[0] : added));
    setDraft((items) => addItem(items, containerId, added));
  };

  const remove = (siblings: DraftItem[], index: number, containerId: string | null) => {
    pendingFocus.current = byId(focusAfterRemoval(base, siblings, index, containerId));
    setDraft((items) => removeItem(items, siblings[index].id));
  };

  const submit = () => {
    const built = fromDraft(draft, valueKindOf);
    if ('refusals' in built) {
      setRefusals(built.refusals);
      // Focus goes to the first refused control, which its refusal describes, so the reason is
      // heard where the correction is made rather than only seen.
      pendingFocus.current = () =>
        document.querySelector<HTMLElement>(`[data-builder="${base}"] [aria-invalid="true"]`);
      return;
    }
    onApply(built.filters);
  };

  const renderCondition = (row: DraftCondition, label: string) => {
    const refusal = refusals[row.id] || null;
    const columnRefused = refusal !== null && (row.column === '' || row.operator === '');
    const listed = offered.some((column) => column.name === row.column);
    const operators = row.column === '' ? [] : operatorsOf(row.column);
    // A stored operator the column no longer offers is still shown, rather than silently read as
    // the first one the select lists.
    const shownOperators =
      row.operator !== '' && !operators.includes(row.operator) ? [row.operator, ...operators] : operators;
    const hint = row.operator !== '' && operatorTakesValue(row.operator) ? operatorHint(row.operator) : null;
    const errorId = `${base}-${row.id}-error`;
    const hintId = `${base}-${row.id}-hint`;
    const numeric =
      row.operator !== '' && operatorUsesValueKind(row.operator) && draftValueKind(row, valueKindOf) === 'number';
    return (
      <div className="flex flex-wrap items-start gap-2">
        <select
          id={firstControlId(base, row)}
          aria-label={`${label}: column`}
          className={SELECT_CLASS}
          aria-invalid={columnRefused || undefined}
          aria-describedby={columnRefused ? errorId : undefined}
          value={row.column}
          onChange={(e) => edit(row.id, (r) => withColumn(r, e.target.value, operatorsOf(e.target.value)))}>
          <option value="">Choose a column</option>
          {!listed && row.column !== '' && <option value={row.column}>{row.column}</option>}
          {offered.map((column) => (
            <option
              key={column.name}
              value={column.name}>
              {column.name}
            </option>
          ))}
        </select>
        {row.operator !== '' && (
          <select
            aria-label={`${label}: test`}
            className={SELECT_CLASS}
            value={row.operator}
            onChange={(e) => edit(row.id, (r) => withOperator(r, e.target.value as FilterOperator))}>
            {shownOperators.map((operator) => (
              <option
                key={operator}
                value={operator}>
                {FILTER_OPERATOR_LABELS[operator]}
              </option>
            ))}
          </select>
        )}
        {row.operator !== '' && operatorTakesValue(row.operator) && (
          <span className="min-w-0 flex-1 basis-40">
            <Input
              aria-label={`${label}: value`}
              aria-describedby={hint ? hintId : undefined}
              value={row.value}
              error={columnRefused ? null : refusal}
              inputMode={numeric ? 'decimal' : undefined}
              onChange={(e) => edit(row.id, (r) => ({...r, dirty: true, value: e.target.value}))}
            />
            {hint && (
              <p
                id={hintId}
                className="mt-1 text-xs text-text-3">
                {hint}
              </p>
            )}
          </span>
        )}
        {row.operator !== '' && operatorTakesValues(row.operator) && (
          <>
            <FilterValuesField
              className="basis-full"
              label={`${label}: values, one per line`}
              labelHidden
              value={row.listField}
              offersEmpty={draftValueKind(row, valueKindOf) === 'string'}
              offersNull={operatorListsNull(row.operator)}
              error={columnRefused ? null : refusal}
              onChange={(next) => edit(row.id, (r) => ({...r, dirty: true, listField: next}))}
            />
            {source && (
              <Button
                size="sm"
                aria-expanded={picking.has(row.id)}
                aria-label={`${label}: pick values`}
                onClick={() => togglePicking(row.id)}>
                {picking.has(row.id) ? 'Hide values' : 'Pick values'}
              </Button>
            )}
            {source && picking.has(row.id) && (
              <div className="basis-full">
                <FilterValuePicker
                  source={source}
                  column={row.column}
                  valueKind={draftValueKind(row, valueKindOf)}
                  operator={row.operator === 'notIn' ? 'notIn' : 'in'}
                  narrowing={NO_NARROWING}
                  selection={selectionOfField(row.listField, draftValueKind(row, valueKindOf))}
                  onSelectionChange={(next) =>
                    edit(row.id, (r) => ({...r, dirty: true, listField: fieldOfSelection(next)}))
                  }
                />
              </div>
            )}
          </>
        )}
        {columnRefused && (
          <p
            id={errorId}
            className="basis-full text-xs text-danger">
            {refusal}
          </p>
        )}
      </div>
    );
  };

  const renderItems = (items: DraftItem[], container: DraftGroup | null, parentLabel: string | null, depth: number) => {
    const labels = labelsFor(items, parentLabel);
    const joinWord = container?.join === 'or' ? 'or' : 'and';
    const containerId = container?.id ?? null;
    return (
      <>
        <ul className="flex flex-col gap-2">
          {items.map((item, index) => (
            <li
              key={item.id}
              className="flex items-start gap-2">
              <span className="w-8 flex-none pt-2 text-right text-xs text-text-3">{index > 0 ? joinWord : ''}</span>
              <fieldset className="min-w-0 flex-1 rounded-md border border-border px-3 py-2">
                <legend className="sr-only">{labels[index]}</legend>
                {item.kind === 'condition'
                  ? renderCondition(item, labels[index])
                  : renderGroup(item, labels[index], depth + 1)}
                <Button
                  size="sm"
                  variant="ghost"
                  className="mt-2"
                  onClick={() => remove(items, index, containerId)}>
                  {`Remove ${lowerFirst(labels[index])}`}
                </Button>
              </fieldset>
            </li>
          ))}
        </ul>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button
            id={addConditionId(base, containerId)}
            size="sm"
            aria-label={parentLabel ? `Add condition to ${lowerFirst(parentLabel)}` : undefined}
            onClick={() => add(containerId, emptyCondition())}>
            Add condition
          </Button>
          {/* Groups nest two deep: a group at the top level, and one more level inside it. */}
          {depth < 2 && (
            <Button
              size="sm"
              aria-label={parentLabel ? `Add group to ${lowerFirst(parentLabel)}` : undefined}
              onClick={() => add(containerId, newGroup(container ? opposite(container.join) : 'or'))}>
              Add group
            </Button>
          )}
        </div>
      </>
    );
  };

  const renderGroup = (group: DraftGroup, label: string, depth: number) => {
    const refusal = refusals[group.id] || null;
    const errorId = `${base}-${group.id}-error`;
    return (
      <div className="flex flex-col gap-2">
        <label className="flex items-center gap-2 text-sm text-text-2">
          Match
          <select
            id={firstControlId(base, group)}
            aria-label={`${label}: match`}
            className={SELECT_CLASS}
            aria-invalid={refusal !== null || undefined}
            aria-describedby={refusal ? errorId : undefined}
            value={group.join}
            onChange={(e) => {
              const join = e.target.value as FilterJoin;
              setDraft((items) => updateItem(items, group.id, (item) => ({...item, join}) as DraftItem));
            }}>
            {(['and', 'or'] as const).map((join) => (
              <option
                key={join}
                value={join}>
                {JOIN_LABELS[join]}
              </option>
            ))}
          </select>
        </label>
        {refusal && (
          <p
            id={errorId}
            className="text-xs text-danger">
            {refusal}
          </p>
        )}
        {renderItems(group.items, group, label, depth)}
      </div>
    );
  };

  return (
    <FormDialog
      title="Filter rows"
      ariaLabel="Filter rows"
      submitLabel="Apply"
      className="max-w-3xl"
      scrollBody
      onSubmit={submit}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        Rows must match all of these. Nothing runs until you press Apply, and then it runs once.
      </p>
      <div
        className="mt-4"
        data-builder={base}>
        {renderItems(draft, null, null, 0)}
      </div>
    </FormDialog>
  );
}
