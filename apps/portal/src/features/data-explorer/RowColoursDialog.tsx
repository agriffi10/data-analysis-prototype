import {useState} from 'react';
import {Button} from '../../components/Button';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {
  COLOUR_OPERATORS,
  colourOperatorTakesValue,
  COLOUR_OPERATOR_LABELS,
  FORMATTING_BACKGROUNDS,
  FORMATTING_COLOUR_LABELS,
  FORMATTING_FOREGROUNDS,
  SELECT_CLASS
} from './dataExplorer.constants';
import {newExplorationId} from './exploration';
import {StripingControl} from './StripingControl';
import {colourValue, isRuleApplicable, ruleRefusal} from './formatting';
import type {ColourOperator, ColourRule, ColourToken, FormattingState, SurfaceToken} from './dataExplorer.types';

export type RowColoursSettings = Pick<FormattingState, 'rules' | 'colourByType' | 'stripeColumns'>;

export type RowColoursDialogProps = {
  /** Every column the current result has, in display order. */
  columns: string[];
  /** The applied formatting — the starting point for the staged draft. */
  formatting: FormattingState;
  onApply: (settings: RowColoursSettings) => void;
  onCancel: () => void;
};

/** Shown against a rule whose column the current result no longer has. */
export const INAPPLICABLE_RULE = 'This column isn’t in the results right now, so the rule is doing nothing.';
export const NO_RULES = 'No rules yet. Add one to color cells by what they hold.';
export const ROW_COLOURS_FREE = 'Colors are worked out in your browser. Nothing here runs a query.';
const ANY_COLUMN = '';

/** A rule as a new one starts: matches nothing yet, and paints one thing. */
function newRule(): ColourRule {
  return {id: newExplorationId(), operator: '=', value: '', foreground: 'danger'};
}

/**
 * Conditional colouring, colour-by-type and row banding, in one staged form.
 *
 * Staged for `OrderFilterDialog`'s reason turned inside out. There it is about cost — many
 * changes becoming one execution. Here **nothing costs anything**, and the staging is about
 * coherence instead: a rule is built across five controls, and applying it after each one
 * would repaint the grid from half-written conditions. Cancel discards the draft whole.
 *
 * The palette is a bounded set of design tokens rather than a colour picker, which is what
 * makes the contrast promise one this dialog can actually keep — every pairing
 * it can produce is measured in `formatting.test.ts`.
 */
