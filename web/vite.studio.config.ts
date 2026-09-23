import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  base: "./",
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    outDir: "../dist-studio",
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
    lib: {
      entry: "src/app/client.tsx",
      name: "AIIMGStudio",
      formats: ["iife"],
      fileName: () => "studio.js",
      cssFileName: "studio",
    },
  },
});
