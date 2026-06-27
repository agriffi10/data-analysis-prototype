// prettier.config.js
export default {
  // Use 2 spaces per indentation level to keep deeply nested JSX readable
  tabWidth: 2,

  // Use spaces instead of tabs
  useTabs: false,

  // Enforce semicolons at the end of statements to avoid ASI edge cases
  semi: true,

  // Use single quotes for JavaScript strings (standard practice)
  singleQuote: true,

  // Keep double quotes for JSX attributes to match HTML standard convention
  jsxSingleQuote: false,

  // Print trailing commas wherever possible in ES5 (objects, arrays, etc.) for clean Git diffs
  trailingComma: 'es5',

  // Print spaces between brackets in object literals: { foo: bar }
  bracketSpacing: true,

  // Put the > of a multi-line HTML/JSX element at the end of the last line instead of a new line
  bracketSameLine: false,

  // Always include parentheses around arrow function arguments: (x) => x
  arrowParens: 'always',

  // Wrap lines that exceed 100 characters to keep code from horizontally scrolling
  printWidth: 120,

  // Maintain existing line endings (LF vs CRLF) across mixed OS teams
  endOfLine: 'auto',
};
