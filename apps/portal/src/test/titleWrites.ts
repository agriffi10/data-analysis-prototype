import {afterEach, beforeEach} from 'vitest';

/**
 * Records every value written to `document.title` in each test of the calling file, in order,
 * through an accessor of the document's own over the prototype's, removed after each test. Call it
 * at the top of a test file.
 *
 * @returns The writes, emptied before each test.
 */
export function recordTitleWrites(): string[] {
  const writes: string[] = [];
  const title = Object.getOwnPropertyDescriptor(Document.prototype, 'title') as PropertyDescriptor;
  beforeEach(() => {
    writes.length = 0;
    Object.defineProperty(document, 'title', {
      configurable: true,
      get: () => title.get?.call(document) as string,
      set: (value: string) => {
        writes.push(value);
        title.set?.call(document, value);
      }
    });
  });
  afterEach(() => {
    Reflect.deleteProperty(document, 'title');
  });
  return writes;
}
