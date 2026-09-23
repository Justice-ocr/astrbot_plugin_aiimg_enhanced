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
const bundle = path.join(root, "dist-studio");
const pages = path.join(root, "pages");
const target = path.join(pages, "Settings");
const temporary = path.join(pages, ".Settings.next");
const backup = path.join(pages, ".Settings.previous");

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
for (const name of ["studio.js", "studio.css"]) {
  if (!(await exists(path.join(bundle, name)))) {
    throw new Error(`dist-studio/${name} is missing; run npm --prefix web run build first`);
  }
}

await mkdir(pages, { recursive: true });
await rm(temporary, { recursive: true, force: true });
await rm(backup, { recursive: true, force: true });
await cp(source, temporary, { recursive: true });

const indexPath = path.join(temporary, "index.html");
let html = await readFile(indexPath, "utf8");
html = html
  .replace(/\s*<link\b(?=[^>]*\brel=["']stylesheet["'])[^>]*>/gi, "")
  .replace(/\s*<script\b(?=[^>]*\btype=["']module["'])[^>]*>[\s\S]*?<\/script>/gi, "");
if (!html.includes("</head>") || !html.includes("</body>")) {
  throw new Error("Astro output is missing the expected head/body tags");
}
html = html
  .replace("</head>", '  <link rel="stylesheet" href="./assets/studio.css">\n  </head>')
  .replace("</body>", '    <script src="./assets/studio.js"></script>\n  </body>');
await rm(path.join(temporary, "_astro"), { recursive: true, force: true });
const assets = path.join(temporary, "assets");
await rm(assets, { recursive: true, force: true });
await mkdir(assets, { recursive: true });
await cp(path.join(bundle, "studio.js"), path.join(assets, "studio.js"));
await cp(path.join(bundle, "studio.css"), path.join(assets, "studio.css"));
await writeFile(indexPath, html, "utf8");
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
