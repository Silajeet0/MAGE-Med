import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    exclude: ["**/*.smoke.test.ts", "**/node_modules/**", "**/dist/**"],
  },
});
