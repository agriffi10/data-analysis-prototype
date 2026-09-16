import {describe, expect, it} from 'vitest';
import {toUserMessage} from './errorMessages';

/**
 * Engine text captured from PRODUCTION Athena, and the sentence each must not fall past.
 *
 * **Every string here was read off a real `GET /v1/queries/{id}`**, by running the statement in
 * the third column as a signed-in user on 2026-09-15 and taking `stateChangeReason` verbatim.
 * None was written by hand, and that is the whole point of the file: three separate rules in
 * `errorMessages.ts` were tuned against invented strings, passed their own tests, and answered
 * the real message with the wrong sentence — one of them telling users who had qualified their
 * table to go and qualify it.
 *
 * The rule the corpus holds is the module's own: **the generic "Contact the Administrator"
 * sentence is reserved for what a user cannot act on**, and every failure below is a mistake in
 * the user's own SQL. A rule that stops matching Athena's current wording fails here rather than
 * in front of a user, which is the failure this corpus exists to move.
 *
 * Add a row whenever a live session captures a shape that is not here yet. Do not edit a string
 * to make a rule pass — the strings are the measurement.
 */
const CAPTURED: ReadonlyArray<{
  readonly name: string;
  readonly reason: string;
  readonly sql: string;
  /**
   * Whether the reader should be shown Athena's own words beneath the sentence.
   *
   * Set from the message's ERROR CLASS, not from what the module currently returns: it is true
   * exactly when the reason opens with a class `errorMessages` treats as describing the user's
   * own SQL. Recording observed behaviour instead would make the field agree with any change,
   * including a class silently dropping off the allowlist — which is what the plain
   * "not the generic sentence" assertion below cannot see, because such a message falls to the
   * syntax catch-all and keeps a sentence that is merely wrong rather than alarming.
   */
  readonly showsEngineText: boolean;
}> = [
  {name: 'divide by zero', sql: 'SELECT 1/0', reason: 'DIVISION_BY_ZERO: Division by zero', showsEngineText: true},
  {
    name: 'bad cast',
    sql: "SELECT CAST('abc' AS INTEGER)",
    reason: "INVALID_CAST_ARGUMENT: Cannot cast 'abc' to INT",
    showsEngineText: true
  },
  {
    name: 'year cast to date',
    sql: "SELECT CAST('2019' AS DATE)",
    reason: 'INVALID_CAST_ARGUMENT: Value cannot be cast to date: 2019',
    showsEngineText: true
  },
  {
    name: 'unknown function',
    sql: 'SELECT nosuchfn(1)',
    reason: "FUNCTION_NOT_FOUND: line 1:8: Function 'nosuchfn' not registered",
    showsEngineText: true
  },
  {
    name: 'wrong argument types',
    sql: "SELECT substr('abc')",
    reason:
      'FUNCTION_NOT_FOUND: line 1:8: Unexpected parameters (varchar(3)) for function substr. Expected: substr(char(x), bigint)',
    showsEngineText: true
  },
  {
    name: 'operator type mismatch',
    sql: "SELECT 1 + 'a'",
    reason: 'TYPE_MISMATCH: line 1:10: Cannot apply operator: integer + varchar(1)',
    showsEngineText: true
  },
  {
    name: 'union type mismatch',
    sql: "SELECT 1 UNION ALL SELECT 'a'",
    reason: 'TYPE_MISMATCH: line 1:10: column 1 in UNION query has incompatible types: integer, varchar(1)',
    showsEngineText: true
  },
  {
    name: 'array subscript',
    sql: 'SELECT ARRAY[1,2][5]',
    reason: 'INVALID_FUNCTION_ARGUMENT: Array subscript must be less than or equal to array length: 5 > 2',
    showsEngineText: true
  },
  {
    name: 'bad regex',
    sql: "SELECT regexp_like('a', '[')",
    reason: 'INVALID_FUNCTION_ARGUMENT: premature end of char-class',
    showsEngineText: true
  },
  {
    name: 'bad date format',
    sql: "SELECT date_parse('notadate', '%Y-%m-%d')",
    reason: 'INVALID_FUNCTION_ARGUMENT: Invalid format: "notadate"',
    showsEngineText: true
  },
  {
    name: 'sequence over its ceiling',
    sql: 'SELECT count(*) FROM UNNEST(sequence(1,200000))',
    reason: 'INVALID_FUNCTION_ARGUMENT: result of sequence function must not have more than 50000 entries',
    showsEngineText: true
  },
  {
    name: 'ambiguous column',
    sql: 'SELECT x FROM a, b',
    reason: "AMBIGUOUS_NAME: line 1:8: Column 'x' is ambiguous",
    showsEngineText: true
  },
  {
    name: 'aggregation in GROUP BY',
    sql: 'SELECT x, count(*) FROM t GROUP BY 2',
    reason:
      'EXPRESSION_NOT_SCALAR: line 1:11: GROUP BY clause cannot contain aggregations, window functions or grouping operations: [count(*)]',
    showsEngineText: true
  },
  {
    name: 'aggregation in WHERE',
    sql: 'SELECT x FROM t WHERE count(*) > 0',
    reason:
      'EXPRESSION_NOT_SCALAR: line 1:48: WHERE clause cannot contain aggregations, window functions or grouping operations: [count(*)]',
    showsEngineText: true
  },
  {
    name: 'ORDER BY position out of range',
    sql: 'SELECT x FROM t ORDER BY 9',
    reason: 'INVALID_COLUMN_REFERENCE: line 1:42: ORDER BY position 9 is not in select list',
    showsEngineText: true
  },
  {
    name: 'missing column',
    sql: 'SELECT nope FROM t',
    reason:
      "COLUMN_NOT_FOUND: line 1:8: Column 'nope' cannot be resolved or requester is not authorized to access requested resources",
    showsEngineText: true
  },
  {
    name: 'missing table, qualified',
    sql: 'SELECT * FROM agriffith.notable_xyz',
    reason: "TABLE_NOT_FOUND: line 1:15: Table 'awsdatacatalog.agriffith.notable_xyz' does not exist",
    showsEngineText: true
  },
  {
    name: 'INSERT into a missing table',
    sql: 'INSERT INTO agriffith.nope_xyz VALUES (1)',
    reason: 'Table nope_xyz not found in database agriffith',
    showsEngineText: false
  },
  {
    name: 'DROP a missing table',
    sql: 'DROP TABLE agriffith.nope_xyz',
    reason: 'FAILED: SemanticException [Error 10001]: Table not found agriffith.nope_xyz',
    showsEngineText: false
  },
  {
    name: 'missing schema',
    sql: 'SELECT * FROM nodb.t',
    reason: "SCHEMA_NOT_FOUND: line 1:15: Schema 'awsdatacatalog.nodb' does not exist",
    showsEngineText: true
  }
];

