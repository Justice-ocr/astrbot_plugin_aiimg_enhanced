import {
  cp,
  mkdir,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { artifactDigests, sourceDigest } from "./studio_integrity.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(scriptDir, "..");
const source = path.join(root, "web", "dist");
const pages = path.join(root, "pages");
const target = path.join(pages, "Studio");
const temporary = path.join(pages, ".Studio.next");
const backup = path.join(pages, ".Studio.previous");

function assertChild(parent, child) {
  const relative = path.relative(parent, child);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("Refusing to modify path outside pages: " + child);
  }
}

async function exists(filePath) {
  try {
    await stat(filePath);
    return true;
  } catch {
    return false;
  }
}

assertChild(pages, target);
assertChild(pages, temporary);
assertChild(pages, backup);

if (!(await exists(path.join(source, "index.html")))) {
  throw new Error("web/dist is missing; run npm --prefix web run build first");
}

await mkdir(pages, { recursive: true });
await rm(temporary, { recursive: true, force: true });
await rm(backup, { recursive: true, force: true });
await cp(source, temporary, { recursive: true });

const indexPath = path.join(temporary, "index.html");
const html = await readFile(indexPath, "utf8");
const portableHtml = html.replaceAll('="/assets/', '="./assets/');
await writeFile(indexPath, portableHtml, "utf8");
await writeFile(path.join(temporary, ".studio-integrity.json"), JSON.stringify({
  source: await sourceDigest(root),
  files: await artifactDigests(temporary),
}, null, 2), "utf8");

if (await exists(target)) {
  await rename(target, backup);
}

try {
  await rename(temporary, target);
  await rm(backup, { recursive: true, force: true });
} catch (error) {
  if (await exists(backup)) {
    await rm(target, { recursive: true, force: true });
    await rename(backup, target);
  }
  throw error;
}

console.log("Studio build installed at " + target);
