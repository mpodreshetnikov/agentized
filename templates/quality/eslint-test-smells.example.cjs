/**
 * Optional ESLint starter for JS/TS test-smell warnings (mode=warn first).
 * Pair with quality-gates skill rules; do not duplicate a second skill.
 *
 * npm i -D eslint eslint-plugin-jest  (or vitest equivalent)
 */
module.exports = {
  overrides: [
    {
      files: ["**/*.{test,spec}.{js,jsx,ts,tsx}"],
      rules: {
        // Prefer real oracles over truthy/defined-only checks.
        "no-unused-expressions": "warn",
        // Discourage assert.ok / expect(x).toBeTruthy as sole oracle — enforce in review + skill.
        "jest/valid-expect": "warn",
      },
    },
  ],
};