describe('every captured production failure reaches a sentence the user can act on', () => {
  it.each(CAPTURED.map((c) => [c.name, c.reason] as const))('%s', (_name, reason) => {
    const {message} = toUserMessage({code: 'FAILED', message: reason});

    expect(message).not.toMatch(/Contact the Administrator/i);
  });

  it('never leaks the engine text into the SENTENCE, whatever the rule chose', () => {
    // The sentences are authored; Athena's own words reach the reader only through `detail`,
    // behind a disclosure. A rule that passed the raw reason through as its message would still
    // satisfy the assertion above, so the corpus checks both halves.
    for (const {name, reason} of CAPTURED) {
      expect(toUserMessage({code: 'FAILED', message: reason}).message, name).not.toContain(reason);
    }
  });

  it.each(CAPTURED.filter((c) => c.showsEngineText).map((c) => [c.name, c.reason] as const))(
    'shows Athena its own words for %s',
    (_name, reason) => {
      // The observable consequence of a class being on the user-SQL allowlist. Without this the
      // corpus cannot see a class dropping off it: the message then falls to the syntax
      // catch-all, which calls a type mismatch a typo but is not the generic sentence.
      expect(toUserMessage({code: 'FAILED', message: reason}).detail).toBeDefined();
    }
  );

  it.each(CAPTURED.filter((c) => !c.showsEngineText).map((c) => [c.name, c.reason] as const))(
    'shows no engine text for %s, which carries no error class',
    (_name, reason) => {
      expect(toUserMessage({code: 'FAILED', message: reason}).detail).toBeUndefined();
    }
  );

  it('tells the two table failures apart from the one that means a missing prefix', () => {
    // The advice "add a database to each table" is true of exactly one shape, and these are the
    // near neighbours it was wrongly offered for.
    for (const name of ['missing table, qualified', 'INSERT into a missing table', 'DROP a missing table']) {
      const {reason} = CAPTURED.find((c) => c.name === name)!;

      expect(toUserMessage({code: 'FAILED', message: reason}).message, name).not.toBe(
        'Add a database to each table, like `mydb.sales`.'
      );
    }
  });
});
