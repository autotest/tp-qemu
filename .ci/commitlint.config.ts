import type {UserConfig} from '@commitlint/types';

const Configuration: UserConfig = {
  /*
   * Resolve and load @commitlint/config-conventional from node_modules.
   * Referenced packages must be installed
   */
  extends: ['@commitlint/config-conventional'],
  /*
   * Resolve and load @commitlint/format from node_modules.
   * Referenced package must be installed
   */
  formatter: '@commitlint/format',
  /*
   * Any rules defined here will override rules from @commitlint/config-conventional
   */
  rules: {
    "body-full-stop": [0, "never", '.'],
    "body-leading-blank": [2, "always"],
    "body-empty": [0, "never"],
    "body-min-length": [0, "always", 1],
    "body-case": [0, "always", "lower-case"],
    "footer-leading-blank": [2, "always"],
    "footer-empty": [0, "never"],
    "footer-max-length": [0, "always", 72],
    "header-case": [0, "always", "lower-case"],
    "header-full-stop": [2, "never", "."],
    "header-max-length": [2, "always", 72],
    "header-min-length": [2, "always", 1],
    "references-empty": [0, "never"],
    "scope-case": [0, "always", "lower-case"],
    "subject-case": [0, "always", "lower-case"],
    "subject-empty": [0, "never"],
    "subject-full-stop": [2, "never", "."],
    "signed-off-by": [2, "always", "Signed-off-by:"],
    /*
    * Enable type if we need, warn it currently.
    */
    "type-enum": [0, "always", ['ci', 'docs', 'feat', 'fix', 'perf', 'refactor', 'revert', 'rfe', 'style']],
    "type-case": [0, "always", "lower-case"],
    "type-empty": [0, "never"],
    "trailer-exists": [2, "always", "Signed-off-by:"]
  },
  /*
   * Functions that return true if commitlint should ignore the given message.
   */
  ignores: [(commit) => commit === ''],
  /*
   * Whether commitlint uses the default ignore rules.
   */
  defaultIgnores: true,
  /*
   * Custom URL to show upon failure
   */
  helpUrl:
    'https://avocado-framework.readthedocs.io/en/latest/guides/contributor/chapters/styleguides.html#commit-style-guide',
  /*
   * Custom prompt configs
   */
  prompt: {
    messages: {},
    questions: {
      type: {
        description: 'please input type:',
      },
    },
  },
};

module.exports = Configuration;
