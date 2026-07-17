import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Single source of truth for the displayed version: package.json "version".
// Bump it there (and the matching tauri.conf.json / Cargo.toml) for a new release.
const APP_VERSION = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf-8"),
).version;

// Tauri serves on a fixed port and reads the dist output from ../dist.
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  plugins: [svelte()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      // Don't watch the Rust side from Vite.
      ignored: ["**/src-tauri/**", "**/legacy/**"],
    },
  },
  build: {
    // One HTML entry point per window (hub + floating cards + dictation pill).
    rollupOptions: {
      input: {
        main: "index.html",
        cards: "cards.html",
        dictate: "dictate.html",
      },
    },
  },
});