export function RowColoursDialog({columns, formatting, onApply, onCancel}: RowColoursDialogProps) {
  const [draft, setDraft] = useState<RowColoursSettings>({
    rules: formatting.rules,
    colourByType: formatting.colourByType,
    stripeColumns: formatting.stripeColumns
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  // The gradient bounds AS TYPED, keyed `${rule.id}:min|max`. A number-only round trip
  // through `Number()` cannot be typed into: `-` is NaN and renders as empty, so the minus
  // is erased, and `1.` renders as `1`, so the point is. Both make a range like `-10..40`
  // or `0..1.5` unreachable — the rule asks for a numeric range, not a whole positive one.
  // The parsed value still rides on the rule, so a half-typed bound is refused at Apply.
  const [bounds, setBounds] = useState<Record<string, string>>({});

  const editRule = (id: string, update: Partial<ColourRule>) => {
    setErrors((e) => ({...e, [id]: ''}));
    setDraft((d) => ({...d, rules: d.rules.map((rule) => (rule.id === id ? {...rule, ...update} : rule))}));
  };

  const boundText = (id: string, end: 'min' | 'max', value: number): string =>
    bounds[`${id}:${end}`] ?? (Number.isFinite(value) ? String(value) : '');

  const editBound = (id: string, end: 'min' | 'max', text: string, gradient: NonNullable<ColourRule['gradient']>) => {
    setBounds((b) => ({...b, [`${id}:${end}`]: text}));
    // `Number('')` is 0, which would silently accept an emptied field as a bound of zero.
    editRule(id, {gradient: {...gradient, [end]: text.trim() === '' ? NaN : Number(text)}});
  };

  const move = (index: number, direction: -1 | 1) =>
    setDraft((d) => {
      const to = index + direction;
      if (to < 0 || to >= d.rules.length) return d;
      const rules = [...d.rules];
      [rules[index], rules[to]] = [rules[to], rules[index]];
      return {...d, rules};
    });

  const submit = () => {
    // Every refusal is raised at once rather than one per attempt, and each is user
    // wording: the engine's own `SyntaxError` names character offsets in a pattern the
    // user is still writing, which the error-wording rule forbids showing (the same reason).
    const bad: Record<string, string> = {};
    for (const rule of draft.rules) {
      const refusal = ruleRefusal(rule);
      if (refusal) bad[rule.id] = refusal;
    }
    if (Object.keys(bad).length > 0) {
      setErrors(bad);
      return;
    }
    onApply(draft);
  };

  return (
    <FormDialog
      title="Colors"
      ariaLabel="Colors"
      submitLabel="Apply"
      className="max-w-4xl"
      scrollBody
      onSubmit={submit}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">{ROW_COLOURS_FREE}</p>

      <label className="mt-4 flex items-center gap-2 text-sm text-text-2">
        <input
          type="checkbox"
          checked={draft.colourByType}
          onChange={(e) => setDraft((d) => ({...d, colourByType: e.target.checked}))}
        />
        Color values by their data type
      </label>

      <div className="mt-4">
        <StripingControl
          columns={columns}
          value={draft.stripeColumns}
          onChange={(stripeColumns) => setDraft((d) => ({...d, stripeColumns}))}
        />
      </div>

      <h3 className="mt-5 text-sm font-semibold text-text">Rules</h3>
      <p className="text-xs text-text-3">Rules run in order, and a later one wins where two set the same thing.</p>

      {draft.rules.length === 0 && <p className="mt-2 text-sm text-text-3">{NO_RULES}</p>}

      <ul className="mt-2 flex flex-col gap-2">
        {draft.rules.map((rule, index) => {
          const position = index + 1;
          const gradient = rule.gradient;
          return (
            <li
              key={rule.id}
              className="flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2">
              <span className="text-xs text-text-3">{position}</span>

              <select
                aria-label={`Rule ${position} column`}
                className={SELECT_CLASS}
                value={rule.column ?? ANY_COLUMN}
                onChange={(e) =>
                  editRule(rule.id, {column: e.target.value === ANY_COLUMN ? undefined : e.target.value})
                }>
                <option value={ANY_COLUMN}>Any column</option>
                {/* A rule whose column has gone keeps it as an option, or selecting the
                    rule's own value would be impossible and the select would silently
                    show a different column than the rule tests. */}
                {(rule.column && !columns.includes(rule.column) ? [...columns, rule.column] : columns).map((name) => (
                  <option
                    key={name}
                    value={name}>
                    {name}
                  </option>
                ))}
              </select>

              {!gradient && (
                <>
                  <select
                    aria-label={`Rule ${position} test`}
                    className={SELECT_CLASS}
                    value={rule.operator}
                    onChange={(e) => editRule(rule.id, {operator: e.target.value as ColourOperator})}>
                    {COLOUR_OPERATORS.map((operator) => (
                      <option
                        key={operator}
                        value={operator}>
                        {COLOUR_OPERATOR_LABELS[operator]}
                      </option>
                    ))}
                  </select>

                  {/* The two presence tests take no value, so the field LEAVES the tree
                      rather than being disabled: a disabled input beside a rule that
                      ignores it is a control that looks like it still means something. A
                      stored value survives the switch and is ignored while it does. */}
                  {colourOperatorTakesValue(rule.operator) && (
                    <span className="basis-40">
                      <Input
                        aria-label={`Rule ${position} value`}
                        value={rule.value}
                        error={errors[rule.id] || null}
                        onChange={(e) => editRule(rule.id, {value: e.target.value})}
                      />
                    </span>
                  )}
                </>
              )}

              {gradient && (
                <>
                  <Input
                    aria-label={`Rule ${position} range start`}
                    className="w-24"
                    inputMode="decimal"
                    value={boundText(rule.id, 'min', gradient.min)}
                    error={errors[rule.id] || null}
                    onChange={(e) => editBound(rule.id, 'min', e.target.value, gradient)}
                  />
                  <Input
                    aria-label={`Rule ${position} range end`}
                    className="w-24"
                    inputMode="decimal"
                    value={boundText(rule.id, 'max', gradient.max)}
                    onChange={(e) => editBound(rule.id, 'max', e.target.value, gradient)}
                  />
                  <ColourSelect
                    label={`Rule ${position} range start color`}
                    tokens={FORMATTING_BACKGROUNDS}
                    value={gradient.from}
                    onChange={(from) => editRule(rule.id, {gradient: {...gradient, from: from as SurfaceToken}})}
                  />
                  <ColourSelect
                    label={`Rule ${position} range end color`}
                    tokens={FORMATTING_BACKGROUNDS}
                    value={gradient.to}
                    onChange={(to) => editRule(rule.id, {gradient: {...gradient, to: to as SurfaceToken}})}
                  />
                </>
              )}

              <select
                aria-label={`Rule ${position} paints`}
                className={SELECT_CLASS}
                value={rule.scope ?? 'cell'}
                onChange={(e) => editRule(rule.id, {scope: e.target.value as 'cell' | 'row'})}>
                <option value="cell">Paint the matching cells</option>
                <option value="row">Paint the whole row</option>
              </select>

              <ColourSelect
                label={`Rule ${position} text color`}
                tokens={FORMATTING_FOREGROUNDS}
                value={rule.foreground}
                allowNone
                onChange={(foreground) =>
                  editRule(rule.id, {foreground: (foreground || undefined) as ColourRule['foreground']})
                }
              />
              {!gradient && (
                <ColourSelect
                  label={`Rule ${position} background`}
                  tokens={FORMATTING_BACKGROUNDS}
                  value={rule.background}
                  allowNone
                  onChange={(background) =>
                    editRule(rule.id, {background: (background || undefined) as ColourRule['background']})
                  }
                />
              )}

              <label className="flex items-center gap-1.5 text-xs text-text-2">
                <input
                  type="checkbox"
                  aria-label={`Shade a number range, rule ${position}`}
                  checked={Boolean(gradient)}
                  onChange={(e) =>
                    editRule(rule.id, {
                      gradient: e.target.checked
                        ? {min: 0, max: 100, from: FORMATTING_BACKGROUNDS[0], to: FORMATTING_BACKGROUNDS[3]}
                        : undefined
                    })
                  }
                />
                Shade a number range
              </label>

              <Button
                size="sm"
                variant="ghost"
                aria-label={`Move rule ${position} earlier`}
                disabledReason={index === 0 ? `Rule ${position} is already first.` : undefined}
                onClick={() => move(index, -1)}>
                ↑
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Move rule ${position} later`}
                disabledReason={index === draft.rules.length - 1 ? `Rule ${position} is already last.` : undefined}
                onClick={() => move(index, 1)}>
                ↓
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Remove rule ${position}`}
                onClick={() => setDraft((d) => ({...d, rules: d.rules.filter((r) => r.id !== rule.id)}))}>
                Remove
              </Button>

              {!isRuleApplicable(rule, columns) && (
                <p className="basis-full text-xs text-warning">{INAPPLICABLE_RULE}</p>
              )}
            </li>
          );
        })}
      </ul>

      <Button
        size="sm"
        className="mt-3"
        onClick={() => setDraft((d) => ({...d, rules: [...d.rules, newRule()]}))}>
        Add rule
      </Button>
    </FormDialog>
  );
}

type ColourSelectProps = {
  label: string;
  tokens: readonly (ColourToken | SurfaceToken)[];
  value: ColourToken | SurfaceToken | undefined;
  allowNone?: boolean;
  onChange: (value: string) => void;
};

/**
 * One colour choice, from the palette and only from the palette.
 *
 * The swatch beside each name is reinforcement, never the carrier: every option is named
 * in words too, because a select whose options differ only by colour is unusable to anyone
 * who cannot see the difference (1.4.1).
 */
function ColourSelect({label, tokens, value, allowNone, onChange}: ColourSelectProps) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="h-4 w-4 flex-none rounded-full border border-border"
        style={value ? {backgroundColor: colourValue(value)} : undefined}
      />
      <select
        aria-label={label}
        className={SELECT_CLASS}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}>
        {allowNone && <option value="">No change</option>}
        {tokens.map((token) => (
          <option
            key={token}
            value={token}>
            {FORMATTING_COLOUR_LABELS[token]}
          </option>
        ))}
      </select>
    </span>
  );
}
