// ESLint 9 flat config, replacing .eslintrc.cjs.
//
// ESLint 9 no longer reads .eslintrc by default and v10 drops it entirely, so
// eslint-plugin-react-refresh >= 0.5 (peer: eslint ^9 || ^10) could not be
// installed while this project stayed on eslint 8.
//
// A direct translation of the old config — same rules, same severities, same
// ignores — verified by diffing `eslint -f json` output against eslint 8:
// identical, 6 react-refresh warnings and 0 errors.
import js from '@eslint/js'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import prettier from 'eslint-config-prettier'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

export default [
  // Was `ignorePatterns`. Flat config needs no `root`: a config file is the root.
  { ignores: ['dist', 'node_modules', 'playwright-report', 'e2e/**'] },

  js.configs.recommended, // was 'eslint:recommended'

  // Was 'plugin:@typescript-eslint/recommended'. The plugin's own flat config
  // is used rather than spreading `configs.recommended.rules` by hand: that
  // would silently drop the `eslint-recommended` overrides, which switch OFF
  // core rules TypeScript already enforces — notably `no-undef`, which
  // otherwise reports "'React' is not defined" on every .tsx file.
  ...tsPlugin.configs['flat/recommended'],

  {
    files: ['src/**/*.{ts,tsx}'],
    // Was 'plugin:react-hooks/recommended'. The flat configs moved in v7: they
    // now live under `configs.flat[...]`, while the top-level `recommended` and
    // `recommended-latest` are BOTH eslintrc-shaped (`plugins` as an array),
    // which flat config rejects with
    // `Key "plugins": Key "0": Expected an object`.
    //
    // v7 brings the React Compiler rule set — 16 rules, up from v5's two
    // (rules-of-hooks, exhaustive-deps).
    plugins: {
      ...reactHooks.configs.flat.recommended.plugins,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.flat.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },

  // Must stay last: turns off stylistic rules that conflict with Prettier.
  prettier,
]
