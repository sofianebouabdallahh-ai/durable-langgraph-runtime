import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist", "coverage", "src/api/schema.d.ts", "e2e"] },
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  reactHooks.configs.flat.recommended,
  {
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: { allowDefaultProject: ["*.config.js"] },
        tsconfigRootDir: new URL(".", import.meta.url).pathname,
      },
    },
    rules: {
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      // Untrusted content (G3): never inject HTML.
      "no-restricted-properties": ["error", { property: "innerHTML" }, { property: "outerHTML" }],
    },
  },
  { files: ["*.config.{js,ts}"], languageOptions: { globals: globals.node } },
  {
    // Tests may assert what they just built, and read markup to prove it is inert.
    files: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    rules: { "@typescript-eslint/no-non-null-assertion": "off", "no-restricted-properties": "off" },
  },
);
