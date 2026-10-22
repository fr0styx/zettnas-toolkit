// ESLint for the frontend (OPS-24). Correctness rules are errors; unused code is a warning.
import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['static/**', 'node_modules/**', 'frontend/src/__tests__/**', 'coverage/**'] },
  js.configs.recommended,
  {
    files: ['frontend/**/*.{js,mjs}', '*.mjs'],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      'no-unused-vars': ['warn', { args: 'none', caughtErrors: 'none', ignoreRestSiblings: true }],
      'no-empty': ['error', { allowEmptyCatch: true }],
      // terminal and ANSI handling needs control characters in regexes
      'no-control-regex': 'off',
    },
  },
];
