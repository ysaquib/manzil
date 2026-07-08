import js from "@eslint/js";
import tseslint from "typescript-eslint";

// Flat config (ESLint 9). Frontend lint job from Phase 1 (IMPLEMENTATION §2).
export default tseslint.config(
  { ignores: ["dist", "src/lib/generated"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2022, sourceType: "module" },
  },
);
