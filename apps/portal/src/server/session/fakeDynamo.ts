import 'server-only';
import {
  ConditionalCheckFailedException,
  DeleteItemCommand,
  GetItemCommand,
  PutItemCommand,
  UpdateItemCommand,
  type AttributeValue
} from '@aws-sdk/client-dynamodb';
import type {DynamoSend} from './store';

type Item = Record<string, AttributeValue>;

/** A recorded command, for assertions on exactly what the adapter sent. */
export type SentCommand = {name: string; input: Record<string, unknown>};

/**
 * An in-memory DynamoDB table that evaluates condition expressions as DynamoDB does. Tests only:
 * the suites run the real adapter on it, so what they prove is the adapter's condition.
 *
 * Two DynamoDB behaviours matter to the session store and both are reproduced: a comparison on a
 * missing attribute is false, and an `UpdateItem` with no condition creates the item it updates.
 * A condition this double does not understand throws, so it can never quietly evaluate something
 * the real service would evaluate differently.
 *
 * `beforeUpdate` runs inside an `UpdateItem`, after the caller's read and before the condition is
 * evaluated, which is where a test forces a racing write or a sign-out.
 */
export function fakeDynamo(): {
  send: DynamoSend;
  table: Map<string, Item>;
  sent: SentCommand[];
  beforeUpdate: {hook?: () => Promise<void>};
} {
  const table = new Map<string, Item>();
  const sent: SentCommand[] = [];
  const beforeUpdate: {hook?: () => Promise<void>} = {};

  const key = (input: {Key?: Item}) => input.Key?.pk?.S ?? '';

  function holds(condition: string | undefined, input: UpdateItemCommand['input'], item: Item | undefined): boolean {
    if (condition === undefined) return true;
    const names = input.ExpressionAttributeNames ?? {};
    const values = input.ExpressionAttributeValues ?? {};
    return condition.split(' AND ').every((clause) => {
      const exists = /^attribute_exists\((#\w+)\)$/.exec(clause.trim());
      if (exists) return item !== undefined && names[exists[1]] in item;
      const equals = /^(#\w+) = (:\w+)$/.exec(clause.trim());
      if (equals) {
        const actual = item?.[names[equals[1]]];
        const expected = values[equals[2]];
        return actual !== undefined && JSON.stringify(actual) === JSON.stringify(expected);
      }
      throw new Error(`fakeDynamo cannot evaluate the clause ${JSON.stringify(clause)}`);
    });
  }

  const send: DynamoSend = async (command) => {
    sent.push({name: command.constructor.name, input: command.input as unknown as Record<string, unknown>});
    if (command instanceof GetItemCommand) {
      const item = table.get(key(command.input));
      return {Item: item ? structuredClone(item) : undefined};
    }
    if (command instanceof PutItemCommand) {
      const item = structuredClone(command.input.Item ?? {});
      table.set(item.pk?.S ?? '', item);
      return {};
    }
    if (command instanceof DeleteItemCommand) {
      table.delete(key(command.input));
      return {};
    }
    if (command instanceof UpdateItemCommand) {
      await beforeUpdate.hook?.();
      const pk = key(command.input);
      const current = table.get(pk);
      if (!holds(command.input.ConditionExpression, command.input, current)) {
        throw new ConditionalCheckFailedException({message: 'The conditional request failed', $metadata: {}});
      }
      const names = command.input.ExpressionAttributeNames ?? {};
      const values = command.input.ExpressionAttributeValues ?? {};
      const next: Item = {...(current ?? {pk: {S: pk}})};
      for (const assignment of (command.input.UpdateExpression ?? '').replace(/^SET /, '').split(', ')) {
        const [name, value] = assignment.split(' = ');
        next[names[name]] = values[value];
      }
      table.set(pk, next);
      return {};
    }
    throw new Error('fakeDynamo received a command it does not model');
  };

  return {send, table, sent, beforeUpdate};
}
