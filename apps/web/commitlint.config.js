import { createRequire } from 'module';
const require = createRequire(import.meta.url);

/** @type {import('commitlint').UserConfig} */
export default {
  extends: ['@commitlint/config-conventional', 'commitlint-plugin-workspace-scopes'],
  rules: {
    'type-enum': [
      2,
      'always',
      [
        'feat',
        'fix',
        'perf',
        'refactor',
        'docs',
        'test',
        'chore',
        'ci',
        'build',
        'style',
        'revert'
      ]
    ],
    'scope-enum': [2, 'always', ['web', 'api', 'shared', 'docs', 'prd', 'tooling', 'release']],
    'scope-case': [2, 'always', 'lower-case'],
    'subject-case': [2, 'always', 'lower-case'],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],
    'subject-max-length': [2, 'always', 72],
    'body-leading-blank': [2, 'always'],
    'body-max-line-length': [2, 'always', 100],
    'footer-leading-blank': [2, 'always'],
    'footer-max-line-length': [2, 'always', 100],
    'header-max-length': [2, 'always', 72]
  },
  ignores: [
    'Merge pull request',
    'Merge remote-tracking branch',
    'Revert "',
    'chore(release):'
  ]
};