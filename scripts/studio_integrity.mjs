import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

async function filesUnder(root, base = root) {
  const result = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const absolute = path.join(root, entry.name);
    if (entry.isDirectory()) result.push(...await filesUnder(absolute, base));
    else if (entry.isFile()) result.push(path.relative(base, absolute).replaceAll("\\", "/"));
  }
  return result.sort();
}

async function hashFile(filename) {
  return createHash("sha256").update(await readFile(filename)).digest("hex");
}

export async function sourceDigest(root) {
  const hash = createHash("sha256");
  const files = [
    ...(await filesUnder(path.join(root, "web", "src"))).map((name) => `web/src/${name}`),
    "web/package.json",
    "web/package-lock.json",
    "web/pnpm-lock.yaml",
    "web/tsconfig.json",
    "web/vite.studio.config.ts",
    "scripts/build_studio.mjs",
  ];
  for (const name of files.sort()) {
    hash.update(name).update("\0").update(await readFile(path.join(root, name))).update("\0");
  }
  return hash.digest("hex");
}

export async function artifactDigests(folder) {
  const result = {};
  for (const name of await filesUnder(folder)) {
    if (name === ".studio-integrity.json") continue;
    result[name] = await hashFile(path.join(folder, name));
  }
  return result;
}
